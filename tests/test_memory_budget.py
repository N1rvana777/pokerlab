"""Resource safety boundaries and the launcher's explicit automatic/manual contract."""
from contextlib import contextmanager
import copy
import json
from types import SimpleNamespace

import pytest

from pokerlab.solver import resources, workbench

MB = resources.MIB


def measured(host_available=20480, guest_available=14336):
    return ({'total': 32768 * MB, 'available': host_available * MB},
            {'MemTotal': 15872 * MB, 'MemAvailable': guest_available * MB})


def test_automatic_budget_does_not_keep_the_legacy_4g_ceiling():
    host, guest = measured()
    config = {'memory_budget_mb': 4096, 'memory_auto': True}
    report = resources.resolve_memory_budget(config, host, guest)
    assert report['ready']
    assert report['mode'] == 'automatic'
    assert report['configured_mb'] == 4096
    assert report['requested_mb'] is None
    assert report['effective_mb'] == report['automatic_budget_mb'] == 13824
    assert config == {'memory_budget_mb': 4096, 'memory_auto': True}


def test_memory_the_vm_holds_but_does_not_use_counts_towards_the_budget():
    host, guest = measured(host_available=7168, guest_available=14336)
    assert resources.resolve_memory_budget({'memory_budget_mb': 4096, 'memory_auto': True}, host, guest)['automatic_budget_mb'] == 5120
    host['vm_resident'] = 7680 * MB  # 1536 MiB is in use inside the guest, so 6144 MiB is idle.
    report = resources.resolve_memory_budget({'memory_budget_mb': 4096, 'memory_auto': True}, host, guest)
    assert report['windows']['vm_idle_mb'] == 6144
    assert report['automatic_budget_mb'] == 11264


def test_the_vm_side_still_caps_a_budget_with_idle_memory():
    host, guest = measured(host_available=20480, guest_available=14336)
    host['vm_resident'] = 15872 * MB
    assert resources.resolve_memory_budget({'memory_budget_mb': 4096, 'memory_auto': True}, host, guest)['automatic_budget_mb'] == 13824


def test_a_vm_using_all_it_holds_adds_nothing():
    host, guest = measured(host_available=7168, guest_available=12288)
    host['vm_resident'] = 2048 * MB
    report = resources.resolve_memory_budget({'memory_budget_mb': 4096, 'memory_auto': True}, host, guest)
    assert report['windows']['vm_idle_mb'] == 0
    assert report['automatic_budget_mb'] == 5120


def test_stretching_is_an_explicit_choice_and_keeps_six_gib_for_windows():
    host, guest = measured(host_available=13312, guest_available=14336)
    guest['MemTotal'] = guest['MemAvailable'] = 28672 * MB
    config = {'memory_budget_mb': 4096, 'memory_auto': True}
    plain = resources.resolve_memory_budget(config, host, guest)
    assert plain['automatic_budget_mb'] == plain['effective_mb'] == 11264
    assert plain['stretch_budget_mb'] == 24576
    stretched = resources.resolve_memory_budget({**config, 'memory_stretch': True}, host, guest)
    assert stretched['effective_mb'] == 24576


def test_stretching_never_passes_the_vm_or_the_total_limit():
    host, guest = measured(host_available=13312, guest_available=14336)
    report = resources.resolve_memory_budget({'memory_budget_mb': 4096, 'memory_auto': True, 'memory_stretch': True}, host, guest)
    assert report['effective_mb'] == 13824
    host['total'] = 24576 * MB
    guest['MemTotal'] = guest['MemAvailable'] = 24000 * MB
    report = resources.resolve_memory_budget({'memory_budget_mb': 4096, 'memory_auto': True, 'memory_stretch': True}, host, guest)
    assert report['effective_mb'] == 18432


def test_a_manual_cap_still_holds_when_stretching():
    report = resources.resolve_memory_budget({'memory_budget_mb': 4096, 'memory_stretch': True}, *measured())
    assert report['effective_mb'] == 4096


