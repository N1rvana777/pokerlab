"""Serial real-memory acceptance; never edits the supplied configuration file."""
import argparse
import json
from pathlib import Path
import time

from pokerlab.solver.__main__ import ROOT, save_result
from pokerlab.solver.workbench import new_job_dir, solve_cached


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--pot', type=int)
    parser.add_argument('--iterations', type=int, default=50)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    config.update(memory_auto=True, amount_unit='bb', compression=True, auto_suits=True,
                  expand_suits=True, threads=8, max_iterations=args.iterations)
    if args.pot is not None:
        config['pot'] = args.pot
    folder = new_job_dir()
    print(json.dumps({'folder': str(folder), 'pot': config['pot'], 'stack': config['stack'],
                      'iterations': args.iterations, 'mode': config['mode'],
                      'note': 'Memory acceptance; iteration cap does not certify target precision.'}), flush=True)
    started = time.monotonic()
    try:
        result = solve_cached(config, folder, timeout=args.timeout)
        evidence = {key: result[key] for key in ('precision', 'memory', 'resource_budget', 'worker_resources',
                    'opponent_unchanged', 'ev', 'policy_validation', 'timing', 'tree')}
        evidence.update(state='completed', wall_seconds=time.monotonic()-started,
                        report=str(folder/'result.json'), unchanged_game_fields=['players','stack','bets','raises','profile'],
                        acceptance_iterations=args.iterations, pot=config['pot'], amount_unit='bb')
    except Exception as exc:
        evidence = {'state': 'failed', 'error': str(exc), 'wall_seconds': time.monotonic()-started}
        if (folder/'worker.json').exists():
            evidence['worker_resources'] = json.loads((folder/'worker.json').read_text(encoding='utf-8'))
    save_result(folder/'usability-acceptance.json', evidence)
    print(json.dumps(evidence, ensure_ascii=True), flush=True)
    return 0 if evidence['state'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
