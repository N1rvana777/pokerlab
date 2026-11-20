// Node panel: strategy with EV / Equity / EQR, range summary, hand filters and the equity chart.
const filterGroups=[['hand','Hands'],['draw','Draws'],['equity_simple','EQ buckets - Simple'],['equity_advanced','EQ buckets - Advanced']];
const nodeFilter={exclude:false,hand:new Set(),draw:new Set(),equity_simple:new Set(),equity_advanced:new Set(),offsuit:new Set(),suited:new Set()};
let gridMode='strategy',nodeTab='hands',chartMetric='equity',filterVersion=0,maskVersion=-1,maskNode=null,mask=null;

function filterActive(){return filterGroups.some(([key])=>nodeFilter[key].size)||nodeFilter.offsuit.size>0||nodeFilter.suited.size>0}
function buildMask(){
  const p=node.players[node.actor],classes=p.classes;
  return p.combos.map((combo,i)=>{
    const picked=filterGroups.filter(([key])=>nodeFilter[key].size),inClass=([key])=>classes&&nodeFilter[key].has(classes[key][i]);
    const suits=nodeFilter.offsuit.size||nodeFilter.suited.size,suited=combo[1]===combo[3];
    const suitHit=suited?nodeFilter.suited.has(combo[1]):nodeFilter.offsuit.has(combo[1])||nodeFilter.offsuit.has(combo[3]);
    if(nodeFilter.exclude)return !picked.some(inClass)&&!(suits&&suitHit);
    return picked.every(inClass)&&(!suits||suitHit);
  });
}
function comboPasses(i){
  if(!node||node.terminal||node.chance||!filterActive())return true;
  if(maskNode!==node||maskVersion!==filterVersion){mask=buildMask();maskNode=node;maskVersion=filterVersion}
  return mask[i];
}
const allCombosStrategy=weightedStrategy;
weightedStrategy=function(n,indices=null){const ids=indices||n.players[n.actor].combos.map((_,i)=>i);return allCombosStrategy(n,n===node?ids.filter(comboPasses):ids)};

// GTO Wizard's EQR leaves out the bet this seat still has to call.
const eqrPot=seat=>node.pot-Math.max(0,node.contributions[1-seat]-node.contributions[seat]);
function rangeStats(p,ids,pot){
  let mass=0,ev=0,equity=0;
  for(const i of ids){const w=p.blocker_adjusted_weights[i];if(w<=0)continue;mass+=w;ev+=w*p.ev[i];equity+=w*p.equity[i]}
  return {mass,ev:mass?ev/mass:NaN,equity:mass?equity/mass:NaN,eqr:equity>0?ev/equity/pot:NaN};
}
const shareText=v=>Number.isFinite(v)?fmt(v*100,1)+'%':'—';
function heat(value,low,high){
  // Red through amber to green; values outside the scale clamp to its ends.
  const t=Math.min(1,Math.max(0,(value-low)/Math.max(high-low,1e-9))),stops=[[122,34,48],[150,112,40],[31,138,90]];
  const a=t<.5?0:1,f=t<.5?t*2:t*2-1;
  return `rgb(${stops[a].map((c,k)=>Math.round(c+(stops[a+1][k]-c)*f)).join(',')})`;
}