@pytest.mark.parametrize('mode', [{}, {'memory_auto': False}])
def test_explicit_and_legacy_manual_caps_are_respected(mode):
    report = resources.resolve_memory_budget({'memory_budget_mb': 4096, **mode}, *measured())
    assert report['mode'] == 'manual'
    assert report['requested_mb'] == report['effective_mb'] == 4096
    assert report['automatic_budget_mb'] > report['effective_mb']


@pytest.mark.parametrize('host_available,guest_available,expected', [
    (7168, 14336, 5120),  # Windows headroom is the limiting boundary.
    (20480, 4096, 3584),  # WSL VM availability, not Windows total RAM.
    (2048, 14336, 0),
    (20480, 512, 0),
])
def test_both_measured_boundaries_keep_their_reserves(host_available, guest_available, expected):
    report = resources.resolve_memory_budget(None, *measured(host_available, guest_available))
    assert report['effective_mb'] == expected
    assert report['ready'] is (expected >= 128)
    if not report['ready']:
        assert '安全预算' in report['error']


def test_manual_cap_is_reduced_when_free_ram_falls():
    report = resources.resolve_memory_budget({'memory_auto': False, 'memory_budget_mb': 4096}, *measured(4096, 4096))
    assert report['requested_mb'] == 4096
    assert report['effective_mb'] == 2048


def test_tiny_manual_budget_is_shown_as_unready():
    report = resources.resolve_memory_budget({'memory_auto': False, 'memory_budget_mb': 64}, *measured())
    assert not report['ready']
    assert report['effective_mb'] == 64
    assert report['automatic_budget_mb'] == 13824


def test_global_cap_and_native_linux_boundary():
    report = resources.resolve_memory_budget(None, {'total': 128000 * MB, 'available': 100000 * MB},
                                            {'MemTotal': 65536 * MB, 'MemAvailable': 60000 * MB})
    assert report['effective_mb'] == resources.MAX_BUDGET_MB
    linux = resources.resolve_memory_budget(None, *measured(0, 4096), windows=False)
    assert linux['windows'] is None
    assert linux['effective_mb'] == 3584


@pytest.mark.parametrize('mode', ['false', 0, 1, None])
def test_memory_mode_cannot_be_accidentally_enabled_by_truthiness(mode):
    with pytest.raises(ValueError, match='memory_auto'):
        resources.resolve_memory_budget({'memory_budget_mb': 4096, 'memory_auto': mode}, *measured())


@pytest.mark.parametrize('budget', [True, 0, 24577, 4096.0, '4096'])
def test_invalid_configured_budgets_are_rejected(budget):
    with pytest.raises(ValueError, match='memory_budget_mb'):
        resources.resolve_memory_budget({'memory_budget_mb': budget, 'memory_auto': True}, *measured())


def test_meminfo_uses_available_physical_ram_not_free_ram_or_swap():
    counters = resources.parse_meminfo('MemTotal: 16000 kB\nMemFree: 2 kB\nMemAvailable: 8000 kB\nSwapFree: 999999 kB\n')
    assert counters == {'MemTotal': 16000 * 1024, 'MemAvailable': 8000 * 1024}
    for invalid in ('MemTotal: 16000 kB\n', 'MemTotal: 16000 B\nMemAvailable: 8000 kB',
                    'MemTotal: 16000 kB\nMemAvailable: 18000 kB'):
        with pytest.raises(ValueError):
            resources.parse_meminfo(invalid)


