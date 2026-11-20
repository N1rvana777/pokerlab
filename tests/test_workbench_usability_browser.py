"""Real browser acceptance for units, memory mode and the local Solver agent."""
import json
import threading

import pytest

from pokerlab.solver.server import make_server


def test_units_memory_recovery_and_solver_agent_are_local(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    server = make_server(0, agent_dir=tmp_path / 'agent')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors, requests = [], []
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1550, 'height': 1100})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append(request.url))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            expect = playwright.expect
            expect(page.locator('#board')).to_have_value('9h 8h 2c')
            expect(page.locator('#solver-agent')).to_contain_text('当前局面已同步', timeout=30000)
            expect(page.locator('#solver-agent')).to_contain_text('Pokerlab Solver 助手')
            expect(page.locator('#amount-unit')).to_have_value('bb')
            expect(page.locator('#pot-label')).to_have_text('底池（bb）')
            expect(page.locator('#memory-auto')).to_be_checked()
            expect(page.locator('#memory')).to_be_disabled()
            expect(page.locator('#memory-resources')).to_contain_text('自动安全预算', timeout=30000)
            page.locator('#pot').fill('20')
            expect(page.locator('#spr-hint')).to_contain_text('SPR = 10.00')
            page.locator('#memory-auto').uncheck()
            page.locator('#memory').fill('4096')
            expect(page.locator('#memory-resources')).to_contain_text('手动上限 4.00 GiB')
            expect(page.locator('#solver-agent')).to_contain_text('当前局面已同步', timeout=30000)
            saved = json.loads((tmp_path/'agent/solver-state.json').read_text(encoding='utf-8'))
            assert saved['config']['pot'] == 20
            assert saved['config']['memory_auto'] is False
            assert saved['config']['amount_unit'] == 'bb'
            page.evaluate("setError('内存预检：预计峰值 5.37 GiB，任务预算 4.00 GiB')")
            expect(page.locator('#memory-recovery')).to_be_visible()
            # An edit must not keep showing a failed estimate for the old tree.
            page.locator('#pot').fill('21')
            expect(page.locator('#error')).to_be_empty()
            expect(page.locator('#status')).to_contain_text('尚未重新求解')
            page.locator('#pot').fill('20')
            page.evaluate("setError('内存预检：预计峰值 5.37 GiB，任务预算 4.00 GiB')")
            page.locator('#memory-recovery-auto').click()
            expect(page.locator('#memory-auto')).to_be_checked()
            expect(page.locator('#memory')).to_be_disabled()
            expect(page.locator('#error')).to_be_empty(timeout=30000)
            expect(page.locator('#pot')).to_have_value('20')
            # A legacy import does not silently relabel old chip EV as bb.
            page.evaluate("() => { const old=getConfig(); delete old.amount_unit; setConfig(old); }")
            expect(page.locator('#amount-unit')).to_have_value('chips')
            expect(page.locator('#pot-label')).to_have_text('底池（筹码）')
            expect(page.locator('#amount-unit-hint')).to_contain_text('不会自动换算金额')
            page.locator('#load-example').click()
            expect(page.locator('#amount-unit')).to_have_value('bb')
            expect(page.locator('#solver-agent')).to_contain_text('当前局面已同步', timeout=30000)
            # Observe a backend/agent edit, then explicitly load it through UI.
            page.evaluate("async () => { const state=await api('/api/agent/config'); await api('/api/agent/config',{patch:{pot:35},expected_revision:state.revision}); }")
            page.locator('#solver-agent').get_by_role('button', name='载入后台局面', exact=True).click()
            expect(page.locator('#pot')).to_have_value('35')
            # Dirty input is kept and explicitly synchronized after a conflict.
            page.evaluate("async () => { const state=await api('/api/agent/config'); await api('/api/agent/config',{patch:{pot:36},expected_revision:state.revision}); }")
            page.locator('#pot').fill('37')
            expect(page.locator('#solver-agent')).to_contain_text('后台局面已更新', timeout=10000)
            expect(page.locator('#pot')).to_have_value('37')
            page.locator('#solver-agent').get_by_role('button', name='同步当前局面', exact=True).click()
            expect(page.locator('#solver-agent')).to_contain_text('当前局面已同步', timeout=10000)
            assert page.evaluate("async () => (await api('/api/agent/config')).config.pot") == 37
            assert not any('127.0.0.1:8770' in request for request in requests)
            assert page.locator('a[href*="8770"]').count() == 0
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        server.jobs.close()
        thread.join(timeout=5)
