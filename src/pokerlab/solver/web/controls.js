// Visual input controls and strategy rendering; all strategy values come from the engine.
const visualRanges=[];
function publicCards(){return $('board').value.match(/[2-9TJQKA][cdhs]/g)||[]}
function refreshEditors(){for(const editor of visualRanges)editor.refresh();refreshSizes();refreshTraitLevels()}

for(let seat=0;seat<2;seat++) {
  const host=el('details',undefined,'range-editor');host.id='range-editor'+seat;host.open=seat===0;
  host.append(el('summary',(seat===0?'OOP':'IP')+' 可视化范围编辑'));
  const tools=el('div',undefined,'toolbar'),mode=el('select'),weight=el('input');
  mode.setAttribute('aria-label','范围编辑模式');
  for(const [value,label]of [['paint','点选 / 拖选'],['erase','移除'],['inspect','查看具体花色']])mode.append(new Option(label,value));
  weight.type='number';weight.min=0;weight.max=100;weight.step=5;weight.value=100;weight.setAttribute('aria-label','范围权重百分比');
  tools.append(mode,weight,el('span','% 权重'));
  const clear=el('button','清空'),all=el('button','全选'),download=el('button','导出文本');
  for(const button of [clear,all,download])button.type='button';tools.append(clear,all,download);host.append(tools);
  const count=el('p',undefined,'hint'),error=el('p',undefined,'range-error'),grid=el('div',undefined,'grid range-grid'),detail=el('div',undefined,'suit-editor');
  host.append(count,error,el('p','点一下选中，再点取消；悬停滚轮调本格权重（每格5%，Shift为1%）。拖选涂指定权重。“查看具体花色”保留高级非对称编辑。冲突组合保留在文本中，求解时排除。','hint'),grid);
  const totalBox=el('div',undefined,'range-total'),totalLabel=el('label',(seat===0?'OOP':'IP')+' 翻前总范围 %（1326组合加权）'),totalSlider=el('input'),totalNumber=el('input'),totalOutput=el('output');
  totalSlider.type='range';totalSlider.min=0;totalSlider.max=100;totalSlider.step=.1;totalSlider.id='range-total'+seat;totalSlider.setAttribute('aria-label',(seat===0?'OOP':'IP')+' 总范围百分比滑杆');
  totalNumber.type='number';totalNumber.min=0;totalNumber.max=100;totalNumber.step=.1;totalNumber.id='range-total-number'+seat;totalNumber.setAttribute('aria-label',(seat===0?'OOP':'IP')+' 总范围百分比');
  totalLabel.append(totalSlider);const totalTools=el('div',undefined,'toolbar');totalTools.append(totalNumber,totalOutput);totalBox.append(totalLabel,totalTools,el('p','调整总范围将按翻前启发式重新选前 X%，边界牌类可混合权重；具体花色将恢复同权重，可撤销。百分比包含公共牌冲突，原组合不删除。','hint'));
  const rankingInfo=el('details');rankingInfo.append(el('summary','自动范围排序方法与限制'),el('p',RangeEditor.rankingDescription,'hint'));totalBox.append(rankingInfo);host.append(totalBox,detail);
  $('range'+seat).parentElement.after(host);
  let weights=new Map(),valid=true,chosen=null,painting=false,dragging=false,first=null,visited=new Set();
  const cells=new Map(),ranks='AKQJT98765432';
  const board=()=>publicCards();
  const record=()=>{if(typeof captureEdit==='function')captureEdit()};
  function write(){ $('range'+seat).value=RangeEditor.serialize(weights);changed();refresh() }
  function setGroup(name,{toggle=false,defer=false}={}) {
    if(!valid)return;
    chosen=name;
    if(mode.value!=='inspect') {
      const selected=RangeEditor.combosFor(name).some(c=>(weights.get(c)||0)>0);
      const value=mode.value==='erase'||toggle&&selected?0:Number(weight.value)/100;
      if(!Number.isFinite(value)||value<0||value>1||weight.value===''){error.textContent='权重必须在 0–100%';return}
      for(const c of RangeEditor.combosFor(name))weights.set(c,value);
      if(defer)render();else write();
    } else render();
  }
  for(let i=0;i<13;i++)for(let j=0;j<13;j++) {
    const name=i===j?ranks[i]+ranks[j]:i<j?ranks[i]+ranks[j]+'s':ranks[j]+ranks[i]+'o';
    const b=el('button',name,'cell');b.type='button';b.dataset.hand=name;
    b.onpointerdown=e=>{if(e.button!==0||!valid)return;e.preventDefault();record();painting=true;dragging=false;first=name;visited=new Set([name]);if(mode.value==='inspect')setGroup(name)};
    b.onpointerenter=()=>{if(painting&&!visited.has(name)&&mode.value!=='inspect'){if(!dragging){dragging=true;setGroup(first,{defer:true})}visited.add(name);setGroup(name,{defer:true})}};
    b.onclick=e=>{if(e.detail===0){record();setGroup(name,{toggle:true});record()}}; // keyboard activation
    b.addEventListener('wheel',e=>{
      if(!valid||mode.value==='inspect'||e.deltaY===0)return;
      e.preventDefault();record();chosen=name;
      const list=RangeEditor.combosFor(name),average=list.reduce((sum,c)=>sum+(weights.get(c)||0),0)/list.length;
      const value=Number(Math.max(0,Math.min(1,average+(e.deltaY<0?1:-1)*(e.shiftKey ? .01 : .05))).toFixed(12));
      for(const combo of list)weights.set(combo,value);
      write();record();
    },{passive:false});
    grid.append(b);cells.set(name,b);
  }
  window.addEventListener('pointerup',()=>{if(!painting)return;painting=false;if(mode.value!=='inspect'){if(dragging)write();else setGroup(first,{toggle:true});record()}});
  const cancelPaint=()=>{if(painting){painting=false;refresh()}};
  window.addEventListener('pointercancel',cancelPaint);window.addEventListener('blur',cancelPaint);
  function render() {
    const dead=board();let effective=0,total=0,mass=0,blocked=0;
    for(const [c,w]of weights)if(w>0){total++;if(RangeEditor.blocked(c,dead))blocked++;else{effective++;mass+=w}}
    count.textContent=(valid?'':'文本无效，以下为上次有效输入：')+`有效 ${effective} 组合 · 加权 ${mass.toFixed(2)} · 公共牌冲突 ${blocked} · 原范围 ${total}`;
    const preflopMass=RangeEditor.mass(weights),percent=preflopMass/1326*100;
    totalSlider.disabled=totalNumber.disabled=!valid;totalSlider.value=percent;totalNumber.value=Number(percent.toFixed(4));totalOutput.textContent=`${percent.toFixed(2)}% · ${preflopMass.toFixed(2)} / 1326 加权组合`;
    for(const [name,b]of cells) {
      const list=RangeEditor.combosFor(name),average=list.reduce((s,c)=>s+(weights.get(c)||0),0)/list.length;
      b.classList.toggle('selected',name===chosen);b.classList.toggle('empty',average===0);b.disabled=!valid;
      b.style.background=`linear-gradient(to top, #236b94 ${average*100}%, #17232e ${average*100}%)`;
      b.dataset.weight=String(Number(average.toFixed(12)));b.title=`${name} · 平均权重 ${(average*100).toFixed(1)}% · 合法 ${list.filter(c=>!RangeEditor.blocked(c,dead)).length}/${list.length} 组合`;
      b.setAttribute('aria-label',b.title);b.setAttribute('aria-pressed',String(average>0));
    }
    detail.replaceChildren();detail.hidden=mode.value!=='inspect';if(!chosen||!valid||mode.value!=='inspect')return;
    detail.append(el('strong',chosen+' · 具体花色权重'));
    for(const c of RangeEditor.combosFor(chosen)) {
      const blocked=RangeEditor.blocked(c,dead),label=el('label',c+(blocked?' · 公共牌冲突':''),blocked?'blocked':'');
      const input=el('input');input.type='number';input.min=0;input.max=100;input.step=5;input.value=(weights.get(c)||0)*100;input.dataset.combo=c;
      input.onchange=()=>{const w=Number(input.value)/100;if(input.value===''||!Number.isFinite(w)||w<0||w>1){error.textContent='组合权重必须在 0–100%';return}record();weights.set(c,w);write();record()};
      label.append(input,el('span','%'));detail.append(label);
    }
  }
  function refresh(){try{weights=RangeEditor.parse($('range'+seat).value);valid=true;error.textContent=''}catch(e){valid=false;error.textContent=e.message+'；请修正文本后再编辑网格。'}render()}
  function setTotal(value){if(!valid)return;try{record();weights=RangeEditor.fromPercent(Number(value));write();record()}catch(e){error.textContent=e.message}}
  totalSlider.oninput=()=>setTotal(totalSlider.value);totalNumber.onchange=()=>{if(totalNumber.value===''){error.textContent='总范围百分比不能为空';return}setTotal(totalNumber.value)};
  mode.onchange=render;
  clear.onclick=()=>{record();weights=new Map();write();record()};all.onclick=()=>{record();weights=new Map();for(const name of cells.keys())for(const c of RangeEditor.combosFor(name))weights.set(c,1);write();record()};
  download.onclick=()=>{const blob=new Blob([$('range'+seat).value],{type:'text/plain;charset=utf-8'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download=(seat===0?'OOP':'IP')+'-range.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
  $('range'+seat).addEventListener('input',refresh);visualRanges.push({refresh});
}
$('board').addEventListener('input',()=>visualRanges.forEach(e=>e.refresh()));

const sizeControls=[];
for(const street of [3,4,5])for(const kind of ['bet','raise']) {
  const input=$(kind+street),host=el('div',undefined,'size-choices');
  const choices=kind==='bet'?['25%','33%','50%','66%','75%','100%','a']:['2x','2.5x','3x','a'];
  for(const value of choices) {
    const b=el('button',value==='a'?'All-in':value);b.type='button';b.dataset.size=value;
    b.onclick=()=>{const values=input.value.split(',').map(s=>s.trim()).filter(Boolean),next=values.includes(value)?values.filter(v=>v!==value):[...values,value];if(next.length>3){setError('每街最多 3 个'+(kind==='bet'?'下注':'加注')+'尺寸；请先取消一个尺寸。');return}input.value=next.join(',');input.dispatchEvent(new Event('input',{bubbles:true}));setError('')};host.append(b);
  }
  input.before(host);input.placeholder=kind==='bet'?'自定义：40%, 10c（10 bb）':'自定义：2.2x, a';if(kind==='bet')input.dataset.amountBet='';input.setAttribute('aria-label',street+' '+kind+' 自定义尺寸');
  const description=el('small');input.after(description);sizeControls.push({input,host,description,kind,street});input.addEventListener('input',refreshSizes);
}
function refreshSizes(){for(const {input,host,description,kind,street}of sizeControls){const values=input.value.split(',').map(s=>s.trim()).filter(Boolean);for(const b of host.children)b.setAttribute('aria-pressed',String(values.includes(b.dataset.size)));description.textContent=(street<publicCards().length?'起始街道之前，不使用。':values.length?'已选 '+values.map(v=>v==='a'?'All-in':v).join(' / '):kind==='raise'?'不开放加注尺寸':'无主动下注尺寸')+($('separate-sizes')?.checked?' · 仅 OOP':' · 双方共用');}}
$('board').addEventListener('input',refreshSizes);

for(const box of $('traits').children) {
  const strength=box.querySelector('.strength'),enabled=box.querySelector('.enabled');
  const level=el('select');level.className='trait-level';level.setAttribute('aria-label','特质强度');
  for(const [v,label]of [['off','关闭'],['1','轻度'],['2','中度'],['3','重度'],['custom','自定义']])level.append(new Option(label,v));
  const label=el('label','研究强度');label.append(level);box.append(label);
  const advanced=el('details');advanced.append(el('summary','高级数值（0–6）'),strength,el('small','不是百分比。适用情境内调整动作的相对倾向；实际变化以下方节点预览为准。'));box.append(advanced);
  level.onchange=()=>{if(level.value==='custom'){advanced.open=true;return}enabled.checked=level.value!=='off';if(enabled.checked)strength.value=level.value;changed()};
  enabled.addEventListener('change',refreshTraitLevels);strength.addEventListener('input',refreshTraitLevels);
}
function refreshTraitLevels(){for(const box of $('traits').children){const level=box.querySelector('.trait-level');if(!level)continue;const v=box.querySelector('.strength').value;level.value=!box.querySelector('.enabled').checked?'off':['1','2','3'].includes(v)?v:'custom'}}

const palette={Fold:'#3686df',Check:'#269a72',Call:'#269a72',aggressive:['#ef4651','#881428'],overbet:['#ad69df','#612387']};
function actionCategory(action,index,n=node) {
  const kind=action.match(/^[A-Za-z]+/)?.[0]||action;
  if(kind==='Fold')return 'Fold';if(kind==='Check'||kind==='Call')return kind;
  // Native metadata measures raise increment beyond calling, divided by the
  // pot after calling. Street Raise-to is not a percentage of the current pot.
  return n?.action_details?.[index]?.is_overbet===true?'overbet':'aggressive';
}
function actionStyle(action,index,actions,n=node) {
  const category=actionCategory(action,index,n),color=palette[category];
  if(!Array.isArray(color))return color;
  const peers=actions.map((a,i)=>actionCategory(a,i,n)===category?i:-1).filter(i=>i>=0);
  // Rank real sizes, not action-array order. Use one unit for all peers; legacy
  // nodes can order amounts but cannot infer the missing overbet classification.
  const hasFractions=peers.every(i=>Number.isFinite(n?.action_details?.[i]?.pot_fraction)&&n.action_details[i].pot_fraction>=0);
  const sizeOf=i=>hasFractions?n.action_details[i].pot_fraction:Number(actions[i].match(/\(([\d.]+)\)$/)?.[1]??NaN);
  const sizes=[...new Set(peers.map(sizeOf).filter(Number.isFinite))].sort((a,b)=>a-b);
  const ordinal=sizes.indexOf(sizeOf(index)),position=ordinal>0?ordinal/Math.max(1,sizes.length-1):0;
  // Interpolate across the full light-to-dark range, including two-size nodes.
  // Never cycle a short palette: an additional large size must stay darker.
  const rgb=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));
  const light=rgb(color[0]),dark=rgb(color[1]);
  return '#'+light.map((c,i)=>Math.round(c+(dark[i]-c)*position).toString(16).padStart(2,'0')).join('');
}
function actionSizingDescription(n,index){
  const detail=n.action_details?.[index];if(!detail||!Number.isFinite(detail.pot_fraction))return '';
  const facing=detail.call_amount>0;
  return `${fmt(detail.pot_fraction*100,1)}% ${facing?'跟注后底池（加注增量）':'当前底池'}`;
}
function actionLabel(a){return a.replace('AllIn','全下 AllIn').replace('Raise','加注至 Raise').replace('Bet','下注 Bet').replace('Check','过牌 Check').replace('Call','跟注 Call').replace('Fold','弃牌 Fold')}
function weightedStrategy(n,indices=null){
  // Frequencies count combos, as GTO Wizard does; blockers only matter for EV and Equity averages.
  const p=n.players[n.actor],count=p.combos.length,weight=i=>p.blocker_adjusted_weights[i]>0?p.raw_reach[i]:0,ids=indices||p.combos.map((_,i)=>i),mass=ids.reduce((s,i)=>s+weight(i),0);
  return {mass,probabilities:n.actions.map((_,a)=>mass?ids.reduce((s,i)=>s+weight(i)*n.strategy_action_major[a*count+i],0)/mass:0)};
}
function strategyGradient(probabilities,colors) {
  let position=0;const stops=[];
  probabilities.forEach((p,i)=>{if(p<=0)return;const end=position+p*100;stops.push(`${colors[i]} ${position}% ${end}%`);position=end});
  return stops.length?'linear-gradient(to right, '+stops.join(',')+')':'#263442';
}
const legend=el('div',undefined,'strategy-legend');legend.id='strategy-legend';$('grid').before(legend);
const explanation=el('p',undefined,'hint');explanation.id='strategy-explanation';legend.after(explanation);
const preview=el('div',undefined,'model-preview');preview.id='node-model-preview';$('grid').after(preview);
function paintStrategy(){
  legend.replaceChildren();preview.replaceChildren();explanation.textContent='';
  if(!node||node.terminal||node.chance)return;
  const colors=node.actions.map((a,i)=>actionStyle(a,i,node.actions)),aggregate=weightedStrategy(node);
  [...$('actions').children].forEach((button,i)=>{const sizing=actionSizingDescription(node,i);button.textContent=actionLabel(node.actions[i])+(sizing?' · '+sizing:'');button.style.borderColor=colors[i];button.dataset.category=actionCategory(node.actions[i],i);button.title=sizing});
  node.actions.forEach((a,i)=>{const sizing=actionSizingDescription(node,i),item=el('span',undefined,'legend-item');item.dataset.action=a;item.dataset.category=actionCategory(a,i);item.title=sizing;const swatch=el('i');swatch.style.background=colors[i];const label=el('span',actionLabel(a));if(sizing)label.append(el('small',sizing));item.append(swatch,label,el('strong',aggregate.mass?fmt(aggregate.probabilities[i]*100,1)+'%':'未到达'));legend.append(item)});
  explanation.textContent='蓝：Fold；绿：Check / Call；红：Bet / Raise；紫：超过 100% 底池的进攻（恰好 100% 仍为红）。同一节点、同一色系内，尺寸越大颜色越深；深浅表示尺寸，色块宽度表示行动概率。加注以跟注后底池计算加注增量，All-in 按实际尺寸着色。网格按当前节点条件权重汇总；灰色斜纹 = 零到达。最佳回应可以是纯策略。'+(!node.action_details?' 此旧节点缺少尺寸元数据，进攻暂显示红色；重新查询后可识别超池。':'');
  const p=node.players[node.actor];
  for(const b of $('grid').children) {
    const name=b.dataset.hand,ids=p.combos.map((c,i)=>group(c)===name?i:-1).filter(i=>i>=0),data=weightedStrategy(node,ids);
    b.classList.toggle('unreached',ids.length>0&&!data.mass);b.style.background=data.mass?strategyGradient(data.probabilities,colors):'';
    b.dataset.probabilities=JSON.stringify(data.probabilities);b.dataset.mass=data.mass;
    b.title=name+' · '+(data.mass?node.actions.map((a,i)=>actionLabel(a)+' '+fmt(data.probabilities[i]*100,2)+'%').join(' / '):'没有可达组合');
  }
  [...$('combos').querySelectorAll('thead th')].slice(5).forEach((th,i)=>{th.style.borderBottom=`3px solid ${colors[i]}`;th.title=actionSizingDescription(node,i)});
  if(node.actor!==result.config.hero&&templateComparison&&$('variant').value!=='baseline') {
    preview.append(el('strong','当前对手节点 · 基线 → 固定模型'));
    const ids=p.combos.map((c,i)=>!selected||group(c)===selected?i:-1).filter(i=>i>=0),data=weightedStrategy(node,ids);
    // Use the model posterior for both conditional action distributions to isolate policy changes.
    const bp=templateComparison.players[node.actor],lookup=new Map(bp.combos.map((c,i)=>[c,i]));
    node.actions.forEach((a,j)=>{const aj=templateComparison.actions.indexOf(a);let before=0;for(const i of ids){const bi=lookup.get(p.combos[i]);if(bi!==undefined&&aj>=0)before+=p.blocker_adjusted_weights[i]*templateComparison.strategy_action_major[aj*bp.combos.length+bi]}
      preview.append(el('p',actionLabel(a)+'：'+(data.mass?`${fmt(before/data.mass*100,1)}% → ${fmt(data.probabilities[j]*100,1)}%`:'未到达')))});
    preview.append(el('small',(selected||'全范围')+'；两列使用当前模型相同的条件范围权重，展示本节点动作分布变化。包含手动覆盖；适用规则解释见模型覆盖。'));
  } else if($('variant').value!=='baseline')preview.append(el('p','进入对手行动节点，可查看基线 → 固定模型的实际频率变化。','hint'));
}
refreshEditors();

// A shared four-suit deck for input boards and actual engine chance branches.
// Only chance cards explicitly returned by the engine can navigate the tree.
const deckRanks='AKQJT98765432',deckSuits=[['s','♠','黑桃'],['h','♥','红桃'],['d','♦','方块'],['c','♣','梅花']];
function cardButton(card,extra=''){
  const button=el('button',undefined,'playing-card '+extra);button.type='button';
  if(!card){button.classList.add('card-empty');button.append(el('span','＋'));return button;}
  const suit=deckSuits.find(([s])=>s===card[1]);
  button.dataset.card=card;button.dataset.suit=card[1];button.title=card+' · '+suit[2];button.setAttribute('aria-label',card+' '+suit[2]);
  button.append(el('span',card[0],'card-rank'),el('span',suit[1],'card-suit'));return button;
}
function validBoardText(){const text=$('board').value.replace(/\s+/g,'');if(!/^(?:[2-9TJQKA][cdhs]){3,5}$/.test(text))return [];const cards=text.match(/../g);return new Set(cards).size===cards.length?cards:[];}
function paintInputBoard(){
  const cards=validBoardText(),host=$('board-preview');host.replaceChildren();
  for(const card of cards){const b=cardButton(card);b.onclick=openBoardPicker;host.append(b)}
  if(!cards.length)host.append(el('small','请选择 3–5 张不重复的公共牌','hint'));
}
const boardDialog=el('dialog',undefined,'board-dialog');boardDialog.id='board-picker';boardDialog.setAttribute('aria-labelledby','board-picker-title');
const boardDialogTitle=el('h2','选择公共牌');boardDialogTitle.id='board-picker-title';
const boardClose=el('button','关闭');boardClose.type='button';boardClose.id='board-picker-close';boardClose.onclick=()=>boardDialog.close();
const boardTop=el('div',undefined,'toolbar');boardTop.append(boardDialogTitle,boardClose);
const streetChoices=el('div',undefined,'toolbar board-streets');
const boardSlots=el('div',undefined,'board-cards');boardSlots.id='board-picker-slots';
const boardDeck=el('div',undefined,'card-deck');boardDeck.id='board-picker-deck';boardDeck.setAttribute('aria-label','52 张牌，按黑桃红桃方块梅花排列');
const boardHelp=el('p',undefined,'hint');boardHelp.id='board-picker-help';boardHelp.setAttribute('aria-live','polite');
const boardConfirm=el('button','确认牌面','primary'),boardClear=el('button','清空牌面'),boardRemove=el('button','移除当前牌');
boardConfirm.id='board-picker-confirm';boardClear.id='board-picker-clear';boardRemove.id='board-picker-remove';
for(const b of [boardConfirm,boardClear,boardRemove])b.type='button';
const boardBottom=el('div',undefined,'toolbar');boardBottom.append(boardClear,boardRemove,boardConfirm);
boardDialog.append(boardTop,streetChoices,boardSlots,boardHelp,boardDeck,boardBottom);document.body.append(boardDialog);
let boardDraft=[],boardCount=3,boardSlot=0;
for(const [count,name]of [[3,'Flop · 3 张'],[4,'Turn · 4 张'],[5,'River · 5 张']]){
  const b=el('button',name);b.type='button';b.dataset.count=count;
  b.onclick=()=>{boardCount=count;boardDraft=boardDraft.slice(0,count);boardSlot=Array.from({length:count},(_,i)=>i).find(i=>!boardDraft[i])??Math.min(boardSlot,count-1);paintBoardPicker()};streetChoices.append(b);
}
function openBoardPicker(){boardDraft=validBoardText();boardCount=boardDraft.length||3;boardSlot=0;paintBoardPicker();boardDialog.showModal();}
function paintBoardPicker(){
  streetChoices.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.count===boardCount)));
  boardSlots.replaceChildren();for(let i=0;i<boardCount;i++){const b=cardButton(boardDraft[i]);b.dataset.slot=i;b.setAttribute('aria-pressed',String(i===boardSlot));b.setAttribute('aria-label',`${['Flop 1','Flop 2','Flop 3','Turn','River'][i]}：${boardDraft[i]||'待选择'}`);b.onclick=()=>{boardSlot=i;paintBoardPicker()};boardSlots.append(b)}
  boardDeck.replaceChildren();for(const [suit]of deckSuits)for(const rank of deckRanks){
    const card=rank+suit,b=cardButton(card);b.disabled=boardDraft.some((c,i)=>c===card&&i!==boardSlot);b.setAttribute('aria-pressed',String(boardDraft[boardSlot]===card));
    b.onclick=()=>{boardDraft[boardSlot]=card;const empty=Array.from({length:boardCount},(_,i)=>i).find(i=>!boardDraft[i]);boardSlot=empty??Math.min(boardSlot+1,boardCount-1);paintBoardPicker()};boardDeck.append(b);
  }
  const complete=Array.from({length:boardCount},(_,i)=>boardDraft[i]).every(Boolean);
  boardConfirm.disabled=!complete;boardRemove.disabled=!boardDraft[boardSlot];boardHelp.textContent=`点选上方位置可替换该牌。当前选择：${['Flop 第 1 张','Flop 第 2 张','Flop 第 3 张','Turn','River'][boardSlot]}；${boardDraft.filter(Boolean).length} / ${boardCount} 张。`;
}
boardClear.onclick=()=>{boardDraft=[];boardSlot=0;paintBoardPicker()};
boardRemove.onclick=()=>{boardDraft[boardSlot]=null;paintBoardPicker()};
boardConfirm.onclick=()=>{$('board').value=boardDraft.slice(0,boardCount).join(' ');$('board').dispatchEvent(new Event('input',{bubbles:true}));boardDialog.close()};
$('choose-board').onclick=openBoardPicker;$('board').addEventListener('input',paintInputBoard);
const cardSetConfig=setConfig;setConfig=function(config){cardSetConfig(config);paintInputBoard()};
const cardRenderNode=renderNode;renderNode=function(){
  cardRenderNode();let display=$('node-board');if(!display){display=el('div',undefined,'board-cards');display.id='node-board';display.setAttribute('aria-label','当前结果公共牌');$('actions').before(display)}
  display.replaceChildren();for(const card of node.board){const b=cardButton(card);b.disabled=true;display.append(b)}
  if(!node.chance)return;
  const actions=$('actions');actions.replaceChildren();actions.append(el('p',`选择 ${node.board.length===3?'Turn':'River'} 公共牌；仅可点击引擎返回的合法分支。`,'hint'));
  const deck=el('div',undefined,'card-deck chance-deck');deck.id='chance-deck';deck.setAttribute('aria-label',node.board.length===3?'选择 Turn 公共牌':'选择 River 公共牌');
  const legal=new Map(node.possible_cards.map(c=>[c.card,c.id]));
  for(const [suit]of deckSuits)for(const rank of deckRanks){const card=rank+suit,b=cardButton(card);b.disabled=!legal.has(card);b.onclick=()=>guard(async()=>{if(job)return;path.push(legal.get(card));selected=null;await showNode()});deck.append(b)}actions.append(deck);
};
paintInputBoard();
