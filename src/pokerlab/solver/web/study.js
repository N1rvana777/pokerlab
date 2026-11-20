// Player profiles, locked re-solves and the study views beyond strategy, EV and equity.

// Virtual incentives in percent of the pot. Only the opponent is biased; Hero best-responds.
const playerProfiles={fish:['Fish',{check:-6,call:4}],station:['Calling Station',{check:2,call:6,bet:-3}],glass:['Glass Cannon',{fold:5,check:1,bet:4}],maniac:['Maniac',{fold:-6,call:3,bet:6}],nit:['Nit',{fold:7,check:2,bet:-3}],tag:['TAG Reg',{fold:2,check:2,call:-2}],lag:['LAG Reg',{fold:-3,bet:3}]};
const incentiveFields=[['bet','Bet / Raise'],['check','Check'],['fold','Fold'],['call','Call']];
const profileBox=el('section',undefined,'profile-box');profileBox.id='profile-box';
const profileSelect=el('select');profileSelect.id='player-profile';profileSelect.append(new Option('不用 Profile（GTO）',''));
for(const [key,[label]]of Object.entries(playerProfiles))profileSelect.append(new Option(label,key));
profileSelect.append(new Option('自定义','custom'));
const profileLabel=el('label','Player Profile（对手）');profileLabel.append(profileSelect);
const profileInputs=el('div',undefined,'profile-inputs');profileInputs.id='profile-inputs';
const incentiveInputs={};
for(const [key,label]of incentiveFields){const box=el('label',label),input=el('input');input.type='number';input.step='1';input.min='-50';input.max='50';input.value='0';input.id='incentive-'+key;input.addEventListener('input',()=>{profileSelect.value='custom';changed()});incentiveInputs[key]=input;box.append(input);profileInputs.append(box)}
const profileStreet=el('select');profileStreet.id='profile-street';profileStreet.append(new Option('所有街：对手一直这样打','all'),new Option('只这一街：后续街按均衡打','first'));
const profileStreetLabel=el('label','作用范围');profileStreetLabel.append(profileStreet);profileInputs.append(profileStreetLabel);profileStreet.onchange=()=>changed();
profileBox.append(profileLabel,profileInputs,el('p','数字是虚拟激励（% 底池），加在对手每个决策的对应动作上，不是频率，也不计入 EV。第 3 步先解出带激励的对手，再算 Hero 最佳回应。“只这一街”是 GTO Wizard 的做法，一次解一条街；“所有街”让 Hero 提前利用对手后面的错误，所以翻牌和转牌频率会不同。','hint'));
$('combined').before(profileBox);
function readIncentives(){
  if(!profileSelect.value)return null;
  const values=Object.fromEntries(incentiveFields.map(([key])=>[key,+incentiveInputs[key].value]).filter(([,v])=>v));
  return Object.keys(values).length?values:null;
}
function fillIncentives(values){for(const [key]of incentiveFields)incentiveInputs[key].value=values?.[key]??0;profileInputs.hidden=!profileSelect.value}
profileSelect.onchange=()=>{fillIncentives(playerProfiles[profileSelect.value]?.[1]);changed()};
profileInputs.hidden=true;
const configBeforeProfile=getConfig;
let upstreamLocks=[];
// One copy of the scene per node: it holds both ranges, and repeating it for every combo of a wide lock outgrows the request limit.
function compactLocks(list){
  const seen=new Set();
  return list.map(o=>{const key=JSON.stringify(o.path);if(!seen.has(key)){seen.add(key);return o}const {scene,...rest}=o;return rest});
}
getConfig=function(mode='fixed'){
  const c=configBeforeProfile(mode);
  if(mode==='locked'){c.profile={traits:[],overrides:[...compactLocks(structuredClone(overrides)),...upstreamLocks]};return c}
  if(mode==='equilibrium')return c;
  // A lock on Hero's own node only means something when both seats are solved again.
  c.profile.overrides=compactLocks(c.profile.overrides.filter(o=>o.seat===undefined||o.seat!==c.hero));
  const incentives=readIncentives();
  if(incentives){if(profileStreet.value==='first')incentives.streets=[c.board.length];c.profile.incentives=incentives}
  return c;
};
const setConfigBeforeProfile=setConfig;
setConfig=function(c){
  setConfigBeforeProfile(c);
  const {streets,...rates}=c.profile?.incentives||{},values=c.profile?.incentives?rates:null,match=Object.entries(playerProfiles).find(([,[,v]])=>JSON.stringify(Object.entries(v).sort())===JSON.stringify(Object.entries(rates).sort()));
  profileSelect.value=!values?'':match?match[0]:'custom';fillIncentives(values);profileStreet.value=streets?'first':'all';
};

