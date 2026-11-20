// Daily research workflow: explicit seats, reversible edits, locks and reusable inputs.
const advancedTree=el('details');advancedTree.id='advanced-tree';advancedTree.append(el('summary','按位置配置尺寸 / Donk'));
const separateSizes=el('input');separateSizes.type='checkbox';separateSizes.id='separate-sizes';const separateLabel=el('label','IP 使用独立尺寸（上方尺寸为 OOP）');separateLabel.prepend(separateSizes);advancedTree.append(separateLabel);
const ipInputs=el('div');advancedTree.append(ipInputs);
for(const street of [3,4,5])for(const kind of ['bet','raise']){
  const label=el('label',({3:'Flop',4:'Turn',5:'River'})[street]+' · IP '+kind),input=el('input');input.id='ip-'+kind+street;label.append(input);
  const choices=el('div',undefined,'size-choices');for(const value of kind==='bet'?['33%','50%','75%','a']:['2x','2.5x','a']){
    const b=el('button',value==='a'?'All-in':value);b.type='button';b.onclick=()=>{const current=input.value.split(',').map(s=>s.trim()).filter(Boolean),next=current.includes(value)?current.filter(v=>v!==value):[...current,value];if(next.length>3){setError('每街每类最多 3 个尺寸');return}input.value=next.join(',');changed()};choices.append(b);
  }label.append(choices);ipInputs.append(label);
}
const customDonk=el('input');customDonk.type='checkbox';customDonk.id='custom-donk';const donkLabel=el('label','单独配置 OOP Turn / River Donk');donkLabel.prepend(customDonk);advancedTree.append(donkLabel);
const donkInputs=el('div');for(const [s,name]of [[4,'Turn'],[5,'River']]){const label=el('label',name+' Donk'),input=el('input');input.id='donk'+s;input.placeholder='例如 33%,50%；留空表示禁用该街 Donk';label.append(input);donkInputs.append(label)}const treeUnitHint=el('p','关闭独立设置时沿用上方尺寸。Donk 指上一街跟注后，下一街 OOP 先下注；勾选后空值表示禁用。下注单位是 bb／底池比例（10c 表示 10 bb），加注当前支持倍数及 All-in。','hint');treeUnitHint.id='tree-unit-hint';advancedTree.append(donkInputs,treeUnitHint);
$('bet3').closest('table').after(advancedTree);
function updateTreeControls(){ipInputs.hidden=!separateSizes.checked;donkInputs.hidden=!customDonk.checked;for(const item of sizeControls){const t=item.description.textContent;item.description.textContent=separateSizes.checked?t.replace('双方共用','仅 OOP'):t.replace('仅 OOP','双方共用')}}
separateSizes.onchange=customDonk.onchange=()=>{updateTreeControls();changed()};advancedTree.addEventListener('input',changed);
const coreGetConfig=getConfig;
getConfig=function(mode='fixed'){const c=coreGetConfig(mode);c.bets_ip=separateSizes.checked?[3,4,5].map(s=>$('ip-bet'+s).value.trim()):[];c.raises_ip=separateSizes.checked?[3,4,5].map(s=>$('ip-raise'+s).value.trim()):[];c.donks=customDonk.checked?[4,5].map(s=>$('donk'+s).value.trim()):[];return c};
const coreSetConfig=setConfig;
setConfig=function(c){coreSetConfig(c);separateSizes.checked=!!c.bets_ip?.length||!!c.raises_ip?.length;[3,4,5].forEach((s,i)=>{$('ip-bet'+s).value=c.bets_ip?.[i]??c.bets[i];$('ip-raise'+s).value=c.raises_ip?.[i]??c.raises?.[i]??''});customDonk.checked=!!c.donks?.length;[4,5].forEach((s,i)=>$('donk'+s).value=c.donks?.[i]??'');updateTreeControls()};
updateTreeControls();
const sceneOf=c=>Object.fromEntries(['board','players','pot','stack','bets','raises','hero','bets_ip','raises_ip','donks'].map(k=>[k,c[k]??(['raises','bets_ip','raises_ip','donks'].includes(k)?[]:null)]));
const sameScene=(a,b)=>JSON.stringify(sceneOf(a))===JSON.stringify(sceneOf(b));

