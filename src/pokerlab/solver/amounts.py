"""Decimal amounts over the engine's integer chips.

With ``chip_scale`` 100 the workbench works in bb to two places while the engine
counts 1/100 bb. Requests are scaled on the way in and reports on the way out, so
nothing above this module sees engine chips. Configs without the field use scale 1.
"""
import re

ACTION = re.compile(r'^(Bet|Raise|AllIn)\(([\d.]+)\)$')
REPORT_AMOUNTS = ('ev', 'hero_best_response_ev', 'same_model_baseline_hero_ev', 'hero_improvement')
PRECISION_AMOUNTS = ('target_chips', 'actual_chips', 'numerical_floor_chips', 'baseline_exploitability_chips')
VALIDATION_AMOUNTS = ('exported_br_ev', 'reevaluated_ev', 'absolute_error', 'tolerance_chips')
DETAIL_AMOUNTS = ('additional_contribution', 'call_amount', 'aggression_amount', 'pot_after_call')
SIZE_FIELDS = ('bets', 'raises', 'bets_ip', 'raises_ip', 'donks')


def chips(value, scale):
    amount = round(value * scale)
    if abs(amount - value * scale) > 1e-6:
        raise ValueError(f'金额 {value} 超出 {1 / scale:g} 的精度')
    return amount


def scale_sizes(text, scale):
    """Fixed sizes such as ``10c`` count in display units; ratios stay as they are."""
    return ','.join(f'{chips(float(token[:-1]), scale)}c' if token.endswith('c') else token
                    for token in (part.strip() for part in text.split(',')) if token)


def scale_action(label, factor):
    match = ACTION.match(label)
    if not match:
        return label
    amount = float(match[2]) * factor
    return f'{match[1]}({amount:.10g})'


def scale_scene(values, scale):
    for field in ('pot', 'stack'):
        if field in values:
            values[field] = chips(values[field], scale)
    for field in SIZE_FIELDS:
        if field in values:
            values[field] = [scale_sizes(text, scale) for text in values[field]]


def scale_request(request, scale):
    """Turn a display-unit request into engine chips, in place."""
    if scale == 1:
        return request
    if type(scale) is not int or not 1 <= scale <= 1000:
        raise ValueError('chip_scale must be an integer in 1..1000')
    scale_scene(request, scale)
    request['lines'] = [[scale_action(action, scale) for action in line] for line in request.get('lines', [])]
    if request.get('target_unit') == 'chips':
        request['target'] *= scale
    if 'rake_cap' in request:
        request['rake_cap'] *= scale
    for override in request.get('profile', {}).get('overrides', []):
        if override.get('scene'):
            scale_scene(override['scene'], scale)
        if override.get('actions'):
            override['actions'] = [scale_action(action, scale) for action in override['actions']]
    return request


def divide(values, scale):
    if isinstance(values, list):
        return [divide(value, scale) for value in values]
    return values / scale if isinstance(values, (int, float)) else values


def scale_node(node, scale):
    """Turn an engine node report into display units, in place."""
    for field in ('pot', 'contributions', 'remaining_stacks', 'action_ev_action_major', 'terminal_root_net_ev'):
        if field in node:
            node[field] = divide(node[field], scale)
    if 'actions' in node:
        node['actions'] = [scale_action(action, 1 / scale) for action in node['actions']]
    for detail in node.get('action_details', []):
        for field in DETAIL_AMOUNTS:
            detail[field] = divide(detail[field], scale)
    for player in node.get('players', []):
        player['ev'] = divide(player['ev'], scale)
    return node


def scale_result(result, scale):
    """Turn a native report into display units, in place."""
    if scale == 1:
        return result
    for field in ('node', 'root'):
        if field in result:
            scale_node(result[field], scale)
    for field in REPORT_AMOUNTS:
        if field in result:
            result[field] = divide(result[field], scale)
    for section, fields in (('precision', PRECISION_AMOUNTS), ('policy_validation', VALIDATION_AMOUNTS)):
        for field in fields:
            if field in result.get(section, {}):
                result[section][field] = divide(result[section][field], scale)
    for sample in result.get('coverage', {}).get('samples', []):
        sample['actions'] = [scale_action(action, 1 / scale) for action in sample.get('actions', [])]
        for step in sample.get('history', []):
            step['action'] = scale_action(step['action'], 1 / scale)
    return result