// Layout: grid on the left, tabs on the right.
const nodePanel=el('div',undefined,'node-view');nodePanel.id='node-view';
const nodeLeft=el('div',undefined,'node-left'),nodeRight=el('div',undefined,'node-right');nodePanel.append(nodeLeft,nodeRight);
const gridModes=el('div',undefined,'toolbar grid-modes');gridModes.id='grid-modes';
const actionCards=el('div',undefined,'action-cards');actionCards.id='action-cards';
const rangeLine=el('p',undefined,'range-line');rangeLine.id='range-line';
const gridHint=$('grid').nextElementSibling.nextElementSibling;
$('grid').before(nodePanel);nodeLeft.append(gridModes,rangeLine,$('grid'),$('node-model-preview'),gridHint);
for(const [mode,label]of [['strategy','策略 + EV'],['ev','EV'],['equity','Equity'],['eqr','EQR']]){
  const b=el('button',label);b.type='button';b.dataset.mode=mode;b.onclick=()=>{gridMode=mode;paintStrategy()};gridModes.append(b);
}
const tabBar=el('div',undefined,'toolbar node-tabs'),tabHands=el('div'),tabSummary=el('div'),tabFilters=el('div'),tabChart=el('div');
tabBar.id='node-tabs';tabHands.id='node-hands';tabSummary.id='node-summary';tabFilters.id='node-filters';tabChart.id='node-chart';
nodeRight.append(actionCards,tabBar,tabHands,tabSummary,tabFilters,tabChart);
tabHands.append($('all-combos'),$('combo-tools'),$('combos').parentElement);
const nodeTabs=[['hands','手牌',tabHands],['summary','汇总',tabSummary],['filters','Filters',tabFilters],['chart','Equity chart',tabChart]];
for(const [key,label,panel]of nodeTabs){
  const b=el('button',label);b.type='button';b.dataset.tab=key;b.onclick=()=>{nodeTab=key;showNodeTab()};tabBar.append(b);
}
function showNodeTab(){
  for(const [key,,panel]of nodeTabs)panel.hidden=key!==nodeTab;
  for(const b of tabBar.children)b.setAttribute('aria-pressed',String(b.dataset.tab===nodeTab));
  if(!node)return;
  if(nodeTab==='summary')renderNodeSummary();
  if(nodeTab==='filters')renderFilters();
  if(nodeTab==='chart')renderEquityChart();
}

function filterChanged(){
  filterVersion++;
  if(node&&!node.terminal&&!node.chance){$('combos').querySelector('thead').replaceChildren();$('combos').querySelector('tbody').replaceChildren();renderCombos();paintStrategy();showNodeTab()}
}
function renderFilters(){
  tabFilters.replaceChildren();
  if(node.terminal||node.chance||!node.class_labels){tabFilters.append(el('p','进入决策节点后可以筛选手牌。','hint'));return}
  const p=node.players[node.actor],ids=p.combos.map((_,i)=>i),combos=i=>p.blocker_adjusted_weights[i]>0?p.raw_reach[i]:0,total=ids.reduce((s,i)=>s+combos(i),0)||1;
  const colors=node.actions.map((a,i)=>actionStyle(a,i,node.actions));
  const top=el('div',undefined,'toolbar filter-mode');
  for(const [exclude,label]of [[false,'Include'],[true,'Exclude']]){const b=el('button',label);b.type='button';b.setAttribute('aria-pressed',String(nodeFilter.exclude===exclude));b.onclick=()=>{nodeFilter.exclude=exclude;filterChanged()};top.append(b)}
  const clear=el('button','清除筛选');clear.type='button';clear.id='filter-clear';clear.disabled=!filterActive();clear.onclick=()=>{for(const [key]of filterGroups)nodeFilter[key].clear();nodeFilter.offsuit.clear();nodeFilter.suited.clear();filterChanged()};top.append(clear);
  tabFilters.append(top);
  const suits=el('div',undefined,'toolbar filter-suits');
  for(const [key,label]of [['offsuit','Offsuit'],['suited','Suited']]){
    suits.append(el('small',label));
    for(const [suit,symbol]of [['s','♠'],['h','♥'],['d','♦'],['c','♣']]){
      const b=el('button',key==='suited'?symbol+symbol:symbol);b.type='button';b.dataset.suit=suit;b.setAttribute('aria-pressed',String(nodeFilter[key].has(suit)));
      b.onclick=()=>{nodeFilter[key].has(suit)?nodeFilter[key].delete(suit):nodeFilter[key].add(suit);filterChanged()};suits.append(b);
    }
  }
  tabFilters.append(suits);
  const groups=el('div',undefined,'filter-groups');
  for(const [key,title]of filterGroups){
    const section=el('section',undefined,'filter-group');section.dataset.group=key;section.append(el('h4',title));
    node.class_labels[key].forEach((label,c)=>{
      const members=ids.filter(i=>p.classes[key][i]===c),mass=members.reduce((s,i)=>s+combos(i),0);
      if(mass<=0)return;
      const data=allCombosStrategy(node,members),row=el('button',undefined,'filter-row');row.type='button';row.dataset.label=label;row.setAttribute('aria-pressed',String(nodeFilter[key].has(c)));
      const bar=el('i');bar.style.background=strategyGradient(data.probabilities,colors);
      bar.title=node.actions.map((a,j)=>actionLabel(a)+' '+fmt(data.probabilities[j]*100,1)+'%').join(' / ');
      row.append(el('span',label),el('b',fmt(mass/total*100,1)+'%'),bar);
      row.onclick=()=>{nodeFilter[key].has(c)?nodeFilter[key].delete(c):nodeFilter[key].add(c);filterChanged()};
      section.append(row);
    });
    groups.append(section);
  }
  tabFilters.append(groups,el('p','百分比是该类占当前行动者范围的比例，色条是该类的策略频率。同一组内多选取并集，不同组取交集。分类只用于查看，不影响求解。','hint'));
}