const rangeTabs=el('div',undefined,'toolbar seat-tabs');rangeTabs.setAttribute('aria-label','双方范围定位');
const rangePanels=el('div');$('range0').parentElement.before(rangeTabs,rangePanels);
let rangeSeat=0;
for(let seat=0;seat<2;seat++){
  const tab=el('button',seat===0?'定位 OOP 范围':'定位 IP 范围');tab.type='button';tab.id='range-tab'+seat;tab.setAttribute('aria-controls','range-panel'+seat);rangeTabs.append(tab);
  const panel=el('section');panel.id='range-panel'+seat;panel.className='seat-range-panel';panel.append(el('h3',seat===0?'OOP 范围 · 先行动':'IP 范围 · 后行动'),$('range'+seat).parentElement,$('range-editor'+seat));rangePanels.append(panel);
  $('range-editor'+seat).open=true;
  tab.onclick=()=>{rangeSeat=seat;$('range-editor'+seat).open=true;$('range-panel'+seat).scrollIntoView({block:'start'});$('range-seat').value=String(seat)};
}
$('range-seat').addEventListener('change',()=>$('range-tab'+$('range-seat').value).click());

const editbar=el('div',undefined,'toolbar');editbar.id='edit-history';
const undo=el('button','撤销'),redo=el('button','重做');undo.id='undo';redo.id='redo';undo.type=redo.type='button';
editbar.append(undo,redo,el('small','局面、范围、特质、节点锁 · 最近 100 步'));document.querySelector('aside h2').after(editbar);
let edits=[],editIndex=-1,restoring=false,captureTimer=null;
function captureEdit(){
  clearTimeout(captureTimer);captureTimer=null;if(restoring)return;
  const config=getConfig();if(config.board.length<3||config.pot<=0||!Number.isFinite(config.target))return;
  const value=JSON.stringify(config);
  if(edits[editIndex]!==value){edits=edits.slice(0,editIndex+1);edits.push(value);if(edits.length>100)edits.shift();editIndex=edits.length-1}
  undo.disabled=editIndex<=0;redo.disabled=editIndex>=edits.length-1;
}
function scheduleCapture(){if(restoring)return;clearTimeout(captureTimer);captureTimer=setTimeout(captureEdit,180)}
const originalChanged=changed;
changed=function(){originalChanged();scheduleCapture();if(typeof renderLocks==='function')renderLocks();const old=$('sensitivity-results');if(old?.dataset.version&&Number(old.dataset.version)!==version)old.setAttribute('aria-label','结果已过期')};
document.addEventListener('input',scheduleCapture);
function restoreEdit(delta){captureEdit();const next=editIndex+delta;if(next<0||next>=edits.length)return;editIndex=next;restoring=true;try{setConfig(JSON.parse(edits[editIndex]));renderLocks()}finally{restoring=false}undo.disabled=editIndex<=0;redo.disabled=editIndex>=edits.length-1}
undo.onclick=()=>restoreEdit(-1);redo.onclick=()=>restoreEdit(1);undo.disabled=redo.disabled=true;