// Locked re-solve: only the locked combos stay fixed; both seats are solved again around them.
let lockBase=null,lockBaseConfig=null;
const lockedSolve=el('button','4 · 只锁这些节点，重新求解双方');lockedSolve.id='locked-solve';lockedSolve.type='button';
const lockUpstream=el('select');lockUpstream.id='lock-upstream';lockUpstream.append(new Option('不锁上游','none'),new Option('锁全部上游','all'),new Option('只锁该玩家的上游','player'));
const lockUpstreamLabel=el('label','到锁定节点之前的节点');lockUpstreamLabel.append(lockUpstream);
const lockedHelp=el('p',undefined,'workflow-help');lockedHelp.append(el('strong','其余节点双方都会调整。'),'第 3 步是把对手整棵树冻住、只优化 Hero；这一步只固定你锁的组合，对手其他节点也会重新适应。上游选项和 GTO Wizard 的三个选项相同：不锁时上游也重新求解；锁全部时走到这里的路线保持基线；只锁该玩家时对方的上游仍会调整。GTO Wizard 默认锁全部。');
$('override-count').before(lockUpstreamLabel,lockedSolve,lockedHelp);
async function frozenUpstream(){
  // Each node on the way to a lock keeps its baseline strategy. A lock set on that node by hand wins.
  if(lockUpstream.value==='none')return [];
  if(!lockBase||!sameScene(getConfig('locked'),lockBaseConfig))throw Error('要锁上游，先解出当前局面的基线。');
  const out=[],done=new Set(),own=new Set(overrides.map(o=>JSON.stringify(o.path)+o.combo));
  for(const lock of overrides)for(let depth=0;depth<lock.path.length;depth++){
    const at=lock.path.slice(0,depth),key=JSON.stringify(at);
    if(done.has(key))continue;
    const n=(await runJob({kind:'node',source:lockBase,path:at,variant:'baseline'})).node;
    if(n.chance||n.terminal||(lockUpstream.value==='player'&&n.actor!==lock.seat))continue;
    done.add(key);
    const p=n.players[n.actor],count=p.combos.length;
    p.combos.forEach((combo,i)=>{if(p.raw_reach[i]>0&&!own.has(key+combo))out.push({path:at,combo,probabilities:roundShares(n.actions.map((_,a)=>n.strategy_action_major[a*count+i]))})});
  }
  return out;
}
lockedSolve.onclick=()=>guard(async()=>{
  if(!overrides.length)throw Error('还没有节点锁。先解出基线，走到要锁的节点，在下方 Node Lock 里添加。');
  if(result?.config?.mode==='equilibrium'&&sameScene(getConfig('locked'),result.config)){lockBase=result.result_id;lockBaseConfig=result.config}
  upstreamLocks=await frozenUpstream();
  await solve('locked');
});
const nodeBeforeLock=showNode;
showNode=async function(){
  await nodeBeforeLock();
  if(result?.config?.mode!=='locked'||!lockBase||!node||node.terminal||node.chance)return;
  comparison=(await runJob({kind:'node',source:lockBase,path,variant:'baseline'})).node;
  renderNode();
};
function lockCompareTable(){
  // Each column uses its own reach, so the table shows what the seat really does in that solution.
  const table=el('table'),head=el('tr');table.id='lock-compare';
  ['动作','锁定前','锁定后','变化'].forEach(t=>head.append(el('th',t)));table.append(head);
  const before=allCombosStrategy(comparison),after=allCombosStrategy(node);
  node.actions.forEach((a,i)=>{const at=comparison.actions.indexOf(a),old=at<0?NaN:before.probabilities[at],row=el('tr');[actionLabel(a),fmt(old*100,1)+'%',fmt(after.probabilities[i]*100,1)+'%',fmt((after.probabilities[i]-old)*100,1)].forEach(v=>row.append(el('td',v)));table.append(row)});
  const u=unitOf(result.config),ev=n=>n.players.map((p,seat)=>rangeStats(p,p.combos.map((_,i)=>i),eqrPot(seat)).ev);
  const was=ev(comparison),now=ev(node);
  for(const seat of [0,1]){const row=el('tr');[(seat?'IP':'OOP')+' 平均 EV ('+u+')',fmt(was[seat]),fmt(now[seat]),fmt(now[seat]-was[seat])].forEach(v=>row.append(el('td',v)));table.append(row)}
  return table;
}

