"""Live games: stake presets ($5/$5/$10 three blinds by default) and position-based seating.

Typed live notes name positions, not seat numbers. ``build_live_hand`` turns a
position-based description into a seat-based ``pokerlab-hand-v1`` record: seats
1..N follow the clockwise order SB, (MB), BB, early positions, ..., BTN, the
button is seat N, unnamed seats become anonymous players (``#UTG+1``) and the
blind posts come from the preset, so the assistant never has to do seat
arithmetic or remember blind sizes.
"""
from __future__ import annotations

import copy
import itertools

from .hands import MIDDLE, normalize, replay

PRESETS = {
    "live-5-5-10": {"label": "$5/$5/$10 三盲（SB 5 / MB 5 / BB 10）", "small_blind": 5, "middle_blind": 5,
                       "big_blind": 10, "unit_scale": 1, "currency": "USD", "table_size": 9},
    "live-1-3": {"label": "现场 $1/$3", "small_blind": 1, "big_blind": 3, "unit_scale": 1, "currency": "USD", "table_size": 9},
    "live-2-5": {"label": "现场 $2/$5", "small_blind": 2, "big_blind": 5, "unit_scale": 1, "currency": "USD", "table_size": 9},
    "live-5-10": {"label": "现场 $5/$10（两个盲注）", "small_blind": 5, "big_blind": 10, "unit_scale": 1, "currency": "USD", "table_size": 9},
}
DEFAULT_PRESET = "live-5-5-10"
SYNONYMS = {"EP": "UTG", "UTG1": "UTG+1", "+1": "UTG+1", "UTG+1": "UTG+1", "+2": "UTG+2", "UTG2": "UTG+2", "MP": "LJ",
            "MP1": "LJ", "MP2": "HJ", "BU": "BTN", "BUTTON": "BTN", "D": "BTN", "DEALER": "BTN", "STR": "UTG",
            "STRADDLE": "UTG", "SMALL": "SB", "MIDDLE": "MB", "BIG": "BB"}


def layout(table_size, middle_blind):
    """Positions in seat order 1..N (clockwise from the small blind; the button is seat N)."""
    blinds = ["SB", "MB", "BB"] if middle_blind else ["SB", "BB"]
    middle = len(blinds) + 1
    if not middle <= table_size <= 10:
        raise ValueError(f"桌子人数需要在 {middle}–10 之间")
    return blinds + MIDDLE[table_size - middle] + ["BTN"]


UNKNOWN = {"", "?", "UNKNOWN", "NONE", "未知", "不确定"}
MAX_TRIALS = 5000


def canonical_position(text):
    value = str(text).strip().upper().replace(" ", "")
    return SYNONYMS.get(value, value)


def _unknown(position):
    return position is None or canonical_position(position) in UNKNOWN


def build_live_hand(spec, default_preset=DEFAULT_PRESET):
    return build_live_hand_with_guesses(spec, default_preset)[0]


