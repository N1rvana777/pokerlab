"""Opponent evidence: per-situation opportunities and outcomes taken from a replayed hand.

Every statistic is a count of opportunities and successes with the definitions
in ``DEFINITIONS`` (shown in the UI and docs). One observation per player per
hand, except ``aggression`` which counts every postflop decision.

Live notes hold only the hands the user chose to write down, so a rate whose
denominator is every hand dealt or every flop seen means nothing there:
``NEEDS_EVERY_HAND`` is counted from complete exports only. The other statistics
keep live hands and mark them ``selected``.
"""
from __future__ import annotations

from dataclasses import dataclass

from .hands import STREET_CN

# stat -> (name, opportunity, success)
DEFINITIONS = {
    "vpip": ("入池率 VPIP", "翻前至少行动一次（大盲在无人加注时直接结束的 walk 不算）", "主动投入筹码：跟注、补齐小盲或加注"),
    "pfr": ("翻前加注率 PFR", "同 VPIP", "翻前有加注"),
    "open_raise": ("开池加注率", "轮到他时前面无人入池（只有盲注）", "加注"),
    "open_limp": ("开池溜入率", "同开池加注", "跟注溜入"),
    "three_bet": ("3-bet 率", "第一次面对恰好一次加注", "再加注"),
    "fold_to_three_bet": ("面对 3-bet 弃牌率", "做了第一次加注后，第一次面对再加注（中间没有 4-bet）", "弃牌"),
    "cbet_flop": ("翻牌持续下注率", "翻前最后加注者在翻牌第一次有下注机会（之前无人下注）", "下注"),
    "donk_flop": ("翻牌领先下注率（donk）", "不是翻前加注者，在翻前加注者行动之前、无人下注时行动", "下注"),
    "fold_to_cbet_flop": ("面对翻牌持续下注弃牌率", "第一次面对翻前加注者的翻牌持续下注（之前没有加注）", "弃牌"),
    "raise_cbet_flop": ("加注翻牌持续下注率", "同上", "加注"),
    "cbet_turn": ("转牌第二枪率", "翻牌持续下注被跟注、无人加注，转牌第一次有下注机会", "下注"),
    "fold_to_turn_bet": ("面对转牌下注弃牌率", "第一次面对转牌的第一个下注", "弃牌"),
    "river_bet": ("河牌主动下注率", "河牌第一次有下注机会（之前无人下注）", "下注"),
    "fold_to_river_bet": ("面对河牌下注弃牌率", "第一次面对河牌的第一个下注", "弃牌"),
    "check_raise": ("过牌加注率", "同一街先过牌，之后第一次面对下注", "加注"),
    "wtsd": ("摊牌率 WTSD", "看到翻牌且手牌记录完整", "坚持到摊牌"),
    "wsd": ("摊牌胜率 W$SD", "到达摊牌且记录了赢得金额", "赢得筹码"),
    "aggression": ("翻后激进频率 AFq", "翻后每次下注、加注、跟注或弃牌（过牌不计）", "下注或加注"),
}
NEEDS_EVERY_HAND = ("vpip", "pfr", "open_raise", "open_limp", "three_bet", "fold_to_three_bet", "wtsd", "wsd")


@dataclass(frozen=True)
class Observation:
    stat: str
    player: str
    hand_id: str
    success: bool
    street: str
    inferred: bool = False
    selected: bool = False


