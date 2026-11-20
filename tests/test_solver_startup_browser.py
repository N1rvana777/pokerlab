"""Delayed first-load regression; real config REST, no solver/provider request.

Resource/status responses are UI fixtures. These checks do not establish native
solver correctness or live-memory availability.
"""
from contextlib import contextmanager
import json
import threading
import time

import pytest

from pokerlab.solver.__main__ import ROOT
from pokerlab.solver.agent import SolverAgent
from pokerlab.solver.server import make_server


BOOT_CONTROL = r"""(() => {
  const realFetch=window.fetch.bind(window);
  const state=window.__bootCheck={release:null,fail:false,holdConfig:false,releaseConfig:null,configGets:0,configPosts:0,solverRequests:0};
  const json=(value,status=200)=>new Response(JSON.stringify(value),{
    status,headers:{'Content-Type':'application/json'}
  });
  window.fetch=async(input,options={})=>{
    const path=new URL(typeof input==='string'?input:input.url,location.href).pathname;
    if(path==='/api/examples'){
      const response=await realFetch(input,options);
      return await new Promise(resolve=>{state.release=()=>resolve(state.fail?json({error:'controlled example failure'},500):response)});
    }
    if(path==='/api/resources')return json({ready:false,error:'UI-only startup fixture'});
    if(path==='/api/agent/status')return json({subscription:{mode:'siwc',logged_in:false},api:{configured:false,allow_paid:false}});
    if(path==='/api/agent/sessions')return json([]);
    if(path==='/api/agent/config'){
      if(options.method==='POST')state.configPosts++;else state.configGets++;
      if(options.method!=='POST'&&state.holdConfig){
        state.holdConfig=false;
        const response=await realFetch(input,options);
        return await new Promise(resolve=>{state.releaseConfig=()=>resolve(response)});
      }
    }else if(path.startsWith('/api/agent/'))throw Error('Unexpected provider request');
    if(path.startsWith('/api/jobs')){state.solverRequests++;throw Error('Native jobs forbidden in startup test');}
    return await realFetch(input,options);
  };
})();"""


def wait_for_release(page, name='release'):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if page.evaluate(f'typeof __bootCheck.{name} === "function"'):
            return
        time.sleep(.02)
    pytest.fail(f'Request did not reach the controlled {name} response gate')


@contextmanager
def startup_page(tmp_path):
    playwright=pytest.importorskip('playwright.sync_api')
    server=make_server(0,agent_dir=tmp_path/'agent',agent_factory=lambda jobs,data_dir:
        SolverAgent(jobs,data_dir=data_dir,auth_dir=tmp_path/'auth'))
    server.solver_agent.update(patch={'target':.125,'target_unit':'chips'},expected_revision=0)
    original=server.solver_agent.state_file.read_bytes()
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            try:
                page=browser.new_page()
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.add_init_script(BOOT_CONTROL)
                page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='domcontentloaded')
                wait_for_release(page)
                yield page,playwright.expect,server,original
                assert errors==[]
                assert page.evaluate('__bootCheck.solverRequests')==0
            finally:
                browser.close()
    finally:
        server.shutdown();server.server_close();server.jobs.close();thread.join(5)


def test_slow_examples_wait_for_real_ready_and_keep_saved_precision(tmp_path):
    with startup_page(tmp_path) as (page,expect,server,original):
        for selector in ('#example','#load-example','#new-scene'):
            expect(page.locator(selector)).to_be_disabled()
        # Deliberately cross the removed five-second heuristic. No initial
        # restoration may race ahead of this unresolved examples request.
        time.sleep(5.2)
        assert page.evaluate('__bootCheck.configGets')==0
        assert page.evaluate('__bootCheck.configPosts')==0
        assert server.solver_agent.state_file.read_bytes()==original
        page.evaluate('__bootCheck.release()')
        expect(page.locator('#solver-agent')).to_contain_text('当前局面已同步')
        expect(page.locator('#target')).to_have_value('0.125')
        expect(page.locator('#unit')).to_have_value('chips')
        assert page.evaluate('__bootCheck.configPosts')==0
        assert server.solver_agent.state_file.read_bytes()==original
        expect(page.locator('#new-scene')).to_be_enabled()
        page.locator('#new-scene').click()
        expect(page.locator('#target')).to_have_value('0.5')
        expect(page.locator('#unit')).to_have_value('pot_pct')


