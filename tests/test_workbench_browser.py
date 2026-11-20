"""Real headless Edge workflow; opt-in, requires Playwright and native engine."""
import os
import threading
import time

import pytest

from pokerlab.solver.server import make_server
from pokerlab.solver.__main__ import ROOT

pytestmark=pytest.mark.skipif(os.environ.get('POKERLAB_BROWSER')!='1',reason='opt-in browser/native E2E')

def test_actual_flop_workflow(tmp_path):
    from playwright.sync_api import sync_playwright,expect
    server=make_server(8766,agent_dir=tmp_path/'agent')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1500,'height':1000})
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:8766')
            def wait_text(selector,text):
                # A native resource failure is already final. Surface it now
                # instead of spending 120 seconds waiting for nonexistent UI.
                page.wait_for_function("([selector,text]) => document.querySelector('#error').textContent || document.querySelector(selector).textContent.includes(text)",arg=[selector,text],timeout=120000)
                assert not page.locator('#error').inner_text(), page.locator('#error').inner_text()
                expect(page.locator(selector)).to_contain_text(text)
            expect(page.locator('#board')).to_have_value('9h 8h 2c')
            oop=page.locator('#range-editor0');ip=page.locator('#range-editor1')
            expect(page.locator('#range-tab1')).to_be_visible()
            expect(ip).to_be_visible()
            expect(ip.locator('.cell')).to_have_count(169)
            assert ip.evaluate('(e) => e.open')
            expect(oop.locator('.cell')).to_have_count(169)
            expect(oop).to_contain_text('有效 61 组合')
            page.locator('#range-tab1').click()
            expect(ip).to_be_visible()
            expect(ip).to_contain_text('有效 71 组合')
            page.locator('#range-tab0').click()
            original_ip=page.locator('#range1').input_value()
            page.locator('#range0').fill('AA:0.5,AKs')
            expect(oop).to_contain_text('有效 10 组合 · 加权 7.00')
            oop.locator('select').select_option('inspect')
            oop.locator('[data-hand="AA"]').click()
            oop.locator('[data-combo="AcAd"]').fill('25')
            oop.locator('[data-combo="AcAd"]').press('Tab')
            expect(oop).to_contain_text('加权 6.75')
            assert 'AcAd:0.25' in page.locator('#range0').input_value()
            assert page.locator('#range1').input_value()==original_ip
            page.locator('#board').fill('Ac 8h 2c')
            expect(oop).to_contain_text('有效 6 组合 · 加权 4.50 · 公共牌冲突 4')
            page.locator('#board').fill('9h 8h 2c')
            oop.locator('select').select_option('paint')
            oop.get_by_label('范围权重百分比').fill('50')
            oop.locator('[data-hand="KQs"]').scroll_into_view_if_needed();first=oop.locator('[data-hand="KK"]').bounding_box();last=oop.locator('[data-hand="KQs"]').bounding_box()
            page.mouse.move(first['x']+first['width']/2,first['y']+first['height']/2);page.mouse.down()
            page.mouse.move(last['x']+last['width']/2,last['y']+last['height']/2,steps=5);page.mouse.up()
            assert 'KK:0.5' in page.locator('#range0').input_value()
            assert 'KQs:0.5' in page.locator('#range0').input_value()
            with page.expect_download() as downloaded:oop.get_by_text('导出文本',exact=True).click()
            assert downloaded.value.suggested_filename=='OOP-range.txt'
            page.locator('#range0').fill('not-a-range')
            expect(oop.locator('.range-error')).to_contain_text('请修正文本')
            expect(oop.locator('[data-hand="AA"]')).to_be_disabled()
            page.locator('#load-example').click()
            parsed=page.evaluate("""() => {
                const total=t=>[...RangeEditor.parse(t).values()].filter(v=>v>0).length;
                const input='AsAh:0.25,AA:0.5,AKs,98s-65s,A8o+';
                const r=RangeEditor.parse(input), round=RangeEditor.parse(RangeEditor.serialize(r));
                return {pairs:total('88+'),connectors:total('98s+'),gap:total('AQo-86o'),
                    exact:total('AhAs-QhQs'), weight:r.get('AhAs'),
                    round:[...r].every(([k,v])=>round.get(k)===v)};
            }""")
            assert parsed=={'pairs':42,'connectors':24,'gap':84,'exact':3,'weight':.25,'round':True}
            page.locator('#bet3').locator('..').locator('[data-size="50%"]').click()
            expect(page.locator('#bet3')).to_have_value('33%,50%')
            page.locator('#bet3').locator('..').locator('[data-size="75%"]').click()
            page.locator('#bet3').locator('..').locator('[data-size="100%"]').click()
            expect(page.locator('#error')).to_contain_text('最多 3')
            expect(page.locator('#bet3')).to_have_value('33%,50%,75%')
            page.locator('#bet3').locator('..').locator('[data-size="50%"]').click()
            page.locator('#load-example').click()
            expect(page.locator('#bet3')).to_have_value('33%')
            station=page.locator('[data-kind="station"]')
            station.locator('.trait-level').select_option('1')
            expect(station.locator('.strength')).to_have_value('1')
            expect(station.locator('.enabled')).to_be_checked()
            page.locator('#advanced-tree summary').click()
            page.locator('#separate-sizes').check()
            page.locator('#ip-bet3').fill('40%')
            page.locator('#custom-donk').check()
            page.locator('#donk4').fill('25%')
            assert page.evaluate("getConfig().bets_ip[0]")=='40%'
            assert page.evaluate("getConfig().donks")==['25%','']
            # Restore shared sizes for the integration benchmark below.
            page.locator('#separate-sizes').uncheck()
            page.locator('#custom-donk').uncheck()
            # Solve the edited range and two-size Flop tree, not just the default.
            oop.locator('select').select_option('paint')
            oop.get_by_label('范围权重百分比').fill('50')
            # AA is already selected. A single click now removes it; another
            # click selects it at the chosen 50% weight.
            oop.locator('[data-hand="AA"]').click()
            oop.locator('[data-hand="AA"]').click()
            page.locator('#bet3').locator('..').locator('[data-size="50%"]').click()
            edited_range=page.locator('#range0').input_value()
            assert 'AA:0.5' in edited_range
            oop.screenshot(path=str(ROOT/'outputs/workbench-range-editor.png'))
            oop.locator(':scope > summary').click()
            page.locator('#baseline').click()
            wait_text('#summary','均衡基线 · 9h 8h 2c')
            expect(page.locator('#grid .cell')).to_have_count(169,timeout=120000)
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            # Compare displayed aggregate to an independent weighted calculation.
            values=page.evaluate("""() => ({node, cells:[...document.querySelectorAll('#grid .cell')].map(b=>({
                hand:b.dataset.hand,probabilities:JSON.parse(b.dataset.probabilities),
                background:getComputedStyle(b).backgroundImage}))})""")
            node=values['node'];player=node['players'][node['actor']];count=len(player['combos'])
            assert len(node['action_details']) == len(node['actions'])
            assert node['action_details'][0]['pot_fraction'] is None
            assert [detail['pot_fraction'] for detail in node['action_details'][1:]] == pytest.approx([.33, .50])
            aa=[i for i,c in enumerate(player['combos']) if c[0]==c[2]=='A']
            mass=sum(player['blocker_adjusted_weights'][i] for i in aa)
            expected=[sum(player['blocker_adjusted_weights'][i]*node['strategy_action_major'][a*count+i] for i in aa)/mass for a in range(len(node['actions']))]
            cell=next(c for c in values['cells'] if c['hand']=='AA')
            assert cell['probabilities']==pytest.approx(expected,abs=1e-7)
            assert 'linear-gradient' in cell['background']
            expect(page.locator('#strategy-legend')).to_contain_text('Check')
            assert len(node['actions'])==3
            assert page.evaluate('result.config.players[0]')==edited_range
            page.locator('#workspace').screenshot(path=str(ROOT/'outputs/workbench-strategy.png'))
            # Select the combined player model through real UI controls.
            page.locator('#combined').click()
            page.locator('#preview').click()
            wait_text('#summary','对手模型预览')
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            page.locator('#response').click()
            wait_text('#summary','冻结对手后的完整最佳回应')
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            expect(page.locator('#combos tbody tr')).not_to_have_count(0)
            page.locator('#grid button').filter(has_text='AA').click()
            expect(page.locator('#combos tbody tr')).to_have_count(6)
            page.locator('#all-combos').click()
            page.locator('#actions button').filter(has_text='Bet(33)').click()
            wait_text('#node-label','IP 行动')
            expect(page.locator('#strategy-legend')).to_contain_text('Fold',timeout=120000)
            expect(page.locator('#strategy-legend')).to_contain_text('Call')
            expect(page.locator('#strategy-legend')).to_contain_text('AllIn')
            colors=page.locator('#strategy-legend i').evaluate_all('(items)=>items.map(i=>getComputedStyle(i).backgroundColor)')
            assert colors[:2]==['rgb(54, 134, 223)','rgb(38, 154, 114)']
            assert page.locator('#strategy-legend .legend-item').evaluate_all(
                '(items)=>items.map(i=>i.dataset.category)')==['Fold','Call','overbet']
            assert colors==page.locator('#actions button').evaluate_all(
                '(items)=>items.map(i=>getComputedStyle(i).borderColor)')
            real_details=page.evaluate('node.action_details')
            assert real_details[-1]['is_overbet'] is True
            assert real_details[-1]['pot_fraction'] == pytest.approx((200-33)/(133+33))
            page.locator('#workspace').screenshot(path=str(ROOT/'outputs/workbench-facing-bet-20261013.png'))
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            page.locator('#root').click()
            wait_text('#node-label','OOP 行动')
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            page.locator('#actions button').filter(has_text='Check').click()
            wait_text('#node-label','IP 行动')
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            expect(page.locator('#node-model-preview')).to_contain_text('基线 → 固定模型',timeout=120000)
            # Navigate through an actual chance card and lock one Turn combination.
            page.locator('#actions button').filter(has_text='Check').click()
            wait_text('#node-label','发公共牌')
            expect(page.locator('#chance-deck button')).to_have_count(52)
            expect(page.locator('#chance-deck [data-card="9h"]')).to_be_disabled()
            page.locator('#chance-deck [data-card="3c"]').click()
            wait_text('#node-label','OOP 行动')
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            page.locator('#actions button').filter(has_text='Check').click()
            wait_text('#node-label','IP 行动')
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            # The same graphical legal-card deck also navigates actual River
            # branches; return to this Turn opponent node before locking it.
            page.locator('#actions button').filter(has_text='Check').click()
            wait_text('#node-label','发公共牌')
            expect(page.locator('#chance-deck')).to_have_attribute('aria-label','选择 River 公共牌',timeout=120000)
            expect(page.locator('#chance-deck [data-card="3c"]')).to_be_disabled()
            page.locator('#chance-deck [data-card="4c"]').click()
            wait_text('#node-label','3c 4c · OOP 行动')
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            page.locator('#back').click()
            wait_text('#node-label','发公共牌')
            expect(page.locator('#chance-deck')).to_be_visible(timeout=120000)
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            page.locator('#back').click()
            wait_text('#node-label','3c · IP 行动')
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            page.locator('#workspace').screenshot(path=str(ROOT/'outputs/workbench-turn-20261013.png'))
            page.locator('#manual').get_by_role('button',name='100% 过牌 Check',exact=True).click()
            locked_combo=page.locator('#manual-combo').input_value()
            page.locator('#apply-override').click()
            expect(page.locator('#lock-list')).to_contain_text('已保留节点锁：1')
            page.locator('#undo').click()
            expect(page.locator('#lock-list')).to_contain_text('已保留节点锁：0')
            page.locator('#redo').click()
            expect(page.locator('#lock-list')).to_contain_text('已保留节点锁：1')
            page.locator('#response').click()
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            expect(page.locator('#error')).to_be_empty()
            page.locator('#lock-list').get_by_role('button',name='定位',exact=True).click()
            wait_text('#node-label','3c · IP 行动')
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            expect(page.locator('#manual-combo')).to_have_value(locked_combo)
            assert page.locator('#manual-actions input').first.input_value()=='1'
            page.locator('#library summary').click()
            page.locator('#library-name').fill('E2E named range '+str(time.time_ns()))
            page.locator('#save-range').click()
            expect(page.locator('#library')).to_contain_text('范围已保存到本地库')
            page.locator('#library-name').fill('E2E player '+str(time.time_ns()))
            page.locator('#save-player').click()
            expect(page.locator('#library')).to_contain_text('特质已保存')
            page.locator('#root').click()
            wait_text('#node-label','OOP 行动')
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            name='E2E Flop '+str(time.time_ns())
            page.locator('#study-name').fill(name);page.locator('#save').click()
            expect(page.locator('#status')).to_have_text('配置与完整策略已保存',timeout=120000)
            page.locator('#pot').fill('101')
            expect(page.locator('#stale')).to_contain_text('过期')
            page.locator('#studies').select_option(label=name);page.locator('#open').click()
            expect(page.locator('#pot')).to_have_value('100',timeout=120000)
            expect(page.locator('#range0')).to_have_value(edited_range)
            expect(page.locator('#bet3')).to_have_value('33%,50%')
            expect(page.locator('#lock-list')).to_contain_text('已保留节点锁：1')
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            expect(page.locator('#error')).to_be_empty()
            page.evaluate("() => {window.scrollTo(0,0);document.querySelector('aside').scrollTop=0}")
            page.screenshot(path=str(ROOT/'outputs/workbench-flop.png'),full_page=True)
            page.locator('#sensitivity-panel summary').click()
            page.locator('#sensitivity').click()
            expect(page.locator('#sensitivity-results table tr')).to_have_count(4,timeout=120000)
            expect(page.locator('#sensitivity-results')).to_contain_text('根 Hero 组合')
            expect(page.locator('#cancel')).to_be_disabled(timeout=120000)
            expect(page.locator('#error')).to_be_empty()
            page.locator('#target').fill('0.000001');page.locator('#iterations').fill('100000');page.locator('#baseline').click()
            expect(page.locator('#cancel')).to_be_enabled(timeout=10000)
            page.locator('#cancel').click()
            expect(page.locator('#error')).to_contain_text('cancel',timeout=30000)
            browser.close()
        assert errors==[]
    finally:
        server.shutdown();server.server_close();server.jobs.close();thread.join(timeout=5)
