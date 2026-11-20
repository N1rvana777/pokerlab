"""Put review questions to the real assistant, one fresh session each, and keep every record.

    python -X utf8 scripts/coach_eval.py <cases.json> --output outputs/coach-runs/<name>

cases.json is a list of {"id": ..., "question": ...}. Each case gets its own copy of outputs/coach with every hand
without errors confirmed, the state after the user has checked them in the panel, so the assistant's notes stay in
the copy. The real store is hashed before and after. A case that already has a run.json is skipped, so the command
can be run again after a failure. Uses the caller's Claude Code login: run it from a plain terminal, because a Claude
Code session's environment trips the credential check.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pokerlab.coach.store import CoachStore  # noqa: E402

STORE = ROOT / "outputs/coach"


def fingerprint(folder):
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(folder)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def prepare(folder):
    copy = folder / "coach"
    shutil.copytree(STORE, copy)
    store = CoachStore(copy)
    for row in store.list_hands(limit=10000):
        if not row["errors"]:
            store.confirm(row["hand_id"], row["latest_revision"], by="eval")
    return copy


def values(item):
    if isinstance(item, dict):
        for value in item.values():
            yield from values(value)
    elif isinstance(item, list):
        for value in item:
            yield from values(value)
    else:
        yield item


def known_numbers(results, question):
    """Every number the tools returned or the question held, at the roundings an answer would use, also as a percent."""
    known = set()
    found = [float(v) for v in values(results) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    found += [float(m) for v in values(results) if isinstance(v, str) for m in re.findall(r"\d+(?:\.\d+)?", v)]
    found += [float(m) for m in re.findall(r"\d+(?:\.\d+)?", question)]
    for number in found:
        for digits in (0, 1, 2, 3):
            known.update((round(abs(number), digits), round(abs(number) * 100, digits)))
    return known


def trace(run, question):
    """What the answer cites that the tools did not return. Numbers listed here need a look, they are not all wrong: pot odds are worked out by hand."""
    results = [e.get("result") for e in run["events"] if e["type"] == "tool_result"]
    text = json.dumps(results, ensure_ascii=False)
    answer = run["answer"] or ""
    prose = re.sub(r"`[^`]*`", " ", re.sub(r"https?://\S+", " ", answer))
    known = known_numbers(results, question)
    numbers = set()
    for token in re.findall(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?", prose):
        value = float(token.strip("$%").replace(",", ""))
        if (value >= 10 or "." in token) and value not in known:
            numbers.add(token)
    links = re.findall(r"watch\?v=([\w-]+)&t=\d+", answer)
    ids = set(re.findall(r"`([a-z0-9][a-z0-9-]{5,})`", answer)) | set(re.findall(r"hhp-[\w-]+", answer))
    return {"unmatched_numbers": sorted(numbers), "links": len(links), "unknown_links": sorted({v for v in links if v not in text}),
            "ids": len(ids), "unknown_ids": sorted(i for i in ids if i not in text)}


def audit(run, question):
    """What can be read off the record without judging the answer."""
    events = run["events"]
    calls = [e for e in events if e["type"] == "tool_call"]
    results = [e for e in events if e["type"] == "tool_result"]
    isolation = next((e for e in events if e["type"] == "tool_isolation"), {})
    usage = next((e["usage"] for e in events if e["type"] == "usage"), {})
    return {"status": run["status"], "error": run["error"], "seconds": run["seconds"], "model": run["model"],
            "api_key_source": isolation.get("api_key_source"),
            "only_pokerlab_tools": bool(isolation.get("tools")) and all(t.startswith("mcp__pokerlab__") for t in isolation["tools"]),
            "tool_calls": [e["name"] for e in calls], "tool_errors": [e["name"] for e in results if e.get("error") or e.get("is_error")],
            "output_tokens": usage.get("output_tokens"), "answer_chars": len(run["answer"] or ""), **trace(run, question)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--only", default=None, help="comma separated case ids")
    parser.add_argument("--timeout", type=float, default=1500)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    wanted = set(args.only.split(",")) if args.only else None
    args.output.mkdir(parents=True, exist_ok=True)
    before = fingerprint(STORE)
    rows = []
    for case in cases:
        if wanted and case["id"] not in wanted:
            continue
        folder = args.output / case["id"]
        record = folder / "run" / "run.json"
        if not record.is_file():
            if folder.exists():
                raise SystemExit(f"{folder} exists without a finished run; move it aside first")
            folder.mkdir()
            (folder / "question.txt").write_text(case["question"], encoding="utf-8")
            copy = prepare(folder)
            subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/coach_ask.py"), "--message-file", str(folder / "question.txt"),
                            "--coach-dir", str(copy), "--timeout", str(args.timeout), "--output", str(folder / "run")], check=False)
        row = {"id": case["id"], **(audit(json.loads(record.read_text(encoding="utf-8")), case["question"]) if record.is_file() else {"status": "no record"})}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    after = fingerprint(STORE)
    summary = args.output / "audit.jsonl"
    with summary.open("a", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"store_unchanged": before == after, "cases": len(rows)}, ensure_ascii=False), flush=True)
    return 0 if before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