// Node-lock definitions carry scene and action signatures to prevent silent retargeting.
const manual=$('manual');manual.open=true;manual.replaceChildren(el('summary','Node Lock · 固定对手节点锁'));
manual.append(el('p','Flop / Turn / River 均可锁定。导航到对手节点，编辑完整动作分布；模板只填未手动覆盖的组合。添加手动锁后会展开公共牌分支，可能重建更大的基线；含硬锁快照查询使用 f32，可能比压缩求解更占内存。','hint'));
const scope=el('select');scope.id='lock-scope';for(const [v,t]of [['one','单个具体组合'],['group','当前网格手牌组'],['filter','当前 Filters 选中的组合'],['all','当前节点全部合法组合']])scope.append(new Option(t,v));
const manualCombo=el('select');manualCombo.id='manual-combo';const manualActions=el('div');manualActions.id='manual-actions';
const pure=el('div',undefined,'toolbar'),total=el('p',undefined,'hint');total.id='lock-total';
const apply=el('button','保留节点锁'),restore=el('button','选中范围恢复模板');apply.id='apply-override';restore.id='restore-template';
const message=el('p');message.id='manual-message';const lockList=el('div');lockList.id='lock-list';
const clearLocks=el('button','移除全部节点锁');clearLocks.id='clear-locks';
manual.append(scope,manualCombo,manualActions,pure,total,apply,restore,message,clearLocks,lockList);
function eligibleCombos(){return node&&!node.terminal&&!node.chance?node.players[node.actor].combos.filter(c=>!RangeEditor.blocked(c,node.board)):[]}
function lockTargets(){const list=eligibleCombos(),combos=node.players[node.actor].combos;if(scope.value==='all')return list;if(scope.value==='filter')return list.filter(c=>comboPasses(combos.indexOf(c)));if(scope.value==='group'){if(!selected)throw Error('请先在策略网格选择手牌组');return list.filter(c=>group(c)===selected)}return list.filter(c=>c===manualCombo.value)}
function draftTotal(){const sum=[...manualActions.querySelectorAll('input')].reduce((s,e)=>s+Number(e.value),0);total.textContent='动作概率合计 '+fmt(sum*100,2)+'%（必须为 100%）'}
function fillManual(){
  if(!node||node.terminal||node.chance)return;
  const p=node.players[node.actor],h=p.combos.indexOf(manualCombo.value),o=overrides.find(o=>JSON.stringify(o.path)===JSON.stringify(path)&&o.combo===manualCombo.value);
  [...manualActions.querySelectorAll('input')].forEach((input,a)=>input.value=o?o.probabilities[a]:Number(node.strategy_action_major[a*p.combos.length+h]).toFixed(8));draftTotal();
}
renderManual=function(){
  const previous=manualCombo.value;manualCombo.replaceChildren();manualActions.replaceChildren();pure.replaceChildren();
  const eligible=eligibleCombos();for(const c of eligible)manualCombo.append(new Option(c,c));if(eligible.includes(previous))manualCombo.value=previous;
  const allowed=node&&!node.terminal&&!node.chance;
  apply.disabled=restore.disabled=!allowed;
  if(!allowed){message.textContent='请导航到决策节点。第 3 步只用对手节点的锁，第 4 步两边的锁都生效。';renderLocks();return}
  message.textContent=node.actor===Number($('hero').value)?'这是 Hero 的节点：锁只在第 4 步生效，第 3 步会忽略。':'编辑仅保留在配置中；点击第 3 步或第 4 步后生效。';
  node.actions.forEach((a,i)=>{
    const label=el('label',actionLabel(a)),input=el('input');input.type='number';input.min=0;input.max=1;input.step=.05;input.oninput=draftTotal;label.append(input);manualActions.append(label);
    const b=el('button','100% '+actionLabel(a));b.onclick=()=>{[...manualActions.querySelectorAll('input')].forEach((e,j)=>e.value=i===j?1:0);draftTotal()};pure.append(b);
  });
  const normalize=el('button','按比例归一到 100%');normalize.onclick=()=>guard(async()=>{const inputs=[...manualActions.querySelectorAll('input')],values=inputs.map(e=>Number(e.value)),sum=values.reduce((a,b)=>a+b,0);if(values.some(v=>!Number.isFinite(v)||v<0)||sum<=0)throw Error('请输入非负且合计大于零的概率');inputs.forEach((e,i)=>e.value=(values[i]/sum).toFixed(8));draftTotal()});pure.append(normalize);
  fillManual();renderLocks();
};
manualCombo.onchange=fillManual;
apply.onclick=()=>guard(async()=>{
  if(!result||!sameScene(getConfig(),result.config))throw Error('当前局面／树已改变，请先重新求解，再定位节点。现有节点锁不会被自动迁移。');
  if(!node||node.terminal||node.chance)throw Error('请选择决策节点');
  const probabilities=[...manualActions.querySelectorAll('input')].map(e=>Number(e.value));
  if(probabilities.length!==node.actions.length||probabilities.some(p=>!Number.isFinite(p)||p<0||p>1)||Math.abs(probabilities.reduce((a,b)=>a+b,0)-1)>1e-6)throw Error('每个动作概率必须为 0–1，且合计为 1；不会静默归一化。');
  const targets=lockTargets();if(!targets.length)throw Error('选中范围没有合法组合');
  captureEdit();
  for(const combo of targets){overrides=overrides.filter(o=>JSON.stringify(o.path)!==JSON.stringify(path)||o.combo!==combo);overrides.push({path:[...path],combo,probabilities:[...probabilities],scene:sceneOf(getConfig()),board:[...node.board],actions:[...node.actions],seat:node.actor})}
  changed();captureEdit();message.textContent='已保留 '+targets.length+' 个组合节点锁；重算后生效。';
});
restore.onclick=()=>guard(async()=>{const targets=lockTargets();captureEdit();overrides=overrides.filter(o=>JSON.stringify(o.path)!==JSON.stringify(path)||!targets.includes(o.combo));changed();captureEdit();fillManual();message.textContent='已移除选中节点锁，重算将采用模板。'});
clearLocks.onclick=()=>{captureEdit();overrides=[];changed();captureEdit();message.textContent='全部节点锁已移除，可撤销。'};
function renderLocks(){
  if(!lockList)return;lockList.replaceChildren();
  lockList.append(el('strong','已保留节点锁：'+overrides.length));
  const nodes=new Map();
  for(const o of overrides){const key=JSON.stringify(o.path);(nodes.get(key)||nodes.set(key,[]).get(key)).push(o)}
  for(const [key,list]of nodes){
    const o=list[0],row=el('div',undefined,'lock-row');row.append(el('span',(o.board?.join(' ')||'路径 '+o.path.join('/'))+' · '+(list.length===1?o.combo+' · '+o.probabilities.map(p=>fmt(p*100,1)+'%').join(' / '):list.length+' 个组合')));
    const visit=el('button','定位');visit.onclick=()=>guard(async()=>{if(!result||o.scene&&!sameScene(o.scene,result.config))throw Error('该节点锁属于其他局面，请先恢复对应局面');path=[...o.path];selected=list.length===1?group(o.combo):null;await showNode();manualCombo.value=o.combo;fillManual()});
    const remove=el('button','删除');remove.onclick=()=>{captureEdit();overrides=overrides.filter(x=>JSON.stringify(x.path)!==key);changed();captureEdit()};row.append(visit,remove);lockList.append(row);
  }
}
// Update locks when visiting chance/terminal nodes as well as decision nodes.
const originalRenderNode=renderNode;
renderNode=function(){originalRenderNode();if(node.terminal||node.chance)renderManual();renderResearchNode()};

