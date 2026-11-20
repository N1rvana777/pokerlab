"""Codex 0.162 app-server JSONL transport, checked against generated schema.

Authentication belongs to Codex or the application's SIWC implementation. This
module never opens the CLI's credential file or changes its config.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Callable


def codex_command() -> list[str]:
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError("未找到 Codex CLI；请安装 @openai/codex 后重新启动应用。")
    if Path(executable).suffix.lower() in (".cmd", ".bat", ".ps1"):
        script = Path(executable).parent / "node_modules/@openai/codex/bin/codex.js"
        node = shutil.which("node")
        if not script.is_file() or not node:
            raise RuntimeError("Codex npm 启动脚本或 Node.js 不可用。")
        return [node, str(script)]
    return [executable]


class AppServer:
    def __init__(self, *, cwd: Path, codex_home: Path | None = None,
                 access_token: str | None = None,
                 notification: Callable[[str, dict], None] | None = None,
                 server_request: Callable[[str, dict], dict] | None = None):
        self.cwd = Path(cwd)
        self.codex_home = codex_home
        self.access_token = access_token
        self.notification = notification or (lambda *_: None)
        self.server_request = server_request or (lambda *_: {})
        self.process = None
        self.pending = {}
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.sequence = 0
        self.stderr_tail = []
        self.closed = False
        self.reader_threads = []
        self.disabled_mcp_names = set()
        self.business_config = {"features": {"shell_tool": False, "apps": False, "plugins": False},
                                "web_search": "disabled"}

    def start(self):
        if self.process and self.process.poll() is None:
            return
        env = os.environ.copy()
        # API billing cannot accidentally win over subscription authentication.
        env.pop("OPENAI_API_KEY", None)
        env.pop("OPENAI_BASE_URL", None)
        if self.codex_home:
            self.codex_home.mkdir(parents=True, exist_ok=True)
            env["CODEX_HOME"] = str(self.codex_home.resolve())
        cmd = codex_command() + ["app-server", "--listen", "stdio://",
                                 "-c", "analytics.enabled=false",
                                 "-c", "features.apps=false",
                                 "-c", "features.plugins=false",
                                 "-c", "features.shell_tool=false",
                                 "-c", 'web_search="disabled"']
        for name in sorted(self.disabled_mcp_names):
            if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in name):
                raise RuntimeError("当前 CLI 的 MCP 名称不能安全用于进程级覆盖，请使用应用独立登录目录。")
            cmd += ["-c", "mcp_servers." + name + ".enabled=false"]
        if self.access_token:
            env["POKERSTUDIO_CHATGPT_ACCESS_TOKEN"] = self.access_token
            cmd += ["-c", 'model_provider="pokerstudio_chatgpt"',
                    "-c", 'model_providers.pokerstudio_chatgpt.name="Pokerstudio ChatGPT plan"',
                    "-c", 'model_providers.pokerstudio_chatgpt.base_url="https://api.openai.com/v1"',
                    "-c", 'model_providers.pokerstudio_chatgpt.env_key="POKERSTUDIO_CHATGPT_ACCESS_TOKEN"',
                    "-c", "model_providers.pokerstudio_chatgpt.requires_openai_auth=false",
                    "-c", 'model_providers.pokerstudio_chatgpt.wire_api="responses"',
                    "-c", "model_providers.pokerstudio_chatgpt.supports_websockets=false"]
        else:
            # An unrelated custom provider in daily config must not route a
            # subscription turn into API billing. This override is process-only.
            cmd += ["-c", 'model_provider="openai"']
        self.closed = False
        self.process = subprocess.Popen(cmd, cwd=self.cwd, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", errors="replace", bufsize=1,
                                        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        self.reader_threads = [threading.Thread(target=self._read, daemon=True, name="pokerstudio-codex-events"),
                               threading.Thread(target=self._stderr, daemon=True, name="pokerstudio-codex-errors")]
        for thread in self.reader_threads:
            thread.start()
        self.rpc("initialize", {"clientInfo": {"name": "pokerstudio", "title": "Pokerstudio", "version": "0.1.0"},
                                "capabilities": {"experimentalApi": True}}, timeout=30)
        self.send({"method": "initialized", "params": {}})
        # CLI configuration maps merge. An empty mcp_servers table therefore
        # does not disable existing entries; use formal inventory names only.
        disabled, cursor = {}, None
        while True:
            inventory = self.rpc("mcpServerStatus/list", {"limit": 100, "cursor": cursor,
                                                         "detail": "toolsAndAuthOnly"})
            for item in inventory.get("data", []):
                disabled[item["name"]] = {"enabled": False}
            cursor = inventory.get("nextCursor")
            if not cursor:
                break
        self.business_config["mcp_servers"] = disabled
        if set(disabled) - self.disabled_mcp_names:
            self.disabled_mcp_names.update(disabled)
            token = self.access_token
            self.close()
            self.access_token = token
            self.start()

    def ensure_business_thread(self, thread_id=None):
        names, tool_count, cursor = [], 0, None
        while True:
            inventory = self.rpc("mcpServerStatus/list", {"limit": 100, "cursor": cursor,
                "detail": "toolsAndAuthOnly", "threadId": thread_id})
            for item in inventory.get("data", []):
                names.append(item["name"])
                tool_count += len(item.get("tools", {}))
            cursor = inventory.get("nextCursor")
            if not cursor:
                break
        if tool_count:
            raise RuntimeError("应用会话仍暴露外部 MCP 工具，已拒绝启动推理：" + ", ".join(names))
        return {"configured_mcp_servers": len(names), "external_mcp_tool_count": tool_count}

    def send(self, payload):
        with self.write_lock:
            if not self.process or self.process.poll() is not None:
                raise RuntimeError("Codex app-server 已退出。")
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def rpc(self, method, params=None, timeout=40):
        future = concurrent.futures.Future()
        with self.lock:
            self.sequence += 1
            request_id = self.sequence
            self.pending[request_id] = future
        try:
            self.send({"id": request_id, "method": method, "params": params or {}})
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise RuntimeError(f"Codex app-server {method} 在 {timeout} 秒内未响应。") from None
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def _read(self):
        process = self.process
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "method" in message:
                    if "id" in message:
                        threading.Thread(target=self._respond, args=(message,), daemon=True).start()
                    else:
                        self.notification(message["method"], message.get("params", {}))
                else:
                    with self.lock:
                        future = self.pending.get(message.get("id"))
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(RuntimeError(json.dumps(message["error"], ensure_ascii=False)))
                        else:
                            future.set_result(message.get("result", {}))
        finally:
            with self.lock:
                for future in list(self.pending.values()):
                    if not future.done():
                        future.set_exception(RuntimeError("Codex app-server 连接结束。"))
            if not self.closed and self.process is process:
                self.notification("transport/closed", {"error": "Codex app-server 连接结束。"})

    def _respond(self, message):
        try:
            result = self.server_request(message["method"], message.get("params", {}))
            self.send({"id": message["id"], "result": result})
        except Exception as exc:
            try:
                self.send({"id": message["id"], "error": {"code": -32603, "message": str(exc)}})
            except Exception:
                pass

    def _stderr(self):
        process = self.process
        # Do not publish raw stderr: upstream may include credential-bearing URLs.
        for line in process.stderr:
            self.stderr_tail.append(line.rstrip())
            self.stderr_tail = self.stderr_tail[-20:]

    def close(self):
        self.closed = True
        self.access_token = None
        process = self.process
        if not process:
            return
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.process = None
        for thread in self.reader_threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2)
