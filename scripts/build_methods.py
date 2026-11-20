"""Build methods.json from the reading batches, a merge plan and the Solver checks.

  python -X utf8 scripts/build_methods.py

Under outputs/knowledge/hhp/methods: candidates/*.json hold what each batch read, merge_plan.json says which
entries say the same thing, and solver_checks.json holds what the Solver found. methods.json is built from these
three, so it can always be rebuilt. Every candidate must be kept, absorbed or dropped with a reason.
"""
import json
from pathlib import Path

from pokerlab.coach import knowledge

FIELDS = ('title', 'read', 'adjustment', 'why', 'how_far', 'limits', 'thinking')
MAX_TAGS = 6


def load_candidates(folder):
    out = {}
    for path in sorted((folder / 'candidates').glob('*.json')):
        for at, entry in enumerate(json.loads(path.read_text(encoding='utf-8'))):
            out[f'{path.stem}:{at}'] = entry
    return out


def key_of(item):
    return item.get('url') or (item.get('video'), item.get('time'), item.get('hand'))


def build(candidates, plan, checks):
    used, out = {}, []
    for group in plan['groups']:
        refs = [group['keep'], *group.get('absorb', [])]
        for ref in refs:
            if ref not in candidates:
                raise ValueError(f'{group["id"]}: no candidate {ref}')
            if ref in used:
                raise ValueError(f'{ref} is in {used[ref]} and {group["id"]}')
            used[ref] = group['id']
        base = candidates[group['keep']]
        entry = {'id': group['id'], **{key: base.get(key) for key in FIELDS}, **group.get('edits', {})}
        tags, evidence, seen = [], [], set()
        for ref in refs:
            tags += [tag for tag in candidates[ref].get('tags') or [] if tag not in tags]
            for item in candidates[ref].get('evidence') or []:
                if key_of(item) not in seen:
                    seen.add(key_of(item))
                    evidence.append(item)
        kinds = {'blog' if ref.startswith('blog:') else 'hhp' for ref in refs}
        out.append({**entry, 'tags': tags[:MAX_TAGS], 'origin': 'hhp+blog' if len(kinds) == 2 else kinds.pop(),
                    'sources': len({item.get('url') or item.get('video') for item in evidence}), 'evidence': evidence,
                    'solver': checks.get(group['id'])})
    dropped = {item['ref'] for item in plan.get('dropped', [])}
    if unknown := dropped - set(candidates):
        raise ValueError(f'dropped refs do not exist: {sorted(unknown)}')
    if both := dropped & set(used):
        raise ValueError(f'kept and dropped: {sorted(both)}')
    if missing := set(candidates) - set(used) - dropped:
        raise ValueError(f'not placed: {sorted(missing)}')
    if len({entry['id'] for entry in out}) != len(out):
        raise ValueError('duplicate ids')
    if unknown := set(checks) - {entry['id'] for entry in out}:
        raise ValueError(f'checks for unknown ids: {sorted(unknown)}')
    return out


def main():
    folder = knowledge.home() / 'methods'
    plan = json.loads((folder / 'merge_plan.json').read_text(encoding='utf-8'))
    checks_file = folder / 'solver_checks.json'
    checks = json.loads(checks_file.read_text(encoding='utf-8')) if checks_file.is_file() else {}
    candidates = load_candidates(folder)
    entries = build(candidates, plan, checks)
    (folder / 'methods.json').write_bytes(json.dumps(entries, ensure_ascii=False, indent=1).encode('utf-8'))
    print(len(candidates), 'candidates,', len(entries), 'methods,', len(plan.get('dropped', [])), 'dropped,', sum(bool(e['solver']) for e in entries), 'with a Solver check')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