const library=el('details');library.id='library';library.append(el('summary','命名范围库 / 玩家特质库'));
const libraryName=el('input');libraryName.id='library-name';libraryName.placeholder='名称（每次保存新版本）';
const saveRange=el('button','保存当前席位范围'),savePlayer=el('button','保存玩家特质');saveRange.id='save-range';savePlayer.id='save-player';
const entries=el('select');entries.id='library-entries';const loadEntry=el('button','应用选中项');loadEntry.id='load-library';
const libraryMessage=el('p',undefined,'hint');library.append(libraryName,saveRange,savePlayer,entries,loadEntry,libraryMessage);$('neutral').parentElement.insertBefore(library,$('neutral'));
let libraryItems=[];
async function refreshLibrary(){libraryItems=await api('/api/library');entries.replaceChildren();for(const item of libraryItems)entries.append(new Option((item.kind==='range'?'范围':'玩家')+' · '+item.name,item.id))}
saveRange.onclick=()=>guard(async()=>{RangeEditor.parse($('range'+rangeSeat).value);const saved=await api('/api/library',{kind:'range',name:libraryName.value,value:$('range'+rangeSeat).value});await refreshLibrary();entries.value=saved.id;libraryMessage.textContent='范围已保存到本地库。'});
savePlayer.onclick=()=>guard(async()=>{const saved=await api('/api/library',{kind:'player',name:libraryName.value,value:getConfig().profile.traits});await refreshLibrary();entries.value=saved.id;libraryMessage.textContent='特质已保存；节点锁属于具体局面，随研究保存，不混入通用玩家库。'});
loadEntry.onclick=()=>guard(async()=>{const item=libraryItems.find(i=>i.id===entries.value);if(!item)return;captureEdit();if(item.kind==='range'){$('range'+rangeSeat).value=item.value;refreshEditors()}else setTraits(item.value);changed();captureEdit();libraryMessage.textContent='已应用 '+item.name+'；现有节点锁保留，局面不匹配时重算将报错。'});
const exportConfig=el('button','导出配置 / 复制模型'),importConfig=el('input');exportConfig.id='export-config';importConfig.id='import-config';importConfig.type='file';importConfig.accept='.json';
editbar.append(exportConfig);
library.append(el('p','顶部“导出配置 / 复制模型”保存范围、特质和节点锁；不含求解策略。此处可导入配置 JSON。','hint'),importConfig);
exportConfig.onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(getConfig(),null,2)],{type:'application/json'})),a=el('a');a.href=url;a.download='pokerlab-study-config.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
importConfig.onchange=()=>guard(async()=>{const f=importConfig.files[0];if(!f)return;const c=JSON.parse(await f.text());if(c.schema_version!==1||!Array.isArray(c.board)||!Array.isArray(c.players)||c.players.length!==2||!Array.isArray(c.bets)||c.bets.length!==3||c.runtime)throw Error('不是有效的研究配置');for(const r of c.players)RangeEditor.parse(r);captureEdit();setConfig(c);captureEdit()});
guard(refreshLibrary);

