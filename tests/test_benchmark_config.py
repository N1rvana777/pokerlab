"""Cold full-solve launch semantics, checked without native tree allocation."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def bench(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'scripts/benchmark_config.py'
    spec = importlib.util.spec_from_file_location('benchmark_config_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    executable = tmp_path / 'target/release/pokerlab-solver'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'fake binary, never executed')
    return module


@pytest.fixture
def config():
    return {'board': ['9h', '8h', '2c'], 'players': ['AA,AKs:0.5', 'QQ,AQo'],
            'pot': 8, 'stack': 100, 'bets': ['33%,66%,100%', '33%,50%,75%', '33%,50%,75%'],
            'raises': ['3x'] * 3, 'hero': 0, 'mode': 'fixed', 'target': .5,
            'target_unit': 'pot_pct', 'max_iterations': 100000, 'threads': 16,
            'compression': True, 'auto_suits': True, 'memory_auto': True,
            'memory_budget_mb': 4096, 'time_limit_seconds': 600,
            'profile': {'traits': [{'kind': 'station', 'strength': 2}], 'overrides': []}}


def write_source(bench, config):
    path = bench.ROOT / 'source.json'
    path.write_text(json.dumps(config), encoding='utf-8-sig')
    return path


def fake_result(config):
    return {'config': copy.deepcopy(config), 'cache': {'baseline_hit': False, 'resumed_iterations': 0},
            'precision': {'metric': 'hero_response_gap', 'actual_chips': 0, 'actual_pot_pct': 0,
                          'target_chips': .04, 'baseline_exploitability_chips': .035,
                          'baseline_iterations': 320, 'baseline_stop_reason': 'target_met'},
            'worker_resources': {'exit_code': 0, 'process_reaped': True, 'sampled_peak_rss_bytes': 100,
                                 'sampled_peak_vms_bytes': 200, 'sampled_peak_swap_bytes': 0},
            'memory': {'measured_native_peak_rss_bytes': 110, 'measured_native_peak_vms_bytes': 205},
            'timing': {'build_seconds': 1, 'baseline_seconds': 12, 'compile_seconds': 2,
                       'response_seconds': 3, 'evaluation_seconds': 4, 'save_seconds': 5},
            'resource_budget': {'effective_mb': 14000}}


def test_preserves_tree_target_threads_and_source(bench, config):
    original = copy.deepcopy(config)
    request = bench.prepare_config(config)
    assert config == original
    assert request['threads'] == 16
    assert request['time_limit_seconds'] == 0
    assert request['target'] == .5
    for key in config.keys() - {'memory_budget_mb', 'time_limit_seconds'}:
        assert request[key] == config[key]
    assert bench.prepare_config(config, threads=8)['threads'] == 8
    config.pop('threads')
    assert bench.prepare_config(config)['threads'] == 8


@pytest.mark.parametrize('threads', [True, 0, 17, -1, 1.5])
def test_rejects_invalid_thread_override(bench, config, threads):
    with pytest.raises(ValueError, match='threads'):
        bench.prepare_config(config, threads)


def test_cold_runtime_paths_are_new_local_and_metadata_is_inspectable(bench, config, monkeypatch):
    source = write_source(bench, config)
    before = source.read_bytes()
    folder = bench.ROOT / 'outputs/cold-complete'
    shared = bench.ROOT / 'outputs/cache'
    shared.mkdir(parents=True)
    cache_sentinel = shared / 'unrelated-existing-baseline.policy'
    cache_sentinel.write_bytes(b'never read or change shared cache')
    calls = []

    def execute(request, output, timeout):
        calls.append(copy.deepcopy(request))
        assert output == folder and timeout is None
        runtime = request['runtime']
        for name in ['baseline_file', 'checkpoint_file', 'output_prefix']:
            artifact = bench.ROOT / runtime[name]
            assert artifact.parent == folder
            assert not artifact.exists()
        assert 'benchmark_iterations' not in runtime
        assert request['threads'] == 16
        assert request['target'] == .5
        assert request['time_limit_seconds'] == 0
        (folder / 'native.stderr').write_text('not json\n' + json.dumps(
            {'phase': 'baseline', 'detail': {'iteration': 320, 'actual_chips': .035}}))
        result = fake_result(request)
        (folder / 'worker.json').write_text(json.dumps(result['worker_resources']))
        for path in [runtime['baseline_file'], runtime['output_prefix'] + '.model.policy',
                     runtime['output_prefix'] + '.response.policy']:
            (bench.ROOT / path).write_bytes(b'fake complete policy')
        return result

    monkeypatch.setattr(bench, 'execute', execute)
    monkeypatch.setattr(bench, 'solve_cached', lambda *a, **k: pytest.fail('cold must not call solve_cached'))
    assert bench.run(source, cold=True, output=folder) == 0
    assert len(calls) == 1
    assert source.read_bytes() == before
    assert cache_sentinel.read_bytes() == b'never read or change shared cache'
    result = json.loads((folder / 'result.json').read_text())
    assert 'runtime' not in result['config']
    assert result['config_sha256'] == bench.fingerprint(result['config'])
    for variant in ['baseline', 'model', 'response']:
        assert (bench.ROOT / result['artifacts'][variant]).parent == folder
    native_echo = json.loads((folder / 'native-config.json').read_text())
    assert native_echo['runtime'] == calls[0]['runtime']
    summary = json.loads((folder / 'benchmark-summary.json').read_text())
    assert summary['state'] == 'completed'
    assert summary['source_file_sha256'] == hashlib.sha256(before).hexdigest()
    assert summary['binary_sha256_before'] == summary['binary_sha256_after']
    assert summary['binary_unchanged_across_run'] is True
    assert summary['baseline_precision']['actual_pot_pct'] == pytest.approx(.4375)
    assert summary['precision']['actual_pot_pct'] == 0  # response gap is separate
    assert summary['baseline_precision']['target_met'] is True
    assert summary['observed_memory'] == {'native_peak_rss_bytes': 110, 'native_peak_vms_bytes': 205,
                                          'sampled_native_peak_swap_bytes': 0,
                                          'process_reaped': True, 'exit_code': 0}
    assert summary['timing']['save_seconds'] == 5
    assert summary['last_precision_sample']['iteration'] == 320
    assert summary['wall_clock_timeout'] is None


def test_default_still_uses_workbench_cache(bench, config, monkeypatch):
    source = write_source(bench, config)
    folder = bench.ROOT / 'outputs/legacy-cached'
    monkeypatch.setattr(bench, 'execute', lambda *a, **k: pytest.fail('cached mode bypasses cold execute'))

    def cached(request, output, timeout):
        assert timeout == 15
        assert output == folder
        assert 'runtime' not in request
        result = fake_result(request)
        result['cache'] = {'baseline_hit': True, 'resumed_iterations': 0}
        return result

    monkeypatch.setattr(bench, 'solve_cached', cached)
    assert bench.run(source, output=folder, timeout=15) == 0
    summary = json.loads((folder / 'benchmark-summary.json').read_text())
    assert summary['cache']['baseline_hit'] is True
    assert summary['wall_clock_timeout'] == 15


@pytest.mark.parametrize('cache', [{'baseline_hit': True, 'resumed_iterations': 0},
                                 {'baseline_hit': False, 'resumed_iterations': 10}, {}])
def test_cold_requires_native_proof_of_no_cache(bench, config, monkeypatch, cache):
    source = write_source(bench, config)
    folder = bench.ROOT / 'outputs/invalid-cold'

    def execute(request, *_args):
        result = fake_result(request)
        result['cache'] = cache
        return result

    monkeypatch.setattr(bench, 'execute', execute)
    assert bench.run(source, cold=True, output=folder) == 1
    summary = json.loads((folder / 'benchmark-summary.json').read_text())
    assert 'zero baseline/checkpoint reuse' in summary['error']
    assert not (folder / 'result.json').exists()


def test_failure_keeps_measured_resource_record_not_invented_precision(bench, config, monkeypatch):
    source = write_source(bench, config)
    folder = bench.ROOT / 'outputs/failed'

    def execute(_request, output, _timeout):
        (output / 'resources.json').write_text(json.dumps({'effective_mb': 11000}))
        (output / 'worker.json').write_text(json.dumps({'process_reaped': True, 'exit_code': 1,
                                                       'sampled_peak_rss_bytes': 1000,
                                                       'sampled_peak_swap_bytes': 0}))
        raise RuntimeError('memory preflight rejected before allocation')

    monkeypatch.setattr(bench, 'execute', execute)
    assert bench.run(source, cold=True, output=folder) == 1
    summary = json.loads((folder / 'benchmark-summary.json').read_text())
    assert summary['state'] == 'failed'
    assert summary['resource_budget']['effective_mb'] == 11000
    assert summary['observed_memory']['native_peak_rss_bytes'] == 1000
    assert summary['observed_memory']['process_reaped'] is True
    assert 'baseline_precision' not in summary
    assert summary['precision_samples'] == []


def test_interrupt_is_recorded_without_replacing_supervisor_cleanup(bench, config, monkeypatch):
    source = write_source(bench, config)
    folder = bench.ROOT / 'outputs/cancelled'

    def execute(_request, output, _timeout):
        # The real execute only raises after the existing supervisor reaps.
        (output / 'worker.json').write_text(json.dumps({'state': 'cancelled', 'process_reaped': True}))
        raise KeyboardInterrupt()

    monkeypatch.setattr(bench, 'execute', execute)
    assert bench.run(source, cold=True, output=folder) == 1
    summary = json.loads((folder / 'benchmark-summary.json').read_text())
    assert summary['state'] == 'cancelled'
    assert summary['observed_memory']['process_reaped'] is True


def test_cold_refuses_existing_folder_and_internal_runtime(bench, config, tmp_path):
    source = write_source(bench, config)
    folder = bench.ROOT / 'outputs/existing'
    folder.mkdir(parents=True)
    (folder / 'result.json').write_text('preserved')
    with pytest.raises(FileExistsError):
        bench.run(source, cold=True, output=folder)
    assert (folder / 'result.json').read_text() == 'preserved'
    with pytest.raises(ValueError):
        bench.run(source, cold=True, output=tmp_path.parent / 'outside')
    config['runtime'] = {'baseline_file': 'outputs/cache/old.policy'}
    source = write_source(bench, config)
    with pytest.raises(ValueError, match='runtime'):
        bench.run(source, cold=True, output=bench.ROOT / 'outputs/must-not-exist')
    assert not (bench.ROOT / 'outputs/must-not-exist').exists()


def test_iteration_limit_is_not_reported_as_accuracy_success(bench, config):
    result = fake_result(config)
    result['precision'].update(baseline_exploitability_chips=.08, baseline_stop_reason='iteration_limit')
    measured = bench.baseline_precision(result, config)
    assert measured['target_met'] is False
    assert measured['actual_pot_pct'] == 1
    assert measured['stop_reason'] == 'iteration_limit'


def test_cold_does_not_claim_complete_without_all_final_policies(bench, config, monkeypatch):
    source = write_source(bench, config)
    folder = bench.ROOT / 'outputs/missing-policy'
    monkeypatch.setattr(bench, 'execute', lambda request, *_args: fake_result(request))
    assert bench.run(source, cold=True, output=folder) == 1
    summary = json.loads((folder / 'benchmark-summary.json').read_text())
    assert 'did not save the baseline policy' in summary['error']
    assert not (folder / 'result.json').exists()
