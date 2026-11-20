'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="local-token"]').content;
const analysisEntry = location.pathname === '/analysis';
const entry = analysisEntry ? 'analysis' : 'studio';
const terminal = state => ['completed','failed','cancelled','interrupted'].includes(state);
const stateNames = {queued:'排队中',running:'正在运行',cancelling:'正在取消',completed:'已完成',failed:'失败',cancelled:'已取消',interrupted:'已中断'};
const kindNames = {export:'导出 MP4',demo:'生成测试素材',proxy:'生成预览代理',transcribe:'本地转写',solve:'真实求解',node:'策略节点查询'};
const phaseNames = {building:'建树与资源检查',memory_plan:'内存计划',baseline:'均衡基线迭代',compiling_model:'编译完整对手策略',best_response:'求解 Hero 最佳回应',evaluating_policy:'独立重评策略',reporting:'生成报告',sensitivity:'敏感性模型'};
let project, clipId=null, playhead=0, playing=false, sourceAsset=null, pendingSourceTime=null;
let handDraft=null, subtitleId=null, overlayId=null, lastSolver=null, frameSeq=0, frameTimer=null, overlayKey='';
let agentTask=null, agentCursor=0, agentReply=null, sessionId=null, sessions=[], agentPolling=false;
let polling=false, statusTimer=null, handDirty=false;
let positionTimer=null, positionPromise=Promise.resolve();
const tasks = new Map();
const el = (tag,text,cls) => { const e=document.createElement(tag); if(text!==undefined)e.textContent=text; if(cls)e.className=cls; return e; };
const uid = () => crypto.randomUUID().replaceAll('-','');
const fmt = (n,d=2) => Number.isFinite(n) ? n.toFixed(d) : '未知';
const clock = n => `${String(Math.floor(Math.max(0,n)/60)).padStart(2,'0')}:${(Math.max(0,n)%60).toFixed(1).padStart(4,'0')}`;
const val = id => $(id).value.trim();
const optionalNumber = id => val(id)==='' ? null : Number(val(id));
const show = (id,on) => $(id).classList.toggle('hidden',!on);
function error(err){ $('error').textContent=err?.message||String(err); show('error',true); }
function notice(message){ $('notice').textContent=message; show('notice',!!message); }
async function api(path,body){
  const response=await fetch(path,body===undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json','X-Pokerstudio-Token':token},body:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);
  return data;
}
function bind(id,fn){ $(id).addEventListener('click',async()=>{show('error',false);const b=$(id);b.disabled=true;try{await fn();}catch(e){error(e);}finally{b.disabled=false;syncButtons();}}); }
function parseJSON(id,empty=null){const text=val(id);if(!text)return empty;try{return JSON.parse(text);}catch(e){throw new Error(`${id==='analysis-config'?'分析配置':'配置'} JSON 格式错误：${e.message}`);}}
function cardList(text){if(!text.trim())return [];return text.trim().split(/[\s,]+/).map(x=>['?','??'].includes(x)?null:x);}
const assetFor = id => project.assets.find(a=>a.id===id);
const clipFor = id => project.timeline.find(c=>c.id===id);
function activeClip(t=playhead){return project?.timeline.find(c=>t>=c.start&&t<c.end) || (t===project?.duration?project.timeline.at(-1):null);}
function selectedHand(){return project?.hands.find(h=>h.id===project.selected_hand_id);}
async function edit(command){
  pause(false);
  const next=await api('/api/project/edit',{command,revision:project.revision,project_id:project.id});
  setProject(next);
  return next;
}
function setProject(next,refreshForms=true){
  const changed=!project || next.id!==project.id;
  if(project&&next.id!==project.id&&!agentTask){
    $('chat').replaceChildren();$('agent-events').replaceChildren();$('agent-task-status').textContent='';agentReply=null;
  }
  if(changed){pause(false);sourceAsset=null;clipId=null;sessionId=null;$('session-list').value='';}
  project=next;
  if(!clipFor(clipId))clipId=project.clips[0]?.id||null;
  playhead=Math.min(Math.max(changed?project.playhead||0:playhead,0),project.duration);
  renderProject(refreshForms);
  if(!analysisEntry)seek(playhead,false);
}
function syncButtons(){
  if(!project)return;
  $('undo').disabled=!project.can_undo; $('redo').disabled=!project.can_redo;
  const has=!!clipFor(clipId);
  ['trim','set-in','set-out','split','move-up','move-down','delete-clip'].forEach(id=>$(id).disabled=!has);
  $('play').disabled=!project.clips.length;
  $('cancel-agent').disabled=!agentTask;
}
function renderProject(refreshForms=true){
  $('project-name').value=project.name;
  $('save-status').textContent=`已保存 · 版本 ${project.revision}`;
  $('project-path').value=project.file_path||'';
  $('asset-count').textContent=String(project.assets.length);
  $('duration').textContent=clock(project.duration);
  $('seek').max=project.duration;
  $('preview-stage').style.aspectRatio=`${project.export_settings.width}/${project.export_settings.height}`;
  $('warnings').textContent=project.warnings.join('\n');show('warnings',project.warnings.length>0);
  renderAssets();renderTimeline();renderClip();renderEntityLists();
  if(refreshForms){renderHand(selectedHand());renderText('subtitle',subtitleId);renderText('overlay',overlayId);handDirty=false;}
  const settings=project.export_settings;
  $('export-width').value=settings.width;$('export-height').value=settings.height;$('export-fps').value=settings.fps;
  $('export-subtitles').checked=settings.subtitles!==false;$('export-overlays').checked=settings.overlays!==false;
  syncButtons();renderSessions();
}
function renderAssets(){
  $('assets').replaceChildren();$('transcribe-asset').replaceChildren();
  for(const a of project.assets){
    const box=el('div',undefined,'asset');
    const thumb=el('img',undefined,'asset-thumbnail');thumb.alt=(a.name||'素材')+'缩略图';thumb.loading='lazy';
    thumb.src='/api/thumbnail?id='+encodeURIComponent(a.id)+'&time=0';thumb.onerror=()=>thumb.classList.add('hidden');
    box.append(thumb,el('strong',a.name||a.path.split(/[\\/]/).at(-1)));
    const m=a.metadata;box.append(el('div',`${clock(m.duration)} · ${m.width||'?'}×${m.height||'?'} · ${fmt(m.fps,2)}fps · ${m.audio?.length?'有音轨':'无音轨'}`,'meta'),el('div',a.path,'path'));
    const row=el('div',undefined,'row wrap');
    for(const [name,action] of [['再加到时间线',()=>edit({op:'add_clip',clip:{asset_id:a.id,name:a.name,in:0,out:m.duration}})],['重新定位',async()=>{const path=prompt('请输入该素材的新完整路径',a.path);if(path)setProject(await api('/api/assets/import',{path,asset_id:a.id,project_id:project.id}));}],['生成代理',async()=>trackTask(await api('/api/proxy',{asset_id:a.id}),async()=>setProject(await api('/api/project'))) ]]){
      const b=el('button',name);b.onclick=()=>action().catch(error);row.append(b);
    }
    box.append(row);$('assets').append(box);$('transcribe-asset').append(new Option(a.name||a.id,a.id));
  }
}
function renderTimeline(){
  $('timeline').replaceChildren();show('clip-empty',!project.clips.length);
  for(const c of project.timeline){
    const b=el('button',undefined,c.id===clipId?'active':'');b.dataset.clipId=c.id;
    b.style.flexGrow=String(Math.max(1,c.duration));
    b.append(el('strong',c.name||assetFor(c.asset_id)?.name||'片段'),el('small',`${clock(c.start)} → ${clock(c.end)}`),el('small',`素材 ${fmt(c.in)}–${fmt(c.out)}s`));
    b.onclick=()=>{clipId=c.id;renderTimeline();renderClip();seek(c.start+.001);};$('timeline').append(b);
  }
}
function renderClip(){const c=clipFor(clipId);$('clip-name').value=c?.name||'';$('clip-in').value=c?.in??'';$('clip-out').value=c?.out??'';syncButtons();}
function seek(t,shouldPause=true){
  if(!project)return;if(shouldPause)pause(false);
  playhead=Math.min(Math.max(Number(t)||0,0),project.duration);
  $('seek').value=playhead;$('playhead').value=playhead.toFixed(2);
  if(shouldPause)schedulePosition();
  const clip=activeClip();show('preview-empty',!clip);if(!clip){show('frame',false);show('playing-overlay',false);return;}
  const time=clip.in+Math.min(playhead-clip.start,clip.duration-.0001);
  if(sourceAsset!==clip.asset_id){sourceAsset=clip.asset_id;pendingSourceTime=time;$('video').src='/media/'+encodeURIComponent(clip.asset_id);$('video').load();}
  else if($('video').readyState>=1 && Math.abs($('video').currentTime-time)>.05){$('video').currentTime=time;}
  if(!playing){$('preview-mode').textContent='完整合成 · 暂停画面';show('playing-overlay',false);requestFrame();}
}
function requestFrame(){
  clearTimeout(frameTimer);const seq=++frameSeq;
  frameTimer=setTimeout(()=>{const image=new Image();const t=playhead;image.onload=()=>{if(seq===frameSeq&&!playing){$('frame').src=image.src;show('frame',true);}};image.onerror=()=>{if(seq===frameSeq&&!playing){show('frame',false);notice('完整预览帧暂不可用，请检查素材路径、媒体能力或稍后重试。');}};image.src=`/api/frame?time=${t.toFixed(3)}&revision=${project.revision}`;},130);
}
function overlayIdentity(t){
  return JSON.stringify([project.revision,
    project.subtitles.filter(x=>x.enabled!==false&&t>=x.start&&t<x.end).map(x=>x.id),
    project.overlays.filter(x=>x.enabled!==false&&t>=x.start&&t<x.end).map(x=>x.id),
    project.hands.filter(x=>x.overlay_enabled!==false&&t>=x.start&&t<x.end).map(x=>[x.id,x.actions?.filter(a=>a.time<=t).length,x.board_reveal?.filter(a=>a.time<=t).length])]);
}
function updateOverlay(){
  const key=overlayIdentity(playhead);if(key===overlayKey)return;overlayKey=key;
  const image=new Image();image.onload=()=>{if(playing&&key===overlayKey){$('playing-overlay').src=image.src;show('playing-overlay',true);}};image.onerror=()=>{if(key===overlayKey)show('playing-overlay',false);};image.src=`/api/overlay?time=${playhead.toFixed(3)}&revision=${project.revision}`;
}
function persistPosition(time=playhead,projectId=project?.id){
  if(analysisEntry||!projectId)return Promise.resolve();
  // Serialize metadata writes. This endpoint deliberately leaves revision and
  // undo history alone; a cursor movement is not an editing operation.
  const next=positionPromise.catch(()=>{}).then(async()=>{if(project?.id!==projectId)return;const result=await api('/api/project/playhead',{time,project_id:projectId});if(project?.id===projectId)project.playhead=result.playhead??time;});
  positionPromise=next;return next;
}
function schedulePosition(){
  clearTimeout(positionTimer);const time=playhead,projectId=project?.id;
  positionTimer=setTimeout(()=>persistPosition(time,projectId).catch(e=>{if(project?.id===projectId)error(e);}),400);
}
function pause(frame=true){playing=false;$('video').pause();$('play').textContent='▶ 播放';if(frame&&project){seek(playhead,false);schedulePosition();}}
async function play(){
  if(playing){pause();return;}
  clearTimeout(positionTimer);
  if(playhead>=project.duration-.02)seek(0);
  playing=true;frameSeq++;clearTimeout(frameTimer);show('frame',false);overlayKey='';$('preview-mode').textContent='播放 · 实时牌面与字幕';$('play').textContent='Ⅱ 暂停';
  if($('video').readyState<1)await new Promise((resolve,reject)=>{$('video').addEventListener('loadedmetadata',resolve,{once:true});$('video').addEventListener('error',()=>reject(new Error('浏览器无法播放该素材。可生成兼容代理后重试。')),{once:true});});
  await $('video').play();updateOverlay();
}
$('video').onloadedmetadata=()=>{if(pendingSourceTime!==null){$('video').currentTime=pendingSourceTime;pendingSourceTime=null;}if(playing)$('video').play().catch(error);};
$('video').ontimeupdate=()=>{
  if(!playing||!project)return;const clip=activeClip();if(!clip)return;
  if($('video').currentTime>=clip.out-.025){const next=project.timeline[project.timeline.findIndex(c=>c.id===clip.id)+1];if(next){playhead=next.start;seek(playhead,false);$('video').play().catch(error);}else{playhead=project.duration;pause();}return;}
  playhead=clip.start+Math.max(0,$('video').currentTime-clip.in);$('seek').value=playhead;$('playhead').value=playhead.toFixed(2);updateOverlay();
};
$('video').onended=()=>{if(playing){const clip=activeClip();const next=project.timeline[project.timeline.findIndex(c=>c.id===clip?.id)+1];if(next){seek(next.start,false);$('video').play().catch(error);}else pause();}};
$('video').onerror=()=>{if(project?.clips.length){pause(false);notice('底视频解码失败。请使用素材的“生成代理”，或重新定位可播放视频。');}};
$('seek').oninput=()=>seek($('seek').value);$('playhead').onchange=()=>seek($('playhead').value);
bind('play',play);bind('back-second',()=>seek(playhead-1));bind('forward-second',()=>seek(playhead+1));
bind('trim',()=>edit({op:'trim_clip',id:clipId,in:Number(val('clip-in')),out:Number(val('clip-out')),name:val('clip-name')}));
bind('set-in',()=>{const c=activeClip();if(c?.id!==clipId)throw new Error('请先定位到所选片段内。');$('clip-in').value=(c.in+playhead-c.start).toFixed(3);});
bind('set-out',()=>{const c=activeClip();if(c?.id!==clipId)throw new Error('请先定位到所选片段内。');$('clip-out').value=(c.in+playhead-c.start).toFixed(3);});
bind('split',async()=>{const c=activeClip();if(c?.id!==clipId)throw new Error('请先定位到所选片段内。');await edit({op:'split_clip',id:c.id,at:c.in+playhead-c.start});});
bind('move-up',()=>edit({op:'move_clip',id:clipId,to:Math.max(0,project.clips.findIndex(c=>c.id===clipId)-1)}));
bind('move-down',()=>edit({op:'move_clip',id:clipId,to:Math.min(project.clips.length-1,project.clips.findIndex(c=>c.id===clipId)+1)}));
bind('delete-clip',()=>edit({op:'delete_clip',id:clipId}));
bind('undo',async()=>{pause(false);setProject(await api('/api/project/undo',{project_id:project.id}));});bind('redo',async()=>setProject(await api('/api/project/redo',{project_id:project.id})));
async function refreshProjects(){const list=await api('/api/projects');$('project-list').replaceChildren(new Option('选择已保存项目…',''));for(const p of list)$('project-list').append(new Option(p.name,p.path));}
bind('save',async()=>{if(!analysisEntry){clearTimeout(positionTimer);await persistPosition();setProject(await api('/api/project/save',{}));await refreshProjects();notice(`项目已保存：${project.file_path}`);}else{await saveAnalysis();}});
bind('rename-project',()=>edit({op:'name',name:val('project-name')}));
bind('new-project',async()=>{setProject(await api('/api/project/new',{name:val('project-name')||'未命名扑克剪辑'}));await refreshProjects();});
bind('refresh-projects',refreshProjects);
bind('open-project',async()=>{if(!$('project-list').value)throw new Error('请先选择项目。');setProject(await api('/api/project/open',{path:$('project-list').value}));await loadSessions();});
bind('open-path',async()=>setProject(await api('/api/project/open',{path:val('project-path')})));
bind('save-as',async()=>{setProject(await api('/api/project/save',{path:val('project-path')}));await refreshProjects();});
bind('import-path',async()=>{notice('正在读取视频信息…');setProject(await api('/api/assets/import',{path:val('asset-path'),project_id:project.id}));$('asset-path').value='';notice('素材已导入，原文件保持完整。');});
$('asset-file').onchange=async()=>{const file=$('asset-file').files[0];if(!file)return;notice('正在复制素材并读取信息…');try{const response=await fetch('/api/assets/upload',{method:'POST',headers:{'X-Pokerstudio-Token':token,'X-Filename':encodeURIComponent(file.name),'X-Project-Id':project.id},body:file});const data=await response.json();if(!response.ok)throw new Error(data.error);setProject(data);notice('素材已导入。');}catch(e){error(e);}finally{$('asset-file').value='';}};
bind('demo',async()=>trackTask(await api('/api/demo',{}),async()=>{setProject(await api('/api/project'));notice('短测试素材已生成并导入；它是测试用途，不是真实扑克录像。');}));
bind('transcribe',async()=>{const asset_id=$('transcribe-asset').value;if(!asset_id)throw new Error('请先导入视频并选择素材。');const task=trackTask(await api('/api/transcribe',{asset_id,model_path:val('transcribe-model')||null}));Object.assign(tasks.get(task.task_id),{sourceAsset:asset_id,sourcePath:assetFor(asset_id).path,projectId:project.id});});

function renderEntityLists(){
  $('hand-list').replaceChildren(new Option('选择 / 新建手牌…',''));for(const h of project.hands)$('hand-list').append(new Option(h.title||`手牌 ${clock(h.start)}`,h.id));$('hand-list').value=project.selected_hand_id||'';
  for(const kind of ['subtitle','overlay']){const list=$(kind+'-list');list.replaceChildren(new Option(kind==='subtitle'?'新建字幕':'新建说明文字',''));for(const item of project[kind==='subtitle'?'subtitles':'overlays'])list.append(new Option(`${clock(item.start)} · ${item.text.slice(0,35)}`,item.id));list.value=(kind==='subtitle'?subtitleId:overlayId)||'';}
}
function renderHand(hand){
  handDraft=structuredClone(hand||{id:uid(),title:'',start:playhead,end:Math.max(playhead+1,project?.duration||1),amount_unit:'chips',street:'river',pot:null,effective_stack:null,board:[],players:[{id:uid(),name:'Hero',position:'OOP',cards:[null,null],range:null},{id:uid(),name:'对手',position:'IP',cards:[null,null],range:null}],actions:[],board_reveal:[],blinds:{small:null,big:null,straddle:null},notes:'',overlay_enabled:true,solver_config:null});
  const h=handDraft;for(const [id,key] of [['hand-title','title'],['hand-start','start'],['hand-end','end'],['hand-unit','amount_unit'],['hand-street','street'],['hand-pot','pot'],['hand-stack','effective_stack'],['hand-notes','notes']])$(id).value=h[key]??'';
  for(const k of ['small','big','straddle'])$('blind-'+k).value=h.blinds?.[k]??'';
  $('hand-board').value=h.board?.map(c=>c||'?').join(' ')||'';$('hand-overlay').checked=h.overlay_enabled!==false;
  $('hand-solver-config').value=h.solver_config?JSON.stringify(h.solver_config,null,2):'';
  renderHandRows();show('hand-result',!!h.analysis);if(h.analysis)renderSolver(h.analysis.report,'hand-result',h.analysis.stale);
}
function field(kind,value,key,placeholder=''){const x=document.createElement(kind==='select'?'select':'input');x.dataset.field=key;if(kind!=='select'){x.type=kind;x.placeholder=placeholder;}x.value=value??'';return x;}
function choice(values,value,key){const x=field('select',value,key);for(const item of values){const [v,label]=Array.isArray(item)?item:[item,item];x.append(new Option(label,v));}if(value!==undefined&&value!==null&&![...x.options].some(o=>o.value===value))x.append(new Option(value,value));x.value=value;return x;}
function rowDelete(row,collection,index){const b=el('button','×');b.title='移除此项';b.onclick=()=>{collectHand();handDraft[collection].splice(index,1);renderHandRows();handDirty=true;};row.append(b);}
function renderHandRows(){
  $('players').replaceChildren();$('actions').replaceChildren();$('reveals').replaceChildren();
  handDraft.players.forEach((p,i)=>{const row=el('div',undefined,'player-row');row.dataset.id=p.id;
    const defs=[['名字',field('text',p.name,'name')],['位置',choice(['OOP','IP','BTN','SB','BB','UTG','CO'],p.position||'OOP','position')],['底牌 1',field('text',p.cards?.[0],'card0','?')],['底牌 2',field('text',p.cards?.[1],'card1','?')],['分析范围',field('text',p.range,'range','未知留空')]];
    for(const [label,x]of defs){const l=el('label',label);l.append(x);row.append(l);}rowDelete(row,'players',i);$('players').append(row);});
  if(handDraft.actions?.length){const labels=el('div',undefined,'column-labels actions');['街道','玩家','行动','金额','项目秒','行动后池',''].forEach(x=>labels.append(el('span',x)));$('actions').append(labels);}
  (handDraft.actions||[]).forEach((a,i)=>{const row=el('div',undefined,'action-row');row.append(choice([['preflop','Preflop'],['flop','Flop'],['turn','Turn'],['river','River']],a.street,'street'),choice(handDraft.players.map(p=>[p.id,p.name||p.position]),a.player_id,'player_id'),choice([['check','Check'],['bet','Bet'],['call','Call'],['raise','Raise'],['fold','Fold'],['allin','All-in'],['showdown','摊牌']],a.type,'type'),field('number',a.amount,'amount','未知'),field('number',a.time,'time','项目秒'),field('number',a.pot_after,'pot_after','未知'));rowDelete(row,'actions',i);$('actions').append(row);});
  (handDraft.board_reveal||[]).forEach((r,i)=>{const row=el('div',undefined,'reveal-row');row.append(field('number',r.time,'time','项目秒'),field('text',r.cards?.map(c=>c||'?').join(' '),'cards','已显示牌，例如 2c 3d 7h'));rowDelete(row,'board_reveal',i);$('reveals').append(row);});
}
function collectRows(container){return [...$(container).querySelectorAll('.'+({players:'player-row',actions:'action-row',reveals:'reveal-row'}[container]))].map(row=>{const item={};for(const x of row.querySelectorAll('[data-field]'))item[x.dataset.field]=x.type==='number'?(x.value===''?null:Number(x.value)):x.value.trim();if(row.dataset.id)item.id=row.dataset.id;return item;});}
function collectHand(){
  if(!handDraft)return null;const h=handDraft;
  Object.assign(h,{title:val('hand-title'),start:Number(val('hand-start')),end:Number(val('hand-end')),amount_unit:val('hand-unit'),street:val('hand-street'),pot:optionalNumber('hand-pot'),effective_stack:optionalNumber('hand-stack'),board:cardList(val('hand-board')),notes:val('hand-notes'),overlay_enabled:$('hand-overlay').checked,blinds:{small:optionalNumber('blind-small'),big:optionalNumber('blind-big'),straddle:optionalNumber('blind-straddle')},solver_config:parseJSON('hand-solver-config')});
  h.players=collectRows('players').map(p=>({id:p.id,name:p.name,position:p.position,cards:[p.card0||null,p.card1||null],range:p.range||null}));
  h.actions=collectRows('actions');h.board_reveal=collectRows('reveals').map(r=>({...r,cards:cardList(r.cards)}));return h;
}
async function saveHand(){const item=structuredClone(collectHand());delete item.analysis;await edit({op:'upsert_hand',item});handDirty=false;}
$('detail-hand').addEventListener('input',()=>handDirty=true);
$('hand-list').onchange=()=>{if($('hand-list').value)edit({op:'select_hand',id:$('hand-list').value}).catch(error);else renderHand(null);};
bind('new-hand',()=>{renderHand(null);$('hand-list').value='';$('hand-start').value=playhead.toFixed(2);$('hand-end').value=Math.min(playhead+5,project.duration||playhead+5).toFixed(2);handDirty=true;});
bind('delete-hand',()=>{if(!selectedHand())throw new Error('请选择已保存手牌。');return edit({op:'delete_hand',id:project.selected_hand_id});});
bind('add-player',()=>{collectHand();handDraft.players.push({id:uid(),name:'玩家',position:'BTN',cards:[null,null],range:null});renderHandRows();});
bind('add-action',()=>{collectHand();handDraft.actions.push({street:handDraft.street,player_id:handDraft.players[0]?.id,type:'check',amount:null,time:Number(playhead.toFixed(2)),pot_after:null});renderHandRows();});
bind('add-reveal',()=>{collectHand();handDraft.board_reveal.push({time:Number(playhead.toFixed(2)),cards:handDraft.board});renderHandRows();});
bind('hand-start-now',()=>{$('hand-start').value=playhead.toFixed(2);});bind('hand-end-now',()=>{$('hand-end').value=playhead.toFixed(2);});bind('save-hand',saveHand);
bind('extract-hand',async()=>{await saveHand();const h=selectedHand();await edit({op:'crop_range',start:h.start,end:h.end});});
bind('hand-config-example',async()=>{$('hand-solver-config').value=JSON.stringify(await api('/api/solver/example?name=river.json'),null,2);notice('只载入了示例分析配置。实际手牌字段必须与配置一致才可求解。');});
bind('solve-hand',async()=>{await saveHand();trackTask(await api('/api/solver/start',{entry:'studio',project_id:project.id,options:selectedHand().solver_config?undefined:{hero:Number(val('hand-hero'))}}),async(task)=>{const r=await api('/api/solver/result?id='+encodeURIComponent(task.task_id));lastSolver=r;setProject(await api('/api/project'));renderSolver(r,'hand-result',selectedHand()?.analysis?.stale);});});
bind('explain-hand',async()=>{await saveHand();$('agent-message').value='读取当前选中的手牌；如有成功且未过期的 solver 报告，基于真实结果与其范围、尺寸和精度假设起草简洁中文讲稿，并通过 update_hand 写入 notes。没有报告时只依据已确认手牌叙述，不编造 EV。';$('agent-message').focus();});
function renderText(kind,id){const item=project[kind==='subtitle'?'subtitles':'overlays'].find(x=>x.id===id);$(kind+'-start').value=item?.start??Number(playhead.toFixed(2));$(kind+'-end').value=item?.end??Number(Math.min(playhead+2,Math.max(project.duration,playhead+2)).toFixed(2));$(kind+'-text').value=item?.text||'';$(kind+'-enabled').checked=item?.enabled!==false;}
for(const kind of ['subtitle','overlay']){
  $(kind+'-list').onchange=()=>{if(kind==='subtitle')subtitleId=$(kind+'-list').value||null;else overlayId=$(kind+'-list').value||null;renderText(kind,$(kind+'-list').value);};
  bind('new-'+kind,()=>{if(kind==='subtitle')subtitleId=null;else overlayId=null;$(kind+'-list').value='';renderText(kind,null);});
  bind('save-'+kind,()=>{const id=(kind==='subtitle'?subtitleId:overlayId)||uid();if(kind==='subtitle')subtitleId=id;else overlayId=id;return edit({op:'upsert_'+kind,item:{id,start:Number(val(kind+'-start')),end:Number(val(kind+'-end')),text:val(kind+'-text'),enabled:$(kind+'-enabled').checked}});});
  bind('delete-'+kind,()=>{const id=kind==='subtitle'?subtitleId:overlayId;if(!id)throw new Error('请先选择已保存的条目。');if(kind==='subtitle')subtitleId=null;else overlayId=null;return edit({op:'delete_'+kind,id});});
}
bind('import-srt',async()=>setProject(await api('/api/subtitles/import',{text:val('srt-text')})));
$('srt-file').onchange=async()=>{const file=$('srt-file').files[0];if(!file)return;try{$('srt-text').value=await file.text();setProject(await api('/api/subtitles/import',{text:$('srt-text').value}));notice('SRT 已导入，可编辑或撤销。');}catch(e){error(e);}finally{$('srt-file').value='';}};
document.querySelectorAll('[data-detail]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-detail]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.detail-view').forEach(x=>x.classList.toggle('hidden',x.id!=='detail-'+b.dataset.detail));});
bind('export',async()=>{await edit({op:'settings',settings:{width:Number(val('export-width')),height:Number(val('export-height')),fps:Number(val('export-fps')),subtitles:$('export-subtitles').checked,overlays:$('export-overlays').checked}});trackTask(await api('/api/export',{}));});