const comboTools=el('div',undefined,'toolbar');comboTools.id='combo-tools';
const comboSort=el('select');comboSort.id='combo-sort';
for(const [v,t]of [['original','原顺序'],['ev','EV 从高到低'],['equity','Equity 从高到低'],['delta','收益变化从高到低']])comboSort.append(new Option(t,v));
const deltaOnly=el('input');deltaOnly.type='checkbox';deltaOnly.id='delta-only';const deltaLabel=el('label','仅显示 |ΔEV| > 0.01 的组合');deltaLabel.prepend(deltaOnly);
comboTools.append(comboSort,deltaLabel);$('combos').parentElement.before(comboTools);
comboSort.onchange=deltaOnly.onchange=()=>{if(node&&!node.chance&&!node.terminal){$('combos').querySelector('thead').replaceChildren();$('combos').querySelector('tbody').replaceChildren();renderCombos()}};
renderCombos=function(){
  const colors=node.actions.map((a,i)=>actionStyle(a,i,node.actions)),u=unitOf(result.config),head=el('tr');['组合','Equity','EQR','EV ('+u+')','相对原策略 ΔEV ('+u+')',...node.actions.map(a=>actionLabel(a)+'：频率 / EV ('+u+')'),'Value removal','Trash removal'].forEach((s,i)=>{const th=el('th',s);if(i>=5&&i<5+node.actions.length){th.dataset.actionIndex=i-5;th.style.borderBottom=`3px solid ${colors[i-5]}`;th.title=actionSizingDescription(node,i-5)}head.append(th)});$('combos').querySelector('thead').append(head);
  const p=node.players[node.actor],n=p.combos.length,other=comparison?.players?.[node.actor],otherIndex=new Map((other?.combos||[]).map((c,i)=>[c,i]));
  const rows=p.combos.map((combo,i)=>{const j=otherIndex.get(combo),valid=p.blocker_adjusted_weights[i]>0,delta=valid&&other?.blocker_adjusted_weights[j]>0?p.ev[i]-other.ev[j]:null;return {combo,i,valid,delta}});
  if(comboSort.value!=='original')rows.sort((a,b)=>{const value=r=>!r.valid?-Infinity:comboSort.value==='delta'?r.delta??-Infinity:comboSort.value==='ev'?p.ev[r.i]:p.equity[r.i];return value(b)-value(a)});
  for(const {combo,i,valid,delta}of rows){
    if(!comboPasses(i)||selected&&group(combo)!==selected||deltaOnly.checked&&(delta===null||Math.abs(delta)<=.01))continue;
    const row=el('tr',undefined,valid?'':'zero'),locked=overrides.some(o=>o.combo===combo&&JSON.stringify(o.path)===JSON.stringify(path));
    [combo+(locked?' 🔒':''),valid?fmt(p.equity[i]*100,1)+'%':'—',valid&&p.equity[i]>0?fmt(p.ev[i]/p.equity[i]/eqrPot(node.actor)*100,0)+'%':'—',valid?fmt(p.ev[i]):'未定义',fmt(delta)].forEach(s=>row.append(el('td',s)));
    node.actions.forEach((a,j)=>{const probability=node.strategy_action_major[j*n+i],cell=el('td',fmt(probability*100,1)+'% / '+(valid?fmt(node.action_ev_action_major[j*n+i]):'—'));cell.dataset.actionIndex=j;cell.dataset.probability=probability;cell.title=actionLabel(a)+(actionSizingDescription(node,j)?' · '+actionSizingDescription(node,j):'');const track=el('span',undefined,'combo-frequency-track'),bar=el('i');track.setAttribute('aria-hidden','true');bar.style.backgroundColor=colors[j];bar.style.width=(valid?probability*100:0)+'%';track.append(bar);cell.append(track);row.append(cell)});const scores=removalScores(node).get(combo);row.append(el('td',fmt(scores?.[0],1)),el('td',fmt(scores?.[1],1)));
    row.onclick=()=>{if(node.actor!==Number($('hero').value)&&eligibleCombos().includes(combo)){manualCombo.value=combo;fillManual();manual.open=true}};
    $('combos').querySelector('tbody').append(row);
  }
  if(!rows.length||!$('combos').querySelector('tbody').children.length){const row=el('tr'),cell=el('td','没有符合筛选条件的组合。');cell.colSpan=7+node.actions.length;row.append(cell);$('combos').querySelector('tbody').append(row)}
};

