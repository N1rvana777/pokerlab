"""Run a complete supervised solve, optionally without shared cache reuse.

--cold creates baseline/checkpoint/model/response artifacts in a fresh directory.
Existing output directories are rejected; the input file is unchanged. The
default remains the historical cached workbench solve. There is no wall-clock
cutoff unless --timeout is explicitly supplied.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

from pokerlab.solver.__main__ import ROOT, save_result
from pokerlab.solver.workbench import (
    VERSION, baseline_key, cfr_key, execute, fingerprint, new_job_dir, solve_cached,
)


def prepare_config(source, threads=None):
    if not isinstance(source, dict) or 'runtime' in source:
        raise ValueError('Source config must be an object without internal runtime fields')
    if threads is not None and (type(threads) is not int or not 1 <= threads <= 16):
        raise ValueError('threads must be 1..16')
    config = copy.deepcopy(source)
    # Historical resource defaults, preserving an explicit input thread count.
    config.update(compression=True, auto_suits=True, memory_budget_mb=24576,
                  threads=threads if threads is not None else source.get('threads', 8),
                  time_limit_seconds=0)
    return config


def config_changes(before, after):
    return {key: {'source': before.get(key), 'effective': after.get(key)}
            for key in sorted(before.keys() | after.keys())
            if key not in before or key not in after or before[key] != after[key]}


def binary_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def precision_samples(path):
    samples = []
    if path.exists():
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                event = json.loads(line)
                detail = event.get('detail', {})
                if event.get('phase') == 'baseline' and 'actual_chips' in detail:
                    samples.append(detail)
            except (ValueError, TypeError, AttributeError):
                continue
    return samples


def cold_solve(config, folder, timeout=None):
    """Workbench artifact metadata with exclusively fresh policy/state paths.

    execute owns the engine lock, dual resource budget and process supervisor.
    Do not acquire a nested engine lock here.
    """
    key = baseline_key(config)
    model_key = fingerprint({'config': config, 'version': VERSION})
    relative = folder.relative_to(ROOT).as_posix()
    baseline = relative + '/baseline.policy'
    checkpoint = relative + '/checkpoint.cfr'
    prefix = relative + '/policy'
    for artifact in (baseline, checkpoint, prefix + '.model.policy', prefix + '.response.policy'):
        if (ROOT / artifact).exists():
            raise ValueError('Cold solve refuses existing policy/checkpoint artifacts')
    request = copy.deepcopy(config)
    request['runtime'] = {'baseline_file': baseline, 'baseline_key': key,
                          'checkpoint_file': checkpoint, 'checkpoint_key': cfr_key(config),
                          'output_prefix': prefix, 'inspect_key': model_key}
    save_result(folder / 'request.json', request)
    started = time.perf_counter()
    result = execute(request, folder, timeout)
    # Retain the native echo, including actual guest budget, before decorating.
    save_result(folder / 'native-config.json', result.get('config'))
    cache = result.get('cache', {})
    if cache.get('baseline_hit') is not False or cache.get('resumed_iterations') != 0:
        raise RuntimeError('Cold solve did not prove zero baseline/checkpoint reuse')
    result['config'] = config
    result['config_sha256'] = fingerprint(config)
    result['artifacts'] = {'baseline': baseline, 'model': prefix + '.model.policy',
                           'response': prefix + '.response.policy',
                           'baseline_key': key, 'model_key': model_key}
    if config['mode'] == 'equilibrium':
        result['artifacts'].update(model=baseline, response=baseline, model_key=key)
    for variant in ('baseline', 'model', 'response'):
        artifact = ROOT / result['artifacts'][variant]
        if not artifact.is_file() or artifact.stat().st_size == 0:
            raise RuntimeError(f'Native solve did not save the {variant} policy artifact')
    result['persistence'] = 'full_final_policy_snapshots_not_CFR_resume_state'
    result['wall_seconds'] = time.perf_counter() - started
    result['created_at'] = time.time()
    save_result(folder / 'result.json', result)
    return result


def baseline_precision(result, config):
    """Never label fixed-opponent response gap as equilibrium accuracy."""
    precision = result.get('precision', {})
    actual = precision.get('baseline_exploitability_chips')
    target = precision.get('target_chips')
    return {'metric': 'equilibrium_exploitability', 'actual_chips': actual,
            'actual_pot_pct': actual * 100 / config['pot'] if actual is not None else None,
            'target': config.get('target'), 'target_unit': config.get('target_unit'),
            'target_chips': target,
            'target_met': actual <= target if actual is not None and target is not None else None,
            'iterations': precision.get('baseline_iterations'),
            'stop_reason': precision.get('baseline_stop_reason')}


def memory_summary(result, worker):
    memory = (result or {}).get('memory', {})
    rss = [value for value in (memory.get('measured_native_peak_rss_bytes'),
                               worker.get('sampled_peak_rss_bytes'),
                               worker.get('final_native_usage', {}).get('max_rss_bytes'))
           if type(value) is int]
    vms = [value for value in (memory.get('measured_native_peak_vms_bytes'),
                               worker.get('sampled_peak_vms_bytes')) if type(value) is int]
    return {'native_peak_rss_bytes': max(rss) if rss else None,
            'native_peak_vms_bytes': max(vms) if vms else None,
            'sampled_native_peak_swap_bytes': worker.get('sampled_peak_swap_bytes'),
            'process_reaped': worker.get('process_reaped'), 'exit_code': worker.get('exit_code')}


def run(config_path, *, cold=False, output=None, threads=None, timeout=0):
    if type(timeout) is not int or timeout < 0:
        raise ValueError('timeout must be zero (unlimited) or an explicit positive number of seconds')
    config_path = Path(config_path)
    raw = config_path.read_bytes()
    source = json.loads(raw.decode('utf-8-sig'))
    config = prepare_config(source, threads)
    if output is None:
        folder = new_job_dir()
    else:
        folder = Path(output).resolve()
        folder.relative_to((ROOT / 'outputs').resolve())
        folder.mkdir(parents=True, exist_ok=False)
    (folder / 'source-config.json').write_bytes(raw)
    save_result(folder / 'config.json', config)
    binary = ROOT / 'target/release/pokerlab-solver'
    manifest = {'kind': 'cold_complete_solve' if cold else 'cached_complete_solve',
                'config_path': str(config_path.resolve()),
                'source_file_sha256': hashlib.sha256(raw).hexdigest(),
                'source_config_sha256': fingerprint(source),
                'effective_config_sha256': fingerprint(config),
                'config_changes': config_changes(source, config),
                'binary_path': str(binary), 'threads_override': threads,
                'wall_clock_timeout': timeout or None,
                'cache_policy': 'fresh local baseline/checkpoint only; no shared cache read or write'
                                if cold else 'existing workbench shared baseline/checkpoint cache',
                'binary_hash_scope': 'disk snapshots before and after execute; not an atomic hash of the running image',
                'memory_scope': 'native process RSS/VmPeak; sampled native swap, not whole-system memory'}
    save_result(folder / 'manifest.json', manifest)
    print(str(folder), flush=True)
    started = time.perf_counter()
    summary = dict(manifest)
    result = None
    try:
        summary['binary_sha256_before'] = binary_digest(binary)
        save_result(folder / 'manifest.json', summary)
        result = (cold_solve if cold else solve_cached)(config, folder, timeout=timeout or None)
        worker = result.get('worker_resources', {})
        if worker.get('exit_code') != 0 or worker.get('process_reaped') is not True:
            raise RuntimeError('Native exit/reap was not verified')
        summary.update({key: result[key] for key in (
            'tree', 'precision', 'timing', 'memory', 'ev', 'policy_validation', 'worker_resources',
            'resource_budget', 'opponent_unchanged', 'same_model_baseline_hero_ev',
            'hero_best_response_ev', 'hero_improvement', 'cache', 'artifacts') if key in result})
        summary['baseline_precision'] = baseline_precision(result, config)
        summary['state'] = 'completed'
    except BaseException as error:
        summary.update(state='cancelled' if isinstance(error, KeyboardInterrupt) else 'failed',
                       error=f'{type(error).__name__}: {error}')
    finally:
        summary['wall_seconds'] = time.perf_counter() - started
        summary['precision_samples'] = precision_samples(folder / 'native.stderr')
        if summary['precision_samples']:
            summary['last_precision_sample'] = summary['precision_samples'][-1]
        for filename, field in [('worker.json', 'worker_resources'), ('resources.json', 'resource_budget')]:
            path = folder / filename
            if path.exists():
                try:
                    value = json.loads(path.read_text(encoding='utf-8'))
                    # Successful execute adds the guest's final budget.
                    if field == 'resource_budget' and field in summary:
                        summary['prelaunch_resource_budget'] = value
                    else:
                        summary[field] = value
                except (OSError, ValueError) as error:
                    summary.setdefault('record_errors', []).append(f'{filename}: {error}')
        summary['observed_memory'] = memory_summary(result, summary.get('worker_resources', {}))
        try:
            summary['binary_sha256_after'] = binary_digest(binary)
            summary['binary_unchanged_across_run'] = (summary['binary_sha256_after'] ==
                                                       summary.get('binary_sha256_before'))
        except OSError as error:
            summary['binary_hash_after_error'] = str(error)
        try:
            summary['source_file_unchanged'] = config_path.read_bytes() == raw
        except OSError as error:
            summary['source_file_verification_error'] = str(error)
        save_result(folder / 'benchmark-summary.json', summary)
        print(json.dumps(summary, ensure_ascii=True, allow_nan=False), flush=True)
    return 0 if summary['state'] == 'completed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--cold', action='store_true', help='No shared baseline/checkpoint reuse')
    parser.add_argument('--output', type=Path, help='New directory under workspace outputs; existing directories are rejected')
    parser.add_argument('--timeout', type=int, default=0, help='Explicit diagnostic cutoff only; default unlimited')
    parser.add_argument('--threads', type=int, help='Explicit override; omitted preserves input, or defaults to 8 if absent')
    args = parser.parse_args()
    return run(args.config, cold=args.cold, output=args.output, timeout=args.timeout, threads=args.threads)


if __name__ == '__main__':
    raise SystemExit(main())
