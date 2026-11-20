"""Transport contract/edge tests. They do not establish real account access."""
import copy
import json
import threading
import time

import pytest

from pokerstudio.agent import AgentService
from pokerstudio.agent.service import AgentTask, public_error, validate_arguments


TOOLS = [{"name": "update_hand", "description": "change confirmed pot", "input_schema": {
    "type": "object", "required": ["pot"], "properties": {"pot": {"type": "number", "minimum": 0}}, "additionalProperties": False}}]


def service(tmp_path, callback=None):
    return AgentService(tmp_path / "sessions", callback or (lambda *a, **k: {"ok": True}), TOOLS,
                        workspace=tmp_path, auth_dir=tmp_path / "auth")


def finish(agent, task):
    assert agent.tasks[task["id"]].done_event.wait(5)
    return agent.get(task["id"])


def response(output, status="completed"):
    return {"type": "response.completed", "response": {"status": status, "output": output, "usage": {"total_tokens": 10}}}


def test_no_credential_or_paid_authorization_never_calls_network(tmp_path, monkeypatch):
    agent = service(tmp_path)
    monkeypatch.setattr(agent.api, "stream", lambda *a: pytest.fail("network called"))
    agent.configure_api("sk-test-never-transmit", "test-model", allow_paid=False)
    result = finish(agent, agent.start("change pot", provider="api"))
    assert result["status"] == "failed"
    assert "授权" in result["error"]
    assert "sk-test-never-transmit" not in (tmp_path / "sessions/sessions.json").read_text(encoding="utf-8")
    agent.close()


def test_api_stream_dispatch_results_resume_and_model_verification(tmp_path, monkeypatch):
    calls, requests = [], []
    def execute(name, args, context=None):
        calls.append((name, args, context))
        return {"pot": args["pot"], "saved": True}
    agent = service(tmp_path, execute)
    agent.configure_api("sk-test-never-transmit", "test-model", allow_paid=True)
    outputs = [[{"type": "function_call", "name": "update_hand", "arguments": '{"pot":120}', "call_id": "call-1"}], []]
    def stream(task_id, payload, cancelled):
        requests.append(copy.deepcopy(payload))
        output = outputs.pop(0)
        if not output:
            yield {"type": "response.output_text.delta", "delta": "saved"}
        yield response(output)
    monkeypatch.setattr(agent.api, "stream", stream)
    result = finish(agent, agent.start("pot to 120", provider="api", context={"entry": "studio"}))
    assert result["status"] == "completed"
    assert result["text"] == "saved"
    assert calls == [("update_hand", {"pot": 120}, {"entry": "studio"})]
    assert requests[1]["input"][-1]["type"] == "function_call_output"
    assert requests[0]["store"] is False and requests[0]["stream"] is True
    assert "test-model" in agent.status("api")["verified_models"]
    assert "sk-test-never-transmit" not in json.dumps(result)
    reopened = service(tmp_path)
    assert reopened.list_sessions()[0]["id"] == result["session_id"]
    assert reopened.status("api")["verified_models"] == []
    assert reopened.status("api")["historical_model_validations"][0]["model"] == "test-model"
    assert not reopened.api.api_key and not reopened.api.allow_paid
    with pytest.raises(ValueError, match="provider"):
        reopened.start("hello", provider="subscription", session_id=result["session_id"], context={"entry": "studio"})
    with pytest.raises(ValueError, match="项目"):
        agent.start("hello", provider="api", session_id=result["session_id"], context={"entry": "analysis"})
    reopened.close()
    agent.close()


def test_stream_eof_is_failure_not_verified(tmp_path, monkeypatch):
    agent = service(tmp_path)
    agent.configure_api("sk-test", "test-model", True)
    monkeypatch.setattr(agent.api, "stream", lambda *a: iter([{"type": "response.output_text.delta", "delta": "partial"}]))
    result = finish(agent, agent.start("hello", provider="api"))
    assert result["status"] == "failed"
    assert "response.completed" in result["error"]
    assert agent.status("api")["verified_models"] == []
    agent.close()


def test_tool_validation_failure_reaches_model_as_failed_result(tmp_path, monkeypatch):
    agent = service(tmp_path, lambda *a, **k: pytest.fail("invalid tool executed"))
    agent.configure_api("sk-test", "test-model", True)
    outputs = [[{"type": "function_call", "name": "update_hand", "arguments": '{"pot":true}', "call_id": "c1"}], []]
    requests = []
    def stream(task_id, payload, cancelled):
        requests.append(copy.deepcopy(payload))
        yield response(outputs.pop(0))
    monkeypatch.setattr(agent.api, "stream", stream)
    result = finish(agent, agent.start("hello", provider="api"))
    tools = [e for e in result["events"] if e["type"] == "tool_result"]
    assert tools[0]["success"] is False and "类型" in tools[0]["result"]["error"]
    assert "error" in json.loads(requests[-1]["input"][-1]["output"])
    assert result["status"] == "failed" and "业务工具未完成" in result["text"]
    agent.close()


