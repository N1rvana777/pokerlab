"""Preflop range libraries: building from captured lines, loading, the decision tree and walking it."""
import importlib.util
import json
import threading
from pathlib import Path
from urllib.request import urlopen

import pytest

from pokerlab.solver import preflop
from pokerlab.solver.server import make_server


@pytest.fixture
def builder():
    path = Path(__file__).resolve().parents[1] / 'scripts/build_preflop_library.py'
    spec = importlib.util.spec_from_file_location('build_preflop_library_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RAW = {
    '3bet_BTN_STR': {'actions': 'F-F-F-F-R7-F-F-R21-C', 'pot': '43.5', 'first': 'STR 79', 'oop': 'AA,KK,AKs:0.5', 'ip': 'QQ:0.25,AKo'},
    'srp_BTN_STR': {'actions': 'F-F-F-F-R7-F-F-C', 'pot': '15.5', 'first': 'STR 93', 'oop': 'QQ,JJ', 'ip': 'AA,KK,QQ,AKs,AKo'},
    'srp_UTG_STR': {'actions': 'R7-F-F-F-F-F-F-C', 'pot': '15.5', 'first': 'STR 93', 'oop': 'AA,KK', 'ip': 'QQ,AKs'},
    'srp_UTG_SB': {'actions': 'R7-F-F-F-F-C-F-F', 'pot': '17', 'first': 'SB 93', 'oop': 'AQs:0.01', 'ip': 'AA,KK'},
}
META = {'id': 'lib', 'title': 'Test', 'source': 'test', 'note': 'n'}


def test_combo_counts_weight_each_class(builder):
    assert builder.class_combos('AA') == 6
    assert builder.class_combos('AKs') == 4
    assert builder.class_combos('AKo') == 12
    assert builder.range_combos('AA,AKs:0.5,AKo:0.25') == 11


def test_build_orders_lines_and_names_the_seats(builder):
    library = builder.build(RAW, META)
    assert library['schema'] == preflop.SCHEMA
    assert [line['id'] for line in library['lines']] == ['srp_UTG_SB', 'srp_UTG_STR', 'srp_BTN_STR', '3bet_BTN_STR']
    three_bet = library['lines'][3]
    assert three_bet['group'] == '3bet 底池'
    assert three_bet['label'] == 'BTN 开池 7bb · STR 3bet 21bb'
    assert (three_bet['oop_seat'], three_bet['ip_seat']) == ('STR', 'BTN')
    assert (three_bet['pot'], three_bet['stack']) == (43.5, 79)
    assert (three_bet['oop_combos'], three_bet['ip_combos']) == (14, 13.5)


def test_a_side_that_almost_never_gets_here_is_flagged(builder):
    lines = {line['id']: line for line in builder.build(RAW, META)['lines']}
    assert lines['srp_UTG_SB']['rare'] and lines['srp_UTG_SB']['label'].endswith('（几乎不出现）')
    assert not lines['srp_UTG_STR']['rare']


@pytest.mark.parametrize('name', ['name', 'srp_UTG_UTG', 'srp_UTG_XX', '4bet_UTG_LJ'])
def test_unknown_line_names_are_refused(builder, name):
    with pytest.raises(ValueError, match='unknown line name'):
        builder.build({name: RAW['srp_UTG_STR']}, META)


def test_a_first_actor_outside_the_pot_is_refused(builder):
    with pytest.raises(ValueError, match='not in this pot'):
        builder.build({'srp_UTG_STR': {**RAW['srp_UTG_STR'], 'first': 'BB 93'}}, META)


def test_an_empty_capture_is_refused(builder):
    with pytest.raises(ValueError, match='came back empty'):
        builder.build({'srp_UTG_STR': {**RAW['srp_UTG_STR'], 'oop': ''}}, META)


def test_an_action_string_of_the_wrong_kind_is_refused(builder):
    with pytest.raises(ValueError, match='does not match'):
        builder.build({'3bet_UTG_STR': RAW['srp_UTG_STR']}, META)


def test_output_is_never_overwritten(builder, tmp_path, monkeypatch):
    source = tmp_path / 'raw.json'
    source.write_text(json.dumps(RAW), encoding='utf-8')
    output = tmp_path / 'library.json'
    output.write_text('kept', encoding='utf-8')
    argv = ['build', '--input', str(source), '--output', str(output), '--id', 'a', '--title', 'b', '--source', 'c', '--note', 'd']
    monkeypatch.setattr('sys.argv', argv)
    with pytest.raises(FileExistsError):
        builder.main()
    assert output.read_text(encoding='utf-8') == 'kept'


