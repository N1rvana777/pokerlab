"""Loopback-only Chinese workbench; one serialized native job at a time."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import shutil
import socket
import threading
import time
from urllib.parse import parse_qs,urlsplit
import uuid
import os
import psutil

from .__main__ import ROOT,save_result
from .workbench import SESSIONS,solve_cached,inspect,new_job_dir
from .hand_classes import annotate
from .preflop import walks
from .reports import flop_report
from .research import list_library,save_library,sensitivity

WEB=Path(__file__).with_name('web')


class LocalSolverServer(ThreadingHTTPServer):
    allow_reuse_address=os.name!='nt'
    def server_bind(self):
        if os.name=='nt':self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


def with_classes(report):
    """Classes depend on the board and node equity, so they are added on the way out, not stored."""
    for field in ('node','root'):
        if isinstance(report.get(field),dict):annotate(report[field])
    return report


class Jobs:
    def __init__(self):
        self.pool=ThreadPoolExecutor(max_workers=1)
        self.items={};self.lock=threading.Lock();self.owned=set()
        for path in (ROOT/'outputs/jobs').glob('*/status.json'):
            try:
                item=json.loads(path.read_text(encoding='utf-8'))
                if item.get('state') in ('queued','running','cancelling'):
                    alive=False
                    try:alive=psutil.Process(item['owner_pid']).create_time()==item.get('owner_started')
                    except (KeyError,psutil.Error):pass
                    if not alive:
                        (path.parent/'cancel').touch();item['state']='interrupted';save_result(path,item)
                self.items[path.parent.name]=item
            except (ValueError,OSError):pass

    def source(self,source):
        if not isinstance(source,str) or not re.fullmatch('[a-f0-9]{32}',source):raise ValueError('invalid result id')
        for folder in ('studies','jobs'):
            path=ROOT/'outputs'/folder/source/'result.json'
            if path.exists():return json.loads(path.read_text(encoding='utf-8'))
        raise ValueError('结果不存在')

    def submit(self,data):
        if data.get('kind') not in ('solve','node','save','sensitivity','flop_report'):raise ValueError('未知任务')
        with self.lock:
            if sum(j['state'] in ('queued','running','cancelling') for j in self.items.values())>=8:raise ValueError('任务队列已满')
            folder=new_job_dir();key=folder.name
            item={'id':key,'state':'queued','kind':data['kind'],'created_at':time.time(),'owner_pid':os.getpid(),'owner_started':psutil.Process().create_time()}
            if type(data.get('config_revision')) is int:item['config_revision']=data['config_revision']
            if data.get('source')=='agent' or data.get('source_entry')=='agent':item['source_entry']='agent'
            self.owned.add(key)
            self.items[key]=item;save_result(folder/'status.json',item)
            self.pool.submit(self._run,key,folder,copy.deepcopy(data))
        return item.copy()

    def _run(self,key,folder,data):
        item=self.items[key]
        try:
            if (folder/'cancel').exists():raise RuntimeError('cancelled')
            item['state']='running';save_result(folder/'status.json',item)
            if data['kind']=='solve':
                result=solve_cached(data['config'],folder)
                result['result_id']=key;save_result(folder/'result.json',result)
            elif data['kind']=='sensitivity':
                def progress(index,label):
                    item['progress']={'phase':'sensitivity','detail':{'index':index,'label':label}}
                result=sensitivity(data['config'],folder,progress)
                save_result(folder/'result.json',result)
            elif data['kind']=='flop_report':
                def progress(index,total,board):
                    item['progress']={'phase':'flop_report','detail':{'index':index,'total':total,'board':board}}
                save_result(folder/'result.json',flop_report(data['config'],data.get('boards'),folder,progress))
            elif data['kind']=='node':
                source=self.source(data['source'])
                result={'node':inspect(source,data.get('path',[]),data.get('variant','response'),folder)}
                save_result(folder/'result.json',result)
            else:
                result=self.source(data['source']);study=ROOT/'outputs/studies'/key;study.mkdir(parents=True)
                for variant in ('baseline','model','response'):
                    target=study/(variant+'.policy')
                    shutil.copy2(ROOT/result['artifacts'][variant],target)
                    result['artifacts'][variant]=target.relative_to(ROOT).as_posix()
                result['result_id']=key;result['study_name']=str(data.get('name','研究'))[:80]
                save_result(study/'result.json',result)
                save_result(folder/'result.json',{'study_id':key,'name':result['study_name']})
            item['state']='cancelled' if (folder/'cancel').exists() else 'completed'
        except Exception as e:
            item['state']='cancelled' if (folder/'cancel').exists() else 'failed';item['error']=str(e)
        finally:
            item['finished_at']=time.time();save_result(folder/'status.json',item)

    def status(self,key):
        if key not in self.items:raise ValueError('任务不存在')
        item=self.items[key].copy()
        log=ROOT/'outputs/jobs'/key/'native.stderr'
        if log.exists():
            lines=log.read_text(encoding='utf-8',errors='replace').splitlines()
            for line in reversed(lines[-5:]):
                try:item['progress']=json.loads(line);break
                except ValueError:pass
        return item

    def cancel(self,key):
        item=self.items.get(key)
        if item is None:raise ValueError('任务不存在')
        if item['state'] in ('queued','running'):
            (ROOT/'outputs/jobs'/key/'cancel').touch();item['state']='cancelling'
        return item.copy()

    def close(self):
        if getattr(self,'agent_service',None):self.agent_service.close()
        for key in list(self.owned):self.cancel(key)
        self.pool.shutdown(wait=True)
        SESSIONS.close()


def make_server(port=8765,server_class=LocalSolverServer,agent_dir=None,agent_factory=None):
    from .agent import SolverAgent,RevisionConflict
    from pokerstudio.agent.service import public_error
    jobs=Jobs();token=secrets.token_urlsafe(32)
    solver=None
    allowed={f'127.0.0.1:{port}',f'localhost:{port}'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,value,status=200,content_type='application/json; charset=utf-8'):
            raw=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(raw)
        def check(self,write=False):
            if self.headers.get('Host') not in allowed:raise ValueError('invalid Host')
            origin=self.headers.get('Origin')
            if origin and origin not in {f'http://{h}' for h in allowed}:raise ValueError('cross-origin access denied')
            if self.headers.get('Sec-Fetch-Site')=='cross-site':raise ValueError('cross-site access denied')
            if write and not secrets.compare_digest(self.headers.get('X-Pokerlab-Token',''),token):raise ValueError('invalid local session token')
        def do_GET(self):
            try:
                self.check();url=urlsplit(self.path);path=url.path;q=parse_qs(url.query)
                query=lambda key,default=None:q.get(key,[default])[0]
                if path=='/':self.reply((WEB/'index.html').read_bytes().replace(b'__TOKEN__',token.encode()),content_type='text/html; charset=utf-8')
                elif path in ('/app.js','/range.js','/controls.js','/research.js','/node_view.js','/study.js','/reports.js','/preflop.js','/style.css','/agent.js','/agent.css','/integration.js','/coach.js'):self.reply((WEB/path[1:]).read_bytes(),content_type='application/javascript' if path.endswith('.js') else 'text/css')
                elif path=='/api/resources':
                    from .resources import memory_resources
                    self.reply(memory_resources())
                elif path in ('/api/agent/config','/api/solver/config'):self.reply(solver.snapshot())
                elif path=='/api/bootstrap':self.reply({'token':token,'solver':solver.snapshot(),'agent_sessions':solver.list_sessions()})
                elif path=='/api/agent/status':self.reply(solver.status(query('provider')))
                elif path=='/api/agent/models':self.reply(solver.models(query('provider','subscription')))
                elif path=='/api/agent/sessions':self.reply(solver.list_sessions())
                elif path=='/api/agent/task':self.reply(solver.get(query('id',''),int(query('after','0'))))
                elif path=='/api/coach/hands':self.reply({'hands':solver.coach.list_hands(query('status','all'),query('player'),int(query('limit','100')))})
                elif path=='/api/coach/hand':self.reply(solver.coach.hand_detail(query('id',''),int(query('revision')) if query('revision') else None))
                elif path=='/api/coach/players':self.reply({'players':solver.coach.players(),'hero_names':solver.coach.hero_names(),
                    'priors':{k:solver.coach.priors[k] for k in ('version','calibrated','description','strength')},
                    'data_dir':str(solver.coach.root),'load_warnings':solver.coach.load_warnings})
                elif path=='/api/coach/player':self.reply(solver.coach.player_profile(query('name','')))
                elif path=='/api/coach/settings':self.reply(solver.coach.settings())
                elif path=='/api/library':self.reply(list_library())
                elif path=='/api/preflop':self.reply(walks())
                elif path=='/api/examples':self.reply({name:json.loads((ROOT/'examples'/name).read_text()) for name in ('river.json','flop_research.json','flop_research_raises.json','station_overbluff.json')})
                elif path=='/api/studies':
                    studies=[]
                    for p in (ROOT/'outputs/studies').glob('*/result.json'):
                        r=json.loads(p.read_text(encoding='utf-8'));studies.append({'id':p.parent.name,'name':r.get('study_name','研究')})
                    self.reply(studies)
                elif path.startswith('/api/jobs/'):
                    key=path.split('/')[3]
                    if path.endswith('/result'):
                        if jobs.status(key)['state']!='completed':raise ValueError('任务未完成')
                        self.reply(with_classes(json.loads((ROOT/'outputs/jobs'/key/'result.json').read_text(encoding='utf-8'))))
                    else:self.reply(jobs.status(key))
                elif path.startswith('/api/studies/'):self.reply(with_classes(jobs.source(path.split('/')[-1])))
                else:self.reply({'error':'not found'},404)
            except Exception as e:self.reply({'error':public_error(e)},409 if isinstance(e,RevisionConflict) else 400)
        def do_POST(self):
            try:
                self.check(True)
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=16*1024*1024:raise ValueError('invalid request size')
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict):raise ValueError('JSON request must be an object')
                path=urlsplit(self.path).path
                if path=='/api/library':self.reply(save_library(data),201)
                elif path=='/api/jobs':
                    if data.get('kind')=='solve':
                        state=solver.update(data['config'],expected_revision=data.get('expected_revision',solver.snapshot()['revision']))
                        data={**data,'config':state['config'],'config_revision':state['revision']}
                    submitted=jobs.submit(data)
                    if data.get('kind')=='solve':solver.track_job(submitted)
                    self.reply(submitted,202)
                elif path.startswith('/api/jobs/') and path.endswith('/cancel'):self.reply(jobs.cancel(path.split('/')[3]))
                elif path in ('/api/agent/config','/api/solver/config'):
                    self.reply(solver.update(data.get('config'),patch=data.get('patch'),expected_revision=data.get('expected_revision')))
                elif path=='/api/agent/configure-subscription':self.reply(solver.service.configure_subscription(data['mode']))
                elif path=='/api/agent/configure-api':self.reply(solver.service.configure_api(data['api_key'],data.get('model'),data.get('allow_paid',False)))
                elif path=='/api/agent/login':self.reply(solver.service.login('subscription',data.get('mode')))
                elif path=='/api/agent/logout':self.reply(solver.service.logout())
                elif path=='/api/agent/cancel-login':self.reply(solver.service.cancel_login(data.get('login_id')))
                elif path=='/api/agent/start':self.reply(solver.start(data['message'],data.get('provider','subscription'),data.get('model'),data.get('session_id'),data.get('expected_revision')),202)
                elif path=='/api/agent/cancel':self.reply(solver.cancel(data['id']))
                elif path=='/api/coach/import':self.reply({'results':solver.coach.import_text(str(data.get('text','')))})
                elif path=='/api/coach/confirm':self.reply(solver.coach.confirm(data['hand_id'],data['revision'],by='user'))
                elif path=='/api/coach/unconfirm':self.reply(solver.coach.unconfirm(data['hand_id'],by='user'))
                elif path=='/api/coach/alias':self.reply(solver.coach.link_alias(data['name'],data['target']))
                elif path=='/api/coach/hero':self.reply(solver.coach.set_hero(data['names']))
                elif path=='/api/coach/note':self.reply(solver.coach.add_note(data['player'],data['text'],data.get('hand_ids',[]),'user'))
                elif path=='/api/coach/default-game':self.reply(solver.coach.set_default_game(data['preset']))
                else:self.reply({'error':'not found'},404)
            except Exception as e:self.reply({'error':public_error(e)},409 if isinstance(e,RevisionConflict) else 400)
    try:server=server_class(('127.0.0.1',port),Handler)
    except BaseException:
        jobs.close()
        raise
    allowed={f'127.0.0.1:{server.server_port}',f'localhost:{server.server_port}'}
    try:solver=(agent_factory or SolverAgent)(jobs,data_dir=agent_dir)
    except BaseException:
        server.server_close();jobs.close();raise
    server.jobs=jobs;server.solver_agent=solver;jobs.agent_service=solver
    return server


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    server=make_server(args.port)
    print(f'PokerLab: http://127.0.0.1:{args.port}  (Ctrl+C to stop)',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();server.jobs.close()


if __name__=='__main__':main()
