"""The situation of a hand, worked out from its replay: Hero's cards and seat, depth, pot type, flop, line.

``features`` describes one hand; ``checks`` turns search criteria into tests on those features. Both
serve the HHP hand records and the user's own hands, so a hand under review can be compared with the
videos. A value the record does not hold stays ``None`` or absent and matches nothing; it is never guessed.
"""
from __future__ import annotations

import re

from .hands import RANKS, STREETS

GROUPS = {"EP": {"UTG", "UTG+1", "UTG+2", "UTG+3", "LJ"}, "MP": {"LJ", "HJ"}, "LP": {"CO", "BTN"}, "blinds": {"SB", "MB", "BB"}}
POT_TYPES = ("limped", "single_raised", "iso", "3bet", "squeeze", "4bet", "5bet")
BOARD_TAGS = ("A_high", "K_high", "Q_high", "J_high", "T_high", "low", "paired", "trips", "monotone", "two_tone",
              "rainbow", "connected", "dry", "wet")
HIGH = {"A": "A_high", "K": "K_high", "Q": "Q_high", "J": "J_high", "T": "T_high"}
WEIGHTS = {"cards": 3, "pot_type": 3, "line": 3, "facing": 2, "position": 2, "in_position": 2, "multiway": 2, "depth": 2,
           "board": 2, "opponent_position": 1, "text": 2}
COMBO = re.compile(r"^([2-9TJQKA])([2-9TJQKAX])([SO]?)$")


def rank(card):
    return RANKS.index(card[0])


def combo(cards):
    """'JJ', 'AKs', 'AKo', or 'AK' when a suit is unknown; ``None`` unless both ranks are known."""
    if not cards or "??" in cards:
        return None
    high, low = sorted(cards, key=rank, reverse=True)
    if high[0] == low[0]:
        return high[0] * 2
    if "x" in (high[1], low[1]):
        return high[0] + low[0]
    return high[0] + low[0] + ("s" if high[1] == low[1] else "o")


def holds(actual, wanted):
    """Does a holding fit a query such as JJ, AKs, AK or Ax (any ace), Axs (any suited ace)?"""
    m = COMBO.match(wanted.upper().replace("10", "T"))
    if not m:
        raise ValueError(f"cards 写 JJ、AKs、AKo、AK 或 Ax 这样的牌型，不是：{wanted}")
    if actual is None:
        return False
    first, second, suited = m[1], m[2], m[3].lower()
    ranks = actual[:2]
    if second == "X":
        fits = first in ranks
    else:
        fits = sorted(ranks) == sorted(first + second)
    if suited:
        return fits and len(actual) == 3 and actual[2] == suited and ranks[0] != ranks[1]
    return fits


def board_tags(board):
    flop = board[:3]
    if len(flop) < 3 or "??" in flop:
        return set()
    top = max(flop, key=rank)[0]
    tags = {HIGH.get(top, "low")}
    values = {rank(c) + 2 for c in flop}
    if len(values) == 2:
        tags.add("paired")
    elif len(values) == 1:
        tags.add("trips")
    else:
        wheel = {1 if v == 14 else v for v in values}
        if max(values) - min(values) <= 4 or max(wheel) - min(wheel) <= 4:
            tags.add("connected")
    suits = {c[1] for c in flop}
    if "x" not in suits:
        tags.add({1: "monotone", 2: "two_tone", 3: "rainbow"}[len(suits)])
        if "rainbow" in tags and "connected" not in tags:
            tags.add("dry")
        elif "rainbow" not in tags and "connected" in tags:
            tags.add("wet")
    return tags


def position_tags(position, seats):
    if position is None:
        return set()
    tags = {position} | {group for group, members in GROUPS.items() if position in members}
    if position == "UTG" and seats <= 6:  # HHP calls the first of six seats LJ; the replay calls it UTG
        tags |= {"LJ", "MP"}
    return tags


