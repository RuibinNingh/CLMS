/**
 * 题库页：「题目」分页（分面筛选 + 按题 / 按篇列表 + 批量操作）与「复习记录」分页（全库复习历史），右侧是题目详情。
 * 编辑、停用、删除、恢复、复习记录增删改查都写 Ledger；「加入复习」经 store.reviewIntent 把题带到复习页当自选题。
 * 筛选、列表方式、分页状态存在模块级 saved 里，切页面回来不丢。
 */
import { html } from '../../core/html.js';
import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get, post } from '../../core/api.js';
import { parseDay } from '../../core/format.js';
import { toast, confirmDialog } from '../../ui/feedback.js';
import { loadTaxonomy } from '../../domain/genres.js';
import { facets, list, toolbar } from './view.js';
import { detail } from './detail.js';
import { historyView } from './history.js';

const PAGE = 50;
const GROUP_PAGE = 20;
const BLANK = { genre: '', status: '', qtype: '', kind: '', added: '', last: '', grade: '', q: '', sort: 'priority' };
const saved = { filter: { ...BLANK }, selected: null, group: 'item', tab: 'items',
  hist: { genre: '', grade: '', since: '', note: false, voided: false } };

function daysAgo(today, n) {
  const d = parseDay(today) || new Date();
  d.setDate(d.getDate() - Number(n));
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export const page = {
  id: 'library', title: '题库', icon: 'library',
  mount(root, { bus, store, router }) {
    const s = { filter: { ...saved.filter }, group: saved.group, tab: saved.tab, items: [], groups: [], counts: {}, facets: {},
      total: 0, totalGroups: 0, libraryTotal: 0, deletedCount: 0, selected: saved.selected, detail: null, editing: false,
      loading: true, taxonomy: null, today: '', showVoided: false, noteFor: null, selecting: false, picked: new Set(),
      facetsOpen: false, hist: { ...saved.hist, records: [], total: 0, loading: true } };
    let alive = true; let searchTimer = 0; let seq = 0; let histSeq = 0;
    const render = () => alive && morph(root, html`<div class="lib ${s.detail ? 'has-detail' : ''}" data-tab="${s.tab}">
      <div class="lib__top"><div class="seg" role="tablist" aria-label="题库分页">
        <button role="tab" data-action="lib.tab" data-arg="items" aria-pressed="${String(s.tab === 'items')}">题目 <small>${s.libraryTotal}</small></button>
        <button role="tab" data-action="lib.tab" data-arg="history" aria-pressed="${String(s.tab === 'history')}">复习记录</button></div></div>
      <div class="lib__body">${s.tab === 'items' ? facets(s) : ''}
        <div class="lib__col">${s.tab === 'items' ? html`${toolbar(s)}${list(s)}` : historyView(s)}</div>${detail(s)}</div></div>`);

    async function load(more = false) {
      const mine = ++seq;
      const size = s.group === 'material' ? GROUP_PAGE : PAGE;
      const offset = more ? (s.group === 'material' ? s.groups.length : s.items.length) : 0;
      const q = new URLSearchParams({ ...s.filter, suspended: '1', group: s.group, offset, limit: size });
      s.loading = true;
      if (more) render();
      const res = await get(`/api/items?${q}`);
      if (mine !== seq || !alive) return;
      s.loading = false;
      if (res.ok) {
        const d = res.data;
        if (s.group === 'material') { s.groups = more ? [...s.groups, ...d.groups] : d.groups; s.items = []; } else { s.items = more ? [...s.items, ...d.items] : d.items; s.groups = []; }
        s.counts = d.counts; s.facets = d.facets; s.total = d.total; s.totalGroups = d.total_groups || 0;
        s.deletedCount = d.deleted || 0; s.libraryTotal = d.library_total || 0;
      }
      render();
    }
    async function loadHistory(more = false) {
      const mine = ++histSeq;
      const h = s.hist;
      const q = new URLSearchParams({ genre: h.genre, grade: h.grade, since: h.since ? daysAgo(s.today, h.since) : '',
        has_note: h.note ? '1' : '', voided: h.voided ? '1' : '0', limit: PAGE, offset: more ? h.records.length : 0 });
      h.loading = true;
      if (more) render();
      const res = await get(`/api/records?${q}`);
      if (mine !== histSeq || !alive) return;
      h.loading = false;
      if (res.ok) { h.records = more ? [...h.records, ...res.data.records] : res.data.records; h.total = res.data.total; }
      render();
    }
    async function openDetail(id) {
      s.selected = id; saved.selected = id; s.editing = false; s.noteFor = null;
      const res = await get(`/api/item?id=${encodeURIComponent(id)}`);
      s.detail = res.ok ? res.data : null;
      if (!res.ok) { s.selected = null; saved.selected = null; }
      render();
    }
    async function act(path, body, message) {
      const res = await post(path, body);
      if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return null; }
      if (message) toast(message);
      return res.data;
    }
    const refresh = () => { openDetail(s.detail.id); load(); if (s.tab === 'history') loadHistory(); bus.emit('library:changed'); };
    const setFilter = patch => { Object.assign(s.filter, patch); saved.filter = { ...s.filter }; load(); };
    const setHist = patch => {
      Object.assign(s.hist, patch);
      saved.hist = { genre: s.hist.genre, grade: s.hist.grade, since: s.hist.since, note: s.hist.note, voided: s.hist.voided };
      loadHistory();
    };
    const loadedIds = () => (s.group === 'material' ? s.groups.flatMap(g => g.items.map(it => it.id)) : s.items.map(it => it.id));
    const toReview = ids => { store.set({ reviewIntent: { pinned: ids } }); router.go('review'); };

    const undefine = defineActions('lib', {
      tab: ({ arg }) => { s.tab = arg; saved.tab = arg; if (arg === 'history') loadHistory(); render(); },
      genre: ({ arg }) => setFilter({ genre: arg, qtype: '' }),
      filter: ({ el, arg }) => setFilter({ [arg]: el.value }),
      facet: ({ arg }) => { const at = arg.indexOf(':'); const dim = arg.slice(0, at); const value = arg.slice(at + 1); setFilter({ [dim]: s.filter[dim] === value ? '' : value }); },
      clear: () => { clearTimeout(searchTimer); setFilter({ ...BLANK, sort: s.filter.sort }); },
      search: ({ el }) => { clearTimeout(searchTimer); s.filter.q = el.value; searchTimer = setTimeout(() => setFilter({}), 250); },
      group: ({ arg }) => { s.group = arg; saved.group = arg; load(); },
      facets: () => { s.facetsOpen = !s.facetsOpen; render(); },
      more: () => load(true),
      selecting: () => { s.selecting = !s.selecting; if (!s.selecting) s.picked.clear(); render(); },
      pick: ({ arg }) => { if (s.picked.has(arg)) s.picked.delete(arg); else s.picked.add(arg); render(); },
      pickGroup: ({ arg }) => {
        const ids = (s.groups.find(g => g.key === arg)?.items || []).map(it => it.id);
        const all = ids.every(id => s.picked.has(id));
        ids.forEach(id => (all ? s.picked.delete(id) : s.picked.add(id)));
        render();
      },
      pickPage: () => { loadedIds().forEach(id => s.picked.add(id)); render(); },
      pickNone: () => { s.picked.clear(); render(); },
      batchReview: () => toReview([...s.picked]),
      async batch({ arg }) {
        const ids = [...s.picked];
        if (arg === 'delete' && !await confirmDialog({ title: `删除选中的 ${ids.length} 道题？`, body: '删除会记录在提交链里，可以在「已删除」里逐题恢复。', ok: '删除', danger: true })) return;
        const data = await act('/api/items/batch', { ids, action: arg });
        if (!data) return;
        const verb = { suspend: '停用', resume: '恢复复习', delete: '删除' }[arg];
        toast(`已${verb} ${data.done} 题${data.failed.length ? `，${data.failed.length} 题没成功：${data.failed[0].msg}` : ''}`, { tone: data.failed.length ? 'bad' : '' });
        s.picked.clear();
        if (s.detail && ids.includes(s.detail.id)) openDetail(s.detail.id);
        load(); bus.emit('library:changed');
      },
      histGenre: ({ arg }) => setHist({ genre: arg }),
      histFilter: ({ el, arg }) => setHist({ [arg]: el.value }),
      histCheck: ({ el, arg }) => setHist({ [arg]: el.checked }),
      histMore: () => loadHistory(true),
      select: ({ arg }) => openDetail(arg),
      close: () => { s.detail = null; s.selected = null; saved.selected = null; render(); },
      toReview: () => toReview([s.detail.id]),
      edit: () => { s.editing = !s.editing; render(); },
      async save({ el }) {
        const form = new FormData(el);
        const changes = Object.fromEntries([...form.entries()].map(([k, v]) => [k, k === 'blank_lines' ? Number(v) : v]));
        const data = await act('/api/item/update', { id: s.detail.id, changes }, '已保存');
        if (data) { s.detail = data; s.editing = false; load(); }
      },
      async suspend() {
        const data = await act('/api/item/suspend', { id: s.detail.id, suspended: !s.detail.suspended }, s.detail.suspended ? '已恢复复习' : '已停用');
        if (data) { s.detail = data; load(); }
      },
      async restore() {
        const data = await act('/api/item/restore', { id: s.detail.id }, '已恢复到题库');
        if (data) { s.detail = data; load(); bus.emit('library:changed'); }
      },
      async regrade({ el, arg }) { if (await act('/api/record/update', { commit_id: arg, grade: Number(el.value) }, '评分已改')) refresh(); },
      async void({ arg }) { if (await act('/api/record/delete', { commit_id: arg }, '已撤销这条记录')) refresh(); },
      async unvoid({ arg }) { if (await act('/api/record/restore', { commit_id: arg }, '已恢复这条记录')) refresh(); },
      noteEdit: ({ arg }) => { s.noteFor = s.noteFor === arg ? null : arg; render(); root.querySelector('.rec__noteinput')?.focus(); },
      async note({ el, arg }) { s.noteFor = null; if (await act('/api/record/update', { commit_id: arg, note: el.value }, '反馈已保存')) refresh(); },
      showVoided: () => { s.showVoided = !s.showVoided; render(); },
      async addRecord({ el }) {
        const f = new FormData(el);
        const body = { item_id: s.detail.id, grade: Number(f.get('grade')), date: f.get('date'), note: f.get('note') };
        if (await act('/api/record/add', body, '已补记')) refresh();
      },
      async delete() {
        const ok = await confirmDialog({ title: '删除这道题？', body: '删除会记录在提交链里；复习记录一并不再统计。再次录入同一道题时会当作新题。', ok: '删除', danger: true });
        if (ok && await act('/api/item/delete', { id: s.detail.id }, '已删除')) { s.detail = null; s.selected = null; saved.selected = null; load(); }
      },
    });
    loadTaxonomy().then(t => { s.taxonomy = t; render(); });
    get('/api/summary').then(r => { if (r.ok) { s.today = r.data.today; render(); if (s.tab === 'history' && s.hist.since) loadHistory(); } });
    load();
    if (s.tab === 'history') loadHistory();
    if (s.selected) openDetail(s.selected);
    render();
    return () => { alive = false; undefine(); };
  },
};
