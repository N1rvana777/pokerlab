"""PokerStars-format No-Limit Hold'em histories (cash and tournament) to ``pokerlab-hand-v1``.

GGPoker exports share the layout ("Poker Hand #..."); the same patterns accept
them, but only synthetic examples have been checked so far.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

from .hands import SCHEMA, normalize, replay

HEADER = re.compile(r"^(?P<site>PokerStars(?: Zoom)?|Poker) (?:Hand|Game) #(?P<id>[A-Za-z0-9-]+):\s*(?P<rest>.*)$")
CASH = re.compile(r"Hold'em No Limit \((?P<cur>[$€£]?)(?P<sb>[\d.,]+)/[$€£]?(?P<bb>[\d.,]+)(?: (?P<code>[A-Z]{3}))?\)")
TOURNEY = re.compile(r"Hold'em No Limit - Level [^(]*\((?P<sb>[\d.,]+)/(?P<bb>[\d.,]+)\)")
DATE = re.compile(r"(?P<date>\d{4}/\d{2}/\d{2} \d{1,2}:\d{2}:\d{2}(?: [A-Z]{2,4})?)")
TABLE = re.compile(r"^Table '(?P<table>.+?)'.*?Seat #(?P<button>\d+) is the button")
SEAT = re.compile(r"^Seat (?P<seat>\d+): (?P<name>.+?) \([$€£]?(?P<stack>[\d.,]+) in chips[^)]*\)(?P<out> is sitting out)?")
MARKER = re.compile(r"^\*\*\* (?P<name>HOLE CARDS|FLOP|TURN|RIVER|SHOW ?DOWN|SUMMARY|FIRST FLOP|FIRST TURN|FIRST RIVER) \*\*\*")
DEALT = re.compile(r"^Dealt to (?P<name>.+?) \[(?P<cards>[^\]]+)\]")
UNCALLED = re.compile(r"^Uncalled bet \((?P<amount>[$€£]?[\d.,]+)\) returned to (?P<name>.+)$")
COLLECTED = re.compile(r"^(?P<name>.+?) collected (?P<amount>[$€£]?[\d.,]+) from (?:side |main )?pot")
TOTAL = re.compile(r"^Total pot (?P<pot>[$€£]?[\d.,]+).*?\| Rake (?P<rake>[$€£]?[\d.,]+)")
SUMMARY_CARDS = re.compile(r"^Seat \d+: (?P<name>.+?) (?:\([^)]*\) )*(?:showed|mucked) \[(?P<cards>[^\]]+)\]")
BRACKETS = re.compile(r"\[([^\]]+)\]")
AMOUNT = r"[$€£]?([\d.,]+)"
VERBS = [("fold", re.compile(r"^folds\b")), ("check", re.compile(r"^checks\b")),
         ("call", re.compile(r"^calls " + AMOUNT + r"(?P<all> and is all-in)?")),
         ("bet", re.compile(r"^bets " + AMOUNT + r"(?P<all> and is all-in)?")),
         ("raise", re.compile(r"^raises " + AMOUNT + r" to " + AMOUNT + r"(?P<all> and is all-in)?")),
         ("sb", re.compile(r"^posts small blind " + AMOUNT)), ("both", re.compile(r"^posts small & big blinds " + AMOUNT)),
         ("bb", re.compile(r"^posts big blind " + AMOUNT)), ("ante", re.compile(r"^posts the ante " + AMOUNT)),
         ("straddle", re.compile(r"^posts (?:a )?straddle " + AMOUNT)), ("show", re.compile(r"^shows \[(?P<cards>[^\]]+)\]"))]
CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP"}


def split(text):
    """Split a file into hand blocks at each header line."""
    blocks, current = [], []
    for line in text.replace("﻿", "").splitlines():
        if HEADER.match(line.strip()) and current:
            blocks.append("\n".join(current))
            current = []
        if line.strip() or current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return [b for b in blocks if HEADER.match(b.strip().splitlines()[0].strip())]


def _money(text, scale):
    try:
        value = Decimal(text.replace(",", "").lstrip("$€£")) * scale
    except InvalidOperation:
        raise ValueError(f"无法解析金额：{text}") from None
    if value != value.to_integral_value():
        raise ValueError(f"金额 {text} 不是最小单位的整数倍")
    return int(value)


def parse_hand(block):
    lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
    head = HEADER.match(lines[0])
    if not head:
        raise ValueError("缺少 PokerStars 格式的手牌头")
    rest = head["rest"]
    cash, tourney = CASH.search(rest), TOURNEY.search(rest)
    if cash:
        scale = 100 if cash["cur"] or "." in cash["sb"] + cash["bb"] else 1
        currency = cash["code"] or CURRENCY.get(cash["cur"], "chips")
        blinds = cash
    elif tourney:
        scale, currency, blinds = 1, "chips", tourney
    else:
        raise ValueError("不是无限注德州手牌（只支持 Hold'em No Limit）")
    money = lambda text: _money(text, scale)
    site = "GGPoker" if head["site"] == "Poker" else "PokerStars"
    date = DATE.search(rest)
    hand = {"schema": SCHEMA, "hand_id": ("gg-" if site == "GGPoker" else "ps-") + head["id"],
            "source": {"kind": "pokerstars", "site": site, "raw_id": head["id"]},
            "game": {"variant": "NLHE", "small_blind": money(blinds["sb"]), "big_blind": money(blinds["bb"]),
                     "unit_scale": scale, "currency": currency, "tournament": bool(tourney) and not cash},
            "played_at": date["date"] if date else None, "table": None, "button_seat": None, "players": [],
            "posts": [], "actions": [], "board": [], "showdown": [], "collected": [], "rake": None, "hero": None}
    sitting_out, names, committed = set(), [], {}
    street, phase, uncalled, collected, shown = None, "setup", None, {}, {}
    for line in lines[1:]:
        marker = MARKER.match(line)
        if marker:
            name = marker["name"].replace("FIRST ", "")
            if name == "HOLE CARDS":
                street, phase = "preflop", "play"
            elif name in ("FLOP", "TURN", "RIVER"):
                if hand["board"] and name == "FLOP":
                    break  # run-it-twice boards are not modelled; keep the first runout only
                street = name.lower()
                cards = " ".join(BRACKETS.findall(line)).split()
                hand["board"] = cards
                committed = dict.fromkeys(committed, 0)
            elif name.replace(" ", "") == "SHOWDOWN":
                phase = "showdown"
            else:
                phase = "summary"
            continue
        if phase == "summary":
            total = TOTAL.match(line)
            if total:
                hand["rake"] = money(total["rake"])
            seen = SUMMARY_CARDS.match(line)
            if seen and seen["name"] in names and seen["name"] not in shown:
                shown[seen["name"]] = seen["cards"].split()
            continue
        table = TABLE.match(line)
        if table and hand["button_seat"] is None:
            hand["table"], hand["button_seat"] = table["table"], int(table["button"])
            continue
        seat = SEAT.match(line)
        if seat and phase == "setup":
            name = seat["name"]
            names.append(name)
            hand["players"].append({"seat": int(seat["seat"]), "name": name, "stack": money(seat["stack"]), "cards": None})
            committed[name] = 0
            if seat["out"]:
                sitting_out.add(name)
            continue
        dealt = DEALT.match(line)
        if dealt:
            cards = dealt["cards"].split()
            if len(cards) == 2 and dealt["name"] in names:
                hand["hero"] = dealt["name"]
                next(p for p in hand["players"] if p["name"] == dealt["name"])["cards"] = cards
            continue
        back = UNCALLED.match(line)
        if back:
            uncalled = (back["name"], money(back["amount"]))
            continue
        won = COLLECTED.match(line)
        if won and won["name"] in names:
            collected[won["name"]] = collected.get(won["name"], 0) + money(won["amount"])
            continue
        actor = next((n for n in sorted(names, key=len, reverse=True) if line.startswith(n + ": ")), None)
        if actor is None:
            continue
        verb = line[len(actor) + 2:]
        for kind, pattern in VERBS:
            m = pattern.match(verb)
            if not m:
                continue
            all_in = bool(m.groupdict().get("all"))
            if kind == "show":
                shown.setdefault(actor, m["cards"].split())
            elif kind in ("sb", "bb", "straddle", "ante", "both"):
                amount = money(m.group(1))
                if kind == "both":
                    live = hand["game"]["big_blind"]
                    hand["posts"].append({"player": actor, "kind": "post", "amount": min(live, amount)})
                    if amount > live:
                        hand["posts"].append({"player": actor, "kind": "dead", "amount": amount - live})
                    committed[actor] += min(live, amount)
                    break
                if kind == "bb" and any(p["kind"] == "bb" for p in hand["posts"]):
                    kind = "post"
                hand["posts"].append({"player": actor, "kind": kind, "amount": amount})
                if kind != "ante":
                    committed[actor] += amount
            elif street is not None:
                action = {"street": street, "player": actor, "kind": kind}
                if kind == "call":
                    action["to"] = committed[actor] + money(m.group(1))
                elif kind == "bet":
                    action["to"] = committed[actor] + money(m.group(1))
                elif kind == "raise":
                    action["to"] = money(m.group(2))
                if "to" in action:
                    committed[actor] = action["to"]
                if all_in:
                    action["all_in"] = True
                hand["actions"].append(action)
            break
    active = {p["player"] for p in hand["posts"]} | {a["player"] for a in hand["actions"]} | set(shown)
    hand["players"] = [p for p in hand["players"] if p["name"] not in sitting_out or p["name"] in active]
    present = {p["name"] for p in hand["players"]}
    # Hero's cards are already on the seat record; showdown keeps the other players' shown cards.
    hand["showdown"] = [{"player": n, "cards": c} for n, c in shown.items() if n in present and n != hand["hero"]]
    hand["collected"] = [{"player": n, "amount": a} for n, a in collected.items() if n in present]
    normalized = normalize(hand)
    return normalized, uncalled


def parse_text(text):
    """Returns ``[(hand or None, replay or None, problems)]`` for every hand block found."""
    results = []
    for block in split(text):
        try:
            hand, uncalled = parse_hand(block)
        except ValueError as exc:
            first = block.strip().splitlines()[0][:120]
            results.append((None, None, [f"{first}：{exc}"]))
            continue
        r = replay(hand)
        problems = list(r.errors)
        if uncalled and r.complete and tuple(uncalled) != tuple(r.returned or ()):
            problems.append(f"未跟注退回与重放不一致：记录 {uncalled}，重放 {r.returned}")
        results.append((hand, r, problems))
    return results
