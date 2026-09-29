/**
 * 录入页控制器：状态、录入记录、实时流、自动保存与动作。渲染在 layout.js，管理类动作在 manage.js，纯数据操作在 edit.js。
 * - 流程：居中输入框（launch.js：新对话，或上传后确认页序 / 方向 / 说明）→ 开始 → Agent 执行（对话里实时显示思考、
 *   说的话、工具调用）→ 校对 → 入库 →「录下一份」回到居中输入框。两种界面之间用 View Transition 过渡（输入框平滑移动）。
 * - 实时：打开一份草稿就订阅 /api/draft/events（SSE）。block 事件整块替换，delta 事件逐字追加（requestAnimationFrame 合批重画），
 *   status 事件稍后重新拉草稿（右侧草稿随工具调用实时更新）。live_seq 之前的事件忽略，避免和刚拉到的快照重复。
 * - 录入记录每 4 秒（有执行中的）或 15 秒刷新；执行中每秒重画一次计时。
 * - 手工编辑：先改本地工作副本，停顿 0.7 秒后整份提交（带版本号，AI 同时改过则拒绝并提示刷新）。
 * - 时间线跟随：用户停在底部时新内容自动滚到底；往上翻看时不打扰。
 * - 输入框旁的圆环（gauge.js）：服务端 stats 事件给上下文与累计用量，逐字事件在前端算实时速度。
 * - 录入记录宽屏可收起，状态存在 localStorage（clms-hist）。
 */
import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get, post } from '../../core/api.js';
import { subscribe } from '../../core/sse.js';
import { readImages } from '../../core/files.js';
import { toast, confirmDialog } from '../../ui/feedback.js';
import { loadTaxonomy } from '../../domain/genres.js';
import { BUSY, view } from './layout.js';
import { manageActions } from './manage.js';
import { createRate } from './gauge.js';
import { bindListeners } from './listeners.js';
import { fileImports } from './imports.js';
import { pageManager } from './page-manager.js';
import { addGroup, addItem, clone, insertBlank, parsePath, removeEntry, setField, stepLines } from './edit.js';

let lastActive = null;
const remembered = { view: 'all', q: '' };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const reduceMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const wide = () => window.matchMedia?.('(min-width: 1501px)').matches;
const stored = key => { try { return localStorage.getItem(key); } catch (_) { return null; } };
const localDay = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

export const page = { id: 'entry', title: '录入', icon: 'entry', workbench: true, mount };

