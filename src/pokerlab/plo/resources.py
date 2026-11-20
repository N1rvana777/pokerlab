"""Run metadata: wall/CPU time, peak memory and a code fingerprint for reports."""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def code_fingerprint() -> str:
    """SHA-256 over the PLO package sources (the repository has no git history)."""
    digest = hashlib.sha256()
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        digest.update(path.relative_to(PACKAGE_DIR).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def peak_memory_mib() -> dict:
    """Peak resident memory of this process, as reported by the OS."""
    try:
        import psutil
        info = psutil.Process().memory_info()
        peak = getattr(info, "peak_wset", None)
        if peak is not None:
            return {"peak_mib": peak / 2**20, "source": "psutil peak working set (Windows)",
                    "current_rss_mib": info.rss / 2**20}
        try:
            import resource
            return {"peak_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                    "source": "getrusage ru_maxrss", "current_rss_mib": info.rss / 2**20}
        except ImportError:
            return {"peak_mib": None, "source": "unavailable", "current_rss_mib": info.rss / 2**20}
    except ImportError:
        return {"peak_mib": None, "source": "psutil not installed", "current_rss_mib": None}


class Meter:
    """Context manager measuring wall and CPU seconds."""

    def __enter__(self) -> "Meter":
        self.wall0 = time.perf_counter()
        self.cpu0 = time.process_time()
        return self

    def __exit__(self, *exc) -> None:
        self.wall = time.perf_counter() - self.wall0
        self.cpu = time.process_time() - self.cpu0

    def report(self) -> dict:
        return {"wall_s": round(self.wall, 3), "cpu_s": round(self.cpu, 3), **peak_memory_mib()}


def git_state() -> dict:
    """Commit of the working tree and whether solver code or only other files differ from it."""
    def run(*args):
        try:
            proc = subprocess.run(["git", *args], cwd=PACKAGE_DIR, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return proc.stdout if proc.returncode == 0 else None
    commit = run("rev-parse", "HEAD")
    if commit is None:
        return {"commit": None}
    commit = commit.strip()
    changed = [line[3:] for line in (run("status", "--porcelain") or "").splitlines() if line]
    return {"commit": commit, "dirty": bool(changed),
            "dirty_package_files": sorted(p for p in changed if p.startswith("src/pokerlab/plo/"))}


def environment() -> dict:
    return {"python": sys.version.split()[0], "platform": platform.platform(),
            "processor": platform.processor(), "cpu_count": os.cpu_count(),
            "code_fingerprint": code_fingerprint(), "git": git_state(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
