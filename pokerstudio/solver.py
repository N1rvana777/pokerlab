"""Validated Pokerstudio bridge to the existing, supervised PokerLab solver.

No poker calculation is implemented here. Jobs, budgets, the cross-process lock,
native worker, snapshots and reports remain owned by ``pokerlab.solver``.
"""
from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

from pokerlab.solver.__main__ import ROOT, save_result
from pokerlab.solver.server import Jobs

_CARD = re.compile(r"[2-9TJQKA][cdhs]", re.IGNORECASE)
_COMBO = r"(?:(?:[AKQJT2-9]{2}[os]?)|(?:[AKQJT2-9][cdhs]){2})"
_RANGE = re.compile(rf"{_COMBO}(?:\+|-{_COMBO})?(?::(?:[01](?:\.\d*)?|\.\d+))?", re.IGNORECASE)
_TRAITS = {"station", "overbluff", "underbluff", "weak_check", "double_barrel_give_up", "delayed_aggression"}
_REQUIRED = {"schema_version", "board", "players", "pot", "stack", "bets", "hero", "mode", "target", "target_unit", "max_iterations", "memory_budget_mb"}
_OPTIONAL = {"raises", "bets_ip", "raises_ip", "donks", "expand_suits", "compression", "auto_suits", "memory_auto", "memory_stretch", "amount_unit", "chip_scale", "raise_limit", "lines", "rake_rate", "rake_cap", "add_allin_threshold", "force_allin_threshold", "merging_threshold", "threads", "time_limit_seconds", "profile"}
_STREETS = {"flop": 3, "turn": 4, "river": 5}


def default_config(name: str = "river.json") -> dict[str, Any]:
    """Return an explicitly selected repository fixture; never fill a real hand."""
    if name not in {"river.json", "station_overbluff.json", "flop_research.json", "flop_research_raises.json"}:
        raise ValueError("未知 solver 示例")
    config = json.loads((ROOT / "examples" / name).read_text(encoding="utf-8-sig"))
    config.update(compression=True, auto_suits=True, expand_suits=True, threads=8, time_limit_seconds=600)
    return config


def _number(value: Any, field: str, minimum: float, maximum: float, integer: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} 必须为有限数值")
    if integer and (not isinstance(value, int)):
        raise ValueError(f"{field} 必须使用整数筹码，不能静默舍入或换算货币")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} 必须在 {minimum:g}..{maximum:g} 之间")
    return value


def _cards(value: Any, field: str, lengths: set[int], unknown: bool = False) -> list[str | None]:
    if not isinstance(value, list) or len(value) not in lengths:
        raise ValueError(f"{field} 需要 {sorted(lengths)} 张牌的数组")
    result = []
    for card in value:
        if card is None and unknown:
            result.append(None)
        elif not isinstance(card, str) or not _CARD.fullmatch(card):
            raise ValueError(f"{field} 包含未知或非法牌 {card!r}，牌张格式例如 As、Th")
        else:
            result.append(card[0].upper() + card[1].lower())
    known = [c for c in result if c is not None]
    if len(set(known)) != len(known):
        raise ValueError(f"{field} 存在重复牌")
    return result


