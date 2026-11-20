// Hands and opponent profiles for the off-table review coach. Confirmation is a user action here only.
(() => {
  'use strict';
  const STATUS = {confirmed:'已确认（计入统计）', pending:'待确认', has_errors:'有错误，不能确认', new_revision:'有新修订待确认'};
  const TOPIC = {mood:'心情 · ', tell:'tell · ', image:'形象 · ', read:'判断 · ', tendency:'倾向 · ', other:''};
  const nodes = {};
  const token = () => document.querySelector('meta[name="local-token"]').content;
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const pct = v => v == null ? '—' : `${Math.round(v * 100)}%`;
  async function request(path, body) {
    const response = await fetch(path, body === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json','X-Pokerlab-Token':token()},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    return data;
  }
  function button(text, action) {
    const b = make('button', text); b.type = 'button';
    b.onclick = async () => { b.disabled = true; nodes.error.textContent = ''; try { await action(); } catch (e) { nodes.error.textContent = e.message || String(e); } finally { b.disabled = false; } };
    return b;
  }
  function table(headers, rows) {
    const t = make('table', undefined, 'coach-table'), head = make('tr'), thead = make('thead'), body = make('tbody');
    headers.forEach(h => head.append(make('th', h))); thead.append(head); rows.forEach(r => body.append(r)); t.append(thead, body);
    return t;
  }
  function row(cells) { const tr = make('tr'); for (const c of cells) { const td = make('td'); if (c instanceof Node) td.append(c); else td.textContent = c ?? '—'; tr.append(td); } return tr; }
  function lines(title, items, cls) {
    if (!items?.length) return make('span');
    const box = make('div', undefined, cls); box.append(make('strong', title)); const ul = make('ul'); items.forEach(i => ul.append(make('li', i))); box.append(ul); return box;
  }

  async function showHand(id) {
    const d = await request('/api/coach/hand?id=' + encodeURIComponent(id));
    const r = d.replay;
    nodes.detail.replaceChildren(make('h3', `手牌 ${id} · 修订 ${d.record.revision} · ${STATUS[d.status.status] || d.status.status}`),
      make('p', `底池 ${r.pot}（最小单位）· ${r.showdown ? '到达摊牌' : '未摊牌'} · 补记行动 ${r.inferred_actions} 个 · 位置 ${Object.entries(r.positions).map(([n, p]) => n + ' ' + p).join('，')}`, 'solver-agent-hint'),
      lines('错误', r.errors, 'coach-errors'), lines('警告', r.warnings, 'coach-warnings'), make('pre', JSON.stringify(d.record.hand, null, 1)));
  }
  async function showPlayer(name) {
    const d = await request('/api/coach/player?name=' + encodeURIComponent(name));
    if (!d.stats) { nodes.detail.replaceChildren(make('p', `${d.player}：${d.message}`, 'solver-agent-hint'), lines('场外观察与备注', (d.notes || []).map(n => `${n.session ? n.session + ' · ' : ''}${n.text}`), 'coach-notes')); return; }
    const rows = Object.values(d.stats).map(s => row([s.label, String(s.n), String(s.k), pct(s.raw), pct(s.mean), `${pct(s.ci90[0])}–${pct(s.ci90[1])}`, pct(s.population), `${s.score}/10`]));
    const alias = make('input'); alias.placeholder = '把这个名字合并到本玩家，例如绰号';
    nodes.detail.replaceChildren(
      make('h3', `${d.player}${d.is_hero ? '（Hero）' : ''} · ${d.hands} 手已确认${d.bomb_pot_hands ? `（其中 BP ${d.bomb_pot_hands} 手，不计入频率统计）` : ''} · 类型：${d.type.type}`),
      make('p', `别名：${d.aliases.join('、')} · 待确认手牌 ${d.pending_hands.length} 手 · 先验 ${d.priors.version}${d.priors.calibrated ? '' : '（未校准占位值）'}`, 'solver-agent-hint'),
      d.sample_note ? make('p', d.sample_note, 'solver-agent-hint') : '',
      lines('标签（至少 3 手牌且后验概率 ≥ 85%）', d.tags.map(t => `${t.label} ${t.score}/10 · ${t.k}/${t.n} · ${t.hands} 手${t.selected_hands ? `（${t.selected_hands} 手来自笔记）` : ''} · 手牌 ${t.evidence.join('，')}`), 'coach-tags'),
      table(['统计', '机会 n', '成功 k', '原始', '后验均值', '90% 区间', '人群先验', '倾向分'], rows),
      make('p', '倾向分 = 高于人群水平的后验概率 × 10；5 表示没有证据。人群先验目前是占位值。', 'solver-agent-hint'),
      lines('摊牌记录', d.showdowns.map(s => `${s.hand_id} · ${s.position || ''} ${s.cards.join(' ')} · 公共牌 ${s.board.join(' ') || '—'} · ${s.line}`), 'coach-showdowns'),
      lines('场外观察与备注', d.notes.map(n => `${n.session ? n.session + ' · ' : ''}${TOPIC[n.topic] || ''}${n.kind === 'inference' ? '【推断】' : '【观察】'}${n.text}（${n.source === 'agent' ? '助手记录' : '你'}；手牌 ${(n.hand_ids || []).join('，') || '—'}）`), 'coach-notes'),
      (() => { const box = make('div', undefined, 'solver-agent-row'); box.append(alias, button('合并别名', async () => { await request('/api/coach/alias', {name: alias.value, target: d.key}); await refresh(); await showPlayer(d.key); })); return box; })());
  }
  async function refreshHands() {
    const data = await request('/api/coach/hands?limit=100');
    const rows = data.hands.slice().reverse().map(h => {
      const actions = make('div', undefined, 'solver-agent-row');
      actions.append(button('查看', () => showHand(h.hand_id)));
      if (h.status === 'pending' || h.status === 'new_revision') actions.append(button('确认计入统计', async () => { await request('/api/coach/confirm', {hand_id: h.hand_id, revision: h.latest_revision}); await refresh(); }));
      if (h.status === 'confirmed' || h.status === 'new_revision') actions.append(button('撤销确认', async () => { await request('/api/coach/unconfirm', {hand_id: h.hand_id}); await refresh(); }));
      return row([h.hand_id, h.played_at, h.stakes, h.players.map(p => p.name + (p.position ? `(${p.position})` : '')).join('、'), STATUS[h.status] || h.status, `${h.errors} 错误 / ${h.warnings} 警告`, actions]);
    });
    nodes.hands.replaceChildren(rows.length ? table(['手牌', '时间', '盲注', '玩家（位置）', '状态', '校验', ''], rows) : make('p', '还没有手牌。', 'solver-agent-hint'));
  }
  async function refreshPlayers() {
    const data = await request('/api/coach/players');
    nodes.meta.textContent = `数据目录：${data.data_dir} · 先验：${data.priors.version}${data.priors.calibrated ? '' : '（未校准占位值）'}${data.load_warnings.length ? ' · 读取警告 ' + data.load_warnings.length + ' 条' : ''}`;
    if (document.activeElement !== nodes.hero) nodes.hero.value = data.hero_names.join(', ');
    const rows = data.players.map(p => row([p.player + (p.is_hero ? '（Hero）' : ''), String(p.hands), pct(p.vpip), pct(p.pfr), p.type, p.tags.join('；') || '—', button('档案', () => showPlayer(p.key))]));
    nodes.players.replaceChildren(rows.length ? table(['玩家', '手数', 'VPIP', 'PFR', '类型', '主要标签', ''], rows) : make('p', '已确认的手牌里还没有玩家。', 'solver-agent-hint'));
  }
  async function refreshSettings() {
    const s = await request('/api/coach/settings');
    nodes.level.replaceChildren(...Object.entries(s.presets).map(([key, label]) => new Option(label, key)));
    nodes.level.value = s.default_game;
  }
  async function refresh() { await Promise.all([refreshHands(), refreshPlayers(), refreshSettings()]); }
  function mount() {
    const host = document.getElementById('coach-panel');
    if (!host) return;
    nodes.error = make('p', '', 'coach-error'); nodes.error.setAttribute('role', 'alert');
    nodes.meta = make('p', '', 'solver-agent-hint');
    nodes.text = make('textarea'); nodes.text.rows = 4; nodes.text.placeholder = '粘贴 PokerStars / GG 格式的手牌（可多手）。现场手牌请直接在上面的助手里描述，由助手整理后在这里确认。'; nodes.text.setAttribute('aria-label', '导入手牌');
    nodes.hero = make('input'); nodes.hero.placeholder = '你在手牌里的名字，逗号分隔'; nodes.hero.setAttribute('aria-label', 'Hero 名字');
    nodes.level = make('select'); nodes.level.setAttribute('aria-label', '默认级别');
    nodes.level.onchange = async () => { nodes.error.textContent = ''; try { await request('/api/coach/default-game', {preset: nodes.level.value}); } catch (e) { nodes.error.textContent = e.message || String(e); } };
    nodes.result = make('p', '', 'solver-agent-hint');
    nodes.hands = make('div', undefined, 'coach-scroll'); nodes.players = make('div', undefined, 'coach-scroll'); nodes.detail = make('div', undefined, 'coach-detail');
    const importRow = make('div', undefined, 'solver-agent-row');
    importRow.append(button('导入手牌', async () => {
      const data = await request('/api/coach/import', {text: nodes.text.value});
      const count = kind => data.results.filter(r => r.result === kind).length;
      nodes.result.textContent = `导入 ${count('stored')} 手，重复 ${count('duplicate')} 手，拒绝 ${count('rejected')} 手` + (count('rejected') ? '：' + data.results.filter(r => r.result === 'rejected').map(r => (r.hand_id || '?') + ' ' + r.problems.join('；')).join(' | ') : '');
      if (count('stored')) nodes.text.value = '';
      await refresh();
    }), nodes.hero, button('保存 Hero 名字', async () => { await request('/api/coach/hero', {names: nodes.hero.value.split(/[,，]/).map(s => s.trim()).filter(Boolean)}); await refresh(); }), button('刷新', refresh));
    const levelRow = make('label', '现场手牌默认级别（助手按它填盲注）'); levelRow.append(nodes.level);
    host.append(make('h2', '手牌与对手'), make('p', '统计只用已确认的手牌。标签至少要 3 手不同的牌；倾向分随样本增加才会离开 5/10。现场笔记是挑过的牌，不计入入池率、加注率、3-bet 和摊牌率。Bomb pot 只记录，不计入频率统计。', 'solver-agent-hint'),
      nodes.meta, levelRow, nodes.text, importRow, nodes.result, make('h3', '手牌'), nodes.hands, make('h3', '玩家'), nodes.players, nodes.detail, nodes.error);
    refresh().catch(e => { nodes.error.textContent = e.message || String(e); });
  }
  window.PokerlabCoach = {refresh};
  mount();
})();