function mount(root, { bus, store }) {
  const intent = store.get().entryIntent;
  if (intent) { store.set({ entryIntent: null }); lastActive = intent.open; }
  const s = {
    drafts: [], counts: {}, total: 0, view: remembered.view, q: remembered.q, limit: 60, today: localDay(),
    aiReady: true, activeId: lastActive, draft: null, working: null, pane: 'draft', tab: 'chat', histOpen: false,
    composer: '', withImage: true, attach: [], dragging: false, dragPage: null, flash: null, expanded: new Set(),
    opened: new Set(), zoom: false, taxonomy: null, saving: false, dirty: false, seen: 0, open: new Map(),
    renaming: null, starting: false, liveSeq: 0, heroText: '', split: false, known: new Set(), liveTps: 0,
    histCollapsed: stored('clms-hist') === 'collapsed',
  };
  const rate = createRate();
  let alive = true; let pollTimer = 0; let saveTimer = 0; let flashTimer = 0; let refetchTimer = 0; let frame = 0;
  let closeStream = null; let streamId = null; let loadSeq = 0; let openSeq = 0;
  let focusAfter = null; let scrollAnchor = null; let forceBottom = false;
  const manager = pageManager({ s, root, render });

  function render() {
    if (!alive) return;
    cancelAnimationFrame(frame); frame = 0;
    s.liveTps = s.draft && BUSY.includes(s.draft.status) ? rate.tps() : 0;
    s.wide = wide();
    const log = root.querySelector('#chat-log');
    const stick = forceBottom || !log || log.scrollHeight - log.scrollTop - log.clientHeight < 80;
    morph(root, view(s));
    manager.sync();
    root.querySelectorAll('textarea[data-autosize]').forEach(autosize);
    const after = root.querySelector('#chat-log');
    if (after && stick) after.scrollTop = after.scrollHeight;
    forceBottom = false;
    if (scrollAnchor) {
      root.querySelector(`[data-anchor="${scrollAnchor}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      scrollAnchor = null;
    }
    if (focusAfter) { const el = root.querySelector(focusAfter); focusAfter = null; if (el) { el.focus(); el.setSelectionRange?.(el.value.length, el.value.length); } }
  }
  const soon = () => { if (!frame) frame = requestAnimationFrame(render); };

  /** 界面大变化（开始 ↔ 对话）走 View Transition：输入框从中间落到底部（或反过来），其余交叉淡入淡出。 */
  async function transition(update) {
    update();                                          // 状态立刻变（进行中的刷新据此作废），只把「画」交给过渡
    if (!document.startViewTransition || reduceMotion() || document.hidden) { render(); return; }
    await document.startViewTransition(() => render()).finished.catch(() => {});
  }

  function autosize(ta) {
    ta.style.height = 'auto';
    ta.style.height = `${ta.scrollHeight + 2}px`;
  }

  function flashChanges(changes, { scroll = true } = {}) {
    if (!changes?.length) return;
    if (scroll && s.pane === 'draft') scrollAnchor = `${changes[0].gid}|${changes[0].iid}`;
    s.flash = new Set(changes.map(c => `${c.gid}|${c.iid}|${c.field === '-' ? '*' : c.field}`));
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => { s.flash = null; render(); }, 2200);
  }

  function applyDraft(d) {
    const fresh = !s.draft || s.draft.id !== d.id;
    const msgs = d.messages || [];
    if (!fresh && msgs.length > s.seen) {
      flashChanges(msgs.slice(s.seen).flatMap(m => (['run', 'ai'].includes(m.role) || (m.role === 'edit' && !m.merge) ? m.changes || [] : [])));
    }
    if (fresh) {
      forceBottom = true; s.expanded = new Set(); s.opened = new Set(); s.open = new Map(); s.pane = d.revision ? 'draft' : 'image';
      s.known = new Set(msgs.map(m => m.id)); s.split = false;
      if (d.status === 'staged') s.heroText = d.hint || '';
    }
    if (s.draft && !s.draft.revision && d.revision) s.pane = 'draft';
    s.seen = msgs.length;
    s.draft = d;
    s.liveSeq = Math.max(fresh ? 0 : s.liveSeq, d.live_seq || 0);
    if (fresh || (!s.dirty && !s.saving)) s.working = clone(d.groups);
  }

  // ── 实时流 ───────────────────────────────────────
  function onEvent(ev) {
    if (!s.draft || (ev.seq && ev.seq <= s.liveSeq)) return;
    if (ev.seq) s.liveSeq = ev.seq;
    const msgs = s.draft.messages;
    if (ev.type === 'delta') {
      const block = msgs.find(m => m.id === ev.id);
      rate.add(ev.text);
      if (block) { block[ev.field] = (block[ev.field] || '') + ev.text; soon(); }
    } else if (ev.type === 'stats') {
      s.draft.stats = ev.stats; soon();
    } else if (ev.type === 'block') {
      const i = msgs.findIndex(m => m.id === ev.block.id);
      if (i >= 0) msgs[i] = ev.block; else msgs.push(ev.block);
      soon();
    } else if (ev.type === 'status' || ev.type === 'reload') {
      if (ev.status) s.draft.status = ev.status;
      clearTimeout(refetchTimer);
      refetchTimer = setTimeout(() => {                 // 草稿和左侧录入记录一起刷新：状态点、标题、题数随执行结束立刻变
        if (!s.saving && !s.dirty) Promise.all([loadActive(), refreshList()]).then(render);
      }, ev.type === 'reload' ? 0 : 250);
    }
  }

  function connect() {
    if (!s.draft || streamId === s.draft.id) return;
    closeStream?.();
    streamId = s.draft.id;
    closeStream = subscribe(`/api/draft/events?id=${encodeURIComponent(streamId)}&since=${s.liveSeq}`, onEvent);
  }

  async function refreshList() {
    const q = new URLSearchParams({ view: s.view, q: s.q, limit: s.limit });
    remembered.view = s.view; remembered.q = s.q;
    const res = await get(`/api/drafts?${q}`);
    if (!res.ok) return;
    Object.assign(s, { drafts: res.data.drafts, counts: res.data.counts, total: res.data.total, aiReady: res.data.ai_ready, today: localDay() });
  }

  async function loadActive() {
    const id = s.activeId;
    if (!id) { s.draft = null; return; }
    const mine = ++loadSeq;
    const opening = openSeq;
    const res = await get(`/api/draft?id=${encodeURIComponent(id)}`);
    // 请求途中切走了、后发的刷新先回来了、或者用户又打开了别的：这份旧回复作废，免得界面倒退
    if (s.activeId !== id || mine !== loadSeq || opening !== openSeq) return;
    if (res.ok) { applyDraft(res.data); connect(); } else if (res.status === 404) { s.activeId = null; s.draft = null; }
  }

  async function poll() {
    clearTimeout(pollTimer);
    if (!alive) return;
    await refreshList();
    if (!s.saving && !s.dirty && s.draft && BUSY.includes(s.draft.status)) await loadActive();
    lastActive = s.activeId;
    render();
    const busy = s.drafts.some(d => BUSY.includes(d.status)) || (s.draft && BUSY.includes(s.draft.status));
    pollTimer = setTimeout(poll, busy ? 4000 : 15000);
    bus.emit('badge', { id: 'entry', text: s.counts.ready || '' });
  }

  // ── 保存 ──────────────────────────────────────────
  function scheduleSave(delay = 700) {
    s.dirty = true;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveNow, delay);
  }

  async function saveNow() {
    clearTimeout(saveTimer);
    if (!s.draft || !s.dirty || s.saving) return;
    s.saving = true; s.dirty = false;
    const res = await post('/api/draft/edit', { id: s.draft.id, groups: s.working, revision: s.draft.revision });
    s.saving = false;
    if (!alive) return;
    if (!res.ok) {
      toast(res.error.message, { tone: 'bad' });
      await loadActive(); s.working = clone(s.draft.groups); render();
      return;
    }
    const more = s.dirty;
    s.draft = res.data; s.seen = res.data.messages.length;
    if (!more) s.working = clone(res.data.groups);
    render();
    if (more) scheduleSave(250);
  }

  async function flush() {
    for (let i = 0; i < 100 && (s.dirty || s.saving); i += 1) {
      if (!s.saving) await saveNow(); else await sleep(80);
    }
  }

  function edit(next, { now = false, rerender = true } = {}) {
    s.working = next;
    scheduleSave(now ? 0 : 700);
    if (rerender) render();
  }

  // ── 上传 / 打开 ───────────────────────────────────
  async function open(id, { fromHero = false } = {}) {
    manager.reset();
    imports.clear();
    await flush();
    const mine = ++openSeq;                              // 打开以最后一次为准；后台刷新不会打断它
    const res = await get(`/api/draft?id=${encodeURIComponent(id)}`);
    if (mine !== openSeq) return;
    if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return; }
    const change = Boolean(s.draft) !== true || s.draft.status === 'staged' || res.data.status === 'staged' || fromHero;
    const apply = () => {
      closeStream?.(); closeStream = null; streamId = null;
      s.activeId = id; lastActive = id; s.draft = null; s.tab = 'chat'; s.histOpen = false; s.renaming = null;
      applyDraft(res.data);
      if (fromHero) s.known = new Set();              // 从开始界面过来：第一条消息也要入场
      connect();
    };
    if (change) await transition(apply); else { apply(); render(); }
    await refreshList();
    render();
  }

  /** 回到居中输入框（新录入 / 录下一份）。 */
  async function fresh() {
    manager.reset();
    imports.clear();
    await flush();
    await transition(() => {
      closeStream?.(); closeStream = null; streamId = null;
      s.activeId = null; lastActive = null; s.draft = null; s.heroText = ''; s.attach = []; s.histOpen = false; s.split = false;
    });
    root.querySelector('#composer')?.focus();
  }

  async function heroSend() {
    const text = s.heroText.trim();
    if (!text || s.starting || s.imports.length) return;
    s.starting = true; render();
    const made = await post('/api/drafts', { chat: true });
    const sent = made.ok ? await post('/api/draft/message', { id: made.data.drafts[0].id, text }, { timeout: 120000 }) : made;
    s.starting = false;
    if (!sent.ok) { toast(sent.error.message, { tone: 'bad', ms: 6000 }); render(); return; }
    s.heroText = '';
    await open(made.data.drafts[0].id, { fromHero: true });
    poll();
  }

  const imports = fileImports({ s, root, render, post, applyDraft, connect, refreshList, fresh });
  const takeFiles = imports.take;
  const pickFiles = ({ el }) => { const files = [...el.files]; el.value = ''; takeFiles(files); };

  async function call(path, body, { reload = true, timeout } = {}) {
    const res = await post(path, body, timeout ? { timeout } : {});
    if (!res.ok) { toast(res.error.message, { tone: 'bad', ms: 5000 }); return null; }
    if (reload && res.data?.id) applyDraft(res.data);
    return res.data;
  }

  const managed = manageActions({ s, root, render, refreshList, open, fresh, post, toast, confirmDialog, applyDraft, poll });
  const actions = {
    ...managed,
    ...manager.actions,
    pageAdd: pickFiles,
    importRetry: imports.retry,
    importRemove: imports.remove,
    open: ({ arg }) => open(arg),
    files: pickFiles,
    async manual({ el }) {
      const genre = el.value; el.value = '';
      if (!genre) return;
      const res = await post('/api/drafts', { manual: genre });
      if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return; }
      await open(res.data.drafts[0].id);
    },
    fresh: () => fresh(),
    heroText({ el }) {
      s.heroText = el.value;
      autosize(el);
      const btn = root.querySelector('.launch .composer__send');
      if (btn && s.draft?.status !== 'staged') btn.disabled = !s.heroText.trim() || Boolean(s.imports.length);
    },
    heroSuggest: ({ arg }) => { s.heroText = arg; focusAfter = '#composer'; render(); },
    split: ({ arg }) => { s.split = arg === 'each'; render(); },
    collapse() {
      s.histCollapsed = !s.histCollapsed;
      try { localStorage.setItem('clms-hist', s.histCollapsed ? 'collapsed' : 'open'); } catch (_) { /* 隐私模式 */ }
      render();
    },
    hist() {
      if (wide()) { actions.collapse(); return; }
      s.histOpen = !s.histOpen; render();
    },
    field({ el, event }) {
      if (el.dataset.oneline !== undefined && /\n/.test(el.value)) el.value = el.value.replace(/\s*\n\s*/g, ' ');   // 粘贴进来的换行
      const { field } = parsePath(el.dataset.path);
      const structural = event.type === 'change' || field === 'template' || field.startsWith('blank:');
      if (el.tagName === 'TEXTAREA') autosize(el);
      edit(setField(s.working, el.dataset.path, el.value), { now: event.type === 'change', rerender: structural });
    },
    lines: ({ el, arg }) => edit(stepLines(s.working, el.dataset.path, Number(arg)), { now: true }),
    add: ({ arg }) => edit(addItem(s.working, arg), { now: true }),
    addGroup({ el }) { const genre = el.value; el.value = ''; if (genre) edit(addGroup(s.working, genre), { now: true }); },
    remove: ({ arg }) => edit(removeEntry(s.working, arg), { now: true }),
    insertBlank: ({ arg }) => { focusAfter = `textarea[data-path="${arg}|template"]`; edit(insertBlank(s.working, arg), { now: true }); },
    reveal: ({ arg }) => { s.opened.add(arg); focusAfter = `textarea[data-path="${arg}"]`; render(); },
    expand: ({ arg }) => { if (s.expanded.has(arg)) s.expanded.delete(arg); else s.expanded.add(arg); render(); },
    composer({ el }) {
      s.composer = el.value;
      autosize(el);
      const btn = root.querySelector('[data-action="entry.send"]');
      if (btn) btn.disabled = !s.composer.trim() && !s.attach.length;
    },
    async attach({ el }) { const files = [...el.files]; el.value = ''; s.attach.push(...await readImages(files)); render(); },
    unattach: ({ arg }) => { s.attach.splice(Number(arg), 1); render(); },
    suggest: ({ arg }) => { s.composer = s.composer.trim() ? `${s.composer.trim()}\n${arg}` : arg; focusAfter = '#composer'; render(); },
    withImage: () => { s.withImage = !s.withImage; render(); },
    async send() {
      if (!s.draft) { heroSend(); return; }
      const text = s.composer.trim();
      const images = s.attach;
      if ((!text && !images.length) || !s.draft) return;
      await flush();
      s.composer = ''; s.attach = [];
      const box = root.querySelector('#composer');
      if (box) box.value = '';                 // morph 会保留聚焦输入框的值，发送后要手动清空
      forceBottom = true;
      const data = await call('/api/draft/message', { id: s.draft.id, text, with_image: s.withImage, images }, { timeout: 120000 });
      if (!data) { s.composer = text; s.attach = images; }
      render();
      poll();
    },
    async stop() { if (await call('/api/draft/abort', { id: s.draft.id })) { toast('已停止'); render(); } },
    async restore({ arg }) {
      await flush();
      if (await call('/api/draft/restore', { id: s.draft.id, revision: Number(arg) })) {
        s.working = clone(s.draft.groups);
        flashChanges(s.draft.messages.at(-1)?.changes);
        render();
      }
    },
    async retry() { if (await call('/api/draft/retry', { id: s.draft.id })) { render(); poll(); } },
    jump({ arg }) {
      const [gid, iid] = String(arg).split('|');
      s.pane = 'draft'; s.tab = 'draft';
      if (gid && !iid) s.expanded.add(gid);
      flashChanges([{ gid, iid: iid || '', field: '*' }]);
      render();
    },
    pane: ({ arg }) => { s.pane = arg; s.tab = 'draft'; render(); },
    tab: ({ arg }) => { if (arg === 'chat') s.tab = 'chat'; else { s.tab = 'draft'; s.pane = arg; } render(); },
    zoom: () => { s.zoom = !s.zoom; render(); },
    async commit() {
      await flush();
      const data = await call('/api/draft/commit', { id: s.draft.id });
      if (!data) return;
      const c = data.committed;
      toast(`已入库 ${c.created} 题${c.reencountered ? `，${c.reencountered} 题记为又错一次` : ''}`);
      bus.emit('library:changed');
      await refreshList();
      render();
    },
  };
  const undefine = defineActions('entry', actions);

  const unbind = bindListeners(root, { s, render, takeFiles, readImages, movePage: managed.movePage });
  const ticker = setInterval(() => { if (s.draft && BUSY.includes(s.draft.status)) render(); }, 1000);

  render();
  loadTaxonomy().then(t => { s.taxonomy = t; render(); });
  loadActive().then(poll);

  return () => {
    alive = false;
    manager.dispose();
    imports.clear();
    if (s.dirty) saveNow();
    clearTimeout(pollTimer); clearTimeout(flashTimer); clearTimeout(refetchTimer); clearInterval(ticker);
    cancelAnimationFrame(frame);
    closeStream?.();
    undefine();
    unbind();
  };
}