def test_loading_skips_other_files_and_a_missing_folder(builder, tmp_path, monkeypatch):
    monkeypatch.setattr(preflop, 'FOLDER', tmp_path / 'absent')
    assert preflop.load_libraries() == []
    monkeypatch.setattr(preflop, 'FOLDER', tmp_path)
    (tmp_path / 'good.json').write_text(json.dumps(builder.build(RAW, META)), encoding='utf-8')
    (tmp_path / 'broken.json').write_text('{', encoding='utf-8')
    (tmp_path / 'other.json').write_text('{"schema": "other", "lines": []}', encoding='utf-8')
    assert [library['id'] for library in preflop.load_libraries()] == ['lib']


def test_endpoint_returns_the_private_libraries(builder, tmp_path, monkeypatch):
    monkeypatch.setattr(preflop, 'FOLDER', tmp_path)
    (tmp_path / 'good.json').write_text(json.dumps(builder.build(RAW, META)), encoding='utf-8')
    server = make_server(0, agent_dir=tmp_path / 'agent')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        libraries = json.load(urlopen(f'http://127.0.0.1:{server.server_port}/api/preflop'))
        assert libraries[0]['depth'] == 100
        assert libraries[0]['lines']['R7-F-F-F-F-F-F-C']['id'] == 'srp_UTG_STR'
    finally:
        server.shutdown()
        server.server_close()
        server.jobs.close()
        thread.join(timeout=5)


def tree(builder):
    return preflop.walk(builder.build(RAW, META))


def test_every_hand_class_appears_once():
    assert len(preflop.CLASSES) == len(set(preflop.CLASSES)) == 169
    assert preflop.CLASSES[:2] == ('AA', 'AKs') and preflop.CLASSES[13] == 'AKo' and preflop.CLASSES[-1] == '22'


def test_replay_follows_the_table_order():
    state = preflop.replay('F-F-F-F-R7-F-F-R21'.split('-'))
    assert state['seat'] == 'BTN' and state['pending'] == ['BTN']
    assert state['put'] == {'UTG': 0, 'LJ': 0, 'HJ': 0, 'CO': 0, 'BTN': 7, 'SB': .5, 'BB': 1, 'STR': 21}
    assert preflop.replay('F-F-F-F-R7-F-F-R21-C'.split('-'))['seat'] is None
    assert preflop.replay(['F'] * 7)['seat'] is None


def test_depth_and_lines_come_from_the_library(builder):
    book = tree(builder)
    assert book['depth'] == 100
    assert book['lines']['F-F-F-F-R7-F-F-R21-C']['pot'] == 43.5


def test_find_lines_takes_the_nearest_depth_and_gives_both_ranges(builder, tmp_path, monkeypatch):
    monkeypatch.setattr(preflop, 'FOLDER', tmp_path)
    with pytest.raises(ValueError, match='没有翻前范围库'):
        preflop.find_lines(160)
    (tmp_path / 'good.json').write_text(json.dumps(builder.build(RAW, META)), encoding='utf-8')
    found = preflop.find_lines(160, ['UTG'])
    assert found['depth'] == 100 and found['total'] == 2 and {line['line'] for line in found['lines']} == {'R7-F-F-F-F-F-F-C', 'R7-F-F-F-F-C-F-F'}
    assert all('oop' not in line for line in found['lines'])
    assert preflop.find_lines(100, ['UTG', 'SB'])['total'] == 1 and preflop.find_lines(100)['total'] == 4
    one = preflop.find_lines(100, line='R7-F-F-F-F-F-F-C')
    assert one['oop'] == 'AA,KK' and one['ip'] == 'QQ,AKs' and one['line'] == 'R7-F-F-F-F-F-F-C'
    with pytest.raises(ValueError, match='没有这条线'):
        preflop.find_lines(100, line='R7')


