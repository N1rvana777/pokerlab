"""Claude subscription provider contracts with a fake SDK client; no real inference happens here."""
import json
import subprocess

import claude_agent_sdk
import pytest
from claude_agent_sdk import AssistantMessage, RateLimitEvent, RateLimitInfo, ResultMessage, StreamEvent, SystemMessage, TextBlock

from pokerlab.solver.claude_provider import ClaudeSubscriptionService, auth_status, environment_problems
from tests.test_solver_agent import FakeJobs, FakeService

SCHEMAS = [{"name": "list_players", "description": "players", "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}]
ALLOWED = ["mcp__pokerlab__list_players"]


def init(source="none", tools=ALLOWED):
    return SystemMessage("init", {"apiKeySource": source, "tools": list(tools), "model": "claude-opus-5-5", "session_id": "sdk-1",
                                  "permissionMode": "dontAsk", "claude_code_version": "2.1.310"})


def text(chunk):
    return StreamEvent("u", "sdk-1", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": chunk}})


def result(**extra):
    values = dict(subtype="success", duration_ms=5, duration_api_ms=4, is_error=False, num_turns=2, session_id="sdk-1",
                  total_cost_usd=0.02, usage={"input_tokens": 10}, result="done")
    values.update(extra)
    return ResultMessage(**values)


class FakeClient:
    instances = []

    def __init__(self, options, script):
        self.options, self.script, self.interrupted = options, script, False
        FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, message):
        self.message = message

    async def interrupt(self):
        self.interrupted = True

    async def receive_response(self):
        for step in self.script:
            if callable(step):
                step = await step(self)
            if step is not None:
                yield step


@pytest.fixture(autouse=True)
def capture_tools(monkeypatch):
    monkeypatch.setattr(claude_agent_sdk, "create_sdk_mcp_server", lambda name, version, tools: {"name": name, "tools": tools})
    FakeClient.instances.clear()


def service(tmp_path, script, environ=None, calls=None):
    calls = [] if calls is None else calls
    def execute(name, args, context=None):
        calls.append((name, args, context))
        return {"players": []}
    return ClaudeSubscriptionService(tmp_path / "claude", execute, SCHEMAS, "instructions", tmp_path,
                                     client_factory=lambda options: FakeClient(options, script), environ=environ or {})


def finish(svc, task):
    assert svc.tasks[task["id"]].done_event.wait(10)
    return svc.get(task["id"])


async def call_tool(client):
    tool = client.options.mcp_servers["pokerlab"]["tools"][0]
    reply = await tool.handler({})
    assert json.loads(reply["content"][0]["text"]) == {"players": []} and reply["is_error"] is False
    return None


def test_turn_isolates_tools_streams_text_and_resumes(tmp_path):
    calls = []
    svc = service(tmp_path, [init(), call_tool, text("你好"), AssistantMessage([TextBlock("你好")], "claude-opus-5-5"), result()], calls=calls)
    view = finish(svc, svc.start("看看对手", context={"entry": "solver"}))
    assert view["status"] == "completed" and view["text"] == "你好" and view["model"] == "claude-opus-5-5"
    kinds = [e["type"] for e in view["events"]]
    assert {"started", "tool_isolation", "tool_call", "tool_result", "usage", "completed"} <= set(kinds)
    assert calls == [("list_players", {}, {"entry": "solver"})]
    options = FakeClient.instances[0].options
    assert options.tools == [] and options.setting_sources == [] and options.permission_mode == "dontAsk"
    assert options.strict_mcp_config and options.allowed_tools == ALLOWED and options.system_prompt == "instructions"
    assert options.resume is None
    usage = next(e for e in view["events"] if e["type"] == "usage")
    assert "不单独扣费" in usage["note"]
    again = finish(svc, svc.start("继续", session_id=view["session_id"], context={"entry": "solver"}))
    assert again["status"] == "completed" and FakeClient.instances[1].options.resume == "sdk-1"
    assert svc.verified_models == {"claude-opus-5-5"}
    reopened = ClaudeSubscriptionService(tmp_path / "claude", lambda *a, **k: {}, SCHEMAS, "instructions", tmp_path, environ={})
    assert reopened.list_sessions()[0]["messages"][-1]["status"] == "completed"


@pytest.mark.parametrize("script,needle", [
    ([init(source="ANTHROPIC_API_KEY"), text("x"), result()], "API 凭据"),
    ([init(tools=ALLOWED + ["Bash"]), result()], "工具隔离失败"),
    ([init(), RateLimitEvent(RateLimitInfo(status="rejected", rate_limit_type="five_hour"), "u", "sdk-1"), result()], "额度已用完"),
    ([init(), RateLimitEvent(RateLimitInfo(status="allowed", rate_limit_type="overage"), "u", "sdk-1"), result()], "额外付费"),
    ([init(), AssistantMessage([], "claude-opus-5-5", error="authentication_failed"), result()], "/login"),
    ([init(), result(is_error=True, subtype="error_during_execution", errors=["boom"])], "没有正常完成"),
])
def test_billing_and_isolation_guards_stop_the_turn(tmp_path, script, needle):
    svc = service(tmp_path, script)
    view = finish(svc, svc.start("hi", context={"entry": "solver"}))
    assert view["status"] == "failed" and needle in view["error"]
    if needle != "没有正常完成":
        assert FakeClient.instances[0].interrupted


def test_routing_environment_is_refused_before_any_request(tmp_path):
    assert environment_problems({"ANTHROPIC_API_KEY": "x", "ANTHROPIC_BASE_URL": "http://proxy", "PATH": "p"}) == ["ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"]
    svc = service(tmp_path, [init(), result()], environ={"CLAUDE_CODE_USE_BEDROCK": "1"})
    view = finish(svc, svc.start("hi", context={"entry": "solver"}))
    assert view["status"] == "failed" and "CLAUDE_CODE_USE_BEDROCK" in view["error"] and FakeClient.instances == []
    status = svc.status()
    assert status["ready"] is False and status["environment_problems"] == ["CLAUDE_CODE_USE_BEDROCK"]


def test_expired_login_is_reported_until_a_request_succeeds(tmp_path, monkeypatch):
    import pokerlab.solver.claude_provider as provider
    monkeypatch.setattr(provider, "auth_status", lambda environ, runner: {"checked": True, "logged_in": True, "auth_method": "claude.ai",
                                                                           "api_provider": "firstParty", "subscription": "max"})
    script = [init(), AssistantMessage([], "claude-opus-5-5", error="authentication_failed"), result(is_error=True, result="Failed to authenticate")]
    svc = service(tmp_path, script)
    assert svc.status()["ready"] is True
    assert finish(svc, svc.start("hi", context={"entry": "solver"}))["status"] == "failed"
    status = svc.status()
    assert status["ready"] is False and "/login" in status["note"]
    script[:] = [init(), text("ok"), result()]
    assert finish(svc, svc.start("hi", context={"entry": "solver"}))["status"] == "completed"
    assert svc.status()["ready"] is True


def test_echoed_tool_markup_is_removed_from_the_answer(tmp_path):
    echoed = '<invoke name="mcp__pokerlab__list_players">\n<parameter name="include_hero">true</parameter>\n</invoke>\n'
    svc = service(tmp_path, [init(), text(echoed[:30]), text(echoed[30:] + "回答"), text(' <invoke name="Other">x</invoke>'), result()])
    view = finish(svc, svc.start("hi", context={"entry": "solver"}))
    assert view["status"] == "completed" and view["text"] == '回答 <invoke name="Other">x</invoke>'
    assert sum(e["type"] == "text_cleanup" for e in view["events"]) == 1


def test_answer_is_the_text_after_the_last_tool_call(tmp_path):
    start = StreamEvent("u", "sdk-1", {"type": "message_start", "message": {}})
    svc = service(tmp_path, [init(), start, text("草稿：先读档案。"), call_tool, start, text("最终回答"), result()])
    view = finish(svc, svc.start("hi", context={"entry": "solver"}))
    assert view["text"] == "最终回答"
    assert next(e for e in view["events"] if e["type"] == "progress_text")["texts"] == ["草稿：先读档案。"]


def test_auth_status_keeps_only_non_identifying_fields():
    def runner(args, **kwargs):
        assert args[1:] == ["auth", "status", "--json"] and "CLAUDECODE" not in kwargs["env"]
        payload = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "email": "someone@example.com",
                   "orgId": "org", "orgName": "Org", "subscriptionType": "max"}
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
    status = auth_status({"CLAUDECODE": "1"}, runner)
    assert status == {"checked": True, "logged_in": True, "auth_method": "claude.ai", "api_provider": "firstParty", "subscription": "max"}


def test_solver_agent_routes_claude_and_coach_tools(tmp_path):
    from pokerlab.solver.agent import SolverAgent, TOOLS
    created = {}
    def factory(folder, execute, tools, instructions, workdir):
        created.update(folder=folder, tools=tools, workdir=workdir)
        return ClaudeSubscriptionService(folder, execute, tools, instructions, workdir,
                                         client_factory=lambda options: FakeClient(options, [init(tools=["mcp__pokerlab__" + t["name"] for t in tools]), text("ok"), result()]), environ={})
    solver = SolverAgent(FakeJobs(), tmp_path / "solver", auth_dir=tmp_path / "auth", service_factory=FakeService, claude_factory=factory)
    assert solver.coach.root == (tmp_path / "coach").resolve() and created["workdir"] == solver.coach.root
    assert {t["name"] for t in created["tools"]} == {t["name"] for t in TOOLS} and "record_live_hand" in {t["name"] for t in TOOLS}
    task = solver.start("hi", provider="claude", expected_revision=0)
    assert solver.claude.tasks[task["id"]].done_event.wait(10)
    assert solver.get(task["id"])["status"] == "completed" and solver.cancel(task["id"])["status"] == "completed"
    assert solver.service.started == [] and any(s["provider"] == "claude" for s in solver.list_sessions())
    assert solver.execute_tool("list_players", {}, solver.context) == {"players": [], "hero_names": []}
    with pytest.raises(PermissionError):
        solver.execute_tool("list_players", {}, {"entry": "studio"})
    solver.close()


def test_unresolved_tool_error_keeps_the_answer_behind_a_warning(tmp_path):
    async def failing_tool(client):
        reply = await client.options.mcp_servers["pokerlab"]["tools"][0].handler({})
        assert reply["is_error"] is True
        return None
    svc = ClaudeSubscriptionService(tmp_path / "claude", lambda *a, **k: (_ for _ in ()).throw(ValueError("坏输入")), SCHEMAS, "i", tmp_path,
                                    client_factory=lambda options: FakeClient(options, [init(), failing_tool, text("我记录了其他手牌。"), result()]), environ={})
    view = finish(svc, svc.start("hi", context={"entry": "solver"}))
    assert view["status"] == "failed" and view["text"].startswith("⚠ 业务工具未完成：list_players: 坏输入") and view["text"].endswith("我记录了其他手牌。")
