import { html, each } from '../../core/html.js';
import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get, post } from '../../core/api.js';
import { toast } from '../../ui/feedback.js';
import { objectLinks, showTime, pretty } from '../../domain/object-links.js';

const STATUS = { pending_confirmation: '待审核', applied: '已执行', rejected: '已拒绝', expired: '已过期',
  conflict: '内容冲突', failed: '执行失败', applying: '正在执行', interrupted: '已中断', unchanged: '未改变', cancelled: '已停止' };
const FIELDS = { stem: '题干', answer: '参考答案', analysis: '解析', note: '笔记', qtype: '题型', source: '来源',
  title: '标题', text: '材料正文', author: '作者', blank_lines: '留白行数', minutes: '分钟数', item_ids: '题目编号', score: '分值' };

function impact(d) {
  const p = d.preview || {};
  if (d.tool === 'session.create') return html`<section class="workspace__form"><h3>计划影响</h3>
    <p>${p.title || '复习'} · ${p.minutes} 分钟 · ${p.count} 道题</p>
    <ul>${each(p.items || [], x => x.id, x => html`<li class="audit__question"><a href="#/library?item=${encodeURIComponent(x.id)}">${x.label || x.id}</a><p>${x.stem}</p></li>`)}</ul></section>`;
  const before = p.before || {}, after = p.after || d.payload?.changes || {};
  return html`<section class="workspace__form"><h3>原对象：${p.target?.label || p.target?.id || d.payload?.item_id || d.payload?.material_id || ''}</h3>
    <table class="audit__compare"><thead><tr><th>字段</th><th>修改前</th><th>修改后</th></tr></thead>
      <tbody>${each(Object.keys(after), k => k, k => html`<tr><th>${FIELDS[k] || k}</th><td><pre>${typeof before[k] === 'object' ? pretty(before[k]) : before[k] ?? '—'}</pre></td><td><pre>${typeof after[k] === 'object' ? pretty(after[k]) : after[k] ?? '—'}</pre></td></tr>`)}</tbody></table></section>`;
}

function detail(d, busy) {
  if (!d) return html`<p class="empty">选择一条操作，查看修改前后和计划影响。</p>`;
  const current = d.payload?.changes || d.payload || {};
  return html`<article class="workspace__detail card" data-key="${d.id}">
    <header><h2>${d.label || d.tool}</h2><span class="chip">${STATUS[d.status] || d.status}</span></header>
    <p class="muted">${d.source === 'mcp' ? 'MCP' : d.source === 'entry' ? '录入助手' : '内置助手'} · ${showTime(d.created_at)} · revision ${d.revision}</p>
    <p class="muted">到期：${showTime(d.expires_at)}</p>
    ${d.error_code ? html`<p role="alert">${d.error_code}。请核对当前对象后重新提案。</p>` : ''}
    ${impact(d)}
    ${d.status === 'pending_confirmation' ? html`
      <form data-submit="audit.revise" class="workspace__form">
        <p class="muted">可在原请求范围内修订；批准前会再次核对对象快照。</p>
        ${each(d.editable_fields || [], k => k, k => html`<label class="field"><span>${FIELDS[k] || k}</span>
          <textarea class="textarea" name="${k}" rows="${k === 'minutes' || k === 'blank_lines' ? 1 : 3}">${typeof current[k] === 'object' ? pretty(current[k]) : current[k] ?? ''}</textarea></label>`)}
        ${(d.editable_fields || []).length ? html`<button class="btn" ${busy ? html`disabled` : ''}>保存修订</button>` : ''}
      </form>
      <div class="workspace__links"><button class="btn btn--primary" data-action="audit.decide" data-arg="approve" ${busy ? html`disabled` : ''}>批准</button>
        <button class="btn btn--danger" data-action="audit.decide" data-arg="reject" ${busy ? html`disabled` : ''}>拒绝</button></div>` : ''}
    ${d.status === 'applied' ? html`<p role="status">已完成${d.commits?.length ? `，追加 ${d.commits.length} 条学习变更。` : '。'}${d.tool === 'session.create' ? `复习编号：${d.result?.id || ''}` : ''}</p>` : ''}
    ${objectLinks(d)}
    <details><summary>请求与决定历史</summary><pre class="workspace__json">${pretty({ original_payload: d.original_payload, revisions: d.revisions, decisions: d.decisions })}</pre></details>
  </article>`;
}

