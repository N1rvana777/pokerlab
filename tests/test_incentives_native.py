"""Player profiles and locked re-solves on a river toy game whose answers can be worked out by hand."""
import json
import os

import pytest

from pokerlab.solver.__main__ import ROOT
from pokerlab.solver.workbench import baseline_key,inspect,solve_cached

pytestmark=pytest.mark.skipif(os.environ.get('POKERLAB_NATIVE')!='1',reason='native integration opt-in')

VALUE,BLUFF,CATCHER='7h7d','5h4h','AcQc'


def game(hero=0,**extra):
    """OOP has one value hand and one bluff, IP one bluff catcher; OOP may bet pot and IP may not bet."""
    return {'schema_version':1,'board':['Ks','Qd','7c','3s','2s'],'players':[f'{VALUE},{BLUFF}',CATCHER],'pot':100,'stack':100,
            'bets':['','','100%'],'raises':['','',''],'bets_ip':['','',''],'raises_ip':['','',''],'hero':hero,'mode':'preview',
            'target':.02,'target_unit':'pot_pct','max_iterations':20000,'memory_budget_mb':2048,'threads':4,'compression':True,
            'auto_suits':True,'expand_suits':True,'profile':{'traits':[]},**extra}


def share(node,player,combo,action):
    combos=node['players'][player]['combos'];hand=combos.index(combo)
    return node['strategy_action_major'][node['actions'].index(action)*len(combos)+hand]


def hand(text):
    """The engine writes the higher card first; these combos are already written that way."""
    return text


def bet(node):
    return next(a for a in node['actions'] if a.startswith(('Bet','AllIn')))


def test_equilibrium_of_the_toy_game():
    config=game(mode='equilibrium')
    result=solve_cached(config)
    root=inspect(result,[],'baseline')
    assert share(root,0,hand(VALUE),bet(root))==pytest.approx(1,abs=.01)
    assert share(root,0,hand(BLUFF),bet(root))==pytest.approx(.5,abs=.01)
    assert share(inspect(result,[root['actions'].index(bet(root))],'baseline'),1,hand(CATCHER),'Call')==pytest.approx(.5,abs=.01)


def test_call_incentive_moves_the_bluff_frequency_by_the_pot_including_the_bet():
    # Calling gains 6% of 200, so IP is indifferent at bluff share q = (100 - 12) / 300.
    config=game(profile={'traits':[],'incentives':{'call':6}})
    result=solve_cached(config)
    root=inspect(result,[],'baseline')
    q=88/300
    assert share(root,0,hand(BLUFF),bet(root))==pytest.approx(q/(1-q),abs=.01)
    facing=inspect(result,[root['actions'].index(bet(root))],'baseline')
    assert share(facing,1,hand(CATCHER),'Call')==pytest.approx(.5,abs=.01)
    assert result['precision']['baseline_metric']=='other_seat_response_gap'
    assert result['precision']['baseline_iterations']>=100


def test_fold_penalty_matches_the_same_call_incentive():
    # Losing 6% of the pot for folding moves the same indifference as gaining it for calling.
    root=inspect(solve_cached(game(profile={'traits':[],'incentives':{'fold':-6}})),[],'baseline')
    q=88/300
    assert share(root,0,hand(BLUFF),bet(root))==pytest.approx(q/(1-q),abs=.01)


def test_bet_incentive_on_oop_moves_the_call_frequency_by_the_current_pot():
    # OOP gains 6% of 100 for betting, so its bluff is indifferent when IP calls (100 + 6) / 200.
    result=solve_cached(game(hero=1,profile={'traits':[],'incentives':{'bet':6}}))
    root=inspect(result,[],'baseline')
    facing=inspect(result,[root['actions'].index(bet(root))],'baseline')
    assert share(facing,1,hand(CATCHER),'Call')==pytest.approx(.53,abs=.01)


def test_an_incentive_on_another_street_changes_nothing():
    root=inspect(solve_cached(game(profile={'traits':[],'incentives':{'call':6,'streets':[3,4]}})),[],'baseline')
    assert share(root,0,hand(BLUFF),bet(root))==pytest.approx(.5,abs=.01)


def test_an_incentive_on_this_street_works_as_before():
    q=88/300
    root=inspect(solve_cached(game(profile={'traits':[],'incentives':{'call':6,'streets':[5]}})),[],'baseline')
    assert share(root,0,hand(BLUFF),bet(root))==pytest.approx(q/(1-q),abs=.01)


