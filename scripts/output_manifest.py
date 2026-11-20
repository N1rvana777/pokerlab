"""Record paths, sizes and SHA-256 hashes of output files that stay outside Git.

Outputs are large and are not committed (``/outputs/`` is ignored).  Reports refer to them
by path; this manifest lets a later reader check that a file is the one a report used.

    python scripts/output_manifest.py outputs/plo outputs/jobs/<id> --summary outputs \
        --output manifests/outputs-YYYY-MM-DD.json

Every file under each hashed root gets {path, bytes, mtime, sha256}.  ``--summary`` adds a
per-directory size and file count for a larger tree without hashing it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

CHUNK = 8 * 2**20


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def git_head() -> dict:
    def run(*args):
        proc = subprocess.run(["git", *args], capture_output=True, text=True)
        return proc.stdout.strip() if proc.returncode == 0 else None
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain"))}


def summary(root: Path) -> list[dict]:
    rows = []
    for child in sorted(root.iterdir()):
        files = [child] if child.is_file() else [p for p in child.rglob("*") if p.is_file()]
        rows.append({"path": child.as_posix(), "files": len(files),
                     "bytes": sum(p.stat().st_size for p in files)})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", help="directories or files to hash")
    parser.add_argument("--summary", help="also list sizes and file counts under this directory")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    started = time.perf_counter()
    files = []
    for root in map(Path, args.roots):
        paths = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for path in paths:
            stat = path.stat()
            files.append({"path": path.as_posix(), "bytes": stat.st_size,
                          "mtime": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(stat.st_mtime)),
                          "sha256": sha256(path)})
    report = {"schema": "pokerlab.output-manifest/1", "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "git": git_head(), "hashed_roots": args.roots, "files": files,
              "hashed_bytes": sum(f["bytes"] for f in files),
              "seconds": round(time.perf_counter() - started, 1)}
    if args.summary:
        report["summary_root"] = args.summary
        report["summary"] = summary(Path(args.summary))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"{len(files)} files, {report['hashed_bytes'] / 2**30:.2f} GiB hashed in {report['seconds']} s -> {out}")


if __name__ == "__main__":
    main()
