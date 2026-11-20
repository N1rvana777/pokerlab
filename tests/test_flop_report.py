"""Flop reports: root numbers, resuming and what a report refuses."""
import json
import os

import pytest

from pokerlab.solver import reports
from pokerlab.solver.workbench import new_job_dir


def root():
    return {'pot':10,'actor':0,'actions':['Check','Bet(5)'],'strategy_action_major':[1,0,0,1],
            'players':[{'combos':['AsAh','KsKh'],'raw_reach':[1,.5],'blocker_adjusted_weights':[.2,.6],'ev':[10,0],'equity':[.9,.5]},
                       {'combos':['QsQh'],'raw_reach':[1],'blocker_adjusted_weights':[1],'ev':[4],'equity':[.4]}]}


def result():
    return {'root':root(),'timing':{'total_seconds':1.5},'precision':{'actual_pot_pct':.4}}


def test_root_row_counts_combos_and_weights_averages_by_blockers():
    row=reports.root_row('Ks7d2c',result())
    assert row['frequencies']==pytest.approx([1/1.5,.5/1.5])
    assert row['seats'][0]['ev']==pytest.approx(2.5)
    assert row['seats'][0]['equity']==pytest.approx(.6)
    assert row['seats'][0]['eqr']==pytest.approx(2.5/(.6*10))
    assert row['seats'][0]['combos']==pytest.approx(1.5)
    assert row['seats'][1]['eqr']==pytest.approx(4/(.4*10))


def test_a_seat_with_no_reach_has_no_averages():
    assert reports.seat_numbers({'blocker_adjusted_weights':[0],'ev':[0],'equity':[0],'raw_reach':[0]},10)['ev'] is None


@pytest.mark.parametrize('board',['Ks7d','Ks7d2c3h','KsKs2c','Xs7d2c'])
def test_bad_flops_are_refused(board):
    with pytest.raises(ValueError):reports.cards(board)


@pytest.mark.parametrize('profile',[{'incentives':{'call':6}}])
def test_a_report_only_solves_baselines(tmp_path,profile):
    with pytest.raises(ValueError,match='均衡基线'):
        reports.flop_report({'profile':profile},['Ks7d2c'],tmp_path,lambda *a:None)


def test_finished_boards_are_not_solved_again(tmp_path,monkeypatch):
    calls=[];monkeypatch.setattr(reports,'CACHE',tmp_path/'cache')
    monkeypatch.setattr(reports,'execute',lambda request,folder:calls.append(request['board']) or result())
    config={'mode':'equilibrium','profile':{'traits':[]},'players':['AA','KK']}
    folder=tmp_path/'job';folder.mkdir()
    first=reports.flop_report(config,['Ks7d2c','Th9h8c'],folder,lambda *a:None)
    folder=tmp_path/'job2';folder.mkdir()
    second=reports.flop_report(config,['Ks7d2c','Th9h8c'],folder,lambda *a:None)
    assert calls==[['Ks','7d','2c'],['Th','9h','8c']]
    assert json.dumps(first['rows'],sort_keys=True)==json.dumps(second['rows'],sort_keys=True)


def test_a_cancelled_report_stops_between_boards(tmp_path):
    (tmp_path/'cancel').touch()
    with pytest.raises(RuntimeError,match='cancelled'):
        reports.flop_report({'mode':'equilibrium','profile':{'traits':[]}},['Ks7d2c'],tmp_path,lambda *a:None)


@pytest.mark.skipif(os.environ.get('POKERLAB_NATIVE')!='1',reason='native integration opt-in')
def test_a_small_report_runs_on_the_engine(tmp_path,monkeypatch):
    monkeypatch.setattr(reports,'CACHE',tmp_path/'cache')
    config={'schema_version':1,'players':['AA,KK,QQ','JJ,TT,99'],'pot':10,'stack':20,'bets':['50%','',''],'raises':['','',''],'hero':0,'mode':'equilibrium',
            'target':.5,'target_unit':'pot_pct','max_iterations':200,'memory_budget_mb':2048,'threads':4,'compression':True,'auto_suits':True,'expand_suits':True,'profile':{'traits':[]},'board':[]}
    folder=new_job_dir()
    data=reports.flop_report(config,['Ks7d2c','Th9h8c'],folder,lambda *a:None)
    assert [row['board'] for row in data['rows']]==['Ks7d2c','Th9h8c']
    assert sum(data['rows'][0]['frequencies'])==pytest.approx(1,abs=1e-5)
    assert data['rows'][0]['seats'][0]['equity']>.5
    assert not list(folder.rglob('*.policy'))
