import copy

import pytest

from pokerstudio.solver import SolverAdapter, config_from_hand, default_config, prepare, validate_config


def hand():
    c = default_config()
    return {"id": "test-hand", "street": "river", "amount_unit": "chips", "pot": 20,
            "effective_stack": 30, "board": c["board"], "actions": [],
            "players": [{"id": "hero", "position": "OOP", "cards": ["As", "Ah"], "range": c["players"][0]},
                        {"id": "villain", "position": "IP", "cards": [None, None], "range": c["players"][1]}]}


def test_hand_mapping_uses_explicit_data_and_preserves_range_text():
    h = hand()
    h["players"].reverse()
    h["players"][1]["range"] = "AA:0.5,AA,AKs"
    c = config_from_hand(h, {"hero": 1, "bets_ip": ["7c"] * 3, "raises": ["2x"] * 3})
    assert c["players"] == ["AA:0.5,AA,AKs", "KsKh,TcTd"]
    assert c["hero"] == 1 and c["board"] == h["board"]
    assert c["bets_ip"] == ["7c"] * 3 and c["raises"] == ["2x"] * 3
    assert c["pot"] == 20 and c["stack"] == 30
    assert h["players"][1]["range"] == "AA:0.5,AA,AKs"  # no normalization/deletion


@pytest.mark.parametrize("field,value,message", [
    ("amount_unit", "USD", "整数筹码"), ("effective_stack", None, "有限数值"),
    ("pot", 20.1, "整数筹码"), ("board", ["2c", "2c", "7h", "8s", "9c"], "重复牌"),
    ("board", ["2c", None, "7h", "8s", "9c"], "未知或非法牌"),
    ("street", "preflop", "不符"), ("root_player", "IP", "OOP"),
    ("side_pots", [10], "边池"), ("rake", 0.05, "抽水"),
])
def test_hand_missing_or_unsupported_data_is_rejected(field, value, message):
    h = hand()
    h[field] = value
    with pytest.raises(ValueError, match=message):
        config_from_hand(h, {"hero": 0})


def test_hand_unknown_ranges_and_current_street_actions_are_not_invented():
    h = hand()
    h["players"][1]["range"] = None
    with pytest.raises(ValueError, match="明确的非空范围"):
        config_from_hand(h, {"hero": 0})
    h = hand()
    h["actions"] = [{"street": "river", "player_id": "hero", "type": "bet", "amount": 10}]
    with pytest.raises(ValueError, match="当前街已经发生行动"):
        config_from_hand(h, {"hero": 0})
    # An explicit full config is a separate, confirmed street-root analysis.
    assert prepare(default_config(), h)["pot"] == 20
    with pytest.raises(ValueError, match="缺少分析 Hero"):
        config_from_hand(hand())
    with pytest.raises(ValueError, match="不能覆盖"):
        config_from_hand(hand(), {"hero": 0, "pot": 25})


def test_known_hole_cards_are_validated_even_with_explicit_config():
    h = hand()
    h["players"][1]["cards"] = ["As", None]
    with pytest.raises(ValueError, match="重复牌"):
        prepare(default_config(), h)
    h = hand()
    c = default_config()
    c["pot"] = 21
    with pytest.raises(ValueError, match="不一致"):
        prepare(c, h)
    h["solver_config"] = default_config()
    assert config_from_hand(h)["players"] == h["solver_config"]["players"]


@pytest.mark.parametrize("field,value,message", [
    ("runtime", {"inspect_file": "private"}, "runtime"),
    ("players", ["AsAh", "KsKh", "TcTd"], "两人"),
    ("players", ["AsAs", "KsKh"], "重复牌"),
    ("players", ["AA:1.2", "KsKh"], "权重"),
    ("stack", 401, "SPR"), ("pot", True, "有限数值"),
    ("raises", ["20c"] * 3, "Raise-to"), ("raises", ["1.5x"] * 3, "Raise-to"),
    ("bets", ["10c,20c,30c,40c"] * 3, "尺寸"),
    ("threads", 65, "threads"), ("time_limit_seconds", 3601, "time_limit"),
])
def test_config_rejects_unsupported_values(field, value, message):
    c = default_config()
    c[field] = value
    with pytest.raises(ValueError, match=message):
        validate_config(c)