// Frequency lock: shift hands by EV until the whole range hits the target frequencies.
function frequencyShares(n,targets,ids){
  const p=n.players[n.actor],count=p.combos.length,tau=Math.max(n.pot*.002,1e-6),weights=ids.map(i=>p.raw_reach[i]),total=weights.reduce((s,w)=>s+w,0);
  const scale=n.actions.map(()=>1);let shares=[];
  for(let round=0;round<3000;round++){
    shares=ids.map(i=>{
      const values=n.actions.map((_,a)=>targets[a]>0?n.action_ev_action_major[a*count+i]/tau:-Infinity),top=Math.max(...values);
      const raw=values.map((v,a)=>targets[a]>0?Math.exp(v-top)*scale[a]:0),sum=raw.reduce((s,v)=>s+v,0);
      return raw.map(v=>v/sum);
    });
    const reached=n.actions.map((_,a)=>shares.reduce((s,row,k)=>s+weights[k]*row[a],0)/total);
    let worst=0;
    n.actions.forEach((_,a)=>{if(targets[a]<=0)return;worst=Math.max(worst,Math.abs(reached[a]-targets[a]));scale[a]*=targets[a]/Math.max(reached[a],1e-9)});
    if(worst<1e-4)break;
  }
  return shares;
}
const roundShares=row=>{const out=row.map(v=>Math.round(v*1e6)/1e6),top=out.indexOf(Math.max(...out));out[top]=0;out[top]=+(1-out.reduce((s,v)=>s+v,0)).toFixed(6);return out};
const freqBox=el('section',undefined,'freq-lock');freqBox.id='freq-lock';
const freqInputs=el('div',undefined,'profile-inputs');freqInputs.id='freq-inputs';
const freqApply=el('button','按总频率生成节点锁');freqApply.type='button';freqApply.id='freq-apply';
const freqNote=el('p',undefined,'hint');freqNote.id='freq-note';
freqBox.append(el('h4','按总频率锁定'),freqInputs,freqApply,freqNote,el('p','填目标频率（%，合计 100）。EV 损失最小的手牌先调整，所以价值和诈唬的结构会保留。范围取上方“锁定范围”；选 Filters 时只调整选中的组合。','hint'));
$('lock-total').after(freqBox);
function renderFreqLock(){
  freqInputs.replaceChildren();freqNote.textContent='';
  const open=node&&!node.terminal&&!node.chance;freqApply.disabled=!open;if(!open)return;
  const data=allCombosStrategy(node);
  node.actions.forEach((a,i)=>{const box=el('label',actionLabel(a)),input=el('input');input.type='number';input.min=0;input.max=100;input.step=1;input.value=fmt(data.probabilities[i]*100,1);box.append(input);freqInputs.append(box)});
}
const manualBeforeFreq=renderManual;
renderManual=function(){manualBeforeFreq();renderFreqLock()};
freqApply.onclick=()=>guard(async()=>{
  if(!result||!sameScene(getConfig(),result.config))throw Error('当前局面／树已改变，请先重新求解，再定位节点。');
  const p=node.players[node.actor],combos=p.combos,scoped=$('lock-scope').value==='one'?'all':$('lock-scope').value;
  const allowed=new Set(eligibleCombos()),ids=combos.map((c,i)=>i).filter(i=>allowed.has(combos[i])&&p.blocker_adjusted_weights[i]>0&&p.raw_reach[i]>0&&(scoped!=='filter'||comboPasses(i))&&(scoped!=='group'||group(combos[i])===selected));
  if(!ids.length)throw Error('选中范围没有可达组合');
  const targets=[...freqInputs.querySelectorAll('input')].map(e=>Number(e.value)/100),sum=targets.reduce((s,v)=>s+v,0);
  if(targets.some(v=>!Number.isFinite(v)||v<0)||Math.abs(sum-1)>.01)throw Error('目标频率必须非负，合计 100%');
  const shares=frequencyShares(node,targets.map(v=>v/sum),ids);
  captureEdit();
  ids.forEach((i,k)=>{const combo=combos[i];overrides=overrides.filter(o=>JSON.stringify(o.path)!==JSON.stringify(path)||o.combo!==combo);overrides.push({path:[...path],combo,probabilities:roundShares(shares[k]),scene:sceneOf(getConfig()),board:[...node.board],actions:[...node.actions],seat:node.actor})});
  changed();captureEdit();
  freqNote.textContent=`已为 ${ids.length} 个组合生成节点锁，重算后生效。`;
});

