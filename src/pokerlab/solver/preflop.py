"""Preflop range libraries: private files under outputs/gtow-preflop, never in Git.

A tree (raw/tree_<depth>.json) holds what the pages showed node by node: every action with its combos and the action
shares of each hand class. `walk_tree` serves those as they are, and gets the ranges of a closed line by multiplying
each seat's shares along its own actions.

A library holds only the two ranges at the flop for each captured line. `walk` infers a decision tree from those.
Frequencies come from the ranges: what a seat continues with, divided by what it arrived with. Actions no line covers
(limps, shoves, 4-bets) are not separated from folding. A depth with a tree does not use its library.
"""
import json
from .__main__ import ROOT

SCHEMA='pokerlab-preflop-v1'
FOLDER=ROOT/'outputs/gtow-preflop'
SEATS=('UTG','LJ','HJ','CO','BTN','SB','BB','STR')
POSTFLOP=('SB','BB','STR','UTG','LJ','HJ','CO','BTN')
BLINDS={'SB':.5,'BB':1,'STR':2}
RARE_COMBOS=2.0  # A line with fewer combos on one side almost never happens at this equilibrium.
LISTED_LINES=30
UNREAD='这条线没有抄录：出现频率太低，或第三名玩家入池后没有继续读'
RANKS='AKQJT98765432'
CLASSES=tuple(RANKS[a]+RANKS[b]+('' if a==b else 's' if a<b else 'o') if a<=b else RANKS[b]+RANKS[a]+'o' for a in range(13) for b in range(13))

def load_libraries():
    libraries=[]
    for path in sorted(FOLDER.glob('*.json')):
        try:data=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        if isinstance(data,dict) and data.get('schema')==SCHEMA and isinstance(data.get('lines'),list):libraries.append(data)
    return libraries

def load_trees():
    """One tree per depth. Captures are never rewritten: a later one, tree_<depth>_<part>.json, only adds nodes."""
    trees={}
    for path in sorted((FOLDER/'raw').glob('tree_*.json')):
        try:data=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        if not (isinstance(data,dict) and data.get('depth') and isinstance(data.get('nodes'),dict)):continue
        if data['depth'] in trees:trees[data['depth']]['nodes'].update(data['nodes'])
        else:trees[data['depth']]=data
    return list(trees.values())

def replay(tokens,depth=0):
    """Who acts next, chips in front and who is left. Tokens are F, C, X, R<raise-to> or RAI, a raise to the whole depth."""
    put={seat:BLINDS.get(seat,0) for seat in SEATS};pending=list(SEATS);folded=set();shoved=set();current=2
    for token in tokens:
        seat=pending.pop(0)
        if token=='F':folded.add(seat)
        elif token=='C':put[seat]=current
        elif token!='X':
            current=depth if token=='RAI' else float(token[1:]);put[seat]=current;at=SEATS.index(seat)
            if token=='RAI':shoved.add(seat)
            pending=[SEATS[(at+k)%8] for k in range(1,8) if SEATS[(at+k)%8] not in folded|shoved]
    live=[seat for seat in SEATS if seat not in folded]
    return {'seat':pending[0] if pending and len(live)>1 else None,'pending':pending if len(live)>1 else [],'put':put,'current':current,'live':live}

def weights(text):
    out={}
    for part in filter(None,(p.strip() for p in text.split(','))):
        name,_,value=part.partition(':');out[name]=float(value or 1)
    return out

def class_combos(name):
    return 6 if len(name)==2 else 4 if name.endswith('s') else 12

def label(token):
    return {'F':'Fold','C':'Call','X':'Check','RAI':'Allin'}.get(token) or f'Raise {token[1:]}'

def walk(library):
    """The clickable tree of a library, or the same dict without nodes if it has no lines."""
    lines={line['actions']:line for line in library['lines']};options={};after={};depth=None
    for actions,line in lines.items():
        tokens=actions.split('-')
        held={line['oop_seat']:weights(line['oop']),line['ip_seat']:weights(line['ip'])}
        depth=depth or line['stack']+replay(tokens)['put'][line['oop_seat']]
        for at,token in enumerate(tokens):
            path='-'.join(tokens[:at]);seat=replay(tokens[:at])['seat']
            options.setdefault(path,{}).setdefault(token)
            if token!='F' and not any(replay(tokens[:k])['seat']==seat for k in range(at+1,len(tokens))):after[path,token]=held[seat]
    nodes={path:node(path,list(choices),after,depth) for path,choices in options.items()}
    closed={actions:{key:line[key] for key in ('id','label','oop_seat','ip_seat','pot','stack','oop','ip','oop_combos','ip_combos','rare')} for actions,line in lines.items()}
    return {key:library.get(key) for key in ('id','title','source','note')}|{'depth':depth,'nodes':nodes,'lines':closed}

