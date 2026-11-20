import copy
from itertools import product
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from pokerlab.solver.__main__ import ROOT
from pokerlab.solver.workbench import solve_cached,inspect,new_job_dir,execute,baseline_key
from pokerlab.solver.reference import cards,river_matrix

pytestmark=pytest.mark.skipif(os.environ.get('POKERLAB_NATIVE')!='1',reason='native integration opt-in')

def config():return json.loads((ROOT/'examples/station_overbluff.json').read_text())

def test_compressed_snapshot_cache_preserves_frozen_strategy():
    c=config();c.update(pot=27,compression=True,auto_suits=True,expand_suits=True,threads=4)
    first=solve_cached(c);second=solve_cached(c)
    assert second['cache']['baseline_hit']
    for variant in ('baseline','model','response'):
        with (ROOT/first['artifacts'][variant]).open('rb') as stream:
            assert stream.read(8)==b'PLPOL003'
    assert first['hero_best_response_ev']==second['hero_best_response_ev']
    assert first['same_model_baseline_hero_ev']==second['same_model_baseline_hero_ev']
    for path in ([],[0],[1],[0,1]):
        assert inspect(first,path)['strategy_action_major']==inspect(second,path)['strategy_action_major']
    assert first['opponent_unchanged'] and second['opponent_unchanged']

def mixed_plans(probabilities):
    return np.array([np.prod([p if bit else 1-p for bit,p in zip(plan,probabilities)]) for plan in product([0,1],repeat=len(probabilities))])

@pytest.mark.parametrize('compressed', [False, True])
def test_exported_policy_independent_evaluation_and_cache(compressed):
    c=config();c.update(compression=compressed,auto_suits=True,expand_suits=True,threads=4);result=solve_cached(c)
    root=inspect(result,[])
    ip_check=inspect(result,[0])
    hero_facing=inspect(result,[0,1])
    ip_bet=inspect(result,[1])
    ranges=[[('AsAh',1),('QhJh',1)],[('KsKh',1),('TcTd',1),('AcJd',1)]]
    def prob(node,player,combo,action):
        combos=node['players'][player]['combos'];h=next(i for i,s in enumerate(combos) if set(cards(s))==set(cards(combo)))
        return node['strategy_action_major'][node['actions'].index(action)*len(combos)+h]
    p0=[];p1=[]
    for h,_ in ranges[0]:p0.extend([prob(root,0,h,'Bet(10)'),prob(hero_facing,0,h,'Call')])
    for h,_ in ranges[1]:p1.extend([prob(ip_check,1,h,'Bet(10)'),prob(ip_bet,1,h,'Call')])
    matrix=river_matrix(''.join(c['board']),ranges,20,10)
    independently_evaluated=float(mixed_plans(p0) @ matrix @ mixed_plans(p1))
    assert independently_evaluated==pytest.approx(result['hero_best_response_ev'],abs=1e-4)
    assert result['policy_validation']['absolute_error']<result['policy_validation']['tolerance_chips']
    changed=copy.deepcopy(c);changed['profile']['traits'][0]['strength']=1
    second=solve_cached(changed)
    assert second['cache']['baseline_hit'] is True
    assert baseline_key(c)==baseline_key(changed)
    changed['bets'][2]='50%'
    assert baseline_key(c)!=baseline_key(changed)
    # An exported decision is a single distribution for the hero hand, independent
    # of which villain hand is later used by this evaluator.
    assert all(p in (0,1) for p in p0)