export const page = {
  id: 'audit', title: '审核中心', icon: 'check',
  mount(root, { bus }) {
    const s = { view: 'pending', items: [], total: 0, more: false, selected: null, busy: false, loading: true, error: '' };
    let alive = true, seq = 0, detailSeq = 0;
    const draw = () => alive && morph(root, html`<div class="workspace">
      <div class="workspace__toolbar"><div class="seg" role="tablist" aria-label="审核记录">
        <button role="tab" aria-selected="${String(s.view === 'pending')}" data-action="audit.tab" data-arg="pending">待审核</button>
        <button role="tab" aria-selected="${String(s.view === 'records')}" data-action="audit.tab" data-arg="records">已处理 / 历史</button></div>
        <button class="btn btn--sm" data-action="audit.refresh">刷新</button><span class="muted">${s.total} 条</span></div>
      ${s.error ? html`<p role="alert">${s.error}</p>` : ''}
      <div class="workspace__body"><div class="workspace__list">${each(s.items, d => d.id, d => html`
        <button class="workspace__row card" data-action="audit.open" data-arg="${d.id}" aria-pressed="${String(s.selected?.id === d.id)}">
          <strong>${d.label || d.tool}</strong><span>${d.source === 'mcp' ? 'MCP' : d.source === 'entry' ? '录入助手' : '内置助手'} · ${STATUS[d.status] || d.status}</span><small>${showTime(d.created_at)}</small></button>`)}
        ${!s.items.length ? html`<p class="empty">${s.loading ? '正在加载…' : '暂无记录'}</p>` : ''}
        ${s.more ? html`<button class="btn" data-action="audit.more">加载更多</button>` : ''}</div>${detail(s.selected, s.busy)}</div></div>`);
    async function load(more = false) {
      const mine = ++seq, wanted = more ? 100 : Math.max(100, s.items.length);
      const rows = []; let offset = more ? s.items.length : 0, total = 0;
      do {
        const r = await get(`/api/ai-review/items?view=${s.view}&limit=100&offset=${offset}`);
        if (!alive || mine !== seq) return;
        if (!r.ok) { s.loading = false; s.error = r.error.message; draw(); return; }
        rows.push(...r.data.items); total = r.data.total; offset += r.data.items.length;
        if (!r.data.items.length) break;
      } while (rows.length < wanted && offset < total);
      s.loading = false; s.items = more ? [...s.items, ...rows] : rows;
      s.total = total; s.more = s.items.length < total; s.error = '';
      draw();
      const c = await get('/api/ai-review/counts');
      if (alive && c.ok) bus.emit('badge', { id: 'audit', text: c.data.counts.pending ? String(c.data.counts.pending) : '' });
    }
    async function open(id) {
      const mine = ++detailSeq;
      const r = await get(`/api/ai-review/detail?id=${encodeURIComponent(id)}`);
      if (!alive || mine !== detailSeq) return;
      if (r.ok) { s.selected = r.data.item; s.error = ''; } else s.error = r.error.message;
      draw();
    }
    async function write(path, body) {
      if (s.busy) return;
      s.busy = true; draw();
      const r = await post(path, body);
      if (!alive) return;
      s.busy = false;
      if (r.ok) { s.selected = r.data.item; toast(STATUS[s.selected.status] || '已保存'); bus.emit('library:changed'); bus.emit('audit:changed'); }
      else { s.error = r.error.message; await open(body.id); }
      draw(); load();
    }
    const off = defineActions('audit', {
      tab: ({ arg }) => { ++detailSeq; s.view = arg; s.items = []; s.selected = null; load(); draw(); },
      open: ({ arg }) => open(arg), refresh: () => load(), more: () => load(true),
      decide: ({ arg }) => s.selected && write('/api/ai-review/decide', { id: s.selected.id, expected_revision: s.selected.revision, decision: arg }),
      revise({ el }) {
        const values = new FormData(el), current = s.selected.payload?.changes || s.selected.payload;
        const patch = {};
        try {
          for (const [k, v] of values) {
            const parsed = typeof current[k] === 'number' ? Number(v) : typeof current[k] === 'object' ? JSON.parse(v) : v;
            if (JSON.stringify(parsed) !== JSON.stringify(current[k])) patch[k] = parsed;
          }
        } catch (_) { toast('列表字段需填写有效 JSON', { tone: 'bad' }); return; }
        if (!Object.keys(patch).length) return;
        write('/api/ai-review/update', { id: s.selected.id, expected_revision: s.selected.revision, patch });
      },
    });
    const offBus = bus.on('audit:changed', () => { load(); if (s.selected) open(s.selected.id); });
    const id = new URLSearchParams(location.hash.split('?')[1] || '').get('id');
    draw(); load(); if (id) open(id);
    const timer = setInterval(() => { load(); if (s.selected && !s.busy) open(s.selected.id); }, 5000);
    return () => { alive = false; clearInterval(timer); off(); offBus(); };
  },
};
