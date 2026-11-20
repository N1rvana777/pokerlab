"""Serial, opt-in benchmark. Saves complete configs, precision and measured RSS."""
import argparse
import copy
import json
import platform
import subprocess
import time
from pathlib import Path

import psutil

from pokerlab.solver.__main__ import ROOT, solve, save_result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        parser.error("output exists; use a new filename")
    scenarios=[]
    river=json.loads((ROOT/"examples/river.json").read_text())
    scenarios.append(("river_small",river))
    wider=copy.deepcopy(river)
    wider["players"]=["AA,KK,QQ,AKs", "JJ,TT,99,AQs"]
    wider["stack"]=60; wider["bets"][2]="33%,75%"
    scenarios.append(("river_wider_two_sizes",wider))
    flop=json.loads((ROOT/"examples/flop_barrel.json").read_text())
    for street in (4,3):
        for q in (0,1):
            config=copy.deepcopy(flop)
            config["board"]=["Ac","Ad","2h","3s"][:street]
            config["profile"]["fixture_river_bet"]=q
            scenarios.append((f"{street}_cards_river_bet_{q}",config))
    records=[]
    for name,config in scenarios:
        start=time.perf_counter()
        result=solve(config)
        records.append({"name":name,"wall_seconds_including_wsl":time.perf_counter()-start,"result":result})
        print(name, result["ev"], result["precision"], flush=True)
    gpu=subprocess.run(["nvidia-smi","--query-gpu=name,memory.total","--format=csv,noheader"],capture_output=True,text=True)
    save_result(args.output,{"hardware":{"platform":platform.platform(),"cpu":platform.processor(),"logical_cpus":psutil.cpu_count(),"memory":dict(psutil.virtual_memory()._asdict()),"gpu":gpu.stdout.strip()},"records":records})


if __name__=="__main__":
    main()
