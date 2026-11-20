"""Windows desktop entry points with hidden, reusable loopback services."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

import psutil

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "pokerstudio" / ".data" / "desktop"


@dataclass(frozen=True)
class App:
    key: str
    name: str
    port: int
    title: str


APPS = {
    "pokerstudio": App("pokerstudio", "Pokerstudio", 8770, "Pokerstudio · 扑克视频工作台"),
    "pokerlab": App("pokerlab", "Pokerlab Solver", 8765, "PokerLab · 翻后研究"),
}


class DesktopError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def service_ready(app: App, port: int) -> bool:
    """Only reuse this app's page; a listener or a redirect isn't readiness."""
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(f"http://127.0.0.1:{port}/", timeout=1.5) as response:
            page = response.read(256 * 1024).decode("utf-8", errors="replace")
            if f"<title>{app.title}</title>" not in page or 'name="local-token"' not in page:
                raise DesktopError(f"端口 {port} 已被其他应用占用，无法启动 {app.name}。")
            return True
    except HTTPError as exc:
        raise DesktopError(f"端口 {port} 返回 HTTP {exc.code}，不是可用的 {app.name} 服务。") from exc
    except (URLError, TimeoutError, ConnectionError, OSError):
        # A service may be in the middle of starting. The startup loop checks
        # child exit, exclusive binding and the same identity before opening UI.
        return False


@contextmanager
def startup_lock(path: Path, timeout=40):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise DesktopError("另一个启动操作尚未完成，请稍后重新打开。")
                time.sleep(0.1)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def find_browser() -> Path:
    candidates = []
    if os.name == "nt":
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for name in ("msedge.exe", "chrome.exe"):
                try:
                    with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}") as key:
                        candidates.append(Path(winreg.QueryValue(key, None).strip('"')))
                except OSError:
                    pass
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.extend(Path(base) / suffix for suffix in (
                "Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"))
    for path in candidates:
        if path.is_file():
            return path
    raise DesktopError("未找到 Microsoft Edge 或 Chrome。请安装其中一个后重新打开。")


def python_windowless() -> Path:
    current = Path(sys.executable)
    alternative = current.with_name("pythonw.exe")
    return alternative if os.name == "nt" and alternative.is_file() else current


def paths(app: App, port: int, state: Path = STATE):
    stem = f"{app.key}-{port}"
    return state / "runtime" / f"{stem}.json", state / "runtime" / f"{stem}.stop.json"


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def owned_process(record):
    """PID reuse or an unrelated interpreter must never receive a stop request."""
    try:
        process = psutil.Process(record["pid"])
        if abs(process.create_time() - record["started"]) > 0.01:
            return None
        command = process.cmdline()
        if "pokerstudio.desktop" not in command or "--serve" not in command:
            return None
        index = command.index("--app")
        if command[index + 1] != record["app"]:
            return None
        return process
    except (KeyError, ValueError, IndexError, TypeError, psutil.Error):
        return None


def ensure_service(app: App, port: int, state: Path = STATE, data_dir: Path | None = None):
    state.mkdir(parents=True, exist_ok=True)
    with startup_lock(state / "runtime" / f"{app.key}-{port}.lock"):
        if service_ready(app, port):
            if data_dir is not None:
                record_path, _ = paths(app, port, state)
                try:
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    same_data = Path(record["data_dir"]).resolve() == data_dir.resolve()
                    if not same_data or owned_process(record) is None:
                        raise ValueError("data directory mismatch")
                except (OSError, ValueError, KeyError, TypeError):
                    raise DesktopError(f"端口 {port} 的现有服务不能确认使用指定数据目录。请换一个未占用端口，避免打开其他项目。")
            return "reused"
        log_path = state / "logs" / f"{app.key}-{port}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [str(python_windowless()), "-X", "utf8", "-m", "pokerstudio.desktop",
                   "--serve", "--app", app.key, "--port", str(port), "--state-dir", str(state)]
        if data_dir is not None:
            command.extend(["--data-dir", str(data_dir)])
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        with log_path.open("ab", buffering=0) as log:
            log.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Start {app.name}\n".encode())
            child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if child.poll() is not None:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                raise DesktopError(f"{app.name} 服务启动失败（退出码 {child.returncode}）。\n\n{tail}\n\n日志：{log_path}")
            if service_ready(app, port):
                return "started"
            time.sleep(0.2)
        raise DesktopError(f"{app.name} 30 秒内尚未启动完成。请查看日志后再试：\n{log_path}")


def open_window(app: App, port: int, browser: Path, state: Path = STATE):
    profile = state / "profiles" / app.key
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([str(browser), f"--app=http://127.0.0.1:{port}/", f"--user-data-dir={profile}",
                      "--no-first-run", "--no-default-browser-check", "--window-size=1440,960"],
                     cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_service(app: App, port: int, state: Path = STATE):
    with startup_lock(state / "runtime" / f"{app.key}-{port}.lock"):
        record_path, stop_path = paths(app, port, state)
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise DesktopError("没有找到桌面启动器所属的服务。手动启动的服务请在原终端按 Ctrl+C 关闭。")
        process = owned_process(record)
        if process is None:
            raise DesktopError("记录的服务已退出或进程身份已改变；没有停止任何其他进程。")
        write_json(stop_path, {"token": record["token"]})
        try:
            process.wait(timeout=45)
        except psutil.TimeoutExpired as exc:
            raise DesktopError("正在等待任务取消和进程回收，暂未完成关闭。请查看服务日志；没有强制终止进程。") from exc


def serve(app: App, port: int, state: Path = STATE, data_dir: Path | None = None):
    server = studio = None
    record_path, stop_path = paths(app, port, state)
    token = secrets.token_urlsafe(32)
    finished = threading.Event()
    try:
        if app.key == "pokerstudio":
            from .server import LocalServer
            from .tools import Studio
            studio = Studio(data_dir or ROOT / "pokerstudio" / ".data")
            server = LocalServer(("127.0.0.1", port), studio)
        else:
            from http.server import ThreadingHTTPServer
            from pokerlab.solver.server import make_server

            class ExclusiveServer(ThreadingHTTPServer):
                allow_reuse_address = os.name != "nt"

                def server_bind(self):
                    if os.name == "nt":
                        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    super().server_bind()

            server = make_server(port, server_class=ExclusiveServer, agent_dir=data_dir)
        write_json(record_path, {"pid": os.getpid(), "started": psutil.Process().create_time(),
                                 "app": app.key, "port": port, "token": token,
                                 "data_dir": str((data_dir or (ROOT / "pokerstudio" / ".data" if studio
                                                             else ROOT / "outputs" / "agent")).resolve())})

        def monitor():
            while not finished.wait(0.25):
                try:
                    request = json.loads(stop_path.read_text(encoding="utf-8"))
                    if isinstance(request, dict) and secrets.compare_digest(request.get("token", ""), token):
                        server.shutdown()
                        return
                except (OSError, ValueError, TypeError):
                    pass

        threading.Thread(target=monitor, name="desktop-stop", daemon=True).start()
        print(f"{app.name} ready on 127.0.0.1:{port}", flush=True)
        server.serve_forever(poll_interval=0.25)
    finally:
        finished.set()
        if studio is not None:
            studio.close()
        if server is not None:
            server.server_close()
            if app.key == "pokerlab":
                server.jobs.close()
        # Remove only our own ownership record, even after a startup failure.
        try:
            if json.loads(record_path.read_text(encoding="utf-8")).get("token") == token:
                record_path.unlink(missing_ok=True)
                stop_path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pokerstudio / Pokerlab 桌面启动器")
    parser.add_argument("--app", choices=APPS, required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--state-dir", type=Path, default=STATE)
    parser.add_argument("--data-dir", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    group.add_argument("--stop", action="store_true", help="取消任务并正常关闭启动器所属的后台服务")
    group.add_argument("--no-open", action="store_true", help="只启动服务，不打开窗口（诊断用）")
    args = parser.parse_args(argv)
    app = APPS[args.app]
    port = args.port if args.port is not None else app.port
    if not 1024 <= port <= 65535:
        parser.error("端口须为1024–65535")
    try:
        if args.serve:
            serve(app, port, args.state_dir, args.data_dir)
        elif args.stop:
            stop_service(app, port, args.state_dir)
        else:
            browser = None if args.no_open else find_browser()
            ensure_service(app, port, args.state_dir, args.data_dir)
            if browser:
                open_window(app, port, browser, args.state_dir)
        return 0
    except Exception as exc:
        args.state_dir.joinpath("logs").mkdir(parents=True, exist_ok=True)
        log = args.state_dir / "logs" / f"{app.key}-launcher.log"
        with log.open("a", encoding="utf-8") as handle:
            traceback.print_exc(file=handle)
        message = f"{exc}\n\n启动日志：{log}"
        if os.name == "nt" and not args.serve and Path(sys.executable).name.lower() == "pythonw.exe":
            ctypes.windll.user32.MessageBoxW(None, message, app.name, 0x10)
        elif sys.stderr is not None:
            print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
