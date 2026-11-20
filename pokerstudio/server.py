"""Local-only HTTP application. Run: python -m pokerstudio.server."""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .project import uid
from .solver import default_config
from .tools import Studio

ROOT = Path(__file__).resolve().parent


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows SO_REUSEADDR allows two listeners to claim the same port.
    # Exclusive binding keeps the existing app and its token/session intact.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, address, studio):
        super().__init__(address, Handler)
        self.studio = studio
        self.token = secrets.token_urlsafe(32)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Never log request bodies, keys, OAuth codes, media paths or query tokens.
        return

    def _guard(self, mutate=False):
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if host not in allowed:
            raise PermissionError("只接受本机地址请求")
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + x for x in allowed}:
            raise PermissionError("拒绝其他网页访问本地应用")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise PermissionError("拒绝跨网站请求")
        if mutate and not secrets.compare_digest(self.headers.get("X-Pokerstudio-Token", ""), self.server.token):
            raise PermissionError("请求令牌失效，请刷新本地页面")

    def _json(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 2 * 1024 * 1024:
            raise ValueError("JSON请求体必须为1字节至2MiB")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("请求体必须是JSON对象")
        return data

    def _file(self, path, content_type=None, download=False):
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError("文件不存在，请重新定位素材")
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        value = self.headers.get("Range")
        if value:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
            if not match or not any(match.groups()):
                self.send_error(416)
                return
            a, b = match.groups()
            if a:
                start = int(a)
                end = min(int(b), size - 1) if b else size - 1
            else:
                start = max(0, size - int(b))
            if not 0 <= start <= end < size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="pokerstudio-export.mp4"')
        self.end_headers()
        if self.command == "HEAD":
            return
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _handle_error(self, exc):
        if isinstance(exc, ConnectionError):
            self.close_connection = True
            return
        from .agent.service import public_error
        status = 403 if isinstance(exc, PermissionError) else 404 if isinstance(exc, (FileNotFoundError, KeyError, StopIteration)) else 400
        self._json({"error": public_error(exc)}, status)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            self._guard()
            studio = self.server.studio
            url = urlparse(self.path)
            q = parse_qs(url.query)
            get = lambda key, default=None: q.get(key, [default])[0]
            path = url.path
            if path == "/api/bootstrap":
                self._json({"token": self.server.token, "project": studio.store.get(), "projects": studio.store.list(),
                            "capabilities": studio.media.capabilities(), "agent": studio.agent.status(), "analysis": studio.analysis_config})
            elif path == "/api/project":
                self._json(studio.store.get())
            elif path == "/api/projects":
                self._json(studio.store.list())
            elif path == "/api/tasks":
                self._json(studio.tasks.list())
            elif path == "/api/task":
                self._json(studio.task_status(get("id", "")))
            elif path == "/api/solver/example":
                self._json(default_config(get("name", "river.json")))
            elif path == "/api/solver/result":
                self._json(studio.solver_result(get("id", "")))
            elif path == "/api/agent/status":
                self._json(studio.agent.status(get("provider")))
            elif path == "/api/agent/models":
                self._json(studio.agent.models(get("provider", "subscription")))
            elif path == "/api/agent/task":
                self._json(studio.agent.get(get("id", ""), int(get("after", "0"))))
            elif path == "/api/agent/sessions":
                self._json(studio.agent.list_sessions())
            elif path == "/api/thumbnail":
                asset = next(a for a in studio.store.get()["assets"] if a["id"] == get("id"))
                source = Path(asset["path"])
                stat = source.stat()
                t = max(0, min(float(get("time", "0")), max(0, asset["metadata"]["duration"] - 0.05)))
                fingerprint = hashlib.sha256(f"{source}:{stat.st_size}:{stat.st_mtime_ns}:{t:.3f}".encode()).hexdigest()
                thumb = studio.data_dir / "cache" / "thumbnails" / f"{fingerprint}.png"
                if not thumb.exists():
                    studio.media.extract_frame(source, t, thumb, width=320, height=180)
                self._file(thumb, "image/png")
            elif path in ("/api/frame", "/api/overlay"):
                p = studio.store.get()
                t = float(get("time", "0"))
                if not 0 <= t <= p["duration"]:
                    raise ValueError("预览时间超出项目范围")
                if get("revision") is not None and int(get("revision")) != p["revision"]:
                    raise ValueError("预览项目版本已更新，请刷新")
                # Cache identity includes project content revision and frame time.
                frame = studio.data_dir / "cache" / p["id"] / f"r{p['revision']}-{path.rsplit('/',1)[1]}-{t:.3f}.png"
                if not frame.exists():
                    frame.parent.mkdir(parents=True, exist_ok=True)
                    if path == "/api/overlay":
                        studio.media.overlay_frame(p, t, frame)
                    else:
                        studio.media.preview_frame(p, t, frame)
                self._file(frame, "image/png")
            elif path.startswith("/media/"):
                asset_id = path.rsplit("/", 1)[1]
                asset = next(a for a in studio.store.get()["assets"] if a["id"] == asset_id)
                proxy = asset.get("proxy_path")
                self._file(proxy if proxy and Path(proxy).is_file() else asset["path"])
            elif path.startswith("/exports/"):
                name = unquote(path.rsplit("/", 1)[1])
                if Path(name).name != name or not name.endswith(".mp4"):
                    raise PermissionError("无效导出文件")
                self._file(studio.data_dir / "exports" / name, "video/mp4", download=get("download") == "1")
            elif path == "/api/srt":
                from .subtitles import export_srt
                text = export_srt(studio.store.get()["subtitles"])
                data = text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", 'attachment; filename="pokerstudio.srt"')
                self.end_headers()
                self.wfile.write(data)
            elif path == "/" or path == "/analysis":
                data = (ROOT / "web/index.html").read_bytes().replace(b"__TOKEN__", self.server.token.encode())
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'")
                self.end_headers()
                self.wfile.write(data)
            elif path in ("/app.js", "/style.css"):
                self._file(ROOT / "web" / path[1:])
            else:
                raise FileNotFoundError("页面不存在")
        except Exception as exc:
            self._handle_error(exc)

    def do_POST(self):
        try:
            self._guard(mutate=True)
            studio = self.server.studio
            path = urlparse(self.path).path
            if path == "/api/assets/upload":
                project_id = self.headers.get("X-Project-Id") or studio.store.get()["id"]
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 200 * 1024**3:
                    raise ValueError("上传文件为空或超过200GiB；大文件可用本地路径导入")
                name = Path(unquote(self.headers.get("X-Filename", "media.mp4"))).name
                name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:160]
                target = studio.data_dir / "imported" / f"{uid()}-{name}"
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as f:
                    remaining = length
                    while remaining:
                        block = self.rfile.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ValueError("上传中断，素材未导入")
                        f.write(block)
                        remaining -= len(block)
                self._json(studio.import_asset(target, project_id=project_id))
                return
            data = self._body()
            if path == "/api/project/new":
                result = studio.store.create(data.get("name", "未命名扑克剪辑"))
            elif path == "/api/shutdown":
                self._json({"status": "stopping"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            elif path == "/api/project/open":
                result = studio.store.open(data["path"])
            elif path == "/api/project/save":
                result = studio.store.save(data.get("path"))
            elif path == "/api/project/playhead":
                result = studio.store.set_playhead(data["time"], project_id=data.get("project_id"))
            elif path == "/api/project/edit":
                result = studio.edit(data["command"], expected_revision=data.get("revision"), project_id=data.get("project_id"))
            elif path == "/api/project/undo":
                result = studio.undo(project_id=data.get("project_id"))
            elif path == "/api/project/redo":
                result = studio.undo(project_id=data.get("project_id"), redo=True)
            elif path == "/api/assets/import":
                result = studio.import_asset(data["path"], asset_id=data.get("asset_id"), project_id=data.get("project_id"))
            elif path == "/api/demo":
                target = studio.data_dir / "demo" / ("TEST-" + uid()[:8] + ".mp4")
                project_id = studio.store.get()["id"]
                def worker(task):
                    studio.media.create_demo_media(target, task=task)
                    if task.cancel_event.is_set():
                        raise RuntimeError("测试素材任务已请求取消，未导入项目")
                    if studio.store.get()["id"] != project_id:
                        raise ValueError("项目已切换；测试素材保留在磁盘，未导入另一项目")
                    return studio.import_asset(target, project_id=project_id)
                result = studio.tasks.create("demo", worker)
            elif path == "/api/export":
                result = studio.export()
            elif path == "/api/task/cancel":
                result = studio.cancel_task(data["id"])
            elif path == "/api/subtitles/import":
                from .subtitles import parse_srt
                result = studio.edit({"op": "replace_subtitles", "subtitles": parse_srt(data["text"])})
            elif path == "/api/transcribe":
                asset = next(a for a in studio.store.get()["assets"] if a["id"] == data["asset_id"])
                result = studio.tasks.create("transcribe", lambda task: studio.media.transcribe_local(asset["path"], data.get("model_path"), task))
            elif path == "/api/proxy":
                asset = next(a for a in studio.store.get()["assets"] if a["id"] == data["asset_id"])
                project_id = studio.store.get()["id"]
                output = studio.data_dir / "cache" / "proxies" / f"{asset['id']}.mp4"
                def proxy_worker(task):
                    result = studio.media.create_proxy(asset["path"], output, task)
                    if not task.cancel_event.is_set():
                        studio.store.edit({"op": "attach_proxy", "id": asset["id"], "source_path": asset["path"], "path": str(output)},
                                          project_id=project_id, source="proxy")
                        studio.store.save()
                    return result
                result = studio.tasks.create("proxy", proxy_worker)
            elif path == "/api/analysis/config":
                result = studio.set_analysis(data["config"])
            elif path == "/api/solver/start":
                result = studio.solve(config=data.get("config"), options=data.get("options"), entry=data.get("entry", "studio"), project_id=data.get("project_id"))
            elif path == "/api/solver/node":
                result = studio.solver.inspect(data["id"].removeprefix("solve:"), data.get("path", []), data.get("variant", "response"))
                result["task_id"] = "solve:" + result["id"]
            elif path == "/api/agent/configure-subscription":
                result = studio.agent.configure_subscription(data["mode"])
            elif path == "/api/agent/login":
                result = studio.agent.login("subscription", data.get("mode"))
            elif path == "/api/agent/cancel-login":
                result = studio.agent.cancel_login(data.get("login_id"))
            elif path == "/api/agent/logout":
                result = studio.agent.logout()
            elif path == "/api/agent/configure-api":
                result = studio.agent.configure_api(data["api_key"], data.get("model"), data.get("allow_paid", False))
            elif path == "/api/agent/start":
                context = {"entry": data.get("entry", "studio")}
                if context["entry"] == "studio":
                    context["project_id"] = studio.store.get()["id"]
                elif context["entry"] != "analysis":
                    raise ValueError("未知会话入口")
                result = studio.agent.start(data["message"], data.get("provider", "subscription"), data.get("model"), data.get("session_id"), context)
            elif path == "/api/agent/cancel":
                result = studio.agent.cancel(data["id"])
            else:
                raise FileNotFoundError("接口不存在")
            self._json(result)
        except Exception as exc:
            self._handle_error(exc)


def main():
    parser = argparse.ArgumentParser(description="Pokerstudio 本地剪辑与分析工作台")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".data")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口须为1024–65535")
    studio = None
    try:
        studio = Studio(args.data_dir)
        server = LocalServer(("127.0.0.1", args.port), studio)
        print(f"Pokerstudio: http://127.0.0.1:{args.port}", flush=True)
        print(f"项目/缓存/导出: {args.data_dir.resolve()}", flush=True)
        print("按 Ctrl+C 停止；导出和求解任务会取消并回收进程。", flush=True)
        server.serve_forever(poll_interval=0.25)
    except OSError as exc:
        print(f"无法启动：{exc}。若端口被占用，使用 --port 8771。", file=sys.stderr)
        return 1
    except (ImportError, RuntimeError, ValueError) as exc:
        print(f"无法启动：{exc}。依赖请安装 python -m pip install -r pokerstudio/requirements.txt；媒体能力见 pokerstudio/docs/MEDIA.md。", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        if studio:
            studio.close()
        if "server" in locals():
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
