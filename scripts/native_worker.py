"""WSL supervisor: a bounded native process group, cancelled via workspace marker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time


def diagnostic_sample(pid, elapsed_seconds):
    """Read cumulative native CPU and live-thread context counters, not estimates."""
    process = Path(f'/proc/{pid}')
    fields = (process / 'stat').read_text().rsplit(')', 1)[1].split()
    ticks = os.sysconf('SC_CLK_TCK')
    sample = {'elapsed_seconds': elapsed_seconds,
              'user_cpu_seconds': int(fields[11]) / ticks,
              'system_cpu_seconds': int(fields[12]) / ticks,
              'live_thread_voluntary_context_switches': 0,
              'live_thread_involuntary_context_switches': 0,
              'live_threads_sampled': 0}
    memory = {line.split(':', 1)[0]: int(line.split()[1]) * 1024
              for line in (process / 'status').read_text().splitlines()
              if line.startswith(('VmRSS:', 'VmSize:', 'VmSwap:', 'VmHWM:', 'VmPeak:'))}
    sample.update(rss_bytes=memory.get('VmRSS'), vms_bytes=memory.get('VmSize'),
                  swap_bytes=memory.get('VmSwap'), peak_rss_bytes=memory.get('VmHWM'),
                  peak_vms_bytes=memory.get('VmPeak'))
    for task in (process / 'task').iterdir():
        try:
            counters = dict(line.split(':', 1) for line in (task / 'status').read_text().splitlines()
                            if line.startswith(('voluntary_ctxt_switches:', 'nonvoluntary_ctxt_switches:')))
            sample['live_thread_voluntary_context_switches'] += int(counters['voluntary_ctxt_switches'])
            sample['live_thread_involuntary_context_switches'] += int(counters['nonvoluntary_ctxt_switches'])
            sample['live_threads_sampled'] += 1
        except (OSError, KeyError):
            # A worker can exit between listing its task directory and reading it.
            continue
    return sample


def child_usage():
    """Final wait/reap accounting includes terminated native worker threads."""
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {'user_cpu_seconds': usage.ru_utime, 'system_cpu_seconds': usage.ru_stime,
            'voluntary_context_switches': usage.ru_nvcsw,
            'involuntary_context_switches': usage.ru_nivcsw,
            'max_rss_bytes': usage.ru_maxrss * 1024,
            'minor_page_faults': usage.ru_minflt, 'major_page_faults': usage.ru_majflt}


def serve(binary,config,restrict,env):
    """Hold one policy in the engine: one JSON line in, one JSON line out, until stdin closes."""
    proc=subprocess.Popen([str(Path(binary).resolve(strict=True)),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          start_new_session=True,preexec_fn=restrict,env=env)
    try:
        proc.stdin.write(json.dumps(config).encode()+b'\n');proc.stdin.flush()
        def relay():
            line=proc.stdout.readline()
            if not line:raise RuntimeError('native session ended')
            sys.stdout.buffer.write(line);sys.stdout.buffer.flush()
        relay()
        for line in sys.stdin.buffer:
            proc.stdin.write(line);proc.stdin.flush();relay()
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid,signal.SIGKILL)
        proc.wait()


def main():
    p=argparse.ArgumentParser()
    p.add_argument("job")
    p.add_argument("--timeout",type=float,default=0,help='0: no automatic deadline; positive values reserved for explicit diagnostics')
    p.add_argument('--binary', default='./target/release/pokerlab-solver',
                   help='Explicit native executable for controlled A/B diagnostics; default unchanged')
    p.add_argument('--diagnostics', action='store_true',
                   help='Record native CPU/context-switch samples once per second and final child accounting')
    p.add_argument('--serve', action='store_true', help='Keep the loaded policy for node queries on stdin')
    args=p.parse_args()
    folder=Path(args.job); folder.mkdir(parents=True,exist_ok=True)
    config=json.loads(sys.stdin.readline()) if args.serve else json.load(sys.stdin)
    mem={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:'))}
    limit=min(config['memory_budget_mb']*1024**2,max(0,mem['MemAvailable']-512*1024**2))
    if limit<64*1024**2:
        raise RuntimeError('memory budget too low for native worker (WSL)')
    config['memory_budget_mb']=limit//1024**2
    def restrict():
        resource.setrlimit(resource.RLIMIT_AS,(limit,limit))
    if args.serve:
        serve(args.binary,config,restrict,{**os.environ,'MALLOC_ARENA_MAX':'2','MALLOC_MMAP_THRESHOLD_':'131072',
                                           'MALLOC_TRIM_THRESHOLD_':'131072','MALLOC_MMAP_MAX_':'65536'})
        return
    status={'state':'running','supervisor_pid':os.getpid(),'wsl_memory':mem,'limit_bytes':limit}
    stdout=folder/'native.stdout'; stderr=folder/'native.stderr'
    start=time.monotonic(); proc=None
    next_diagnostic=0.0
    diagnostic_phase=None
    diagnostic_log_offset=0
    try:
        if (folder/'cancel').exists() or (folder.parent/'cancel').exists():
            status['state']='cancelled';raise RuntimeError('cancelled before launch')
        with stdout.open('wb') as out,stderr.open('wb') as err:
            native_env=os.environ.copy()
            # Fix the allocator layout before libc initializes. Large continuous
            # engine arrays use their own mappings, while worker-local scratch
            # shares at most two arenas. Neither RAM nor RLIMIT_AS caps increase.
            controlled=not any(native_env.get(k) for k in ('GLIBC_TUNABLES','LD_PRELOAD'))
            profile='glibc-bounded-v1' if controlled else 'unverified-allocator-env'
            native_env.update(MALLOC_ARENA_MAX='2',MALLOC_MMAP_THRESHOLD_='131072',
                              MALLOC_TRIM_THRESHOLD_='131072',MALLOC_MMAP_MAX_='65536',
                              POKERLAB_ALLOCATOR_PROFILE=profile)
            status.update(malloc_arena_max=2,malloc_mmap_threshold=131072,
                          allocator_profile=profile)
            binary=Path(args.binary).resolve(strict=True)
            if args.diagnostics:
                with binary.open('rb') as source:
                    status['binary_sha256']=hashlib.file_digest(source,'sha256').hexdigest()
                status['binary_path']=str(binary)
                status['diagnostic_sample_interval_seconds']=1.0
            proc=subprocess.Popen([str(binary)],stdin=subprocess.PIPE,stdout=out,stderr=err,start_new_session=True,preexec_fn=restrict,env=native_env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            status['native_pid']=proc.pid
            (folder/'worker.json').write_text(json.dumps(status))
            proc.stdin.write(json.dumps(config).encode());proc.stdin.close()
            while proc.poll() is None:
                try:
                    counters={line.split(':',1)[0]:int(line.split()[1])*1024
                              for line in Path(f'/proc/{proc.pid}/status').read_text().splitlines()
                              if line.startswith(('VmHWM:','VmPeak:','VmSwap:'))}
                    for field,source in [('sampled_peak_rss_bytes','VmHWM'),('sampled_peak_vms_bytes','VmPeak'),('sampled_peak_swap_bytes','VmSwap')]:
                        status[field]=max(status.get(field,0),counters.get(source,0))
                except (OSError, StopIteration):
                    pass
                elapsed=time.monotonic()-start
                if args.diagnostics and elapsed>=next_diagnostic:
                    try:
                        # Only complete progress lines update the sampled phase.
                        # This is the last emitted phase, not exact solver timing.
                        with stderr.open('r',encoding='utf-8',errors='replace') as progress_log:
                            progress_log.seek(diagnostic_log_offset)
                            while True:
                                line=progress_log.readline()
                                if not line.endswith('\n'):break
                                diagnostic_log_offset=progress_log.tell()
                                try:
                                    event=json.loads(line)
                                    if isinstance(event,dict) and 'phase' in event:
                                        diagnostic_phase=event['phase']
                                except ValueError:pass
                        sample=diagnostic_sample(proc.pid,elapsed)
                        sample['last_emitted_phase']=diagnostic_phase
                        with (folder/'native-metrics.jsonl').open('a',encoding='utf-8') as samples:
                            samples.write(json.dumps(sample)+'\n')
                        status['diagnostic_sample_count']=status.get('diagnostic_sample_count',0)+1
                        if diagnostic_phase is not None:
                            phase_usage=status.setdefault('sampled_phase_memory',{}).setdefault(diagnostic_phase,{})
                            for field in ('rss_bytes','vms_bytes','swap_bytes'):
                                if sample[field] is not None:
                                    phase_usage['peak_'+field]=max(phase_usage.get('peak_'+field,0),sample[field])
                    except (OSError, ValueError, IndexError) as error:
                        status['diagnostic_sample_error']=str(error)
                    next_diagnostic=elapsed+1.0
                if (folder/'cancel').exists() or (folder.parent/'cancel').exists():
                    status['state']='cancelled';break
                if args.timeout>0 and time.monotonic()-start>args.timeout:
                    status['state']='timeout';break
                time.sleep(.1)
            if proc.poll() is None:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=2)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
            status['exit_code']=proc.returncode
            status['process_reaped']=True
            if args.diagnostics:status['final_native_usage']=child_usage()
        if status['state'] in ('cancelled','timeout'):
            raise RuntimeError(status['state'])
        if proc.returncode:
            status['state']='failed'
            raise RuntimeError(stderr.read_text()[-4000:])
        result=json.loads(stdout.read_text())
        result['worker_resources']=status
        status['state']='completed'
        print(json.dumps(result))
    finally:
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid,signal.SIGKILL);proc.wait();status['process_reaped']=True
        if args.diagnostics and proc is not None and status.get('process_reaped'):
            status['final_native_usage']=child_usage()
        if status['state']=='running':status['state']='failed'
        # Only incomplete files owned by this request; never remove completed policies.
        candidates=list(folder.glob('*.tmp'))
        baseline=config.get('runtime',{}).get('baseline_file')
        if baseline:
            candidate=Path(baseline+'.tmp').resolve()
            if candidate.parent==Path('outputs/cache').resolve():candidates.append(candidate)
        checkpoint=config.get('runtime',{}).get('checkpoint_file')
        if checkpoint and proc is not None:
            target=Path(checkpoint).resolve()
            if target.parent==Path('outputs/cache').resolve():
                candidates.extend(target.parent.glob(f'{target.name}.{proc.pid}.*.tmp'))
        for candidate in candidates:
            if candidate.is_file():candidate.unlink()
        (folder/'worker.json').write_text(json.dumps(status))


if __name__=='__main__':
    try:main()
    except Exception as e:print(str(e),file=sys.stderr);sys.exit(1)