def _range(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 32768:
        raise ValueError(f"{field} 必须提供明确的非空范围，最多 32768 字符")
    # Native remains the final authority for range ordering, legal combinations,
    # weights and overlaps. Keep the text intact: first-entry priority matters.
    value = value.strip()
    parts = value.split(",")
    if parts[-1].strip() == "":
        parts.pop()  # Upstream accepts a trailing comma.
    for part in parts:
        part = re.sub(r"\s*([-:])\s*", r"\1", part.strip())
        if not _RANGE.fullmatch(part):
            raise ValueError(f"{field} 的范围条目无效：{part!r}")
        expression, _, weight = part.partition(":")
        if weight and not 0 <= float(weight) <= 1:
            raise ValueError(f"{field} 的范围权重必须在 0..1 之间")
        for combo in expression.rstrip("+").split("-"):
            if len(combo) == 4 and _CARD.fullmatch(combo[:2]) and _CARD.fullmatch(combo[2:]):
                _cards([combo[:2], combo[2:]], field, {2})
    return value


def _sizes(value: Any, field: str, length: int, raises: bool = False) -> None:
    if not isinstance(value, list) or len(value) not in {0, length} or any(not isinstance(s, str) for s in value):
        raise ValueError(f"{field} 需要 {length} 个街道尺寸字符串")
    for entry in value:
        parts = [p.strip() for p in entry.split(",")]
        if len(parts) > 3:
            raise ValueError(f"{field} 每街最多 3 个尺寸，不会自动缩减求解树")
        for size in parts:
            if not size:
                continue
            if raises and size != "a":
                multiple = re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)x", size) and float(size[:-1]) >= 2
                if not multiple and not re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)%", size):
                    raise ValueError(f"{field} 加注支持至少 2x、底池百分比或 a（All-in）；不支持任意 Raise-to")
            elif not raises:
                # Includes the upstream geometric notation; native validates its
                # numeric details before allocating the full game.
                valid = size.lower() == "a" or re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)%", size)
                valid = valid or re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)c", size) or re.fullmatch(r"(?:\d+)?e(?:(?:\d+(?:\.\d*)?|\.\d+)%)?", size.lower())
                if not valid:
                    raise ValueError(f"{field} 下注尺寸无效：{size!r}；示例 50%、10c、a")


def _profile(value: Any, config: dict[str, Any]) -> None:
    if not isinstance(value, dict) or set(value) - {"traits", "overrides", "fixture_river_bet", "incentives"}:
        raise ValueError("profile 包含不支持的字段")
    traits, locks = value.get("traits", []), value.get("overrides", [])
    if not isinstance(traits, list) or not isinstance(locks, list):
        raise ValueError("traits 和 overrides 必须为数组")
    for trait in traits:
        if not isinstance(trait, dict) or set(trait) != {"kind", "strength", "streets"} or trait["kind"] not in _TRAITS:
            raise ValueError("未知特质或缺少 kind/strength/streets")
        _number(trait["strength"], "特质 strength", 0, 6)
        if not isinstance(trait["streets"], list) or not trait["streets"] or any(type(s) is not int or s not in (3, 4, 5) for s in trait["streets"]):
            raise ValueError("特质 streets 必须为非空的 3/4/5 数组")
    fixture = value.get("fixture_river_bet")
    if fixture is not None:
        _number(fixture, "fixture_river_bet", 0, 1)
        if traits:
            raise ValueError("合成测试 fixture 不能和特质混用")
    for lock in locks:
        if not isinstance(lock, dict) or set(lock) - {"path", "combo", "probabilities", "scene", "actions", "board", "seat"} or not {"path", "combo", "probabilities"} <= set(lock):
            raise ValueError("Node Lock 缺少 path/combo/probabilities 或包含未知字段")
        path = lock["path"]
        if not isinstance(path, list) or len(path) > 100 or any(type(p) is not int or p < 0 for p in path):
            raise ValueError("Node Lock path 无效")
        combo = lock["combo"]
        if not isinstance(combo, str) or len(combo) != 4:
            raise ValueError("Node Lock combo 必须为具体两张牌")
        _cards([combo[:2], combo[2:]], "Node Lock combo", {2})
        probabilities = lock["probabilities"]
        if not isinstance(probabilities, list) or not probabilities:
            raise ValueError("Node Lock 必须提供完整动作概率")
        for probability in probabilities:
            _number(probability, "Node Lock probability", 0, 1)
        if abs(sum(probabilities) - 1) > 1e-6:
            raise ValueError("Node Lock 的完整动作概率之和必须为 1，不会暗中归一化")
    incentives = value.get("incentives")
    if incentives is not None:
        if not isinstance(incentives, dict) or set(incentives) - {"check", "bet", "fold", "call", "streets"}:
            raise ValueError("incentives 只能包含 check/bet/fold/call/streets")
        for field, rate in incentives.items():
            if field == "streets":
                if not isinstance(rate, list) or not rate or any(type(s) is not int or s not in (3, 4, 5) for s in rate):
                    raise ValueError("incentives streets 必须为非空的 3/4/5 数组")
            else:
                _number(rate, "incentives " + field, -50, 50)
        if config["mode"] not in ("fixed", "preview"):
            raise ValueError("Player Profile 只用于 fixed 或 preview")
    if config["mode"] == "locked" and (traits or not locks or fixture is not None):
        raise ValueError("locked 需要 Node Lock，且不能和特质同时使用")
    if config["mode"] == "equilibrium" and (traits or locks or fixture is not None):
        raise ValueError("equilibrium 不能应用固定对手特质或 Node Lock")
    if len(config["board"]) < 5 and locks and not config.get("expand_suits", False):
        raise ValueError("Flop/Turn Node Lock 必须设置 expand_suits=true")