def preflop_lines(hand, r):
    """Labels of the raises in order, pot-type tags, and Hero's line and what Hero faced before the flop."""
    hero = hand["hero"]
    pot, line, facing, raises = set(), set(), set(), []
    limps = calls = 0
    last = None
    for d in r.decisions:
        if d.street != "preflop":
            continue
        count = len(raises)
        if d.player == hero:
            if raises and last.player != hero and d.facing > 0:
                facing.add(f"preflop:{raises[-1]}")
                if last.all_in:
                    facing.add("preflop:all_in")
            name = ("open", "3bet", "4bet")[count] if count < 3 else "5bet"
            suffix = {0: "", 1: "open", 2: "3bet", 3: "4bet"}.get(count, "5bet")
            if d.kind == "raise":
                line.add("preflop:" + ("iso" if count == 0 and limps else "squeeze" if count == 1 and calls else name))
                line.add("preflop:raise")
            elif d.kind == "call":
                line.add("preflop:call_" + suffix if count else "preflop:limp")
                if count:
                    line.add("preflop:call")
            elif d.kind == "fold":
                line.add("preflop:fold")
                if count:
                    line.add("preflop:fold_" + suffix)
            elif d.kind == "check":
                line.add("preflop:check")
        if d.kind == "raise":
            if count == 0:
                raises.append("iso" if limps else "open")
            elif count == 1:
                raises.append("squeeze" if calls else "3bet")
            else:
                raises.append("4bet" if count == 2 else "5bet")
            calls = 0
            last = d
        elif d.kind == "call":
            calls += 1
            limps += 0 if raises else 1
    if last is not None and last.player != hero and to_decide(hand, r, "preflop", last):
        facing.add(f"preflop:{raises[-1]}")
        if last.all_in:
            facing.add("preflop:all_in")
    if not raises:
        pot.add("limped" if limps else "walk")
    else:
        pot.add({1: "single_raised", 2: "3bet", 3: "4bet"}.get(len(raises), "5bet"))
        pot |= {label for label in raises if label in ("iso", "squeeze")}
    return pot, line, facing


def postflop_lines(hand, r):
    """Hero's line on each street after the flop comes (flop:check_raise, turn:cbet) and what Hero faced."""
    hero = hand["hero"]
    line, facing = set(), set()
    for number, street in enumerate(STREETS[1:], 1):
        actions = [d for d in r.decisions if d.street == street]
        mine = [d for d in actions if d.player == hero]
        kinds = [d.kind for d in mine]
        if kinds:
            line |= {f"{street}:{'_'.join(kinds)}"} | {f"{street}:{k}" for k in kinds}
        aggressor = r.street_aggressor.get(STREETS[number - 1])
        last, acted = None, set()
        for d in actions:
            if d.player == hero:
                if d.kind == "bet" and aggressor == hero:
                    line.add(f"{street}:cbet")
                if d.kind == "bet" and aggressor not in (None, hero) and aggressor not in acted and aggressor in r.saw.get(street, ()):
                    line.add(f"{street}:donk")
                if d.facing > 0 and last is not None:
                    facing |= faced(street, last, d.street_bets)
            elif d.kind in ("bet", "raise"):
                last = d
            acted.add(d.player)
        if last is not None and to_decide(hand, r, street, last):
            facing |= faced(street, last, sum(d.kind in ("bet", "raise") for d in actions))
    return line, facing


def faced(street, last, bets):
    tags = {f"{street}:{'bet' if bets == 1 else 'raise' if bets == 2 else 'reraise'}"}
    if last.checked_before and last.kind == "raise":
        tags.add(f"{street}:check_raise")
    if last.all_in:
        tags.add(f"{street}:all_in")
    return tags


def to_decide(hand, r, street, last):
    """Does the record stop with Hero facing ``last``? Teaching spots often end at that decision."""
    hero = hand["hero"]
    return (not r.complete and r.last_street == street and hero in r.active_at_end
            and not any(d.street == street and d.player == hero and d.index > last.index for d in r.decisions))


