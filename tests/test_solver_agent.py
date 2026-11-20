"""Standalone agent contracts. Fake jobs/transport never establish real inference."""
import copy
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from pokerlab.solver.agent import RevisionConflict, SOLVER_INSTRUCTIONS, SolverAgent
from pokerlab.solver.__main__ import ROOT
from pokerstudio.agent import AgentService


class FakeJobs:
    def __init__(self):
        self.items, self.reports, self.submitted = {}, {}, []
        self.closed = False
    def submit(self, request):
        self.submitted.append(copy.deepcopy(request))
        key = f"{len(self.submitted):032x}"
        item = {"id": key, "kind": request["kind"], "state": "queued"}
        self.items[key] = item
        return copy.deepcopy(item)
    def status(self, key):
        return copy.deepcopy(self.items[key])
    def source(self, key):
        return copy.deepcopy(self.reports[key])
    def cancel(self, key):
        self.items[key]["state"] = "cancelling"
        return self.status(key)
    def close(self):
        if getattr(self, "agent_service", None):
            self.agent_service.close()
        self.closed = True


class FakeService:
    def __init__(self, folder, callback, tools, **options):
        self.folder, self.callback, self.tools, self.options = folder, callback, tools, options
        self.started, self.closed = [], False
    def start(self, message, **options):
        self.started.append((message, options))
        return {"id": "agent-task", "session_id": "solver-session", "status": "queued"}
    def list_sessions(self, context=None):
        return []
    def status(self, provider=None):
        return {"subscription": {"mode": "siwc", "logged_in": False}, "api": {"configured": False, "allow_paid": False}}
    def close(self):
        self.closed = True


def adapter(tmp_path):
    return SolverAgent(FakeJobs(), tmp_path / "solver", auth_dir=tmp_path / "solver-auth", service_factory=FakeService)


def river():
    config = json.loads((ROOT / "examples/river.json").read_text(encoding="utf-8"))
    config.update(amount_unit="bb", memory_auto=False)
    return config


def test_standalone_default_role_tools_storage_and_revision(tmp_path):
    solver = adapter(tmp_path)
    state = solver.snapshot()
    assert state["config"]["board"] == ["9h", "8h", "2c"]
    assert state["config"]["memory_auto"] is True and state["amount_unit"] == "bb"
    assert solver.service.options["instructions"] == SOLVER_INSTRUCTIONS
    assert Path(solver.service.options["auth_dir"]) == tmp_path / "solver-auth"
    assert {t["name"] for t in solver.service.tools} == {"read_solver_config", "update_solver_config", "start_solver", "get_job", "get_result", "inspect_node", "cancel_job", "lock_node", "find_preflop_ranges", "calc_equity",
                                                     "import_hand_history", "find_methods", "read_method", "search_hhp", "read_hhp", "find_hhp_hands", "get_review_context", "record_live_hand", "link_player_alias", "list_hands", "get_hand",
                                                     "list_players", "get_player_profile", "add_player_note"}
    updated = solver.update(patch={"pot": 120}, expected_revision=state["revision"], source="agent")
    assert updated["config"]["pot"] == 120 and updated["revision"] == 1
    assert updated["config"]["profile"] == state["config"]["profile"]
    with pytest.raises(RevisionConflict):
        solver.update(patch={"pot": 130}, expected_revision=0)
    with pytest.raises(ValueError, match="整数bb"):
        solver.update(patch={"pot": 120.5}, expected_revision=1)
    assert solver.snapshot()["revision"] == 1
    reopened = SolverAgent(FakeJobs(), tmp_path / "solver", auth_dir=tmp_path / "solver-auth", service_factory=FakeService)
    assert reopened.snapshot()["config"]["pot"] == 120
    assert reopened.snapshot()["revision"] == 1
    solver.close(); reopened.close()


