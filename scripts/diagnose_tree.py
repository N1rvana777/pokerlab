"""Public-tree-only memory diagnostics; never launches an expanded solve.

PowerShell: python scripts/diagnose_tree.py PATH --output outputs/tree-diagnostic.json
"""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOCATOR_ENV = {'MALLOC_ARENA_MAX':'2', 'MALLOC_MMAP_THRESHOLD_':'131072',
                 'MALLOC_TRIM_THRESHOLD_':'131072', 'MALLOC_MMAP_MAX_':'65536',
                 'POKERLAB_ALLOCATOR_PROFILE':'glibc-bounded-v1'}


def estimate(config, storage=False):
    config = copy.deepcopy(config)
    # A launcher-only resource mode is not part of the strict native schema.
    config.pop('memory_auto', None)
    config.pop('memory_stretch', None)
    config.pop('amount_unit', None)
    # Old binaries reject this unknown field before allocation instead of ignoring
    # an unsupported CLI flag and accidentally running a full solve.
    config['runtime'] = {'storage_estimate_only' if storage else 'estimate_only': True}
    if sys.platform == 'win32':
        posix = '/mnt/' + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
        command = ['wsl', '-d', 'Ubuntu', '--cd', posix, '--',
                   'bash', '-c', 'ulimit -v 2097152; exec env '+
                   ' '.join(k+'='+v for k,v in ALLOCATOR_ENV.items())+' ./target/release/pokerlab-solver']
    else:
        command = [str(ROOT / 'target/release/pokerlab-solver')]
    environment={**os.environ,**ALLOCATOR_ENV}
    result = subprocess.run(command, input=json.dumps(config), text=True,
                            encoding='utf-8', capture_output=True, timeout=60, cwd=ROOT,env=environment)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).replace('\x00', '').strip() or f'native diagnostic exit {result.returncode}')
    report = json.loads(result.stdout)
    if not report.get('estimate_only') or report.get('solver_game_allocated') is not False:
        raise RuntimeError('Rebuild the engine: estimate-only support is required')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--storage', action='store_true', help='Exact storage layout; compare compression/isomorphism without changing the game')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; choose a new filename')
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    variants = [('original', {})]
    # Explicit counterfactuals only: never replace or save the user's configuration.
    if args.storage:
        variants=[(f'compression_{c}_auto_suits_{s}', {'compression':c,'auto_suits':s}) for c,s in [(False,False),(False,True),(True,False),(True,True)]]
    elif not config.get('bets_ip') and not config.get('raises_ip'):
        variants += [('one_bet_size_each_street', {'bets': [s.split(',')[0] for s in config['bets']]}),
                     ('only_allin_raises', {'raises': ['a'] * 3}),
                     ('no_raises', {'raises': [''] * 3}),
                     ('pot_times_ten_same_stack', {'pot': config['pot'] * 10})]
    reports = []
    for label, changes in variants:
        trial = copy.deepcopy(config)
        trial.update(changes)
        report = estimate(trial, args.storage)
        if not args.storage:
            assert sum(r.get('public_nodes', 0) for r in report['streets']) == report['public_nodes']
            assert sum(r.get('preflight_bytes', 0) for r in report['streets']) + report['fixed_overhead_bytes'] == report['preflight_upper_bound_bytes']
        reports.append({'label': label, 'changes': changes, **report})
        total=report['memory_plan']['estimated_peak_bytes'] if args.storage else report['preflight_upper_bound_bytes']
        print(label, 'estimated_GiB=', round(total / 1024**3, 3), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump({'note': 'Counterfactual diagnostics, not solved policies or measured full-tree memory',
                   'reports': reports}, stream, indent=2)


if __name__ == '__main__':
    main()
