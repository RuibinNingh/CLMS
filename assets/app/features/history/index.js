import { html, each } from '../../core/html.js';
import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get } from '../../core/api.js';
import { objectLinks, showTime, pretty } from '../../domain/object-links.js';

function groups(items) {
  const days = new Map();
  items.forEach(item => {
    const day = (item.created_at || item.started_at || '').slice(0, 10);
    if (!days.has(day)) days.set(day, []);
    days.get(day).push(item);
  });
  return [...days];
}

export const page = {
  id: 'history', title: '历史记录', icon: 'undo',
  mount(root) {
    const s = { tab: 'learning', items: [], total: 0, selected: null, error: '', loading: true,
      filter: { q: '', source: '', type: '', from: '', to: '' }, sources: [], types: [], more: false };
    let alive = true, seq = 0, detailSeq = 0, timer = 0;
    const draw = () => alive && morph(root, html`<div class="workspace">
      <div class="workspace__toolbar"><div class="seg" role="tablist" aria-label="历史类别">
        <button role="tab" aria-selected="${String(s.tab === 'learning')}" data-action="hist.tab" data-arg="learning">学习与变更</button>
        <button role="tab" aria-selected="${String(s.tab === 'runtime')}" data-action="hist.tab" data-arg="runtime">系统运行</button></div><span class="muted">${s.total} 条</span></div>
      <div class="workspace__filters"><input class="input" type="search" aria-label="搜索历史" placeholder="搜索记录" value="${s.filter.q}" data-input="hist.search">
        <select class="select" aria-label="来源" data-change="hist.filter" data-arg="source"><option value="">全部来源</option>${each(s.sources, x => x, x => html`<option value="${x}" ${x === s.filter.source ? html`selected` : ''}>${x}</option>`)}</select>
        <input class="input" aria-label="操作类型" placeholder="按类型过滤" value="${s.filter.type}" data-change="hist.filter" data-arg="type">
        <label class="field"><span>开始日期</span><input class="input" type="date" value="${s.filter.from}" data-change="hist.filter" data-arg="from"></label>
        <label class="field"><span>结束日期</span><input class="input" type="date" value="${s.filter.to}" data-change="hist.filter" data-arg="to"></label></div>
      ${s.error ? html`<p role="alert">${s.error}</p>` : ''}
      <div class="workspace__body"><div class="workspace__list">${each(groups(s.items), d => d[0], ([day, rows]) => html`
        <section class="workspace__day"><h2>${day || '日期未知'}</h2>${each(rows, r => r.id || r.call_id || r.commit_id, r => html`
          <button class="workspace__row card" data-action="hist.open" data-arg="${r.id || r.call_id || r.commit_id}" aria-pressed="${String(s.selected?.id === (r.id || r.call_id || r.commit_id))}">
            <strong>${r.message || r.title || r.label || r.tool}</strong><span>${r.source} · ${r.commit_type || r.tool} ${r.status || ''}</span><small>${showTime(r.created_at || r.started_at)}</small></button>`)}</section>`)}
        ${!s.items.length ? html`<p class="empty">${s.loading ? '正在加载…' : '暂无匹配记录'}</p>` : ''}
        ${s.more ? html`<button class="btn" data-action="hist.more">加载更多</button>` : ''}</div>
        ${s.selected ? html`<article class="workspace__detail card"><h2>${s.selected.message || s.selected.title || s.selected.tool}</h2>
          ${objectLinks(s.selected)}<pre class="workspace__json">${pretty(s.selected)}</pre></article>` : html`<p class="empty">选择记录查看详情和对应对象。</p>`}</div></div>`);
    async function load(more = false) {
      const mine = ++seq;
      const path = s.tab === 'learning' ? '/api/history' : '/api/runtime/records';
      const q = new URLSearchParams({ ...s.filter, offset: more ? s.items.length : 0, limit: 50 });
      s.loading = true;
      const r = await get(`${path}?${q}`);
      if (!alive || mine !== seq) return;
      s.loading = false;
      if (r.ok) { s.items = more ? [...s.items, ...r.data.items] : r.data.items; s.total = r.data.total;
        s.more = r.data.has_more; s.sources = r.data.sources || ['assistant', 'mcp', 'review', 'ocr', 'entry']; s.error = ''; }
      else s.error = r.error.message;
      draw();
    }
    const off = defineActions('hist', {
      tab: ({ arg }) => { ++detailSeq; s.tab = arg; s.selected = null; s.filter.source = ''; s.filter.type = ''; load(); draw(); },
      search: ({ value }) => { s.filter.q = value; clearTimeout(timer); timer = setTimeout(() => load(), 250); },
      filter: ({ arg, value }) => { s.filter[arg] = value; load(); }, more: () => load(true),
      async open({ arg }) {
        const mine = ++detailSeq;
        const path = s.tab === 'learning' ? '/api/history/detail' : '/api/runtime/records/detail';
        const r = await get(`${path}?id=${encodeURIComponent(arg)}`);
        if (!alive || mine !== detailSeq) return;
        if (r.ok) s.selected = { ...r.data.item, id: arg }; else s.error = r.error.message;
        draw();
      },
    });
    draw(); load();
    return () => { alive = false; clearTimeout(timer); off(); };
  },
};