def test_business_scope_jobs_and_completed_real_report_contract(tmp_path):
    solver = adapter(tmp_path)
    with pytest.raises(PermissionError):
        solver.execute_tool("read_solver_config", {}, {"entry": "studio"})
    state = solver.update(river(), expected_revision=0)
    job = solver.execute_tool("start_solver", {"expected_revision": state["revision"]}, solver.context)
    assert solver.jobs.submitted[0]["config"] == state["config"]
    with pytest.raises(ValueError, match="尚未"):
        solver.result(job["id"])
    report = {"config": state["config"], "ev": [13, 7], "precision": {"actual_chips": 0.02}, "artifacts": {"response": "outputs/fake.policy"}}
    solver.jobs.reports[job["id"]] = report
    solver.jobs.items[job["id"]]["state"] = "completed"
    received = solver.execute_tool("get_result", {"job_id": job["id"]}, solver.context)
    assert received["result"] == report and received["amount_unit"] == "bb"
    node = solver.execute_tool("inspect_node", {"result_id": job["id"], "path": [0], "variant": "model"}, solver.context)
    assert node["state"] == "queued" and solver.jobs.submitted[-1]["kind"] == "node"
    solver.jobs.reports[job["id"]]["config"].pop("amount_unit")
    assert solver.result(job["id"])["amount_unit"] == "chips"
    solver.close()


NODE = {"path": [1], "actor": 0, "actions": ["Fold", "Call"], "pot": 300.0, "board": ["Ac", "6c", "7h"], "players": [
    {"combos": ["AdJd", "KcQc", "2h2d"], "raw_reach": [1.0, 0.5, 0.0], "blocker_adjusted_weights": [1.0, 0.5, 0.0], "equity": [0.4, 0.2, 0.0], "ev": [30.0, 0.0, 0.0]},
    {"combos": ["AhKh"], "raw_reach": [1.0], "blocker_adjusted_weights": [1.0], "equity": [0.6], "ev": [70.0]}],
    "strategy_action_major": [0.0, 1.0, 1.0, 1.0, 0.0, 0.0], "action_ev_action_major": [0.0, 0.0, 0.0, 30.0, -20.0, -50.0]}


def test_the_model_reads_a_short_report_and_asks_for_combos(tmp_path):
    solver = adapter(tmp_path)
    solver.jobs.items["a" * 32] = {"id": "a" * 32, "state": "completed"}
    solver.jobs.reports["a" * 32] = {"node": NODE}
    plain = solver.execute_tool("get_result", {"job_id": "a" * 32}, solver.context)["result"]["node"]
    assert not {"players", "strategy_action_major", "action_ev_action_major"} & set(plain) and "combos" not in plain
    assert plain["overall"] == [{"action": "Fold", "frequency": 0.3333, "combos": 0.5, "ev": 0.0}, {"action": "Call", "frequency": 0.6667, "combos": 1.0, "ev": 30.0}]
    assert plain["by_class"]["columns"] == ["hand", "combos", "Fold", "Call", "ev"]
    assert plain["by_class"]["rows"] == [["AJs", 1.0, 0.0, 1.0, 30.0], ["KQs", 0.5, 1.0, 0.0, 0.0]]
    assert plain["ranges"][0]["combos"] == 1.5 and plain["ranges"][1]["equity"] == 0.6
    asked = solver.execute_tool("get_result", {"job_id": "a" * 32, "combos": ["JdAd", "AhKh", "3c3d"]}, solver.context)["result"]["node"]
    assert [(row["combo"], row["player"]) for row in asked["combos"]] == [("AdJd", 0), ("AhKh", 1)]
    assert asked["combos"][0]["strategy"] == {"Fold": 0.0, "Call": 1.0} and asked["combos"][0]["action_ev"] == {"Fold": 0.0, "Call": 30.0}
    assert "strategy" not in asked["combos"][1] and asked["combos_not_in_range"] == ["3c3d"]
    solver.jobs.reports["b" * 32] = {"precision": {"actual_chips": 1}, "config": {"amount_unit": "chips"}, "root": NODE, "baseline_root_strategy": [1, 0]}
    solver.jobs.items["b" * 32] = {"id": "b" * 32, "state": "completed"}
    report = solver.execute_tool("get_result", {"job_id": "b" * 32}, solver.context)["result"]
    assert "baseline_root_strategy" not in report and "players" not in report["root"] and report["precision"] == {"actual_chips": 1}
    solver.jobs.reports["b" * 32]["config"]["profile"] = {"traits": [], "overrides": [{"path": []}, {"path": [1]}]}
    report = solver.execute_tool("get_result", {"job_id": "b" * 32}, solver.context)["result"]
    assert report["config"]["profile"] == {"traits": [], "locked_combos": 2}
    solver.close()


