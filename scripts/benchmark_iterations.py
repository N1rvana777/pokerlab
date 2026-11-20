"""Cold, fixed-iteration diagnostics with the complete input tree and safety caps.

PowerShell example (run A and B serially, never in parallel):
  python -X utf8 scripts/benchmark_iterations.py outputs/performance-20261013-v2/config.json --iterations 30 --binary outputs/performance-20261015/baseline/pokerlab-solver

This is NOT precision acceptance or an opponent-model solve. The original target
is retained and measured, but the explicit diagnostic iteration count is the stop
condition. No baseline/checkpoint cache, final policy, model or BR is produced.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from pokerlab.solver.__main__ import ROOT
from pokerlab.solver.resources import memory_resources
from pokerlab.solver.workbench import engine_lock, fingerprint, new_job_dir


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def diagnostic_request(config, iterations, threads=None, check_every=None):
    if not isinstance(config, dict) or 'runtime' in config:
        raise ValueError('Source config must be an object without internal runtime fields')
    if type(iterations) is not int or not 1 <= iterations <= 100000:
        raise ValueError('iterations must be an explicit integer in 1..100000')
    if threads is not None and (type(threads) is not int or not 1 <= threads <= 64):
        raise ValueError('threads must be 1..64')
    request = copy.deepcopy(config)
    request.pop('memory_auto', None)
    request.pop('memory_stretch', None)
    request.pop('amount_unit', None)
    request['time_limit_seconds'] = 0
    if threads is not None:
        request['threads'] = threads
    request['runtime'] = {'benchmark_iterations': iterations}
    if check_every is not None:
        request['runtime']['benchmark_check_every'] = check_every
    return request


def guest_path(path):
    """Paths are argv values, never interpolated shell code."""
    raw = str(path)
    if sys.platform == 'win32' and raw.startswith('/'):
        # An explicit WSL-only location is resolved and hashed by the supervisor.
        return raw
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise ValueError(f'Native binary does not exist: {resolved}')
    if sys.platform == 'win32':
        if len(resolved.drive) != 2 or resolved.drive[1] != ':':
            raise ValueError('Native binary must use a local drive or an explicit WSL absolute path')
        return '/mnt/' + resolved.drive[0].lower() + resolved.as_posix()[2:]
    return str(resolved)


def worker_command(folder, binary):
    relative = folder.relative_to(ROOT).as_posix()
    worker = ['scripts/native_worker.py', relative, '--timeout', '0', '--binary', binary, '--diagnostics']
    if sys.platform == 'win32':
        root_posix = '/mnt/' + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
        return ['wsl', '-d', 'Ubuntu', '--cd', root_posix, '--', 'python3', *worker]
    return [sys.executable, *worker]


def parse_precision_samples(path):
    samples = []
    if path.exists():
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                event = json.loads(line)
                detail = event.get('detail', {})
                if event.get('phase') == 'baseline' and 'actual_chips' in detail:
                    samples.append(detail)
            except (ValueError, AttributeError, TypeError):
                continue
    return samples


def validate_result(result, iterations):
    if result.get('benchmark') is not True:
        raise RuntimeError('Executable did not return the fixed-iteration diagnostic protocol')
    precision = result.get('precision', {})
    if precision.get('stop_reason') != 'fixed_iteration_diagnostic' or precision.get('baseline_iterations') != iterations:
        raise RuntimeError('Executable did not complete the exact requested diagnostic iteration count')
    resources = result.get('worker_resources', {})
    if resources.get('exit_code') != 0 or not resources.get('process_reaped'):
        raise RuntimeError('Native exit/reap was not verified')


def run(config_path, iterations, binary, output=None, threads=None, check_every=None):
    raw = config_path.read_bytes()
    config = json.loads(raw.decode('utf-8-sig'))
    request = diagnostic_request(config, iterations, threads, check_every)
    binary = guest_path(binary)
    if output is None:
        folder = new_job_dir()
    else:
        folder = output.resolve()
        folder.relative_to((ROOT / 'outputs').resolve())
        folder.mkdir(parents=True, exist_ok=False)
    (folder / 'source-config.json').write_bytes(raw)
    manifest = {'kind': 'cold_fixed_iteration_diagnostic', 'config_path': str(config_path.resolve()),
                'source_file_sha256': hashlib.sha256(raw).hexdigest(), 'source_config_sha256': fingerprint(config),
                'binary_requested': binary, 'iterations_requested': iterations,
                'threads_override': threads, 'original_target': config.get('target'),
                'original_target_unit': config.get('target_unit'), 'wall_clock_timeout': None,
                'cache_policy': 'cold; no baseline/checkpoint load or save',
                'limitations': ['Fixed iterations, not full precision acceptance',
                               'No opponent model, Hero response, final policy snapshot or UI report',
                               'Live-thread context counts can fall when threads exit; use final child accounting for totals',
                               'Diagnostics use the existing dual memory budgets and process-group supervisor']}
    write_json(folder / 'manifest.json', manifest)
    print(str(folder), flush=True)
    started = time.perf_counter()
    summary = dict(manifest)
    result = None
    try:
        with engine_lock(folder):
            summary['queue_seconds'] = time.perf_counter() - started
            resources = memory_resources(config)
            write_json(folder / 'resources.json', resources)
            if not resources['ready']:
                raise RuntimeError(resources.get('error') or 'Resource budget is not ready')
            request['memory_budget_mb'] = resources['effective_mb']
            write_json(folder / 'request.json', request)
            command = worker_command(folder, binary)
            summary['worker_command'] = command
            launched = time.perf_counter()
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                out, err = process.communicate(json.dumps(request, allow_nan=False))
            except BaseException:
                # Ask the existing supervisor to kill and reap its native group.
                # Keep engine_lock until that supervisor exits. Killing only the
                # WSL wrapper cannot prove that the native group has been reaped.
                # These short waits are polling intervals, never a cleanup deadline.
                (folder / 'cancel').touch()
                while True:
                    try:
                        process.communicate(timeout=1)
                        break
                    except (subprocess.TimeoutExpired, KeyboardInterrupt):
                        # Repeated Ctrl-C must not release the serialization lock
                        # while the supervisor is still cleaning up its child.
                        continue
                raise
            finally:
                summary['supervised_wall_seconds'] = time.perf_counter() - launched
            (folder / 'supervisor.stderr').write_text(err, encoding='utf-8')
            if process.returncode:
                raise RuntimeError(err.replace('\x00', '').strip() or out.replace('\x00', '').strip()
                                   or f'Supervisor exited {process.returncode}')
            result = json.loads(out)
            write_json(folder / 'result.json', result)
            validate_result(result, iterations)
            summary.update(state='completed', tree=result.get('tree'), memory=result.get('memory'),
                           timing=result.get('timing'), precision=result.get('precision'))
    except BaseException as error:
        summary.update(state='cancelled' if isinstance(error, KeyboardInterrupt) else 'failed',
                       error=f'{type(error).__name__}: {error}')
    finally:
        summary['wall_seconds'] = time.perf_counter() - started
        summary['precision_samples'] = parse_precision_samples(folder / 'native.stderr')
        worker_file = folder / 'worker.json'
        if worker_file.exists():
            summary['worker_resources'] = json.loads(worker_file.read_text(encoding='utf-8'))
            summary['binary_sha256'] = summary['worker_resources'].get('binary_sha256')
        write_json(folder / 'benchmark-summary.json', summary)
        print(json.dumps(summary, ensure_ascii=True), flush=True)
    return 0 if summary['state'] == 'completed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--iterations', required=True, type=int)
    parser.add_argument('--binary', default=str(ROOT / 'target/release/pokerlab-solver'))
    parser.add_argument('--output', type=Path, help='New directory under workspace outputs; existing folders are rejected')
    parser.add_argument('--threads', type=int, help='Explicit resource-only override; omitted preserves source config')
    parser.add_argument('--check-every', type=int, help='Iterations between exploitability measurements (default 10)')
    args = parser.parse_args()
    return run(args.config, args.iterations, args.binary, args.output, args.threads, args.check_every)


if __name__ == '__main__':
    raise SystemExit(main())
