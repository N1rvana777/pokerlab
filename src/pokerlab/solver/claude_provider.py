"""Claude subscription provider: agent turns through the user's own Claude Code login (Claude Agent SDK).

The app never reads, copies or stores Claude credentials. The SDK's bundled
Claude Code binary uses whatever login the user made through Anthropic's own
flow (run ``claude``, then ``/login``). Each turn:
- refuses to start when the server environment carries variables that would
  change the login or billing source (API key, auth token, custom base URL,
  cloud providers, a parent Claude Code host);
- runs with every built-in Claude Code tool removed, no filesystem settings and
  only this app's business tools, served by an in-process MCP server;
- stops when Claude Code reports an API-key credential, a rejected rate limit
  or paid overage, so plan usage never turns into pay-as-you-go silently.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid

from pokerstudio.agent.service import AgentTask, public_error, validate_arguments

SERVER = "pokerlab"
BILLING = "本人 Claude 订阅（经本机 Claude Code 登录）"
ROUTING_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_BEDROCK_BASE_URL",
                     "ANTHROPIC_VERTEX_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                     "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_ANTHROPIC_AWS",
                     # Set inside a Claude Code desktop/host session; a child would ride on the host's channel.
                     "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH", "CLAUDE_CODE_MESSAGING_TOKEN")
# MCP resource helpers can only reach MCP servers, and strict_mcp_config leaves only ours.
HARMLESS_TOOLS = {"ListMcpResourcesTool", "ReadMcpResourceTool"}
MODELS = [("opus", "Opus（套餐内的 Opus）"), ("sonnet", "Sonnet"), ("claude-opus-5-5", "Claude Opus 5.5"),
          ("claude-sonnet-5-5", "Claude Sonnet 5.5")]
# Seen in the 2026-10-29 acceptance: the model echoed a call to one of our tools as text, then made the real call.
TOOL_MARKUP = re.compile(r'(?:<function_calls>\s*)?<invoke name="mcp__' + SERVER + r'__[^"]*">.*?</invoke>\s*(?:</function_calls>\s*)?', re.S)
TURN_SECONDS = 900
MAX_TURNS = 80
ERRORS = {"authentication_failed": "Claude Code 没有登录或登录已失效：在终端运行 claude，用 /login 登录你的订阅账号。",
          "billing_error": "Claude 账号计费状态异常，请在 claude.ai 检查订阅。",
          "rate_limit": "订阅额度已用完或触发限流；本应用不会改用额外付费。",
          "invalid_request": "Claude 拒绝了这次请求（请求格式无效）。",
          "server_error": "Claude 服务端错误，请稍后重试。", "unknown": "Claude 返回了未知错误。"}


def clean_text(text):
    """Drop echoed calls to this app's tools from the visible answer; the real calls are tool events."""
    return TOOL_MARKUP.sub("", text)


def environment_problems(environ=None):
    environ = os.environ if environ is None else environ
    return sorted(name for name in ROUTING_VARIABLES if environ.get(name))


def cli_path():
    try:
        import claude_agent_sdk
    except ImportError:
        return None
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / ("claude.exe" if os.name == "nt" else "claude")
    return bundled if bundled.is_file() else (Path(found) if (found := shutil.which("claude")) else None)


def auth_status(environ=None, runner=subprocess.run):
    """Claude Code's own ``auth status``; only non-identifying fields are kept."""
    path = cli_path()
    if path is None:
        return {"checked": False, "error": "没有找到 Claude Code（需要安装 claude-agent-sdk）"}
    env = {k: v for k, v in (os.environ if environ is None else environ).items() if k != "CLAUDECODE"}
    try:
        done = runner([str(path), "auth", "status", "--json"], capture_output=True, text=True, timeout=30, env=env,
                      encoding="utf-8", errors="replace")
        data = json.loads(done.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"checked": False, "error": "无法读取 Claude Code 登录状态：" + public_error(exc)}
    return {"checked": True, "logged_in": bool(data.get("loggedIn")), "auth_method": data.get("authMethod"),
            "api_provider": data.get("apiProvider"), "subscription": data.get("subscriptionType")}


def subscription_login(auth):
    return bool(auth.get("logged_in")) and auth.get("auth_method") == "claude.ai" and auth.get("api_provider") == "firstParty"


