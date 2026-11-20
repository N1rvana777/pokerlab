"""Time and memory of full-flop solves started from preflop-library lines.

  python -X utf8 scripts/benchmark_preflop_lines.py --library outputs/gtow-preflop/<file>.json --lines srp_BTN_STR 3bet_BTN_STR
      --boards Ks7d2c Th9h8c --trees fast standard --output outputs/performance-lines/<new folder>

--extra-stack adds chips behind on both sides, to see how a deeper stack behaves with the same ranges. Every run is a
fresh solve; a run the memory check refuses is recorded as refused. The output folder must not exist yet.
"""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_reference import config_for  # noqa: E402
from pokerlab.solver.workbench import ROOT, execute, new_job_dir  # noqa: E402

TREES = {
    'fast': {'bets': ['33%', '66%', '66%'], 'raises': ['3x', '3x', '3x'], 'raise_limit': 2},
    'standard': {'bets': ['33%,75%', '50%,100%', '50%,100%'], 'raises': ['3x', '3x', '3x'], 'raise_limit': 2},
    'full': {'bets': ['33%,66%,100%'] * 3, 'raises': ['3x', '3x', '3x'], 'raise_limit': 2},
    'full_light': {'bets': ['33%,66%,100%'] * 3, 'raises': ['3x', '3x', ''], 'raise_limit': 2},
}


def board_cards(text):
    return [text[i:i + 2] for i in range(0, len(text), 2)]


def run(line, board, tree, target, extra, threads, iterations, stretch=False):
    spot = dict(board=board_cards(board), pot_bb=line['pot'], stack_bb=line['stack'] + extra, chip_scale=10, oop=line['oop'], ip=line['ip'], tree=TREES[tree])
    config = config_for(spot, target, threads, iterations)
    if stretch:
        config['memory_stretch'] = True
    started = time.perf_counter()
    row = dict(line=line['id'], board=board, tree=tree, target=target, stack=spot['stack_bb'], pot=line['pot'], spr=round(spot['stack_bb'] / line['pot'], 2))
    try:
        report = execute(config, new_job_dir())
    except (RuntimeError, ValueError) as error:
        return {**row, 'state': 'refused', 'error': str(error)[:300], 'wall_seconds': round(time.perf_counter() - started, 1)}
    timing, memory, precision = report['timing'], report['memory'], report['precision']
    peak = memory.get('measured_native_peak_rss_bytes') or 0
    return {**row, 'state': 'completed', 'iterations': precision['baseline_iterations'], 'pot_pct': round(precision['actual_pot_pct'], 3),
            'solve_seconds': round(timing['total_seconds'], 1), 'wall_seconds': round(time.perf_counter() - started, 1),
            'peak_gib': round(peak / 1024 ** 3, 2), 'budget_mb': memory.get('effective_budget_mb') or memory.get('budget_mb')}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--lines', nargs='+', required=True)
    parser.add_argument('--boards', nargs='+', required=True)
    parser.add_argument('--trees', nargs='+', choices=sorted(TREES), default=['fast'])
    parser.add_argument('--target', type=float, default=0.5)
    parser.add_argument('--extra-stack', type=float, default=0)
    parser.add_argument('--threads', type=int, default=24)
    parser.add_argument('--iterations', type=int, default=3000)
    parser.add_argument('--pause', type=float, default=45, help='seconds between runs, so WSL can hand memory back')
    parser.add_argument('--stretch', action='store_true', help='let Windows page idle programs out for a larger budget')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    library = json.loads(args.library.read_text(encoding='utf-8'))
    lines = {line['id']: line for line in library['lines']}
    args.output.mkdir(parents=True)
    log = args.output / 'results.jsonl'
    first = True
    for tree in args.trees:
        for name in args.lines:
            for board in args.boards:
                if not first:
                    time.sleep(args.pause)
                first = False
                row = {'library': library['id'], **run(lines[name], board, tree, args.target, args.extra_stack, args.threads, args.iterations, args.stretch)}
                print(json.dumps(row, ensure_ascii=False), flush=True)
                with log.open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    print('written', log.relative_to(ROOT) if log.is_relative_to(ROOT) else log)


if __name__ == '__main__':
    main()
