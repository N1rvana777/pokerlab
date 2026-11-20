// Standalone 8765 Solver assistant. No request goes to the editing application.
(() => {
  'use strict';
  let hooks, host, snapshot, dirty = false, conflicted = false, applying = false, mounted = false, timer, syncing, activeTask = null, cursor = 0, loginId = null;
  const nodes = {}, sessions = [];
  const token = () => document.querySelector('meta[name="local-token"]').content;
  const readVisible = () => hooks.readConfig(snapshot?.config?.mode);
  const make = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  async function request(path, body) {
    const response = await fetch(path, body === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json','X-Pokerlab-Token':token()},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) { const error = new Error(data.error || response.statusText); error.status = response.status; throw error; }
    return data;
  }
  const error = value => { nodes.error.textContent = value?.message || String(value || ''); };
  const button = (text, action) => { const b = make('button', text); b.type = 'button'; b.onclick = async () => { b.disabled = true; try { await action(); } catch (e) { error(e); } finally { b.disabled = b === nodes.cancel ? !activeTask : [nodes.send,nodes.configure,nodes.login].includes(b) && !!activeTask; } }; return b; };
  function field(label, node) { const box = make('label', label); box.append(node); return box; }
  function select(options) { const node = make('select'); for (const [value,label] of options) node.append(new Option(label,value)); return node; }
  function pending(on) { nodes.send.disabled = on; nodes.cancel.disabled = !on; nodes.provider.disabled = on; nodes.session.disabled = on; nodes.configure.disabled = on; nodes.login.disabled = on; }
  function acceptSnapshot(value) {
    // Both HTTP replies and tool events can arrive out of order.
    if (snapshot && value.revision < snapshot.revision) return false;
    snapshot = value;
    nodes.revision.textContent = `Solver配置版本 ${snapshot.revision} · ${snapshot.amount_unit === 'bb' ? '整数bb输入 · EV bb' : '原筹码单位，未自动换算bb'}`;
    return true;
  }
  async function applyRemote(value) {
    const advanced = snapshot && value.revision > snapshot.revision;
    if (!acceptSnapshot(value)) return false;
    if (dirty) {
      if (advanced) { conflicted = true; clearTimeout(timer); }
      nodes.sync.textContent = '表单有新编辑，已保留；请同步当前局面后继续。'; return;
    }
    conflicted = false;
    applying = true;
    try { await hooks.applyConfig?.(snapshot.config); } finally { applying = false; }
    nodes.sync.textContent = snapshot.warning || '当前局面已同步。';
  }
  async function syncConfig(explicit = false) {
    // Initial restoration owns the first revision. An edit while that GET is
    // pending stays local; it must not POST with an undefined/guessed revision.
    if (!mounted || !snapshot || applying) return;
    if (syncing) { await syncing; if (!dirty) return snapshot; }
    if (!dirty && !explicit) return snapshot;
    if (conflicted && !explicit) { const e = new Error('后台局面已更新。已保留表单，请点击“同步当前局面”确认当前输入。'); e.status = 409; throw e; }
    const config = readVisible();
    const submitted = JSON.stringify(config);
    syncing = (async () => {
      if (explicit) acceptSnapshot(await request('/api/agent/config'));
      try {
        const value = await request('/api/agent/config', {config,expected_revision:snapshot.revision});
        const accepted = acceptSnapshot(value);
        dirty = JSON.stringify(hooks.readConfig(config.mode)) !== submitted;
        if (!accepted) { await applyRemote(await request('/api/agent/config')); return snapshot; }
        conflicted = false;
        nodes.sync.textContent = dirty ? '正在保留后续编辑…' : '当前局面已同步。';
        return value;
      } catch (e) {
        if (e.status === 409) { acceptSnapshot(await request('/api/agent/config')); conflicted = true; nodes.sync.textContent = '后台局面已更新。已保留表单，请点击“同步当前局面”确认当前输入。'; }
        throw e;
      }
    })();
    try { return await syncing; } finally { syncing = null; }
  }
  function configChanged(change = {}) {
    if (applying || change.initialDefault) return;
    dirty = true; clearTimeout(timer);
    // Imports and programmatic range/board controls are real edits too. Track
    // the configuration mutation, not whether a DOM event happened to be trusted.
    if (!mounted || !snapshot) {
      if (nodes.sync) nodes.sync.textContent = '表单有新编辑，已保留；正在读取后台局面。';
      return;
    }
    nodes.sync.textContent = '局面有编辑，正在同步…';
    timer = setTimeout(() => syncConfig().catch(e => { error(e); nodes.sync.textContent = e.status === 409 ? nodes.sync.textContent : '局面暂未同步；修正输入后重试。'; }), 120);
  }
  async function refreshStatus() {
    const status = await request('/api/agent/status');
    const subscription = status.subscription, api = status.api, claude = status.claude || {};
    const provider = nodes.provider.value;
    nodes.mode.value = subscription.mode;
    nodes.status.textContent = provider === 'api'
      ? `OpenAI API 独立计费 · ${api.configured ? '已配置' : '尚未配置'} · ${api.allow_paid ? '本人已授权付费调用' : '未授权付费调用'}`
      : provider === 'claude'
      ? `${claude.billing || 'Claude 订阅'} · ${claude.ready ? '可以使用' : '暂不可用'} · ${claude.note || ''}`
      : `本人ChatGPT/Codex订阅额度 · ${subscription.logged_in ? '已登录' : '尚未登录'} · ${subscription.mode}`;
    const current = provider === 'api' ? api : provider === 'claude' ? claude : subscription;
    if (current.error) nodes.status.textContent += ' · ' + current.error;
    const verified = current.verified_models || [];
    nodes.modelNote.textContent = verified.length ? `本次运行已成功请求：${verified.join('、')}` : '候选模型和历史成功不保证当前权限；真实成功请求后验证。';
    return status;
  }
  async function refreshSessions() {
    sessions.splice(0,sessions.length,...await request('/api/agent/sessions'));
    const selected = nodes.session.value;
    nodes.session.replaceChildren(new Option('新会话',''));
    for (const session of sessions.filter(s => s.provider === nodes.provider.value)) {
      const first = session.messages?.find(m => m.role === 'user')?.text || 'Solver会话';
      nodes.session.append(new Option(first.slice(0,45),session.id));
    }
    if ([...nodes.session.options].some(o => o.value === selected)) nodes.session.value = selected;
  }
  function history() {
    nodes.messages.replaceChildren();
    const session = sessions.find(s => s.id === nodes.session.value);
    for (const message of (session?.messages || []).slice(-20)) {
      const box = make('article',undefined,`solver-agent-message ${message.role}`);
      box.append(make('strong',message.role === 'user' ? '你' : 'Solver助手'),make('pre',message.text || message.error || ''));
      nodes.messages.append(box);
    }
  }
  function providerChanged() {
    nodes.subscription.hidden = nodes.provider.value !== 'subscription';
    nodes.api.hidden = nodes.provider.value !== 'api';
    nodes.claude.hidden = nodes.provider.value !== 'claude';
    nodes.session.value = ''; refreshStatus().catch(error); refreshSessions().then(history).catch(error);
  }
  async function send() {
    error(''); clearTimeout(timer);
    if (!mounted || !snapshot) throw new Error('正在读取初始局面，请稍后再发送。');
    if (!dirty) await applyRemote(await request('/api/agent/config'));
    else await syncConfig();
    if (dirty) throw new Error('当前局面尚未同步，请先修正或同步输入。');
    const message = nodes.prompt.value.trim();
    if (!message) throw new Error('请输入Solver请求。');
    const task = await request('/api/agent/start',{message,provider:nodes.provider.value,model:nodes.model.value.trim() || null,session_id:nodes.session.value || null,expected_revision:snapshot.revision});
    nodes.prompt.value = ''; activeTask = task.id; cursor = 0; pending(true);
    const mine = make('article',undefined,'solver-agent-message user'); mine.append(make('strong','你'),make('pre',message)); nodes.messages.append(mine);
    const answer = make('article',undefined,'solver-agent-message assistant'), content = make('pre',''); answer.append(make('strong','Solver助手'),content); nodes.messages.append(answer);
    try {
      while (activeTask) {
        const state = await request(`/api/agent/task?id=${encodeURIComponent(activeTask)}&after=${cursor}`); cursor = state.cursor;
        content.textContent = state.text || (state.status === 'queued' ? '请求已排队…' : '正在处理…');
        for (const event of state.events || []) {
          if (event.type === 'tool_call') nodes.activity.textContent = '调用：' + event.name;
          if (event.type === 'tool_isolation') nodes.activity.textContent = `凭据来源：${event.api_key_source === 'none' ? 'claude.ai 订阅登录' : event.api_key_source} · 模型：${event.model || '默认'} · 可用工具 ${event.tools.length} 个`;
          if (event.type === 'rate_limit') nodes.activity.textContent = `额度状态：${event.status}${event.utilization != null ? ' · 已用 ' + Math.round(event.utilization * 100) + '%' : ''}`;
          if (event.type === 'tool_result') {
            nodes.activity.textContent = `${event.success ? '成功' : '失败'}：${event.name}`;
            if (event.success && ['update_solver_config','lock_node'].includes(event.name)) await applyRemote(event.result);
            if (event.success && ['import_hand_history','record_live_hand','add_player_note'].includes(event.name)) window.PokerlabCoach?.refresh().catch(() => {});
            if (event.success && event.name === 'get_result' && event.result.result?.precision) await hooks.showResult?.(await request(`/api/jobs/${event.result.job.id}/result`), {config:snapshot.config});
          }
        }
        if (!['queued','running'].includes(state.status)) {
          content.textContent = state.text || state.error || state.status;
          nodes.activity.textContent = `请求状态：${state.status}`;
          if (state.error) error(state.error);
          const sid = state.session_id; await refreshSessions(); nodes.session.value = sid;
          await refreshStatus(); break;
        }
        await new Promise(resolve => setTimeout(resolve,700));
      }
    } finally { activeTask = null; pending(false); }
  }
  async function mount(options = {}) {
    if (mounted) return;
    hooks = options; host = document.getElementById(options.container || 'solver-agent');
    if (!host) return;
    host.classList.add('solver-agent');
    host.append(make('h2','Pokerlab Solver 助手'),make('p','直接操作本Solver的局面、真实求解任务与策略结果。会话和工具独立于视频剪辑。','solver-agent-hint'));
    nodes.error = make('p','','solver-agent-error'); nodes.error.setAttribute('role','alert');
    nodes.status = make('p','正在读取登录状态…','solver-agent-hint');
    const settings = make('details'), summary = make('summary','账号与模型'); settings.append(summary);
    nodes.provider = select([['claude','Claude订阅（本机Claude Code登录）'],['subscription','ChatGPT/Codex订阅'],['api','OpenAI API独立计费']]); nodes.provider.onchange = providerChanged;
    nodes.claude = make('div',undefined,'solver-agent-row');
    nodes.claude.append(make('p','使用你自己在本机 Claude Code 里的订阅登录：在终端运行 claude，再用 /login 登录。本应用不读取、不保存凭据；额度用完或进入额外付费时停止，不会改为按量计费。','solver-agent-hint'));
    nodes.mode = select([['siwc','Sign in with ChatGPT · 应用独立授权'],['existing_cli','本机既有Codex登录'],['managed','应用隔离Codex登录']]);
    nodes.subscription = make('div',undefined,'solver-agent-row');
    nodes.configure = button('应用登录方式',async () => { await request('/api/agent/configure-subscription',{mode:nodes.mode.value}); await refreshStatus(); });
    nodes.login = button('登录',async () => { const result = await request('/api/agent/login',{mode:nodes.mode.value}); loginId = result.loginId || null; if (result.authUrl || result.auth_url) { nodes.auth.href = result.authUrl || result.auth_url; nodes.auth.hidden = false; } await refreshStatus(); });
    nodes.auth = make('a','在官方页面继续登录'); nodes.auth.target = '_blank'; nodes.auth.rel = 'noopener noreferrer'; nodes.auth.hidden = true;
    nodes.subscription.append(field('订阅登录方式',nodes.mode),nodes.configure,nodes.login,nodes.auth,button('取消登录',async () => { await request('/api/agent/cancel-login',{login_id:loginId}); nodes.auth.hidden = true; await refreshStatus(); }),button('退出应用账号',async () => { await request('/api/agent/logout',{}); await refreshStatus(); }));
    nodes.api = make('div',undefined,'solver-agent-row'); nodes.api.hidden = true; nodes.subscription.hidden = true;
    const key = make('input'); key.type = 'password'; key.autocomplete = 'off'; key.placeholder = '仅提交至本机后端内存'; key.setAttribute('aria-label','OpenAI API key');
    const paid = make('input'); paid.type = 'checkbox';
    nodes.api.append(field('API key',key),field('我授权OpenAI API独立计费调用',paid),button('配置API',async () => { const secret = key.value; key.value = ''; await request('/api/agent/configure-api',{api_key:secret,model:nodes.model.value.trim(),allow_paid:paid.checked}); await refreshStatus(); }));
    nodes.model = make('input'); nodes.model.placeholder = '默认模型，或明确的模型ID'; nodes.model.setAttribute('aria-label','Agent模型'); nodes.model.setAttribute('list','solver-agent-models');
    const models = make('datalist'); models.id = 'solver-agent-models';
    const loadModels = button('读取模型候选',async () => { const data = await request('/api/agent/models?provider='+nodes.provider.value); models.replaceChildren(); for (const model of data.models || []) models.append(new Option(model.displayName || model.model || model.id,model.model || model.id)); nodes.modelNote.textContent = data.note; });
    nodes.modelNote = make('p','','solver-agent-hint');
    settings.append(field('Provider',nodes.provider),nodes.claude,nodes.subscription,nodes.api,field('模型',nodes.model),models,loadModels,nodes.modelNote,button('刷新账号状态',refreshStatus));
    nodes.session = select([['','新会话']]); nodes.session.setAttribute('aria-label','会话'); nodes.session.onchange = history;
    nodes.messages = make('div',undefined,'solver-agent-messages'); nodes.messages.setAttribute('aria-live','polite');
    nodes.prompt = make('textarea'); nodes.prompt.rows = 3; nodes.prompt.maxLength = 30000; nodes.prompt.placeholder = '例如：读取当前局面，把底池改为20 bb，求真实均衡并解释EV和测得精度。'; nodes.prompt.setAttribute('aria-label','Solver助手请求');
    nodes.send = button('发送',send); nodes.cancel = button('取消助手请求',async () => { if (activeTask) await request('/api/agent/cancel',{id:activeTask}); }); nodes.cancel.disabled = true;
    nodes.revision = make('p','','solver-agent-hint'); nodes.sync = make('p','','solver-agent-hint'); nodes.activity = make('p','','solver-agent-hint');
    const actions = make('div',undefined,'solver-agent-row'); actions.append(nodes.send,nodes.cancel,button('同步当前局面',() => syncConfig(true)),button('载入后台局面',async () => { dirty = false; await applyRemote(await request('/api/agent/config')); }));
    host.append(nodes.status,settings,field('会话',nodes.session),nodes.messages,nodes.prompt,actions,nodes.activity,nodes.revision,nodes.sync,nodes.error);
    // Await the actual initializer, including its failure result. A guessed
    // deadline could restore saved settings before a late default overwrites them.
    let initialization;
    try { initialization = await hooks.ready; }
    catch (e) { initialization = {ok:false,error:'局面初始化失败：'+(e?.message||String(e))}; }
    // Also covers an import made before this script mounted or while examples
    // loaded; the app's initializer reports its actual configuration version.
    dirty = dirty || initialization?.userModified === true;
    mounted = true;
    try { await applyRemote(await request('/api/agent/config')); if(initialization?.ok===false)error(initialization.error+'；可继续使用后台局面，或刷新重试示例。'); await refreshStatus(); await refreshSessions(); } catch (e) { error(e); }
  }
  window.PokerlabAgent = {mount,configChanged,syncConfig};
})();