function renderNodeSummary(){
  tabSummary.replaceChildren();
  if(node.terminal||node.chance){tabSummary.append(el('p','进入决策节点后查看汇总。','hint'));return}
  const u=unitOf(result.config),table=el('table'),head=el('tr');table.id='summary-range';
  ['','OOP','IP'].forEach(t=>head.append(el('th',t)));table.append(head);
  const stats=node.players.map((p,seat)=>rangeStats(p,p.combos.map((_,i)=>i),eqrPot(seat)));
  const combos=node.players.map(p=>p.combos.reduce((s,c,i)=>s+(p.blocker_adjusted_weights[i]>0?p.raw_reach[i]:0),0));
  for(const [label,values]of [['组合数',combos.map(v=>fmt(v,1))],['EV ('+u+')',stats.map(s=>fmt(s.ev))],['Equity',stats.map(s=>shareText(s.equity))],['EQR',stats.map(s=>shareText(s.eqr))]]){
    const row=el('tr');row.append(el('th',label));values.forEach(v=>row.append(el('td',v)));table.append(row);
  }
  tabSummary.append(el('h4','双方范围（底池 '+fmt(node.pot,2)+' '+u+'）'),table);
  const p=node.players[node.actor],n=p.combos.length,ids=p.combos.map((_,i)=>i).filter(i=>(!selected||group(p.combos[i])===selected)&&comboPasses(i));
  const shown=rangeStats(p,ids,eqrPot(node.actor)),actions=el('table'),top=el('tr');actions.id='summary-actions';
  ['动作','频率','组合数','EV ('+u+')'].forEach(t=>top.append(el('th',t)));actions.append(top);
  node.actions.forEach((a,j)=>{
    let weight=0,count=0,ev=0;
    for(const i of ids){const w=p.blocker_adjusted_weights[i];if(w<=0)continue;const f=node.strategy_action_major[j*n+i];weight+=w*f;count+=p.raw_reach[i]*f;ev+=w*f*node.action_ev_action_major[j*n+i]}
    const combosShown=ids.reduce((s,i)=>s+(p.blocker_adjusted_weights[i]>0?p.raw_reach[i]:0),0);
    const row=el('tr');row.append(el('td',actionLabel(a)),el('td',combosShown?shareText(count/combosShown):'—'),el('td',fmt(count,1)),el('td',weight>0?fmt(ev/weight):'—'));actions.append(row);
  });
  const scope=(node.actor===0?'OOP':'IP')+' 行动'+(selected?' · '+selected:'')+(filterActive()?' · 已筛选':'');
  tabSummary.append(el('h4',scope+'：平均 EV '+fmt(shown.ev)+' '+u+'，Equity '+shareText(shown.equity)+'，EQR '+shareText(shown.eqr)),actions);
  tabSummary.append(el('p','EV 从当前节点算起，之前投入的筹码是沉没成本，所以 Fold 的 EV 是 0。Equity 是对当前对手范围的摊牌胜率。EQR = EV ÷（Equity × 底池），底池不含自己还要跟注的部分。','hint'));
}

