"""Real acceptance of the Claude subscription provider (uses the caller's own Claude Code login).

Two short turns through SolverAgent with provider="claude", against an isolated
coach store loaded with the synthetic PokerStars hands:
1. read a player profile and summarise it (tool use + statistics wording);
2. turn a typed live hand into pokerlab-hand-v1 with record_live_hand.

Run it from a normal shell. Inside a Claude Code session, strip the host's
ANTHROPIC_*/CLAUDE_* variables first, otherwise the provider refuses (by design).
Writes ``acceptance.json`` into a new folder; nothing is overwritten.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from pokerlab.plo.resources import git_state  # noqa: E402
from pokerlab.solver.agent import SolverAgent  # noqa: E402
from pokerlab.solver.claude_provider import auth_status, cli_path, environment_problems  # noqa: E402
from pokerlab.solver.server import Jobs  # noqa: E402

# Seats are consistent: button 9, so seat 1 posts the small blind and seat 3 is UTG.
# (The first run on 2026-10-29 put the button on seat 7 with seats 8–9 occupied; the model flagged it.)
LIVE_TEXT = ("帮我记录这手现场牌：1/3 九人桌，Hero 在按钮（9 号位）拿 Ah Kd，有效筹码 300。"
             "1 号位小盲 Kay，2 号位大盲 Tom，3 号位 UTG 是 Mike（筹码约 400），4–8 号位分别是 Seat4、Seat5、Seat6、Seat7、Seat8。"
             "Mike 开池加注到 15，其他人都弃牌到我，我 3-bet 到 45，两个盲注弃牌，Mike 跟注。"
             "翻牌 Ks 7d 2c，Mike 过牌，我下注 40，Mike 弃牌。请用 record_live_hand 提交，然后告诉我校验结果。")


def run_turn(solver, message, timeout, model=None):
    start = time.monotonic()
    task = solver.start(message, provider="claude", model=model, expected_revision=solver.snapshot()["revision"])
    item = solver.claude.tasks[task["id"]]
    finished = item.done_event.wait(timeout)
    view = solver.get(task["id"])
    events = view["events"]
    pick = lambda kind: [e for e in events if e["type"] == kind]
    isolation = pick("tool_isolation")
    return {"finished": finished, "status": view["status"], "error": view["error"], "seconds": round(time.monotonic() - start, 1),
            "model": view["model"], "api_key_source": isolation[0]["api_key_source"] if isolation else None,
            "tools_available": isolation[0]["tools"] if isolation else None,
            "unexpected_tools": isolation[0]["unexpected_tools"] if isolation else None,
            "tool_calls": [e["name"] for e in pick("tool_call")],
            "tool_failures": [e["name"] for e in pick("tool_result") if not e["success"]],
            "rate_limit_events": pick("rate_limit"), "usage": pick("usage"), "text_cleanups": len(pick("text_cleanup")),
            "progress_texts": [t for e in pick("progress_text") for t in e["texts"]],
            "text_sha256": hashlib.sha256(view["text"].encode()).hexdigest(), "text": view["text"][:4000]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "outputs/coach-acceptance" / time.strftime("%Y%m%d-%H%M%S")))
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    report = {"command": " ".join(sys.argv), "git": git_state(), "cli_path": str(cli_path()),
              "environment_problems": environment_problems(), "auth": auth_status()}
    if report["environment_problems"]:
        report["result"] = "refused: routing environment variables present"
    else:
        import claude_agent_sdk
        from claude_agent_sdk._cli_version import __cli_version__
        report["sdk"] = {"claude_agent_sdk": claude_agent_sdk.__version__, "bundled_cli": __cli_version__}
        jobs = Jobs()
        solver = SolverAgent(jobs, data_dir=out / "agent", auth_dir=out / "auth", coach_dir=out / "coach")
        try:
            solver.coach.import_text((ROOT / "tests/data/coach/pokerstars_synthetic.txt").read_text(encoding="utf-8"))
            solver.coach.set_hero(["Hero"])
            first = run_turn(solver, "读取玩家 Mike 的档案，用三句话总结他的倾向，写明样本数和区间，并说明先验是否校准。不要启动求解。", args.timeout, args.model)
            second = run_turn(solver, LIVE_TEXT, args.timeout, args.model)
            hands = solver.coach.list_hands("pending")
            report["turns"] = [first, second]
            report["pending_hands"] = hands
            positions = {p["name"]: p["position"] for p in hands[0]["players"]} if len(hands) == 1 else {}
            report["checks"] = checks = {
                "both_turns_completed": all(t["status"] == "completed" for t in (first, second)),
                "subscription_credential": all(t["api_key_source"] == "none" for t in (first, second)),
                "only_app_tools": all(t["unexpected_tools"] == [] for t in (first, second)),
                "turn1_read_profile": "get_player_profile" in first["tool_calls"],
                "turn2_recorded_hand": "record_live_hand" in second["tool_calls"],
                "no_tool_markup_in_answers": all("<invoke" not in t["text"] for t in (first, second)),
                "recorded_hand_clean": len(hands) == 1 and hands[0]["errors"] == 0 and hands[0]["warnings"] == 0,
                "mike_utg_hero_button": positions.get("Mike") == "UTG" and positions.get("Hero") == "BTN"}
            report["result"] = "passed" if all(checks.values()) else "failed"
        finally:
            solver.close()
            jobs.close()
    (out / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"result": report["result"], "output": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