def observations(hand, r):
    """All observations for every player in one replayed hand (hero included; callers filter).

    Bomb pots are recorded and shown but give no frequency observations: everyone
    sees the flop without preflop decisions, so they would distort every rate.
    """
    if hand["game"].get("bomb_pot"):
        return []
    out = []
    hid = hand["hand_id"]
    decisions = r.decisions
    pfa = r.preflop_aggressor
    selected = hand["source"]["kind"] == "live_text"

    def add(stat, decision_or_player, success, street=None, inferred=None):
        if selected and stat in NEEDS_EVERY_HAND:
            return
        if isinstance(decision_or_player, str):
            out.append(Observation(stat, decision_or_player, hid, bool(success), street, bool(inferred), selected))
        else:
            d = decision_or_player
            out.append(Observation(stat, d.player, hid, bool(success), d.street, d.inferred, selected))

    for p in hand["players"]:
        name = p["name"]
        pre = [d for d in decisions if d.player == name and d.street == "preflop"]
        if not pre:
            continue
        inferred = all(d.inferred for d in pre)
        add("vpip", name, any(d.kind in ("call", "raise", "bet") for d in pre), "preflop", inferred)
        add("pfr", name, any(d.kind in ("raise", "bet") for d in pre), "preflop", inferred)
        first = pre[0]
        if first.voluntary_before == 0:
            add("open_raise", first, first.kind in ("raise", "bet"))
            add("open_limp", first, first.kind == "call")
        facing_one = next((d for d in pre if d.street_bets == 1), None)
        if facing_one is not None:
            add("three_bet", facing_one, facing_one.kind in ("raise", "bet"))
        opened = next((i for i, d in enumerate(pre) if d.kind in ("raise", "bet") and d.street_bets == 0), None)
        if opened is not None:
            later = next((d for d in pre[opened + 1:]), None)
            if later is not None and later.street_bets == 2:
                add("fold_to_three_bet", later, later.kind == "fold")

    def street_of(name):
        return [d for d in decisions if d.street == name]

    flop = street_of("flop")
    if pfa and flop:
        mine = [d for d in flop if d.player == pfa]
        if mine:
            for d in flop:
                if d.player == pfa:
                    break
                if d.street_bets == 0:
                    add("donk_flop", d, d.kind == "bet")
        cbet = next((d for d in mine if d.street_bets == 0), None)
        if cbet is not None:
            add("cbet_flop", cbet, cbet.kind == "bet")
            if cbet.kind == "bet":
                counted = set()
                for d in flop[flop.index(cbet) + 1:]:
                    if d.player in counted or d.player == pfa:
                        continue
                    if d.first_bettor == pfa and d.street_bets == 1 and d.facing > 0:
                        counted.add(d.player)
                        add("fold_to_cbet_flop", d, d.kind == "fold")
                        add("raise_cbet_flop", d, d.kind == "raise")
                turn = street_of("turn")
                if r.street_aggressor.get("flop") == pfa and turn:
                    second = next((d for d in turn if d.player == pfa and d.street_bets == 0), None)
                    if second is not None:
                        add("cbet_turn", second, second.kind == "bet")
    for name in ("turn", "river"):
        street = street_of(name)
        bet = next((d for d in street if d.kind == "bet"), None)
        if bet is not None:
            counted = {bet.player}
            for d in street[street.index(bet) + 1:]:
                if d.player not in counted and d.street_bets == 1 and d.facing > 0:
                    counted.add(d.player)
                    add(f"fold_to_{name}_bet", d, d.kind == "fold")
    counted = set()
    for d in street_of("river"):
        if d.player not in counted and d.street_bets == 0:
            counted.add(d.player)
            add("river_bet", d, d.kind == "bet")
    for name in ("flop", "turn", "river"):
        street = street_of(name)
        for player in {d.player for d in street}:
            mine = [d for d in street if d.player == player]
            if mine and mine[0].kind == "check":
                answer = next((d for d in mine[1:] if d.facing > 0), None)
                if answer is not None:
                    add("check_raise", answer, answer.kind == "raise")
    if r.complete and "flop" in r.saw:
        for name in r.saw["flop"]:
            add("wtsd", name, r.showdown and name in r.active_at_end, "flop")
    if r.showdown and hand["collected"]:
        won = {c["player"]: c["amount"] for c in hand["collected"]}
        for name in r.active_at_end:
            add("wsd", name, won.get(name, 0) > 0, "river")
    for d in decisions:
        if d.street != "preflop" and d.kind != "check":
            add("aggression", d, d.kind in ("bet", "raise"))
    return out


def showdowns(hand, r):
    """Known non-hero hole cards with the line the player took, for qualitative review."""
    shown = {p["name"]: p["cards"] for p in hand["players"] if p["cards"] and p["name"] != hand["hero"]}
    shown.update({s["player"]: s["cards"] for s in hand["showdown"]})
    scale = hand["game"]["unit_scale"]
    records = []
    for name, cards in shown.items():
        parts = []
        for street in ("preflop", "flop", "turn", "river"):
            acts = [d for d in r.decisions if d.player == name and d.street == street]
            if acts:
                parts.append(STREET_CN[street] + " " + "，".join(
                    d.kind + (f" {d.to / scale:g}" if d.to and d.kind != "fold" else "") + ("（补记）" if d.inferred else "")
                    for d in acts))
        records.append({"hand_id": hand["hand_id"], "player": name, "cards": cards, "board": hand["board"],
                        "position": r.positions.get(name), "line": " · ".join(parts),
                        "reached_showdown": r.showdown and name in r.active_at_end})
    return records
