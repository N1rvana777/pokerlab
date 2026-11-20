"""The same validated business tools serve the UI and both agent providers."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import time

from .project import ProjectStore, uid, analysis_input
from .solver import SolverAdapter, default_config, validate_config


def schema(name, description, properties=None, required=None):
    return {"name": name, "description": description, "input_schema": {
        "type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}}


TEXT = {"type": "string"}
OBJECT = {"type": "object"}
TOOL_SCHEMAS = [
    schema("read_project", "读取当前剪辑项目及选中手牌；分析入口返回独立分析配置。"),
    schema("update_hand", "修改已选/指定手牌的已确认信息。未知牌/金额保持null，不编造行动。编辑可撤销并自动保存。", {"hand_id": TEXT, "patch": OBJECT}, ["patch"]),
    schema("edit_timeline", "执行真实非破坏时间线编辑。command.op可为 trim_clip/split_clip/move_clip/delete_clip/add_clip/replace_timeline/crop_range；crop_range开始结束是项目秒，其他in/out/at是素材秒。", {"command": OBJECT}, ["command"]),
    schema("extract_selected_hand", "把当前标记手牌的项目开始结束范围裁成独立时间线；同步保留相交字幕/叠加，可撤销。"),
    schema("update_subtitle", "新增或修改带项目秒start/end/text的字幕；已有字幕用id。", {"subtitle": OBJECT}, ["subtitle"]),
    schema("update_overlay", "新增或修改说明叠加，含start/end/text/enabled；项目秒。", {"overlay": OBJECT}, ["overlay"]),
    schema("set_analysis_config", "更新独立Pokerlab分析入口的完整v1 solver配置，适用范围由真实适配器验证。", {"config": OBJECT}, ["config"]),
    schema("solve_hand", "调用真实Pokerlab solver。剪辑入口对选中手牌求解；分析入口对独立配置求解。缺字段会报错。返回任务，必须查询completed后才能报告EV。", {"config": OBJECT, "options": OBJECT}),
    schema("get_solver_result", "读取成功完成的真实solver报告，包含输入、假设与测得精度；未完成会报错。", {"task_id": TEXT}, ["task_id"]),
    schema("get_task", "查询导出/媒体/求解任务真实状态、进度与错误。", {"task_id": TEXT}, ["task_id"]),
    schema("cancel_task", "取消指定任务；请求取消不代表任务已经完成取消，继续查终态。", {"task_id": TEXT}, ["task_id"]),
    schema("export_video", "按当前已保存剪辑时间线、字幕和叠加启动真实MP4导出。返回任务，必须查成功终态才称已导出。"),
    schema("undo_edit", "撤销最近一次项目编辑并保存。"),
]


class Studio:
    def __init__(self, data_dir):
        from . import media
        from .tasks import TaskManager
        from .agent import AgentService
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = ProjectStore(self.data_dir)
        self.media = media
        self.tasks = TaskManager()
        self.solver = SolverAdapter()
        self.solver_bindings = {}
        self.analysis_config = None
        path = self.data_dir / "analysis.json"
        if path.exists():
            try:
                self.analysis_config = validate_config(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        self.agent = AgentService(self.data_dir / "agent-sessions", self.execute_tool, TOOL_SCHEMAS,
                                  workspace=Path(__file__).resolve().parent)

    def close(self):
        self.agent.close()
        self.tasks.shutdown()
        self.solver.close()

    def import_asset(self, path, *, asset_id=None, project_id=None):
        project_id = project_id or self.store.get()["id"]
        path = Path(path).expanduser().resolve()
        metadata = self.media.probe_media(path)
        with self.store.lock:
            if asset_id:
                p = self.store.edit({"op": "relink_asset", "id": asset_id, "path": str(path), "metadata": metadata}, project_id=project_id)
            else:
                p = self.store.edit({"op": "add_asset", "asset": {
                    "id": uid(), "name": path.name, "path": str(path), "metadata": metadata}}, project_id=project_id)
            self.store.save()
        return p

    def selected_hand(self):
        p = self.store.get()
        hand = next((h for h in p["hands"] if h["id"] == p["selected_hand_id"]), None)
        if hand is None:
            raise ValueError("请先标记并选中一手牌")
        return hand

    def edit(self, command, *, context=None, expected_revision=None, project_id=None):
        if context and context.get("entry") == "analysis":
            raise ValueError("Pokerlab分析会话不能修改剪辑项目")
        if command.get("op") == "upsert_hand" and "analysis" in command.get("item", {}):
            raise ValueError("analysis 只接受真实 solver 完成后的报告，不能手工写入数值")
        with self.store.lock:
            p = self.store.edit(command, source="agent" if context else "user", expected_revision=expected_revision,
                                project_id=context.get("project_id") if context else project_id)
            self.store.save()
        return p

    def undo(self, *, project_id=None, redo=False):
        with self.store.lock:
            if project_id and self.store.get()["id"] != project_id:
                raise ValueError("项目已切换，该撤销不能操作另一项目")
            p = self.store.redo() if redo else self.store.undo()
            self.store.save()
            return p

    def set_analysis(self, config):
        config = validate_config(config)
        self.analysis_config = config
        ProjectStore._write(self.data_dir / "analysis.json", config)
        return {"entry": "analysis", "config": copy.deepcopy(config)}

    def solve(self, *, config=None, hand=None, options=None, entry="studio", project_id=None):
        project = self.store.get()
        if entry != "analysis" and project_id and project_id != project["id"]:
            raise ValueError("项目已切换，该分析不能使用另一项目的手牌")
        if entry == "analysis":
            config = config or self.analysis_config
            if config is None:
                raise ValueError("分析入口没有已确认配置，请先载入示例或输入完整配置")
        elif hand is None:
            hand = next((h for h in project["hands"] if h["id"] == project["selected_hand_id"]), None)
            if hand is None:
                raise ValueError("请先标记并选中一手牌")
            config = config or hand.get("solver_config")
        state = self.solver.start(config=config, hand=hand, options=options)
        if hand:
            self.solver_bindings[state["id"]] = {"project_id": project["id"], "hand_id": hand["id"], "hand": copy.deepcopy(hand)}
        return {**state, "task_id": "solve:" + state["id"]}

    def solver_result(self, task_id):
        job_id = task_id.removeprefix("solve:")
        result = self.solver.result(job_id)
        bind = self.solver_bindings.get(job_id)
        if bind and bind["project_id"] == self.store.get()["id"]:
            p = self.store.get()
            current = next((h for h in p["hands"] if h["id"] == bind["hand_id"]), None)
            if current:
                analysis = {"job_id": job_id, "stale": analysis_input(current) != analysis_input(bind["hand"]),
                            "input": result.get("studio_adapter"), "report": result}
                if (current.get("analysis") or {}).get("job_id") != job_id:
                    with self.store.lock:
                        self.store.edit({"op": "upsert_hand", "item": {"id": current["id"], "analysis": analysis}}, source="solver", project_id=bind["project_id"])
                        self.store.save()
        return result

    def task_status(self, task_id):
        if task_id.startswith("solve:"):
            return {**self.solver.status(task_id[6:]), "task_id": task_id}
        return self.tasks.get(task_id.removeprefix("media:"))

    def cancel_task(self, task_id):
        if task_id.startswith("solve:"):
            return self.solver.cancel(task_id[6:])
        return self.tasks.cancel(task_id.removeprefix("media:"))

    def export(self):
        project = self.store.get()
        if not project["clips"]:
            raise ValueError("时间线没有片段，不能导出")
        if project["warnings"] and any("路径失效" in w for w in project["warnings"]):
            raise ValueError("存在失效素材路径，请先重新定位")
        output = self.data_dir / "exports" / f"{project['id']}-{int(time.time())}-{uid()[:8]}.mp4"
        self.store.save()
        return self.tasks.create("export", lambda task: self.media.export_project(project, output, task))

    def execute_tool(self, name, args, context=None):
        context = context or {}
        entry = context.get("entry", "studio")
        if entry == "studio" and context.get("project_id") and context["project_id"] != self.store.get()["id"]:
            raise ValueError("项目已切换，本会话不可操作新项目；请新建会话")
        if name == "read_project":
            if entry == "analysis":
                return {"entry": "analysis", "config": self.analysis_config, "solver_capabilities": "两人街开始OOP；Flop/Turn/River；真实固定对手BR及均衡测量"}
            p = self.store.get()
            return {k: v for k, v in p.items() if k != "audit"}
        if name == "set_analysis_config":
            if entry != "analysis":
                raise ValueError("请在Pokerlab分析入口修改独立分析配置")
            return self.set_analysis(args["config"])
        if name == "update_hand":
            hand_id = args.get("hand_id") or self.selected_hand()["id"]
            patch = args["patch"]
            if "id" in patch and patch["id"] != hand_id:
                raise ValueError("不能通过patch更换手牌id")
            return self.edit({"op": "upsert_hand", "item": {**patch, "id": hand_id}}, context=context)
        if name == "edit_timeline":
            if args["command"].get("op") not in {"trim_clip", "split_clip", "move_clip", "delete_clip", "add_clip", "replace_timeline", "crop_range"}:
                raise ValueError("时间线工具不允许此操作")
            return self.edit(args["command"], context=context)
        if name == "extract_selected_hand":
            hand = self.selected_hand()
            return self.edit({"op": "crop_range", "start": hand["start"], "end": hand["end"]}, context=context)
        if name in ("update_subtitle", "update_overlay"):
            key = "subtitle" if name == "update_subtitle" else "overlay"
            return self.edit({"op": "upsert_" + key, "item": args[key]}, context=context)
        if name == "solve_hand":
            return self.solve(config=args.get("config"), options=args.get("options"), entry=entry, project_id=context.get("project_id"))
        if name == "get_solver_result":
            return self.solver_result(args["task_id"])
        if name == "get_task":
            return self.task_status(args["task_id"])
        if name == "cancel_task":
            return self.cancel_task(args["task_id"])
        if name == "export_video":
            if entry != "studio":
                raise ValueError("分析会话不能导出剪辑项目")
            return self.export()
        if name == "undo_edit":
            if entry != "studio":
                raise ValueError("分析会话不能撤销剪辑项目")
            return self.undo(project_id=context.get("project_id"))
        raise ValueError("未知业务工具：" + name)
