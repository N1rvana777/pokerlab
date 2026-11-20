"""Decimal bb over integer engine chips."""
import pytest

from pokerlab.solver.amounts import scale_action, scale_request, scale_result, scale_sizes


def test_request_scales_amounts_and_fixed_sizes_only():
    request = {'pot': 5.5, 'stack': 97.5, 'bets': ['33%,1.5c', '50%', 'a'], 'raises': ['3x', '3x', 'a'], 'bets_ip': [],
               'target': .5, 'target_unit': 'pot_pct', 'rake_cap': 3.0, 'rake_rate': .05, 'profile': {'traits': []}}
    scale_request(request, 100)
    assert (request['pot'], request['stack']) == (550, 9750)
    assert request['bets'] == ['33%,150c', '50%', 'a']
    assert request['raises'] == ['3x', '3x', 'a']
    assert request['target'] == .5
    assert request['rake_cap'] == 300 and request['rake_rate'] == .05


def test_chip_target_and_locks_follow_the_scale():
    request = {'pot': 10, 'stack': 90, 'bets': ['50%'] * 3, 'target': .05, 'target_unit': 'chips',
               'profile': {'overrides': [{'scene': {'pot': 10, 'stack': 90, 'bets': ['2c'] * 3}, 'actions': ['Check', 'Bet(2.5)']}]}}
    scale_request(request, 100)
    assert request['target'] == 5
    override = request['profile']['overrides'][0]
    assert (override['scene']['pot'], override['scene']['bets'][0]) == (1000, '200c')
    assert override['actions'] == ['Check', 'Bet(250)']


def test_scale_one_leaves_old_requests_alone():
    request = {'pot': 8, 'stack': 100, 'bets': ['10c'] * 3}
    assert scale_request(dict(request), 1) == request


def test_amount_finer_than_the_scale_is_refused():
    with pytest.raises(ValueError):
        scale_sizes('1.234c', 100)
    with pytest.raises(ValueError):
        scale_request({'pot': 5.555, 'stack': 90}, 100)


def test_action_labels():
    assert scale_action('Bet(182)', .01) == 'Bet(1.82)'
    assert scale_action('Raise(5.5)', 100) == 'Raise(550)'
    assert scale_action('AllIn(9750)', .01) == 'AllIn(97.5)'
    assert scale_action('Check', 100) == 'Check'


def test_report_returns_to_display_units():
    report = {'ev': [200.0, 350.0], 'hero_improvement': 25.0, 'precision': {'actual_chips': 2.5, 'target_chips': 2.75, 'actual_pot_pct': .45},
              'policy_validation': {'absolute_error': 1.0, 'method': 'x'},
              'root': {'pot': 550, 'contributions': [0, 0], 'remaining_stacks': [9750, 9750], 'actions': ['Check', 'Bet(182)'],
                       'action_details': [{'additional_contribution': 0, 'call_amount': 0, 'aggression_amount': 0, 'pot_after_call': 550, 'pot_fraction': None}],
                       'action_ev_action_major': [200.0, 210.0], 'strategy_action_major': [.5, .5], 'players': [{'ev': [100.0], 'equity': [.5]}]}}
    scale_result(report, 100)
    assert report['ev'] == [2, 3.5] and report['hero_improvement'] == .25
    assert report['precision']['actual_chips'] == .025 and report['precision']['actual_pot_pct'] == .45
    assert report['root']['pot'] == 5.5 and report['root']['actions'] == ['Check', 'Bet(1.82)']
    assert report['root']['action_ev_action_major'] == [2, 2.1] and report['root']['strategy_action_major'] == [.5, .5]
    assert report['root']['players'][0]['ev'] == [1] and report['root']['players'][0]['equity'] == [.5]
    assert report['root']['action_details'][0]['pot_after_call'] == 5.5