// Extra grid modes.
const compareBar=el('div',undefined,'toolbar');compareBar.id='compare-bar';compareBar.hidden=true;
const compareFirst=el('select'),compareSecond=el('select');compareFirst.id='compare-first';compareSecond.id='compare-second';
compareBar.append(el('span','比较 EV'),compareFirst,el('span','减去'),compareSecond);
gridModes.after(compareBar);
compareFirst.onchange=compareSecond.onchange=()=>paintStrategy();
for(const [mode,label]of [['range','范围高度'],['compare','比较 EV']]){const b=el('button',label);b.type='button';b.dataset.mode=mode;b.onclick=()=>{gridMode=mode;paintStrategy()};gridModes.append(b)}
const mergeLabel=el('label','合并尺寸'),mergeSizes=el('input');mergeSizes.type='checkbox';mergeSizes.id='merge-sizes';mergeLabel.prepend(mergeSizes);gridModes.append(mergeLabel);
mergeSizes.onchange=()=>paintStrategy();
function fillCompare(){
  const first=compareFirst.value,second=compareSecond.value;
  compareFirst.replaceChildren(...node.actions.map((a,i)=>new Option(actionLabel(a),i)));
  compareSecond.replaceChildren(...node.actions.map((a,i)=>new Option(actionLabel(a),i)),new Option('最佳动作','best'));
  compareFirst.value=node.actions[first]!==undefined?first:'0';
  compareSecond.value=second==='best'||node.actions[second]!==undefined?second:String(Math.min(1,node.actions.length-1));
}
function classIds(p,name){return p.combos.map((c,i)=>group(c)===name&&comboPasses(i)&&p.blocker_adjusted_weights[i]>0?i:-1).filter(i=>i>=0)}
function paintCompare(){
  fillCompare();
  const p=node.players[node.actor],n=p.combos.length,first=+compareFirst.value,second=compareSecond.value,u=unitOf(result.config);
  const ev=(a,i)=>node.action_ev_action_major[a*n+i],best=i=>Math.max(...node.actions.map((_,a)=>ev(a,i))),gap=i=>ev(first,i)-(second==='best'?best(i):ev(+second,i));
  const scale=Math.max(node.pot*.1,1e-9);
  for(const b of $('grid').children){
    const ids=classIds(p,b.dataset.hand);if(!ids.length)continue;
    const mass=ids.reduce((s,i)=>s+p.blocker_adjusted_weights[i],0),value=ids.reduce((s,i)=>s+p.blocker_adjusted_weights[i]*gap(i),0)/mass;
    b.style.background=heat(value,-scale,scale);b.replaceChildren(el('span',b.dataset.hand,'cell-hand'),el('small',fmt(value,2),'cell-value'));
    b.title=b.dataset.hand+' · EV 差 '+fmt(value)+' '+u;
  }
}
function paintRangeHeight(){
  const p=node.players[node.actor],colors=node.actions.map((a,i)=>actionStyle(a,i,node.actions));
  for(const b of $('grid').children){
    const ids=classIds(p,b.dataset.hand);if(!ids.length)continue;
    const reach=ids.reduce((s,i)=>s+p.raw_reach[i],0)/ids.length,data=allCombosStrategy(node,ids);if(!data.mass)continue;
    b.style.background=`${strategyGradient(data.probabilities,colors)} left bottom / 100% ${Math.max(reach*100,2)}% no-repeat`;
    b.replaceChildren(el('span',b.dataset.hand,'cell-hand'),el('small',fmt(reach*100,0)+'%','cell-value'));
  }
}
const cellsBeforeStudy=paintCells;
paintCells=function(){
  cellsBeforeStudy();
  compareBar.hidden=gridMode!=='compare'||!node||node.terminal||node.chance;
  if(!node||node.terminal||node.chance)return;
  if(gridMode==='compare')paintCompare();
  if(gridMode==='range')paintRangeHeight();
  if(result?.config?.mode==='locked'&&comparison)$('node-model-preview').replaceChildren(el('strong','当前节点 · 锁定前 → 锁定后'),lockCompareTable());
};
const cardsBeforeMerge=paintActionCards;
paintActionCards=function(){
  cardsBeforeMerge();
  if(!mergeSizes.checked||!node||node.terminal||node.chance)return;
  const data=weightedStrategy(node),groups=new Map(),old=[...actionCards.children];
  node.actions.forEach((a,i)=>{const kind=actionCategory(a,i),key=kind==='overbet'?'aggressive':kind;(groups.get(key)||groups.set(key,[]).get(key)).push(i)});
  actionCards.replaceChildren(...[...groups.values()].map(list=>{
    if(list.length===1)return old[list[0]];
    const share=list.reduce((s,i)=>s+data.probabilities[i],0),card=el('div',undefined,'action-card');card.style.background=actionStyle(node.actions[list[0]],list[0],node.actions);card.style.flexGrow=String(Math.max(.18,share));
    card.append(el('span',`下注 / 加注（${list.length} 个尺寸）`,'action-card-name'),el('strong',data.mass?fmt(share*100,1)+'%':'—'),el('small',fmt(data.mass*share,1)+' combos'));
    return card;
  }));
};