@pytest.mark.parametrize('compressed', [False, True])
def test_raise_to_contributions_min_raise_allin_refund(compressed):
    c=config();c['profile']={'traits':[]};c['raises']=['2x','2x','2x']
    c['compression']=compressed
    c['players']=['AsAh','KcKd'];c['board']=['Ac','Ad','2h','3s','4c']
    c['profile']['overrides']=[{'path':[1],'combo':'KcKd','probabilities':[0,0,1]}, {'path':[1,2,2],'combo':'KcKd','probabilities':[.5,.5]}]
    r=solve_cached(c)
    bet=inspect(r,[1]);assert bet['contributions']==[10,0]
    assert 'Raise(20)' in bet['actions']
    raised=inspect(r,[1,bet['actions'].index('Raise(20)')])
    assert raised['contributions']==[10,20] and raised['pot']==50
    assert 'AllIn(30)' in raised['actions']
    shoved_path=[1,bet['actions'].index('Raise(20)'),raised['actions'].index('AllIn(30)')]
    shoved=inspect(r,shoved_path)
    assert shoved['contributions']==[30,20] and shoved['actions']==['Fold','Call']
    folded=inspect(r,shoved_path+[0])
    assert folded['terminal_root_net_ev'][0][0]==pytest.approx(40)
    assert folded['terminal_root_net_ev'][1][0]==pytest.approx(-20)
    called=inspect(r,shoved_path+[1])
    assert called['terminal_root_net_ev'][0][0]==pytest.approx(50)
    assert called['terminal_root_net_ev'][1][0]==pytest.approx(-30)

def test_cancel_native_group_and_timeout():
    c=config();folder=new_job_dir();(folder/'cancel').touch()
    # Cancellation is honored even before a very short task starts.
    with pytest.raises(RuntimeError,match='cancel'):
        execute(c,folder)
    # Pre-launch cancellation is handled before any native process is created.
    assert not (folder/'worker.json').exists()
    c=json.loads((ROOT/'examples/flop_research.json').read_text());folder=new_job_dir()
    with pytest.raises(RuntimeError,match='timeout'):
        execute(c,folder,timeout=.01)
    status=json.loads((folder/'worker.json').read_text())
    assert status['state']=='timeout' and status['process_reaped']

@pytest.mark.parametrize('compressed', [False, True])
def test_manual_override_priority_conflict_and_zero_reach(compressed):
    c=config();override={'path':[1],'combo':'AcJd','probabilities':[.1,.9]}
    c.update(compression=compressed,auto_suits=True,expand_suits=True)
    c['profile']['overrides']=[override]
    result=solve_cached(c)
    n=inspect(result,[1]);h=n['players'][1]['combos'].index('AcJd')
    assert n['strategy_action_major'][len(n['players'][1]['combos'])+h]==pytest.approx(.9)
    c['profile']['traits'].reverse();c['profile']['traits'][0]['strength']=5
    altered=solve_cached(c);n=inspect(altered,[1])
    assert n['strategy_action_major'][len(n['players'][1]['combos'])+h]==pytest.approx(.9)
    c['profile']['overrides'].append(copy.deepcopy(override))
    with pytest.raises(RuntimeError,match='conflicting'):solve_cached(c)
    c=json.loads((ROOT/'examples/flop_barrel.json').read_text());c['profile']['fixture_river_bet']=1
    r=solve_cached(c);chance=inspect(r,[1,1]);assert chance['chance']
    available={v['card']:v['id'] for v in chance['possible_cards']}
    assert 'Ac' not in available and 'As' not in available and 'Kc' not in available
    turn=inspect(r,[1,1,available['3s']])
    assert all(w==0 for w in turn['players'][0]['raw_reach'])
    with pytest.raises(RuntimeError,match='illegal chance'):inspect(r,[1,1,48])


