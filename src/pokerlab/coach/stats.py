"""Beta-binomial opponent statistics, tendency scores, tags and a coarse player type.

Tendency score: ``round(10 * P(player's rate > population rate))`` under the
posterior. 5 means no evidence either way; 9 means a 90% posterior
probability that the player is above the population mean. With few
observations the posterior stays near the prior, so the score stays near 5.
"""
from __future__ import annotations

import json
from pathlib import Path

from scipy.stats import beta as beta_dist

from .evidence import DEFINITIONS

PRIORS_FILE = Path(__file__).with_name("priors_v0.json")
TAG_MIN_HANDS = 3          # different hands behind a tag: decisions inside one hand are not independent
TAG_PROBABILITY = 0.85     # posterior probability needed for a tag
TYPE_MIN_N = 15            # preflop observations before a player type is named


def load_priors(path=None):
    data = json.loads(Path(path or PRIORS_FILE).read_text(encoding="utf-8"))
    missing = set(DEFINITIONS) - set(data["stats"])
    if missing:
        raise ValueError("先验缺少统计项：" + ", ".join(sorted(missing)))
    for stat in DEFINITIONS:
        if not 0 < data["stats"][stat]["mean"] < 1:
            raise ValueError(f"{stat} 的先验均值必须在 0 和 1 之间")
    if not data.get("strength", 0) > 0:
        raise ValueError("先验强度必须为正")
    return data


def posterior(k, n, mean, strength):
    a = mean * strength + k
    b = (1 - mean) * strength + (n - k)
    low, high = beta_dist.ppf([0.05, 0.95], a, b)
    above = float(beta_dist.sf(mean, a, b))
    return {"n": n, "k": k, "raw": k / n if n else None, "mean": a / (a + b), "ci90": [float(low), float(high)],
            "population": mean, "p_above_population": above, "score": round(10 * above) if n else 5}


def _ids(items, limit=12):
    seen = []
    for item in items:
        if item.hand_id not in seen:
            seen.append(item.hand_id)
    return seen[-limit:]


def profile(observations, priors):
    grouped = {}
    for o in observations:
        grouped.setdefault(o.stat, []).append(o)
    result = {}
    for stat, (label, opportunity, success) in DEFINITIONS.items():
        items = grouped.get(stat, [])
        post = posterior(sum(o.success for o in items), len(items), priors["stats"][stat]["mean"], priors["strength"])
        post.update(label=label, opportunity=opportunity, success=success, inferred=sum(o.inferred for o in items),
                    hands=len({o.hand_id for o in items}), selected_hands=len({o.hand_id for o in items if o.selected}),
                    hands_success=_ids(o for o in items if o.success),
                    hands_failure=_ids(o for o in items if not o.success))
        result[stat] = post
    return result


def tags(prof, priors):
    out = []
    for stat, post in prof.items():
        spec = priors["stats"][stat]
        if post["hands"] < TAG_MIN_HANDS:
            continue
        p = post["p_above_population"]
        common = {"stat": stat, "n": post["n"], "k": post["k"], "hands": post["hands"], "selected_hands": post["selected_hands"]}
        if p >= TAG_PROBABILITY and spec.get("high"):
            out.append({**common, "label": spec["high"], "direction": "high", "probability": p,
                        "score": round(10 * p), "evidence": post["hands_success"]})
        elif p <= 1 - TAG_PROBABILITY and spec.get("low"):
            out.append({**common, "label": spec["low"], "direction": "low", "probability": 1 - p,
                        "score": round(10 * (1 - p)), "evidence": post["hands_failure"]})
    return sorted(out, key=lambda t: (-t["probability"], -t["n"]))


def player_type(prof):
    v, p, a = prof["vpip"], prof["pfr"], prof["aggression"]
    if v["n"] < TYPE_MIN_N:
        return {"type": "未定", "reason": f"翻前样本 {v['n']} 手，少于 {TYPE_MIN_N} 手"}
    pv, pp, pa = v["p_above_population"], p["p_above_population"], a["p_above_population"]
    loose, tight = pv >= 0.8, pv <= 0.2
    aggressive, passive = pp >= 0.8 or pa >= 0.8, pp <= 0.2 and pa <= 0.5
    if loose and passive:
        kind = "松弱（跟注站倾向）"
    elif loose and aggressive:
        kind = "松凶"
    elif tight and aggressive:
        kind = "紧凶"
    elif tight and passive:
        kind = "紧弱（nit 倾向）"
    elif loose or tight:
        kind = "偏松" if loose else "偏紧"
    else:
        kind = "接近人群平均"
    return {"type": kind, "basis": {"vpip_p_above": pv, "pfr_p_above": pp, "aggression_p_above": pa, "vpip_n": v["n"]}}