def test_a_first_decision_splits_each_hand_between_its_actions(builder):
    node = tree(builder)['nodes']['F-F-F-F-R7-F-F']
    assert node['seat'] == 'STR'
    assert (node['pot'], node['to_call'], node['stack']) == (10.5, 5, 98)
    assert [a['label'] for a in node['actions']] == ['Raise 21', 'Call', 'Fold']
    assert node['hands']['AA'] == [1, 0, 0]
    assert node['hands']['QQ'] == [0, 1, 0]
    assert node['hands']['72o'] == [0, 0, 1]
    assert node['hands']['AKs'] == [.5, 0, .5]
    assert node['actions'][0]['combos'] == 14
    assert node['actions'][0]['frequency'] == round(14 / 1326, 4)


def test_a_second_decision_is_measured_against_what_the_seat_arrived_with(builder):
    node = tree(builder)['nodes']['F-F-F-F-R7-F-F-R21']
    assert node['seat'] == 'BTN'
    assert '72o' not in node['hands']
    assert node['hands']['QQ'] == [.25, .75]
    assert node['actions'][0]['label'] == 'Call'
    assert node['actions'][1]['next'] is None and '4bet' in node['actions'][1]['label']


def test_a_seat_with_only_a_fold_on_record_is_marked_forced(builder):
    node = tree(builder)['nodes']['R7-F-F-F-F-C']
    assert node['seat'] == 'BB' and node['forced']
    assert [a['next'] for a in node['actions']] == ['R7-F-F-F-F-C-F']


def test_a_line_whose_earlier_action_is_missing_shows_no_frequencies(builder):
    raw = {key: value for key, value in RAW.items() if key != 'srp_BTN_STR'}
    node = preflop.walk(builder.build(raw, META))['nodes']['F-F-F-F-R7-F-F-R21']
    assert 'hands' not in node and [a['label'] for a in node['actions']] == ['Call']


def tree_node(seat, actions, default, **cells):
    row = [default] * 169
    for name, cell in cells.items():
        row[preflop.CLASSES.index(name)] = cell
    return {'seat': seat, 'actions': [[code, code, '', combos] for code, combos in actions], 'cells': row}


def folds_to_the_end(nodes, path, seats, last):
    """Each of `seats` folds in turn after `path`; the seat after them gets the node `last`."""
    for seat in seats:
        nodes[path] = tree_node(seat, [('F', 1326)], '0')
        path += '-F'
    nodes[path] = last


@pytest.fixture
def capture():
    """UTG opens. LJ may call or raise (the raise is unread). STR, last to act, calls or shoves."""
    nodes = {
        '': tree_node('UTG', [('RAI', 0), ('R7', 10), ('F', 1316)], '2', AA='1', KK='1:5000;2:5000'),
        'R7': tree_node('LJ', [('R16', 4), ('C', 4), ('F', 1318)], '2', AKs='1', QQ='1:2500;2:7500'),
        'R7-F-F-F-F-F-F-RAI': tree_node('UTG', [('C', 6), ('F', 3)], '', AA='0', KK='1'),
    }
    answer = tree_node('STR', [('RAI', 2), ('C', 6), ('F', 1318)], '2', QQ='0:2500;1:7500', JJ='1')
    folds_to_the_end(nodes, 'R7-F', ('HJ', 'CO', 'BTN', 'SB', 'BB'), answer)
    folds_to_the_end(nodes, 'R7-C', ('HJ', 'CO', 'BTN', 'SB', 'BB'), tree_node('STR', [('C', 6), ('F', 1320)], '1', JJ='0'))
    return {'depth': 100, 'names': list(preflop.CLASSES), 'nodes': nodes}


def test_replay_counts_a_shove_as_the_whole_depth_and_nobody_acts_on_it_again():
    state = preflop.replay(['R7', 'RAI'], 100)
    assert state['put']['LJ'] == 100 and state['current'] == 100
    assert state['pending'] == ['HJ', 'CO', 'BTN', 'SB', 'BB', 'STR', 'UTG']
    assert preflop.replay(['R7', 'RAI'] + ['F'] * 6 + ['C'], 100)['seat'] is None


def test_a_check_closes_a_limped_pot():
    state = preflop.replay(['F'] * 6 + ['C', 'X'])
    assert state['seat'] is None and state['live'] == ['BB', 'STR']
    assert sum(state['put'].values()) == 4.5


def test_a_cell_is_absent_pure_or_mixed():
    assert preflop.cell_shares('', 3) is None
    assert preflop.cell_shares('1', 3) == [0, 1, 0]
    assert preflop.cell_shares('0:2500;2:7500', 3) == [.25, 0, .75]


