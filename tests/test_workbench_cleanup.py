"""Cancellation retains ownership until the supervisor has reaped its child."""
from contextlib import contextmanager
import json
import subprocess
import sys
import time

import psutil
import pytest

from pokerlab.solver import workbench


@pytest.mark.parametrize('first_error', [KeyboardInterrupt(),
                                       subprocess.TimeoutExpired('explicit diagnostic', 35),
                                       ValueError('request encoding failure')])
@pytest.mark.parametrize('cleanup_delays', [[], ['timeout'] * 12,
                                          ['interrupt', 'timeout', 'interrupt']])
def test_cleanup_keeps_lock_past_ten_seconds_and_preserves_original_error(
        tmp_path, monkeypatch, first_error, cleanup_delays):
    folder = tmp_path / 'job'
    folder.mkdir()
    monkeypatch.setattr(workbench, 'ROOT', tmp_path)
    ownership = {'locked': False, 'native_reaped': False}
    calls = []

    @contextmanager
    def lock(_folder):
        ownership['locked'] = True
        try:
            yield
        finally:
            assert ownership['native_reaped'], 'unlocked before native cleanup completed'
            ownership['locked'] = False

    class Process:
        def kill(self):
            pytest.fail('must not kill only the supervisor/WSL client')

        def communicate(self, value=None, **kwargs):
            assert ownership['locked']
            calls.append(kwargs)
            if len(calls) == 1:
                assert kwargs == {'timeout': None}
                assert json.loads(value)['memory_budget_mb'] == 1024
                raise first_error
            assert (folder / 'cancel').exists()
            assert kwargs == {'timeout': 1}
            index = len(calls) - 2
            if index < len(cleanup_delays):
                if cleanup_delays[index] == 'interrupt':
                    raise KeyboardInterrupt
                raise subprocess.TimeoutExpired('supervisor cleanup', 1)
            ownership['native_reaped'] = True
            return '', ''

    monkeypatch.setattr(workbench, 'engine_lock', lock)
    monkeypatch.setattr(workbench, 'memory_resources', lambda _: {'ready': True, 'effective_mb': 1024})

    def launch(command, **kwargs):
        assert command[command.index('--timeout') + 1] == '0'
        return Process()

    monkeypatch.setattr(workbench.subprocess, 'Popen', launch)
    with pytest.raises(type(first_error)) as caught:
        workbench.execute({'time_limit_seconds': 600}, folder)
    assert caught.value is first_error
    assert ownership == {'locked': False, 'native_reaped': True}
    assert len(calls) == len(cleanup_delays) + 2


def test_interrupt_waits_for_real_supervisor_child_reap(tmp_path, monkeypatch):
    """Only tiny Python fixtures run; neither WSL nor the native solver launches."""
    folder = tmp_path / 'job'
    folder.mkdir()
    monkeypatch.setattr(workbench, 'ROOT', tmp_path)
    monkeypatch.setattr(workbench, 'memory_resources', lambda _: {'ready': True, 'effective_mb': 1024})
    real_popen = subprocess.Popen
    running = []
    locked = False
    supervisor = """
import json, subprocess, sys, time
from pathlib import Path
folder = Path(sys.argv[1])
json.load(sys.stdin)
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
(folder/'started.json').write_text(json.dumps({'child_pid': child.pid}))
try:
    while not (folder/'cancel').exists():
        time.sleep(.01)
finally:
    child.terminate()
    child.wait()
    (folder/'worker.json').write_text(json.dumps({'process_reaped': True}))
"""

    @contextmanager
    def lock(_folder):
        nonlocal locked
        locked = True
        try:
            yield
        finally:
            assert json.loads((folder / 'worker.json').read_text())['process_reaped']
            child_pid = json.loads((folder / 'started.json').read_text())['child_pid']
            assert not psutil.pid_exists(child_pid)
            assert running[0].poll() == 0
            locked = False

    class InterruptOnce:
        def __init__(self, proc):
            self.proc = proc
            self.first = True

        def communicate(self, value=None, **kwargs):
            assert locked
            if self.first:
                self.first = False
                self.proc.stdin.write(value)
                self.proc.stdin.close()
                self.proc.stdin = None
                deadline = time.monotonic() + 5
                while not (folder / 'started.json').exists():
                    assert time.monotonic() < deadline, 'fixture supervisor failed to start'
                    time.sleep(.01)
                raise KeyboardInterrupt
            return self.proc.communicate(**kwargs)

        def kill(self):
            pytest.fail('must allow supervisor to reap its child')

    def launch(_command, **kwargs):
        proc = real_popen([sys.executable, '-c', supervisor, str(folder)], **kwargs)
        running.append(proc)
        return InterruptOnce(proc)

    monkeypatch.setattr(workbench, 'engine_lock', lock)
    monkeypatch.setattr(workbench.subprocess, 'Popen', launch)
    try:
        with pytest.raises(KeyboardInterrupt):
            workbench.execute({}, folder)
        assert not locked
    finally:
        # Fixture-only fallback keeps a failed regression test from leaking a
        # helper. This is not the production cancellation implementation.
        (folder / 'cancel').touch()
        for proc in running:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
