"""Hand classes behind the node filters, checked against hands worked out by eye."""
import pytest

from pokerlab.solver.hand_classes import EQUITY_ADVANCED, annotate, classify, draw_class, hand_class, parse, split_combo


def made(combo, board):
    return hand_class(split_combo(combo), [parse(board[i:i + 2]) for i in range(0, len(board), 2)])


def draw(combo, board):
    return draw_class(split_combo(combo), [parse(board[i:i + 2]) for i in range(0, len(board), 2)])


@pytest.mark.parametrize('combo,board,expected', [
    ('AhKh', 'QhJhTh', 'straight_flush'),
    ('9h8h', 'QhJhTh', 'straight_flush'),
    ('2c2d', 'AhKhQhJhTh', 'fifth_pair'),
    ('9s9d', '9c9h2d', 'quads'),
    ('9s2c', '9c9h2d', 'full_house'),
    ('AsAd', 'KsKcKh5c5d', 'full_house'),
    ('7s2c', 'KsKcKh5c5d', 'no_made_hand'),
    ('As2s', 'KsTs5s', 'flush'),
    ('2s3d', 'AsKsQsJs9s', 'no_made_hand'),
    ('Ts9d', 'AsKsQs7s5s', 'flush'),
    ('6d5c', '9h8s7d', 'straight'),
    ('As2c', '3d4h5s', 'straight'),
    ('Ad2c', 'TsJsQsKhAh', 'top_pair'),
    ('9s9d', '9c5h2d', 'set'),
    ('9s8d', '9c9h2d', 'trips'),
    ('Ks9d', 'KcTh9c', 'two_pair'),
    ('AsAd', 'KcTh9c', 'overpair'),
    ('QsQd', 'KcTh9c', 'second_pair'),
    ('Ks7d', 'KcTh9c', 'top_pair'),
    ('Ts7d', 'KcTh9c', 'second_pair'),
    ('9s7d', 'KcTh9c', 'third_pair'),
    ('7s7d', 'KcTh9c', 'fourth_pair'),
    ('7s4d', 'KcTh9c7d', 'fourth_pair'),
    ('6s4d', 'KcTh9c7d6d', 'fifth_pair'),
    ('Ks7d', 'Kc5h5c', 'top_pair'),
    ('5s7d', 'KcKh5c', 'second_pair'),
    ('As7d', 'Kc9h5c', 'ace_high'),
    ('Ks7d', 'Ac9h5c', 'king_high'),
    ('Qs7d', 'Ac9h5c', 'no_made_hand'),
])
def test_made_hand(combo, board, expected):
    assert made(combo, board) == expected


@pytest.mark.parametrize('combo,board,expected', [
    ('AsKs', 'Qs7s2d', 'flush_draw_nuts'),
    ('KsTs', 'As7s2d', 'flush_draw_nuts'),
    ('QsTs', 'As7s2d', 'flush_draw'),
    ('9s8s', 'Ts7s2d', 'combo_draw'),
    ('Js9c', 'Ts8d2h', 'oesd'),
    ('Qc6c', 'Td8d7h', 'gutshot'),
    ('Ah6d', 'Tc8c4s', 'no_draw'),
    ('AsKs', 'Qs7d2d', 'bdfd_2'),
    ('As7c', 'Qs9s2d', 'bdfd_1'),
    ('5d4c', '9s8h2d', 'bdsd'),
    ('4d3c', '9s8h2d', 'no_draw'),
    ('6d4c', '9s8h2d', 'no_draw'),
    ('KdQc', '9s8h2d', 'no_draw'),
    ('AsKs', 'Qs7s2d3s', 'no_draw'),
    ('AsKd', 'Qs7s2s3d', 'flush_draw_nuts'),
    ('Js9c', 'Ts8d2h3c', 'oesd'),
    ('AsKs', 'Qs7s2d3c', 'flush_draw_nuts'),
    ('AsKs', 'Qs7d2d3c', 'no_draw'),
    ('AsKs', 'Qs7s2d3c4h', 'no_draw'),
])
def test_draw(combo, board, expected):
    assert draw(combo, board) == expected


def test_board_only_straight_is_nobodys_draw():
    assert draw('As2c', '5c6d7h8s') == 'no_draw'


def test_classes_are_exclusive_and_blocked_combos_are_skipped():
    board = ['Ks', '7d', '2c', '9h']
    combos = ['AsAd', 'KhQh', '9d9c', 'Ks3d']
    out = classify(combos, board, [.85, .76, .9, 0])
    assert [out[key][3] for key in out] == [None] * 4
    assert all(value is not None for key in out for value in out[key][:3])
    assert out['equity_simple'][:3] == [0, 0, 0]
    assert out['equity_advanced'][:2] == [1, 2]


def test_a_hand_with_no_equity_can_round_below_zero():
    out = classify(['5c4c'], ['Ks', '7d', '2c', '9h'], [-5.96e-08])
    assert out['equity_simple'] == [3]
    assert out['equity_advanced'] == [len(EQUITY_ADVANCED) - 1]


def test_annotate_covers_both_players_and_skips_other_nodes():
    node = {'board': ['Ks', '7d', '2c'], 'players': [{'combos': ['AsAd'], 'equity': [.8]}, {'combos': ['QhQd'], 'equity': [.2]}]}
    annotate(node)
    labels = node['class_labels']
    assert labels['hand'][node['players'][0]['classes']['hand'][0]] == 'Overpair'
    assert labels['hand'][node['players'][1]['classes']['hand'][0]] == 'Second pair'
    assert labels['equity_simple'][node['players'][1]['classes']['equity_simple'][0]] == 'Trash hands'
    terminal = {'terminal': True}
    assert annotate(terminal) == {'terminal': True}
