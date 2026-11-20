"""Append-only local store: hand revisions are write-once files; confirmations, aliases,
hero names and notes go to ``events.jsonl``. Statistics use confirmed revisions only.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time

from .evidence import observations, showdowns
from .hands import hand_summary, normalize, replay
from .live import DEFAULT_PRESET, PRESETS
from .pokerstars import parse_text
from .stats import load_priors, player_type, profile, tags

ROOT = Path(__file__).resolve().parents[3]


def coach_home():
    return Path(os.environ.get("POKERLAB_COACH_HOME") or ROOT / "outputs/coach")


def key_of(name):
    return " ".join(str(name).split()).casefold()


NOTE_KINDS = ("observation", "inference")   # the user's own description / the assistant's conclusion
NOTE_TOPICS = ("mood", "tell", "image", "read", "tendency", "other")
SELECTED_NOTE = ("其中 {} 手来自现场笔记。笔记只记用户挑出来的牌，不是这个人打的全部牌，所以入池率、加注率、3-bet 和摊牌率不统计这些手；"
                 "其余项目只描述记下来的这些手，不能直接当成真实频率。")


class CoachStore:
    def __init__(self, root=None, priors_path=None):
        self.root = Path(root or coach_home()).resolve()
        (self.root / "hands").mkdir(parents=True, exist_ok=True)
        self.events_file = self.root / "events.jsonl"
        self.priors = load_priors(priors_path)
        self.lock = threading.RLock()
        self.revisions, self.events, self.load_warnings, self._replays = {}, [], [], {}
        for folder in sorted((self.root / "hands").iterdir()):
            for path in sorted(folder.glob("r*.json")) if folder.is_dir() else []:
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    record["hand"] = normalize(record["hand"])
                    self.revisions.setdefault(record["hand"]["hand_id"], []).append(record)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.load_warnings.append(f"{path.name}: {exc}")
        for records in self.revisions.values():
            records.sort(key=lambda r: r["revision"])
        if self.events_file.is_file():
            for number, line in enumerate(self.events_file.read_text(encoding="utf-8").splitlines(), 1):
                if line.strip():
                    try:
                        self.events.append(json.loads(line))
                    except ValueError:
                        self.load_warnings.append(f"events.jsonl 第 {number} 行损坏，已跳过")

    # ---- write paths (never rewrite an existing file) ----
    def _event(self, event):
        event = {**event, "at": time.time()}
        with self.lock, self.events_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            self.events.append(event)
        return event

    def _folder(self, hand_id):
        return self.root / "hands" / (hand_id.replace(":", "_") + "-" + hashlib.sha1(hand_id.encode()).hexdigest()[:6])

    def add_hand(self, hand, origin, confirm=False):
        h = normalize(hand)
        r = replay(h)
        with self.lock:
            records = self.revisions.setdefault(h["hand_id"], [])
            if records and records[-1]["hand"] == h:
                return {**self.hand_status(h["hand_id"]), "result": "duplicate"}
            record = {"hand": h, "revision": len(records) + 1, "origin": origin, "created_at": time.time(),
                      "errors": r.errors, "warnings": r.warnings}
            folder = self._folder(h["hand_id"])
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / f"r{record['revision']:04d}.json").open("x", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=1)
            records.append(record)
            if confirm and not r.errors:
                self._event({"type": "confirm", "hand_id": h["hand_id"], "revision": record["revision"], "by": origin})
        return {**self.hand_status(h["hand_id"]), "result": "stored"}

    def import_text(self, text):
        results = []
        for hand, r, problems in parse_text(text):
            if hand is None or problems:
                results.append({"hand_id": hand["hand_id"] if hand else None, "result": "rejected", "problems": problems})
            else:
                status = self.add_hand(hand, "import", confirm=True)
                status["warnings"] = r.warnings
                results.append(status)
        if not results:
            results.append({"hand_id": None, "result": "rejected", "problems": ["没有找到 PokerStars/GG 格式的手牌头"]})
        return results

    def confirm(self, hand_id, revision, by="user"):
        record = self.record(hand_id, revision)
        if record["errors"]:
            raise ValueError("这一修订有错误，不能确认：" + "；".join(record["errors"][:3]))
        self._event({"type": "confirm", "hand_id": hand_id, "revision": revision, "by": by})
        return self.hand_status(hand_id)

    def unconfirm(self, hand_id, by="user"):
        self.record(hand_id)
        self._event({"type": "unconfirm", "hand_id": hand_id, "by": by})
        return self.hand_status(hand_id)

    def link_alias(self, name, target):
        if not key_of(name) or not key_of(target):
            raise ValueError("名字不能为空")
        self._event({"type": "alias", "name": key_of(name), "target": key_of(target)})
        return {"name": key_of(name), "resolves_to": self.resolve(name)}

    def set_hero(self, names):
        if not isinstance(names, list) or len(names) > 10 or not all(isinstance(n, str) and n.strip() for n in names):
            raise ValueError("Hero 名字需要 1–10 个非空字符串")
        self._event({"type": "hero", "names": sorted({key_of(n) for n in names})})
        return {"hero_names": self.hero_names()}

    def add_note(self, player, text, hand_ids, source, kind="inference", topic=None, session=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError("备注需要 1–2000 字")
        if kind not in NOTE_KINDS or (topic is not None and topic not in NOTE_TOPICS):
            raise ValueError("备注类型只能是 observation / inference；主题只能是 " + " / ".join(NOTE_TOPICS))
        if session is not None and (not isinstance(session, str) or len(session) > 20):
            raise ValueError("session 是不超过 20 字的日期或场次")
        missing = [h for h in hand_ids if h not in self.revisions]
        if missing:
            raise ValueError("备注引用的手牌不存在：" + "、".join(missing))
        if source != "user" and kind == "inference" and not hand_ids:
            raise ValueError("助手的推断必须引用至少一手牌；转述用户自己的描述请用 kind=observation")
        if key_of(player).startswith("#"):
            raise ValueError("匿名座位不能写备注")
        event = self._event({"type": "note", "player": self.resolve(player), "text": text.strip(), "hand_ids": list(hand_ids),
                             "source": source, "kind": kind, "topic": topic, "session": session})
        return {"player": event["player"], "note": event}

    def default_game(self):
        key = DEFAULT_PRESET
        for e in self.events:
            if e.get("type") == "default_game" and e.get("preset") in PRESETS:
                key = e["preset"]
        return key

    def set_default_game(self, preset):
        if preset not in PRESETS:
            raise ValueError(f"未知级别 {preset}；可用：{', '.join(PRESETS)}")
        self._event({"type": "default_game", "preset": preset})
        return self.settings()

    def settings(self):
        key = self.default_game()
        return {"default_game": key, "default_game_label": PRESETS[key]["label"],
                "presets": {k: v["label"] for k, v in PRESETS.items()}, "hero_names": self.hero_names()}

    def context(self):
        """What the assistant needs before reading notes: level, hero names and every known player label."""
        known = {}

        def touch(name):
            key = self.resolve(name)
            if key.startswith("#"):
                return None
            entry = known.setdefault(key, {"player": name, "aliases": set(), "confirmed_hands": 0, "pending_hands": 0, "notes": []})
            entry["aliases"].add(name)
            return entry

        confirmed = self._confirmed_map()
        for hand_id, records in self.revisions.items():
            for p in records[-1]["hand"]["players"]:
                entry = touch(p["name"])
                if entry is not None:
                    entry["confirmed_hands" if hand_id in confirmed else "pending_hands"] += 1
        for e in self.events:
            if e.get("type") == "alias":
                touch(e["name"])
            elif e.get("type") == "note":
                entry = touch(e["player"])
                if entry is not None:
                    entry["notes"].append(e["text"][:160])
        heroes = {self.resolve(n) for n in self.hero_names()}
        players = [{"player": v["player"], "key": k, "is_hero": k in heroes, "aliases": sorted(v["aliases"]),
                    "confirmed_hands": v["confirmed_hands"], "pending_hands": v["pending_hands"],
                    "notes": len(v["notes"]), "recent_notes": v["notes"][-3:]} for k, v in known.items()]
        return {**self.settings(), "default_game_detail": PRESETS[self.default_game()],
                "players": sorted(players, key=lambda p: (-p["confirmed_hands"] - p["pending_hands"], p["key"]))}

    # ---- derived state ----
    def _aliases(self):
        mapping = {}
        for e in self.events:
            if e.get("type") == "alias":
                if e["name"] == e["target"]:
                    mapping.pop(e["name"], None)
                else:
                    mapping[e["name"]] = e["target"]
        return mapping

    def resolve(self, name):
        aliases, key, seen = self._aliases(), key_of(name), set()
        while key in aliases and key not in seen:
            seen.add(key)
            key = aliases[key]
        return key

    def hero_names(self):
        names = []
        for e in self.events:
            if e.get("type") == "hero":
                names = e["names"]
        return names

    def _confirmed_map(self):
        state = {}
        for e in self.events:
            if e.get("type") == "confirm":
                state[e["hand_id"]] = e["revision"]
            elif e.get("type") == "unconfirm":
                state.pop(e["hand_id"], None)
        return state

    def record(self, hand_id, revision=None):
        records = self.revisions.get(hand_id)
        if not records:
            raise ValueError("手牌不存在：" + str(hand_id))
        if revision is None:
            return records[-1]
        found = next((r for r in records if r["revision"] == revision), None)
        if found is None:
            raise ValueError(f"手牌 {hand_id} 没有修订 {revision}")
        return found

    def _replay(self, record):
        key = (record["hand"]["hand_id"], record["revision"])
        if key not in self._replays:
            self._replays[key] = replay(record["hand"])
        return self._replays[key]

    def hand_status(self, hand_id):
        latest = self.record(hand_id)
        confirmed = self._confirmed_map().get(hand_id)
        if confirmed is None:
            status = "has_errors" if latest["errors"] else "pending"
        else:
            status = "confirmed" if confirmed == latest["revision"] else "new_revision"
        return {"hand_id": hand_id, "status": status, "latest_revision": latest["revision"],
                "confirmed_revision": confirmed, "origin": latest["origin"], "errors": latest["errors"],
                "warnings": latest["warnings"]}

    def confirmed_records(self):
        state = self._confirmed_map()
        return [self.record(h, rev) for h, rev in state.items() if h in self.revisions]

    def _gather(self):
        """Observations, showdowns and hands per resolved player key, from confirmed hands."""
        data = {}
        for record in self.confirmed_records():
            hand, r = record["hand"], self._replay(record)
            keys = {p["name"]: self.resolve(p["name"]) for p in hand["players"]}
            for p in hand["players"]:
                if keys[p["name"]].startswith("#"):
                    continue  # anonymous seat from a live note
                entry = data.setdefault(keys[p["name"]], {"names": [], "hands": [], "obs": [], "showdowns": [], "bomb_pots": 0, "selected": 0})
                entry["hands"].append(hand["hand_id"])
                entry["bomb_pots"] += bool(hand["game"]["bomb_pot"])
                entry["selected"] += hand["source"]["kind"] == "live_text"
                if p["name"] not in entry["names"]:
                    entry["names"].append(p["name"])
            for o in observations(hand, r):
                if o.player in keys and keys[o.player] in data:
                    data[keys[o.player]]["obs"].append(o)
            for s in showdowns(hand, r):
                if keys[s["player"]] in data:
                    data[keys[s["player"]]]["showdowns"].append(s)
        return data

    def _notes(self, key):
        return [{k: e.get(k) for k in ("text", "hand_ids", "source", "kind", "topic", "session", "at")} for e in self.events
                if e.get("type") == "note" and self.resolve(e["player"]) == key]

    def players(self, include_hero=True):
        heroes = {self.resolve(n) for n in self.hero_names()}
        out = []
        for key, entry in self._gather().items():
            if key in heroes and not include_hero:
                continue
            prof = profile(entry["obs"], self.priors)
            out.append({"player": entry["names"][-1], "key": key, "aliases": entry["names"], "is_hero": key in heroes,
                        "hands": len(entry["hands"]), "vpip": prof["vpip"]["raw"], "pfr": prof["pfr"]["raw"],
                        "type": player_type(prof)["type"], "tags": [t["label"] + f" {t['score']}/10" for t in tags(prof, self.priors)[:3]]})
        return sorted(out, key=lambda p: (-p["hands"], p["key"]))

    def player_profile(self, name):
        key = self.resolve(name)
        entry = self._gather().get(key)
        pending = [h for h, records in self.revisions.items()
                   if self.hand_status(h)["status"] != "confirmed"
                   and any(self.resolve(p["name"]) == key for p in records[-1]["hand"]["players"])]
        if entry is None:
            return {"player": name, "key": key, "hands": 0, "pending_hands": pending, "notes": self._notes(key),
                    "message": "已确认的手牌里没有这个玩家（别名可以合并到已有玩家）"}
        prof = profile(entry["obs"], self.priors)
        return {"player": entry["names"][-1], "key": key, "aliases": entry["names"],
                "is_hero": key in {self.resolve(n) for n in self.hero_names()}, "hands": len(entry["hands"]),
                "hand_ids": entry["hands"][-30:], "bomb_pot_hands": entry["bomb_pots"], "pending_hands": pending,
                "selected_hands": entry["selected"], "sample_note": SELECTED_NOTE.format(entry["selected"]) if entry["selected"] else None,
                "type": player_type(prof),
                "tags": tags(prof, self.priors), "stats": prof, "showdowns": entry["showdowns"][-15:],
                "notes": self._notes(key),
                "priors": {k: self.priors[k] for k in ("version", "calibrated", "description", "strength")}}

    def list_hands(self, status="all", player=None, limit=50):
        key = self.resolve(player) if player else None
        rows = []
        for hand_id in self.revisions:
            row = self.hand_status(hand_id)
            hand = self.record(hand_id)["hand"]
            if status != "all" and (row["status"] == "confirmed") != (status == "confirmed"):
                continue
            if key and not any(self.resolve(p["name"]) == key for p in hand["players"]):
                continue
            rows.append({**hand_summary(hand, self._replay(self.record(hand_id))), **row,
                         "errors": len(row["errors"]), "warnings": len(row["warnings"])})
        rows.sort(key=lambda r: (r.get("played_at") or "", r["hand_id"]))
        return rows[-limit:]

    def hand_detail(self, hand_id, revision=None):
        record = self.record(hand_id, revision)
        r = self._replay(record)
        return {"record": record, "status": self.hand_status(hand_id), "replay": r.summary(),
                "observations": [o.__dict__ for o in observations(record["hand"], r)] if r.complete else [],
                "showdowns": showdowns(record["hand"], r)}