const chartCanvas=el('canvas');chartCanvas.id='range-chart';chartCanvas.width=760;chartCanvas.height=420;chartCanvas.setAttribute('aria-label','双方范围的 Equity 曲线');
const chartBar=el('div',undefined,'toolbar'),chartReadout=el('p',undefined,'hint');chartReadout.id='chart-readout';
for(const [metric,label]of [['equity','Equity'],['ev','EV']]){const b=el('button',label);b.type='button';b.dataset.metric=metric;b.onclick=()=>{chartMetric=metric;renderEquityChart()};chartBar.append(b)}
tabChart.append(chartBar,chartCanvas,chartReadout);
let chartSeries=[];
function chartRows(p){
  const rows=[];p.combos.forEach((combo,i)=>{const w=p.blocker_adjusted_weights[i];if(w>0)rows.push({combo,w,value:chartMetric==='ev'?p.ev[i]:p.equity[i]})});
  rows.sort((a,b)=>b.value-a.value);const total=rows.reduce((s,r)=>s+r.w,0);let sum=0;
  for(const r of rows){sum+=r.w;r.x=sum/total}
  return rows;
}
function renderEquityChart(){
  for(const b of chartBar.children)b.setAttribute('aria-pressed',String(b.dataset.metric===chartMetric));
  const ctx=chartCanvas.getContext('2d'),W=chartCanvas.width,H=chartCanvas.height,left=52,right=14,top=14,bottom=34;ctx.clearRect(0,0,W,H);
  chartSeries=[];chartReadout.textContent='';
  if(node.terminal||node.chance){chartReadout.textContent='进入决策节点后查看曲线。';return}
  chartSeries=node.players.map(chartRows);
  const values=chartSeries.flat().map(r=>r.value),low=chartMetric==='ev'?Math.min(0,...values):0,high=chartMetric==='ev'?Math.max(...values,1e-9):1;
  const X=x=>left+x*(W-left-right),Y=v=>H-bottom-(v-low)/(high-low)*(H-top-bottom);
  ctx.font='12px system-ui';ctx.strokeStyle='#34414f';ctx.fillStyle='#99acbb';ctx.lineWidth=1;
  for(let i=0;i<=5;i++){const v=low+(high-low)*i/5,y=Y(v);ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(W-right,y);ctx.stroke();ctx.fillText(chartMetric==='ev'?fmt(v,1):fmt(v*100,0)+'%',6,y+4)}
  for(let i=0;i<=10;i++){const x=X(i/10);ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,H-bottom);ctx.stroke();ctx.fillText(i*10+'%',x-12,H-bottom+18)}
  chartSeries.forEach((rows,seat)=>{ctx.strokeStyle=seat?'#f0a14a':'#4aa3f0';ctx.lineWidth=2;ctx.beginPath();rows.forEach((r,i)=>{i?ctx.lineTo(X(r.x),Y(r.value)):ctx.moveTo(X(0),Y(r.value))});ctx.stroke()});
  ctx.fillStyle='#4aa3f0';ctx.fillText('OOP',W-92,top+14);ctx.fillStyle='#f0a14a';ctx.fillText('IP',W-52,top+14);
  chartReadout.textContent='横轴是范围百分位（按'+(chartMetric==='ev'?' EV':' Equity')+'从高到低），纵轴是该位置手牌的'+(chartMetric==='ev'?' EV（'+unitOf(result.config)+'）':' Equity')+'。鼠标移到图上看具体手牌。';
}
chartCanvas.addEventListener('mousemove',event=>{
  if(!chartSeries.length)return;
  const box=chartCanvas.getBoundingClientRect(),x=Math.min(1,Math.max(0,((event.clientX-box.left)*chartCanvas.width/box.width-52)/(chartCanvas.width-66)));
  const text=chartSeries.map((rows,seat)=>{const r=rows.find(row=>row.x>=x)||rows[rows.length-1];return r?(seat?'IP ':'OOP ')+r.combo+' '+(chartMetric==='ev'?fmt(r.value)+' '+unitOf(result.config):fmt(r.value*100,1)+'%'):''});
  chartReadout.textContent='前 '+fmt(x*100,1)+'%：'+text.join(' · ');
});