def test_cancelled_api_turn_is_not_success(tmp_path, monkeypatch):
    agent = service(tmp_path)
    agent.configure_api("sk-test", "test-model", True)
    started = threading.Event()
    def stream(task_id, payload, cancelled):
        started.set()
        cancelled.wait(5)
        yield response([])
    monkeypatch.setattr(agent.api, "stream", stream)
    task = agent.start("wait", provider="api")
    assert started.wait(5)
    agent.cancel(task["id"])
    result = finish(agent, task)
    assert result["status"] == "cancelled"
    assert agent.status("api")["verified_models"] == []
    agent.close()


def test_subscription_stdio_dynamic_contract_and_failure(tmp_path, monkeypatch):
    agent = service(tmp_path)
    agent.configure_subscription("existing_cli")
    requests = []
    class FakeServer:
        def rpc(self, method, params=None, timeout=None):
            requests.append((method, params))
            if method == "account/read":
                return {"account": {"type": "chatgpt", "planType": "pro"}}
            if method == "thread/start":
                assert params["dynamicTools"][0]["type"] == "function"
                assert params["dynamicTools"][0]["inputSchema"] == TOOLS[0]["input_schema"]
                return {"thread": {"id": "thread1"}}
            if method == "turn/start":
                threading.Timer(0.02, lambda: agent._notification("turn/completed", {
                    "threadId": "thread1", "turn": {"id": "turn1", "status": "failed", "error": {"message": "auth expired"}}})).start()
                return {"turn": {"id": "turn1"}}
            raise AssertionError(method)
    monkeypatch.setattr(agent, "_connection", lambda: FakeServer())
    result = finish(agent, agent.start("hello", model="test-model"))
    assert result["status"] == "failed" and "auth expired" in result["error"]
    assert not agent.verified_models["subscription"]
    agent.close()


def test_default_auth_is_app_owned_and_status_is_safe(tmp_path):
    agent = service(tmp_path)
    assert agent.status("subscription")["mode"] == "siwc"
    assert not agent.status("subscription")["logged_in"]
    assert agent.status("api")["allow_paid"] is False
    assert not (tmp_path / "auth").exists()
    agent.close()


def test_app_mode_restores_without_credentials_or_paid_authorization(tmp_path):
    agent = service(tmp_path)
    agent.configure_subscription("existing_cli")
    agent.configure_api("sk-test-never-transmit", "test-model", True)
    agent.close()
    saved = (tmp_path / "sessions/agent-settings.json").read_text(encoding="utf-8")
    assert "sk-test-never-transmit" not in saved and "allow_paid" not in saved
    reopened = service(tmp_path)
    assert reopened.subscription_mode == "existing_cli"
    assert not reopened.api.api_key and not reopened.api.allow_paid
    reopened.close()


def test_old_turn_events_are_rejected_during_session_resume(tmp_path):
    agent = service(tmp_path)
    agent.sessions["session"] = {"provider": "subscription", "last_turn_id": "old"}
    task = AgentTask("task", "session", "subscription", "model", {})
    task.status, task.thread_id = "running", "thread"
    agent.tasks[task.id] = task
    agent._notification("item/agentMessage/delta", {"threadId": "thread", "turnId": "old", "delta": "old"})
    assert not task.text
    task.turn_id = "new"
    agent._notification("turn/completed", {"threadId": "thread", "turn": {"id": "old", "status": "completed"}})
    assert task.status == "running"
    agent._notification("item/agentMessage/delta", {"threadId": "thread", "turnId": "new", "delta": "new"})
    assert task.text == "new"
    task.status = "cancelled"
    agent.close()


def test_analysis_and_explicit_tool_scopes_are_enforced_before_callback(tmp_path):
    agent = service(tmp_path, lambda *a, **k: pytest.fail("forbidden callback executed"))
    task = AgentTask("task", "session", "api", "model", {"entry": "analysis"})
    result, success = agent._tool(task, "update_hand", {"pot": 120})
    assert not success and "update_hand" in result["error"]
    task.context = {"entry": "studio", "allowed_tools": []}
    result, success = agent._tool(task, "update_hand", {"pot": 120})
    assert not success and "update_hand" in result["error"]
    agent.close()


def test_cancel_shuts_down_response_socket_when_connection_released_it():
    from pokerstudio.agent.responses import ResponsesProvider
    class Socket:
        def __init__(self):
            self.shutdown_called = False
        def shutdown(self, how):
            self.shutdown_called = how == 2
    class Connection:
        sock = None
        closed = False
        def close(self):
            self.closed = True
    class Raw:
        def __init__(self, socket):
            self._sock = socket
    provider, socket, conn = ResponsesProvider(), Socket(), Connection()
    provider.connections["task"] = {"connection": conn, "socket": Raw(socket)}
    provider.cancel("task")
    assert socket.shutdown_called and conn.closed


def test_arguments_unknown_params_nan_and_error_redaction():
    for value in ({"pot": True}, {"pot": float("nan")}, {"pot": -1}, {"pot": 1, "oops": 2}):
        with pytest.raises(ValueError):
            validate_arguments(value, TOOLS[0]["input_schema"])
    assert "sk-secret123456" not in public_error("Failed Bearer sk-secret123456")