const researchView=el('details');researchView.id='research-view';researchView.append(el('summary','行动历史'));
const history=el('div',undefined,'toolbar');history.id='node-history';
researchView.append(history);$('combos').parentElement.after(researchView);
function renderResearchNode(){
  history.replaceChildren();const rootButton=el('button','根');rootButton.onclick=()=>guard(async()=>{path=[];await showNode()});history.append(rootButton);
  const query=node.query;history.append(el('small',(query?(query.cache_hit?'节点缓存命中':'首次查询')+' · '+fmt(query.seconds,3)+'s':'已载入结果')+' · 路径 '+(path.join(' → ')||'根')));
  for(let i=1;i<path.length;i++){const button=el('button','返回第 '+i+' 步');button.onclick=()=>guard(async()=>{path=path.slice(0,i);selected=null;await showNode()});history.append(button)}
}

const sensitivityPanel=el('details');sensitivityPanel.id='sensitivity-panel';sensitivityPanel.append(el('summary','模型敏感性 · 轻 / 中 / 重'));
const sensitivityButton=el('button','运行三个固定对手模型');sensitivityButton.id='sensitivity';
const sensitivityResults=el('div');sensitivityResults.id='sensitivity-results';sensitivityPanel.append(el('p','分别使用当前软特质强度的 0.5×、1×、1.5×（上限 6）；手动锁不变，任务串行，复用同一适用基线。每个模型内比较 Hero 原策略与 BR。','hint'),sensitivityButton,sensitivityResults);$('coverage').parentElement.after(sensitivityPanel);
sensitivityButton.onclick=()=>guard(async()=>{const submitted=version;const data=await runJob({kind:'sensitivity',config:getConfig()});sensitivityResults.replaceChildren();sensitivityResults.removeAttribute('aria-label');const u=unitOf(data.records[0]?.report?.config),table=el('table'),head=el('tr');['模型','同模型原 EV ('+u+')','BR EV ('+u+')','提升 ('+u+')','BR 重评误差 ('+u+')'].forEach(t=>head.append(el('th',t)));table.append(head);for(const entry of data.records){const r=entry.report,row=el('tr');[entry.label,fmt(r.same_model_baseline_hero_ev),fmt(r.ev[r.config.hero]),fmt(r.hero_improvement),fmt(r.policy_validation.absolute_error,6)].forEach(v=>row.append(el('td',v)));table.append(row)}sensitivityResults.append(table);
  const unstable=data.root_stability.filter(c=>!c.stable);sensitivityResults.append(el('p',data.root_stability.length?'根 Hero 组合 '+data.root_stability.length+'；行动反转 '+unstable.length+'。这里只判断根节点最优行动，不代表后续策略全部稳定。':'当前根节点不是 Hero，未计算根 Hero 行动稳定性。'));
  for(const c of unstable)sensitivityResults.append(el('p',c.combo+'：'+c.actions.join(' → ')));
  sensitivityResults.dataset.version=String(submitted);if(version!==submitted)sensitivityResults.prepend(el('p','结果已过期：实验期间输入改变。'));
});
document.addEventListener('input',()=>{if(sensitivityResults.dataset.version&&Number(sensitivityResults.dataset.version)!==version)sensitivityResults.setAttribute('aria-label','结果已过期')});
captureEdit();renderLocks();