// Overall action frequencies for the shown range; a card steps into that action's node.
function paintActionCards(){
  actionCards.replaceChildren();
  if(!node||node.terminal||node.chance)return;
  const data=weightedStrategy(node),colors=node.actions.map((a,i)=>actionStyle(a,i,node.actions));
  node.actions.forEach((a,i)=>{
    const card=el('button',undefined,'action-card');card.type='button';card.dataset.action=a;card.style.background=colors[i];card.style.flexGrow=String(Math.max(.18,data.probabilities[i]));
    const sizing=actionSizingDescription(node,i);if(sizing)card.title=sizing;
    card.append(el('span',actionLabel(a),'action-card-name'),el('strong',data.mass?fmt(data.probabilities[i]*100,1)+'%':'—'),el('small',fmt(data.mass*data.probabilities[i],1)+' combos'));
    card.onclick=()=>guard(async()=>{path.push(i);selected=null;await showNode()});actionCards.append(card);
  });
}
function paintCells(){
  for(const b of gridModes.children)b.setAttribute('aria-pressed',String(b.dataset.mode===gridMode));
  if(!node||node.terminal||node.chance){rangeLine.textContent='';return}
  const p=node.players[node.actor],u=unitOf(result.config),byCell=new Map();
  p.combos.forEach((c,i)=>{if(comboPasses(i)){const key=group(c);(byCell.get(key)||byCell.set(key,[]).get(key)).push(i)}});
  const stats=new Map([...byCell].map(([key,ids])=>[key,rangeStats(p,ids,eqrPot(node.actor))])),evs=[...stats.values()].map(s=>s.ev).filter(Number.isFinite);
  const low=Math.min(...evs,0),high=Math.max(...evs,1e-9);
  for(const b of $('grid').children){
    const name=b.dataset.hand,s=stats.get(name),reached=s&&s.mass>0,value=!reached?'':gridMode==='equity'?fmt(s.equity*100,0)+'%':gridMode==='eqr'?fmt(s.eqr*100,0)+'%':fmt(s.ev,gridMode==='ev'?2:1);
    b.replaceChildren(el('span',name,'cell-hand'),el('small',value,'cell-value'));
    b.classList.toggle('filtered',filterActive()&&!s&&p.combos.some(c=>group(c)===name));
    if(reached&&gridMode!=='strategy')b.style.background=gridMode==='ev'?heat(s.ev,low,high):gridMode==='equity'?heat(s.equity,0,1):heat(s.eqr,.3,1.3);
    if(reached)b.title+=' · EV '+fmt(s.ev)+' '+u+' · Equity '+shareText(s.equity)+' · EQR '+shareText(s.eqr);
  }
  const all=rangeStats(p,p.combos.map((_,i)=>i).filter(comboPasses),eqrPot(node.actor));
  rangeLine.textContent=(node.actor===0?'OOP':'IP')+' 行动：EV '+fmt(all.ev)+' '+u+' · Equity '+shareText(all.equity)+' · EQR '+shareText(all.eqr)+(filterActive()?' · 已筛选':'');
}
const paintBaseStrategy=paintStrategy;
paintStrategy=function(){paintBaseStrategy();paintCells();paintActionCards()};
const renderBaseNode=renderNode;
renderNode=function(){renderBaseNode();showNodeTab()};
$('all-combos').addEventListener('click',()=>{if(node)showNodeTab()});
$('grid').addEventListener('click',()=>{if(node)showNodeTab()});
showNodeTab();

// Tree templates fill the size inputs; a hand edit moves the select back to custom.
const treePresets={fast:{bets:['33%','66%','66%'],raises:['3x','3x','3x'],limit:2},standard:{bets:['33%,75%','50%,100%','50%,100%'],raises:['3x','3x','3x'],limit:2},full:{bets:['33%,66%,100%','33%,66%,100%','33%,66%,100%'],raises:['3x','3x','3x'],limit:2},full_light:{bets:['33%,66%,100%','33%,66%,100%','33%,66%,100%'],raises:['3x','3x',''],limit:2}};
$('tree-preset').onchange=()=>{const t=treePresets[$('tree-preset').value];if(!t)return;[3,4,5].forEach((s,i)=>{$('bet'+s).value=t.bets[i];$('raise'+s).value=t.raises[i]});$('raise-limit').value=t.limit;refreshSizes();changed()};
for(const s of [3,4,5])for(const kind of ['bet','raise'])$(kind+s).addEventListener('input',()=>{$('tree-preset').value=''});
$('raise-limit').addEventListener('input',()=>{$('tree-preset').value=''});
$('threads').value=String(defaultThreads);
