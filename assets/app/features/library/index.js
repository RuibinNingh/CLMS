/** 题库页：筛选（板块 / 状态 / 题型 / 搜索 / 排序）+ 列表 + 详情；编辑、停用、删除、恢复、复习记录增删改查都写 Ledger。 */
import { html } from '../../core/html.js';
import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get, post } from '../../core/api.js';
import { toast, confirmDialog } from '../../ui/feedback.js';
import { loadTaxonomy } from '../../domain/genres.js';
import { detail, filters, list } from './view.js';

const saved = { filter: { genre: '', status: '', qtype: '', q: '', sort: 'priority' }, selected: null };

export const page = {
  id: 'library', title: '题库', icon: 'library',
  mount(root, { bus }) {
    const s = { filter: { ...saved.filter }, items: [], counts: {}, total: 0, selected: saved.selected, detail: null,
      editing: false, loading: true, taxonomy: null, today: '', showVoided: false, noteFor: null, deletedCount: 0 };
    let alive = true; let searchTimer = 0; let seq = 0;
    const render = () => alive && morph(root, html`<div class="lib ${s.detail ? 'has-detail' : ''}">${filters(s)}
      <div class="lib__body"><div class="lib__col">${list(s)}</div>${detail(s)}</div></div>`);

    async function load() {
      const mine = ++seq;
      const f = s.filter;
      const q = new URLSearchParams({ genre: f.genre, status: f.status, qtype: f.qtype, q: f.q, sort: f.sort, suspended: '1' });
      const res = await get(`/api/items?${q}`);
      if (mine !== seq || !alive) return;
      s.loading = false;
      if (res.ok) {
        s.items = res.data.items; s.counts = res.data.counts; s.deletedCount = res.data.deleted || 0;
        s.total = Object.values(s.counts).reduce((a, b) => a + b, 0);
      }
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
    const refresh = () => { openDetail(s.detail.id); load(); bus.emit('library:changed'); };
    const setFilter = patch => { Object.assign(s.filter, patch); saved.filter = { ...s.filter }; load(); };

    const undefine = defineActions('lib', {
      genre: ({ arg }) => setFilter({ genre: arg, qtype: '' }),
      filter: ({ el, arg }) => setFilter({ [arg]: el.value }),
      search: ({ el }) => { clearTimeout(searchTimer); s.filter.q = el.value; searchTimer = setTimeout(() => setFilter({}), 250); },
      select: ({ arg }) => openDetail(arg),
      close: () => { s.detail = null; s.selected = null; saved.selected = null; render(); },
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
    get('/api/summary').then(r => { if (r.ok) { s.today = r.data.today; render(); } });
    load();
    if (s.selected) openDetail(s.selected);
    render();
    return () => { alive = false; undefine(); };
  },
};