// Extra node tabs.
function addNodeTab(key,label){const panel=el('div'),b=el('button',label);panel.id='node-'+key;b.type='button';b.dataset.tab=key;b.onclick=()=>{nodeTab=key;showNodeTab()};tabBar.append(b);nodeRight.append(panel);nodeTabs.push([key,label,panel]);return panel}
const tabRanges=addNodeTab('ranges','Ranges'),tabBreakdown=addNodeTab('breakdown','Breakdown'),tabBlockers=addNodeTab('blockers','Blockers');
const decisionHint=panel=>{if(node.terminal||node.chance){panel.replaceChildren(el('p','进入决策节点后查看。','hint'));return false}return true};

let blockerSort=null;
function renderBlockers(){
  if(!decisionHint(tabBlockers))return;
  const p=node.players[node.actor],base=allCombosStrategy(node),deck=[...'AKQJT98765432'].flatMap(r=>[...'shdc'].map(s=>r+s)).filter(c=>!node.board.includes(c));
  const rows=deck.map(card=>{const ids=p.combos.map((c,i)=>c.slice(0,2)!==card&&c.slice(2,4)!==card?i:-1).filter(i=>i>=0),data=allCombosStrategy(node,ids);return {card,values:data.probabilities.map((v,a)=>v-base.probabilities[a])}});
  if(blockerSort!==null&&blockerSort<node.actions.length)rows.sort((a,b)=>b.values[blockerSort]-a.values[blockerSort]);
  const table=el('table'),head=el('tr');table.id='blocker-table';head.append(el('th','牌'));
  node.actions.forEach((a,i)=>{const th=el('th',actionLabel(a));th.dataset.sort=i;th.onclick=()=>{blockerSort=blockerSort===i?null:i;renderBlockers()};head.append(th)});table.append(head);
  const total=el('tr');total.append(el('td','全部'));base.probabilities.forEach(v=>total.append(el('td',fmt(v*100,1)+'%')));table.append(total);
  for(const row of rows){const line=el('tr');line.dataset.card=row.card;line.append(el('td',row.card));row.values.forEach(v=>{const cell=el('td',(v>0?'+':'')+fmt(v*100,2));cell.className=v>.0005?'gain':v<-.0005?'loss':'';line.append(cell)});table.append(line)}
  tabBlockers.replaceChildren(el('p',(node.actor===0?'OOP':'IP')+' 行动。每行表示对手拿着这张牌时，行动者各动作频率的变化（百分点）。到对手节点看，就是你的这张牌会让对手多做或少做什么。点表头排序。','hint'),table);
}