def validate_config(config: Any) -> dict[str, Any]:
    """Validate supported request shape before launching; native validates the tree."""
    if not isinstance(config, dict):
        raise ValueError("solver 配置必须为 JSON 对象")
    missing = _REQUIRED - set(config)
    if missing:
        raise ValueError("solver 配置缺少必要字段：" + ", ".join(sorted(missing)))
    unknown = set(config) - _REQUIRED - _OPTIONAL
    if unknown:
        raise ValueError("不支持的 solver 字段（包括内部 runtime）：" + ", ".join(sorted(unknown)))
    result = copy.deepcopy(config)
    if "amount_unit" in result and result["amount_unit"] not in ("bb", "chips"):
        raise ValueError("amount_unit 仅支持 bb/chips；计价单位不会自动换算数值")
    if type(result["schema_version"]) is not int or result["schema_version"] != 1:
        raise ValueError("当前 solver 仅支持 schema_version=1")
    result["board"] = _cards(result["board"], "board", {3, 4, 5})
    if not isinstance(result["players"], list) or len(result["players"]) != 2:
        raise ValueError("当前 solver 仅支持两人翻后，players 顺序必须为 OOP、IP")
    result["players"] = [_range(r, f"players[{i}]") for i, r in enumerate(result["players"])]
    # chip_scale lets pot and stack be decimals; the engine still counts whole chips.
    if "chip_scale" in result:
        _number(result["chip_scale"], "chip_scale", 1, 1000, integer=True)
    scale = result.get("chip_scale", 1)
    for field in ("pot", "stack"):
        _number(result[field], field, 1 / scale, 1_000_000, integer=scale == 1)
    for field, low, high in (("max_iterations", 1, 100_000), ("memory_budget_mb", 1, 24576), ("hero", 0, 1)):
        _number(result[field], field, low, high, integer=True)
    if "lines" in result and (not isinstance(result["lines"], list) or len(result["lines"]) > 2000
                              or any(not isinstance(line, list) or any(not isinstance(a, str) for a in line) for line in result["lines"])):
        raise ValueError("lines 必须是行动线数组")
    if "raise_limit" in result:
        _number(result["raise_limit"], "raise_limit", 0, 10, integer=True)
    for field, high in (("rake_rate", 1), ("rake_cap", 1_000_000), ("add_allin_threshold", 100), ("force_allin_threshold", 100), ("merging_threshold", 100)):
        if field in result:
            _number(result[field], field, 0, high)
    spr_limit = 40 if "raise_limit" in result else 20
    if result["stack"] > result["pot"] * spr_limit:
        raise ValueError(f"当前 solver 支持 SPR≤{spr_limit}（设每街加注次数后可到 40），不会自动截断或缩减筹码")
    _number(result["target"], "target", 1e-30, 1e30)
    if result["target_unit"] not in {"chips", "pot_pct"} or result["mode"] not in {"equilibrium", "fixed", "preview", "locked"}:
        raise ValueError("target_unit 仅支持 chips/pot_pct；mode 仅支持 equilibrium/fixed/preview/locked")
    _sizes(result["bets"], "bets", 3)
    if len(result["bets"]) != 3:
        raise ValueError("bets 需要 Flop/Turn/River 三个尺寸字符串")
    for field in ("raises", "raises_ip", "bets_ip", "donks"):
        if field in result:
            _sizes(result[field], field, 2 if field == "donks" else 3, field.startswith("raises"))
    for field in ("expand_suits", "compression", "auto_suits", "memory_auto", "memory_stretch"):
        if field in result and type(result[field]) is not bool:
            raise ValueError(f"{field} 必须为布尔值")
    if "threads" in result:
        _number(result["threads"], "threads", 1, 64, integer=True)
    if "time_limit_seconds" in result:
        _number(result["time_limit_seconds"], "time_limit_seconds", 0, 3600, integer=True)
    _profile(result.get("profile", {}), result)
    # Check serializability too: no NaN, custom objects or secret runtime paths.
    json.dumps(result, allow_nan=False)
    return result


