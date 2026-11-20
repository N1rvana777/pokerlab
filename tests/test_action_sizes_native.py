"""Independent contribution arithmetic for UI sizing and overbet colors."""
import json
import os
import pytest
from pokerlab.solver.__main__ import ROOT
from pokerlab.solver.workbench import solve_cached, inspect, execute

pytestmark=pytest.mark.skipif(os.environ.get('POKERLAB_NATIVE')!='1',reason='native integration opt-in')

@pytest.mark.parametrize('multiplier,raise_to,raise_fraction', [('5x',50,1.0),('6x',60,1.25)])
def test_reported_overbet_uses_raise_increment_after_call(multiplier,raise_to,raise_fraction):
    c=json.loads((ROOT/'examples/river.json').read_text())
    c.update(pot=20,stack=200,bets=['','','50%,100%,150%'],raises=['','',multiplier],
             mode='equilibrium',profile={},max_iterations=4,compression=True,auto_suits=True,
             threads=4,memory_auto=True,time_limit_seconds=0)
    r=solve_cached(c);root=r['root']
    by_action=dict(zip(root['actions'],root['action_details']))
    for bet,fraction in [(10,.5),(20,1),(30,1.5)]:
        details=by_action[f'Bet({bet})']
        assert details['additional_contribution']==bet
        assert details['pot_fraction']==pytest.approx(fraction)
        assert details['is_overbet']==(fraction>1)
    ip=inspect(r,[root['actions'].index('Bet(10)')])
    details=ip['action_details'][ip['actions'].index(f'Raise({raise_to})')]
    # Pot is 30, IP first calls 10, so the raise denominator is 40.
    assert details['call_amount']==10
    assert details['pot_after_call']==40
    assert details['additional_contribution']==raise_to
    assert details['aggression_amount']==raise_to-10
    assert details['pot_fraction']==pytest.approx(raise_fraction)
    assert details['is_overbet']==(raise_fraction>1)
    # Pure equilibrium does not persist two extra identical multi-GB policies.
    assert r['artifacts']['baseline']==r['artifacts']['model']==r['artifacts']['response']


def test_percentage_raise_is_the_increment_over_the_pot_after_call():
    c=json.loads((ROOT/'examples/river.json').read_text())
    c.update(pot=20,stack=200,bets=['','','50%'],raises=['','','60%'],mode='equilibrium',profile={},max_iterations=4,
             compression=True,auto_suits=True,threads=4,memory_auto=True,time_limit_seconds=0)
    r=solve_cached(c);root=r['root']
    ip=inspect(r,[root['actions'].index('Bet(10)')])
    # Pot 30, IP calls 10 into 40, and 60% of 40 adds 24 to the 10 already faced.
    details=ip['action_details'][ip['actions'].index('Raise(34)')]
    assert details['aggression_amount']==24
    assert details['pot_fraction']==pytest.approx(.6)


def test_small_budget_full_flop_does_not_exhaust_sparse_allocator_arenas():
    c=json.loads((ROOT/'examples/flop_research_raises.json').read_text())
    c.update(compression=True,auto_suits=True,expand_suits=True,threads=8,
             memory_budget_mb=384,memory_auto=False,max_iterations=2,time_limit_seconds=0,
             mode='fixed',profile={'traits':[{'kind':'station','strength':2,'streets':[3,4,5]}]})
    r=execute(c)
    assert r['worker_resources']['state']=='completed'
    assert r['worker_resources']['process_reaped']
    assert r['worker_resources']['malloc_arena_max']==2
    assert r['memory']['measured_native_peak_rss_bytes']<384*1024**2
    assert r['policy_validation']['absolute_error']<=r['policy_validation']['tolerance_chips']