def test_an_incentive_can_stop_at_the_turn():
    # The river call bonus reaches the turn bet through its value, so stopping it at the turn changes the turn.
    plain=dict(board=['Ks','Qd','7c','3s'],stack=400,bets=['','100%','100%'])
    later=solve_cached(game(**plain,max_iterations=3000,profile={'traits':[],'incentives':{'call':30}}))
    only=solve_cached(game(**plain,max_iterations=3000,profile={'traits':[],'incentives':{'call':30,'streets':[4]}}))
    root=[inspect(result,[],'baseline') for result in (later,only)]
    assert share(root[0],0,hand(BLUFF),bet(root[0]))!=pytest.approx(share(root[1],0,hand(BLUFF),bet(root[1])),abs=.01)


def test_incentives_do_not_enter_expected_values():
    # Against the biased seat the model EV must stay a plain chip count: IP's strategy only changes who wins.
    result=solve_cached(game(profile={'traits':[],'incentives':{'call':6}}))
    assert result['ev'][0]+result['ev'][1]==pytest.approx(100,abs=.01)


def test_fixed_mode_best_responds_to_the_profile():
    result=solve_cached(game(mode='fixed',profile={'traits':[],'incentives':{'call':6}}))
    assert result['precision']['stop_reason'] in ('target_met','numerical_floor')
    assert result['opponent_unchanged'] is True
    assert result['hero_best_response_ev']>=result['same_model_baseline_hero_ev']-1e-3


def test_baseline_cache_separates_profiles():
    plain,profiled=game(),game(profile={'traits':[],'incentives':{'call':6}})
    assert baseline_key(plain)!=baseline_key(profiled)
    assert baseline_key(profiled)!=baseline_key(game(profile={'traits':[],'incentives':{'call':3}}))
    assert baseline_key(profiled)!=baseline_key(game(profile={'traits':[],'incentives':{'call':6,'streets':[5]}}))


def locked(path,probabilities,**extra):
    return game(mode='locked',expand_suits=True,profile={'traits':[],'overrides':[{'path':path,'combo':CATCHER,'probabilities':probabilities}]},**extra)


def test_locked_call_stops_the_bluffs_and_the_other_seat_resolves():
    plain=inspect(solve_cached(game(mode='equilibrium')),[],'baseline')
    path=[plain['actions'].index(bet(plain))]
    result=solve_cached(locked(path,[0,1]))
    root=inspect(result,[],'baseline')
    assert share(root,0,hand(BLUFF),bet(root))==pytest.approx(0,abs=.01)
    assert share(root,0,hand(VALUE),bet(root))==pytest.approx(1,abs=.01)
    assert share(inspect(result,path,'baseline'),1,hand(CATCHER),'Call')==pytest.approx(1,abs=1e-5)
    assert result['artifacts']['model']==result['artifacts']['baseline']


def test_locked_fold_makes_every_hand_bet():
    plain=inspect(solve_cached(game(mode='equilibrium')),[],'baseline')
    path=[plain['actions'].index(bet(plain))]
    root=inspect(solve_cached(locked(path,[1,0])),[],'baseline')
    assert share(root,0,hand(BLUFF),bet(root))==pytest.approx(1,abs=.01)


def test_locked_cache_follows_the_locks():
    assert baseline_key(locked([1],[0,1]))!=baseline_key(locked([1],[1,0]))
    assert baseline_key(locked([1],[0,1]))!=baseline_key(game(mode='equilibrium'))


def test_a_hero_node_can_be_locked_in_a_locked_solve():
    # The lock belongs to OOP, the hero seat: bluffing every time makes IP call every time.
    config=game(mode='locked',profile={'traits':[],'overrides':[{'path':[],'combo':BLUFF,'probabilities':[0,1]}]})
    actions=inspect(solve_cached(game(mode='equilibrium')),[],'baseline')['actions']
    config['profile']['overrides'][0]['probabilities']=[float(a==bet({'actions':actions})) for a in actions]
    result=solve_cached(config)
    root=inspect(result,[],'baseline')
    facing=inspect(result,[actions.index(bet(root))],'baseline')
    assert share(root,0,hand(BLUFF),bet(root))==pytest.approx(1,abs=1e-5)
    assert share(facing,1,hand(CATCHER),'Call')==pytest.approx(1,abs=.01)
