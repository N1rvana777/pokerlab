"""Local knowledge base of Hungry Horse Poker videos (the user's private use): caption chunks, BM25 search
and hand records rebuilt from video frames.

Captions are YouTube auto-captions (``captions/<video_id>.en.json3``) under
``POKERLAB_KNOWLEDGE_HOME`` or ``outputs/knowledge/hhp``; titles come from
``channel_videos_utf8.tsv``. Auto-captions mishear card names and amounts, so
caption results are a lead to the video moment, not a verified hand record.
Hand records (``hands/<video_id>.json``, built per ``READING_METHOD.md``) combine the screen and the
captions and are replayed here; each is placed in video time by the ``m:ss–m:ss`` ranges in its text,
or by ``hand_times.json`` for records whose text has none. ``find`` looks them up by situation.
``methods/methods.json`` holds the principles drawn from those videos and public articles: what to look for, what to
change, why and how far. It is the layer an answer starts from; hands and captions are its evidence.
"""
from __future__ import annotations

from collections import Counter
import json
import math
import os
from pathlib import Path
import re

from . import situation
from .hands import STREET_CN, STREETS, normalize, replay

ROOT = Path(__file__).resolve().parents[3]
CHUNK_SECONDS = 60
MAX_HANDS = 4  # hand records returned by one read
PER_VIDEO = 3  # hand records per video in one find, so several videos stay in view
REASON_CHARS = 500  # narrator's reasoning quoted per found hand
METHOD_EVIDENCE = 4  # sources returned with one principle
METHOD_TEXT = ("title", "read", "adjustment", "why", "how_far", "limits", "thinking")
TIME_RANGE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})\s*[–—~-]\s*(?:(\d+):)?(\d{1,2}):(\d{2})")
HANDS_NOTE = ("视频里的手牌多是教学用的假设场景，也有讲解人分析的真实牌局（直播、讲解人自己的牌局）。notes 开头的"
              "“教学场景 / 真实牌局 / 来源未说明”写明是哪一种，没有这个开头的是教学场景。记录由画面（牌、金额）和字幕（行动、道理）整理，"
              "并通过了重放校验；具体数字以记录为准，字幕里的数字可能听错。street_end_pots 含未被跟注的部分，final_pot 是退回之后的底池。"
              "notes 里的 label (example hand) 是讲解人举例的手牌，不是底牌。部分记录里 missing 为空的是幻灯片或范围讲解，不是打完的一手。"
              "这些手牌都不是用户对手的证据，不能记入对手库。")
STOP = set("""a an the and or but if then so to of in on at for with from by as is are was were be been being it its this that these
those i you he she we they me him her us them my your his our their do does did doing have has had having not no yes just
like really very can could would should will shall may might must there here what which who whom when where why how all any
some more most other such only own same than too s t don now gonna wanna yeah okay oh um uh going get got right know think""".split())
PHRASES = [(r"\bthree[\s-]?bet", "3bet"), (r"\bfour[\s-]?bet", "4bet"), (r"\b(\d)[\s-]bet", r"\1bet"),
           (r"\bc[\s-]bet", "cbet"), (r"\bcontinuation bet", "cbet"), (r"\bcheck[\s-]raise", "checkraise"),
           (r"\blimp[\s-]re[\s-]?raise", "limpraise"), (r"\blimp[\s-]raise", "limpraise"), (r"\bmulti[\s-]?way", "multiway"),
           (r"\bover[\s-]?bet", "overbet"), (r"\ball[\s-]in", "allin"), (r"\bhero[\s-]call", "herocall")]


def home():
    return Path(os.environ.get("POKERLAB_KNOWLEDGE_HOME") or ROOT / "outputs/knowledge/hhp")


def tokens(text):
    text = text.lower()
    for pattern, replacement in PHRASES:
        text = re.sub(pattern, replacement, text)
    return [w for w in re.findall(r"[a-z0-9']+", text) if w not in STOP and len(w) > 1]


def method_terms(text):
    """Latin words plus overlapping Chinese character pairs, because the principles are written in Chinese."""
    pairs = [a + b for run in re.findall("[一-鿿]+", text) for a, b in zip(run, run[1:])]
    return tokens(text) + pairs


