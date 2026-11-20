"""Real browser and native engine: locks, profiles and the study views on small spots."""
import os
import re
import threading
import time

import pytest

from pokerlab.solver.server import make_server

pytestmark=pytest.mark.skipif(os.environ.get('POKERLAB_BROWSER')!='1',reason='opt-in browser/native E2E')


@pytest.fixture
def page(tmp_path):
    playwright=pytest.importorskip('playwright.sync_api')
    server=make_server(0,agent_dir=tmp_path/'agent')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    errors=[]
    try:
        with playwright.sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            tab=browser.new_page(viewport={'width':1500,'height':1000})
            tab.on('pageerror',lambda e:errors.append(str(e)))
            tab.goto(f'http://127.0.0.1:{server.server_port}/')
            deadline=time.time()+60
            while tab.locator('#load-example').is_disabled():
                assert time.time()<deadline
                time.sleep(.05)
            yield tab
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join();server.jobs.close() if hasattr(server,'jobs') else None
    assert errors==[]


def scene(page,board,oop,ip,pot='100',stack='100',river='100%'):
    page.evaluate('''([board,oop,ip,pot,stack,river])=>{
      $('amount-unit').value='bb';refreshAmountUnit();$('board').value=board;$('pot').value=pot;$('stack').value=stack;
      $('range0').value=oop;$('range1').value=ip;$('bet3').value='';$('bet4').value=river;$('bet5').value=river;
      for(const s of [3,4,5])$('raise'+s).value='';
      $('separate-sizes').checked=true;for(const s of [3,4,5]){$('ip-bet'+s).value='';$('ip-raise'+s).value=''}
      $('target').value='0.05';$('iterations').value='5000';$('threads').value='4';overrides=[];
      $('board').dispatchEvent(new Event('input',{bubbles:true}));updateTreeControls();changed();refreshEditors();
    }''',[board,oop,ip,pot,stack,river])


def until(page,condition,timeout=120):
    """The page's script policy rules out wait_for_function, which evaluates strings inside the page."""
    deadline=time.time()+timeout
    while not page.evaluate(f'!!({condition})'):
        error=page.locator('#error').inner_text()
        assert not error,error
        assert time.time()<deadline,condition
        time.sleep(.1)


def done(page):
    from playwright.sync_api import expect
    expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
    expect(page.locator('#error')).to_be_empty()


def river(page):
    scene(page,'Ks Qd 7c 3s 2s','7h7d,5h4h','AcQc')


def test_study_tabs_and_compare_modes(page):
    from playwright.sync_api import expect
    river(page)
    page.locator('#baseline').click();until(page,"result&&node&&!node.chance");done(page)
    # Blockers: the actor's frequency changes when the other seat holds a card.
    page.locator('#node-tabs [data-tab=blockers]').click()
    expect(page.locator('#blocker-table tr[data-card="7h"] td').nth(0)).to_have_text('7h')
    assert page.locator('#blocker-table tr[data-card]').count()==47
    # With 7h gone from OOP's range the value hand disappears, so OOP bets less often.
    bet_column=page.evaluate("node.actions.findIndex(a=>a.startsWith('Bet')||a.startsWith('AllIn'))")
    assert float(page.locator('#blocker-table tr[data-card="7h"] td').nth(bet_column+1).inner_text())<0
    page.locator('#node-tabs [data-tab=breakdown]').click()
    expect(page.locator('#breakdown-table')).to_contain_text('EQ buckets - Simple')
    page.locator('#node-tabs [data-tab=ranges]').click()
    expect(page.locator('#node-range-panels [data-seat="1"]')).to_contain_text('IP · 1.0 组合')
    expect(page.locator('#bucket-table')).to_be_visible()
    # Compare EV: betting against checking.
    page.locator('#grid-modes [data-mode=compare]').click()
    expect(page.locator('#compare-bar')).to_be_visible()
    page.locator('#compare-first').select_option(str(bet_column))
    page.locator('#compare-second').select_option(str(1-bet_column))
    expect(page.locator('#grid [data-hand="77"] .cell-value')).not_to_have_text('')
    assert float(page.locator('#grid [data-hand="77"] .cell-value').inner_text())>0
    page.locator('#compare-second').select_option('best')
    assert float(page.locator('#grid [data-hand="77"] .cell-value').inner_text())==pytest.approx(0,abs=.01)
    page.locator('#grid-modes [data-mode=range]').click()
    assert 'no-repeat' in page.locator('#grid [data-hand="77"]').evaluate('e=>e.style.background')
    # Value and trash removal arrive with the combo table.
    expect(page.locator('#combos thead')).to_contain_text('Value removal')