def test_guest_probe_failure_is_unavailable_and_preserves_the_error(monkeypatch):
    monkeypatch.setattr(resources, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(resources.psutil, 'virtual_memory', lambda: SimpleNamespace(total=32768 * MB, available=20000 * MB))
    captured = {}

    def denied(command, **kwargs):
        captured.update(kwargs)
        assert command == ['wsl', '-d', 'Ubuntu', '--', 'cat', '/proc/meminfo']
        return SimpleNamespace(returncode=1, stdout='', stderr='WSL denied')

    monkeypatch.setattr(resources.subprocess, 'run', denied)
    report = resources.memory_resources()
    assert not report['ready']
    assert report['effective_mb'] is None and report['automatic_budget_mb'] is None
    assert report['windows']['available_mb'] == 20000
    assert report['wsl'] is None
    assert 'WSL denied' in report['error']
    assert captured['creationflags'] == getattr(resources.subprocess, 'CREATE_NO_WINDOW', 0)


@pytest.mark.parametrize('after_mb,expected_budget_mb', [(14000, 11952), (22000, 14848)])
def test_windows_budget_is_measured_after_guest_probe(monkeypatch, after_mb, expected_budget_mb):
    monkeypatch.setattr(resources, 'sys', SimpleNamespace(platform='win32'))
    events = []

    def host_memory():
        events.append('host')
        available = 20000 if events == ['host'] else after_mb
        return SimpleNamespace(total=32768 * MB, available=available * MB)

    def guest_probe(*args, **kwargs):
        events.append('guest')
        return SimpleNamespace(returncode=0, stderr='',
                               stdout='MemTotal: 16252928 kB\nMemAvailable: 15728640 kB\n')

    monkeypatch.setattr(resources.psutil, 'virtual_memory', host_memory)
    monkeypatch.setattr(resources.subprocess, 'run', guest_probe)
    monkeypatch.setattr(resources, 'vm_resident', lambda: 0)
    report = resources.memory_resources()
    assert events == ['host', 'guest', 'host']
    assert report['windows']['available_mb'] == after_mb
    assert report['effective_mb'] == expected_budget_mb
    assert report['windows']['reserve_mb'] == 2048
    assert report['wsl']['reserve_mb'] == 512
    assert report['measured_at_unix_ms'] > 0
    assert report['probe_seconds'] >= 0


def test_launch_remeasures_inside_lock_strips_mode_and_reports_actual_guest_cap(tmp_path, monkeypatch):
    folder = tmp_path / 'job'
    folder.mkdir()
    monkeypatch.setattr(workbench, 'ROOT', tmp_path)
    active = False
    captured = {}

    @contextmanager
    def lock(_):
        nonlocal active
        active = True
        try:
            yield
        finally:
            active = False

    def live_snapshot(config):
        assert active, 'resource snapshots taken while queued can become stale'
        return resources.resolve_memory_budget(config, *measured(8192, 8192))

    class NativeProcess:
        returncode = 0

        def communicate(self, value=None, **kwargs):
            captured['request'] = json.loads(value)
            native_config = {**captured['request'], 'memory_budget_mb': 5500}
            return json.dumps({'adapter_version': 'br-policy-v4-memory',
                               'config': native_config,
                               'worker_resources': {'limit_bytes': 5500 * MB, 'process_reaped': True}}), ''

    monkeypatch.setattr(workbench, 'engine_lock', lock)
    monkeypatch.setattr(workbench, 'memory_resources', live_snapshot)
    def launch(command, **kwargs):
        assert kwargs['creationflags'] == getattr(workbench.subprocess, 'CREATE_NO_WINDOW', 0)
        return NativeProcess()

    monkeypatch.setattr(workbench.subprocess, 'Popen', launch)
    config = {'memory_auto': True, 'memory_budget_mb': 4096, 'amount_unit': 'bb',
              'board': ['9h', '8h', '2c'], 'pot': 20, 'stack': 200}
    original = copy.deepcopy(config)
    result = workbench.execute(config, folder=folder)
    assert config == original
    assert 'memory_auto' not in captured['request']
    assert 'amount_unit' not in captured['request']
    assert captured['request']['board'] == original['board']
    assert captured['request']['memory_budget_mb'] == 6144
    assert result['resource_budget']['prelaunch_effective_mb'] == 6144
    assert result['resource_budget']['effective_mb'] == 5500
    assert result['config']['memory_auto'] is True and result['config']['amount_unit'] == 'bb'
    assert result['config']['memory_budget_mb'] == 5500
    assert result['config']['pot'] == 20 and result['config']['stack'] == 200
    assert json.loads((folder / 'resources.json').read_text())['effective_mb'] == 6144


@pytest.mark.parametrize('node', [False, True])
def test_cli_metadata_is_not_invented_for_legacy_requests_or_node_reports(tmp_path, monkeypatch, node):
    monkeypatch.setattr(workbench, 'ROOT', tmp_path)
    monkeypatch.setattr(workbench, 'memory_resources', lambda c: resources.resolve_memory_budget(c, *measured()))

    class NativeProcess:
        returncode = 0

        def communicate(self, value=None, **kwargs):
            report = {'node': {'path': []}} if node else {'adapter_version': 'br-policy-v4-memory', 'config': json.loads(value)}
            return json.dumps(report), ''

    monkeypatch.setattr(workbench.subprocess, 'Popen', lambda *a, **k: NativeProcess())
    config = {'memory_budget_mb': 4096, 'pot': 20}
    if node:
        config.update(memory_auto=True, amount_unit='bb')
    result = workbench._execute_locked(config, tmp_path, 10)
    if node:
        assert 'config' not in result
        assert result['node'] == {'path': []}
    else:
        assert 'memory_auto' not in result['config'] and 'amount_unit' not in result['config']
        assert result['config']['pot'] == 20


def test_unavailable_resources_prevent_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, 'ROOT', tmp_path)
    monkeypatch.setattr(workbench, 'memory_resources', lambda _: {'ready': False, 'automatic_budget_mb': None, 'error': 'guest probe failed'})
    monkeypatch.setattr(workbench.subprocess, 'Popen', lambda *a, **k: pytest.fail('launched despite unavailable budget'))
    with pytest.raises(ValueError, match='guest probe failed'):
        workbench._execute_locked({'memory_budget_mb': 4096}, tmp_path, 10)