function renderBreakdown(){
  if(!decisionHint(tabBreakdown))return;
  if(!node.class_labels){tabBreakdown.replaceChildren(el('p','这个节点没有分类数据。','hint'));return}
  const p=node.players[node.actor],ids=p.combos.map((_,i)=>i),combos=i=>p.blocker_adjusted_weights[i]>0?p.raw_reach[i]:0,total=ids.reduce((s,i)=>s+combos(i),0)||1,colors=node.actions.map((a,i)=>actionStyle(a,i,node.actions)),u=unitOf(result.config);
  const table=el('table'),head=el('tr');table.id='breakdown-table';['类别','策略','范围 %','组合','EV ('+u+')','Equity'].forEach(t=>head.append(el('th',t)));table.append(head);
  for(const [key,title]of filterGroups){
    const section=el('tr',undefined,'breakdown-section'),cell=el('td',title);cell.colSpan=6;section.append(cell);table.append(section);
    node.class_labels[key].forEach((label,c)=>{
      const members=ids.filter(i=>p.classes[key][i]===c),mass=members.reduce((s,i)=>s+combos(i),0);if(mass<=0)return;
      const data=allCombosStrategy(node,members),stats=rangeStats(p,members,eqrPot(node.actor)),row=el('tr'),bar=el('td'),fill=el('i');
      fill.style.background=strategyGradient(data.probabilities,colors);fill.title=node.actions.map((a,j)=>actionLabel(a)+' '+fmt(data.probabilities[j]*100,1)+'%').join(' / ');bar.append(fill);
      row.append(el('td',label),bar,el('td',fmt(mass/total*100,1)),el('td',fmt(mass,1)),el('td',fmt(stats.ev)),el('td',shareText(stats.equity)));table.append(row);
    });
  }
  tabBreakdown.replaceChildren(el('p',(node.actor===0?'OOP':'IP')+' 行动，按手牌类别拆开的策略。','hint'),table);
}