def node(path,choices,after,depth):
    tokens=path.split('-') if path else [];state=replay(tokens);seat=state['seat']
    joined=lambda token:'-'.join(tokens+[token])
    base={'seat':seat,'pending':state['pending'],'pot':sum(state['put'].values()),'stack':depth-state['put'][seat],'to_call':state['current']-state['put'][seat]}
    known=sorted((t for t in choices if t!='F' and (path,t) in after),key=lambda t:-float(t[1:]) if t[0]=='R' else 0)
    if not known:return base|{'forced':True,'actions':[{'code':'F','label':'Fold','next':joined('F')}]}
    earlier=next((at for at in reversed(range(len(tokens))) if replay(tokens[:at])['seat']==seat),None)
    reach=None if earlier is None else after.get(('-'.join(tokens[:earlier]),tokens[earlier]))
    if earlier is not None and reach is None:return base|{'actions':[{'code':t,'label':label(t),'next':joined(t)} for t in known]}
    hands={};combos=[0.0]*(len(known)+1)
    for name in CLASSES:
        arrived=1 if reach is None else reach.get(name,0)
        if arrived<=0:continue
        shares=[min(1,after[path,t].get(name,0)/arrived) for t in known]
        shares.append(max(0,1-sum(shares)))
        hands[name]=[round(share,4) for share in shares]
        for i,share in enumerate(shares):combos[i]+=class_combos(name)*arrived*share
    total=sum(combos) or 1
    actions=[{'code':t,'label':label(t),'next':joined(t)} for t in known]
    actions.append({'code':'F','label':'Fold','next':joined('F')} if 'F' in choices else {'code':None,'label':'Fold' if earlier is None else '弃牌 / 4bet / 全下','next':None})
    for action,count in zip(actions,combos):action.update(combos=round(count,1),frequency=round(count/total,4))
    return base|{'actions':actions,'hands':hands}

def cell_shares(cell,count):
    """Action shares of one hand class at a node: '' is a class the seat does not hold, 'i' is pure, 'i:bp;j:bp' mixes."""
    if cell=='':return None
    out=[0.0]*count
    if ':' not in cell:out[int(cell)]=1.0
    for part in filter(None,cell.split(';') if ':' in cell else ()):
        at,value=part.split(':');out[int(at)]=int(value)/10000
    return out

def chained(tree,tokens,seat):
    """A seat's weight of each class after these tokens: its shares multiplied along its own actions."""
    out=dict.fromkeys(tree['names'],1.0)
    for at,token in enumerate(tokens):
        source=tree['nodes']['-'.join(tokens[:at])]
        if source['seat']!=seat:continue
        index=[action[0] for action in source['actions']].index(token)
        for name,cell in zip(tree['names'],source['cells']):
            shares=cell_shares(cell,len(source['actions']))
            out[name]*=shares[index] if shares else 0.0
    return out

def range_text(held):
    return ','.join(name if value>=1 else f'{name}:{value:g}' for name in CLASSES if (value:=round(held[name],4))>0)

def line_label(tokens,depth):
    raises=0;parts=[]
    for at,token in enumerate(tokens):
        seat=replay(tokens[:at],depth)['seat']
        if token=='C':parts.append(f'{seat} {"跟注" if raises else "limp"}')
        elif token=='X':parts.append(f'{seat} 过牌')
        elif token!='F':
            raises+=1;name=('加注' if parts else '开池') if raises==1 else f'{raises+1}bet'
            parts.append(f'{seat} 全下' if token=='RAI' else f'{seat} {name} {token[1:]}bb')
    return ' · '.join(parts)

