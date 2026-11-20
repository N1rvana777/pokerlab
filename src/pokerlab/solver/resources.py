"""Measured host/guest memory caps; automatic mode never changes the poker tree.

Call ``memory_resources()`` for a live UI snapshot. Execution must call it again
inside the existing engine lock: queued jobs cannot reserve an old snapshot.
The guest supervisor still applies its own fresh cap and RLIMIT_AS afterwards.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

import psutil

MIB = 1024 ** 2
HOST_RESERVE_MB = 2048
GUEST_RESERVE_MB = 512
STRETCH_RESERVE_MB = 6144  # What Windows keeps once idle programs are paged out; only with memory_stretch.
MAX_BUDGET_MB = 24576


def _settings(config):
    if config is None:
        return True, None
    automatic = config.get('memory_auto', False)
    if type(automatic) is not bool:
        raise ValueError('memory_auto 必须为布尔值')
    configured = config.get('memory_budget_mb')
    if type(configured) is not int or not 1 <= configured <= MAX_BUDGET_MB:
        raise ValueError(f'memory_budget_mb 必须为 1..{MAX_BUDGET_MB} 的整数 MiB')
    return automatic, configured


def parse_meminfo(value: str) -> dict[str, int]:
    """Read the two required Linux counters as bytes; never count swap as RAM."""
    counters = {}
    for line in value.splitlines():
        key, separator, rest = line.partition(':')
        if separator and key in ('MemTotal', 'MemAvailable'):
            fields = rest.split()
            if len(fields) != 2 or fields[1] != 'kB':
                raise ValueError(f'无法读取 Linux {key} 的 kB 单位')
            counters[key] = int(fields[0]) * 1024
    if set(counters) != {'MemTotal', 'MemAvailable'}:
        raise ValueError('Linux 内存信息缺少 MemTotal/MemAvailable')
    if not 0 <= counters['MemAvailable'] <= counters['MemTotal'] or counters['MemTotal'] <= 0:
        raise ValueError('Linux 内存信息数值无效')
    return counters


def _memory(total, available, reserve):
    if type(total) is not int or type(available) is not int or not 0 <= available <= total or total <= 0:
        raise ValueError('系统内存信息数值无效')
    return {'total_mb': total // MIB, 'available_mb': available // MIB,
            'reserve_mb': reserve, 'safe_mb': max(0, available // MIB - reserve)}


def resolve_memory_budget(config, host, guest, *, windows=True):
    """Pure calculation used by live probing and tests. Counters are bytes.

    Windows available RAM already reflects currently allocated WSL RAM. We keep
    the host's existing 2 GiB reserve, and separately respect the WSL VM's current
    available RAM minus 512 MiB. Native Linux has only the latter boundary.
    Pages the VM still holds after a solve are missing from Windows' figure, yet the
    guest can reuse them at once, so ``vm_resident`` beyond what the guest is using
    counts towards the host side. It credits resident pages only, never the VM's
    uncommitted capacity.
    ``memory_stretch`` is an explicit choice to let Windows page idle programs out,
    so the host side becomes total RAM minus 6 GiB; the machine can feel slower.
    An absent mode flag remains manual for saved configurations and CLI callers.
    """
    automatic, configured = _settings(config)
    win = _memory(host['total'], host['available'], HOST_RESERVE_MB) if windows else None
    linux = _memory(guest['MemTotal'], guest['MemAvailable'], GUEST_RESERVE_MB)
    if win:
        win['vm_idle_mb'] = max(0, host.get('vm_resident', 0) - (guest['MemTotal'] - guest['MemAvailable'])) // MIB
        win['safe_mb'] += win['vm_idle_mb']
    safe = min(MAX_BUDGET_MB, linux['safe_mb'], win['safe_mb'] if win else MAX_BUDGET_MB)
    stretched = min(MAX_BUDGET_MB, linux['safe_mb'], max(win['safe_mb'], win['total_mb'] - STRETCH_RESERVE_MB)) if win else safe
    if config is not None and config.get('memory_stretch') is True:
        safe = stretched
    effective = safe if automatic else min(configured, safe)
    ready = effective >= 128
    return {'ready': ready, 'mode': 'automatic' if automatic else 'manual',
            'configured_mb': configured, 'requested_mb': None if automatic else configured,
            'effective_mb': effective, 'automatic_budget_mb': safe, 'stretch_budget_mb': stretched,
            'windows': win, 'wsl': linux, 'max_budget_mb': MAX_BUDGET_MB,
            'error': None if ready else f'当前任务预算仅 {effective} MiB（可用安全预算 {safe} MiB），请调整手动上限或释放内存后重试'}


def vm_resident():
    """Bytes the WSL VM holds in Windows RAM; 0 when it is not running or cannot be read."""
    for process in psutil.process_iter(['name']):
        if (process.info['name'] or '').lower().startswith('vmmem'):
            try:
                return int(process.memory_info().rss)
            except psutil.Error:
                return 0
    return 0


def memory_resources(config=None):
    """Return a fresh, JSON-serializable resource snapshot without launching a solver.

    ``memory_auto=true`` explicitly opts in to a measured budget. A retained
    ``memory_budget_mb`` is ignored only in this mode. A failed guest probe makes
    the budget unavailable rather than assuming that the VM has host-sized RAM.
    """
    automatic, configured = _settings(config)
    host = None
    started = time.monotonic()
    try:
        measured = psutil.virtual_memory()
        host = {'total': int(measured.total), 'available': int(measured.available)}
        if sys.platform == 'win32':
            probe = subprocess.run(['wsl', '-d', 'Ubuntu', '--', 'cat', '/proc/meminfo'],
                                   capture_output=True, text=True, encoding='utf-8', timeout=8,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if probe.returncode:
                detail = (probe.stderr or probe.stdout).replace('\x00', '').strip()
                raise RuntimeError(f'WSL 内存读取失败（exit {probe.returncode}）：{detail}')
            guest = parse_meminfo(probe.stdout)
            # A cold WSL probe can itself bring resident VM pages into Windows.
            # Admission must use host availability after that probe, not the
            # larger snapshot from before the guest started. Never credit the
            # VM's uncommitted capacity as reclaimable physical host memory.
            measured = psutil.virtual_memory()
            host = {'total': int(measured.total), 'available': int(measured.available), 'vm_resident': vm_resident()}
        else:
            guest = parse_meminfo(Path('/proc/meminfo').read_text(encoding='ascii'))
        report = resolve_memory_budget(config, host, guest, windows=sys.platform == 'win32')
        report['measured_at_unix_ms'] = int(time.time() * 1000)
        report['probe_seconds'] = time.monotonic() - started
        return report
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        return {'ready': False, 'mode': 'automatic' if automatic else 'manual',
                'configured_mb': configured, 'requested_mb': None if automatic else configured,
                'effective_mb': None, 'automatic_budget_mb': None,
                'windows': _memory(host['total'], host['available'], HOST_RESERVE_MB)
                           if host is not None and sys.platform == 'win32' else None,
                'wsl': None, 'max_budget_mb': MAX_BUDGET_MB, 'error': str(error)}
