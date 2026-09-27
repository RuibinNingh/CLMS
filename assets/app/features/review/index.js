/**
 * 复习页：安排（预览 → 确认）、复习列表（打印 / 评分 / 删除）、评分视图（评分、反馈、撤销）。概览页经 store.reviewIntent 带意图进入。
 * 「拍照交给 AI 批改」建一段 review 会话（POST /api/drafts {images, review_session}），经 store.entryIntent 跳到录入页看 AI 执行。
 */
import { html } from '../../core/html.js';
import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get, post } from '../../core/api.js';
import { toast, confirmDialog } from '../../ui/feedback.js';
import { GENRES } from '../../domain/genres.js';
import { readImages } from '../../core/files.js';
import { grading, planner, sessionList } from './view.js';

export const page = {
  id: 'review', title: '复习', icon: 'review',
  mount(root, { store, bus, router }) {
    const s = { minutes: 40, genres: new Set(GENRES.map(g => g.code)), fill: true, plan: null, horizon: '',
      sessions: [], session: null, revealed: new Set(), openMats: new Set(), busy: null, noteFor: null, aiBusy: false };
    let alive = true;
    const render = () => alive && morph(root, s.session ? grading(s) : html`<div class="rv">${planner(s)}
      <section class="rv__sessions"><h2>复习记录</h2>${sessionList(s)}</section></div>`);

    const fail = res => { toast(res.error.message, { tone: 'bad' }); };
    async function loadSessions() { const r = await get('/api/sessions'); if (r.ok) s.sessions = r.data.sessions; render(); }
    async function openSession(id) {
      const r = await get(`/api/session?id=${encodeURIComponent(id)}`);
      if (!r.ok) return fail(r);
      s.session = r.data; s.revealed = new Set(); s.openMats = new Set(Object.keys(r.data.materials).slice(0, 1));
      render(); root.scrollIntoView({ block: 'start' });
      return null;
    }
    async function makePlan() {
      const r = await post('/api/sessions/plan', { minutes: s.minutes, genres: [...s.genres], fill: s.fill });
      if (!r.ok) return fail(r);
      s.plan = r.data; s.horizon = r.data.horizon; render();
      return null;
    }

    const undefine = defineActions('rv', {
      budget: ({ arg }) => { s.minutes = Number(arg); s.plan = null; render(); },
      genre: ({ arg }) => { if (s.genres.has(arg) && s.genres.size > 1) s.genres.delete(arg); else s.genres.add(arg); s.plan = null; render(); },
      fill: ({ el }) => { s.fill = el.checked; s.plan = null; render(); },
      plan: makePlan,
      async create() {
        const r = await post('/api/sessions', { item_ids: s.plan.items.map(x => x.id), minutes: Math.round(s.plan.minutes) });
        if (!r.ok) return fail(r);
        toast(`已安排 ${r.data.items.length} 题，可以打印了`);
        s.plan = null;
        await loadSessions();
        return openSession(r.data.id);
      },
      open: ({ arg }) => openSession(arg),
      back: () => { s.session = null; loadSessions(); },
      async cancel({ arg }) {
        const ok = await confirmDialog({ title: '删除这次复习？', body: '已经录的评分会一起撤销（提交链里留有记录）。', ok: '删除', danger: true });
        if (!ok) return null;
        const r = await post('/api/session/cancel', { id: arg });
        if (!r.ok) return fail(r);
        toast('已删除');
        return loadSessions();
      },
      reveal: ({ arg }) => { s.revealed.add(arg); render(); },
      mat: ({ arg, event }) => { event.preventDefault(); if (s.openMats.has(arg)) s.openMats.delete(arg); else s.openMats.add(arg); render(); },
      async grade({ arg }) {
        const [itemId, value] = arg.split(':');
        s.busy = itemId; render();
        const r = await post('/api/session/grade', { session_id: s.session.id, item_id: itemId, grade: Number(value) });
        s.busy = null;
        if (!r.ok) { render(); return fail(r); }
        s.session = r.data.session; render();
        bus.emit('library:changed');
        return null;
      },
      noteEdit: ({ arg }) => { s.noteFor = s.noteFor === arg ? null : arg; render(); root.querySelector('.rv__noteinput')?.focus(); },
      async note({ el, arg }) {
        const item = s.session.items.find(x => x.id === arg);
        s.noteFor = null;
        if (!item?.grade) return render();
        const r = await post('/api/record/update', { commit_id: item.grade.commit_id, note: el.value });
        if (!r.ok) return fail(r);
        toast('反馈已保存');
        return openSession(s.session.id);
      },
      async aiGrade({ el }) {
        const images = await readImages(el.files);
        el.value = '';
        if (!images.length) return null;
        s.aiBusy = true; render();
        const r = await post('/api/drafts', { images, review_session: s.session.id }, { timeout: 120000 });
        s.aiBusy = false;
        if (!r.ok) { render(); return fail(r); }
        toast('已交给 AI 批改，可以在录入页看它逐题执行');
        store.set({ entryIntent: { open: r.data.drafts[0].id } });
        router.go('entry');
        return null;
      },
      async ungrade({ arg }) {
        const r = await post('/api/session/ungrade', { session_id: s.session.id, item_id: arg });
        if (!r.ok) return fail(r);
        s.session = r.data; render();
        return null;
      },
    });

    const intent = store.get().reviewIntent;
    store.set({ reviewIntent: null });
    loadSessions();
    if (intent?.session) openSession(intent.session);
    else if (intent?.plan) makePlan();
    render();
    return () => { alive = false; undefine(); };
  },
};