@pytest.mark.parametrize('compressed', [False, True])
def test_asymmetric_cross_street_locks_and_independent_chance_value(compressed):
    # Quads always win. Normal river best response earns 5 extra chips;
    # on exactly one runout, the locked IP bet lets Hero earn 10 instead.
    c=json.loads((ROOT/'examples/flop_barrel.json').read_text())
    c.update(compression=compressed,auto_suits=True)
    c['expand_suits']=True;c['profile']['fixture_river_bet']=0
    c['board']=['Ac','Ad','2h','3h']
    river_c=8;river_d=9
    path=[0,1,1,river_c,0]
    c['profile']['overrides']=[{'path':path,'combo':'KcKd','probabilities':[0,1]}]
    r=solve_cached(c)
    assert r['tree']['suit_isomorphism'] is False
    assert r['ev'][0]==pytest.approx(35+5/44,abs=.0002)
    assert inspect(r,path)['strategy_action_major']==pytest.approx([0,1])
    assert inspect(r,[0,1,1,river_d,0])['strategy_action_major']==pytest.approx([1,0])
    assert r['policy_validation']['absolute_error']<=r['policy_validation']['tolerance_chips']
    # Flop: probability of the specified ordered turn/river pair is 1/(45*44).
    c['board']=['Ac','Ad','2h']
    c['profile']['overrides'][0]['path']=[0,1,1,6,0,1,1,river_c,0]
    flop=solve_cached(c)
    assert flop['ev'][0]==pytest.approx(45+5/(45*44),abs=.0003)
    assert flop['opponent_unchanged']
    assert flop['hero_improvement']>=-.001
    # Reject a lock whose hole cards conflict with the selected runout.
    c['profile']['overrides'][0]['path']=[0,1,1,44,0]
    with pytest.raises(RuntimeError,match='chance card|conflicts'):solve_cached(c)


def test_expanded_neutral_matches_original_equilibrium():
    c=json.loads((ROOT/'examples/flop_research.json').read_text())
    c['board'].append('3c');c['mode']='equilibrium';c['profile']={'traits':[]}
    c['target']=.05
    merged=solve_cached(c);c['expand_suits']=True;expanded=solve_cached(c)
    assert expanded['ev'][0]==pytest.approx(merged['ev'][0],abs=.1)
    assert expanded['precision']['actual_chips']<=.05
    assert expanded['tree']['expanded_canonical_nodes']>=merged['tree']['expanded_canonical_nodes']


def test_lock_scene_signature_and_node_cache():
    c=config();c['expand_suits']=True
    scene={k:c.get(k,[]) for k in ('board','players','pot','stack','bets','raises','hero')}
    c['profile']['overrides']=[{'path':[1],'combo':'AcJd','probabilities':[.1,.9],
                              'scene':scene,'actions':['Fold','Call'],'board':c['board']}]
    r=solve_cached(c);first=inspect(r,[1]);second=inspect(r,[1])
    assert second['query']['cache_hit']
    assert first['strategy_action_major']==second['strategy_action_major']
    from pokerlab.solver.__main__ import save_result
    save_result(ROOT/'outputs/node-query-benchmark.json',{'first':first['query'],'repeat':second['query'],'same_strategy':True})
    c['pot']+=1
    with pytest.raises(RuntimeError,match='different scene/tree'):solve_cached(c)


def test_sensitivity_serial_models_and_parent_cancel():
    from pokerlab.solver.research import sensitivity
    c=config();folder=new_job_dir();states=[]
    result=sensitivity(c,folder,lambda i,label:states.append(i))
    assert states==[0,1,2]
    assert len(result['records'])==3
    for record in result['records']:
        r=record['report']
        assert r['opponent_unchanged']
        assert r['hero_improvement']>=-.001
        assert r['policy_validation']['absolute_error']<=r['policy_validation']['tolerance_chips']
    assert result['records'][1]['report']['cache']['baseline_hit']
    cancelled=new_job_dir();(cancelled/'cancel').touch()
    with pytest.raises(RuntimeError,match='cancelled'):sensitivity(c,cancelled,lambda *args:None)


def test_position_specific_sizes_and_donk_tree():
    c=config();c['expand_suits']=True;c['profile']={'traits':[]}
    c['bets_ip']=['7c','7c','7c'];c['raises_ip']=['2.5x']*3;c['raises']=['2x']*3
    r=solve_cached(c)
    assert 'Bet(7)' in inspect(r,[0])['actions']
    assert 'Raise(25)' in inspect(r,[1])['actions']
    other=copy.deepcopy(c);other['bets_ip'][2]='8c'
    assert baseline_key(c)!=baseline_key(other)
    c=json.loads((ROOT/'examples/flop_barrel.json').read_text())
    c['expand_suits']=True;c['donks']=['2c','']
    r=solve_cached(c)
    turn=inspect(r,[0,1,1,7])
    assert turn['board'][-1]=='3s'
    assert turn['actions']==['Check','Bet(2)']
