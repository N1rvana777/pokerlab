"""Versioned non-destructive editing state, atomic persistence and undo."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import re
import threading
import time
import uuid

SCHEMA_VERSION = 1


def uid():
    return uuid.uuid4().hex


def number(value, label, *, minimum=0, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{label} 必须是大于等于 {minimum} 的有限数值")
    return value if isinstance(value, int) else float(value)


def card(value):
    if value in (None, "", "?", "??"):
        return None
    value = str(value).strip().replace("10", "T")
    for symbol, suit in {"♠": "s", "♥": "h", "♦": "d", "♣": "c"}.items():
        value = value.replace(symbol, suit)
    if not re.fullmatch(r"[2-9TJQKA][shdc]", value, re.I):
        raise ValueError(f"非法牌张：{value}；使用 As、Th 等格式，未知牌留空")
    return value[0].upper() + value[1].lower()


def timeline(project):
    result, cursor = [], 0.0
    for clip in project["clips"]:
        duration = clip["out"] - clip["in"]
        result.append({**clip, "start": cursor, "end": cursor + duration, "duration": duration})
        cursor += duration
    return result


def duration(project):
    return sum(c["out"] - c["in"] for c in project["clips"])


def analysis_input(hand):
    return {k: v for k, v in hand.items() if k not in {"analysis", "notes", "title", "name", "start", "end", "overlay_enabled", "board_reveal"}}


def new_project(name="未命名扑克剪辑"):
    return {"schema_version": SCHEMA_VERSION, "id": uid(), "name": name,
            "revision": 0, "created_at": time.time(), "updated_at": time.time(),
            "assets": [], "clips": [], "hands": [], "subtitles": [], "overlays": [],
            "selected_hand_id": None, "playhead": 0,
            "export_settings": {"width": 1280, "height": 720, "fps": 30, "subtitles": True, "overlays": True},
            "audit": []}


def validate(project):
    p = copy.deepcopy(project)
    if p.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("不支持的项目版本，请保留原文件")
    if not isinstance(p.get("id"), str) or not re.fullmatch(r"[a-f0-9]{32}", p["id"]):
        raise ValueError("项目 id 无效")
    if not isinstance(p.get("name"), str) or not p["name"].strip() or len(p["name"]) > 200:
        raise ValueError("项目名称不能为空且最多 200 字")
    for name in ("assets", "clips", "hands", "subtitles", "overlays"):
        if not isinstance(p.get(name), list) or len(p[name]) > 10000:
            raise ValueError(f"{name} 必须是最多 10000 项的列表")
        ids = [x.get("id") for x in p[name] if isinstance(x, dict)]
        if len(ids) != len(p[name]) or any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
            raise ValueError(f"{name} 包含无效或重复 id")
    assets = {x["id"]: x for x in p["assets"]}
    for asset in p["assets"]:
        if not isinstance(asset.get("path"), str) or not asset["path"]:
            raise ValueError("素材路径不能为空")
        if not isinstance(asset.get("metadata"), dict):
            raise ValueError("素材缺少已探测的 metadata")
        asset["metadata"]["duration"] = number(asset["metadata"].get("duration"), "素材时长", minimum=0.001)
    for clip in p["clips"]:
        if clip.get("asset_id") not in assets:
            raise ValueError("片段引用的素材不存在")
        clip["in"] = number(clip.get("in"), "片段入点")
        clip["out"] = number(clip.get("out"), "片段出点")
        if clip["out"] <= clip["in"] or clip["out"] > assets[clip["asset_id"]]["metadata"]["duration"] + 0.05:
            raise ValueError("片段范围须满足 0 ≤ 入点 < 出点 ≤ 素材时长")
    for kind in ("hands", "subtitles", "overlays"):
        for item in p[kind]:
            item["start"] = number(item.get("start"), f"{kind} 开始时间")
            item["end"] = number(item.get("end"), f"{kind} 结束时间")
            if item["end"] <= item["start"]:
                raise ValueError("结束时间必须晚于开始时间")
            if kind != "hands":
                if not isinstance(item.get("text"), str) or len(item["text"]) > 5000:
                    raise ValueError("字幕／叠加文本须为最多 5000 字的字符串")
                if "enabled" in item and not isinstance(item["enabled"], bool):
                    raise ValueError("字幕／叠加 enabled 必须是布尔值")
    for hand in p["hands"]:
        board = hand.get("board", [])
        if not isinstance(board, list) or len(board) > 5:
            raise ValueError("公共牌最多五张")
        hand["board"] = [card(c) for c in board]
        known = [c for c in hand["board"] if c]
        players = hand.get("players", [])
        if not isinstance(players, list) or len(players) > 10:
            raise ValueError("玩家列表无效")
        player_ids = []
        for player in players:
            if not isinstance(player, dict):
                raise ValueError("每位玩家必须是对象")
            player.setdefault("id", uid())
            if not isinstance(player["id"], str) or not player["id"]:
                raise ValueError("玩家 id 不能为空")
            player_ids.append(player["id"])
            cards = player.get("cards", [None, None])
            if not isinstance(cards, list) or len(cards) != 2:
                raise ValueError("每位玩家需要两张底牌；未知牌使用 null")
            player["cards"] = [card(c) for c in cards]
            known += [c for c in player["cards"] if c]
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("玩家 id 重复")
        if len(known) != len(set(known)):
            raise ValueError("手牌存在重复牌或公共牌冲突")
        for key in ("pot", "effective_stack"):
            hand[key] = number(hand.get(key), key, optional=True)
        if hand.get("amount_unit", "chips") not in ("chips", "USD"):
            raise ValueError("金额单位必须为 chips 或 USD")
        for key in ("actions", "board_reveal"):
            if not isinstance(hand.get(key, []), list) or len(hand.get(key, [])) > 10000:
                raise ValueError(f"{key} 必须是最多10000项的列表")
        for action in hand.get("actions", []):
            if not isinstance(action, dict):
                raise ValueError("行动必须是对象")
            if action.get("street") not in ("preflop", "flop", "turn", "river"):
                raise ValueError("行动 street 无效")
            if action.get("type") not in ("check", "bet", "call", "raise", "fold", "allin", "showdown"):
                raise ValueError("行动 type 无效")
            if action.get("player_id") not in player_ids:
                raise ValueError("行动引用未知玩家")
            action["time"] = number(action.get("time"), "行动项目时间")
            action["amount"] = number(action.get("amount"), "行动金额", optional=True)
            if "pot_after" in action:
                action["pot_after"] = number(action["pot_after"], "行动后底池", optional=True)
        for reveal in hand.get("board_reveal", []):
            reveal["time"] = number(reveal.get("time"), "发公共牌时间")
            reveal["cards"] = [card(c) for c in reveal.get("cards", [])]
            if len(reveal["cards"]) > 5 or any(c not in hand["board"] for c in reveal["cards"] if c):
                raise ValueError("发牌事件必须引用已记录的公共牌")
    settings = p.setdefault("export_settings", {})
    for key, default, low, high in (("width", 1280, 320, 3840), ("height", 720, 240, 2160), ("fps", 30, 1, 60)):
        settings[key] = number(settings.get(key, default), key, minimum=low)
        if settings[key] > high or settings[key] != int(settings[key]):
            raise ValueError(f"{key} 超出范围或不是整数")
        settings[key] = int(settings[key])
    if settings["width"] % 2 or settings["height"] % 2:
        raise ValueError("导出宽高必须为偶数")
    for key in ("subtitles", "overlays"):
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError(f"导出设置 {key} 必须为布尔值")
    p["playhead"] = number(p.get("playhead", 0), "预览位置")
    return p


class ProjectStore:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.projects_dir = self.data_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.project = new_project()
        self.path = None
        self.undo_stack, self.redo_stack = [], []
        recent = self.data_dir / "last_project.json"
        if recent.exists():
            try:
                self.open(json.loads(recent.read_text(encoding="utf-8"))["path"])
            except (OSError, ValueError, KeyError):
                pass

    def get(self):
        with self.lock:
            p = copy.deepcopy(self.project)
            p["timeline"] = timeline(p)
            p["duration"] = duration(p)
            p["file_path"] = str(self.path) if self.path else None
            p["can_undo"] = bool(self.undo_stack)
            p["can_redo"] = bool(self.redo_stack)
            p["warnings"] = [f"素材路径失效，请重新定位：{a['path']}" for a in p["assets"] if not Path(a["path"]).is_file()]
            for kind in ("hands", "subtitles", "overlays"):
                p["warnings"] += [f"{kind} {x['id']} 超出当前时间线；导出仅保留重叠范围" for x in p[kind] if x["end"] > p["duration"] + 0.01]
            return p

    def create(self, name):
        with self.lock:
            self.project = validate(new_project(name))
            self.path = None
            self.undo_stack, self.redo_stack = [], []
            return self.save()

    def set_playhead(self, seconds, *, project_id=None):
        """A navigation bookmark is saved without consuming undo or content revision."""
        with self.lock:
            if project_id and project_id != self.project["id"]:
                raise ValueError("项目已切换，忽略旧播放位置")
            seconds = number(seconds, "播放位置")
            if seconds > duration(self.project):
                raise ValueError("播放位置超出当前时间线")
            self.project["playhead"] = seconds
            return self.save()

    @staticmethod
    def _write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + "." + uid() + ".tmp")
        try:
            temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)

    def save(self, path=None):
        with self.lock:
            target = Path(path).expanduser().resolve() if path else self.path or self.projects_dir / f"{self.project['id']}.pokerstudio.json"
            if target.suffix.lower() != ".json":
                raise ValueError("项目文件必须使用 .json 后缀")
            if target.exists() and target != self.path:
                raise ValueError("另存路径已存在；请选择新文件名，避免覆盖已有项目")
            self._write(target, self.project)
            self.path = target
            self._write(self.data_dir / "last_project.json", {"path": str(target)})
            return self.get()

    def open(self, path):
        target = Path(path).expanduser().resolve()
        if target.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("项目 JSON 超过 16MiB，拒绝加载")
        p = validate(json.loads(target.read_text(encoding="utf-8-sig")))
        with self.lock:
            self.project, self.path = p, target
            self.undo_stack, self.redo_stack = [], []
            self._write(self.data_dir / "last_project.json", {"path": str(target)})
            return self.get()

    def list(self):
        result = []
        for path in sorted(self.projects_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                p = json.loads(path.read_text(encoding="utf-8"))
                result.append({"id": p["id"], "name": p["name"], "path": str(path), "updated_at": p["updated_at"]})
            except (OSError, ValueError, KeyError):
                continue
        return result

    def _commit(self, p, label, source):
        p = validate(p)
        self.undo_stack.append(copy.deepcopy(self.project))
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()
        p["revision"] = self.project["revision"] + 1
        p["updated_at"] = time.time()
        p.setdefault("audit", []).append({"time": time.time(), "revision": p["revision"], "label": label, "source": source})
        p["audit"] = p["audit"][-200:]
        self.project = p
        return self.get()

    def edit(self, command, *, source="user", expected_revision=None, project_id=None):
        with self.lock:
            if project_id and project_id != self.project["id"]:
                raise ValueError("当前项目已切换；该任务不能修改另一项目")
            if expected_revision is not None and expected_revision != self.project["revision"]:
                raise ValueError("项目已被其他操作更新，请刷新后重试")
            p = copy.deepcopy(self.project)
            op = command.get("op")
            if op == "name":
                p["name"] = command["name"]
            elif op == "add_asset":
                asset = copy.deepcopy(command["asset"])
                p["assets"].append(asset)
                if command.get("add_clip", True):
                    p["clips"].append({"id": uid(), "asset_id": asset["id"], "in": 0, "out": asset["metadata"]["duration"], "name": asset.get("name", "素材")})
            elif op == "relink_asset":
                asset = next(a for a in p["assets"] if a["id"] == command["id"])
                asset.update(path=command["path"], metadata=command["metadata"])
                asset.pop("proxy_path", None)
            elif op == "attach_proxy":
                asset = next(a for a in p["assets"] if a["id"] == command["id"])
                if asset["path"] != command["source_path"]:
                    raise ValueError("素材路径已经改变，此代理不可绑定")
                if not Path(command["path"]).is_file():
                    raise ValueError("代理文件不存在")
                asset["proxy_path"] = command["path"]
            elif op == "add_clip":
                clip = copy.deepcopy(command["clip"])
                clip.setdefault("id", uid())
                p["clips"].append(clip)
            elif op in ("trim_clip", "split_clip", "delete_clip", "move_clip"):
                index = next(i for i, c in enumerate(p["clips"]) if c["id"] == command["id"])
                clip = p["clips"][index]
                if op == "trim_clip":
                    clip.update({k: command[k] for k in ("in", "out", "name") if k in command})
                elif op == "split_clip":
                    at = number(command["at"], "素材切分时间")
                    if not clip["in"] < at < clip["out"]:
                        raise ValueError("切分位置必须位于片段内部")
                    right = {**clip, "id": uid(), "in": at}
                    clip["out"] = at
                    p["clips"].insert(index + 1, right)
                elif op == "delete_clip":
                    p["clips"].pop(index)
                else:
                    to = command["to"]
                    if not isinstance(to, int) or not 0 <= to < len(p["clips"]):
                        raise ValueError("目标片段序号无效")
                    p["clips"].insert(to, p["clips"].pop(index))
            elif op == "replace_timeline":
                p["clips"] = copy.deepcopy(command["clips"])
            elif op == "crop_range":
                start, end = number(command["start"], "剪辑开始"), number(command["end"], "剪辑结束")
                if not 0 <= start < end <= duration(p):
                    raise ValueError("剪辑范围必须位于当前项目时间线内")
                clips = []
                for c in timeline(p):
                    left, right = max(start, c["start"]), min(end, c["end"])
                    if left < right:
                        clips.append({"id": uid(), "asset_id": c["asset_id"], "name": c.get("name", "片段"),
                                      "in": c["in"] + left - c["start"], "out": c["in"] + right - c["start"]})
                p["clips"] = clips
                for key in ("hands", "subtitles", "overlays"):
                    kept = []
                    for item in p[key]:
                        left, right = max(start, item["start"]), min(end, item["end"])
                        if left >= right:
                            continue
                        item["start"], item["end"] = left - start, right - start
                        if key == "hands":
                            for action in item.get("actions", []):
                                action["time"] = max(0, action["time"] - start)
                            for reveal in item.get("board_reveal", []):
                                reveal["time"] = max(0, reveal["time"] - start)
                        kept.append(item)
                    p[key] = kept
                p["selected_hand_id"] = p["hands"][0]["id"] if p["hands"] else None
                p["playhead"] = 0
            elif op in ("upsert_hand", "upsert_subtitle", "upsert_overlay"):
                key = {"upsert_hand": "hands", "upsert_subtitle": "subtitles", "upsert_overlay": "overlays"}[op]
                item = copy.deepcopy(command["item"])
                item.setdefault("id", uid())
                old = next((x for x in p[key] if x["id"] == item["id"]), None)
                if old:
                    previous_input = copy.deepcopy(analysis_input(old)) if key == "hands" else None
                    old.update(item)
                    if key == "hands" and old.get("analysis") and "analysis" not in item and previous_input != analysis_input(old):
                        old["analysis"]["stale"] = True
                else:
                    p[key].append(item)
                if key == "hands":
                    p["selected_hand_id"] = item["id"]
            elif op in ("delete_hand", "delete_subtitle", "delete_overlay"):
                key = {"delete_hand": "hands", "delete_subtitle": "subtitles", "delete_overlay": "overlays"}[op]
                p[key] = [x for x in p[key] if x["id"] != command["id"]]
                if key == "hands" and p["selected_hand_id"] == command["id"]:
                    p["selected_hand_id"] = p[key][0]["id"] if p[key] else None
            elif op == "replace_subtitles":
                p["subtitles"] = copy.deepcopy(command["subtitles"])
            elif op == "select_hand":
                if command["id"] not in {h["id"] for h in p["hands"]}:
                    raise ValueError("手牌不存在")
                p["selected_hand_id"] = command["id"]
            elif op == "settings":
                p["export_settings"].update(command["settings"])
            elif op == "playhead":
                p["playhead"] = command["time"]
            else:
                raise ValueError(f"未知编辑操作：{op}")
            return self._commit(p, op, source)

    def undo(self):
        with self.lock:
            if not self.undo_stack:
                raise ValueError("没有可撤销操作")
            self.redo_stack.append(copy.deepcopy(self.project))
            rev = self.project["revision"] + 1
            audit = copy.deepcopy(self.project.get("audit", []))
            self.project = self.undo_stack.pop()
            self.project["revision"] = rev
            self.project["updated_at"] = time.time()
            self.project["audit"] = (audit + [{"time": time.time(), "revision": rev, "label": "undo", "source": "user"}])[-200:]
            return self.get()

    def redo(self):
        with self.lock:
            if not self.redo_stack:
                raise ValueError("没有可恢复操作")
            self.undo_stack.append(copy.deepcopy(self.project))
            rev = self.project["revision"] + 1
            audit = copy.deepcopy(self.project.get("audit", []))
            self.project = self.redo_stack.pop()
            self.project["revision"] = rev
            self.project["updated_at"] = time.time()
            self.project["audit"] = (audit + [{"time": time.time(), "revision": rev, "label": "redo", "source": "user"}])[-200:]
            return self.get()
