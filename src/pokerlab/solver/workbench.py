"""Workspace-backed jobs, baseline reuse and complete policy inspection."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager

from .__main__ import ROOT, REV, save_result
from .resources import MIB, memory_resources
from .amounts import scale_node, scale_request, scale_result

VERSION='workbench-br-v4-memory'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def solve_inputs(config):
    """What changes the CFR run itself: profile incentives, or the locks of a locked re-solve."""
    profile=config.get('profile',{});inputs={}
    if profile.get('incentives'):inputs['incentives']=profile['incentives']
    if config.get('mode')=='locked':inputs['locks']=[[o['path'],o['combo'],o['probabilities']] for o in profile['overrides']]
    return inputs


def baseline_key(config):
    fields=('board','players','pot','stack','bets','raises','bets_ip','raises_ip','donks','target','target_unit','max_iterations','schema_version','expand_suits','compression','auto_suits','threads','raise_limit','lines','rake_rate','rake_cap','add_allin_threshold','force_allin_threshold','merging_threshold','chip_scale')
    expanded=config.get('expand_suits',False) and not (config.get('auto_suits',False) and not config.get('profile',{}).get('overrides'))
    return fingerprint({'engine':REV,'adapter':VERSION,'resolved_expanded_suits':expanded,**{k:config[k] for k in fields if k in config},**solve_inputs(config)})


def cfr_key(config):
    # Target and iteration ceiling can change without changing prior DCFR steps.
    fields=('board','players','pot','stack','bets','raises','bets_ip','raises_ip','donks','schema_version','compression','threads','raise_limit','lines','rake_rate','rake_cap','add_allin_threshold','force_allin_threshold','merging_threshold','chip_scale')
    expanded=config.get('expand_suits',False) and not (config.get('auto_suits',False) and not config.get('profile',{}).get('overrides'))
    return fingerprint({'engine':REV,'algorithm':'upstream-dcfr-power4-reset-v1','format':'PLCFR001','expanded':expanded,
                        **{k:config[k] for k in fields if k in config},**solve_inputs(config)})


def checkpoint_iterations(path):
    try:
        with path.open('rb') as stream:
            if stream.read(8)!=b'PLCFR001':return None
            raw_length=stream.read(8)
            if len(raw_length)!=8:return None
            length=int.from_bytes(raw_length,'little')
            if length>1024*1024:return None
            raw_header=stream.read(length)
            if len(raw_header)!=length:return None
            header=json.loads(raw_header)
            if not isinstance(header,dict):return None
            value=header.get('iterations')
            return value if type(value) is int and 0<=value<=0xffffffff else None
    except (OSError,ValueError):return None


def new_job_dir():
    path=ROOT/'outputs/jobs'/uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


@contextmanager
def engine_lock(folder):
    """Serialize native processes across CLI and multiple local server instances."""
    path=ROOT/'outputs/engine.lock';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        if handle.tell()==0:handle.write(b'0');handle.flush()
        locked=False
        try:
            while not locked:
                if (folder/'cancel').exists() or (folder.parent/'cancel').exists():raise RuntimeError('cancelled while queued')
                try:
                    handle.seek(0)
                    if sys.platform=='win32':
                        import msvcrt
                        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    locked=True
                except OSError:time.sleep(.1)
            yield
        finally:
            if locked:
                handle.seek(0)
                if sys.platform=='win32':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


class NodeSessions:
    """Loaded policies kept in the engine, so moving between nodes costs a lookup and not a reload."""
    LIMIT=3

    def __init__(self):
        self.items={};self.lock=threading.Lock()

    def close(self):
        with self.lock:
            for session in self.items.values():self._stop(session)
            self.items.clear()

    def _stop(self,session):
        session['process'].stdin.close()
        try:session['process'].wait(timeout=10)
        except subprocess.TimeoutExpired:session['process'].kill();session['process'].wait()

    def _open(self,request,folder):
        """Load under the engine lock and the same memory budget as a one-off query."""
        with engine_lock(folder):
            resources=memory_resources(request)
            if not resources['ready']:raise ValueError(resources['error'])
            native=copy.deepcopy(request)
            for field in ('memory_auto','memory_stretch','amount_unit','chip_scale'):native.pop(field,None)
            scale_request(native,request.get('chip_scale',1))
            native['memory_budget_mb']=resources['effective_mb']
            relative=folder.relative_to(ROOT).as_posix()
            worker=['scripts/native_worker.py',relative,'--serve']
            if sys.platform=='win32':
                posix='/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:]
                command=['wsl','-d','Ubuntu','--cd',posix,'--','python3',*worker]
            else:command=[sys.executable,*worker]
            process=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            process.stdin.write(json.dumps(native,allow_nan=False)+'\n');process.stdin.flush()
            ready=process.stdout.readline()
        if not ready:
            message=process.stderr.read().replace('\x00','').strip()
            process.wait()
            raise RuntimeError(message or 'native session failed to start')
        return {'process':process,'scale':request.get('chip_scale',1)}

    def query(self,request,path,folder):
        key=(request['runtime']['inspect_file'],request['runtime']['inspect_key'])
        with self.lock:
            session=self.items.pop(key,None)
            if session is None or session['process'].poll() is not None:
                while len(self.items)>=self.LIMIT:self._stop(self.items.pop(next(iter(self.items))))
                try:session=self._open(request,folder)
                except RuntimeError:
                    # Other loaded policies may be what is using the memory budget.
                    while self.items:self._stop(self.items.pop(next(iter(self.items))))
                    session=self._open(request,folder)
            self.items[key]=session
            session['process'].stdin.write(json.dumps(path)+'\n');session['process'].stdin.flush()
            line=session['process'].stdout.readline()
        if not line:raise RuntimeError('native session ended')
        reply=json.loads(line)
        if 'error' in reply:raise RuntimeError(reply['error'])
        return scale_node(reply['node'],session['scale'])


SESSIONS=NodeSessions()


def execute(config, folder=None, timeout=None):
    folder=folder or new_job_dir()
    # A solve needs the memory held by loaded policies.
    SESSIONS.close()
    with engine_lock(folder):
        return _execute_locked(config,folder,timeout)


def _execute_locked(config,folder,timeout):
    relative=folder.relative_to(ROOT).as_posix()
    # Read both boundaries after the shared lock is acquired. Automatic mode is
    # explicit; an old numeric cap is never silently raised for a manual request.
    resources=memory_resources(config)
    save_result(folder/'resources.json',resources)
    if not resources['ready'] and (resources['automatic_budget_mb'] is None or resources['automatic_budget_mb']<128):
        raise ValueError(resources['error'])
    # A deliberately tiny manual cap still reaches the supervisor's existing
    # detailed budget rejection; the UI snapshot correctly marks it unready.
    request=copy.deepcopy(config)
    # The native schema remains the source of truth for poker inputs. This flag
    # controls the Python launcher only and must not reach strict native serde.
    request.pop('memory_auto',None);request.pop('memory_stretch',None)
    request.pop('amount_unit',None)
    chip_scale=request.pop('chip_scale',1)
    scale_request(request,chip_scale)
    request['memory_budget_mb']=resources['effective_mb']
    if sys.platform=='win32':
        posix='/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:]
        command=['wsl','-d','Ubuntu','--cd',posix,'--','python3','scripts/native_worker.py',relative,'--timeout',str(timeout or 0)]
    else:
        command=[sys.executable,'scripts/native_worker.py',relative,'--timeout',str(timeout or 0)]
    proc=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        out,err=proc.communicate(json.dumps(request,allow_nan=False),timeout=timeout+30 if timeout else None)
    except BaseException:
        (folder/'cancel').touch()
        # The supervisor owns the native process group. Killing only its WSL
        # client cannot prove that the native child has exited, so keep the
        # serialization lock until the supervisor finishes its wait/reap path.
        # These short waits are polling intervals, not a cleanup deadline.
        while True:
            try:
                proc.communicate(timeout=1)
                break
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                # A second Ctrl-C must not unlock while native cleanup is active.
                continue
        raise
    if proc.returncode:
        message=err.replace('\x00','').strip() or out.replace('\x00','').strip()
        for line in reversed(message.splitlines()):
            try:
                detail=json.loads(line)
                if isinstance(detail,dict) and 'error' in detail:
                    message=detail['error'];break
            except (ValueError,TypeError):pass
        raise RuntimeError(message)
    result=scale_result(json.loads(out),chip_scale)
    if 'node' not in result and result.get('adapter_version')!='br-policy-v4-memory':
        raise RuntimeError('native adapter version mismatch; rebuild with scripts/build.ps1')
    # CLI reports come directly from this function; restore only launcher/unit
    # metadata explicitly supplied by the caller. Keep native numeric values and
    # the guest's actual request budget intact, and leave old reports unlabelled.
    if isinstance(result.get('config'),dict):
        for field in ('amount_unit','memory_auto','memory_stretch','chip_scale'):
            if field in config:result['config'][field]=config[field]
    # The guest remeasures before launch and can reduce this again. Report its
    # actual limit, not the earlier host-only request as previous versions did.
    final_limit=result.get('worker_resources',{}).get('limit_bytes')
    resources['prelaunch_effective_mb']=request['memory_budget_mb']
    if type(final_limit) is int:
        resources['effective_mb']=min(request['memory_budget_mb'],final_limit//MIB)
    result['resource_budget']=resources
    return result


def solve_cached(config, folder=None, timeout=None):
    if not isinstance(config,dict) or 'runtime' in config:raise ValueError('配置不能指定内部 runtime 路径')
    # Interactive solves have no wall-clock cutoff, including imported legacy
    # configs with time_limit_seconds=600. Explicit test/diagnostic limits only.
    request=copy.deepcopy(config);folder=folder or new_job_dir()
    key=baseline_key(request);model_key=fingerprint({'config':request,'version':VERSION})
    prefix=(folder/'policy').relative_to(ROOT).as_posix()
    baseline=f'outputs/cache/{key}.policy'
    request['runtime']={'baseline_file':baseline,'baseline_key':key,'output_prefix':prefix,'inspect_key':model_key}
    resume_key=cfr_key(request);resume=f'outputs/cache/{resume_key}.cfr'
    saved_iterations=checkpoint_iterations(ROOT/resume)
    # Never load a state beyond the user's requested iteration ceiling.
    if saved_iterations is None or saved_iterations<=request['max_iterations']:
        request['runtime'].update(checkpoint_file=resume,checkpoint_key=resume_key)
    started=time.perf_counter()
    result=execute(request,folder,timeout)
    result['config']=config
    result['config_sha256']=fingerprint(config)
    result['artifacts']={'baseline':baseline,'model':prefix+'.model.policy','response':prefix+'.response.policy','baseline_key':key,'model_key':model_key}
    if config['mode'] in ('equilibrium','locked'):
        result['artifacts'].update(model=baseline,response=baseline,model_key=key)
    result['persistence']='full_final_policy_snapshots_not_CFR_resume_state'
    result['wall_seconds']=time.perf_counter()-started
    result['created_at']=time.time()
    save_result(folder/'result.json',result)
    return result


def inspect(result,path,variant='response',folder=None):
    if variant not in ('baseline','model','response'):raise ValueError('unknown policy variant')
    if not isinstance(path,list) or len(path)>100 or any(type(a)!=int or a<0 for a in path):raise ValueError('invalid node path')
    # Immutable final policies: cache only when config, engine, artifact and path agree.
    started=time.perf_counter()
    policy=ROOT/result['artifacts'][variant];stat=policy.stat()
    key=fingerprint({'version':VERSION,'node_report':2,'config':result['config'],'policy':str(policy),
                     'size':stat.st_size,'mtime_ns':stat.st_mtime_ns,'path':path,'variant':variant})
    cache=ROOT/'outputs/node-cache'/f'{key}.json'
    if cache.exists():
        node=json.loads(cache.read_text(encoding='utf-8'))
        node['query']={'cache_hit':True,'seconds':time.perf_counter()-started}
        return node
    req=copy.deepcopy(result['config'])
    # Keep arbitrary hard-lock probabilities at their saved f32 precision during
    # inspection. This may require more memory than a compressed solve.
    if req.get('compression') and req.get('profile',{}).get('overrides'):
        req['compression']=False
    # Snapshot query never recompiles a model or reruns equilibrium.
    req['runtime']={'inspect_file':result['artifacts'][variant], 'inspect_key':result['artifacts']['baseline_key' if variant=='baseline' else 'model_key'],'query_path':path}
    node=SESSIONS.query(req,path,folder or new_job_dir())
    save_result(cache,node)
    # Bounded expendable cache; never remove saved studies or policy artifacts.
    entries=[p for p in cache.parent.glob('*.json') if len(p.stem)==64 and all(c in '0123456789abcdef' for c in p.stem)]
    entries.sort(key=lambda p:p.stat().st_mtime,reverse=True)
    total=0
    for i,p in enumerate(entries):
        total+=p.stat().st_size
        if i>=256 or total>128*1024**2:
            if p!=cache:p.unlink(missing_ok=True)
    node['query']={'cache_hit':False,'seconds':time.perf_counter()-started}
    return node