def test_a_tree_node_keeps_every_action_and_the_shares_of_each_class(capture):
    root = preflop.walk_tree(capture)['nodes']['']
    assert (root['seat'], root['pot'], root['stack'], root['to_call']) == ('UTG', 3.5, 100, 2)
    assert [a['label'] for a in root['actions']] == ['Allin', 'Raise 7', 'Fold']
    assert root['hands']['AA'] == [0, 1, 0] and root['hands']['KK'] == [0, .5, .5] and root['hands']['72o'] == [0, 0, 1]
    assert root['actions'][1]['combos'] == 10 and root['actions'][1]['frequency'] == round(10 / 1326, 4)


def test_a_class_the_seat_does_not_hold_is_left_out(capture):
    node = preflop.walk_tree(capture)['nodes']['R7-F-F-F-F-F-F-RAI']
    assert set(node['hands']) == {'AA', 'KK'}


def test_a_heads_up_line_multiplies_each_seat_along_its_own_actions(capture):
    line = preflop.walk_tree(capture)['lines']['R7-F-F-F-F-F-F-C']
    assert (line['oop_seat'], line['ip_seat']) == ('STR', 'UTG')  # Heads-up the straddle acts before UTG.
    assert (line['pot'], line['stack']) == (15.5, 93)
    assert line['ip'] == 'AA,KK:0.5' and line['ip_combos'] == 9
    assert line['oop'] == 'QQ:0.75,JJ' and line['oop_combos'] == 10.5
    assert line['label'] == 'UTG 开池 7bb · STR 跟注'


def test_a_side_that_almost_never_gets_here_is_flagged_on_a_tree(capture):
    capture['nodes']['']['cells'] = ['2'] * 169
    capture['nodes']['']['cells'][preflop.CLASSES.index('AA')] = '1:2000;2:8000'
    line = preflop.walk_tree(capture)['lines']['R7-F-F-F-F-F-F-C']
    assert line['rare'] and line['label'].endswith('（几乎不出现）')


def test_a_called_shove_has_no_flop(capture):
    book = preflop.walk_tree(capture)
    key = 'R7-F-F-F-F-F-F-RAI-C'
    assert key not in book['lines'] and book['ends'][key]['kind'] == 'allin'
    assert 'UTG、STR 翻前全下，底池 201.5bb' in book['ends'][key]['text']


def test_three_players_at_the_flop_are_not_a_line(capture):
    book = preflop.walk_tree(capture)
    key = 'R7-C-F-F-F-F-F-C'
    assert key not in book['lines'] and book['ends'][key]['kind'] == 'multiway'
    assert '3 人入池（UTG、LJ、STR），底池 22.5bb' in book['ends'][key]['text']


def test_a_hand_that_ends_with_folds_says_who_won(capture):
    end = preflop.walk_tree(capture)['ends']['R7-F-F-F-F-F-F-F']
    assert end == {'kind': 'won', 'text': 'UTG 收下底池 10.5bb，这手牌在翻前结束。'}


def test_an_action_with_no_page_behind_it_cannot_be_followed(capture):
    node = preflop.walk_tree(capture)['nodes']['R7']
    assert node['actions'][0]['next'] is None and '没有抄录' in node['actions'][0]['note']
    assert node['actions'][1]['next'] == 'R7-C' and 'note' not in node['actions'][1]


def test_a_closing_action_nobody_takes_is_not_a_line(capture):
    capture['nodes']['R7-F-F-F-F-F-F-RAI']['actions'][1][3] = 0
    book = preflop.walk_tree(capture)
    assert 'R7-F-F-F-F-F-F-RAI-F' not in book['ends']
    assert book['nodes']['R7-F-F-F-F-F-F-RAI']['actions'][1]['next'] is None