def seconds_of(text):
    """Seconds of an m:ss or h:mm:ss stamp, or None."""
    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})", str(text or "").strip())
    return int(match[1] or 0) * 3600 + int(match[2]) * 60 + int(match[3]) if match else None


def stamp(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else f"{seconds // 60}:{seconds % 60:02d}"


def spans(*texts):
    """(start, end) seconds of every m:ss–m:ss (or h:mm:ss) range in the texts, in order, without repeats."""
    out = []
    for text in texts:
        for m in TIME_RANGE.finditer(text or ""):
            start = int(m[1] or 0) * 3600 + int(m[2]) * 60 + int(m[3])
            end = int(m[4] or 0) * 3600 + int(m[5]) * 60 + int(m[6])
            if start < end and (start, end) not in out:
                out.append((start, end))
    return out


def segments(path):
    """(start_seconds, text) for every caption event with words."""
    out = []
    for event in json.loads(Path(path).read_text(encoding="utf-8")).get("events", []):
        text = "".join(s.get("utf8", "") for s in event.get("segs") or []).replace("\n", " ").strip()
        if text:
            out.append((event.get("tStartMs", 0) / 1000, text))
    return out


class Knowledge:
    def __init__(self, root=None):
        self.root = Path(root or home())
        self.titles = {}
        catalog = self.root / "channel_videos_utf8.tsv"
        if catalog.is_file():
            for line in catalog.read_bytes().decode("utf-8", errors="replace").splitlines():
                parts = line.split("\t")
                if len(parts) >= 4:
                    self.titles[parts[0]] = parts[3].replace("�", "'")
        self.chunks, self.segments = [], {}
        for path in sorted((self.root / "captions").glob("*.en.json3")):
            vid = path.name.split(".")[0]
            segs = segments(path)
            self.segments[vid] = segs
            current, start = [], None
            for t, text in segs:
                if start is None:
                    start = t
                if t - start >= CHUNK_SECONDS and current:
                    self.chunks.append({"video_id": vid, "start": start, "end": t, "text": " ".join(current)})
                    current, start = [], t
                current.append(text)
            if current:
                self.chunks.append({"video_id": vid, "start": start, "end": segs[-1][0] + 10, "text": " ".join(current)})
        self.docs = [Counter(tokens(c["text"])) for c in self.chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lengths) / len(self.lengths) if self.lengths else 0
        df = Counter(term for d in self.docs for term in d)
        n = len(self.docs)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}
        self._load_hands()
        self._load_methods()

    def _load_methods(self):
        self.methods, self.method_docs = [], []
        path = self.root / "methods" / "methods.json"
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            self.hand_problems.append(f"methods.json：{exc}")
            return
        for entry in data if isinstance(data, list) else []:
            if not isinstance(entry, dict) or not entry.get("id") or not entry.get("title"):
                self.hand_problems.append("methods.json：有条目缺少 id 或 title，已跳过")
                continue
            self.methods.append(entry)
            text = [str(entry.get(key) or "") for key in METHOD_TEXT] + [entry["title"], " ".join(entry.get("tags") or [])]
            self.method_docs.append(Counter(method_terms(" ".join(text))))

    def _method_view(self, entry, every_source=False):
        sources = []
        for item in entry.get("evidence") or []:
            at = seconds_of(item.get("time"))
            if item.get("video") and at is not None:
                sources.append({**self._cite(item["video"], at), "hand": item.get("hand"), "note": item.get("note")})
            elif item.get("url"):
                sources.append({"title": item.get("title"), "url": item["url"], "note": item.get("note")})
        return {**{key: entry.get(key) for key in ("id", *METHOD_TEXT, "tags", "solver", "origin")},
                "evidence_count": len(sources), "evidence": sources if every_source else sources[:METHOD_EVIDENCE]}

    def find_methods(self, query, tags=None, limit=5):
        """Principles ranked by BM25 over their text; tags keep only entries carrying one of them."""
        terms = method_terms(query)
        wanted = set(tags or [])
        count = len(self.methods) or 1
        length = sum(sum(d.values()) for d in self.method_docs) / count or 1
        known = Counter(term for doc in self.method_docs for term in doc)
        scored = []
        for entry, doc in zip(self.methods, self.method_docs):
            if wanted and not wanted & set(entry.get("tags") or []):
                continue
            score = 0.0
            for term in set(terms):
                if doc[term]:
                    idf = math.log(1 + (count - known[term] + 0.5) / (known[term] + 0.5))
                    score += idf * doc[term] * 2.5 / (doc[term] + 1.5 * (0.25 + 0.75 * sum(doc.values()) / length))
            if score > 0 or (wanted and not terms):
                scored.append((score, entry))
        scored.sort(key=lambda row: -row[0])
        return {"results": [self._method_view(entry) for _, entry in scored[:limit]], "matched_total": len(scored), "methods": len(self.methods)}

    def read_method(self, method_id):
        entry = next((e for e in self.methods if e["id"] == method_id), None)
        if entry is None:
            raise ValueError(f"没有这条方法论：{method_id}")
        return self._method_view(entry, every_source=True)

    def _load_hands(self):
        """Hand records from hands/*.json; files named in another file's "supersedes" are older drafts."""
        self.hands, self.hand_problems = [], []
        folder, loaded = self.root / "hands", {}
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                loaded[path.name] = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as exc:
                self.hand_problems.append(f"{path.name}：{exc}")
        superseded = {name for data in loaded.values() if isinstance(data, dict) for name in data.get("supersedes") or []}
        times = self._hand_times()
        seen = set()
        for name, data in loaded.items():
            if name in superseded:
                continue
            if not (isinstance(data, dict) and data.get("video_id") and isinstance(data.get("hands"), list)):
                self.hand_problems.append(f"{name}：不是 {{video_id, hands, partial}} 格式，已跳过")
                continue
            vid = data["video_id"]
            for raw in data["hands"]:
                try:
                    hand = normalize(raw)
                except ValueError as exc:
                    self.hand_problems.append(f"{name}：{exc}")
                    continue
                if hand["hand_id"] in seen:
                    self.hand_problems.append(f"{name}：{hand['hand_id']} 重复，已跳过")
                    continue
                seen.add(hand["hand_id"])
                record = replay(hand)
                self.hands.append({"video_id": vid, "id": hand["hand_id"], "hand": hand, "replay": record,
                                   "situation": situation.features(hand, record), "text": (hand["notes"] or "").lower(),
                                   "spans": spans(times.get(hand["hand_id"]), hand["source"]["raw_id"], hand["notes"])})
            for raw in data.get("partial") or []:
                if not isinstance(raw, dict) or not isinstance(raw.get("label"), str):
                    self.hand_problems.append(f"{name}：partial 记录缺少 label，已跳过")
                    continue
                known = raw.get("known") if isinstance(raw.get("known"), dict) else {}
                self.hands.append({"video_id": vid, "id": "部分记录：" + raw["label"], "partial": raw,
                                   "text": json.dumps(raw, ensure_ascii=False).lower(),
                                   "spans": spans(times.get(raw["label"]), raw["label"], str(known.get("time") or ""))})
        for entry in self.hands:
            if not entry["spans"]:
                self.hand_problems.append(f"{entry['id']} 没有视频时间范围，read_hhp 不会返回它")

    def _hand_times(self):
        """hand_times.json: {"times": {hand_id or partial label: "m:ss–m:ss"}} for records whose text has no range."""
        path = self.root / "hand_times.json"
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            self.hand_problems.append(f"hand_times.json：{exc}")
            return {}
        return {key: value for key, value in (data.get("times") or {}).items() if isinstance(value, str)}

    def hands_at(self, video_id, start, end):
        """Hand records of a video whose time ranges overlap [start, end), earliest first."""
        hits = [e for e in self.hands if e["video_id"] == video_id and any(a < end and start < b for a, b in e["spans"])]
        return sorted(hits, key=lambda e: e["spans"][0])

    def _hand_view(self, entry):
        time = [f"{stamp(a)}–{stamp(b)}" for a, b in entry["spans"]]
        if "partial" in entry:
            raw = entry["partial"]
            return {"record": entry["id"], "complete": False, "time": time, "known": raw.get("known"), "missing": raw.get("missing")}
        hand, r = entry["hand"], entry["replay"]
        scale = hand["game"]["unit_scale"]
        value = (lambda v: v / scale) if scale != 1 else (lambda v: v)
        fmt = (lambda v: f"{v / scale:g}") if scale != 1 else str
        verbs = {"fold": lambda d: "弃牌", "check": lambda d: "过牌", "call": lambda d: f"跟注 {fmt(d.to)}",
                 "bet": lambda d: f"下注 {fmt(d.to)}", "raise": lambda d: f"加注到 {fmt(d.to)}"}
        lines, pots, total = [], {}, sum(p["amount"] for p in hand["posts"])
        for street in STREETS:
            acts = [d for d in r.decisions if d.street == street]
            if acts:
                lines.append(STREET_CN[street] + "：" + "，".join(
                    f"{d.player} {verbs[d.kind](d)}" + ("（全下）" if d.all_in else "") + ("（推定）" if d.inferred else "")
                    for d in acts))
            total += sum(d.added for d in acts)
            pots[STREET_CN[street]] = value(total)
            if street == r.last_street:
                break
        game = hand["game"]
        view = {"record": hand["hand_id"], "complete": True, "time": time,
                "url": f"https://www.youtube.com/watch?v={entry['video_id']}&t={entry['spans'][0][0]}s",
                "stakes": "/".join(fmt(v) for v in (game["small_blind"], game["middle_blind"], game["big_blind"]) if v is not None),
                "posts": "，".join(f"{p['player']} {p['kind']} {fmt(p['amount'])}" for p in hand["posts"]),
                "hero": hand["hero"],
                "players": [{"name": p["name"], "position": r.positions.get(p["name"]),
                             "stack": None if p["stack"] is None else value(p["stack"]), "cards": p["cards"]} for p in hand["players"]],
                "board": hand["board"], "actions": "；".join(lines), "street_end_pots": pots, "final_pot": value(r.pot),
                "returned": [r.returned[0], value(r.returned[1])] if r.returned else None,
                "showdown": hand["showdown"], "notes": hand["notes"]}
        if r.errors or r.warnings:
            view["replay"] = {"errors": list(r.errors), "warnings": list(r.warnings)}
        return view

    def stats(self):
        words = sum(len(t.split()) for segs in self.segments.values() for _, t in segs)
        out = {"videos": len(self.segments), "chunks": len(self.chunks), "words": words, "root": str(self.root),
               "hand_records": sum("hand" in e for e in self.hands), "partial_records": sum("partial" in e for e in self.hands),
               "methods": len(self.methods)}
        if self.hand_problems:
            out["hand_problems"] = list(self.hand_problems)
        return out

    def _cite(self, vid, start):
        return {"video_id": vid, "title": self.titles.get(vid, vid), "start": stamp(start),
                "url": f"https://www.youtube.com/watch?v={vid}&t={int(start)}s"}

    def _found_view(self, entry, matched, missed):
        start = entry["spans"][0][0] if entry["spans"] else 0
        view = {"record": entry["id"], "matched": matched, "missed": missed, **self._cite(entry["video_id"], start),
                "time": [f"{stamp(a)}–{stamp(b)}" for a, b in entry["spans"]]}
        if "partial" in entry:
            return {**view, "complete": False, "known": entry["partial"].get("known"), "missing": entry["partial"].get("missing")}
        full, f = self._hand_view(entry), entry["situation"] or {}
        notes = full["notes"] or ""
        at = notes.rfind("讲解人思路")
        view.update({key: full[key] for key in ("stakes", "board", "actions", "final_pot", "showdown")})
        view.update(complete=True, hero_position=f.get("position"), hero_cards=f.get("cards"), depth_bb=f.get("depth_bb"),
                    pot_type=sorted(f.get("pot", ())), players_to_flop=f.get("players_to_flop"), in_position=f.get("in_position"),
                    reasoning=notes[max(at, 0):][:REASON_CHARS])
        return view

    def find(self, criteria, limit=6):
        """Hand records by situation, best first; every record lists the criteria it meets and misses."""
        tests = situation.checks(criteria)
        terms = (criteria.get("text") or "").lower().split()
        if not tests and not terms:
            raise ValueError("至少给一个条件")
        scored = []
        for entry in self.hands:
            if criteria.get("video_id") and entry["video_id"] != criteria["video_id"]:
                continue
            f, matched, missed, score = entry.get("situation"), [], [], 0
            for label, kind, test in tests:
                hit = f is not None and test(f)
                (matched if hit else missed).append(label)
                score += situation.WEIGHTS[kind] if hit else 0
            for term in terms:
                hit = term in entry["text"]
                (matched if hit else missed).append("text:" + term)
                score += situation.WEIGHTS["text"] if hit else 0
            if score:
                scored.append((-score, len(missed), len(scored), entry, matched, missed))
        exact = Counter(item[3]["video_id"] for item in scored if not item[5])
        scored.sort(key=lambda item: (item[0], item[1], -exact[item[3]["video_id"]], item[2]))  # ties: the video with most such hands
        results, per_video = [], Counter()
        for _, _, _, entry, matched, missed in scored:
            if per_video[entry["video_id"]] >= PER_VIDEO:
                continue
            per_video[entry["video_id"]] += 1
            results.append(self._found_view(entry, matched, missed))
            if len(results) >= limit:
                break
        return {"exact_total": sum(exact.values()), "exact_by_video": dict(exact.most_common(10)), "results": results}

    def search(self, query, limit=5, k1=1.5, b=0.75):
        terms = tokens(query)
        if not terms or not self.docs:
            return []
        scored = []
        for i, doc in enumerate(self.docs):
            score = 0.0
            for term in terms:
                f = doc.get(term)
                if f:
                    score += self.idf[term] * f * (k1 + 1) / (f + k1 * (1 - b + b * self.lengths[i] / self.avg))
            if score:
                scored.append((score, i))
        scored.sort(reverse=True)
        results, per_video = [], Counter()
        for score, i in scored:
            chunk = self.chunks[i]
            if per_video[chunk["video_id"]] >= 2:  # keep several videos in view
                continue
            per_video[chunk["video_id"]] += 1
            doc = self.docs[i]
            # Matched and missing query terms let the reader see a weak hit (e.g. only "pot" for "bomb pot").
            results.append({**self._cite(chunk["video_id"], chunk["start"]), "score": round(score, 2),
                            "matched": sorted({t for t in terms if t in doc}), "missing": sorted({t for t in terms if t not in doc}),
                            "text": chunk["text"],
                            "hands": [e["id"] for e in self.hands_at(chunk["video_id"], chunk["start"], chunk["end"])]})
            if len(results) >= limit:
                break
        return results

    def read(self, video_id, start_seconds, seconds=120):
        segs = self.segments.get(video_id)
        if segs is None:
            raise ValueError("知识库里没有这个视频：" + str(video_id))
        seconds = max(10, min(int(seconds), 600))
        text = " ".join(t for s, t in segs if start_seconds <= s < start_seconds + seconds)
        out = {**self._cite(video_id, start_seconds), "seconds": seconds, "text": text or "(这段时间没有字幕)"}
        found = self.hands_at(video_id, start_seconds, start_seconds + seconds)
        if found:
            out["hands"] = [self._hand_view(e) for e in found[:MAX_HANDS]]
            if found[MAX_HANDS:]:
                out["more_hands"] = [e["id"] for e in found[MAX_HANDS:]]
            out["hands_note"] = HANDS_NOTE
        return out


_DEFAULT = {}


def default():
    """Shared instance per knowledge folder; rebuilt when the caption set or the hand files change."""
    root = home()
    signature = tuple(sorted(p.name for p in (root / "captions").glob("*.en.json3"))) if (root / "captions").is_dir() else ()
    hand_files = [*((root / "hands").glob("*.json") if (root / "hands").is_dir() else []), root / "hand_times.json", root / "methods" / "methods.json"]
    signature += tuple(sorted((p.name, p.stat().st_mtime_ns) for p in hand_files if p.is_file()))
    cached = _DEFAULT.get(str(root))
    if cached is None or cached[0] != signature:
        _DEFAULT[str(root)] = (signature, Knowledge(root))
    return _DEFAULT[str(root)][1]
