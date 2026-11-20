const $=id=>document.getElementById(id), token=document.querySelector('meta[name=local-token]').content;
const traits=[['station','Station / Overcall','面对 Bet / Raise 增加 Call 倾向'],['overbluff','Overbluff','主动下注时，弱牌增加进攻概率'],['underbluff','Underbluff','主动下注时，弱牌减少进攻概率'],['weak_check','Check 范围保护不足','两对及以上、强于公共牌的成牌更多下注'],['double_barrel_give_up','Double barrel / River give-up','前两街弱牌进攻；连续开火后 River 仍弱则降低下注'],['delayed_aggression','延迟进攻','Flop Check–Check 后 Turn 更多主动下注']];
let examples={},examplesReady=false,taskBusy=false,result=null,node=null,comparison=null,templateComparison=null,path=[],selected=null,overrides=[],job=null,version=0,stale=false,applyingInitialDefault=false;
const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
const fmt=(v,d=3)=>Number.isFinite(v)?v.toFixed(d):'—';
const defaultThreads=Math.min(64,navigator.hardwareConcurrency||8);
const unitOf=config=>config?.amount_unit==='bb'?'bb':'筹码';
// Daily defaults apply only to a new scene, never to imported/saved settings.
const dailyScene=example=>({...structuredClone(example),amount_unit:'bb',chip_scale:100,memory_auto:true,target:0.5,target_unit:'pot_pct'});
function refreshAmountUnit(){
 const unit=$('amount-unit').value==='bb'?'bb':'筹码';
 $('pot-label').textContent=`底池（${unit}）`;$('stack-label').textContent=`有效剩余筹码（${unit}）`;
 $('unit').querySelector('[value=chips]').textContent=unit;
 $('amount-unit-hint').textContent=unit==='bb'?'bb = 大盲。底池、剩余筹码、下注金额及 EV 使用同一单位，可以填小数（精确到 0.01 bb）。':'当前保留旧配置的原筹码单位。切换为 bb 只重新定义这些数字的计价单位，不会自动换算金额。';
 for(const span of document.querySelectorAll('.amount-unit-value'))span.textContent=unit;
 for(const input of document.querySelectorAll('[data-amount-bet]'))input.placeholder=`自定义：40%, 10c（10 ${unit}）`;
 if($('tree-unit-hint'))$('tree-unit-hint').textContent=`关闭独立设置时沿用上方尺寸。Donk 指上一街跟注后，下一街 OOP 先下注；勾选后空值表示禁用。下注单位是 ${unit}／底池比例（10c 表示 10 ${unit}），加注当前支持倍数及 All-in。`;
}
const setError=e=>{const text=e?.message||String(e||'');$('error').textContent=text;const box=$('memory-recovery');box.hidden=!/内存预检|memory budget|安全预算/i.test(text);if(!box.hidden)$('memory-recovery-text').textContent=$('memory-auto').checked?'当前树超过安全可用内存。保留系统余量；可以关闭其他占内存程序后重新读取预算，或主动调整范围及尺寸。降低底池本身不保证降低内存。':'当前使用手动内存上限。可启用自动预算，按本机可用资源重新检查，不改变当前范围或下注树。'};
function changed(){
 version++;stale=!!result;
 $('stale').textContent=stale?'结果已过期：输入或模型已改变，请重算':'';
 if(!job&&$('error').textContent){setError('');$('status').textContent='局面已修改，尚未重新求解；内存将按新配置检查';}
 $('override-count').textContent=`保留的手动覆盖：${overrides.length} 条（应用预设不会删除）`;
 refreshSPR();window.PokerlabAgent?.configChanged({initialDefault:applyingInitialDefault});
}
for(const [kind,name,description] of traits){
  const box=el('div',undefined,'trait');box.dataset.kind=kind;
  const row=el('label');const on=el('input');on.type='checkbox';on.className='enabled';row.append(on,el('span',name));
  const strength=el('input');strength.type='number';strength.min='0';strength.max='6';strength.step='.25';strength.value='2';strength.className='strength';row.append(strength);box.append(row,el('small',description));
  const streets=el('div',undefined,'streets');for(const [s,label]of [[3,'Flop'],[4,'Turn'],[5,'River']]){const l=el('label');const c=el('input');c.type='checkbox';c.checked=true;c.dataset.street=s;l.append(c,label);streets.append(l)}box.append(streets);box.addEventListener('input',changed);$('traits').append(box);
}
function setTraits(list){for(const b of $('traits').children){const t=list.find(t=>t.kind===b.dataset.kind);b.querySelector('.enabled').checked=!!t;b.querySelector('.strength').value=t?.strength??2;for(const c of b.querySelectorAll('[data-street]'))c.checked=t?t.streets.includes(+c.dataset.street):true;}if(typeof refreshTraitLevels==='function')refreshTraitLevels();}
function getConfig(mode='fixed'){
  const board=$('board').value.replace(/\s+/g,'').match(/.{1,2}/g)||[];
  const ts=[...$('traits').children].filter(b=>b.querySelector('.enabled').checked).map(b=>({kind:b.dataset.kind,strength:+b.querySelector('.strength').value,streets:[...b.querySelectorAll('[data-street]:checked')].map(c=>+c.dataset.street)}));
  const c={schema_version:1,amount_unit:$('amount-unit').value,expand_suits:true,time_limit_seconds:0,threads:+$('threads').value,compression:$('compression').checked,auto_suits:$('auto-suits').checked,memory_auto:$('memory-auto').checked,...($('memory-stretch').checked?{memory_stretch:true}:{}),board,players:[$('range0').value.trim(),$('range1').value.trim()],pot:+$('pot').value,stack:+$('stack').value,bets:[3,4,5].map(s=>$('bet'+s).value.trim()),raises:[3,4,5].map(s=>$('raise'+s).value.trim()),hero:+$('hero').value,mode,target:+$('target').value,target_unit:$('unit').value,max_iterations:+$('iterations').value,memory_budget_mb:+$('memory').value,profile:mode==='equilibrium'?{traits:[]}:{traits:ts,overrides:structuredClone(overrides)}};
  if(c.amount_unit==='bb')c.chip_scale=100;
  if($('raise-limit').value)c.raise_limit=+$('raise-limit').value;
  if(+$('rake-rate').value>0&&+$('rake-cap').value>0){c.rake_rate=+$('rake-rate').value/100;c.rake_cap=+$('rake-cap').value}
  return c;
}
function setConfig(c){$('amount-unit').value=c.amount_unit??'chips';refreshAmountUnit();$('threads').value=String(c.threads??defaultThreads);$('raise-limit').value=c.raise_limit??'';$('rake-rate').value=c.rake_rate?c.rake_rate*100:'';$('rake-cap').value=c.rake_cap||'';$('compression').checked=c.compression??true;$('auto-suits').checked=c.auto_suits??true;$('memory-auto').checked=c.memory_auto??true;$('memory-stretch').checked=c.memory_stretch===true;$('memory').disabled=$('memory-auto').checked;$('board').value=c.board.join(' ');$('pot').value=c.pot;$('stack').value=c.stack;$('range0').value=c.players[0];$('range1').value=c.players[1];$('hero').value=c.hero;$('target').value=c.target;$('unit').value=c.target_unit;$('iterations').value=c.max_iterations;$('memory').value=c.memory_budget_mb;[3,4,5].forEach((s,i)=>{$('bet'+s).value=c.bets[i];$('raise'+s).value=c.raises?.[i]||''});setTraits(c.profile?.traits||[]);overrides=structuredClone(c.profile?.overrides||[]);refreshMemoryLabel();changed();if(typeof refreshEditors==='function')refreshEditors()}
async function api(url,body){const response=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Pokerlab-Token':token},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.error||response.statusText);return data}
function busy(on){taskBusy=on;for(const id of ['baseline','preview','response','save','open'])$(id).disabled=on;for(const id of ['load-example','new-scene'])$(id).disabled=on||!examplesReady;$('example').disabled=!examplesReady;$('cancel').disabled=!on}
let lastMemoryResources=null;
function refreshSPR(){const pot=+$('pot').value,stack=+$('stack').value;$('spr-hint').dataset.high=String(pot>0&&stack/pot>($('raise-limit').value?40:20));$('spr-hint').textContent=pot>0&&stack>0?`SPR = ${fmt(stack/pot,2)}。单独减小底池会提高 SPR，不保证减少树的内存。`:''}
function refreshMemoryLabel(){const automatic=$('memory-auto').checked;$('memory').disabled=automatic;const info=lastMemoryResources;if(!info)return;if(!info.ready){$('memory-resources').textContent='资源读取未完成：'+(info.error||'请稍后重试')+'。计算时仍会执行内存预检。';return}const safe=($('memory-stretch').checked?info.stretch_budget_mb:info.automatic_budget_mb)/1024;$('memory-resources').textContent=(automatic?`自动安全预算约 ${fmt(safe,2)} GiB；旧示例的手动上限不生效。`:`手动上限 ${fmt(+$('memory').value/1024,2)} GiB（可用安全上限约 ${fmt(safe,2)} GiB）。`)+` Windows 可用 ${fmt(info.windows.available_mb/1024,2)} GiB${info.windows.vm_idle_mb?`（另有 WSL 闲置 ${fmt(info.windows.vm_idle_mb/1024,2)} GiB）`:''} / WSL 可用 ${fmt(info.wsl.available_mb/1024,2)} GiB；启动时复测。`}
async function refreshMemoryResources(){try{lastMemoryResources=await api('/api/resources');refreshMemoryLabel()}catch(e){$('memory-resources').textContent='无法读取资源：'+e.message+'。请重新打开新版 Solver 后重试。'}}
async function enableAutomaticMemory(){$('memory-auto').checked=true;$('memory').disabled=true;changed();await refreshMemoryResources();setError('')}
$('adaptive-memory').onclick=()=>guard(enableAutomaticMemory);
$('memory-recovery-auto').onclick=()=>guard(enableAutomaticMemory);
$('memory-auto').onchange=()=>{refreshMemoryLabel();guard(refreshMemoryResources)};
$('memory').addEventListener('input',refreshMemoryLabel);$('memory-stretch').addEventListener('change',refreshMemoryLabel);
$('amount-unit').addEventListener('change',refreshAmountUnit);
const phases={memory_plan:'内存分配计划',building:'建树 / 资源检查',resuming:'载入 CFR 续算状态',baseline:'均衡基线',saving_checkpoint:'保存 CFR 续算状态',compiling_model:'编译完整对手策略',best_response:'导出信息集最佳回应',evaluating_policy:'重评完整策略',reporting:'生成报告'};
async function runJob(data){const submittedAt=performance.now();if(job)throw new Error('请等待当前任务完成或先取消');busy(true);setError('');try{let state=await api('/api/jobs',data),wait=10;job=state.id;while(true){state=await api('/api/jobs/'+job);const p=state.progress;const d=p?.detail;$('status').textContent=`${state.state} · ${Math.floor((performance.now()-submittedAt)/1000)}s · ${phases[p?.phase]||data.kind}${d?.estimated_peak_bytes!==undefined?' · 预计峰值 '+fmt(d.estimated_peak_bytes/1073741824,2)+' GiB / 预算 '+fmt(d.budget_bytes/1073741824,2)+' GiB':''}${d?.board?' · '+(d.index+1)+' / '+d.total+' '+d.board:''}${d?.iteration!==undefined?' · '+d.iteration+' 次 · 实测 '+fmt(d.actual_chips/((data.config||result?.config||getConfig()).chip_scale||1))+' '+unitOf(data.config||result?.config||getConfig()):''}`;if(state.state==='completed')return await api('/api/jobs/'+job+'/result');if(['failed','cancelled','interrupted'].includes(state.state))throw new Error(state.error||state.state);await new Promise(r=>setTimeout(r,wait));wait=Math.min(250,wait*1.5)}}finally{job=null;busy(false)}}
async function solve(mode){const submittedVersion=version;result=await runJob({kind:'solve',config:getConfig(mode)});path=[];selected=null;stale=version!==submittedVersion;$('stale').textContent=stale?'旧结果：求解期间输入已改变':'';$('variant').value=mode==='equilibrium'?'baseline':mode==='preview'?'model':'response';renderSummary();await showNode()}
function renderSummary(){
 const u=unitOf(result.config),p=result.precision,t=result.timing,fixed=result.config.mode==='fixed';
 $('summary').textContent=[
  `${result.config.mode==='equilibrium'?'均衡基线':result.config.mode==='locked'?`锁定 ${result.config.profile.overrides.filter(o=>o.seat!==undefined).length} 个组合后双方重新求解${result.config.profile.overrides.some(o=>o.seat===undefined)?'，上游保持基线':''}`:fixed?'冻结对手后的完整最佳回应':'对手模型预览（未优化 Hero）'} · ${result.config.board.join(' ')}`,
  ...(result.config.profile?.incentives?[`Player Profile：${Object.entries(result.config.profile.incentives).filter(([k])=>k!=='streets').map(([k,v])=>k+' '+(v>0?'+':'')+v+'%').join('，')}${result.config.profile.incentives.streets?'，只作用于这一街':''}。这里的基线是带激励的模型，不是 GTO；精度看 Hero 回应差距，因为对手是故意偏离。`]:[]),
  `均衡目标 ${result.config.target} ${result.config.target_unit==='pot_pct'?'% 底池':u}；基线实测 ${fmt(p.baseline_exploitability_chips)} ${u}；基线停止 ${p.baseline_stop_reason}；累计 ${p.baseline_iterations} 次迭代；${result.cache.baseline_hit?'复用已求得的基线（本次未迭代）':result.cache.resumed_iterations>0?'从第 '+result.cache.resumed_iterations+' 次续算，本次新增 '+Math.max(0,p.baseline_iterations-result.cache.resumed_iterations)+' 次':'本次从头计算基线'}`,
  fixed?`Hero 回应差距 ${fmt(p.actual_chips,6)} ${u}；停止原因 ${p.stop_reason}；重评误差 ${fmt(result.policy_validation.absolute_error,6)} ${u}`:`当前精度 / 停止原因：${fmt(p.actual_chips,6)} ${u} / ${p.stop_reason}`,
  `同一对手模型：Hero 原策略 EV ${fmt(result.same_model_baseline_hero_ev)} → 当前 EV ${fmt(result.ev[result.config.hero])}；变化 ${fmt(result.hero_improvement)} ${u}`,
  `建树 ${fmt(t.build_seconds)}s · 基线 ${fmt(t.baseline_seconds)}s · 模型 ${fmt(t.compile_seconds)}s · 回应 ${fmt(t.response_seconds)}s · 重评 ${fmt(t.evaluation_seconds)}s · 报告 ${fmt(t.report_seconds)}s · 保存 ${fmt(t.save_seconds)}s`,
  `有效组合 ${result.tree.effective_combos.join(' / ')}；公共行动树 ${result.tree.public_nodes} 节点；原生峰值 ${fmt(result.memory.measured_native_peak_rss_bytes/1048576,1)} MiB。EV 单位为 ${u}，旧投入视为沉没成本。`
 ].join('\n');
 $('summary').textContent+=`\n存储 ${result.config.compression?'16-bit':'32-bit'} / 花色同构 ${result.tree.suit_isomorphism?'ON':'OFF'} / 预计峰值 ${fmt(result.memory.estimated_peak_bytes/1073741824,2)} GiB`;
 $('coverage').replaceChildren();const c=result.coverage;$('coverage').append(el('p',`遍历对手节点 ${c.nodes}；特质影响组合节点 ${c.trait_combos}；Flop/Turn/River 节点 ${c.streets.join(' / ')}；零到达 ${c.zero_reach_under_compiled_prefix}。未应用规则处保留明确的 DCFR 基线；零到达基线不保证可靠。`));for(const s of c.samples.slice(0,12))$('coverage').append(el('p',`${s.board.join(' ')} · ${s.combo} · ${s.history.map(h=>h.action).join(' → ')} · ${s.rules.join(' + ')||'默认基线'}：${s.before.map(p=>fmt(p*100,1)).join('/')}% → ${s.after.map(p=>fmt(p*100,1)).join('/')}%`));}
async function showNode(){if(!result)return;comparison=null;templateComparison=null;const variant=$('variant').value;node=(path.length===0&&variant==='response'&&(result.root.terminal||result.root.chance||Array.isArray(result.root.action_details)))?result.root:(await runJob({kind:'node',source:result.result_id,path,variant})).node;if(variant==='response'&&!node.terminal&&!node.chance)comparison=(await runJob({kind:'node',source:result.result_id,path,variant:'model'})).node;if(!node.terminal&&!node.chance&&node.actor!==result.config.hero&&variant!=='baseline')templateComparison=(await runJob({kind:'node',source:result.result_id,path,variant:'baseline'})).node;renderNode()}
function group(combo){const ranks='AKQJT98765432';let a=combo[0],b=combo[2];if(ranks.indexOf(a)>ranks.indexOf(b))[a,b]=[b,a];return a===b?a+b:a+b+(combo[1]===combo[3]?'s':'o')}
function renderNode(){const actions=$('actions');actions.replaceChildren();$('node-label').textContent=`${node.board.join(' ')} · ${node.terminal?'终局':node.chance?'发公共牌':node.actor===0?'OOP 行动':'IP 行动'} · 底池 ${node.pot} ${unitOf(result.config)} · 已投入 ${node.contributions.join('/')} ${unitOf(result.config)}`;$('grid').replaceChildren();$('combos').querySelector('tbody').replaceChildren();$('combos').querySelector('thead').replaceChildren();
 if(node.terminal){paintStrategy();actions.append(el('p','终局；零到达的条件收益无定义。'));return}
 const next=node.chance?node.possible_cards.map(c=>[c.id,c.card]):node.actions.map((a,i)=>[i,a]);for(const [i,a]of next){const button=el('button',a);button.onclick=()=>guard(async()=>{path.push(i);selected=null;await showNode()});actions.append(button)}if(node.chance){paintStrategy();return;}
 const ranks='AKQJT98765432';const combos=node.players[node.actor].combos;for(let i=0;i<13;i++)for(let j=0;j<13;j++){const name=i===j?ranks[i]+ranks[j]:i<j?ranks[i]+ranks[j]+'s':ranks[j]+ranks[i]+'o';const count=combos.filter(c=>group(c)===name).length;const b=el('button',name+(count?' · '+count:''),'cell '+(count?'active':'empty')+(selected===name?' selected':''));b.dataset.hand=name;b.onclick=()=>{selected=name;renderNode()};$('grid').append(b)}renderCombos();renderManual();paintStrategy()}
function renderCombos(){const u=unitOf(result.config);const head=el('tr');['组合','Equity',`EV (${u})`,`相对原策略 ΔEV (${u})`,...node.actions.map(a=>a+`：频率 / EV (${u})`)].forEach(s=>head.append(el('th',s)));$('combos').querySelector('thead').append(head);const p=node.players[node.actor],n=p.combos.length;const other=comparison?.players?.[node.actor];p.combos.forEach((c,i)=>{if(selected&&group(c)!==selected)return;const valid=p.blocker_adjusted_weights[i]>0;const row=el('tr',undefined,valid?'':'zero');const delta=valid&&other?.blocker_adjusted_weights[i]>0?p.ev[i]-other.ev[i]:null;[c,valid?fmt(p.equity[i]*100,1)+'%':'—',valid?fmt(p.ev[i]):'未定义',fmt(delta),...node.actions.map((a,j)=>fmt(node.strategy_action_major[j*n+i]*100,1)+'% / '+(valid?fmt(node.action_ev_action_major[j*n+i]):'—'))].forEach(s=>row.append(el('td',s)));$('combos').querySelector('tbody').append(row)})}
function renderManual(){} // Implemented by research.js for all postflop streets.
async function studies(){const list=await api('/api/studies');$('studies').replaceChildren();for(const s of list)$('studies').append(new Option(s.name,s.id))}
async function guard(fn){try{await fn()}catch(e){setError(e)}}
$('scenario').addEventListener('input',changed);$('scenario').onsubmit=e=>e.preventDefault();$('baseline').onclick=()=>guard(()=>solve('equilibrium'));$('preview').onclick=()=>guard(()=>solve('preview'));$('response').onclick=()=>guard(()=>solve('fixed'));
$('cancel').onclick=()=>guard(async()=>{if(job)await api('/api/jobs/'+job+'/cancel',{})});$('load-example').onclick=()=>setConfig({...examples[$('example').value],amount_unit:'bb',memory_auto:true});$('combined').onclick=()=>{setTraits([{kind:'station',strength:2,streets:[3,4,5]},{kind:'overbluff',strength:2,streets:[3,4,5]},{kind:'double_barrel_give_up',strength:3,streets:[3,4,5]}]);changed()};$('neutral').onclick=()=>{setTraits([]);changed()};
$('new-scene').onclick=()=>setConfig(dailyScene(examples[$('example').value]));
$('variant').onchange=()=>guard(showNode);$('root').onclick=()=>guard(async()=>{path=[];selected=null;await showNode()});$('back').onclick=()=>guard(async()=>{path.pop();selected=null;await showNode()});$('all-combos').onclick=()=>{selected=null;renderNode()};
$('range-file').onchange=()=>guard(async()=>{const file=$('range-file').files[0];if(file){$('range'+$('range-seat').value).value=await file.text();changed();refreshEditors()}});
$('save').onclick=()=>guard(async()=>{if(!result||stale)throw new Error('请先求解当前配置，避免保存过期结果');await runJob({kind:'save',source:result.result_id,name:$('study-name').value||'本地研究'});await studies();$('status').textContent='配置与完整策略已保存'});
$('open').onclick=()=>guard(async()=>{if(!$('studies').value)return;result=await api('/api/studies/'+$('studies').value);setConfig(result.config);stale=false;$('stale').textContent='';path=[];selected=null;renderSummary();await showNode()});
$('example').insertBefore(new Option('实际范围 Flop · 含 All-in Raise','flop_research_raises.json'),$('example').firstChild);
$('neutral').title='关闭软特质，保留手动覆盖';
$('cancel').onclick=()=>guard(async()=>{for(let i=0;i<100&&!job;i++)await new Promise(r=>setTimeout(r,10));if(job)await api('/api/jobs/'+job+'/cancel',{})});
// The assistant must restore saved settings only after this initializer settles.
// A user import/edit during a slow request takes precedence over daily defaults.
const initialSceneReady=(async()=>{
 const initialVersion=version;
 try{
  examples=await api('/api/examples');
  if(!examples['flop_research_raises.json'])throw Error('初始示例缺失');
  const userModified=version!==initialVersion;
  if(!userModified){
   applyingInitialDefault=true;
   try{$('example').value='flop_research_raises.json';setConfig(dailyScene(examples['flop_research_raises.json']));}
   finally{applyingInitialDefault=false;}
  }
  examplesReady=true;busy(taskBusy);
  return {ok:true,userModified};
 }catch(e){const message='示例载入失败：'+(e?.message||String(e));setError(message);return {ok:false,error:message,userModified:version!==initialVersion};}
})();
initialSceneReady.then(()=>guard(async()=>{await studies();await refreshMemoryResources()}));
