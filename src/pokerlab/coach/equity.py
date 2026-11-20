"""Hold'em all-in equity of a hand against a weighted range, from any street (seeded, reproducible).

Preflop runs Monte Carlo; from the flop on every runout is enumerated, so the result is exact. Uses the project's
5-card evaluator (``pokerlab.plo.evaluator.rank5_batch``, higher key is better) on all 21 five-card subsets of each
seven-card holding.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np

from pokerlab.plo.cards import parse_card
from pokerlab.plo.evaluator import rank5_batch

SUBSETS = np.array(list(combinations(range(7), 5)), dtype=np.int64)
RANKS = "23456789TJQKA"
SUITS = "cdhs"


def best7(cards):
    """(N, 7) card ids -> (N,) best five-card rank key."""
    keys = rank5_batch(cards[:, SUBSETS].reshape(-1, 5)).reshape(len(cards), len(SUBSETS))
    return keys.max(axis=1)


def expand(token):
    """'AKo' / 'AKs' / 'AK' / 'QQ' / 'AsKd' -> list of (card, card) id pairs."""
    if len(token) == 4:
        return [(parse_card(token[:2]), parse_card(token[2:]))]
    high, low = token[0], token[1]
    kind = token[2:] or ""
    pairs = []
    for a in range(4):
        for b in range(4):
            if high == low and b <= a:
                continue
            if kind == "s" and a != b or kind == "o" and a == b:
                continue
            pairs.append((RANKS.index(high) * 4 + a, RANKS.index(low) * 4 + b))
    return pairs


def _span(body):
    """One range entry without its weight -> hand classes or exact combos: QQ+, TT-77, ATs+, A5s-A2s, AKo, AK, AhKh."""
    if len(body) == 4 and body[1] in SUITS and body[3] in SUITS:
        return [body]
    if body.endswith("+"):
        name = body[:-1]
        high, low, kind = name[0], name[1], name[2:]
        if high == low:
            return [r + r for r in RANKS[RANKS.index(high):]]
        return [high + r + kind for r in RANKS[RANKS.index(low):RANKS.index(high)]]
    if "-" in body:
        top, bottom = body.split("-")
        if top[0] == top[1]:
            return [r + r for r in RANKS[RANKS.index(bottom[0]):RANKS.index(top[0]) + 1]]
        return [top[0] + r + top[2:] for r in RANKS[RANKS.index(bottom[1]):RANKS.index(top[1]) + 1]]
    return [body]


def parse_range(text):
    """Range text as the Solver takes it, 'QQ+,AKs,ATs+,99-77,AQo:0.5,AhKh' -> [(token, weight), ...]."""
    out = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        body, _, weight = part.partition(":")
        out += [(name, float(weight or 1)) for name in _span(body.strip())]
    for name, _ in out:
        if not expand(name) or any(not 0 <= card < 52 for pair in expand(name) for card in pair):
            raise ValueError(f"范围条目无效：{name}")
    return out


def equity(hero, villain_tokens, boards=100_000, seed=20261029, board=()):
    """Return overall equity, standard error and per-token breakdown; blocked combos are dropped.

    A token is a hand class or combo, or (token, weight). With three or more board cards every runout is enumerated.
    """
    hero_ids = [parse_card(c) for c in hero]
    known = [parse_card(c) for c in board]
    if len(set(hero_ids + known)) != len(hero_ids) + len(known):
        raise ValueError("底牌和公共牌有重复")
    rng = np.random.default_rng(seed)
    rows, total_weight, total, variance = [], 0.0, 0.0, 0.0
    for item in villain_tokens:
        token, weight = (item, 1.0) if isinstance(item, str) else item
        combos = [c for c in expand(token) if not set(c) & set(hero_ids + known)]
        if not combos or weight <= 0:
            continue
        wins = []
        for combo in combos:
            deck = np.array([c for c in range(52) if c not in hero_ids + known and c not in combo])
            if known:
                drawn = np.array([known + list(run) for run in combinations(deck, 5 - len(known))], dtype=np.int64)
            else:
                drawn = deck[np.argsort(rng.random((boards, len(deck))), axis=1)[:, :5]]
            count = len(drawn)
            h = best7(np.hstack([np.tile(hero_ids, (count, 1)), drawn]))
            v = best7(np.hstack([np.tile(combo, (count, 1)), drawn]))
            score = (h > v) + 0.5 * (h == v)
            wins.append(score.mean())
            if not known:
                variance += (weight ** 2) * score.var() / count
        value = float(np.mean(wins))
        rows.append({"villain": token, "weight": weight, "combos": len(combos), "equity": value})
        total += value * len(combos) * weight
        total_weight += len(combos) * weight
    if not total_weight:
        raise ValueError("范围里的牌全部和底牌或公共牌冲突")
    return {"hero": hero, "board": list(board), "equity": total / total_weight, "combos": total_weight,
            "std_error": float(np.sqrt(variance) / total_weight), "method": "enumerated" if known else "monte_carlo",
            "boards_per_combo": None if known else boards, "seed": seed, "by_hand": rows}
