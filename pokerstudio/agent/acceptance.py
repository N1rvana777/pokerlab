"""Real subscription acceptance against an isolated, saved Studio project.

python -X utf8 -m pokerstudio.agent.acceptance --mode existing_cli --solver
Runs real inference and the existing business tools; never inspects credentials.
"""
import argparse
import json
from pathlib import Path
import time


def run_turn(studio, message, context, model=None):
    task = studio.agent.start(message, provider="subscription", model=model, context=context)
    deadline = time.monotonic() + 660
    cursor = 0
    while time.monotonic() < deadline:
        current = studio.agent.get(task["id"], cursor)
        cursor = current["cursor"]
        for event in current["events"]:
            if event["type"] != "delta":
                print(json.dumps({"agent_event": event}, ensure_ascii=True), flush=True)
        if current["status"] not in ("queued", "running"):
            # Wait for final persistence; turn/completed precedes service.finally.
            studio.agent.tasks[task["id"]].done_event.wait(5)
            return studio.agent.get(task["id"])
        time.sleep(0.5)
    studio.agent.cancel(task["id"])
    raise RuntimeError("验收任务超时，已请求取消。")


def main():
    from pokerstudio.tools import Studio
    from pokerstudio.project import ProjectStore, uid
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["existing_cli", "siwc", "managed"], default="existing_cli")
    parser.add_argument("--model")
    parser.add_argument("--solver", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    folder = args.data_dir or Path(__file__).resolve().parents[1] / ".data/agent-acceptance" / str(int(time.time()))
    studio = Studio(folder)
    evidence = {"mode": args.mode, "data_dir": str(folder.resolve()), "api": "not_configured_not_called"}
    try:
        studio.agent.configure_subscription(args.mode)
        status = studio.agent.status("subscription")
        # Authentication evidence omits personal email/routing identifiers.
        evidence["logged_in"] = status.get("logged_in")
        evidence["plan_type"] = (status.get("account") or {}).get("planType")
        if not status.get("logged_in"):
            raise RuntimeError(status.get("error") or "所选模式需要本人完成正式登录。")
        studio.store.create("TEST ONLY - Agent business acceptance")
        hand_id = uid()
        studio.edit({"op": "upsert_hand", "item": {"id": hand_id, "name": "测试手牌", "start": 0, "end": 5,
                     "pot": 10, "effective_stack": 100, "players": [], "board": [], "actions": []}})
        context = {"entry": "studio", "project_id": studio.store.get()["id"],
                   "allowed_tools": ["read_project", "update_hand", "update_subtitle"]}
        result = run_turn(studio, "这是应用接通验收。请读取当前项目，把选中手牌的底池改成120；"
                          "再新增0到2秒字幕‘这是接通验收测试素材’。保持未知底牌未知。通过真实业务工具操作后简短报告。", context, args.model)
        reopened = ProjectStore(folder).get()
        edit_calls = [e for e in result["events"] if e["type"] == "tool_result" and e.get("success")]
        evidence["studio"] = {"status": result["status"], "error": result["error"], "model": result["model"],
                              "tool_isolation": [e for e in result["events"] if e["type"] == "tool_isolation"],
                              "session_id": result["session_id"], "tool_names": [e["name"] for e in edit_calls],
                              "project_path": reopened["file_path"], "pot": reopened["hands"][0]["pot"],
                              "subtitles": reopened["subtitles"], "audit": reopened["audit"]}
        if result["status"] != "completed" or reopened["hands"][0]["pot"] != 120 or not reopened["subtitles"]:
            raise RuntimeError("真实Studio编辑验收未通过；请查看保留的task和项目。")
        if args.solver:
            config_file = Path(__file__).resolve().parents[1] / "data/solver_acceptance_equilibrium.json"
            config = json.loads(config_file.read_text(encoding="utf-8"))
            config = config.get("input", config)
            studio.set_analysis(config)
            analysis_context = {"entry": "analysis", "allowed_tools": ["read_project", "solve_hand", "get_task", "get_solver_result"]}
            analysis = run_turn(studio, "请读取独立Pokerlab分析配置，直接通过solve_hand启动真实求解。"
                                "查询任务直到完成，再get_solver_result读取真实报告。请简短说明根EV、测得精度及主要假设；"
                                "不可用估算或编造数字替代真实计算。", analysis_context, args.model)
            successful = [e for e in analysis["events"] if e["type"] == "tool_result" and e.get("success")]
            reports = [e["result"] for e in successful if e["name"] == "get_solver_result"]
            evidence["analysis"] = {"status": analysis["status"], "error": analysis["error"], "model": analysis["model"],
                                    "tool_isolation": [e for e in analysis["events"] if e["type"] == "tool_isolation"],
                                    "session_id": analysis["session_id"], "tool_names": [e["name"] for e in successful],
                                    "solver_reports": reports, "text": analysis["text"]}
            if analysis["status"] != "completed" or not reports:
                raise RuntimeError("真实agent调用solver验收未通过。")
        evidence["passed"] = True
    except Exception as exc:
        from .service import public_error
        evidence["passed"], evidence["error"] = False, public_error(exc)
    finally:
        studio.close()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "acceptance.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=True, indent=2))
    if not evidence.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
