"""JSON CLI for the native CPU engine (Windows native binary or existing WSL)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
REV = "9d1509fe5077d019825f833eed04b16d342dfda1"


def engine_command() -> list[str]:
    native = ROOT / "target/release/pokerlab-solver.exe"
    if sys.platform == "win32" and native.exists():
        return [str(native)]
    if sys.platform == "win32":
        posix_root = "/mnt/" + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
        return ["wsl", "-d", "Ubuntu", "--cd", posix_root, "--", "./target/release/pokerlab-solver"]
    return [str(ROOT / "target/release/pokerlab-solver")]


def solve(config: dict, timeout: int | None = None) -> dict:
    """Run a bounded supervised process. CLI alone does not enable baseline caching."""
    config = json.loads(json.dumps(config, allow_nan=False))
    checkout = subprocess.run(["git", "-C", str(ROOT/"third_party/postflop-solver"), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    if checkout != REV:
        raise RuntimeError("candidate revision drift: rebuild using the pinned source")
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False)
    from .workbench import execute
    report = execute(config,timeout=timeout)
    report["config_sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
    report["created_at"] = datetime.now(timezone.utc).isoformat()
    report["persistence"] = "result_and_config_only_not_resume_state"
    return report


def save_result(path: Path, result: dict) -> None:
    """Atomically replace a result; a crash never leaves a partial JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
            name = f.name
            json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def main() -> None:
    parser = argparse.ArgumentParser(description="PokerLab 原生翻后求解 CLI（阶段 0）")
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.output and args.output.exists():
            raise ValueError("output exists; choose a new filename to preserve previous work")
        result = solve(json.loads(args.scenario.read_text(encoding="utf-8-sig")))
        if args.output:
            if args.output.exists():
                raise ValueError("output appeared while solving; choose a new filename")
            save_result(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error)+"\n")


if __name__ == "__main__":
    main()