def test_frequency_lock_and_locked_solve(page):
    from playwright.sync_api import expect
    river(page)
    page.locator('#baseline').click();until(page,"result&&node&&!node.chance");done(page)
    page.locator('#actions button').filter(has_text=re.compile('Bet|AllIn')).click()
    until(page,"node&&node.actor===1");done(page)
    expect(page.locator('#freq-inputs input')).to_have_count(2)
    page.locator('#freq-inputs input').nth(0).fill('0')
    page.locator('#freq-inputs input').nth(1).fill('100')
    page.locator('#freq-apply').click()
    expect(page.locator('#freq-note')).to_contain_text('已为 1 个组合生成节点锁')
    page.locator('#locked-solve').click()
    until(page,"result&&result.config.mode==='locked'");done(page)
    expect(page.locator('#summary')).to_contain_text('锁定 1 个组合后双方重新求解')
    # OOP stops bluffing into a seat that always calls.
    frequency=page.evaluate("""()=>{const p=node.players[0],i=p.combos.indexOf('5h4h'),a=node.actions.findIndex(x=>x.startsWith('Bet')||x.startsWith('AllIn'));return node.strategy_action_major[a*p.combos.length+i]}""")
    assert frequency==pytest.approx(0,abs=.02)
    page.locator('#actions button').filter(has_text=re.compile('Bet|AllIn')).click()
    until(page,"node&&node.actor===1&&comparison");done(page)
    expect(page.locator('#lock-compare')).to_contain_text('锁定前')
    assert page.locator('#lock-compare tr').nth(2).locator('td').nth(2).inner_text()=='100.0%'


def test_player_profile_reaches_the_engine(page):
    from playwright.sync_api import expect
    river(page)
    page.locator('#player-profile').select_option('station')
    expect(page.locator('#incentive-call')).to_have_value('6')
    assert page.evaluate("getConfig('fixed').profile.incentives")=={'bet':-3,'check':2,'call':6}
    assert 'incentives' not in page.evaluate("getConfig('equilibrium').profile")
    page.locator('#response').click()
    until(page,"result&&result.config.mode==='fixed'");done(page)
    expect(page.locator('#summary')).to_contain_text('Player Profile')
    assert page.evaluate("result.precision.baseline_metric")=='other_seat_response_gap'
    # A saved config brings the profile back.
    page.evaluate("setConfig({...getConfig('fixed'),profile:{traits:[],incentives:{fold:7,check:2,bet:-3}}})")
    expect(page.locator('#player-profile')).to_have_value('nit')


def test_profile_street_choice_reaches_the_engine(page):
    from playwright.sync_api import expect
    river(page)
    page.locator('#player-profile').select_option('fish')
    assert 'streets' not in page.evaluate("getConfig('preview').profile.incentives")
    page.locator('#profile-street').select_option('first')
    assert page.evaluate("getConfig('preview').profile.incentives")=={'check':-6,'call':4,'streets':[5]}
    page.locator('#preview').click()
    until(page,"result&&result.config.mode==='preview'");done(page)
    expect(page.locator('#summary')).to_contain_text('只作用于这一街')
    # A saved config brings the street choice and the profile back.
    page.evaluate("setConfig({...getConfig('preview'),profile:{traits:[],incentives:{check:-6,call:4}}})")
    expect(page.locator('#player-profile')).to_have_value('fish')
    expect(page.locator('#profile-street')).to_have_value('all')
    page.evaluate("setConfig({...getConfig('preview'),profile:{traits:[],incentives:{check:-6,call:4,streets:[5]}}})")
    expect(page.locator('#player-profile')).to_have_value('fish')
    expect(page.locator('#profile-street')).to_have_value('first')