def test_resource_mode_does_not_change_the_numerical_baseline_key():
    config = {'board': ['9h', '8h', '2c'], 'pot': 20, 'stack': 200,
              'memory_auto': False, 'memory_budget_mb': 4096}
    automatic = {**config, 'memory_auto': True, 'memory_budget_mb': 10000}
    assert workbench.baseline_key(config) == workbench.baseline_key(automatic)


def test_studio_validator_preserves_explicit_memory_mode():
    from pokerstudio.solver import default_config, validate_config
    config = default_config('river.json')
    for mode in (True, False):
        assert validate_config({**config, 'memory_auto': mode})['memory_auto'] is mode
    with pytest.raises(ValueError, match='memory_auto'):
        validate_config({**config, 'memory_auto': 'false'})


def test_studio_validator_accepts_unit_metadata_without_converting_values():
    from pokerstudio.solver import default_config, validate_config
    config = default_config('river.json')
    for unit in ('bb', 'chips'):
        parsed = validate_config({**config, 'amount_unit': unit})
        assert parsed['amount_unit'] == unit
        assert parsed['pot'] == config['pot'] and parsed['stack'] == config['stack']
    with pytest.raises(ValueError, match='amount_unit'):
        validate_config({**config, 'amount_unit': 'USD'})


def test_storage_diagnostic_does_not_send_python_memory_mode_to_native(monkeypatch):
    from scripts import diagnose_tree
    captured = {}

    def native(*args, **kwargs):
        captured.update(json.loads(kwargs['input']))
        return SimpleNamespace(returncode=0, stdout=json.dumps({'estimate_only': True, 'solver_game_allocated': False}), stderr='')

    monkeypatch.setattr(diagnose_tree.subprocess, 'run', native)
    config = {'memory_auto': True, 'memory_budget_mb': 4096, 'amount_unit': 'bb'}
    diagnose_tree.estimate(config, storage=True)
    assert captured == {'memory_budget_mb': 4096, 'runtime': {'storage_estimate_only': True}}
    assert config['memory_auto'] is True