const rangeText=p=>p.combos.map((c,i)=>p.raw_reach[i]>0&&!RangeEditor.blocked(c,node.board)?`${c}:${+p.raw_reach[i].toFixed(4)}`:'').filter(Boolean).join(',');
function rangePanel(seat){
  const p=node.players[seat],name=seat?'IP':'OOP',weights={},counts={};
  p.combos.forEach((c,i)=>{if(RangeEditor.blocked(c,node.board))return;const key=group(c);weights[key]=(weights[key]||0)+p.raw_reach[i];counts[key]=(counts[key]||0)+1});
  const grid=el('div',undefined,'walk-grid');
  grid.replaceChildren(...walkCells((cell,hand)=>{
    const w=(weights[hand]||0)/(counts[hand]||1);
    if(!w){cell.classList.add('unreached');return}
    cell.style.background=`linear-gradient(to right,${palette.Call} ${w*100}%,#101b25 ${w*100}%)`;cell.title=`${hand} · ${fmt(w*100,1)}%`;
  }));
  const copy=el('button','复制');copy.type='button';copy.onclick=()=>guard(async()=>{await navigator.clipboard.writeText(rangeText(p));copy.textContent='已复制'});
  const save=el('button','存入范围库');save.type='button';save.onclick=()=>guard(async()=>{await api('/api/library',{kind:'range',name:`${node.board.join('')} ${name}`,value:rangeText(p)});await refreshLibrary();save.textContent='已保存'});
  const panel=el('div'),tools=el('div',undefined,'toolbar');panel.dataset.seat=seat;tools.append(el('strong',`${name} · ${fmt(p.combos.reduce((s,c,i)=>s+(p.blocker_adjusted_weights[i]>0?p.raw_reach[i]:0),0),1)} 组合`),copy,save);
  panel.append(tools,grid);return panel;
}
function renderRanges(){
  if(!decisionHint(tabRanges))return;
  const panels=el('div',undefined,'walk-ranges');panels.id='node-range-panels';panels.append(rangePanel(0),rangePanel(1));
  const parts=[panels];
  if(node.class_labels){
    const table=el('table'),head=el('tr');table.id='bucket-table';['Equity 档','OOP','IP'].forEach(t=>head.append(el('th',t)));table.append(head);
    const share=(p,c)=>{const combos=i=>p.blocker_adjusted_weights[i]>0?p.raw_reach[i]:0,all=p.combos.reduce((s,_,i)=>s+combos(i),0)||1;return p.combos.reduce((s,_,i)=>s+(p.classes.equity_simple[i]===c?combos(i):0),0)/all};
    node.class_labels.equity_simple.forEach((label,c)=>{const row=el('tr');row.append(el('td',label),el('td',shareText(share(node.players[0],c))),el('td',shareText(share(node.players[1],c))));table.append(row)});
    parts.push(table);
  }
  const even=node.contributions[0]===node.contributions[1]&&node.actor===0;
  if(even){
    const again=el('button','用当前范围开新局面');again.type='button';again.id='resolve-from-node';
    again.onclick=()=>{
      captureEdit();const c=result.config;
      $('board').value=node.board.join(' ');$('pot').value=node.pot;$('stack').value=c.stack-node.contributions[0];$('range0').value=rangeText(node.players[0]);$('range1').value=rangeText(node.players[1]);
      $('board').dispatchEvent(new Event('input',{bubbles:true}));overrides=[];changed();refreshEditors();captureEdit();
      $('status').textContent='已把当前节点的范围、底池和筹码填到左侧，可以换尺寸重新求解。';
    };
    parts.push(again,el('p','从这里单独重解这一街之后的部分，可以换下注尺寸。节点锁不会带过去。','hint'));
  }
  tabRanges.replaceChildren(...parts);
}
const tabBeforeStudy=showNodeTab;
showNodeTab=function(){
  tabBeforeStudy();
  if(!node)return;
  if(nodeTab==='blockers')renderBlockers();
  if(nodeTab==='breakdown')renderBreakdown();
  if(nodeTab==='ranges')renderRanges();
};

// Value and trash removal: how much of the top and bottom quarter of the other range this combo blocks, ranked 0-10.
// GTO Wizard publishes no formula, so these are local scores and need not match its numbers.
function removalScores(n){
  if(n.removal)return n.removal;
  const p=n.players[n.actor],other=n.players[1-n.actor];
  const rows=other.combos.map((c,i)=>({a:c.slice(0,2),b:c.slice(2,4),w:other.blocker_adjusted_weights[i]>0?other.raw_reach[i]:0,e:other.equity[i]})).filter(r=>r.w>0).sort((x,y)=>y.e-x.e);
  const total=rows.reduce((s,r)=>s+r.w,0),top={},bottom={};let seen=0,topMass=0,bottomMass=0;
  for(const r of rows){
    const middle=seen+r.w/2;seen+=r.w;
    if(middle<=total*.25){top[r.a]=(top[r.a]||0)+r.w;top[r.b]=(top[r.b]||0)+r.w;topMass+=r.w}
    if(middle>=total*.75){bottom[r.a]=(bottom[r.a]||0)+r.w;bottom[r.b]=(bottom[r.b]||0)+r.w;bottomMass+=r.w}
  }
  const hands=p.combos.map((c,i)=>({c,i})).filter(({i})=>p.blocker_adjusted_weights[i]>0);
  const score=(cards,mass)=>{
    const values=hands.map(({c})=>((cards[c.slice(0,2)]||0)+(cards[c.slice(2,4)]||0))/(mass||1)),sorted=[...values].sort((x,y)=>x-y);
    return new Map(hands.map(({c},k)=>[c,Math.round(sorted.lastIndexOf(values[k])/Math.max(1,sorted.length-1)*100)/10]));
  };
  const value=score(top,topMass),trash=score(bottom,bottomMass);
  n.removal=new Map(hands.map(({c})=>[c,[value.get(c),trash.get(c)]]));
  return n.removal;
}

