"""Canonical No-Limit Hold'em hand record (``pokerlab-hand-v1``) and replay validation.

Conventions
- Amounts are integers in minor units; ``game.unit_scale`` minor units make one
  displayed unit (100 for dollars with cents, 1 for whole dollars or chips).
- ``to`` on call/bet/raise is the actor's total commitment on the current street
  after the action. Live posts (sb, bb, straddle, post) count as preflop
  commitment; antes and dead money do not.
- Unknown values are ``None`` and are never guessed. Checks that need them are
  skipped; the replay says so.

Strictness: site histories (``source.kind == "pokerstars"``) are machine
written, so amount and stack mismatches are errors. Typed live hands are
approximate, so the same findings are warnings there, and players skipped in
the action order are filled in as inferred folds (facing a bet) or checks.
Action-order and legality violations are errors in both cases.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
import re

SCHEMA = "pokerlab-hand-v1"
RANKS, SUITS = "23456789TJQKA", "cdhs"
STREETS = ("preflop", "flop", "turn", "river")
STREET_CN = {"preflop": "翻前", "flop": "翻牌", "turn": "转牌", "river": "河牌"}
BOARD_SIZE = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}
LIVE_POSTS, DEAD_POSTS = ("sb", "mb", "bb", "straddle", "post"), ("ante", "dead")
ACTIONS = ("fold", "check", "call", "bet", "raise")
SOURCES = ("pokerstars", "live_text", "manual")
HAND_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
# Seats between the big blind and the button, by count (first one acts first preflop).
MIDDLE = {0: [], 1: ["CO"], 2: ["HJ", "CO"], 3: ["UTG", "HJ", "CO"], 4: ["UTG", "LJ", "HJ", "CO"],
          5: ["UTG", "UTG+1", "LJ", "HJ", "CO"], 6: ["UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO"],
          7: ["UTG", "UTG+1", "UTG+2", "UTG+3", "LJ", "HJ", "CO"]}


def card(text):
    """``As`` style; an unknown suit is ``x`` (``Qx``) and a fully unknown card is ``??``."""
    value = str(text).strip()
    if value in ("??", "xx", "XX", "Xx", "?x", "x?"):
        return "??"
    if value[:2] == "10":
        value = "T" + value[2:]
    if len(value) != 2 or value[0].upper() not in RANKS or value[1].lower() not in SUITS + "x?":
        raise ValueError(f"无效牌张：{text}（花色未知写 x，例如 Qx）")
    return value[0].upper() + ("x" if value[1] in "xX?" else value[1].lower())


def _cards(values, what, count=None, maximum=None):
    if values is None:
        return None
    if not isinstance(values, list):
        raise ValueError(f"{what}必须是数组")
    result = [card(v) for v in values]
    if count is not None and len(result) != count:
        raise ValueError(f"{what}应为 {count} 张")
    if maximum is not None and len(result) > maximum:
        raise ValueError(f"{what}最多 {maximum} 张")
    return result


def _int(value, what, minimum=0, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{what}必须是不小于 {minimum} 的整数（单位：最小金额单位）")
    return value


def _text(value, what, limit, optional=True):
    if value is None and optional:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{what}必须是不超过 {limit} 字的文字")
    return value


def normalize(hand):
    """Structural validation; returns a normalized deep copy or raises ValueError."""
    if not isinstance(hand, dict):
        raise ValueError("手牌必须是 JSON 对象")
    h = copy.deepcopy(hand)
    known = {"schema", "hand_id", "source", "game", "played_at", "table", "button_seat", "players", "posts",
             "actions", "board", "board_texture", "showdown", "collected", "rake", "hero", "notes"}
    if set(h) - known:
        raise ValueError("手牌包含未知字段：" + ", ".join(sorted(set(h) - known)))
    if h.get("schema", SCHEMA) != SCHEMA:
        raise ValueError(f"只支持 {SCHEMA} 格式")
    if not isinstance(h.get("hand_id"), str) or not HAND_ID.match(h["hand_id"]):
        raise ValueError("hand_id 只能用字母、数字和 ._:-，以字母或数字开头，最长 80")
    source = h.get("source") or {}
    if not isinstance(source, dict) or source.get("kind") not in SOURCES:
        raise ValueError("source.kind 必须是 pokerstars / live_text / manual")
    game = h.get("game") or {}
    if not isinstance(game, dict) or game.get("variant", "NLHE") != "NLHE":
        raise ValueError("目前只支持无限注德州（NLHE）")
    out = {"schema": SCHEMA, "hand_id": h["hand_id"],
           "source": {"kind": source["kind"], "site": _text(source.get("site"), "source.site", 40),
                      "raw_id": _text(source.get("raw_id"), "source.raw_id", 80)},
           "game": {"variant": "NLHE", "small_blind": _int(game.get("small_blind"), "小盲", 1),
                    "big_blind": _int(game.get("big_blind"), "大盲", 1),
                    "unit_scale": _int(game.get("unit_scale", 1), "unit_scale", 1),
                    "currency": _text(game.get("currency") or "chips", "currency", 12, False),
                    "tournament": bool(game.get("tournament", False)),
                    "middle_blind": _int(game.get("middle_blind"), "中盲 MB", 1, optional=True),
                    "preset": _text(game.get("preset"), "game.preset", 40),
                    "bomb_pot": bool(game.get("bomb_pot", False)),
                    "bomb_pot_ante": _int(game.get("bomb_pot_ante"), "bomb pot 每人底注", 1, optional=True)},
           "played_at": _text(h.get("played_at"), "played_at", 40), "table": _text(h.get("table"), "table", 80),
           "button_seat": _int(h.get("button_seat"), "button_seat", 1),
           "rake": _int(h.get("rake"), "rake", 0, optional=True), "notes": _text(h.get("notes"), "notes", 4000),
           "board_texture": _text(h.get("board_texture"), "board_texture", 60)}
    if out["game"]["small_blind"] > out["game"]["big_blind"]:
        raise ValueError("小盲不能大于大盲")
    players = h.get("players")
    if not isinstance(players, list) or not 2 <= len(players) <= 10:
        raise ValueError("players 需要 2–10 人")
    seats, names, normalized_players = set(), set(), []
    for p in players:
        if not isinstance(p, dict) or set(p) - {"seat", "name", "stack", "cards"}:
            raise ValueError("玩家记录只能包含 seat / name / stack / cards")
        name = p.get("name").strip() if isinstance(p.get("name"), str) else ""
        if not name or len(name) > 60:
            raise ValueError("玩家名字不能为空，最长 60 字")
        seat = _int(p.get("seat"), f"{name} 的座位号", 1)
        if seat in seats or name in names:
            raise ValueError(f"座位或名字重复：{seat} / {name}")
        seats.add(seat); names.add(name)
        normalized_players.append({"seat": seat, "name": name, "stack": _int(p.get("stack"), f"{name} 的筹码", 0, True),
                                   "cards": _cards(p.get("cards"), f"{name} 的底牌", count=2)})
    out["players"] = sorted(normalized_players, key=lambda p: p["seat"])

    def who(value, where):
        if value not in names:
            raise ValueError(f"{where}引用了不在座位表中的玩家：{value}")
        return value

    out["posts"] = []
    for post in h.get("posts") or []:
        if not isinstance(post, dict) or post.get("kind") not in LIVE_POSTS + DEAD_POSTS:
            raise ValueError("posts 的 kind 必须是 sb / mb / bb / straddle / post / ante / dead")
        out["posts"].append({"player": who(post.get("player"), "posts "), "kind": post["kind"],
                             "amount": _int(post.get("amount"), "盲注金额", 1)})
    out["actions"] = []
    for index, action in enumerate(h.get("actions") or []):
        if not isinstance(action, dict) or action.get("street") not in STREETS or action.get("kind") not in ACTIONS:
            raise ValueError(f"第 {index + 1} 个行动缺少合法的 street / kind")
        if set(action) - {"street", "player", "kind", "to", "all_in", "inferred"}:
            raise ValueError(f"第 {index + 1} 个行动包含未知字段")
        item = {"street": action["street"], "player": who(action.get("player"), "actions "), "kind": action["kind"],
                "to": _int(action.get("to"), f"第 {index + 1} 个行动的 to", 0, True)}
        if item["kind"] in ("bet", "raise") and item["to"] is None:
            raise ValueError(f"第 {index + 1} 个行动是 {item['kind']}，必须给出 to（本街累计投入）")
        if item["kind"] in ("fold", "check") and item["to"] is not None:
            raise ValueError(f"第 {index + 1} 个行动是 {item['kind']}，不能带 to")
        if action.get("all_in"):
            item["all_in"] = True
        if action.get("inferred"):
            item["inferred"] = True
        out["actions"].append(item)
    out["board"] = _cards(h.get("board") or [], "公共牌", maximum=5)
    out["showdown"] = []
    for shown in h.get("showdown") or []:
        if not isinstance(shown, dict):
            raise ValueError("showdown 记录必须是对象")
        out["showdown"].append({"player": who(shown.get("player"), "showdown "),
                                "cards": _cards(shown.get("cards"), "亮牌", count=2)})
    out["collected"] = []
    for won in h.get("collected") or []:
        if not isinstance(won, dict):
            raise ValueError("collected 记录必须是对象")
        out["collected"].append({"player": who(won.get("player"), "collected "), "amount": _int(won.get("amount"), "赢得金额", 0)})
    out["hero"] = who(h["hero"], "hero ") if h.get("hero") is not None else None
    return out


def position_names(ring, middle_blind=False):
    """``ring`` lists players clockwise starting left of the button; ``middle_blind`` adds MB after SB."""
    if len(ring) == 2:
        return {ring[0]: "BB", ring[1]: "BTN"}
    blinds = ["SB", "MB", "BB"] if middle_blind and len(ring) >= 4 else ["SB", "BB"]
    names = dict(zip(ring, blinds))
    names[ring[-1]] = "BTN"
    names.update(zip(ring[len(blinds):-1], MIDDLE[len(ring) - len(blinds) - 1]))
    return names


@dataclass
class Decision:
    """One action with the situation the actor faced."""
    index: int
    street: str
    player: str
    kind: str
    to: int | None
    added: int
    inferred: bool
    facing: int              # chips needed to call before acting
    street_bets: int         # bets and raises already made this street (preflop: voluntary raises only)
    voluntary_before: int    # preflop: calls and raises already made by anyone
    first_bettor: str | None
    acted_before: bool
    checked_before: bool
    position: str
    all_in: bool


@dataclass
class Replay:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    positions: dict = field(default_factory=dict)
    contributed: dict = field(default_factory=dict)
    pot: int = 0
    returned: tuple | None = None
    preflop_aggressor: str | None = None
    street_aggressor: dict = field(default_factory=dict)
    saw: dict = field(default_factory=dict)          # street -> players still in at the start of it
    active_at_end: list = field(default_factory=list)
    showdown: bool = False
    complete: bool = False
    last_street: str = "preflop"

    def summary(self):
        return {"errors": list(self.errors), "warnings": list(self.warnings), "positions": dict(self.positions),
                "pot": self.pot, "returned": list(self.returned) if self.returned else None,
                "preflop_aggressor": self.preflop_aggressor, "showdown": self.showdown, "complete": self.complete,
                "last_street": self.last_street, "active_at_end": list(self.active_at_end),
                "inferred_actions": sum(d.inferred for d in self.decisions)}


class _Stop(Exception):
    pass


def replay(hand):
    """Replay a normalized hand action by action; never raises on poker problems."""
    r = Replay()
    strict = hand["source"]["kind"] == "pokerstars"
    bb = hand["game"]["big_blind"]

    def issue(text):
        (r.errors if strict else r.warnings).append(text)

    def fail(text):
        r.errors.append(text)
        raise _Stop

    players = hand["players"]
    button = hand["button_seat"]
    bomb_pot = hand["game"]["bomb_pot"]
    ring = [p["name"] for p in players if p["seat"] > button] + [p["name"] for p in players if p["seat"] <= button]
    has_mb = hand["game"]["middle_blind"] is not None or any(p["kind"] == "mb" for p in hand["posts"])
    r.positions = position_names(ring, has_mb)
    if button not in {p["seat"] for p in players}:
        r.warnings.append("按钮位没有玩家（死按钮）；位置按座位顺序推算")
    stack = {p["name"]: p["stack"] for p in players}
    committed = dict.fromkeys(ring, 0)
    total = dict.fromkeys(ring, 0)
    folded, allin = set(), set()
    state = {"street": "preflop", "current": 0, "increment": bb, "bets": 0, "voluntary": 0, "first": None,
             "acted": set(), "checked": set(), "blocked": set(), "since_full": set(), "pending": [], "over": False}

    def after(name):
        i = ring.index(name)
        return ring[i + 1:] + ring[:i + 1]

    def pay(name, amount, live):
        if stack[name] is not None:
            if amount > stack[name]:
                issue(f"{name} 投入 {amount}，超过记录的剩余筹码 {stack[name]}；此后按筹码未知处理")
                stack[name] = None
            else:
                stack[name] -= amount
                if stack[name] == 0:
                    allin.add(name)
        total[name] += amount
        if live:
            committed[name] += amount
        return amount

    def start_street(name):
        state.update(street=name, current=0, increment=bb, bets=0, first=None, acted=set(), checked=set(),
                     blocked=set(), since_full=set())
        for n in ring:
            committed[n] = 0
        live = [n for n in ring if n not in folded]
        r.saw[name] = live
        r.last_street = name
        can_bet = [n for n in live if n not in allin]
        state["pending"] = can_bet if len(can_bet) >= 2 else []

    def act(index, player, kind, to, inferred, flagged_all_in):
        st = state["street"]
        facing = state["current"] - committed[player]
        decision = Decision(index, st, player, kind, to, 0, inferred, facing, state["bets"], state["voluntary"],
                            state["first"], player in state["acted"], player in state["checked"],
                            r.positions.get(player, "?"), False)
        if kind in ("bet", "raise"):
            if kind == "bet" and state["current"] > 0:
                (r.warnings if not strict else r.errors).append(f"{player} 在已有下注时记录为 bet，按 raise 处理")
                kind = decision.kind = "raise"
            elif kind == "raise" and state["current"] == 0:
                (r.warnings if not strict else r.errors).append(f"{player} 在无人下注时记录为 raise，按 bet 处理")
                kind = decision.kind = "bet"
        if kind == "fold":
            folded.add(player)
        elif kind == "check":
            if facing > 0:
                fail(f"{STREET_CN[st]}：{player} 面对 {facing} 的下注不能过牌")
            state["checked"].add(player)
        elif kind == "call":
            if facing <= 0:
                fail(f"{STREET_CN[st]}：{player} 没有下注可以跟")
            need = facing if stack[player] is None else min(facing, stack[player])
            if stack[player] is None and flagged_all_in and to is not None and to - committed[player] < facing:
                need = to - committed[player]
            if to is not None and to != committed[player] + need:
                issue(f"{STREET_CN[st]}：{player} 跟注后应累计 {committed[player] + need}，记录为 {to}")
            decision.added = pay(player, need, True)
            decision.to = committed[player]
        else:
            if to <= state["current"]:
                fail(f"{STREET_CN[st]}：{player} 的 {kind} 到 {to}，不大于当前下注 {state['current']}")
            if player in state["blocked"]:
                issue(f"{STREET_CN[st]}：不足额的全下加注没有重新开放加注，{player} 只能跟注或弃牌")
            need = to - committed[player]
            reaches_all_in = stack[player] is not None and need == stack[player]
            step = to - state["current"]
            full = step >= state["increment"]
            if kind == "bet" and to < bb and not (reaches_all_in or flagged_all_in):
                issue(f"{STREET_CN[st]}：{player} 下注 {to} 小于一个大盲 {bb}")
            elif kind == "raise" and not full and not (reaches_all_in or flagged_all_in):
                issue(f"{STREET_CN[st]}：{player} 加注幅度 {step} 小于最小加注 {state['increment']}")
            decision.added = pay(player, need, True)
            if full:
                state["increment"], state["blocked"], state["since_full"] = step, set(), set()
            else:
                state["blocked"] |= state["since_full"] - {player}
            state["current"] = to
            state["bets"] += 1
            state["first"] = state["first"] or player
            r.street_aggressor[st] = player
            if st == "preflop":
                r.preflop_aggressor = player
        if flagged_all_in and player not in allin:
            if stack[player] is None:
                allin.add(player)
            elif kind != "fold":
                issue(f"{STREET_CN[st]}：{player} 记录为全下，但按记录筹码还剩 {stack[player]}")
        decision.all_in = player in allin and kind != "fold"
        if st == "preflop" and kind in ("call", "raise", "bet"):
            state["voluntary"] += 1
        state["acted"].add(player)
        state["since_full"].add(player)
        if kind in ("bet", "raise"):
            state["pending"] = [n for n in after(player) if n != player and n not in folded and n not in allin]
        else:
            state["pending"].remove(player)
        r.decisions.append(decision)
        live = [n for n in ring if n not in folded]
        if len(live) == 1:
            state["over"] = True

    def fill(index, until=None):
        """Lenient mode: players skipped before ``until`` fold facing a bet, otherwise check."""
        while state["pending"] and state["pending"][0] != until:
            name = state["pending"][0]
            kind = "fold" if state["current"] - committed[name] > 0 else "check"
            r.warnings.append(f"{STREET_CN[state['street']]}：{name} 的行动没有记录，按{'弃牌' if kind == 'fold' else '过牌'}补记")
            act(index, name, kind, None, True, False)

    first_post = {}
    for post in hand["posts"]:
        first_post.setdefault(post["kind"], post["player"])
    expected = {label: name for name, label in r.positions.items() if label in ("SB", "MB", "BB")}
    if len(ring) == 2:
        expected["SB"] = ring[1]
    recorded = {kind.upper(): first_post.get(kind) for kind in ("sb", "mb", "bb")}
    wrong = [label for label, name in recorded.items() if name is not None and expected.get(label) != name]
    if wrong and not (wrong == ["BB"] and recorded["SB"] is None and recorded["BB"] == expected.get("SB")):
        # Position labels come from the button seat; a mismatch means one of the two is mis-recorded.
        should = "、".join(f"{label} 应是 {expected[label]}" for label in ("SB", "MB", "BB") if label in expected)
        got = "、".join(f"{label} {recorded[label] or '无'}" for label in ("SB", "MB", "BB") if recorded[label] or label in expected)
        r.warnings.append(f"盲注与按钮位置不一致：按钮在 {button} 号位，按座位{should}；记录的是{got}。位置标签按按钮推算，可能有误")
    try:
        anchor = None
        for post in hand["posts"]:
            if bomb_pot and post["kind"] in LIVE_POSTS:
                fail("bomb pot 没有翻前盲注，posts 里只能有 ante")
            pay(post["player"], post["amount"], post["kind"] in LIVE_POSTS)
            if post["kind"] in ("bb", "straddle"):
                anchor = post["player"]
        r.saw["preflop"] = list(ring)
        if bomb_pot:
            if not hand["posts"]:
                r.warnings.append("bomb pot 每人底注未知：底池只含翻后下注")
            start_street("flop")  # everyone antes and sees the flop; no preflop action
        else:
            if anchor is None:
                fail("缺少大盲（bb）记录，无法确定翻前行动顺序")
            state["current"] = max(committed.values())
            state["increment"] = max(state["current"], bb)
            state["pending"] = [n for n in after(anchor) if n not in allin]
        for index, action in enumerate(hand["actions"]):
            street, player = action["street"], action["player"]
            if state["over"]:
                fail(f"第 {index + 1} 个行动：手牌已经结束，仍记录了 {player} 的行动")
            if STREETS.index(street) < STREETS.index(state["street"]):
                fail(f"第 {index + 1} 个行动：{STREET_CN[street]}行动出现在{STREET_CN[state['street']]}之后")
            while street != state["street"]:
                if state["pending"]:
                    if strict:
                        fail(f"{STREET_CN[state['street']]}行动未结束：{'、'.join(state['pending'])} 尚未行动")
                    fill(index)
                    if state["over"]:
                        fail(f"第 {index + 1} 个行动：补记后手牌已经结束，仍记录了 {player} 的行动")
                start_street(STREETS[STREETS.index(state["street"]) + 1])
            if player in folded:
                fail(f"第 {index + 1} 个行动：{player} 已经弃牌")
            if player in allin:
                fail(f"第 {index + 1} 个行动：{player} 已经全下")
            if player not in state["pending"]:
                fail(f"第 {index + 1} 个行动：{STREET_CN[street]}此时不轮到 {player}（本街行动已结束或顺序不符）")
            if state["pending"][0] != player:
                if strict:
                    fail(f"第 {index + 1} 个行动：行动顺序不符，应由 {state['pending'][0]} 行动")
                fill(index, player)
            act(index, player, action["kind"], action.get("to"), bool(action.get("inferred")), bool(action.get("all_in")))
        live = [n for n in ring if n not in folded]
        r.active_at_end = live
        if state["over"]:
            r.complete = True
        elif state["pending"]:
            issue(f"记录在{STREET_CN[state['street']]}中途结束：{'、'.join(state['pending'])} 尚未行动")
        elif state["street"] == "river" or len([n for n in live if n not in allin]) <= 1:
            r.complete, r.showdown, r.last_street = True, True, "river"
            for later in STREETS[STREETS.index(state["street"]) + 1:]:
                r.saw.setdefault(later, list(live))  # all-in runout: the remaining players see every street
        else:
            issue(f"记录在{STREET_CN[state['street']]}结束后中断，后面街道的行动没有记录")
        if r.complete:
            # Uncalled chips on the final street go back to the player who put them in.
            ordered = sorted(ring, key=lambda n: committed[n], reverse=True)
            if committed[ordered[0]] > committed[ordered[1]]:
                diff = committed[ordered[0]] - committed[ordered[1]]
                total[ordered[0]] -= diff
                r.returned = (ordered[0], diff)
    except _Stop:
        r.active_at_end = [n for n in ring if n not in folded]
    r.contributed = dict(total)
    r.pot = sum(total.values())
    _check_cards(hand, r, issue)
    if r.complete and not r.errors:
        if hand["collected"]:
            won = sum(c["amount"] for c in hand["collected"])
            expected = r.pot - (hand["rake"] or 0)
            if won != expected:
                issue(f"赢得金额合计 {won}，与底池 {r.pot} 减抽水 {hand['rake'] or 0} 不符")
    return r


def _same_cards(a, b):
    """Two holdings agree when ranks match and every suit known on both sides matches."""
    def fits(x, y):
        if "??" in (x, y):
            return True
        return x[0] == y[0] and (x[1] == "x" or y[1] == "x" or x[1] == y[1])
    return any(fits(a[0], b[i]) and fits(a[1], b[1 - i]) for i in (0, 1))


def _check_cards(hand, r, issue):
    seen, ranks = {}, {}

    def note(c, where):
        if c == "??":
            return
        ranks[c[0]] = ranks.get(c[0], 0) + 1
        if c[1] == "x":
            return
        if c in seen and seen[c] != where:
            r.errors.append(f"牌张冲突：{c} 同时出现在{seen[c]}和{where}")
        seen.setdefault(c, where)

    for c in hand["board"]:
        note(c, "公共牌")
    shown = {s["player"]: s["cards"] for s in hand["showdown"]}
    for p in hand["players"]:
        if not p["cards"]:
            continue
        cards = p["cards"]
        if p["name"] in shown:
            if not _same_cards(shown[p["name"]], cards):
                r.errors.append(f"{p['name']} 的底牌与摊牌记录不一致")
            # Count the holding once, preferring the version with more known suits.
            other = shown.pop(p["name"])
            cards = other if sum(c[1] != "x" for c in other) > sum(c[1] != "x" for c in cards) else cards
        for c in cards:
            note(c, f"{p['name']} 的底牌")
    for name, cs in shown.items():
        for c in cs:
            note(c, f"{name} 的底牌")
    crowded = sorted(rank for rank, n in ranks.items() if n > 4)
    if crowded:
        r.errors.append("同一点数超过 4 张：" + "、".join(crowded))
    if not r.complete:
        return
    needed = 5 if r.showdown else BOARD_SIZE[r.last_street]
    if len(hand["board"]) < needed:
        issue(f"公共牌只有 {len(hand['board'])} 张，按行动应至少有 {needed} 张")


def hand_summary(hand, r=None):
    """Short, model-friendly description used by tools and the UI."""
    r = r or replay(hand)
    scale = hand["game"]["unit_scale"]
    fmt = (lambda v: f"{v / scale:g}") if scale != 1 else str
    return {"hand_id": hand["hand_id"], "source": hand["source"]["kind"], "played_at": hand["played_at"],
            "stakes": "/".join(fmt(v) for v in (hand["game"]["small_blind"], hand["game"]["middle_blind"],
                                                hand["game"]["big_blind"]) if v is not None) + (" BP" if hand["game"]["bomb_pot"] else ""),
            "players": [{"name": p["name"], "position": r.positions.get(p["name"]), "stack": p["stack"]}
                        for p in hand["players"]],
            "hero": hand["hero"], "board": hand["board"], "board_texture": hand["board_texture"], "pot": r.pot,
            "unit_scale": scale, "bomb_pot": hand["game"]["bomb_pot"], "preset": hand["game"]["preset"],
            "showdown": r.showdown, "errors": len(r.errors), "warnings": len(r.warnings)}
