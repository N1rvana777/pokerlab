"""Send one message to the Solver assistant through the Claude subscription provider and keep the full record.

Uses the caller's own Claude Code login, like the app. By default the coach data is the
real store (outputs/coach/); the agent's own state goes into the run folder so a
running workbench is not disturbed. Writes run.json (events, answer, tool calls) and
input.txt into a new outputs/coach-runs/<time>/ folder; nothing is overwritten.

    python scripts/coach_ask.py --message-file notes.txt
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from pokerlab.plo.resources import git_state  # noqa: E402
from pokerlab.solver.agent import SolverAgent  # noqa: E402
from pokerlab.solver.server import Jobs  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--message-file", required=True)
    parser.add_argument("--coach-dir", default=None, help="default: POKERLAB_COACH_HOME or outputs/coach")
    parser.add_argument("--hero", default=None, help="set Hero names (comma separated) if none are set yet")
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--output", default=str(ROOT / "outputs/coach-runs" / time.strftime("%Y%m%d-%H%M%S")))
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    message = Path(args.message_file).read_text(encoding="utf-8")
    (out / "input.txt").write_text(message, encoding="utf-8")
    jobs = Jobs()
    coach_dir = args.coach_dir or None
    solver = SolverAgent(jobs, data_dir=out / "agent", auth_dir=out / "auth",
                         coach_dir=coach_dir or (Path(__import__("os").environ.get("POKERLAB_COACH_HOME") or ROOT / "outputs/coach")))
    try:
        if args.hero and not solver.coach.hero_names():
            solver.coach.set_hero([n.strip() for n in args.hero.split(",") if n.strip()])
        start = time.monotonic()
        task = solver.start(message, provider="claude", model=args.model, expected_revision=solver.snapshot()["revision"])
        finished = solver.claude.tasks[task["id"]].done_event.wait(args.timeout)
        view = solver.get(task["id"])
        record = {"git": git_state(), "coach_dir": str(solver.coach.root), "finished": finished, "status": view["status"],
                  "error": view["error"], "seconds": round(time.monotonic() - start, 1), "model": view["model"],
                  "answer": view["text"], "events": view["events"]}
    finally:
        solver.close()
        jobs.close()
    (out / "run.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"status": record["status"], "seconds": record["seconds"], "output": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