def build_live_hand_with_guesses(spec, default_preset=DEFAULT_PRESET):
    """Fill game, seats, button and blind posts for a position-based live hand; seat-based hands pass through.

    Players whose position is unknown (``null``) get the free positions that let the
    recorded actions replay without errors and with the fewest filled-in actions;
    those guesses are returned and written into the hand notes.
    """
    if not isinstance(spec, dict):
        raise ValueError("手牌必须是 JSON 对象")
    hand = copy.deepcopy(spec)
    game = dict(hand.get("game") or {})
    key = game.get("preset") or default_preset
    if key not in PRESETS:
        raise ValueError(f"未知级别 {key}；可用：{', '.join(PRESETS)}")
    preset = PRESETS[key]
    for field in ("small_blind", "big_blind", "unit_scale", "currency", "middle_blind"):
        if field in preset:
            game.setdefault(field, preset[field])
    game["preset"] = key
    hand["game"] = game
    hand.setdefault("source", {"kind": "live_text"})
    players = hand.get("players")
    if not isinstance(players, list) or not players:
        raise ValueError("players 不能为空")
    if all("seat" in p for p in players):
        hand.pop("table_size", None)
        return hand, []
    if any("seat" in p for p in players):
        raise ValueError("players 要么都写 seat，要么都写 position，不能混用")
    size = hand.pop("table_size", None) or preset["table_size"]
    order = layout(size, game.get("middle_blind") is not None)
    by_position, unknown = {}, []
    for p in players:
        if not isinstance(p, dict) or "position" not in p or not isinstance(p.get("name"), str):
            raise ValueError("按位置记录时，每个玩家都要有 name 和 position（不知道写 null）")
        if _unknown(p["position"]):
            unknown.append({k: v for k, v in p.items() if k != "position"})
            continue
        position = canonical_position(p["position"])
        if position not in order:
            raise ValueError(f"{size} 人桌没有位置 {p['position']}；可用：{'、'.join(order)}（不知道写 null）")
        if position in by_position:
            raise ValueError(f"位置 {position} 重复")
        by_position[position] = {k: v for k, v in p.items() if k != "position"}
    free = [position for position in order if position not in by_position]
    if len(unknown) > len(free):
        raise ValueError("位置未知的玩家比空座位还多")
    if not unknown:
        return _seat(hand, game, order, by_position, size, straddle_spec=hand.pop("straddle", None)), []
    straddle = hand.pop("straddle", None)
    best, failure = None, None
    for trial, combo in enumerate(itertools.permutations(free, len(unknown))):
        if trial >= MAX_TRIALS:
            break
        placed = {**by_position, **dict(zip(combo, unknown))}
        try:
            candidate = _seat(copy.deepcopy(hand), game, order, placed, size, straddle)
            r = replay(normalize(candidate))
        except ValueError as exc:
            failure = exc
            continue
        score = (len(r.errors), sum(d.inferred for d in r.decisions), [order.index(p) for p in combo])
        if best is None or score < best[0]:
            best = (score, candidate, combo)
    if best is None:
        # Every seating failed the same structural check; report that check, not the seating.
        raise ValueError(str(failure) if failure else "位置未知的玩家无法安排到任何空座位")
    guesses = [f"{player['name']}={position}" for position, player in zip(best[2], unknown)]
    candidate = best[1]
    prefix = "[系统] 位置未知，按行动顺序暂定：" + "，".join(guesses)
    candidate["notes"] = prefix + ("\n" + candidate["notes"] if candidate.get("notes") else "")
    return candidate, guesses


def _seat(hand, game, order, by_position, size, straddle_spec):
    """Seat players by position, fill anonymous seats, the button and the preset's blind posts."""
    hand["players"] = []
    for seat, position in enumerate(order, 1):
        player = by_position.get(position) or {"name": f"#{position}"}
        hand["players"].append({"seat": seat, "name": player["name"], "stack": player.get("stack"), "cards": player.get("cards")})
    hand["button_seat"] = size
    name_at = {position: (by_position.get(position) or {"name": f"#{position}"})["name"] for position in order}
    straddle = straddle_spec
    if "posts" not in hand:
        if game.get("bomb_pot"):
            ante = game.get("bomb_pot_ante")
            hand["posts"] = [{"player": n, "kind": "ante", "amount": ante} for n in name_at.values()] if ante else []
        else:
            hand["posts"] = [{"player": name_at["SB"], "kind": "sb", "amount": game["small_blind"]}]
            if game.get("middle_blind") is not None:
                hand["posts"].append({"player": name_at["MB"], "kind": "mb", "amount": game["middle_blind"]})
            hand["posts"].append({"player": name_at["BB"], "kind": "bb", "amount": game["big_blind"]})
            if straddle:
                position = canonical_position(straddle.get("position", "UTG"))
                if position not in name_at or not isinstance(straddle.get("amount"), int):
                    raise ValueError("straddle 需要合法的 position 和整数 amount")
                hand["posts"].append({"player": name_at[position], "kind": "straddle", "amount": straddle["amount"]})
    return hand
