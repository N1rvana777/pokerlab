"""The diagnostic launcher must retain poker inputs and supervised boundaries."""
from contextlib import contextmanager
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def bench():
    path = Path(__file__).resolve().parents[1] / 'scripts/benchmark_iterations.py'
    spec = importlib.util.spec_from_file_location('benchmark_iterations_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def config():
    return {'board': ['9h', '8h', '2c'], 'players': ['AA,AKs:0.5', 'QQ,AQo'], 'pot': 8, 'stack': 100,
            'bets': ['33%,66%,100%', '33%,50%,75%', '33%,50%,75%'], 'raises': ['3x'] * 3,
            'bets_ip': [], 'raises_ip': [], 'donks': [], 'hero': 0, 'mode': 'fixed',
            'target': 0.1, 'target_unit': 'pot_pct', 'max_iterations': 100000,
            'compression': True, 'auto_suits': True, 'expand_suits': True, 'threads': 16,
            'time_limit_seconds': 600, 'memory_auto': True, 'memory_budget_mb': 4096,
            'amount_unit': 'bb', 'profile': {'traits': [{'kind': 'station', 'strength': 2}], 'overrides': []}}


def test_diagnostic_does_not_change_the_tree_precision_or_existing_config(bench, config):
    before = copy.deepcopy(config)
    request = bench.diagnostic_request(config, 30)
    assert config == before
    for key in set(config) - {'memory_auto', 'amount_unit', 'time_limit_seconds'}:
        assert request[key] == config[key], key
    assert request['runtime'] == {'benchmark_iterations': 30}
    assert request['time_limit_seconds'] == 0
    assert 'memory_auto' not in request and 'amount_unit' not in request
    assert bench.diagnostic_request(config, 30, 8)['threads'] == 8


@pytest.mark.parametrize('iterations', [True, 0, -1, 1.5, 100001, 2**32])
def test_invalid_fixed_iterations_rejected(bench, config, iterations):
    with pytest.raises(ValueError):
        bench.diagnostic_request(config, iterations)


def test_cache_runtime_cannot_be_smuggled_into_a_diagnostic(bench, config):
    config['runtime'] = {'baseline_file': 'outputs/cache/something.policy'}
    with pytest.raises(ValueError, match='runtime'):
        bench.diagnostic_request(config, 30)


@pytest.mark.parametrize('problem', ['wrong_protocol', 'early_stop', 'unreaped'])
def test_result_requires_exact_iteration_completion_and_reap(bench, problem):
    result = {'benchmark': True, 'precision': {'stop_reason': 'fixed_iteration_diagnostic', 'baseline_iterations': 30},
              'worker_resources': {'exit_code': 0, 'process_reaped': True}}
    if problem == 'wrong_protocol':
        result['benchmark'] = False
    elif problem == 'early_stop':
        result['precision']['baseline_iterations'] = 20
    else:
        result['worker_resources']['process_reaped'] = False
    with pytest.raises(RuntimeError):
        bench.validate_result(result, 30)


def test_precision_samples_keep_initial_and_final_non_multiple_of_ten(bench, tmp_path):
    path = tmp_path / 'native.stderr'
    path.write_text('\n'.join(['ordinary log', json.dumps({'phase': 'building', 'detail': {}}),
                              json.dumps({'phase': 'baseline', 'detail': {'actual_chips': 1.2}}),
                              json.dumps({'phase': 'baseline', 'detail': {'iteration': 10, 'actual_chips': .7}}),
                              json.dumps({'phase': 'baseline', 'detail': {'iteration': 11, 'actual_chips': .6}})]))
    assert bench.parse_precision_samples(path) == [{'actual_chips': 1.2},
                                                  {'iteration': 10, 'actual_chips': .7},
                                                  {'iteration': 11, 'actual_chips': .6}]


def test_budget_is_measured_inside_lock_and_failure_never_launches(bench, config, tmp_path, monkeypatch):
    monkeypatch.setattr(bench, 'ROOT', tmp_path)
    config_path = tmp_path / 'source.json'
    config_path.write_text(json.dumps(config))
    executable = tmp_path / 'binary'
    executable.write_bytes(b'fixture; never executable')
    folder = tmp_path / 'outputs/diagnostic'
    events = []

    @contextmanager
    def lock(_folder):
        events.append('lock')
        yield
        events.append('unlock')

    def resources(_config):
        assert events == ['lock']
        events.append('resources')
        return {'ready': False, 'error': 'fixture: insufficient safe memory'}

    monkeypatch.setattr(bench, 'engine_lock', lock)
    monkeypatch.setattr(bench, 'memory_resources', resources)
    monkeypatch.setattr(bench.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('must not launch'))
    assert bench.run(config_path, 30, executable, folder) == 1
    summary = json.loads((folder / 'benchmark-summary.json').read_text())
    assert summary['state'] == 'failed' and 'insufficient safe memory' in summary['error']
    assert (folder / 'source-config.json').read_bytes() == config_path.read_bytes()
    assert not (folder / 'request.json').exists()


@pytest.mark.parametrize('cleanup_delays', [[], ['timeout'] * 12, ['interrupt', 'timeout', 'interrupt']])
def test_no_timeout_and_interrupt_requests_supervisor_cleanup(bench, config, tmp_path, monkeypatch, cleanup_delays):
    monkeypatch.setattr(bench, 'ROOT', tmp_path)
    config_path = tmp_path / 'source.json'
    config_path.write_text(json.dumps(config))
    executable = tmp_path / 'binary'
    executable.write_bytes(b'fixture; never executable')
    folder = tmp_path / 'outputs/diagnostic'
    ownership = {'locked': False, 'native_reaped': False}

    @contextmanager
    def lock(_folder):
        ownership['locked'] = True
        try:
            yield
        finally:
            assert ownership['native_reaped'], 'serialization lock released before child cleanup'
            ownership['locked'] = False

    monkeypatch.setattr(bench, 'engine_lock', lock)
    monkeypatch.setattr(bench, 'memory_resources', lambda _: {'ready': True, 'effective_mb': 14000})
    calls = []

    class Process:
        def kill(self):
            pytest.fail('must never kill only the WSL wrapper during cleanup')

        def communicate(self, *args, **kwargs):
            assert ownership['locked']
            calls.append((args, kwargs))
            if len(calls) == 1:
                request = json.loads(args[0])
                assert request['memory_budget_mb'] == 14000
                assert request['target'] == config['target']
                assert kwargs == {}  # No solve timeout, even for an old 600s config.
                raise KeyboardInterrupt
            assert (folder / 'cancel').exists()
            assert kwargs == {'timeout': 1}  # Polling interval, never a cleanup deadline.
            cleanup_index = len(calls) - 2
            if cleanup_index < len(cleanup_delays):
                if cleanup_delays[cleanup_index] == 'interrupt':
                    raise KeyboardInterrupt
                raise bench.subprocess.TimeoutExpired('synthetic supervisor', 1)
            ownership['native_reaped'] = True
            (folder / 'worker.json').write_text(json.dumps({'state': 'cancelled', 'process_reaped': True}))
            return '', ''

    def popen(command, **kwargs):
        assert command[-1] == '--diagnostics'
        assert command[command.index('--timeout') + 1] == '0'
        assert '--binary' in command
        assert 'shell' not in kwargs
        return Process()

    monkeypatch.setattr(bench.subprocess, 'Popen', popen)
    assert bench.run(config_path, 30, executable, folder) == 1
    summary = json.loads((folder / 'benchmark-summary.json').read_text())
    assert summary['state'] == 'cancelled'
    assert summary['worker_resources']['process_reaped'] is True
    assert ownership == {'locked': False, 'native_reaped': True}
    assert len(calls) == len(cleanup_delays) + 2
