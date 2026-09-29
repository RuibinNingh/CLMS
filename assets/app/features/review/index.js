/**
 * 复习页（工作台，占满高度、各栏自己滚动）：左栏 + 主区。
 * - 安排：左栏「复习记录」（进行中 / 已评完），主区「安排复习」（页头确认 + 本次安排 | 从题库挑题）。
 * - 评分：左栏「答题卡」（题号导航），主区一次一道题（原文 | 题目、对答案、自评、反馈）+ 右侧复习助手。
 * 离开复习页再回来，回到上次打开的那次复习和那道题（模块级记忆，刷新清空）。
 * 概览 / 题库经 store.reviewIntent 带意图进入：{plan} 直接推荐、{session} 打开某次复习、{pinned:[题号]} 带进自选。
 */
import { html } from '../../core/html.js';
import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get, post } from '../../core/api.js';
import { toast, confirmDialog } from '../../ui/feedback.js';
import { GENRES, loadTaxonomy } from '../../domain/genres.js';
import { initialPlanState, planActions } from './plan.js';
import { planView } from './planner.js';
import { questionNav, sessionsRail } from './rail.js';
import { gradingView } from './grading.js';
import { gradingActions } from './grading-actions.js';
import { assistantActions, initialAssistant } from './assistant-actions.js';
import { bindQuote, placeQuote, quoteButton } from './quote.js';

const memory = { session: null, focus: null };

function layout(s) {
  const grading = Boolean(s.session);
  return html`<div class="rv" data-mode="${grading ? 'grade' : 'plan'}" data-rail="${s.railOpen ? 'open' : 'closed'}" data-ai="${s.ai.open ? 'open' : 'closed'}">
    <aside class="rv__rail" aria-label="${grading ? '答题卡' : '复习记录'}">${grading ? questionNav(s) : sessionsRail(s)}</aside>
    ${s.railOpen ? html`<button class="rv__scrim" data-action="rv.rail" aria-label="收起左栏"></button>` : ''}
    <div class="rv__main">${grading ? gradingView(s) : planView(s)}</div>
    ${quoteButton(s)}
  </div>`;
}

export const page = {
  id: 'review', title: '复习', icon: 'review', workbench: true,
  mount(root, { store, bus }) {
    const s = {
      ...initialPlanState(new Set(GENRES.map(g => g.code))), sessions: null, session: null, revealed: new Set(), busy: null,
      focus: null, pendingNotes: new Map(), ai: initialAssistant(), stickAi: false, taxonomy: null, today: '',
      railOpen: false, quote: null, open: new Map(),
    };
    let alive = true; let frame = 0;

    function render() {
      if (!alive) return;
      cancelAnimationFrame(frame); frame = 0;
      const log = root.querySelector('#ai-log');
      const stick = s.stickAi || !log || log.scrollHeight - log.scrollTop - log.clientHeight < 60;
      morph(root, layout(s));
      const after = root.querySelector('#ai-log');
      if (after && stick) after.scrollTop = after.scrollHeight;
      s.stickAi = false;
      placeQuote(root, s);
      memory.session = s.session?.id || null; memory.focus = s.focus;
    }
    const soon = () => { if (!frame) frame = requestAnimationFrame(render); };
    const fail = res => { toast(res.error.message, { tone: 'bad' }); };

    async function loadSessions() {
      const r = await get('/api/sessions');
      if (r.ok) s.sessions = r.data.sessions; else if (s.sessions === null) s.sessions = [];
      render();
    }
    async function openSession(id, focus = null) {
      const r = await get(`/api/session?id=${encodeURIComponent(id)}`);
      if (!r.ok) { fail(r); return; }
      if (s.session?.id !== id) { s.revealed = new Set(); s.pendingNotes = new Map(); s.quote = null; }
      s.session = r.data; s.railOpen = false; s.stickAi = true;
      const items = r.data.items;
      s.focus = (items.find(x => x.id === focus) || items.find(x => !x.grade) || items[0])?.id || null;
      render();
    }
    /** 只换数据、不动界面状态（对答案、焦点、对话都保留）。 */
    async function refresh() {
      const r = await get(`/api/session?id=${encodeURIComponent(s.session.id)}`);
      if (r.ok && s.session?.id === r.data.id) { s.session = r.data; render(); }
    }

    const plans = planActions(s, { render, afterCreate: async id => { await loadSessions(); return openSession(id); } });
    const grades = gradingActions(s, { root, render, refresh, bus });
    const ai = assistantActions(s, { root, render, soon, refresh, bus });

    function back() {
      ai.abort();
      s.session = null; s.focus = null; s.quote = null; s.railOpen = false; s.ai = initialAssistant();
      render(); loadSessions(); plans.makePlan();
    }

    const undefine = defineActions('rv', {
      ...plans.actions,
      ...grades.actions,
      ...ai.actions,
      open: ({ arg }) => openSession(arg),
      back,
      newPlan: () => { if (s.session) back(); else { s.railOpen = false; render(); } },
      rail: () => { s.railOpen = !s.railOpen; render(); },
      async cancel({ arg }) {
        const ok = await confirmDialog({ title: '删除这次复习？', body: '已经录的评分会一起撤销（提交链里留有记录）。', ok: '删除', danger: true });
        if (!ok) return;
        const r = await post('/api/session/cancel', { id: arg });
        if (!r.ok) { fail(r); return; }
        toast('已删除');
        if (s.session?.id === arg) back(); else { plans.makePlan(); loadSessions(); }
      },
    });
    const unbind = [grades.bindKeys(ai.open), ai.bindComposer(), bindQuote(root, s, render)];

    const intent = store.get().reviewIntent;
    store.set({ reviewIntent: null });
    loadTaxonomy().then(t => { s.taxonomy = t; render(); });
    get('/api/summary').then(r => { if (r.ok) { s.today = r.data.today; render(); } });
    loadSessions();
    if (intent?.pinned?.length) s.pinned = [...intent.pinned];
    if (intent?.session) openSession(intent.session);
    else if (!intent && memory.session) openSession(memory.session, memory.focus);
    plans.makePlan();
    plans.loadPick();
    render();
    return () => { alive = false; cancelAnimationFrame(frame); ai.abort(); unbind.forEach(f => f()); undefine(); };
  },
};
