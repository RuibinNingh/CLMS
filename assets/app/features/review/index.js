/**
 * 复习页：安排（程序推荐 + 从题库挑题 → 确认）、复习列表（打印 / 评分 / 删除）、评分视图（评分、反馈、撤销 + 右侧复习助手）。
 * 概览页经 store.reviewIntent 带意图进入：{plan} 直接推荐、{session} 打开某次复习、{pinned:[题号]} 题库里选好的题带进来。
 */
import { html } from '../../core/html.js';
import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get, post } from '../../core/api.js';
import { toast, confirmDialog } from '../../ui/feedback.js';
import { GENRES, loadTaxonomy } from '../../domain/genres.js';
import { grading, sessionList } from './view.js';
import { picker, planner } from './planner.js';
import { initialPlanState, planActions } from './plan.js';
import { assistantActions, initialAssistant } from './assistant.js';

export const page = {
  id: 'review', title: '复习', icon: 'review',
  mount(root, { store, bus }) {
    const s = { ...initialPlanState(new Set(GENRES.map(g => g.code))), sessions: [], session: null, revealed: new Set(),
      openMats: new Set(), busy: null, noteFor: null, focus: null, pendingNotes: new Map(), ai: initialAssistant(),
      stickAi: false, taxonomy: null, today: '' };
    let alive = true; let frame = 0;

    function render() {
      if (!alive) return;
      cancelAnimationFrame(frame); frame = 0;
      const log = root.querySelector('#ai-log');
      const stick = s.stickAi || !log || log.scrollHeight - log.scrollTop - log.clientHeight < 60;
      morph(root, s.session ? grading(s) : html`<div class="rv">${planner(s)}${picker(s)}
        <section class="rv__sessions"><h2>复习记录</h2>${sessionList(s)}</section></div>`);
      const after = root.querySelector('#ai-log');
      if (after && stick) after.scrollTop = after.scrollHeight;
      s.stickAi = false;
    }
    const soon = () => { if (!frame) frame = requestAnimationFrame(render); };
    const fail = res => { toast(res.error.message, { tone: 'bad' }); };

    async function loadSessions() { const r = await get('/api/sessions'); if (r.ok) s.sessions = r.data.sessions; render(); }
    async function openSession(id) {
      const r = await get(`/api/session?id=${encodeURIComponent(id)}`);
      if (!r.ok) return fail(r);
      s.session = r.data; s.revealed = new Set(); s.openMats = new Set(Object.keys(r.data.materials).slice(0, 1));
      s.pendingNotes = new Map(); s.noteFor = null;
      s.focus = (r.data.items.find(x => !x.grade) || r.data.items[0])?.id || null;
      render(); root.scrollIntoView({ block: 'start' });
      return null;
    }
    /** 只换数据、不动界面状态（对答案、展开的原文、焦点都保留）。 */
    async function refresh() {
      const r = await get(`/api/session?id=${encodeURIComponent(s.session.id)}`);
      if (r.ok && s.session?.id === r.data.id) { s.session = r.data; render(); }
    }

    const plans = planActions(s, { render, afterCreate: async id => { await loadSessions(); return openSession(id); } });
    const ai = assistantActions(s, {
      render, soon, refresh, bus,
      clearComposer: () => { const ta = root.querySelector('#ai-composer'); if (ta) ta.value = ''; },
    });
    const unbindKeys = ai.bindKeys(root);

    const undefine = defineActions('rv', {
      ...plans.actions,
      ...ai.actions,
      open: ({ arg }) => openSession(arg),
      back: () => { ai.abort(); s.session = null; s.ai = initialAssistant(); loadSessions(); plans.makePlan(); },
      async cancel({ arg }) {
        const ok = await confirmDialog({ title: '删除这次复习？', body: '已经录的评分会一起撤销（提交链里留有记录）。', ok: '删除', danger: true });
        if (!ok) return null;
        const r = await post('/api/session/cancel', { id: arg });
        if (!r.ok) return fail(r);
        toast('已删除');
        plans.makePlan();
        return loadSessions();
      },
      focus: ({ arg }) => { if (s.focus !== arg) { s.focus = arg; s.stickAi = true; render(); } },
      ask: ({ arg }) => {
        s.focus = arg; s.ai.open = true; s.stickAi = true; render();
        root.querySelector('#ai-composer')?.focus();
      },
      reveal: ({ arg }) => { s.revealed.add(arg); s.focus = arg; render(); },
      mat: ({ arg, event }) => { event.preventDefault(); if (s.openMats.has(arg)) s.openMats.delete(arg); else s.openMats.add(arg); render(); },
      async grade({ arg }) {
        const [itemId, value] = arg.split(':');
        s.busy = itemId; s.focus = itemId; render();
        const note = s.pendingNotes.get(itemId);
        const r = await post('/api/session/grade', { session_id: s.session.id, item_id: itemId, grade: Number(value), ...(note ? { note } : {}) });
        s.busy = null;
        if (!r.ok) { render(); return fail(r); }
        s.pendingNotes.delete(itemId);
        s.session = r.data.session; render();
        bus.emit('library:changed');
        return null;
      },
      dropNote: ({ arg }) => { s.pendingNotes.delete(arg); render(); },
      noteEdit: ({ arg }) => { s.noteFor = s.noteFor === arg ? null : arg; render(); root.querySelector('.rv__noteinput')?.focus(); },
      async note({ el, arg }) {
        const item = s.session.items.find(x => x.id === arg);
        s.noteFor = null;
        if (!item?.grade) return render();
        const r = await post('/api/record/update', { commit_id: item.grade.commit_id, note: el.value });
        if (!r.ok) return fail(r);
        toast('反馈已保存');
        return refresh();
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
    loadTaxonomy().then(t => { s.taxonomy = t; render(); });
    get('/api/summary').then(r => { if (r.ok) { s.today = r.data.today; render(); } });
    loadSessions();
    if (intent?.pinned?.length) s.pinned = [...intent.pinned];
    if (intent?.session) openSession(intent.session);
    plans.makePlan();
    plans.loadPick();
    render();
    return () => { alive = false; cancelAnimationFrame(frame); ai.abort(); unbindKeys(); undefine(); };
  },
};
