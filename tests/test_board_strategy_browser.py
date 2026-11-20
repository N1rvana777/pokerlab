"""Real Edge input/renderer checks with explicit synthetic strategy fixtures.

No solver job is launched here. Numeric strategy fixtures validate rendering,
not poker EV. The native workflow is covered separately by workbench_browser.
"""
import threading
import re

import pytest

from pokerlab.solver.__main__ import ROOT
from pokerlab.solver.server import make_server


def rgb(color):
    return tuple(int(channel) for channel in re.findall(r'\d+', color)[:3])


def luminance(color):
    """Independent sRGB relative luminance, not palette implementation logic."""
    channels = [c / 255 for c in rgb(color)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
              for c in channels]
    return sum(weight * channel for weight, channel in zip((.2126, .7152, .0722), linear))


def render_fixture(page, fixture):
    page.evaluate('''n => {
      result={config:getConfig()}; node=n; path=[]; selected=null;
      comparison=null; templateComparison=null; $("variant").value="baseline";
      renderNode();
    }''', fixture)


def node_colors(page):
    return page.locator('#strategy-legend .legend-item').evaluate_all('''items=>items.map(e=>({
      action:e.dataset.action, category:e.dataset.category,
      color:getComputedStyle(e.querySelector('i')).backgroundColor}))''')


