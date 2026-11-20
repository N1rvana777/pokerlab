"""Real Edge/state regression for delayed agent events and HTTP replies.

Configuration REST uses the actual isolated Solver server. Provider status and
agent events are controlled transport fixtures: no model, native solve or real
account request is made, and these tests do not establish inference acceptance.
"""
from contextlib import contextmanager
import threading
import time

import pytest

from pokerlab.solver.agent import SolverAgent
from pokerlab.solver.server import make_server


FETCH_CONTROL = r"""(() => {
  const realFetch = window.fetch.bind(window);
  const state = window.__agentRace = {
    realFetch, events: [], waiting: [], heldSnapshot: null,
    holdNextConfig: false, releaseHeld: null, released: false, fullReports: []
  };
  const json = value => new Response(JSON.stringify(value), {
    status: 200, headers: {'Content-Type':'application/json'}
  });
  state.deliver = value => {
    if (state.waiting.length) state.waiting.shift()(json(value));
    else state.events.push(json(value));
  };
  window.fetch = async (input, options={}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    const path = url.pathname;
    if (path === '/api/agent/status') return json({
      subscription:{mode:'siwc',logged_in:false,verified_models:[]},
      api:{configured:false,allow_paid:false,verified_models:[]}
    });
    if (path === '/api/agent/sessions') return json([]);
    if (path === '/api/agent/start') return json({
      id:'controlled-task',session_id:'controlled-session',status:'running',cursor:0,events:[]
    });
    if (path === '/api/agent/task') {
      if (state.events.length) return state.events.shift();
      return await new Promise(resolve => state.waiting.push(resolve));
    }
    if (path.startsWith('/api/jobs/')) { state.fullReports.push(path); return json({}); }
    if (path === '/api/resources') return json({
      ready:true,automatic_budget_mb:8192,
      windows:{available_mb:12288},wsl:{available_mb:8704}
    });
    if (path.startsWith('/api/agent/') && path !== '/api/agent/config')
      throw new Error('Unexpected provider request in a transport fixture: '+path);
    if (path === '/api/agent/config' && options.method === 'POST' && state.holdNextConfig) {
      state.holdNextConfig = false;
      const response = await realFetch(input, options);
      state.heldSnapshot = await response.clone().json();
      await new Promise(resolve => { state.releaseHeld = resolve; });
      state.released = true;
      return response;
    }
    return await realFetch(input, options);
  };
})();
"""