def test_locked_solve_can_keep_the_upstream_baseline(page):
    from playwright.sync_api import expect
    river(page)
    page.locator('#baseline').click();until(page,"result&&node&&!node.chance");done(page)
    bluff="""()=>{const p=node.players[0],i=p.combos.indexOf('5h4h'),a=node.actions.findIndex(x=>x.startsWith('Bet')||x.startsWith('AllIn'));return node.strategy_action_major[a*p.combos.length+i]}"""
    before=page.evaluate(bluff)
    page.locator('#actions button').filter(has_text=re.compile('Bet|AllIn')).click()
    until(page,"node&&node.actor===1");done(page)
    page.locator('#freq-inputs input').nth(0).fill('0')
    page.locator('#freq-inputs input').nth(1).fill('100')
    page.locator('#freq-apply').click()
    expect(page.locator('#freq-note')).to_contain_text('已为 1 个组合生成节点锁')
    page.locator('#lock-upstream').select_option('all')
    page.locator('#locked-solve').click()
    until(page,"result&&result.config.mode==='locked'");done(page)
    expect(page.locator('#summary')).to_contain_text('上游保持基线')
    # With the way here frozen OOP keeps bluffing into a seat that always calls.
    assert page.evaluate(bluff)==pytest.approx(before,abs=.001)
    # This seat has no node before the lock, so only the opponent's root is free and OOP stops bluffing.
    page.locator('#lock-upstream').select_option('player')
    page.locator('#baseline').click();until(page,"result&&result.config.mode==='equilibrium'");done(page)
    page.locator('#locked-solve').click()
    until(page,"result&&result.config.mode==='locked'");done(page)
    expect(page.locator('#summary')).not_to_contain_text('上游保持基线')
    assert page.evaluate(bluff)==pytest.approx(0,abs=.02)


def test_a_wide_lock_fits_the_request_limit(page):
    # Ranges from the preflop walk spell out every combo, and a frequency lock covers a whole node.
    from playwright.sync_api import expect
    cards=[r+s for r in 'AKQJT98765432' for s in 'shdc' if r+s not in ('Ks','Qd','7c','3s','2s')]
    combos=[a+b for at,a in enumerate(cards) for b in cards[at+1:]]
    scene(page,'Ks Qd 7c 3s 2s',','.join(c+':0.9876' for c in combos[:300]),','.join(c+':0.9876' for c in combos[300:800]))
    page.locator('#baseline').click();until(page,"result&&node&&!node.chance");done(page)
    page.locator('#actions button').filter(has_text=re.compile('Bet|AllIn')).click()
    until(page,"node&&node.actor===1");done(page)
    page.locator('#freq-inputs input').nth(0).fill('60')
    page.locator('#freq-inputs input').nth(1).fill('40')
    page.locator('#freq-apply').click()
    expect(page.locator('#freq-note')).to_contain_text('个组合生成节点锁')
    assert page.evaluate("overrides.length")==500
    assert page.evaluate("JSON.stringify(getConfig('locked')).length")<1024*1024
    assert page.evaluate("getConfig('locked').profile.overrides.filter(o=>o.scene).length")==1
    page.locator('#locked-solve').click()
    until(page,"result&&result.config.mode==='locked'");done(page)
    expect(page.locator('#summary')).to_contain_text('锁定 500 个组合后双方重新求解')


def test_hero_lock_only_counts_in_the_locked_solve(page):
    from playwright.sync_api import expect
    river(page)
    page.locator('#baseline').click();until(page,"result&&node&&!node.chance");done(page)
    page.locator('#manual').get_by_role('button',name='100% 过牌 Check',exact=True).click()
    page.locator('#apply-override').click()
    expect(page.locator('#lock-list')).to_contain_text('已保留节点锁：1')
    assert page.evaluate("getConfig('fixed').profile.overrides.length")==0
    assert page.evaluate("getConfig('locked').profile.overrides.length")==1


def test_runout_report_reads_every_card(page):
    from playwright.sync_api import expect
    scene(page,'Ks Qd 7c 3s','7h7d,5h4h','AcQc')
    page.locator('#baseline').click();until(page,"result&&node&&!node.chance");done(page)
    page.locator('#actions button').filter(has_text='Check').click()
    until(page,"node&&node.actor===1");done(page)
    page.locator('#actions button').filter(has_text='Check').click()
    until(page,"node&&node.chance");done(page)
    page.locator('#runout-button').click()
    expect(page.locator('#runout-table tr[data-card]')).to_have_count(page.evaluate('node.possible_cards.length'),timeout=120000)
    done(page)
    page.locator('#runout-table th').nth(1).click()
    page.locator('#runout-table tr[data-card]').first.click()
    until(page,"node&&!node.chance");done(page)
    assert len(page.evaluate('node.board'))==5


def test_flop_report_solves_each_board(page):
    from playwright.sync_api import expect
    scene(page,'Ks Qd 7c','7h7d,5h4h','AcQc')
    page.locator('#report-panel summary').click()
    page.locator('#report-boards').fill('Ks7c2d Th9d8c')
    page.locator('#report-start').click()
    expect(page.locator('#report-table tr[data-board]')).to_have_count(2,timeout=120000)
    done(page)
    expect(page.locator('#status')).to_contain_text('多牌面报告完成')
    page.locator('#report-table tr[data-board="Th9d8c"]').click()
    expect(page.locator('#board')).to_have_value('Th 9d 8c')
