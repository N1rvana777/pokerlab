"""Building the principle layer: every candidate is accounted for, evidence adds up, and bad entries are reported."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_methods  # noqa: E402
import check_methods  # noqa: E402


def candidates():
    moment = {'video': 'vidAAAAAAA1', 'time': '0:30', 'hand': None, 'note': '讲解'}
    return {'a:0': {'title': '对跟注站多打价值', 'read': '不弃牌', 'adjustment': '打薄', 'why': '他跟太宽', 'tags': ['type-station'], 'evidence': [moment]},
            'c:0': {'title': '价值打薄', 'tags': ['type-station', 'value-bet'], 'evidence': [moment, {'video': 'vidAAAAAAA1', 'time': '1:05', 'hand': None, 'note': '例子'}]},
            'blog:0': {'title': '跟注站', 'tags': ['sizing'], 'evidence': [{'url': 'https://blog.example/a', 'title': '文章', 'note': '说明'}]},
            'b:0': {'title': '只评论一手牌'}}


def plan():
    return {'groups': [{'id': 'value-vs-stations', 'keep': 'a:0', 'absorb': ['c:0', 'blog:0'], 'edits': {'limits': '他变紧时停止'}}],
            'dropped': [{'ref': 'b:0', 'reason': '只评论一手牌'}]}


def test_a_group_adds_up_its_evidence_and_takes_edits():
    entry = build_methods.build(candidates(), plan(), {'value-vs-stations': {'status': '支持'}})[0]
    assert entry['title'] == '对跟注站多打价值' and entry['limits'] == '他变紧时停止'
    assert entry['tags'] == ['type-station', 'value-bet', 'sizing']
    assert len(entry['evidence']) == 3 and entry['sources'] == 2
    assert entry['origin'] == 'hhp+blog' and entry['solver'] == {'status': '支持'}


@pytest.mark.parametrize('change, message', [
    (lambda p: p['dropped'].clear(), 'not placed'),
    (lambda p: p['groups'][0]['absorb'].append('z:9'), 'no candidate'),
    (lambda p: p['groups'].append({'id': 'again', 'keep': 'a:0'}), 'is in'),
    (lambda p: p['dropped'].append({'ref': 'a:0', 'reason': 'x'}), 'kept and dropped'),
])
def test_every_candidate_is_placed_once(change, message):
    broken = plan()
    change(broken)
    with pytest.raises(ValueError, match=message):
        build_methods.build(candidates(), broken, {})


def test_a_solver_check_must_name_a_method():
    with pytest.raises(ValueError, match='unknown ids'):
        build_methods.build(candidates(), plan(), {'nothing': {}})


class Base:
    hands = [{'id': 'hand-1'}]
    segments = {'vidAAAAAAA1': [(0, 'they call too wide on every street so we value bet thinner with every top pair we hold'), (100, 'end')]}


def test_check_reports_what_is_wrong():
    good = {'title': 't', 'read': 'r', 'adjustment': 'a', 'why': 'w', 'tags': ['sizing'], 'evidence': [{'video': 'vidAAAAAAA1', 'time': '1:00', 'hand': 'hand-1'}]}
    assert check_methods.problems([good], Base()) == []
    bad = {**good, 'why': '', 'tags': ['nothing'], 'evidence': [{'video': 'vidAAAAAAA1', 'time': '9:00', 'hand': 'hand-2'}, {'video': 'other', 'time': '0:10'}]}
    text = ' '.join(check_methods.problems([bad], Base()))
    for expected in ('缺少 why', '标签 nothing', '不在视频内', '手牌 hand-2', '视频 other'):
        assert expected in text
    assert check_methods.problems([{**good, 'evidence': []}], Base()) == ['第 1 条：没有证据']
    copied = {**good, 'why': 'they call too wide on every street so we value bet thinner with every top pair'}
    assert '连续相同' in check_methods.problems([copied], Base())[0]