def test_lock_node_locks_the_actors_range_to_one_action(tmp_path):
    solver = adapter(tmp_path)
    state = solver.update(river(), expected_revision=0)
    solver.jobs.reports["a" * 32] = {"node": NODE}
    arguments = {"node_job": "a" * 32, "action": 1, "expected_revision": state["revision"]}
    locked = solver.execute_tool("lock_node", arguments, solver.context)
    assert locked["config"]["mode"] == "locked" and locked["revision"] == state["revision"] + 1
    assert locked["config"]["profile"]["overrides"] == [{"path": [1], "combo": "AdJd", "probabilities": [0.0, 1.0]}, {"path": [1], "combo": "KcQc", "probabilities": [0.0, 1.0]}]
    assert locked["config"]["profile"]["traits"] == []
    with pytest.raises(RevisionConflict):
        solver.execute_tool("lock_node", arguments, solver.context)
    with pytest.raises(ValueError, match="动作序号"):
        solver.execute_tool("lock_node", {**arguments, "action": 5, "expected_revision": locked["revision"]}, solver.context)
    solver.jobs.reports["b" * 32] = {"node": {"chance": True, "path": [0]}}
    with pytest.raises(ValueError, match="不是玩家决策点"):
        solver.execute_tool("lock_node", {**arguments, "node_job": "b" * 32, "expected_revision": locked["revision"]}, solver.context)
    solver.close()


JAM = {"path": [2], "actor": 1, "actions": ["Check", "AllIn(600)"], "pot": 470.0, "board": ["Ac", "6c", "7h", "3h"], "players": [{"combos": ["AdJd"], "raw_reach": [1.0], "blocker_adjusted_weights": [1.0], "equity": [0.4], "ev": [1.0]},
    {"combos": ["AhKh", "KcQc", "TsTd", "AdQd"], "raw_reach": [1.0, 1.0, 1.0, 1.0], "blocker_adjusted_weights": [1.0, 1.0, 1.0, 0.0], "equity": [0.9, 0.2, 0.1, 0.9], "ev": [1.0, 1.0, 1.0, 1.0]}],
    "strategy_action_major": [0.5, 0.4, 0.8, 0.5, 0.5, 0.6, 0.2, 0.5], "action_ev_action_major": [0.0] * 8}


@pytest.mark.parametrize("target, value_jam, scale", [(0.8, 1.0, 0.3125), (0.4, 0.5333, 1.0), (1.0, 1.0, 0.0)])
def test_lock_node_sets_a_value_share(tmp_path, target, value_jam, scale):
    solver = adapter(tmp_path)
    state = solver.update(river(), expected_revision=0)
    solver.jobs.reports["a" * 32] = {"node": JAM}
    locked = solver.execute_tool("lock_node", {"node_job": "a" * 32, "action": 1, "expected_revision": state["revision"], "hero_combo": "AdJd", "value_share": target}, solver.context)
    jam = {lock["combo"]: lock["probabilities"][1] for lock in locked["config"]["profile"]["overrides"]}
    assert set(jam) == {"AhKh", "KcQc", "TsTd"}  # AdQd is blocked by the hero and stays free
    assert jam["AhKh"] == pytest.approx(value_jam, abs=1e-3) and jam["KcQc"] == pytest.approx(0.6 * scale) and jam["TsTd"] == pytest.approx(0.2 * scale)
    assert locked["value_share"] == pytest.approx(target) and locked["config"]["mode"] == "locked"
    with pytest.raises(ValueError, match="一起给"):
        solver.execute_tool("lock_node", {"node_job": "a" * 32, "action": 1, "expected_revision": locked["revision"], "hero_combo": "AdJd"}, solver.context)
    solver.close()


def test_get_job_waits_for_the_job_to_finish(tmp_path, monkeypatch):
    solver = adapter(tmp_path)
    state = solver.update(river(), expected_revision=0)
    job = solver.execute_tool("start_solver", {"expected_revision": state["revision"]}, solver.context)
    assert solver.execute_tool("get_job", {"job_id": job["id"], "wait_seconds": 0}, solver.context)["state"] == "queued"
    naps = []
    def finish(seconds):
        naps.append(seconds)
        if len(naps) == 3:
            solver.jobs.items[job["id"]]["state"] = "completed"
    monkeypatch.setattr("pokerlab.solver.agent.time.sleep", finish)
    assert solver.execute_tool("get_job", {"job_id": job["id"]}, solver.context)["state"] == "completed" and len(naps) == 3
    solver.close()