def finish(tree,tokens,lines,ends):
    """File a closed line: a heads-up flop goes to `lines`, anything the engine has nothing to do with to `ends`."""
    depth=tree['depth'];key='-'.join(tokens);state=replay(tokens,depth);live=state['live'];pot=round(sum(state['put'].values()),2)
    held={seat:chained(tree,tokens,seat) for seat in live}
    combos={seat:sum(class_combos(name)*weight for name,weight in held[seat].items()) for seat in live}
    if min(combos.values())<.01:return
    if len(live)==1:ends[key]={'kind':'won','text':f'{live[0]} 收下底池 {pot:g}bb，这手牌在翻前结束。'}
    elif any(state['put'][seat]>=depth for seat in live):
        ends[key]={'kind':'allin','text':f'{"、".join(live)} 翻前全下，底池 {pot:g}bb，没有翻后决策。范围：'+'，'.join(f'{seat} {combos[seat]:.1f} 组合' for seat in live)+'。'}
    elif len(live)>2:ends[key]={'kind':'multiway','text':f'{len(live)} 人入池（{"、".join(live)}），底池 {pot:g}bb。翻后引擎只解两人，这条线不能解算。'}
    else:
        oop,ip=sorted(live,key=POSTFLOP.index);rare=min(combos.values())<RARE_COMBOS
        lines[key]={'id':key,'label':line_label(tokens,depth)+('（几乎不出现）' if rare else ''),'oop_seat':oop,'ip_seat':ip,'pot':pot,'stack':depth-state['put'][oop],
                    'oop':range_text(held[oop]),'ip':range_text(held[ip]),'oop_combos':round(combos[oop],1),'ip_combos':round(combos[ip],1),'rare':rare}

def walk_tree(tree):
    """The clickable tree of a capture, with `lines` for heads-up flops and `ends` for what else finishes a hand."""
    depth=tree['depth'];nodes={};lines={};ends={}
    for path,source in tree['nodes'].items():
        tokens=path.split('-') if path else [];state=replay(tokens,depth);seat=state['seat']
        total=sum(action[3] for action in source['actions']) or 1;actions=[]
        for code,_,_,combos in source['actions']:
            after=tokens+[code];key='-'.join(after)
            if combos and key not in tree['nodes'] and replay(after,depth)['seat'] is None:finish(tree,after,lines,ends)
            known=key in tree['nodes'] or key in lines or key in ends
            actions.append({'code':code,'label':label(code),'next':key if known else None,'combos':round(combos,1),'frequency':round(combos/total,4)}|({} if known else {'note':UNREAD}))
        hands={name:shares for name,cell in zip(tree['names'],source['cells']) if (shares:=cell_shares(cell,len(actions)))}
        nodes[path]={'seat':seat,'pending':state['pending'],'pot':round(sum(state['put'].values()),2),'stack':depth-state['put'][seat],'to_call':state['current']-state['put'][seat],'actions':actions,'hands':hands}
    note=(f'模型 SB 0.5 / BB 1 / STR 2，{depth}bb = {depth//2} 个 straddle。对应 $5/$5/$10：1bb = $5，STR = 现场 BB，{depth}bb = ${depth*5}；现场 SB 是 1bb，比模型多 0.5bb。'
          '频率、组合数和每手牌的比例都是页面上的数字；闭合后的范围由这些比例逐步相乘。灰色按钮的线没有继续抄录。')
    return {'id':f'tree_{depth}','title':f'8max Straddle cEV {depth}bb','source':tree.get('source','GTO Wizard 预解 Straddle、cEV（无抽水）、含 cold call、开池 7bb（盲注位 6bb），2026-11-01 逐节点抄录'),'note':note,
            'depth':depth,'complete':True,'nodes':nodes,'lines':lines,'ends':ends}

def walks():
    trees=[walk_tree(tree) for tree in load_trees()];read={book['depth'] for book in trees}
    return sorted(trees+[book for book in map(walk,load_libraries()) if book['depth'] not in read],key=lambda book:book['depth'] or 0)

def find_lines(depth,seats=None,line=None):
    """Heads-up lines of the depth nearest `depth`, most common first; with `line`, that line and both its ranges."""
    books=[book for book in walks() if book.get('lines')]
    if not books:raise ValueError('这台机器上没有翻前范围库')
    book=min(books,key=lambda item:abs(item['depth']-depth))
    head={key:book[key] for key in ('id','title','depth','note')}
    if line is not None:
        if line not in book['lines']:raise ValueError(f'{book["depth"]}bb 没有这条线：{line}')
        return head|{'line':line}|book['lines'][line]
    found=[{'line':key}|{name:item[name] for name in ('label','oop_seat','ip_seat','pot','stack','oop_combos','ip_combos','rare')}
           for key,item in book['lines'].items() if set(seats or ())<={item['oop_seat'],item['ip_seat']}]
    found.sort(key=lambda item:-min(item['oop_combos'],item['ip_combos']))
    return head|{'lines':found[:LISTED_LINES],'total':len(found)}