def test_a_depth_with_a_tree_does_not_use_its_library(builder, capture, tmp_path, monkeypatch):
    monkeypatch.setattr(preflop, 'FOLDER', tmp_path)
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'raw' / 'tree_100.json').write_text(json.dumps(capture), encoding='utf-8')
    (tmp_path / 'raw' / 'tree_bad.json').write_text('{', encoding='utf-8')
    (tmp_path / 'good.json').write_text(json.dumps(builder.build(RAW, META)), encoding='utf-8')
    books = preflop.walks()
    assert [(book['depth'], book.get('complete')) for book in books] == [(100, True)]
    other = dict(capture, depth=150)
    (tmp_path / 'raw' / 'tree_150.json').write_text(json.dumps(other), encoding='utf-8')
    (tmp_path / 'raw' / 'tree_100.json').unlink()
    assert [(book['depth'], book.get('complete')) for book in preflop.walks()] == [(100, None), (150, True)]


def test_a_later_capture_of_a_depth_adds_nodes(capture, tmp_path, monkeypatch):
    monkeypatch.setattr(preflop, 'FOLDER', tmp_path)
    (tmp_path / 'raw').mkdir()
    extra = tree_node('HJ', [('F', 1326)], '0')
    nodes = {key: value for key, value in capture['nodes'].items() if key != 'R7-C'}
    (tmp_path / 'raw' / 'tree_100.json').write_text(json.dumps(dict(capture, nodes=nodes)), encoding='utf-8')
    (tmp_path / 'raw' / 'tree_100_more.json').write_text(json.dumps({'depth': 100, 'nodes': {'R7-C': extra}}), encoding='utf-8')
    trees = preflop.load_trees()
    assert len(trees) == 1 and len(trees[0]['nodes']) == len(capture['nodes'])
    assert trees[0]['names'] == capture['names']


TREES = preflop.load_trees()


@pytest.mark.parametrize('tree', TREES, ids=lambda tree: f"{tree['depth']}bb")
def test_a_private_capture_adds_up_to_what_its_pages_showed(tree):
    for key, source in tree['nodes'].items():
        tokens = key.split('-') if key else []
        assert source['seat'] == preflop.replay(tokens, tree['depth'])['seat'], key
        reach = preflop.chained(tree, tokens, source['seat'])
        totals = [0.0] * len(source['actions'])
        for name, cell in zip(tree['names'], source['cells']):
            shares = preflop.cell_shares(cell, len(totals))
            if shares is None:
                continue
            assert sum(shares) == pytest.approx(1, abs=.001), (key, name)
            for at, share in enumerate(shares):
                totals[at] += preflop.class_combos(name) * reach[name] * share
        assert totals == pytest.approx([action[3] for action in source['actions']], abs=.05), key


@pytest.mark.skipif(not TREES, reason='private captures are not in Git')
def test_chained_ranges_match_the_ranges_read_from_the_flop_pages():
    trees = {tree['depth']: preflop.walk_tree(tree) for tree in preflop.load_trees()}
    compared = 0
    for library in preflop.load_libraries():
        depth = int(library['id'].split('_')[-2].removesuffix('bb'))
        for line in library['lines'] if depth in trees else ():
            ours = trees[depth]['lines'].get(line['actions'])
            if ours is None:  # A line under 0.3 combos before the flop was not followed.
                assert line['rare'], line['actions']
                continue
            assert (ours['oop_seat'], ours['ip_seat'], ours['pot'], ours['stack']) == (line['oop_seat'], line['ip_seat'], line['pot'], line['stack'])
            for side in ('oop', 'ip'):
                mine, page = preflop.weights(ours[side]), preflop.weights(line[side])
                for name in set(mine) | set(page):  # The library kept two decimals.
                    assert mine.get(name, 0) == pytest.approx(page.get(name, 0), abs=.0051), (line['actions'], side, name)
            compared += 1
    assert compared