def test_memory_stretch_must_be_a_boolean():
    c = default_config()
    c["memory_stretch"] = True
    assert validate_config(c)["memory_stretch"] is True
    c["memory_stretch"] = "yes"
    with pytest.raises(ValueError, match="布尔值"):
        validate_config(c)


def test_a_raise_limit_allows_a_deeper_stack():
    c = default_config()
    c["stack"] = 401
    c["raise_limit"] = 2
    assert validate_config(c)["stack"] == 401
    c["stack"] = 801
    with pytest.raises(ValueError, match="SPR"):
        validate_config(c)


def test_raises_accept_a_pot_percentage():
    c = default_config()
    c["raises"] = ["60%", "2.5x,75%", "a"]
    assert validate_config(c)["raises"] == ["60%", "2.5x,75%", "a"]


@pytest.mark.parametrize("streets", [[], [2], ["3"], 3])
def test_incentive_streets_must_be_board_lengths(streets):
    c = default_config()
    c["mode"] = "preview"
    c["profile"]["incentives"] = {"call": 6, "streets": [3, 5]}
    assert validate_config(c)["profile"]["incentives"]["streets"] == [3, 5]
    c["profile"]["incentives"]["streets"] = streets
    with pytest.raises(ValueError, match="streets"):
        validate_config(c)


def test_traits_locks_and_both_seat_sizes_pass_through_without_reinterpretation():
    c = default_config("station_overbluff.json")
    c.update(bets_ip=["7c"] * 3, raises_ip=["2.5x"] * 3, donks=["2c", ""])
    lock = {"path": [1], "combo": "AcJd", "probabilities": [0.1, 0.9],
            "scene": {"board": c["board"]}, "board": c["board"], "actions": ["Fold", "Call"]}
    c["profile"]["overrides"] = [lock]
    assert validate_config(c) == c
    bad = copy.deepcopy(c)
    bad["profile"]["overrides"][0]["probabilities"] = [0.2, 0.9]
    with pytest.raises(ValueError, match="之和必须为 1"):
        validate_config(bad)
    bad = copy.deepcopy(c)
    bad["board"] = bad["board"][:3]
    bad["expand_suits"] = False
    with pytest.raises(ValueError, match="expand_suits=true"):
        validate_config(bad)


def test_default_is_explicit_and_result_never_claims_failed_work_completed(tmp_path, monkeypatch):
    import pokerstudio.solver as module
    config = default_config()
    monkeypatch.setattr(module, "ROOT", tmp_path)

    class FakeJobs:
        state = "running"
        closed = False

        def submit(self, data):
            self.data = data
            return {"id": "a" * 32, "state": self.state}

        def status(self, key):
            return {"id": key, "state": self.state, "error": "native failed"}

        def source(self, key):
            return {"ev": [13.3, 6.7], "config": self.data["config"]}

        def cancel(self, key):
            self.state = "cancelled"
            return self.status(key)

        def close(self):
            self.closed = True

    jobs = FakeJobs()
    adapter = SolverAdapter(jobs)
    with pytest.raises(ValueError, match="明确的分析配置"):
        adapter.start()
    state = adapter.start(config)
    key = state["id"]
    assert state["solver_input"]["amount_unit"] == "chips"
    for failure in ("running", "failed", "cancelled"):
        jobs.state = failure
        with pytest.raises(ValueError, match=failure):
            adapter.result(key)
    jobs.state = "completed"
    assert adapter.result(key)["studio_adapter"]["root_actor"] == "OOP"
    adapter.close()
    assert jobs.closed
    with pytest.raises(ValueError, match="已关闭"):
        adapter.start({})