def features(hand, r):
    """What the hand looks like from Hero's seat; ``None`` when the record names no Hero."""
    hero = hand["hero"]
    if hero is None:
        return None
    seats = {p["name"]: p for p in hand["players"]}
    preflop = [d for d in r.decisions if d.street == "preflop"]
    flop = r.saw.get("flop")
    rivals = [n for n in flop if n != hero] if flop else list(dict.fromkeys(
        d.player for d in preflop if d.player != hero and d.kind in ("call", "raise")))
    pot, line, facing = preflop_lines(hand, r)
    after, faced = postflop_lines(hand, r)
    stacks = [seats[n]["stack"] for n in (rivals or [n for n in seats if n != hero])]
    mine = seats[hero]["stack"]
    known = mine is not None and stacks and None not in stacks
    count = len(hand["players"])
    unit = max([p["amount"] for p in hand["posts"] if p["kind"] in ("bb", "straddle")], default=hand["game"]["big_blind"])
    return {"hero": hero, "position": r.positions.get(hero), "positions": position_tags(r.positions.get(hero), count),
            "rivals": sorted(r.positions.get(n, "?") for n in rivals),
            "rival_positions": set().union(*[position_tags(r.positions.get(n), count) for n in rivals]) if rivals else set(),
            "cards": seats[hero]["cards"], "combo": combo(seats[hero]["cards"]),
            "depth_bb": round(min(mine, max(stacks)) / unit, 1) if known else None,
            "pot": pot, "players_to_flop": len(flop) if flop else None,
            "multiway": len(flop) > 2 if flop else None,
            "in_position": (flop[-1] == hero) if flop and hero in flop else None,
            "board": hand["board"], "board_tags": board_tags(hand["board"]), "line": line | after, "facing": facing | faced}


def wanted_list(value):
    return value if isinstance(value, list) else [value]


def checks(criteria):
    """(label, kind, test) for every criterion; a list of cards, seats or pot types means any of them."""
    out = []
    if criteria.get("cards"):
        wanted = wanted_list(criteria["cards"])
        for item in wanted:
            holds(None, item)  # reject a bad query even when no record is tested
        out.append(("cards:" + "/".join(wanted), "cards", lambda f, w=wanted: any(holds(f["combo"], c) for c in w)))
    if criteria.get("position"):
        wanted = set(wanted_list(criteria["position"]))
        out.append(("position:" + "/".join(sorted(wanted)), "position", lambda f, w=wanted: bool(w & f["positions"])))
    if criteria.get("opponent_position"):
        wanted = set(wanted_list(criteria["opponent_position"]))
        out.append(("opponent_position:" + "/".join(sorted(wanted)), "opponent_position",
                    lambda f, w=wanted: bool(w & f["rival_positions"])))
    if criteria.get("pot_type"):
        wanted = set(wanted_list(criteria["pot_type"]))
        out.append(("pot_type:" + "/".join(sorted(wanted)), "pot_type", lambda f, w=wanted: bool(w & f["pot"])))
    low, high = criteria.get("depth_min_bb"), criteria.get("depth_max_bb")
    if low is not None or high is not None:
        low, high = low if low is not None else 0, high if high is not None else 100000
        out.append((f"depth:{low}-{high}bb", "depth",
                    lambda f, a=low, b=high: f["depth_bb"] is not None and a <= f["depth_bb"] <= b))
    for key, field in (("in_position", "in_position"), ("multiway", "multiway")):
        if criteria.get(key) is not None:
            out.append((f"{key}:{str(criteria[key]).lower()}", key, lambda f, k=field, v=criteria[key]: f[k] is v))
    for tag in wanted_list(criteria.get("board") or []):
        out.append((f"board:{tag}", "board", lambda f, t=tag: t in f["board_tags"]))
    for tag in wanted_list(criteria.get("line") or []):
        out.append((f"line:{tag}", "line", lambda f, t=tag: t in f["line"]))
    for tag in wanted_list(criteria.get("facing") or []):
        out.append((f"facing:{tag}", "facing", lambda f, t=tag: t in f["facing"]))
    return out


def criteria_of(f):
    """Search criteria describing a hand of the user's, for finding the closest video hands."""
    out = {"position": f["position"], "pot_type": sorted(f["pot"] & set(POT_TYPES))}
    if f["combo"]:
        out["cards"] = f["combo"]
    if f["depth_bb"] is not None:
        out["depth_min_bb"], out["depth_max_bb"] = round(f["depth_bb"] * 0.7), round(f["depth_bb"] * 1.4)
    if f["in_position"] is not None:
        out["in_position"] = f["in_position"]
    if f["multiway"] is not None:
        out["multiway"] = f["multiway"]
    line = f["line"] - {"preflop:raise"}
    for tag in f["line"]:
        street, action = tag.split(":")
        if "_" in action:  # flop:check_raise says more than flop:check and flop:raise
            line -= {f"{street}:{part}" for part in action.split("_")}
    out["board"], out["line"], out["facing"] = sorted(f["board_tags"] - {"dry", "wet"}), sorted(line), sorted(f["facing"])
    return out
