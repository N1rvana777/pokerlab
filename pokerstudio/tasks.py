"""Small cancellable background jobs. A cancellation request is never success."""
from __future__ import annotations

from collections import deque
import copy
import threading
import time
import uuid


class TaskCancelled(RuntimeError):
    pass


class Task:
    def __init__(self, kind):
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.cancel_event = threading.Event()
        self.lock = threading.RLock()
        self.status = "queued"
        self.progress = 0.0
        self.result = None
        self.error = None
        self.created_at = time.time()
        self.started_at = self.finished_at = None
        self.logs = deque(maxlen=60)
        self.thread = None

    def check_cancelled(self):
        if self.cancel_event.is_set():
            raise TaskCancelled("任务已取消")

    def set_progress(self, value, message=None):
        with self.lock:
            self.progress = max(self.progress, min(0.999, max(0.0, float(value))))
            if message:
                self.logs.append(str(message)[:2000])

    def snapshot(self):
        with self.lock:
            return {"id": self.id, "task_id": "media:" + self.id, "kind": self.kind,
                    "status": self.status, "progress": self.progress,
                    "result": copy.deepcopy(self.result), "error": self.error,
                    "cancel_requested": self.cancel_event.is_set(), "logs": list(self.logs),
                    "created_at": self.created_at, "started_at": self.started_at,
                    "finished_at": self.finished_at}


class TaskManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.jobs = {}
        self.closed = False
        # Local encoding jobs are serial: importing large projects cannot launch
        # an arbitrary number of simultaneous FFmpeg encoders.
        self.slot = threading.Semaphore(1)

    def create(self, kind, worker):
        with self.lock:
            if self.closed:
                raise RuntimeError("任务管理器已关闭")
            task = Task(kind)
            self.jobs[task.id] = task
        def run():
            try:
                while not self.slot.acquire(timeout=0.1):
                    task.check_cancelled()
                try:
                    task.check_cancelled()
                    with task.lock:
                        task.status, task.started_at = "running", time.time()
                    result = worker(task)
                    task.check_cancelled()
                    with task.lock:
                        task.result, task.progress, task.status = result, 1.0, "completed"
                finally:
                    self.slot.release()
            except TaskCancelled as exc:
                with task.lock:
                    task.status, task.error = "cancelled", str(exc)
            except Exception as exc:
                with task.lock:
                    task.status = "cancelled" if task.cancel_event.is_set() else "failed"
                    task.error = f"{type(exc).__name__}: {exc}"[:12000]
            finally:
                task.finished_at = time.time()
        task.thread = threading.Thread(target=run, name="studio-" + kind + "-" + task.id[:6], daemon=True)
        task.thread.start()
        return task.snapshot()

    def _task(self, task_id):
        with self.lock:
            return self.jobs[task_id.removeprefix("media:")]

    def get(self, task_id):
        return self._task(task_id).snapshot()

    def list(self):
        with self.lock:
            return [x.snapshot() for x in reversed(list(self.jobs.values()))][:200]

    def cancel(self, task_id):
        task = self._task(task_id)
        with task.lock:
            if task.status not in ("completed", "failed", "cancelled"):
                task.cancel_event.set()
        return task.snapshot()

    def shutdown(self):
        with self.lock:
            self.closed = True
            jobs = list(self.jobs.values())
        for task in jobs:
            if task.status not in ("completed", "failed", "cancelled"):
                task.cancel_event.set()
        deadline = time.monotonic() + 15
        for task in jobs:
            if task.thread:
                task.thread.join(max(0, deadline - time.monotonic()))