def _validate_hand(hand: Any, config: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(hand, dict):
        raise ValueError("手牌必须为结构化对象")
    if hand.get("amount_unit") != "chips":
        raise ValueError("手牌分析暂仅支持 amount_unit='chips' 整数筹码；USD 需要先明确换算并人工确认")
    board = _cards(hand.get("board"), "手牌 board", {3, 4, 5})
    street = hand.get("street")
    if street not in _STREETS or len(board) != _STREETS[street]:
        raise ValueError("手牌 street 与已知公共牌数量不符，仅支持 flop/turn/river")
    players = hand.get("players")
    if not isinstance(players, list) or len(players) != 2:
        raise ValueError("当前 solver 仅支持两人翻后；三人、边池暂未实现")
    positions = [p.get("position") if isinstance(p, dict) else None for p in players]
    if sorted(str(p) for p in positions) != ["IP", "OOP"]:
        raise ValueError("两名玩家的 position 必须明确标为 OOP 和 IP")
    known = list(board)
    for player in players:
        cards = player.get("cards", [None, None])
        known += [c for c in _cards(cards, "玩家 cards", {2}, unknown=True) if c is not None]
    if len(set(known)) != len(known):
        raise ValueError("玩家底牌与公共牌之间存在重复牌")
    for field in ("pot", "effective_stack"):
        _number(hand.get(field), "手牌 " + field, 1, 1_000_000, integer=True)
    if hand.get("rake", 0) not in (0, None) or hand.get("side_pots"):
        raise ValueError("当前 solver 不支持未来抽水或边池")
    if hand.get("root_player", "OOP") != "OOP":
        raise ValueError("当前 solver 根行动者必须是 OOP")
    if config is not None:
        if board != config["board"] or hand["pot"] != config["pot"] or hand["effective_stack"] != config["stack"]:
            raise ValueError("分析配置与手牌的 board/pot/effective_stack 不一致，请先明确分析的街开始局面")
    return hand


def config_from_hand(hand: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Map an explicitly recorded street-start heads-up situation to schema v1.

    ``pot`` is the pot at this street's root and ``effective_stack`` means the
    effective remaining stack there, not either player's original buy-in.
    Current-street actions cannot be reconstructed as an arbitrary native root.
    """
    _validate_hand(hand)
    if hand.get("solver_config") is not None:
        config = validate_config(hand["solver_config"])
        _validate_hand(hand, config)
        return config
    actions = hand.get("actions", [])
    if not isinstance(actions, list):
        raise ValueError("手牌 actions 必须为数组")
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("手牌 actions 必须为结构化行动数组")
        if action.get("street") == hand["street"]:
            raise ValueError("当前街已经发生行动，无法自动映射为街开始 OOP 根；请单独填写并确认分析配置")
    options = copy.deepcopy(options or {})
    if "hero" not in options:
        raise ValueError("缺少分析 Hero：请在 options 中明确 hero=0（OOP）或 1（IP）")
    positions = {p["position"]: p for p in hand["players"]}
    ranges = [_range(positions[p].get("range"), f"{p} range") for p in ("OOP", "IP")]
    config = {"schema_version": 1, "board": list(hand["board"]), "players": ranges,
              "pot": hand["pot"], "stack": hand["effective_stack"], "bets": ["50%"] * 3,
              "raises": [""] * 3, "mode": "fixed", "target": 0.1, "target_unit": "pot_pct",
              "max_iterations": 1000, "memory_budget_mb": 2048, "compression": True,
              "auto_suits": True, "expand_suits": True, "threads": 8,
              "time_limit_seconds": 600, "profile": {"traits": []}}
    # Scene fields are sourced from the hand only. Options are tree/algorithm
    # assumptions, not permission to silently replace known cards or money.
    if set(options) & {"board", "players", "pot", "stack", "schema_version"}:
        raise ValueError("options 不能覆盖手牌 board/players/pot/stack/schema_version")
    config.update(options)
    return validate_config(config)


def prepare(config: dict[str, Any] | None = None, hand: dict[str, Any] | None = None,
            options: dict[str, Any] | None = None) -> dict[str, Any]:
    if config is None:
        if hand is None:
            raise ValueError("请提供明确的分析配置或完整手牌；演示案例必须显式选择")
        return config_from_hand(hand, options)
    if options:
        raise ValueError("显式 config 不能同时使用 options")
    config = validate_config(config)
    if hand is not None:
        _validate_hand(hand, config)
    return config


class SolverAdapter:
    """Asynchronous adapter whose ids refer to genuine PokerLab jobs."""

    def __init__(self, jobs: Jobs | None = None):
        self.jobs = jobs if jobs is not None else Jobs()
        self._metadata: dict[str, dict[str, Any]] = {}
        self._closed = False

    @staticmethod
    def default_config(name: str = "river.json") -> dict[str, Any]:
        return default_config(name)

    @staticmethod
    def prepare(config=None, hand=None, options=None):
        return prepare(config, hand, options)

    def start(self, config=None, hand=None, options=None) -> dict[str, Any]:
        if self._closed:
            raise ValueError("solver adapter 已关闭")
        prepared = prepare(config, hand, options)
        state = self.jobs.submit({"kind": "solve", "config": prepared})
        metadata = {"input_source": "explicit_config" if config is not None else "structured_hand",
                    "hand_id": hand.get("id") if hand else None,
                    "amount_unit": "chips", "root_actor": "OOP",
                    "assumptions": ["两人翻后、有效剩余筹码、街开始 OOP 行动", "无未来抽水；EV 含起始底池份额，旧投入视为沉没成本",
                                    "策略与 EV 仅适用于记录的范围、尺寸、模型与计算精度"],
                    "config": prepared}
        self._metadata[state["id"]] = metadata
        save_result(ROOT / "outputs/jobs" / state["id"] / "studio_input.json", metadata)
        return {**state, "solver_input": copy.deepcopy(metadata)}

    def status(self, job_id: str) -> dict[str, Any]:
        return self.jobs.status(job_id)

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self.jobs.cancel(job_id)

    def result(self, job_id: str) -> dict[str, Any]:
        state = self.jobs.status(job_id)
        if state["state"] != "completed":
            raise ValueError("solver 任务未成功完成：" + state["state"] + ("；" + state["error"] if state.get("error") else ""))
        result = self.jobs.source(job_id)
        path = ROOT / "outputs/jobs" / job_id / "studio_input.json"
        metadata = self._metadata.get(job_id)
        if metadata is None and path.exists():
            metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata:
            result["studio_adapter"] = copy.deepcopy(metadata)
        return result

    def inspect(self, job_id: str, path: list[int] | None = None, variant: str = "response") -> dict[str, Any]:
        if self._closed:
            raise ValueError("solver adapter 已关闭")
        self.result(job_id)
        if variant not in {"baseline", "model", "response"}:
            raise ValueError("variant 必须为 baseline/model/response")
        path = [] if path is None else path
        if not isinstance(path, list) or len(path) > 100 or any(type(p) is not int or p < 0 for p in path):
            raise ValueError("节点 path 无效")
        return self.jobs.submit({"kind": "node", "source": job_id, "path": path, "variant": variant})

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.jobs.close()  # Cancel only this instance's jobs; wait/reap workers.

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
