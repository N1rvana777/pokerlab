"""Flop reports: one tree solved on many boards, with the root numbers side by side.

Nothing is written to the policy cache, because a report keeps only these numbers and a policy file costs gigabytes.
Finished rows are kept by key, so a report that stopped halfway continues where it was.
"""
import copy
import json
import re

from .__main__ import ROOT, save_result
from .workbench import execute, fingerprint, solve_inputs

SCHEMA='pokerlab-flop-report-v1'
CACHE=ROOT/'outputs/flop-reports'
# High and low cards, dry and wet, paired, connected and monotone; enough to see how a line reacts to texture.
PRESET=('Ks7d2c','As8d3c','Qh7d2c','Jc6d2h','Td5c2h','9d5c2h','8d4c2h','7d4c2h',
        'Ks7s2c','As8s3c','Qh7h2c','Jh6h2c','Th9h8c','9h8h7c','8h7h6c',
        'KsKd7c','AsAd5c','7s7d2c','2s2d7c',
        'Th9d8c','9h8d7c','8h7d6c','JhTd9c','QhJdTc','AhKdQc',
        'Ks7s2s','Th9h4h','8s7s3s','7s7d7c')


def cards(board):
    if not re.fullmatch(r'(?:[2-9TJQKA][cdhs]){3}',board):raise ValueError(f'无效翻牌：{board}')
    found=[board[i:i+2] for i in (0,2,4)]
    if len(set(found))!=3:raise ValueError(f'翻牌有重复：{board}')
    return found


def seat_numbers(player,pot):
    weights=player['blocker_adjusted_weights'];total=sum(weights)
    if total<=0:return {'combos':0,'ev':None,'equity':None,'eqr':None}
    ev=sum(w*v for w,v in zip(weights,player['ev']))/total
    equity=sum(w*v for w,v in zip(weights,player['equity']))/total
    combos=sum(r for r,w in zip(player['raw_reach'],weights) if w>0)
    return {'combos':combos,'ev':ev,'equity':equity,'eqr':ev/(equity*pot) if equity>0 else None}


def root_row(board,result):
    """Frequencies count combos and averages use blocker weights, as on the node page."""
    root=result['root'];row={'board':board,'seconds':result['timing']['total_seconds'],'precision_pct':result['precision']['actual_pot_pct']}
    row['seats']=[seat_numbers(player,root['pot']) for player in root['players']]
    actor=root['players'][root['actor']];count=len(actor['combos'])
    reach=[r if w>0 else 0 for r,w in zip(actor['raw_reach'],actor['blocker_adjusted_weights'])];total=sum(reach) or 1
    row['actions']=root['actions']
    row['frequencies']=[sum(reach[i]*root['strategy_action_major'][a*count+i] for i in range(count))/total for a in range(len(root['actions']))]
    return row


def solve_board(config,board,folder):
    request=copy.deepcopy(config);request.update(board=cards(board),mode='equilibrium',profile={'traits':[]})
    key=fingerprint({'schema':SCHEMA,'config':{k:v for k,v in request.items() if k not in ('memory_budget_mb','memory_auto','memory_stretch')}})
    path=CACHE/f'{key}.json'
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    row=root_row(board,execute(request,folder))
    save_result(path,row)
    return row


def flop_report(config,boards,folder,progress):
    if not isinstance(boards,list) or not boards or len(boards)>2000:raise ValueError('请提供 1–2000 个翻牌')
    for board in boards:cards(board)
    if solve_inputs(config):raise ValueError('多牌面报告只解均衡基线，先去掉节点锁和 Player Profile')
    rows=[]
    for index,board in enumerate(boards):
        if (folder/'cancel').exists():raise RuntimeError('cancelled')
        progress(index,len(boards),board)
        part=folder/f'board-{index:04d}';part.mkdir()
        rows.append(solve_board(config,board,part))
    return {'schema':SCHEMA,'config':config,'rows':rows}