class ClaudeSubscriptionService:
    def __init__(self, data_dir, execute_tool, tool_schemas, instructions, workdir, *, client_factory=None,
                 environ=None, status_runner=subprocess.run):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.execute_tool, self.instructions, self.workdir = execute_tool, instructions, Path(workdir)
        self.tools = {t["name"]: copy.deepcopy(t) for t in tool_schemas}
        self.client_factory, self.environ, self.status_runner = client_factory, environ, status_runner
        self.tasks, self.workers, self.verified_models, self.last_check = {}, [], set(), None
        self.auth_failed_at = None  # `auth status` only shows a stored login; a real request proves it works
        self.lock, self.turn_lock = threading.RLock(), threading.Lock()
        self.sessions_file = self.data_dir / "claude-sessions.json"
        self.sessions = {}
        if self.sessions_file.is_file():
            try:
                self.sessions = json.loads(self.sessions_file.read_text(encoding="utf-8"))
            except ValueError:
                self.sessions_file = self.data_dir / f"claude-sessions-recovered-{uuid.uuid4().hex}.json"

    def _env(self):
        return os.environ if self.environ is None else self.environ

    def _save_sessions(self):
        with self.lock:
            temp = self.sessions_file.with_suffix(".tmp")
            temp.write_text(json.dumps(self.sessions, ensure_ascii=False, indent=1), encoding="utf-8")
            temp.replace(self.sessions_file)

    def _signature(self):
        return hashlib.sha256(json.dumps(sorted(self.tools.values(), key=lambda t: t["name"]), sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()

    # ---- public surface used by SolverAgent and the HTTP server ----
    def status(self):
        problems = environment_problems(self._env())
        auth = auth_status(self._env(), self.status_runner) if not problems else {"checked": False}
        ready = not problems and subscription_login(auth) and self.auth_failed_at is None
        if problems:
            note = "Solver 服务的环境里有会改变登录或计费来源的变量：" + "、".join(problems) + "。请在普通 PowerShell 或桌面快捷方式里启动服务。"
        elif not auth.get("checked"):
            note = auth.get("error", "")
        elif not auth.get("logged_in"):
            note = "Claude Code 尚未登录：在终端运行 claude，然后用 /login 登录你的订阅账号。本应用不经手凭据。"
        elif self.auth_failed_at is not None and subscription_login(auth):
            note = (time.strftime("%H:%M", time.localtime(self.auth_failed_at)) + " 的真实请求认证失败：本机 Claude Code 登录已过期。"
                    "在普通 PowerShell 运行 claude，用 /login 重新登录后再发送。")
        elif not ready:
            note = f"Claude Code 当前登录方式是 {auth.get('auth_method')} / {auth.get('api_provider')}，不是 claude.ai 订阅；不会发起请求。"
        else:
            note = f"已用 claude.ai 账号登录（套餐：{auth.get('subscription') or '未知'}）。真实请求成功后才算验证。"
        return {"provider": "claude", "billing": BILLING, "ready": ready, "environment_problems": problems,
                "auth": auth, "note": note, "verified_models": sorted(self.verified_models), "last_check": self.last_check}

    def models(self):
        return {"models": [{"id": m, "model": m, "displayName": label} for m, label in MODELS],
                "note": "候选模型；能否使用取决于你的套餐，真实请求成功后才算验证。留空使用 Claude Code 默认模型。"}

    def start(self, message, model=None, session_id=None, context=None):
        if not isinstance(message, str) or not message.strip() or len(message) > 30000:
            raise ValueError("请输入 1–30000 字的请求。")
        if model is not None and (not isinstance(model, str) or not 1 <= len(model) <= 80):
            raise ValueError("模型名无效。")
        context = copy.deepcopy(context or {})
        with self.lock:
            if session_id:
                session = self.sessions.get(session_id)
                if not session:
                    raise ValueError("会话不存在。")
                if session.get("scope") != context:
                    raise ValueError("会话属于另一个入口，请新建会话。")
                if session.get("tool_signature") != self._signature():
                    raise ValueError("会话的业务工具定义已变化，请新建会话。")
            else:
                session_id = uuid.uuid4().hex
                session = {"provider": "claude", "scope": context, "sdk_session_id": None, "messages": [],
                           "tool_signature": self._signature(), "model": None}
                self.sessions[session_id] = session
            if any(t.session_id == session_id and t.status in ("queued", "running") for t in self.tasks.values()):
                raise RuntimeError("该会话已有运行中的任务。")
            task = AgentTask(uuid.uuid4().hex, session_id, "claude", model or session.get("model"), context)
            task.fatal, task.client, task.loop, task.stderr = None, None, None, []
            self.tasks[task.id] = task
            session["messages"].append({"role": "user", "text": message, "task_id": task.id})
        self._save_sessions()
        worker = threading.Thread(target=self._run, args=(task, message), daemon=True, name="pokerlab-claude-turn")
        self.workers.append(worker)
        worker.start()
        return task.view()

    def get(self, task_id, after=0):
        if not isinstance(after, int) or after < 0:
            raise ValueError("事件游标必须是非负整数。")
        return self.tasks[task_id].view(after)

    def owns(self, task_id):
        return task_id in self.tasks

    def cancel(self, task_id):
        task = self.tasks[task_id]
        if task.status not in ("queued", "running"):
            return task.view()
        task.cancel_event.set()
        task.emit("cancelling")
        if task.status == "queued":
            task.status = "cancelled"
        elif task.client is not None and task.loop is not None:
            asyncio.run_coroutine_threadsafe(task.client.interrupt(), task.loop)
        return task.view()

    def list_sessions(self, context=None):
        return [{"id": sid, "provider": "claude", "auth_mode": "claude_code", "model": s.get("model"),
                 "context": s.get("scope"), "messages": copy.deepcopy(s.get("messages", []))}
                for sid, s in self.sessions.items() if context is None or s.get("scope") == context]

    def close(self):
        for task in list(self.tasks.values()):
            if task.status in ("queued", "running"):
                self.cancel(task.id)
        for worker in self.workers:
            worker.join(timeout=10)

    # ---- turn ----
    def _run(self, task, message):
        try:
            with self.turn_lock:
                if task.cancel_event.is_set():
                    task.status = "cancelled"
                    return
                task.status = "running"
                task.emit("started", provider="claude", billing="subscription")
                asyncio.run(self._turn(task, message))
                if task.cancel_event.is_set():
                    task.status = "cancelled"
                elif task.fatal:
                    raise RuntimeError(task.fatal)
                elif task.tool_errors:
                    task.status = "failed"
                    task.error = "业务工具未完成：" + "; ".join(n + ": " + e for n, e in task.tool_errors.items())
                    # Keep the model's answer, but it may not read as complete over an unresolved failure.
                    task.text = f"⚠ {task.error}\n\n{task.text}" if task.text else task.error
                else:
                    task.status = "completed"
                    self.auth_failed_at = None
                    if task.model:
                        self.verified_models.add(task.model)
        except Exception as exc:
            task.error = public_error(exc)
            task.status = "cancelled" if task.cancel_event.is_set() else "failed"
            if task.stderr and task.status == "failed":
                task.emit("provider_stderr", lines=task.stderr[-10:])
            task.emit("error", error=task.error)
        finally:
            task.emit(task.status, text=task.text, error=task.error)
            session = self.sessions[task.session_id]
            session["model"] = task.model
            session["messages"].append({"role": "assistant", "text": task.text, "status": task.status,
                                        "error": task.error, "task_id": task.id})
            self._save_sessions()
            task.done_event.set()

    async def _turn(self, task, message):
        problems = environment_problems(self._env())
        if problems:
            raise RuntimeError("Solver 服务的环境里有会改变登录或计费来源的变量：" + "、".join(problems)
                               + "。请在普通 PowerShell 或桌面快捷方式里启动服务。")
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, create_sdk_mcp_server
        allowed = [f"mcp__{SERVER}__{name}" for name in self.tools]
        server = create_sdk_mcp_server(SERVER, version="1.0.0", tools=[self._sdk_tool(task, s) for s in self.tools.values()])
        session = self.sessions[task.session_id]

        def stderr(line):
            task.stderr = (task.stderr + [public_error(line)[:300]])[-40:]

        options = ClaudeAgentOptions(
            tools=[], allowed_tools=allowed, mcp_servers={SERVER: server}, strict_mcp_config=True, setting_sources=[],
            permission_mode="dontAsk", system_prompt=self.instructions, model=task.model or None,
            resume=session.get("sdk_session_id"), cwd=str(self.workdir), max_turns=MAX_TURNS,
            include_partial_messages=True, env={"CLAUDE_AGENT_SDK_CLIENT_APP": "pokerlab-solver/1"}, stderr=stderr)
        factory = self.client_factory or ClaudeSDKClient
        deadline = time.monotonic() + TURN_SECONDS
        async with factory(options=options) as client:
            task.client, task.loop = client, asyncio.get_running_loop()
            await client.query(message + "\n\n当前应用 context：" + json.dumps(task.context, ensure_ascii=False))
            async for item in client.receive_response():
                self._handle(task, item, session, set(allowed))
                if task.fatal or task.cancel_event.is_set():
                    await client.interrupt()
                    break
                if time.monotonic() > deadline:
                    task.fatal = f"Claude 请求超过 {TURN_SECONDS} 秒，已中断。"
                    await client.interrupt()
                    break
        task.client = task.loop = None

    def _handle(self, task, item, session, allowed):
        from claude_agent_sdk import AssistantMessage, RateLimitEvent, ResultMessage, StreamEvent, SystemMessage, TextBlock
        if isinstance(item, SystemMessage) and item.subtype == "init":
            data = item.data
            source, tools = data.get("apiKeySource"), list(data.get("tools", []))
            unexpected = sorted(t for t in tools if t not in allowed and t not in HARMLESS_TOOLS)
            self.last_check = {"at": time.time(), "api_key_source": source, "model": data.get("model"),
                               "tools": len(tools), "unexpected_tools": unexpected,
                               "claude_code_version": data.get("claude_code_version")}
            task.emit("tool_isolation", api_key_source=source, model=data.get("model"), tools=tools,
                      unexpected_tools=unexpected, permission_mode=data.get("permissionMode"))
            session["sdk_session_id"] = data.get("session_id") or session.get("sdk_session_id")
            task.model = data.get("model") or task.model
            if source != "none":
                task.fatal = f"Claude Code 正在使用 API 凭据（{source}），不是订阅登录；已停止，避免按量计费。"
            elif unexpected:
                task.fatal = "工具隔离失败，出现了非本应用的工具：" + "、".join(unexpected) + "；已停止。"
        elif isinstance(item, StreamEvent):
            if item.parent_tool_use_id:
                return
            # Each assistant message is a segment. The answer shown is the last non-empty one;
            # text written before tool calls (drafts, plans) is kept as progress events.
            event = item.event
            segments = task.__dict__.setdefault("segments", [""])
            if event.get("type") == "message_start" and segments[-1].strip():
                segments.append("")
            delta = event.get("delta") or {}
            if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                segments[-1] += delta.get("text", "")
                task.emit("delta", delta=delta.get("text", ""))
                cleaned = clean_text(segments[-1])
                if cleaned != segments[-1]:
                    segments[-1] = cleaned
                    task.emit("text_cleanup", removed="tool-call markup")
                if segments[-1].strip():
                    task.text = segments[-1].strip()
        elif isinstance(item, AssistantMessage):
            if item.error:
                task.fatal = ERRORS.get(item.error, ERRORS["unknown"])
                if item.error == "authentication_failed":
                    self.auth_failed_at = time.time()
            if not task.text and not item.parent_tool_use_id:
                task.fallback = getattr(task, "fallback", "") + "".join(b.text for b in item.content if isinstance(b, TextBlock))
        elif isinstance(item, RateLimitEvent):
            info = item.rate_limit_info
            task.emit("rate_limit", status=info.status, window=info.rate_limit_type, utilization=info.utilization,
                      resets_at=info.resets_at, overage_status=info.overage_status)
            if info.status == "rejected":
                task.fatal = f"订阅额度已用完（{info.rate_limit_type or '未知窗口'}）；本应用不会改用额外付费。"
            elif info.rate_limit_type == "overage":
                task.fatal = "Claude Code 开始使用额外付费用量（overage）；本应用已停止，不使用付费额度。"
        elif isinstance(item, ResultMessage):
            session["sdk_session_id"] = item.session_id or session.get("sdk_session_id")
            task.emit("usage", usage=item.usage, num_turns=item.num_turns, duration_ms=item.duration_ms,
                      estimated_api_cost_usd=item.total_cost_usd,
                      note="按 API 价格的客户端估算；订阅登录时计入套餐额度，不单独扣费")
            written = [s.strip() for s in task.__dict__.get("segments", []) if s.strip()]
            if len(written) > 1:
                task.emit("progress_text", texts=written[:-1])
            if not task.text:
                task.text = clean_text(item.result or getattr(task, "fallback", "")).strip()
            if item.is_error or item.subtype != "success":
                detail = "；".join(item.errors or []) or item.result or item.subtype
                task.fatal = task.fatal or ("Claude 请求没有正常完成：" + public_error(detail))

    def _sdk_tool(self, task, schema):
        from claude_agent_sdk import tool
        name = schema["name"]

        async def handler(args):
            result, success = await asyncio.to_thread(self._execute, task, name, args)
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "is_error": not success}

        return tool(name, schema["description"], schema["input_schema"])(handler)

    def _execute(self, task, name, arguments):
        with task.tool_lock:
            if task.cancel_event.is_set():
                return {"error": "任务已取消，未执行工具。"}, False
            try:
                validate_arguments(arguments, self.tools[name]["input_schema"])
                task.emit("tool_call", name=name, arguments=copy.deepcopy(arguments))
                result = self.execute_tool(name, arguments, context=copy.deepcopy(task.context))
                json.dumps(result, allow_nan=False)
                success = not (isinstance(result, dict) and (result.get("error") or result.get("success") is False))
                if success:
                    task.tool_errors.pop(name, None)
                else:
                    task.tool_errors[name] = public_error(result.get("error") or "工具返回失败")
                task.emit("tool_result", name=name, result=copy.deepcopy(result), success=success)
                return result, success
            except Exception as exc:
                error = {"error": public_error(exc)}
                task.tool_errors[name] = error["error"]
                task.emit("tool_result", name=name, result=error, success=False)
                return error, False