def test_solver_session_context_and_start_revision(tmp_path):
    solver = adapter(tmp_path)
    with pytest.raises(RevisionConflict):
        solver.start("read config", expected_revision=9)
    task = solver.start("read config", expected_revision=0)
    assert task["status"] == "queued"
    options = solver.service.started[0][1]
    assert options["context"]["entry"] == "solver" and "project_id" not in options["context"]
    solver.close()


def test_custom_provider_instructions_preserve_old_default(tmp_path, monkeypatch):
    from pokerstudio.agent.service import INSTRUCTIONS
    old = AgentService(tmp_path / "old", lambda *a, **k: {}, [], auth_dir=tmp_path / "old-auth")
    assert old.instructions == INSTRUCTIONS
    service = AgentService(tmp_path / "new", lambda *a, **k: {}, [], auth_dir=tmp_path / "new-auth", instructions=SOLVER_INSTRUCTIONS)
    service.configure_api("sk-test-never-transmit", "test-model", allow_paid=True)
    payloads = []
    def stream(task_id, payload, cancelled):
        payloads.append(copy.deepcopy(payload))
        yield {"type": "response.completed", "response": {"status": "completed", "output": []}}
    monkeypatch.setattr(service.api, "stream", stream)
    task = service.start("read solver", provider="api", context={"entry": "solver"})
    assert service.tasks[task["id"]].done_event.wait(5)
    assert payloads[0]["instructions"] == SOLVER_INSTRUCTIONS
    assert service.get(task["id"])["status"] == "completed"
    service.close(); old.close()


def test_solver_http_config_token_origin_conflict_and_start(tmp_path, monkeypatch):
    from pokerlab.solver import server as module
    from pokerlab.solver import resources
    monkeypatch.setattr(module, "Jobs", FakeJobs)
    monkeypatch.setattr(resources, "memory_resources", lambda: {"ready": True, "effective_mb": 8192})
    http = module.make_server(0, agent_dir=tmp_path / "http", agent_factory=lambda jobs, data_dir: SolverAgent(jobs, data_dir, auth_dir=tmp_path / "auth", service_factory=FakeService))
    thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
    base = f"http://127.0.0.1:{http.server_port}"
    def get(path):
        with urlopen(base + path) as response:
            return json.load(response)
    def post(path, data, headers=None):
        request = Request(base + path, data=json.dumps(data).encode(), headers={"Content-Type": "application/json", **(headers or {})})
        with urlopen(request) as response:
            return json.load(response)
    try:
        boot = get("/api/bootstrap"); token = boot["token"]
        assert boot["solver"]["amount_unit"] == "bb"
        assert get("/api/resources")["effective_mb"] == 8192
        assert get("/api/agent/status")["api"]["allow_paid"] is False
        for headers in ({}, {"X-Pokerlab-Token": token, "Origin": "https://evil.invalid"}):
            with pytest.raises(HTTPError) as denial:
                post("/api/agent/config", {"config": river(), "expected_revision": 0}, headers)
            assert denial.value.code == 400
        headers = {"X-Pokerlab-Token": token}
        state = post("/api/agent/config", {"config": river(), "expected_revision": 0}, headers)
        assert state["revision"] == 1 and state["config"]["memory_auto"] is False
        with pytest.raises(HTTPError) as conflict:
            post("/api/agent/config", {"patch": {"pot": 22}, "expected_revision": 0}, headers)
        assert conflict.value.code == 409
        task = post("/api/agent/start", {"message": "read current config", "expected_revision": 1}, headers)
        assert task["id"] == "agent-task"
        submitted = post("/api/jobs", {"kind": "solve", "config": state["config"]}, headers)
        assert get("/api/agent/config")["last_job"] == submitted["id"]
        assert http.jobs.submitted[-1]["config_revision"] == 1
        with urlopen(base + "/agent.js") as response:
            script = response.read().decode()
        assert "8770" not in script and "/api/agent/start" in script
    finally:
        http.shutdown(); http.server_close(); http.jobs.close(); thread.join(5)
    assert http.solver_agent.service.closed
