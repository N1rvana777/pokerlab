"""Turn captured preflop lines into a range library for the workbench.

Input is JSON {name: {"actions", "pot", "first", "oop", "ip"}}. Names are
srp_<opener>_<caller> or 3bet_<opener>_<three-bettor>; "first" is "<seat> <stack>" of the
player who acts first on the flop. The library stays under outputs/ and never goes into Git.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SCHEMA = "pokerlab-preflop-v1"
SEATS = ("UTG", "LJ", "HJ", "CO", "BTN", "SB", "BB", "STR")
GROUPS = {"srp": "单加注底池", "3bet": "3bet 底池"}
RARE_COMBOS = 2.0  # A line with fewer combos on one side almost never happens at this equilibrium.


def class_combos(name: str) -> int:
    return 6 if len(name) == 2 else 4 if name.endswith("s") else 12


def range_combos(text: str) -> float:
    total = 0.0
    for part in filter(None, (p.strip() for p in text.split(","))):
        name, _, weight = part.partition(":")
        total += class_combos(name) * float(weight or 1)
    return total


def parse_name(name: str) -> tuple[str, str, str]:
    found = re.fullmatch(r"(srp|3bet)_([A-Z]+)_([A-Z]+)", name)
    if not found or found[2] not in SEATS or found[3] not in SEATS or found[2] == found[3]:
        raise ValueError(f"unknown line name: {name}")
    return found[1], found[2], found[3]


def describe(kind: str, opener: str, other: str, actions: str) -> str:
    raises = re.findall(r"R([\d.]+)", actions)
    if kind == "srp" and len(raises) == 1:
        return f"{opener} 开池 {raises[0]}bb · {other} 跟注"
    if kind == "3bet" and len(raises) == 2:
        return f"{opener} 开池 {raises[0]}bb · {other} 3bet {raises[1]}bb"
    raise ValueError(f"{kind} line does not match its actions: {actions}")


def build_line(name: str, line: dict) -> dict:
    kind, opener, other = parse_name(name)
    if not line["oop"] or not line["ip"]:
        raise ValueError(f"{name}: a capture came back empty")
    seat, stack = line["first"].split()
    if seat not in (opener, other):
        raise ValueError(f"{name}: {seat} is not in this pot")
    oop_combos, ip_combos = range_combos(line["oop"]), range_combos(line["ip"])
    label = describe(kind, opener, other, line["actions"])
    rare = min(oop_combos, ip_combos) < RARE_COMBOS
    return {"id": name, "group": GROUPS[kind], "label": label + ("（几乎不出现）" if rare else ""),
            "oop_seat": seat, "ip_seat": other if seat == opener else opener, "actions": line["actions"],
            "pot": float(line["pot"]), "stack": float(stack), "oop": line["oop"], "ip": line["ip"],
            "oop_combos": round(oop_combos, 1), "ip_combos": round(ip_combos, 1), "rare": rare}


def order(line: dict) -> tuple[int, int, int]:
    kind, opener, other = parse_name(line["id"])
    return list(GROUPS).index(kind), SEATS.index(opener), SEATS.index(other)


def build(raw: dict, meta: dict) -> dict:
    lines = sorted((build_line(name, line) for name, line in raw.items()), key=order)
    return {"schema": SCHEMA, **meta, "lines": lines}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    for field in ("id", "title", "source", "note"):
        parser.add_argument("--" + field, required=True)
    args = parser.parse_args()
    meta = {field: getattr(args, field) for field in ("id", "title", "source", "note")}
    library = build(json.loads(args.input.read_text(encoding="utf-8")), meta)
    with args.output.open("x", encoding="utf-8") as handle:  # Outputs are never overwritten.
        json.dump(library, handle, ensure_ascii=False, indent=1)
    print(args.output, len(library["lines"]), "lines")


if __name__ == "__main__":
    main()
