"""Local named inputs and serial, explicitly frozen model sensitivity studies."""
import copy
import json
import time
import uuid
from .__main__ import ROOT,save_result
from .workbench import solve_cached

def list_library():
    folder=ROOT/'outputs/library'
    return sorted((json.loads(p.read_text(encoding='utf-8')) for p in folder.glob('*.json')),
                  key=lambda v:v['created_at'],reverse=True)

def save_library(data):
    kind=data.get('kind');value=data.get('value');name=str(data.get('name','')).strip()[:80]
    if not name:raise ValueError('请填写名称')
    if kind=='range':
        if not isinstance(value,str) or len(value)>32768:raise ValueError('范围文本无效')
    elif kind=='player':
        if not isinstance(value,list) or len(value)>30:raise ValueError('玩家特质无效')
        allowed={'station','overbluff','underbluff','weak_check','double_barrel_give_up','delayed_aggression'}
        for t in value:
            if not isinstance(t,dict) or t.get('kind') not in allowed or not isinstance(t.get('strength'),(int,float)) or not 0<=t['strength']<=6 or not isinstance(t.get('streets'),list) or not t['streets'] or any(s not in (3,4,5) for s in t['streets']):
                raise ValueError('玩家特质参数无效')
    else:raise ValueError('未知库类型')
    record={'id':uuid.uuid4().hex,'kind':kind,'name':name,'value':value,'created_at':time.time()}
    save_result(ROOT/'outputs/library'/f"{record['id']}.json",record)
    return record

def sensitivity(config,folder,progress):
    records=[]
    for index,(label,factor) in enumerate((('轻度',.5),('中心',1),('重度',1.5))):
        if (folder/'cancel').exists():raise RuntimeError('cancelled')
        request=copy.deepcopy(config);request['mode']='fixed'
        for trait in request.get('profile',{}).get('traits',[]):trait['strength']=min(6,trait['strength']*factor)
        child=folder/f'variant-{index}';child.mkdir()
        progress(index,label)
        report=solve_cached(request,child)
        records.append({'label':label,'factor':factor,'report':report})
    # Root actions only; no claim that an unchanged root action proves full-tree stability.
    hero=config['hero'];root=records[1]['report']['root'];stability=[]
    if root['actor']==hero:
        for h,combo in enumerate(root['players'][hero]['combos']):
            choices=[]
            for entry in records:
                n=entry['report']['root'];count=len(n['players'][hero]['combos'])
                choices.append(max(range(len(n['actions'])),key=lambda a:n['strategy_action_major'][a*count+h]))
            stability.append({'combo':combo,'actions':[root['actions'][a] for a in choices],'stable':len(set(choices))==1})
    return {'config':config,'records':records,'root_stability':stability,
            'comparison_basis':'Each baseline and BR EV pair uses its own same frozen opponent. Do not subtract EV across different opponents as strategy improvement.'}