@pytest.fixture
def board_page(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    server = make_server(0, agent_dir=tmp_path / 'agent')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1500, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            playwright.expect(page.locator('#board')).to_have_value('9h 8h 2c')
            yield page, playwright.expect
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        server.jobs.close()
        thread.join(timeout=5)


def test_board_picker_initial_streets_duplicates_cancel_and_undo(board_page):
    page, expect = board_page
    assert page.evaluate('getConfig().time_limit_seconds') == 0
    page.evaluate('() => {const c=getConfig(); c.time_limit_seconds=600; setConfig(c)}')
    assert page.evaluate('getConfig().time_limit_seconds') == 0
    expect(page.locator('#runtime-policy')).to_contain_text('不设自动超时')
    expect(page.locator('#runtime-policy')).to_contain_text('取消任务不提供续算点')
    expect(page.locator('.workflow-help')).to_have_count(4)
    page.locator('#choose-board').click()
    expect(page.locator('#board-picker')).to_be_visible()
    expect(page.locator('#board-picker-deck button')).to_have_count(52)
    # Replacing slot zero keeps other selected cards disabled.
    expect(page.locator('#board-picker-deck [data-card="8h"]')).to_be_disabled()
    page.locator('#board-picker-clear').click()
    expect(page.locator('#board-picker-confirm')).to_be_disabled()
    for card in ['8h', '7d', '5h']:
        page.locator(f'#board-picker-deck [data-card="{card}"]').click()
    expect(page.locator('#board-picker-confirm')).to_be_enabled()
    assert page.locator('#board-picker-slots button').evaluate_all('(items)=>items.map(b=>b.dataset.card)') == ['8h', '7d', '5h']
    (ROOT / 'outputs').mkdir(exist_ok=True)
    page.locator('#board-picker').screenshot(path=str(ROOT / 'outputs/workbench-board-picker-20261013.png'))
    page.locator('#board-picker-confirm').click()
    expect(page.locator('#board')).to_have_value('8h 7d 5h')
    expect(page.locator('#board-preview [data-card]')).to_have_count(3)
    page.locator('#undo').click()
    expect(page.locator('#board')).to_have_value('9h 8h 2c')
    page.locator('#redo').click()
    expect(page.locator('#board')).to_have_value('8h 7d 5h')
    for count, card in [(4, 'As'), (5, '2c')]:
        page.locator('#choose-board').click()
        page.locator(f'#board-picker [data-count="{count}"]').click()
        page.locator(f'#board-picker-slots [data-slot="{count-1}"]').click()
        page.locator(f'#board-picker-deck [data-card="{card}"]').click()
        page.locator('#board-picker-confirm').click()
        expect(page.locator('#board-preview [data-card]')).to_have_count(count)
    expect(page.locator('#board')).to_have_value('8h 7d 5h As 2c')
    page.locator('#choose-board').click()
    page.locator('#board-picker-clear').click()
    page.locator('#board-picker-close').click()
    expect(page.locator('#board')).to_have_value('8h 7d 5h As 2c')
    # Text input is still supported and synchronizes the graphical view.
    page.locator('#board').fill('Ah Ah 2c')
    expect(page.locator('#board-preview')).to_contain_text('不重复')
    page.locator('#board').fill('Ah Ks 2c')
    expect(page.locator('#board-preview [data-card]')).to_have_count(3)


def test_strategy_colors_weighted_probabilities_and_legal_chance_cards(board_page):
    page, expect = board_page
    player = {'combos': ['AcAd', 'AhAs'], 'blocker_adjusted_weights': [3, 1],
              'raw_reach': [1, 3], 'equity': [.7, .6], 'ev': [12, 10]}
    n = {'board': ['9h', '8h', '2c'], 'path': [], 'actor': 0,
         'terminal': False, 'chance': False, 'contributions': [10, 20], 'pot': 50,
         'actions': ['Fold', 'Call', 'Raise(60)', 'AllIn(130)'],
         'action_details': [{'is_overbet': False}, {'is_overbet': False},
                            {'is_overbet': False, 'call_amount': 10, 'pot_fraction': 40/60},
                            {'is_overbet': True, 'call_amount': 10, 'pot_fraction': 110/60}],
         'players': [player, player],
         'strategy_action_major': [.1, .4, .2, .3, .3, .2, .4, .1],
         'action_ev_action_major': [0, 0, 1, 1, 2, 2, 3, 3]}
    page.evaluate('n => {result={config:getConfig()}; node=n; path=[]; selected=null; comparison=null; templateComparison=null; $("variant").value="baseline"; renderNode()}', n)
    expect(page.locator('#grid .cell')).to_have_count(169)
    aa = page.locator('#grid [data-hand="AA"]')
    assert aa.evaluate('e=>JSON.parse(e.dataset.probabilities)') == pytest.approx([.325, .275, .225, .175], abs=1e-12)
    legend = page.locator('#strategy-legend .legend-item').evaluate_all('(items)=>items.map(e=>({category:e.dataset.category,color:getComputedStyle(e.querySelector("i")).backgroundColor}))')
    assert [entry['category'] for entry in legend] == ['Fold', 'Call', 'aggressive', 'overbet']
    assert legend[0]['color'] == 'rgb(54, 134, 223)'
    assert legend[1]['color'] == 'rgb(38, 154, 114)'
    red, purple = (rgb(entry['color']) for entry in legend[2:])
    assert red[0] > max(red[1:])
    assert purple[2] > purple[0] > purple[1]
    assert page.locator('#actions button').evaluate_all(
        'items=>items.map(e=>getComputedStyle(e).borderColor)') == [entry['color'] for entry in legend]
    # Raise-to 60 exceeds current pot 50, but the 40 raise increment is
    # only 2/3 of the 60 pot after calling, so it must remain red.
    assert '66.7%' in page.locator('#actions button').nth(2).get_attribute('title')
    checks = page.evaluate('''() => ({same:actionStyle('Call',0,['Call'])===actionStyle('Check',0,['Check']),
      exact:actionCategory('Bet(50)',0,{action_details:[{is_overbet:false,pot_fraction:1}]}),
      over:actionCategory('Bet(51)',0,{action_details:[{is_overbet:true,pot_fraction:1.02}]}),
      smallAllIn:actionCategory('AllIn(25)',0,{action_details:[{is_overbet:false,pot_fraction:.5}]})})''')
    assert checks == {'same': True, 'exact': 'aggressive', 'over': 'overbet', 'smallAllIn': 'aggressive'}
    # Pure BR remains pure: rendering never injects mixed colors.
    page.evaluate('() => {node.strategy_action_major=[0,0,1,1,0,0,0,0];renderNode()}')
    assert aa.evaluate('e=>JSON.parse(e.dataset.probabilities)') == [0, 1, 0, 0]
    # Engine-provided legality is authoritative, including non-board exclusions.
    chance = {'board': ['9h', '8h', '2c'], 'path': [0, 0], 'terminal': False,
              'chance': True, 'contributions': [0, 0], 'pot': 50,
              'possible_cards': [{'id': 4, 'card': '3c'}, {'id': 35, 'card': 'Ts'}]}
    page.evaluate('n=>{node=n;path=[0,0];renderNode();window.navigated=null;showNode=async()=>{window.navigated=[...path]}}', chance)
    expect(page.locator('#chance-deck button')).to_have_count(52)
    expect(page.locator('#chance-deck button:enabled')).to_have_count(2)
    expect(page.locator('#chance-deck [data-card="9h"]')).to_be_disabled()
    expect(page.locator('#chance-deck [data-card="As"]')).to_be_disabled()
    page.locator('#chance-deck [data-card="3c"]').click()
    assert page.evaluate('window.navigated') == [0, 0, 4]
    chance['board'].append('3c')
    chance['possible_cards'] = [{'id': 35, 'card': 'Ts'}]
    page.evaluate('n=>{node=n;renderNode()}', chance)
    expect(page.locator('#chance-deck')).to_have_attribute('aria-label', '选择 River 公共牌')
    expect(page.locator('#chance-deck [data-card="3c"]')).to_be_disabled()
    page.locator('#chance-deck [data-card="Ts"]').click()
    assert page.evaluate('window.navigated') == [0, 0, 4, 35]


def test_cfr_resume_summary_distinguishes_cache_and_new_iterations(board_page):
    page, expect = board_page
    page.evaluate('''() => {
      result={config:getConfig('equilibrium'),precision:{baseline_iterations:12,
        baseline_exploitability_chips:1,baseline_stop_reason:'iteration_limit',actual_chips:1,stop_reason:'iteration_limit'},
        timing:{},cache:{baseline_hit:false,resumed_iterations:7},
        same_model_baseline_hero_ev:1,ev:[1,1],hero_improvement:0,
        tree:{effective_combos:[1,1],public_nodes:1,suit_isomorphism:true},memory:{},
        coverage:{nodes:0,trait_combos:0,streets:[0,0,0],zero_reach_under_compiled_prefix:0,samples:[]}};
      renderSummary();
    }''')
    expect(page.locator('#summary')).to_contain_text('累计 12 次迭代')
    expect(page.locator('#summary')).to_contain_text('从第 7 次续算，本次新增 5 次')
    assert page.evaluate('phases.resuming') == '载入 CFR 续算状态'
    assert page.evaluate('phases.saving_checkpoint') == '保存 CFR 续算状态'
    page.evaluate('() => {result.cache.baseline_hit=true;renderSummary()}')
    expect(page.locator('#summary')).to_contain_text('复用已求得的基线（本次未迭代）')
    expect(page.locator('#summary')).not_to_contain_text('本次新增')


def test_multiple_bet_sizes_share_ordered_shades_without_changing_probabilities(board_page):
    """Synthetic UI fixture: this does not launch a solver or validate poker EV."""
    page, expect = board_page
    combos = ['AcAd', 'AhAs', 'AcKc', 'AdKd', 'AsQs', 'KcQc', 'JcTc', '7d7s']
    player = {'combos': combos, 'blocker_adjusted_weights': [1, 3, 1, 1, 2, 1, 2, 1],
              'raw_reach': [1] * 8, 'equity': [.8, .8, .55, .55, .5, .45, .4, .35],
              'ev': [12, 10, 5, 5, 4, 3, 2, 1]}
    # Deliberately scramble sizes; displayed depth must not depend on API order.
    actions = ['Check', 'Bet(75)', 'Bet(25)', 'Bet(50)', 'Bet(150)', 'AllIn(250)']
    probabilities = [.2, .15, .3, .1, .15, .1]
    strategy = [p for p in probabilities for _ in combos]
    action_ev = [float(action + combo / 10) for action in range(6) for combo in range(8)]
    n = {'board': ['9h', '8h', '2c'], 'path': [], 'actor': 0,
         'terminal': False, 'chance': False, 'contributions': [0, 0], 'pot': 100,
         'actions': actions,
         'action_details': [{'pot_fraction': fraction, 'call_amount': 0,
                             'is_overbet': fraction is not None and fraction > 1}
                            for fraction in [None, .75, .25, .5, 1.5, 2.5]],
         'players': [player, player], 'strategy_action_major': strategy,
         'action_ev_action_major': action_ev}
    render_fixture(page, n)
    expect(page.locator('#grid .cell')).to_have_count(169)
    entries = node_colors(page)
    colors = [entry['color'] for entry in entries]
    assert [entry['category'] for entry in entries] == ['Check'] + ['aggressive'] * 3 + ['overbet'] * 2
    assert len(set(colors[1:])) == 5
    assert luminance(colors[2]) > luminance(colors[3]) > luminance(colors[1])
    assert luminance(colors[4]) > luminance(colors[5])
    for index in [1, 2, 3]:
        red = rgb(colors[index])
        assert red[0] > max(red[1:])
    for index in [4, 5]:
        purple = rgb(colors[index])
        assert purple[2] > purple[0] > purple[1]
    assert page.locator('#actions button').evaluate_all(
        'items=>items.map(e=>getComputedStyle(e).borderColor)') == colors
    aa = page.locator('#grid [data-hand="AA"]')
    assert aa.evaluate('e=>JSON.parse(e.dataset.probabilities)') == pytest.approx(probabilities, abs=1e-12)
    gradient = aa.evaluate('e=>getComputedStyle(e).backgroundImage')
    for color in colors:
        assert color in gradient
    stops = [float(value) for value in re.findall(r'([\d.]+)%', gradient)]
    expected_stops, cursor = [], 0
    for probability in probabilities:
        expected_stops.extend([cursor, cursor + probability * 100])
        cursor += probability * 100
    assert stops == pytest.approx(expected_stops, abs=1e-9)
    assert page.evaluate('node.strategy_action_major') == strategy
    assert page.evaluate('node.action_ev_action_major') == action_ev
    # Combination bars, legends, buttons and the grid all use the same map.
    aa.click()
    expect(page.locator('#combos tbody tr')).to_have_count(2)
    combo_bars = page.locator('#combos tbody tr').first.locator('[data-action-index]').evaluate_all('''cells=>cells.map(e=>({
      index:Number(e.dataset.actionIndex), probability:Number(e.dataset.probability),
      color:getComputedStyle(e.querySelector('.combo-frequency-track > i')).backgroundColor,
      width:e.querySelector('.combo-frequency-track > i').style.width}))''')
    assert [cell['index'] for cell in combo_bars] == list(range(6))
    assert [cell['probability'] for cell in combo_bars] == pytest.approx(probabilities)
    assert [cell['color'] for cell in combo_bars] == colors
    assert [float(cell['width'].removesuffix('%')) for cell in combo_bars] == pytest.approx([p * 100 for p in probabilities])
    assert page.locator('#combos thead [data-action-index]').evaluate_all(
        'items=>items.map(e=>getComputedStyle(e).borderBottomColor)') == colors
    page.locator('#combo-sort').select_option('ev')
    assert page.locator('#combos tbody tr').first.locator('.combo-frequency-track > i').evaluate_all(
        'items=>items.map(e=>getComputedStyle(e).backgroundColor)') == colors
    # Screenshot explicitly labels the fixture; never pass it off as solved output.
    page.set_viewport_size({'width': 1900, 'height': 1500})
    page.evaluate('''() => {
      $('summary').textContent='UI 配色验收夹具（合成概率／EV，非求解结果）';
      $('workspace').scrollIntoView();
    }''')
    (ROOT / 'outputs').mkdir(exist_ok=True)
    page.locator('#workspace').screenshot(path=str(ROOT / 'outputs/workbench-sizing-shades-20261013.png'))


def test_raise_shades_follow_real_pot_fraction_and_do_not_cycle(board_page):
    """Render-only checks for raise-to ordering, metadata boundary and fallback."""
    page, _ = board_page
    result = page.evaluate('''() => {
      const actions=['Fold','Call','Raise(310)','Raise(110)','Raise(210)','Raise(410)','AllIn(510)','Raise(710)','AllIn(710)'];
      const fractions=[null,null,.75,.25,.5,1,1.25,1.75,1.75];
      const fixture={actions,action_details:fractions.map(p=>({pot_fraction:p,is_overbet:p!==null&&p>1,call_amount:10}))};
      const original=actions.map((a,i)=>actionStyle(a,i,actions,fixture));
      const normalized=original.map(color=>{const e=document.createElement('i');e.style.color=color;document.body.append(e);const value=getComputedStyle(e).color;e.remove();return value});
      const reverse={actions:[...actions].reverse(),action_details:[...fixture.action_details].reverse()};
      const reversed=reverse.actions.map((a,i)=>actionStyle(a,i,reverse.actions,reverse)).reverse();
      const fallbackActions=['Check','Bet(500)','Bet(25)','Bet(100)','Bet(75)','AllIn(1000)'];
      const fallback={actions:fallbackActions};
      return {colors:normalized,unchanged:JSON.stringify(original)===JSON.stringify(reversed),
        categories:actions.map((a,i)=>actionCategory(a,i,fixture)),
        fallbackCategories:fallbackActions.map((a,i)=>actionCategory(a,i,fallback)),
        fallbackColors:fallbackActions.map((a,i)=>{const e=document.createElement('i');e.style.color=actionStyle(a,i,fallbackActions,fallback);document.body.append(e);const value=getComputedStyle(e).color;e.remove();return value})};
    }''')
    colors = result['colors']
    assert result['unchanged']
    assert result['categories'] == ['Fold', 'Call'] + ['aggressive'] * 4 + ['overbet'] * 3
    assert len(set(colors[2:6])) == 4  # Four ordinary sizes must not wrap a 3-color palette.
    assert luminance(colors[3]) > luminance(colors[4]) > luminance(colors[2]) > luminance(colors[5])
    assert luminance(colors[6]) > luminance(colors[7])
    assert colors[7] == colors[8]  # Equal pot fractions get equal colors, even All-in.
    assert result['fallbackCategories'] == ['Check'] + ['aggressive'] * 5
    fallback = result['fallbackColors']
    assert len(set(fallback[1:])) == 5
    assert luminance(fallback[2]) > luminance(fallback[4]) > luminance(fallback[3]) > luminance(fallback[1]) > luminance(fallback[5])