// Runout report: every card of the next street, read from the solved tree.
const runoutBox=el('div',undefined,'runout-report');runoutBox.id='runout-report';$('actions').after(runoutBox);
let runoutRows=[],runoutOrder=null;
function drawRunouts(){
  const actions=runoutRows.find(r=>r.actions)?.actions??[],table=el('table'),head=el('tr'),u=unitOf(result.config);table.id='runout-table';
  const columns=[['牌',r=>r.card],...actions.map((a,i)=>[actionLabel(a),r=>r.shares?.[i]]),['OOP EV ('+u+')',r=>r.ev?.[0]],['IP EV ('+u+')',r=>r.ev?.[1]],['OOP Equity',r=>r.equity?.[0]],['IP Equity',r=>r.equity?.[1]]];
  columns.forEach(([title],c)=>{const th=el('th',title);th.dataset.sort=c;th.onclick=()=>{runoutOrder=runoutOrder===c?null:c;drawRunouts()};head.append(th)});table.append(head);
  const rows=[...runoutRows];if(runoutOrder)rows.sort((a,b)=>(columns[runoutOrder][1](b)??-Infinity)-(columns[runoutOrder][1](a)??-Infinity));
  for(const r of rows){
    const line=el('tr');line.dataset.card=r.card;line.onclick=()=>guard(async()=>{path.push(r.id);selected=null;await showNode()});
    columns.forEach(([,value],c)=>{const v=value(r);line.append(el('td',c===0?v:!Number.isFinite(v)?'—':c<=actions.length?fmt(v*100,1)+'%':c>actions.length+2?fmt(v*100,1)+'%':fmt(v)))});
    table.append(line);
  }
  runoutBox.replaceChildren(el('p','每张牌的第一个决策节点。EV 和 Equity 是双方范围的平均值。点表头排序，点行进入这张牌。','hint'),table);
}
async function runoutReport(){
  const cards=node.possible_cards,at=[...path],variant=$('variant').value;runoutRows=[];
  for(const [k,c]of cards.entries()){
    $('status').textContent=`发牌报告 ${k+1} / ${cards.length}`;
    const n=(await runJob({kind:'node',source:result.result_id,path:[...at,c.id],variant})).node;
    if(n.terminal||n.chance){runoutRows.push({card:c.card,id:c.id});continue}
    const stats=n.players.map((p,seat)=>{const owed=Math.max(0,n.contributions[1-seat]-n.contributions[seat]);return rangeStats(p,p.combos.map((_,i)=>i),n.pot-owed)});
    runoutRows.push({card:c.card,id:c.id,actions:n.actions,shares:allCombosStrategy(n).probabilities,ev:stats.map(s=>s.ev),equity:stats.map(s=>s.equity)});
  }
  $('status').textContent=`发牌报告完成，共 ${cards.length} 张`;
  drawRunouts();
}
const nodeBeforeRunout=renderNode;
renderNode=function(){
  nodeBeforeRunout();
  runoutBox.replaceChildren();
  if(!node.chance||node.terminal)return;
  const b=el('button','生成这一街的发牌报告');b.type='button';b.id='runout-button';b.onclick=()=>guard(runoutReport);runoutBox.append(b);
};
