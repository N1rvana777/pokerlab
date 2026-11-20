"""Read-only protocol diagnostic; no inference, no login, no token inspection.

Run from repository root: python -m pokerstudio.agent.check_cli --existing-cli
"""
import argparse
import json
from pathlib import Path
import subprocess

from .app_server import AppServer, codex_command
from .service import public_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-cli", action="store_true", help="只通过 account/read 检查已有 CLI 登录")
    parser.add_argument("--codex-home", type=Path)
    args = parser.parse_args()
    if not args.existing_cli and not args.codex_home:
        parser.error("请明确选择 --existing-cli 或 --codex-home PATH")
    version = subprocess.run(codex_command() + ["--version"], capture_output=True, text=True, encoding="utf-8")
    result = {"version": version.stdout.strip()}
    server = AppServer(cwd=Path.cwd(), codex_home=args.codex_home)
    try:
        server.start()
        account = server.rpc("account/read", {"refreshToken": False})
        # Retain useful authentication evidence, omit email/routing identifiers.
        info = account.get("account") or {}
        result["account"] = {"type": info.get("type"), "planType": info.get("planType")}
        result["requiresOpenaiAuth"] = account.get("requiresOpenaiAuth")
        models = server.rpc("model/list", {"limit": 100})
        result["models"] = [{"id": m["id"], "model": m["model"], "isDefault": m.get("isDefault")}
                            for m in models.get("data", [])]
        result["catalog_only"] = True
        isolated = server.rpc("thread/start", {"ephemeral": True, "environments": [], "sandbox": "read-only",
                                               "config": server.business_config, "dynamicTools": []})
        result["process_tool_isolation"] = server.ensure_business_thread()
        result["thread_tool_isolation"] = server.ensure_business_thread(isolated["thread"]["id"])
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except Exception as exc:
        print(json.dumps({"error": public_error(exc), "stderr": [public_error(x) for x in server.stderr_tail]}, ensure_ascii=True, indent=2))
        raise SystemExit(1)
    finally:
        server.close()


if __name__ == "__main__":
    main()