async function saveAnalysis(){const result=await api('/api/analysis/config',{config:parseJSON('analysis-config')});notice('独立分析配置已验证并保存。');return result;}
bind('save-analysis',saveAnalysis);
bind('load-analysis-example',async()=>{$('analysis-config').value=JSON.stringify(await api('/api/solver/example?name='+encodeURIComponent(val('analysis-example'))),null,2);notice('已载入明确的研究示例。修改并确认配置后可真实求解。');});
bind('solve-analysis',async()=>{await saveAnalysis();trackTask(await api('/api/solver/start',{entry:'analysis'}),async(task)=>{lastSolver=await api('/api/solver/result?id='+encodeURIComponent(task.task_id));renderSolver(lastSolver,'analysis-result');});});
bind('inspect-node',async()=>{if(!lastSolver)throw new Error('请先完成一次真实求解。');const id=lastSolver.result_id;if(!id)throw new Error('报告没有可查询的结果 ID。');trackTask(await api('/api/solver/node',{id,path:parseJSON('node-path'),variant:val('node-variant')}),async(task)=>{$('solver-raw').textContent=JSON.stringify(await api('/api/solver/result?id='+encodeURIComponent(task.task_id)),null,2);});});
function renderSolver(r,target,stale=false){
  const box=$(target);show(target,true);box.replaceChildren();box.classList.toggle('stale',!!stale);const p=r.precision||{},c=r.config||{};
  box.append(el('strong',`${stale?'结果已过期 · ':''}${c.mode==='equilibrium'?'均衡基线':c.mode==='fixed'?'固定对手最佳回应':'固定模型预览'}`));
  box.append(el('p',`Hero (${c.hero===0?'OOP':'IP'}) 根 EV：${fmt(r.ev?.[c.hero],6)} 筹码${c.mode==='fixed'?`\n同一模型原 Hero EV：${fmt(r.same_model_baseline_hero_ev,6)} → BR：${fmt(r.hero_best_response_ev,6)}；变化 ${fmt(r.hero_improvement,6)}`:''}`));
  box.append(el('p',`牌面 ${c.board?.join(' ')}；底池 ${c.pot}，有效剩余 ${c.stack}。\nOOP 范围 ${c.players?.[0]}\nIP 范围 ${c.players?.[1]}\n下注 ${c.bets?.join(' / ')}；加注 ${c.raises?.join(' / ')||'无'}。Hero 根行动策略为真实输出，可能是纯策略。`));
  box.append(el('p',`基线 exploitability ${fmt(p.baseline_exploitability_chips,8)} 筹码 · ${p.baseline_iterations} 次 · ${p.baseline_stop_reason}\n${p.metric||'精度'} ${fmt(p.actual_chips,8)} 筹码 · ${p.stop_reason}\n无未来抽水；旧投入为沉没成本。仅适用于这些范围、尺寸和模型，不能视为无条件结论。`));
  if(r.root?.actions){const actor=r.root.actor,n=r.root.players?.[actor]?.combos?.length||0;box.append(el('p',`根动作：${r.root.actions.join(' / ')}；${n} 个具体组合。详细概率与 EV 在完整报告中。`));}
  const detail=el('details'),summary=el('summary','查看完整输入、策略和报告'),raw=el('pre',JSON.stringify(r,null,2),'raw');detail.append(summary,raw);box.append(detail);$('solver-raw').textContent=JSON.stringify(r,null,2);
}
function trackTask(task,onDone=null){const id=task.task_id||(task.kind==='solve'||task.kind==='node'?'solve:':'media:')+task.id;task.task_id=id;tasks.set(id,{data:task,onDone,handled:false});renderTasks();return task;}
function renderTasks(){
  const container=$(analysisEntry?'analysis-tasks':'tasks');container.replaceChildren();
  for(const [id,record]of [...tasks].reverse()){
    if(analysisEntry&&!['solve','node'].includes(record.data.kind))continue;
    const task=record.data,s=task.state||task.status,box=el('div',undefined,'task');box.dataset.taskId=id;
    box.append(el('span',stateNames[s]||s,'state'),el('strong',kindNames[task.kind]||task.kind||'任务'));
    if(typeof task.progress==='number'){const progress=document.createElement('progress');progress.max=1;progress.value=task.progress;box.append(progress);}
    const phase=typeof task.progress==='object'?`${phaseNames[task.progress.phase]||task.progress.phase||''} ${JSON.stringify(task.progress.detail||{})}`:task.logs?.at(-1)||'';
    box.append(el('div',task.error||phase||id,'task-detail'));
    if(!terminal(s)){const cancel=el('button','取消任务');cancel.onclick=()=>api('/api/task/cancel',{id}).then(t=>{record.data={...t,task_id:id};renderTasks();}).catch(error);box.append(cancel);}
    if(s==='completed'&&task.result?.path&&task.kind==='export'){
      const name=task.result.path.split(/[\\/]/).at(-1),url='/exports/'+encodeURIComponent(name);const open=el('a','播放成片');open.href=url;open.target='_blank';open.rel='noopener';const download=el('a','下载 MP4');download.href=url+'?download=1';box.append(open,download,el('div',task.result.path,'task-detail'));
    }
    if(s==='completed'&&task.kind==='transcribe'&&task.result){const b=el('button','按时间线导入转写字幕');b.onclick=async()=>{try{const r=task.result;if(r.subtitles){let subtitles=r.subtitles;if(r.requires_timeline_mapping||r.time_basis==='source_media_seconds'){if(record.projectId!==project.id||!record.sourceAsset||assetFor(record.sourceAsset)?.path!==record.sourcePath)throw new Error('无法确认此转写对应当前素材。请对当前项目素材重新转写，不能把素材秒直接当成项目秒。');subtitles=[];for(const clip of project.timeline.filter(c=>c.asset_id===record.sourceAsset))for(const subtitle of r.subtitles){const left=Math.max(subtitle.start,clip.in),right=Math.min(subtitle.end,clip.out);if(left<right)subtitles.push({...subtitle,id:uid(),start:clip.start+left-clip.in,end:clip.start+right-clip.in});}if(!subtitles.length)throw new Error('转写字幕与当前素材片段没有重叠。');}await edit({op:'replace_subtitles',subtitles});notice('已按素材入出点、片段排列转换为项目时间字幕；可撤销。');}else if(r.srt)setProject(await api('/api/subtitles/import',{text:r.srt}));else throw new Error('转写结果没有 SRT / subtitles；请查看后端结果。');}catch(e){error(e);}};box.append(b);}
    container.append(box);
  }
}
async function pollTasks(){
  if(polling)return;polling=true;
  try{for(const [id,record] of tasks){const old=record.data.state||record.data.status;if(terminal(old)&&record.handled)continue;record.data=await api('/api/task?id='+encodeURIComponent(id));record.data.task_id=id;const state=record.data.state||record.data.status;if(terminal(state)&&!record.handled){record.handled=true;if(state==='completed'){if(record.onDone)await record.onDone(record.data);else if(record.data.kind==='demo'||record.data.kind==='proxy')setProject(await api('/api/project'));}else error(record.data.error||stateNames[state]);}}renderTasks();}catch(e){error(e);}finally{polling=false;}
}

