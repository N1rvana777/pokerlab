"""Solve a spot with ranges and tree read from a reference solver and print the node to compare.

  python -X utf8 scripts/compare_reference.py outputs/gtow-compare/river1/spot.json --target 0.01 --nodes "" "0" "1"
  python -X utf8 scripts/compare_reference.py <spot> --incentives '{"check":2,"call":6,"bet":-3,"streets":[3]}' --biased 1
  python -X utf8 scripts/compare_reference.py <spot> --lock 1 '{"Call":1}' --freeze ""

The spot file holds board, pot_bb, stack_bb, oop, ip and tree. Node paths are action indices joined by
commas. Output goes to a new folder under outputs/gtow-compare; nothing is overwritten.
"""
import argparse
import json
from pathlib import Path
import time

from pokerlab.solver.hand_classes import annotate
from pokerlab.solver.workbench import SESSIONS, ROOT, inspect, new_job_dir, solve_cached


def config_for(spot, target, threads, iterations):
    tree = spot['tree']
    return dict(schema_version=1, amount_unit='bb', chip_scale=spot.get('chip_scale', 100), board=spot['board'], players=[spot['oop'], spot['ip']],
                pot=spot['pot_bb'], stack=spot['stack_bb'], hero=0, mode='equilibrium', target=target, target_unit='pot_pct',
                max_iterations=iterations, memory_budget_mb=4096, memory_auto=True, expand_suits=True, auto_suits=True, compression=True,
                threads=threads, time_limit_seconds=0, bets=tree.get('bets', ['', '', '']), raises=tree.get('raises', ['', '', '']),
                bets_ip=tree.get('bets_ip', []), raises_ip=tree.get('raises_ip', []), donks=tree.get('donks', []),
                lines=tree.get('lines', []), profile={'traits': []}, **{k: tree[k] for k in ('raise_limit', 'rake_rate', 'rake_cap') if k in tree})


def steps(text):
    return [int(a) for a in text.split(',') if a != '']


def locked_config(config, baseline, path, shares, freeze):
    """Every combo of a node at the same shares, keyed by the start of the action name; frozen nodes keep the baseline."""
    node = inspect(baseline, path, 'baseline', new_job_dir())
    probabilities = [next((value for key, value in shares.items() if action.startswith(key)), 0.0) for action in node['actions']]
    overrides = [dict(path=path, combo=combo, probabilities=probabilities) for combo in node['players'][node['actor']]['combos']]
    for at in freeze:
        frozen = inspect(baseline, at, 'baseline', new_job_dir())
        hands = frozen['players'][frozen['actor']]['combos']
        overrides += [dict(path=at, combo=combo, probabilities=[frozen['strategy_action_major'][a * len(hands) + h] for a in range(len(frozen['actions']))])
                      for h, combo in enumerate(hands)]
    return dict(config, mode='locked', expand_suits=True, profile={'traits': [], 'overrides': overrides})


def combo_weights(player):
    return [r if w > 0 else 0 for r, w in zip(player['raw_reach'], player['blocker_adjusted_weights'])]


def range_stats(player, pot):
    mass = sum(w for w in player['blocker_adjusted_weights'])
    if mass <= 0:
        return None
    ev = sum(w * v for w, v in zip(player['blocker_adjusted_weights'], player['ev'])) / mass
    equity = sum(w * v for w, v in zip(player['blocker_adjusted_weights'], player['equity'])) / mass
    return dict(combos=round(sum(combo_weights(player)), 2), ev=round(ev, 3), equity=round(equity * 100, 2),
                eqr=round(ev / equity / pot * 100, 1) if equity > 0 else None)


def eqr_pot(node, seat):
    return node['pot'] - max(0, node['contributions'][1 - seat] - node['contributions'][seat])


def shares(node, seat):
    """Class shares of the seat's range, as the filter panel shows them."""
    player = node['players'][seat]
    weights = combo_weights(player)
    total = sum(weights)
    out = {}
    for key, labels in node['class_labels'].items():
        counts = [0.0] * len(labels)
        for index, weight in zip(player['classes'][key], weights):
            if index is not None:
                counts[index] += weight
        out[key] = {label: round(count / total * 100, 1) for label, count in zip(labels, counts) if count > 0}
    return out


def strategy(node):
    player = node['players'][node['actor']]
    weights = combo_weights(player)
    total = sum(weights)
    hands = len(player['combos'])
    return {action: round(sum(weights[h] * node['strategy_action_major'][a * hands + h] for h in range(hands)) / total * 100, 2)
            for a, action in enumerate(node['actions'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spot', type=Path)
    parser.add_argument('--target', type=float, default=.05, help='Exploitability target in percent of the pot')
    parser.add_argument('--threads', type=int, default=24)
    parser.add_argument('--iterations', type=int, default=3000)
    parser.add_argument('--nodes', nargs='*', default=[''], help='Node paths, comma separated indices; empty string is the root')
    parser.add_argument('--incentives', help='Player Profile as JSON; "streets" limits it to those board lengths')
    parser.add_argument('--biased', type=int, default=1, help='Seat of the profile: 0 OOP, 1 IP')
    parser.add_argument('--lock', nargs=2, metavar=('PATH', 'SHARES'), help='Lock every combo of a node, for example 1 \'{"Call":1}\'')
    parser.add_argument('--freeze', nargs='*', default=[], help='Node paths that keep their baseline strategy under --lock')
    args = parser.parse_args()
    spot = json.loads(args.spot.read_text(encoding='utf-8'))
    config = config_for(spot, args.target, args.threads, args.iterations)
    if args.incentives:
        config.update(mode='preview', hero=1 - args.biased, profile={'traits': [], 'incentives': json.loads(args.incentives)})
    if args.lock:
        baseline = solve_cached(config, new_job_dir())
        config = locked_config(config, baseline, steps(args.lock[0]), json.loads(args.lock[1]), [steps(text) for text in args.freeze])
    started = time.perf_counter()
    report = solve_cached(config, new_job_dir())
    summary = dict(seconds=round(time.perf_counter() - started, 1), iterations=report['precision']['baseline_iterations'],
                   exploitability_pot_pct=round(report['precision']['actual_pot_pct'], 4), ev=[round(v, 3) for v in report['ev']],
                   peak_gib=round(report['memory']['measured_native_peak_rss_bytes'] / 2**30, 2))
    print(json.dumps(summary, ensure_ascii=False))
    rows = []
    for text in args.nodes:
        path = steps(text)
        node = annotate(inspect(report, path, 'baseline', new_job_dir()))
        row = dict(path=path, board=node['board'], pot=node['pot'])
        if not node.get('terminal') and not node.get('chance'):
            row.update(actor=node['actor'], strategy=strategy(node), oop=range_stats(node['players'][0], eqr_pot(node, 0)), ip=range_stats(node['players'][1], eqr_pot(node, 1)),
                       filters=shares(node, node['actor']))
        print(json.dumps(row, ensure_ascii=False))
        rows.append(row)
    SESSIONS.close()
    folder = args.spot.parent / time.strftime('run-%Y%m%d-%H%M%S')
    folder.mkdir()
    (folder / 'result.json').write_text(json.dumps(dict(summary=summary, nodes=rows), ensure_ascii=False, indent=1), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
