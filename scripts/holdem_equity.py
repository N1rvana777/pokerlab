"""Seeded Monte Carlo all-in equity of one Hold'em hand against a list of villain hands.

    python scripts/holdem_equity.py --hero Js Jh --villain AKo AKs AQo AQs QQ KK AA --boards 40000
    python scripts/holdem_equity.py ... --pot-after-call 1240 --to-call 510

Writes a JSON report (command, seed, git commit, per-hand equities, pot odds) to a new file.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pokerlab.coach.equity import equity  # noqa: E402
from pokerlab.plo.resources import git_state  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hero", nargs=2, required=True)
    parser.add_argument("--villain", nargs="+", required=True, help="AKo AKs AQ QQ AsKd ...")
    parser.add_argument("--boards", type=int, default=40_000, help="boards per villain combo")
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--pot-after-call", type=float, default=None)
    parser.add_argument("--to-call", type=float, default=None)
    parser.add_argument("--output", default=str(ROOT / "outputs/coach-equity" / (time.strftime("%Y%m%d-%H%M%S") + ".json")))
    args = parser.parse_args()
    started = time.time()
    report = equity(args.hero, args.villain, args.boards, args.seed)
    report.update(command=" ".join(sys.argv), git=git_state(), seconds=round(time.time() - started, 1))
    if args.pot_after_call and args.to_call:
        need = args.to_call / args.pot_after_call
        report["pot_odds"] = {"to_call": args.to_call, "pot_after_call": args.pot_after_call, "required_equity": need,
                              "call_ev": report["equity"] * args.pot_after_call - args.to_call}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
    print(json.dumps({k: report[k] for k in ("equity", "std_error", "combos")} | ({"pot_odds": report["pot_odds"]} if "pot_odds" in report else {}),
                     ensure_ascii=False), str(out))


if __name__ == "__main__":
    main()