def test_walking_a_tree_shows_every_action_and_what_cannot_be_solved(capture, tmp_path, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setattr(preflop, 'FOLDER', tmp_path)
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'raw' / 'tree_100.json').write_text(json.dumps(capture), encoding='utf-8')
    server = make_server(0, agent_dir=tmp_path / 'agent')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1550, 'height': 1100})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            expect = playwright.expect
            expect(page.locator('#board')).to_have_value('9h 8h 2c')
            active = page.locator('.walk-seat.active')
            expect(active).to_contain_text('UTG 100', timeout=30000)
            expect(active.locator('button[data-code="RAI"]')).to_be_disabled()
            expect(active.locator('button[data-code="RAI"]')).to_have_attribute('title', preflop.UNREAD)
            expect(page.locator('#walk-side')).not_to_contain_text('Fold 这一档包含')
            expect(page.locator('#walk-grid [data-hand="KK"]')).to_have_attribute('title', 'KK · Allin 0.0% · Raise 7 50.0% · Fold 50.0%')
            active.locator('button[data-code="R7"]').click()
            expect(active.locator('button[data-code="R16"]')).to_be_disabled()
            active.locator('button[data-code="F"]').click()
            for seat in ('HJ', 'CO', 'BTN', 'SB', 'BB'):
                expect(active).to_contain_text(seat)
                active.locator('button[data-code="F"]').click()
            expect(active).to_contain_text('STR 98')
            active.locator('button[data-code="C"]').click()
            expect(page.locator('#pot')).to_have_value('15.5')
            expect(page.locator('#range0')).to_have_value('QQ:0.75,JJ')
            expect(page.locator('#range1')).to_have_value('AA,KK:0.5')
            page.locator('#walk-back').click()
            active.locator('button[data-code="RAI"]').click()
            expect(active).to_contain_text('UTG')
            active.locator('button[data-code="C"]').click()
            expect(page.locator('#walk-side .walk-end')).to_contain_text('翻前全下，底池 201.5bb')
            expect(page.locator('.walk-flop')).to_contain_text('结束')
            expect(page.locator('#walk-solve')).to_have_count(0)
            page.locator('#walk-back').click()
            expect(page.locator('#walk-side .walk-end')).to_have_count(0)
            active.locator('button[data-code="F"]').click()
            expect(page.locator('#walk-side .walk-end')).to_contain_text('STR 收下底池')
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        server.jobs.close()
        thread.join(timeout=5)
    assert errors == []


def test_walking_a_line_fills_the_scene_and_edits_can_be_restored(builder, tmp_path, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setattr(preflop, 'FOLDER', tmp_path)
    (tmp_path / 'good.json').write_text(json.dumps(builder.build(RAW, META)), encoding='utf-8')
    server = make_server(0, agent_dir=tmp_path / 'agent')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1550, 'height': 1100})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            expect = playwright.expect
            expect(page.locator('#board')).to_have_value('9h 8h 2c')
            expect(page.locator('.walk-depths [data-depth="100"]')).to_be_enabled(timeout=30000)
            expect(page.locator('.walk-depths [data-depth="400"]')).to_be_disabled()
            active = page.locator('.walk-seat.active')
            expect(active).to_contain_text('UTG 100')
            for code in ('F', 'R7'):  # LJ to CO have no other line in this small library, so they step aside.
                active.locator(f'button[data-code="{code}"]').click()
            expect(active).to_contain_text('STR')
            expect(page.locator('#walk-grid [data-hand="AA"]')).to_have_attribute('title', 'AA · Raise 21 100.0% · Call 0.0% · Fold 0.0%')
            page.locator('#walk-side .action-card[data-code="R21"]').click()
            expect(active).to_contain_text('BTN')
            active.locator('button[data-code="C"]').click()
            expect(page.locator('.walk-flop.active')).to_contain_text('底池 43.5bb · 9h 8h 2c')
            expect(page.locator('#pot')).to_have_value('43.5')
            expect(page.locator('#stack')).to_have_value('79')
            expect(page.locator('#range0')).to_have_value('AA,KK,AKs:0.5')
            expect(page.locator('#range1')).to_have_value('QQ:0.25,AKo')
            expect(page.locator('#amount-unit')).to_have_value('bb')
            expect(page.locator('#walk-side')).to_contain_text('OOP = STR（14.0 组合），IP = BTN（13.5 组合）')
            expect(page.locator('#walk-ranges [data-hand="AKs"]').first).to_have_attribute('title', 'AKs · 50.0%')
            page.locator('#range0').fill('AA')
            expect(page.locator('#walk-side')).to_contain_text('已手动修改')
            page.get_by_role('button', name='恢复这条线').click()
            expect(page.locator('#range0')).to_have_value('AA,KK,AKs:0.5')
            expect(page.locator('#walk-side')).not_to_contain_text('已手动修改')
            page.locator('#walk-back').click()
            expect(active).to_contain_text('BTN')
            expect(page.locator('#walk-ranges')).to_be_hidden()
            page.locator('#walk-reset').click()
            expect(active).to_contain_text('UTG 100')
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        server.jobs.close()
        thread.join(timeout=5)
    assert errors == []
