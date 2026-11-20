"""Real-range Flop integration/performance study; no independent accuracy claim."""
import copy
import json
from pathlib import Path
import time
import sys
import argparse
sys.stdout.reconfigure(encoding='utf-8')

parser=argparse.ArgumentParser()
parser.add_argument('--allin-raises',action='store_true')
parser.add_argument('--combined-only',action='store_true')
parser.add_argument('--expanded',action='store_true')
parser.add_argument('--raise-multiplier',default='')
args=parser.parse_args()

from pokerlab.solver.__main__ import ROOT,save_result
from pokerlab.solver.workbench import solve_cached

base=json.loads((ROOT/'examples/flop_research.json').read_text())
if args.allin_raises:base['raises']=['a','a','a']
if args.expanded:base['expand_suits']=True
if args.raise_multiplier:base['raises']=[args.raise_multiplier]*3
stamp=str(time.time_ns())
folder=ROOT/'outputs'/f'flop-study-{stamp}';folder.mkdir()
variants=[('baseline',[]),('station',[base['profile']['traits'][0]]),('overbluff',[base['profile']['traits'][1]]),('combined_no_giveup',base['profile']['traits'][:2]),('combined_giveup',base['profile']['traits'])]
if args.combined_only:variants=[v for v in variants if v[0] not in ('station','overbluff')]
records=[]
for name,traits in variants:
    config=copy.deepcopy(base);config['profile']['traits']=traits
    if name=='baseline':config['mode']='equilibrium'
    print('START',name,flush=True)
    try:
        result=solve_cached(config,timeout=600)
        save_result(folder/f'{name}.json',result)
        records.append({'name':name,'result':result})
        print(name,result['ev'],result['timing'],result['memory'],result['precision'],flush=True)
    except Exception as e:
        save_result(folder/f'{name}.error.json',{'error':str(e),'config':config})
        print('ERROR',name,str(e),flush=True)
        raise
save_result(folder/'summary.json',{'records':records})
print('SAVED',folder,flush=True)
