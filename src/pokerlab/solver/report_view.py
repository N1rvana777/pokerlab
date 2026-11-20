"""What the assistant reads of a report. The per-combo arrays run to 60 KB and overflow its tool output limit."""
from pokerlab.coach.equity import equity

RANKS = '23456789TJQKA'
ARRAYS = ('players', 'strategy_action_major', 'action_ev_action_major')
CLASS_ROWS = 80


def hand_class(combo):
    high, low = sorted((combo[:2], combo[2:]), key=lambda card: -RANKS.index(card[0]))
    return high[0] + low[0] + ('' if high[0] == low[0] else 's' if high[1] == low[1] else 'o')


def weights(player):
    """Combos in the range at this node, counted the way the page counts them."""
    return [reach if adjusted > 0 else 0.0 for reach, adjusted in zip(player['raw_reach'], player['blocker_adjusted_weights'])]


def average(values, shares):
    total = sum(shares)
    return round(sum(v * s for v, s in zip(values, shares)) / total, 4) if total else None


def range_view(player):
    held = weights(player)
    return {'combos': round(sum(held), 2), 'equity': average(player['equity'], player['blocker_adjusted_weights']), 'ev': average(player['ev'], player['blocker_adjusted_weights'])}


def actions_view(node, player):
    """The actor's whole range, then one row per hand class: combos, share of each action, EV."""
    names, count = node['actions'], len(player['combos'])
    held = weights(player)
    taken = [[held[hand] * node['strategy_action_major'][at * count + hand] for hand in range(count)] for at in range(len(names))]
    total = sum(held) or 1
    overall = [{'action': name, 'frequency': round(sum(taken[at]) / total, 4), 'combos': round(sum(taken[at]), 2),
                'ev': average([node['action_ev_action_major'][at * count + hand] for hand in range(count)], taken[at])} for at, name in enumerate(names)]
    rows = {}
    for hand, combo in enumerate(player['combos']):
        if held[hand] > 0:
            rows.setdefault(hand_class(combo), []).append(hand)
    table = []
    for name, hands in rows.items():
        mass = sum(held[hand] for hand in hands)
        table.append([name, round(mass, 2)] + [round(sum(taken[at][hand] for hand in hands) / mass, 3) for at in range(len(names))]
                     + [round(sum(held[hand] * player['ev'][hand] for hand in hands) / mass, 2)])
    table.sort(key=lambda row: -row[-1])
    return overall, {'columns': ['hand', 'combos'] + list(names) + ['ev'], 'rows': table[:CLASS_ROWS], 'total': len(table)}


def combo_view(node, wanted):
    """The asked combos in full, for whichever player holds them."""
    out, found = [], set()
    actor = node.get('actor')
    for seat, player in enumerate(node['players']):
        count = len(player['combos'])
        for hand, combo in enumerate(player['combos']):
            key = frozenset((combo[:2], combo[2:]))
            if key not in wanted:
                continue
            found.add(key)
            row = {'combo': combo, 'player': seat, 'reach': player['raw_reach'][hand], 'equity': player['equity'][hand], 'ev': player['ev'][hand]}
            if seat == actor:
                row['strategy'] = {name: node['strategy_action_major'][at * count + hand] for at, name in enumerate(node['actions'])}
                row['action_ev'] = {name: node['action_ev_action_major'][at * count + hand] for at, name in enumerate(node['actions'])}
            out.append(row)
    return out, sorted(''.join(sorted(key)) for key in wanted - found)


def node_view(node, combos=None):
    view = {key: value for key, value in node.items() if key not in ARRAYS}
    if not node.get('players'):
        return view
    view['ranges'] = [range_view(player) for player in node['players']]
    if node.get('actor') is not None and node.get('strategy_action_major'):
        view['overall'], view['by_class'] = actions_view(node, node['players'][node['actor']])
    if combos:
        view['combos'], view['combos_not_in_range'] = combo_view(node, {frozenset((c[:2], c[2:])) for c in combos})
    return view


def config_view(config):
    profile = config.get('profile')
    if not isinstance(profile, dict) or not profile.get('overrides'):
        return config
    return {**config, 'profile': {**{key: value for key, value in profile.items() if key != 'overrides'}, 'locked_combos': len(profile['overrides'])}}


def value_locks(node, action, hero_combo, target):
    """Locks that make target of the combos taking this action ahead of hero_combo, and what they come to.

    Value hands take it more or the other hands less, whichever reaches the target. A combo the hero blocks stays as solved.
    """
    hero = [hero_combo[:2], hero_combo[2:]]
    player, names = node['players'][node['actor']], node['actions']
    count = len(player['combos'])
    solved = [node['strategy_action_major'][action * count + hand] for hand in range(count)]
    reach = weights(player)
    ahead = [None if not reach[hand] or {combo[:2], combo[2:]} & set(hero) else equity(hero, [combo], board=node['board'])['equity'] < .5
             for hand, combo in enumerate(player['combos'])]
    value = sum(reach[hand] for hand in range(count) if ahead[hand])
    other = sum(reach[hand] * solved[hand] for hand in range(count) if ahead[hand] is False)
    if not value:
        raise ValueError('这个节点没有比这手牌强的组合')
    # value hands at v, the others at s times what they did: v * value / (v * value + s * other) = target
    if target >= 1 or not other:
        v, s = 1.0, 0.0
    elif target / (1 - target) >= value / other:
        v, s = 1.0, value * (1 - target) / (target * other)
    else:
        v, s = target * other / ((1 - target) * value), 1.0
    locks = []
    for hand, combo in enumerate(player['combos']):
        if not reach[hand] or ahead[hand] is None:
            continue
        share = min(1.0, v if ahead[hand] else solved[hand] * s)
        others = {at: node['strategy_action_major'][at * count + hand] for at in range(len(names)) if at != action}
        rest = sum(others.values())
        locks.append({'path': node['path'], 'combo': combo, 'probabilities': [
            share if at == action else (1 - share) * (others[at] / rest if rest > 0 else 1 / len(others)) for at in range(len(names))]})
    return locks, {'value_share': round(v * value / (v * value + s * other), 4), 'value_combos': round(v * value, 2), 'other_combos': round(s * other, 2)}


def report_view(report, combos=None):
    view = {key: value for key, value in report.items() if key not in ('root', 'node', 'baseline_root_strategy')}
    if isinstance(report.get('config'), dict):
        view['config'] = config_view(report['config'])
    for field in ('root', 'node'):
        if isinstance(report.get(field), dict):
            view[field] = node_view(report[field], combos)
    return view