@contextmanager
def isolated_page(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    http = make_server(0, agent_dir=tmp_path / "agent", agent_factory=lambda jobs, data_dir:
        SolverAgent(jobs, data_dir=data_dir, auth_dir=tmp_path / "auth"))
    assert http.server_port not in (8765, 8770)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.add_init_script(FETCH_CONTROL)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{http.server_port}")
            playwright.expect(page.locator("#board")).to_have_value("9h 8h 2c")
            playwright.expect(page.locator("#solver-agent")).to_contain_text("当前局面已同步。")
            try:
                yield page, playwright
                assert errors == []
            finally:
                browser.close()
    finally:
        http.shutdown()
        http.server_close()
        http.jobs.close()
        thread.join(timeout=5)


def snapshot(page):
    return page.evaluate("async () => await (await __agentRace.realFetch('/api/agent/config')).json()")


def wait_for_state(page, predicate):
    # Playwright wait_for_function uses page eval, which this app's CSP forbids.
    # CDP evaluation preserves that CSP without changing production headers.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if page.evaluate(predicate):
            return
        time.sleep(0.02)
    pytest.fail(f"Controlled browser state did not become ready: {predicate}")


def observe_revisions(page):
    page.evaluate(r"""() => {
      const node=[...document.querySelectorAll('#solver-agent p')]
        .find(node=>node.textContent.startsWith('Solver配置版本 '));
      const revisions=__agentRace.visibleRevisions=[];
      const collect=text=>{const match=/Solver配置版本 (\d+)/.exec(text);
        if(match)revisions.push(Number(match[1]));};
      collect(node.textContent);
      __agentRace.observer=new MutationObserver(records=>{
        for(const record of records)for(const child of record.addedNodes)collect(child.textContent);
      });
      __agentRace.observer.observe(node,{childList:true});
    }""")


def assert_no_revision_rollback(page, minimum):
    # Inspect inserted text nodes as well as final text, so a synchronous
    # temporary downgrade followed by a refresh cannot pass unnoticed.
    revisions = page.evaluate("__agentRace.visibleRevisions")
    assert revisions and all(revision >= minimum for revision in revisions), revisions


def backend_patch(page, patch):
    return page.evaluate("""async patch => {
      const original = await (await __agentRace.realFetch('/api/agent/config')).json();
      const response = await __agentRace.realFetch('/api/agent/config', {
        method:'POST',headers:{'Content-Type':'application/json',
          'X-Pokerlab-Token':document.querySelector('meta[name=local-token]').content},
        body:JSON.stringify({patch,expected_revision:original.revision})
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error);
      return value;
    }""", patch)


def start_controlled_agent(page):
    panel = page.locator("#solver-agent")
    panel.get_by_label("Solver助手请求").fill("controlled state race; do not call a provider")
    panel.get_by_role("button", name="发送", exact=True).click()
    wait_for_state(page, "() => __agentRace.waiting.length > 0")


def deliver_update(page, value, *, final=True):
    page.evaluate("""value => __agentRace.deliver({
      id:'controlled-task',session_id:'controlled-session',status:value.final?'completed':'running',
      text:'controlled transport event',cursor:1,error:null,
      events:[{type:'tool_result',name:'update_solver_config',success:true,result:value.snapshot}]
    })""", {"snapshot": value, "final": final})


def test_late_tool_event_does_not_revert_autosaved_user_pot(tmp_path):
    with isolated_page(tmp_path) as (page, playwright):
        start_controlled_agent(page)
        delayed = backend_patch(page, {"pot": 21})
        # The new backend state is loaded before its queued event is delivered.
        page.locator("#solver-agent").get_by_role("button", name="载入后台局面", exact=True).click()
        playwright.expect(page.locator("#pot")).to_have_value("21")
        page.locator("#pot").fill("20")
        wait_for_state(page, """async () => {
          const value=await (await __agentRace.realFetch('/api/agent/config')).json();
          return value.config.pot===20 && value.revision>1;
        }""")
        saved = snapshot(page)
        playwright.expect(page.locator("#solver-agent")).to_contain_text(f"Solver配置版本 {saved['revision']}")
        observe_revisions(page)
        deliver_update(page, delayed)
        playwright.expect(page.locator("#solver-agent")).to_contain_text("请求状态：completed")
        playwright.expect(page.locator("#pot")).to_have_value("20")
        playwright.expect(page.locator("#solver-agent")).to_contain_text(f"Solver配置版本 {saved['revision']}")
        assert snapshot(page) == saved
        assert_no_revision_rollback(page, saved["revision"])


def test_a_result_event_loads_the_full_report_by_job(tmp_path):
    with isolated_page(tmp_path) as (page, playwright):
        start_controlled_agent(page)
        page.evaluate("""() => __agentRace.deliver({
          id:'controlled-task',session_id:'controlled-session',status:'completed',text:'done',cursor:1,error:null,
          events:[{type:'tool_result',name:'get_result',success:true,result:{job:{id:'abc'},result:{precision:{actual_chips:0}}}}]
        })""")
        wait_for_state(page, "() => __agentRace.fullReports.length > 0")
        assert page.evaluate("__agentRace.fullReports") == ["/api/jobs/abc/result"]


@pytest.mark.parametrize("unsent_edit", [False, True])
def test_late_post_reply_keeps_newer_event_and_unsent_edit(tmp_path, unsent_edit):
    with isolated_page(tmp_path) as (page, playwright):
        start_controlled_agent(page)
        page.evaluate("__agentRace.holdNextConfig=true")
        page.locator("#pot").fill("20")
        wait_for_state(page, "() => __agentRace.heldSnapshot !== null && __agentRace.releaseHeld !== null")
        held = page.evaluate("__agentRace.heldSnapshot")
        assert held["config"]["pot"] == 20
        newer = backend_patch(page, {"stack": 300})
        assert newer["revision"] > held["revision"]
        deliver_update(page, newer, final=False)
        playwright.expect(page.locator("#solver-agent")).to_contain_text(f"Solver配置版本 {newer['revision']}")
        observe_revisions(page)
        if unsent_edit:
            page.locator("#pot").fill("22")
        page.evaluate("__agentRace.releaseHeld()")
        wait_for_state(page, "() => __agentRace.released")
        playwright.expect(page.locator("#solver-agent")).to_contain_text(f"Solver配置版本 {newer['revision']}")
        if unsent_edit:
            playwright.expect(page.locator("#pot")).to_have_value("22")
            playwright.expect(page.locator("#solver-agent")).to_contain_text("请点击“同步当前局面”确认当前输入。")
            # The newer remote event must not silently submit the pending 22.
            assert snapshot(page) == newer
            page.locator("#solver-agent").get_by_role("button", name="同步当前局面", exact=True).click()
            wait_for_state(page, """async () => {
              const value=await (await __agentRace.realFetch('/api/agent/config')).json();
              return value.config.pot===22;
            }""")
        else:
            playwright.expect(page.locator("#pot")).to_have_value("20")
            playwright.expect(page.locator("#stack")).to_have_value("300")
            assert snapshot(page) == newer
        assert_no_revision_rollback(page, newer["revision"])


def test_result_identity_includes_model_and_units_but_not_resource_caps(tmp_path):
    with isolated_page(tmp_path) as (page, _):
        result = page.evaluate("""() => {
          const base=getConfig('fixed');
          const compare=patch=>sameSolverInputs(base,{...structuredClone(base),...patch});
          const empty={...base,raises:['','',''],profile:{traits:[]}},omitted={...empty};delete omitted.raises;
          return {
            traits:compare({profile:{traits:[{kind:'station',strength:2,streets:[3]}],overrides:[]}}),
            locks:compare({profile:{traits:[],overrides:[{path:[0],combo:'AsAh',probabilities:[1,0]}]}}),
            mode:compare({mode:'equilibrium'}),unit:compare({amount_unit:'chips'}),
            memory:compare({memory_budget_mb:128}),automatic:compare({memory_auto:false}),
            time:compare({time_limit_seconds:5}),threads:compare({threads:1}),
            emptyRaises:sameSolverInputs(empty,omitted),
            emptyOverrides:sameSolverInputs(empty,{...empty,profile:{traits:[],overrides:[]}})
          };
        }""")
        assert result == {
            "traits": False, "locks": False, "mode": False, "unit": False,
            "memory": True, "automatic": True, "time": True, "threads": True,
            "emptyRaises": True, "emptyOverrides": True,
        }