function localResetTime(seconds){
  if(typeof seconds!=='number'||!Number.isFinite(seconds))return '未知';
  return new Intl.DateTimeFormat('zh-CN',{timeZone:'America/Los_Angeles',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(seconds*1000));
}
function quotaWindow(window,fallback){
  if(!window)return null;
  const used=window.usedPercent,minutes=window.windowDurationMins;
  const duration=minutes===10080?'每周':typeof minutes==='number'?(minutes>=60?`${fmt(minutes/60,minutes%60===0?0:1)} 小时`:`${minutes} 分钟`):fallback;
  const remaining=typeof used==='number'&&Number.isFinite(used)?`${fmt(Math.max(0,Math.min(100,100-used)),1)}%`:'未知';
  return `${duration}剩余 ${remaining} · 重置 ${localResetTime(window.resetsAt)}`;
}
function renderAgentStatus(data){
  const provider=val('provider'),s=data[provider]||data;const lines=[provider==='subscription'?'正在使用本人订阅额度':'正在使用 OpenAI API 独立计费'];
  lines.push(provider==='subscription'?(s.logged_in?'已登录':'尚未登录'):(s.configured?`API 已配置 · ${s.allow_paid?'付费调用已开启':'未开启付费调用'}`:'API 等待配置 / 尚未验证'));
  if(s.error)lines.push(s.error);if(s.session_warning)lines.push(s.session_warning);
  const rates=s.rate_limits||{},buckets=rates.rateLimitsByLimitId||{},quota=buckets.codex||rates.rateLimits||Object.values(buckets).find(x=>x?.primary||x?.secondary)||{};
  const plan=s.account?.planType||quota.planType||s.planType;if(plan)lines.push('订阅方案：'+plan);
  for(const line of [quotaWindow(quota.primary,'短期额度'),quotaWindow(quota.secondary,'长期额度')])if(line)lines.push(line);
  if(s.rate_limits_error)lines.push('额度状态暂不可用');
  lines.push(`本次运行真实请求已完成：${s.verified_models?.filter(Boolean).join(', ')||'暂无'}`);
  const history=(s.historical_model_validations||[]).filter(v=>v.model).slice(-3);
  if(history.length){lines.push('历史完成记录（不保证当前权限/额度）：');for(const v of history)lines.push(`${v.model} · ${v.auth_mode||provider} · ${localResetTime(v.validated_at)}`);}
  if(s.login_pending)lines.push('等待在正式登录网页完成操作…');$('agent-status').textContent=lines.join('\n');
  if(provider==='subscription'&&s.mode)$('subscription-mode').value=s.mode;
  if(s.logged_in){show('login-link',false);show('cancel-login',false);clearInterval(statusTimer);statusTimer=null;}
}
async function refreshAgent(){renderAgentStatus(await api('/api/agent/status?provider='+val('provider')));}
function providerChanged(){show('subscription-settings',val('provider')==='subscription');show('api-settings',val('provider')==='api');sessionId=null;$('session-list').value='';$('agent-model').value='';renderSessions();refreshAgent().catch(error);}
$('provider').onchange=providerChanged;
bind('refresh-agent',refreshAgent);
bind('apply-subscription',async()=>{await api('/api/agent/configure-subscription',{mode:val('subscription-mode')});sessionId=null;await refreshAgent();notice('已应用明确的订阅登录方式。');});
bind('login',async()=>{
  const mode=val('subscription-mode');const r=await api('/api/agent/login',{mode});const url=r.authUrl||r.verificationUrl||r.verification_uri||r.verification_url;
  if(url){const parsed=new URL(url);if(parsed.protocol!=='https:')throw new Error('正式登录地址必须为 HTTPS。');$('login-link').replaceChildren();const a=el('a','打开 OpenAI 正式登录页面');a.href=url;a.target='_blank';a.rel='noopener';$('login-link').append(a);if(r.userCode||r.user_code)$('login-link').append(el('p','设备代码：'+(r.userCode||r.user_code)));show('login-link',true);show('cancel-login',true);$('cancel-login').dataset.loginId=r.loginId||'';notice('请点击正式登录链接，在新页面完成本人账号登录，然后回到本应用检查状态。');clearInterval(statusTimer);statusTimer=setInterval(()=>refreshAgent().catch(error),3000);}else renderAgentStatus(r);await refreshAgent();
});
bind('cancel-login',async()=>{await api('/api/agent/cancel-login',{login_id:$('cancel-login').dataset.loginId||null});show('login-link',false);show('cancel-login',false);clearInterval(statusTimer);statusTimer=null;await refreshAgent();});
bind('configure-api',async()=>{const api_key=$('api-key').value;try{await api('/api/agent/configure-api',{api_key,model:val('api-model'),allow_paid:$('api-paid').checked});}finally{$('api-key').value='';}await refreshAgent();notice('API 配置保存在本地后端内存；应用重启后需重新填写。');});
bind('load-models',async()=>{const r=await api('/api/agent/models?provider='+val('provider'));$('model-options').replaceChildren();for(const m of r.models){const option=document.createElement('option');option.value=m.model||m.id;option.label=(m.displayName||option.value)+(m.verified?' · 已验证':' · 候选');$('model-options').append(option);}notice(r.note||'已读取模型候选；实际完成请求后才验证权限。');});
async function loadSessions(){sessions=await api('/api/agent/sessions');renderSessions();}
function renderSessions(){
  const list=$('session-list');list.replaceChildren(new Option('新会话',''));
  for(const s of sessions){if(s.provider!==val('provider')||s.context?.entry!==entry)continue;if(entry==='studio'&&s.context?.project_id!==project?.id)continue;list.append(new Option((s.messages?.find(m=>m.role==='user')?.text||s.id).slice(0,28),s.id));}list.value=sessionId||'';
}
function chatMessage(role,text){const box=el('div',undefined,'message '+role);box.append(el('span',role==='user'?'你':'助手','role'),el('span',text,'message-text'));$('chat').append(box);$('chat').scrollTop=$('chat').scrollHeight;return box.querySelector('.message-text');}
function newSession(){sessionId=null;$('session-list').value='';$('chat').replaceChildren();$('agent-events').replaceChildren();notice('下次发送会创建当前入口的新会话。');}
bind('new-session',newSession);
$('session-list').onchange=()=>{sessionId=$('session-list').value||null;$('chat').replaceChildren();const session=sessions.find(s=>s.id===sessionId);for(const m of session?.messages||[])chatMessage(m.role,m.text+(m.error?'\n'+m.error:''));};
function renderAgentEvents(events){for(const event of events){if(event.type==='delta')continue;const row=el('div',undefined,'event');row.append(el('strong',event.type+(event.name?' · '+event.name:'')));const raw={...event};delete raw.time;row.append(el('pre',JSON.stringify(raw,null,2)));$('agent-events').append(row);if(event.type==='tool_result'&&event.success&&event.result?.task_id){const task=event.result;if(task.task_id.startsWith('solve:'))trackTask(task,async(t)=>{lastSolver=await api('/api/solver/result?id='+encodeURIComponent(t.task_id));if(analysisEntry)renderSolver(lastSolver,'analysis-result');else setProject(await api('/api/project'));});else if(task.task_id.startsWith('media:'))trackTask(task);}}}
bind('send-agent',async()=>{
  if(agentTask)throw new Error('请先完成或取消当前助手请求。');const message=val('agent-message');if(!message)throw new Error('请输入请求。');
  if(handDirty&&!analysisEntry)notice('手牌表单中有未保存修改。助手读取的是已保存项目；先保存可让助手使用最新数据。');
  const r=await api('/api/agent/start',{message,provider:val('provider'),model:val('agent-model')||null,session_id:sessionId,entry});
  $('agent-message').value='';chatMessage('user',message);agentReply=chatMessage('assistant','正在连接所选 provider…');agentTask=r.id;sessionId=r.session_id;agentCursor=0;$('agent-task-status').textContent=stateNames[r.status]||r.status;syncButtons();await pollAgent();
});
bind('cancel-agent',async()=>{if(agentTask){await api('/api/agent/cancel',{id:agentTask});$('agent-task-status').textContent='已请求取消，等待真实终态…';}});
async function pollAgent(){
  if(!agentTask||agentPolling)return;agentPolling=true;
  try{const r=await api(`/api/agent/task?id=${encodeURIComponent(agentTask)}&after=${agentCursor}`);agentCursor=r.cursor;agentReply.textContent=r.text||r.error||'正在处理…';renderAgentEvents(r.events);$('agent-task-status').textContent=`${stateNames[r.status]||r.status} · ${r.provider==='api'?'API 独立计费':'本人订阅'} · ${r.model||'等待模型'}`;if(terminal(r.status)){if(r.error)error(r.error);agentTask=null;syncButtons();const next=await api('/api/project');if(next.revision!==project.revision)setProject(next,!handDirty);await loadSessions();await refreshAgent();}}
  catch(e){error(e);}finally{agentPolling=false;}
}
async function boot(){
  document.querySelectorAll('.studio-only').forEach(x=>x.classList.toggle('hidden',analysisEntry));document.querySelectorAll('.analysis-only').forEach(x=>x.classList.toggle('hidden',!analysisEntry));$('workspace').classList.toggle('analysis-mode',analysisEntry);$('studio-tab').classList.toggle('active',!analysisEntry);$('analysis-tab').classList.toggle('active',analysisEntry);$('agent-context').textContent=analysisEntry?'独立分析':'剪辑项目';
  const data=await api('/api/bootstrap');setProject(data.project);$('capabilities').textContent=JSON.stringify(data.capabilities,null,2);renderAgentStatus(data.agent);if(data.analysis)$('analysis-config').value=JSON.stringify(data.analysis,null,2);
  await Promise.all([refreshProjects(),loadSessions()]);for(const task of await api('/api/tasks')){trackTask(task);if(terminal(task.status))tasks.get(task.task_id).handled=true;}
  setInterval(()=>{pollTasks();pollAgent();},1000);
  setInterval(async()=>{if(!project||playing)return;try{const next=await api('/api/project');if(next.revision!==project.revision||next.id!==project.id)setProject(next,!handDirty);}catch(e){error(e);}},4000);
}
boot().catch(e=>{error(e);$('save-status').textContent='连接失败，请检查本地服务';});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&project&&!analysisEntry){clearTimeout(positionTimer);persistPosition().catch(()=>{});}});
window.addEventListener('pagehide',()=>{if(project&&!analysisEntry){clearTimeout(positionTimer);fetch('/api/project/playhead',{method:'POST',headers:{'Content-Type':'application/json','X-Pokerstudio-Token':token},body:JSON.stringify({time:playhead,project_id:project.id}),keepalive:true}).catch(()=>{});}});
