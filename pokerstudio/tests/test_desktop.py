"""Desktop ownership and startup checks without operating either real service."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import threading

import psutil
import pytest

from pokerstudio import desktop


@contextmanager
def root_page(body, status=200, location=None):
    """Real loopback HTTP on an OS-selected temporary port; no app processes."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(self.path)
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield server.server_port, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def identity(app):
    return f'<html><head><title>{app.title}</title><meta name="local-token" content="test-only"></head></html>'


@pytest.mark.parametrize("app_key", ["pokerstudio", "pokerlab"])
def test_http_root_accepts_correct_app_identity(app_key):
    app = desktop.APPS[app_key]
    with root_page(identity(app)) as (port, requests):
        assert port not in (8770, 8765)
        assert desktop.service_ready(app, port) is True
        assert requests == ["/"]


@pytest.mark.parametrize("body", [
    '<title>Unrelated application</title><meta name="local-token">',
    '<title>Pokerstudio · 扑克视频工作台</title>',
])
def test_occupied_port_with_wrong_or_incomplete_identity_is_rejected(body):
    with root_page(body) as (port, requests):
        with pytest.raises(desktop.DesktopError, match="其他应用占用"):
            desktop.service_ready(desktop.APPS["pokerstudio"], port)
        assert requests == ["/"]


def test_redirect_is_rejected_without_requesting_target():
    # Even a redirect response containing the right HTML must not establish
    # readiness or cause the launcher to follow a different local/remote page.
    app = desktop.APPS["pokerstudio"]
    with root_page(identity(app), status=302, location="/would-be-followed") as (port, requests):
        with pytest.raises(desktop.DesktopError, match="HTTP 302"):
            desktop.service_ready(app, port)
        assert requests == ["/"]


def test_existing_correct_http_service_is_reused_without_starting_process(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Existing correct service must not launch a new process")

    monkeypatch.setattr(desktop.subprocess, "Popen", forbidden)
    app = desktop.APPS["pokerstudio"]
    with root_page(identity(app)) as (port, requests):
        assert desktop.ensure_service(app, port, state=tmp_path / "launcher") == "reused"
        assert requests == ["/"]
    assert not (tmp_path / "launcher/logs").exists()


def process_command(app="pokerstudio"):
    return ["pythonw.exe", "-m", "pokerstudio.desktop", "--serve", "--app", app, "--port", "9876"]


@pytest.mark.parametrize("started,command,accepted", [
    (100.0, process_command(), True),
    (101.0, process_command(), False),  # Same PID, new process creation time.
    (100.0, ["pythonw.exe", "unrelated.py", "--serve", "--app", "pokerstudio"], False),
    (100.0, ["pythonw.exe", "-m", "pokerstudio.desktop", "--app", "pokerstudio"], False),
    (100.0, process_command("pokerlab"), False),
    (100.0, ["pythonw.exe", "-m", "pokerstudio.desktop", "--serve", "--app"], False),
])
def test_owned_process_requires_creation_time_module_serve_flag_and_same_app(monkeypatch, started, command, accepted):
    class Process:
        def create_time(self):
            return started

        def cmdline(self):
            return command

    process = Process()

    def lookup(pid):
        assert pid == 12345
        return process

    monkeypatch.setattr(desktop.psutil, "Process", lookup)
    record = {"pid": 12345, "started": 100.0, "app": "pokerstudio"}
    assert desktop.owned_process(record) is (process if accepted else None)


def test_inaccessible_process_is_not_considered_owned(monkeypatch):
    def denied(pid):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(desktop.psutil, "Process", denied)
    assert desktop.owned_process({"pid": 12345, "started": 100.0, "app": "pokerstudio"}) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows windowless startup behavior")
def test_windows_startup_uses_pythonw_and_no_console_with_isolated_arguments(tmp_path, monkeypatch):
    python = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    python.write_bytes(b"test fixture; never executed")
    pythonw.write_bytes(b"test fixture; never executed")
    monkeypatch.setattr(desktop.sys, "executable", str(python))
    assert desktop.python_windowless() == pythonw

    readiness = iter([False, True])
    monkeypatch.setattr(desktop, "service_ready", lambda app, port: next(readiness))
    calls = []

    class Child:
        returncode = None

        def poll(self):
            return None

    def start(command, **kwargs):
        calls.append((command, kwargs))
        return Child()

    monkeypatch.setattr(desktop.subprocess, "Popen", start)
    state, data = tmp_path / "launcher", tmp_path / "project data"
    assert desktop.ensure_service(desktop.APPS["pokerstudio"], 9876, state, data) == "started"
    assert len(calls) == 1
    command, options = calls[0]
    assert command[0] == str(pythonw)
    assert command[command.index("-m") + 1] == "pokerstudio.desktop"
    assert "--serve" in command
    assert command[command.index("--app") + 1] == "pokerstudio"
    assert command[command.index("--port") + 1] == "9876"
    assert command[command.index("--state-dir") + 1] == str(state)
    assert command[command.index("--data-dir") + 1] == str(data)
    assert options["creationflags"] & desktop.subprocess.CREATE_NO_WINDOW
    assert options["stdin"] == desktop.subprocess.DEVNULL
    assert options["cwd"] == desktop.ROOT
    assert options["env"]["PYTHONIOENCODING"] == "utf-8"
    assert options["stdout"] is options["stderr"]


def test_startup_lock_prevents_competing_start_and_releases_after_error(tmp_path):
    path = tmp_path / "desktop.lock"
    with pytest.raises(RuntimeError, match="test failure"):
        with desktop.startup_lock(path):
            with pytest.raises(desktop.DesktopError, match="另一个启动操作"):
                with desktop.startup_lock(path, timeout=0):
                    pytest.fail("A competing handle acquired the active startup lock")
            raise RuntimeError("test failure")
    # Exception unwinding releases the lock; subsequent launches can proceed.
    with desktop.startup_lock(path, timeout=0):
        assert path.is_file()


@pytest.mark.parametrize('app_key', ['pokerlab', 'pokerstudio'])
def test_owned_service_reuses_explicit_data_directory(tmp_path, monkeypatch, app_key):
    app = desktop.APPS[app_key]
    state, data = tmp_path/'launcher', tmp_path/'isolated agent'
    record, _ = desktop.paths(app, 9876, state)
    desktop.write_json(record, {'data_dir': str(data.resolve())})
    monkeypatch.setattr(desktop, 'service_ready', lambda *args: True)
    monkeypatch.setattr(desktop, 'owned_process', lambda value: object())
    assert desktop.ensure_service(app, 9876, state, data) == 'reused'
    with pytest.raises(desktop.DesktopError, match='指定数据目录'):
        desktop.ensure_service(app, 9876, state, tmp_path/'other agent')