def test_failed_examples_restore_saved_scene_and_show_error(tmp_path):
    with startup_page(tmp_path) as (page,expect,server,original):
        page.evaluate('() => {__bootCheck.fail=true;__bootCheck.release()}')
        expect(page.locator('#solver-agent')).to_contain_text('示例载入失败')
        expect(page.locator('#target')).to_have_value('0.125')
        expect(page.locator('#unit')).to_have_value('chips')
        expect(page.locator('#board')).to_have_value('9h 8h 2c')
        expect(page.locator('#new-scene')).to_be_disabled()
        expect(page.locator('#load-example')).to_be_disabled()
        assert page.evaluate('__bootCheck.configPosts')==0
        assert server.solver_agent.state_file.read_bytes()==original


@pytest.mark.parametrize('examples_fail', [False, True])
def test_user_import_during_initial_load_is_not_replaced_by_default(tmp_path, examples_fail):
    with startup_page(tmp_path) as (page,expect,server,original):
        config=json.loads((ROOT/'examples/flop_research_raises.json').read_text())
        config.update(target=.27,target_unit='pot_pct',amount_unit='bb',pot=20)
        page.locator('#import-config').set_input_files({
            'name':'explicit-study.json','mimeType':'application/json',
            'buffer':json.dumps(config).encode()
        })
        expect(page.locator('#target')).to_have_value('0.27')
        page.evaluate('fail => {__bootCheck.fail=fail;__bootCheck.release()}', examples_fail)
        expect(page.locator('#solver-agent')).to_contain_text('表单有新编辑，已保留')
        expect(page.locator('#target')).to_have_value('0.27')
        expect(page.locator('#unit')).to_have_value('pot_pct')
        expect(page.locator('#pot')).to_have_value('20')
        assert page.evaluate('__bootCheck.configPosts')==0
        assert server.solver_agent.state_file.read_bytes()==original


@pytest.mark.parametrize('edit_method', ['input', 'programmatic'])
def test_edit_while_first_config_get_waits_is_kept_without_early_post(tmp_path, edit_method):
    with startup_page(tmp_path) as (page,expect,server,original):
        page.evaluate('() => {__bootCheck.holdConfig=true;__bootCheck.release()}')
        wait_for_release(page, 'releaseConfig')
        if edit_method=='input':
            page.locator('#target').fill('0.31')
            page.locator('#pot').fill('20')
        else:
            # Uses the same configuration path as an import, with no trusted DOM
            # input event to hide reliance on event.isTrusted.
            page.evaluate('() => setConfig({...getConfig(),target:.31,pot:20})')
        expect(page.locator('#target')).to_have_value('0.31')
        time.sleep(.3)  # Cross the autosave debounce while no revision exists.
        assert page.evaluate('__bootCheck.configPosts')==0
        expect(page.locator('.solver-agent-error')).to_be_empty()
        assert server.solver_agent.state_file.read_bytes()==original
        page.evaluate('__bootCheck.releaseConfig()')
        expect(page.locator('#solver-agent')).to_contain_text('表单有新编辑，已保留')
        expect(page.locator('#target')).to_have_value('0.31')
        expect(page.locator('#pot')).to_have_value('20')
        assert page.evaluate('__bootCheck.configPosts')==0
        assert server.solver_agent.state_file.read_bytes()==original
        # Explicitly syncing is the first write and uses the actual revision.
        page.locator('#solver-agent').get_by_role('button',name='同步当前局面',exact=True).click()
        expect(page.locator('#solver-agent')).to_contain_text('当前局面已同步')
        saved=json.loads(server.solver_agent.state_file.read_text(encoding='utf-8'))
        assert saved['config']['target']==.31
        assert saved['config']['pot']==20
        assert page.evaluate('__bootCheck.configPosts')==1
        expect(page.locator('.solver-agent-error')).to_be_empty()
