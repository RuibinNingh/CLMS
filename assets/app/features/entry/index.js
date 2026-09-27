/**
 * 录入页控制器：状态、轮询、自动保存与全部动作。渲染在 layout.js，纯数据操作在 edit.js。
 * - 轮询：有草稿在排队 / 识别 / 修改时每 1.2 秒刷新队列与当前草稿，否则每 8 秒。
 * - 手工编辑：先改本地工作副本，停顿 0.7 秒后整份提交（带版本号，AI 同时改过则拒绝并提示刷新）。
 * - AI 改完：新消息里的 changes 会在画布上闪一次，并可在对话里点「回到修改前」。
 * - Agent 模式：执行中也能发话（插话）、可以停止；输入框可附图（在输入框里粘贴截图也算附图）；
 *   「新对话」开一段没有草稿的对话；复习页「交给 AI 批改」经 store.entryIntent 打开对应会话。
 */
import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get, post } from '../../core/api.js';
import { toast, confirmDialog } from '../../ui/feedback.js';
import { loadTaxonomy } from '../../domain/genres.js';
import { readFiles } from './queue.js';
import { BUSY, view } from './layout.js';
import { addGroup, addItem, clone, insertBlank, parsePath, removeEntry, setField, stepLines } from './edit.js';

let lastActive = null;
const sleep = ms => new Promise(r => setTimeout(r, ms));

export const page = { id: 'entry', title: '录入', icon: 'entry', workbench: true, mount };

function mount(root, { bus, store }) {
  const intent = store.get().entryIntent;
  if (intent) { store.set({ entryIntent: null }); lastActive = intent.open; }
  const s = {
    drafts: [], aiReady: true, activeId: lastActive, draft: null, working: null, pane: 'draft', tab: 'draft',
    composer: '', withImage: true, pending: null, dragging: false, flash: null, expanded: new Set(),
    opened: new Set(), zoom: false, taxonomy: null, saving: false, dirty: false, seen: 0, attach: [], runLog: new Map(),
  };
  let alive = true;
  let pollTimer = 0; let saveTimer = 0; let flashTimer = 0;
  let scrollChat = false; let focusAfter = null; let scrollAnchor = null;

  function render() {
    if (!alive) return;
    morph(root, view(s));
    root.querySelectorAll('textarea[data-autosize]').forEach(autosize);
    if (scrollChat) { const log = root.querySelector('#chat-log'); if (log) log.scrollTop = log.scrollHeight; scrollChat = false; }
    if (scrollAnchor) {
      root.querySelector(`[data-anchor="${scrollAnchor}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      scrollAnchor = null;
    }
    if (focusAfter) { const el = root.querySelector(focusAfter); focusAfter = null; if (el) { el.focus(); el.setSelectionRange?.(el.value.length, el.value.length); } }
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
    const wasEmpty = s.draft && !s.draft.revision;
    const msgs = d.messages || [];
    if (!fresh && msgs.length > s.seen) {
      flashChanges(msgs.slice(s.seen).flatMap(m => (m.role === 'ai' || (m.role === 'edit' && !m.merge) ? m.changes || [] : [])));
      scrollChat = true;
    }
    if (fresh) { scrollChat = true; s.expanded = new Set(); s.opened = new Set(); s.pane = d.revision ? 'draft' : 'image'; }
    if (wasEmpty && d.revision) s.pane = 'draft';
    s.seen = msgs.length;
    s.draft = d;
    if (fresh || (!s.dirty && !s.saving)) s.working = clone(d.groups);
  }

  async function refreshList() {
    const res = await get('/api/drafts');
    if (!res.ok) return;
    s.drafts = res.data.drafts;
    s.aiReady = res.data.ai_ready;
    if (!s.activeId || !s.drafts.some(d => d.id === s.activeId)) {
      const next = s.drafts.find(d => d.status !== 'committed');
      s.activeId = next ? next.id : null;
      if (!next) s.draft = null;
    }
  }

  async function loadActive() {
    if (!s.activeId) { s.draft = null; return; }
    const res = await get(`/api/draft?id=${encodeURIComponent(s.activeId)}`);
    if (res.ok) applyDraft(res.data);
    else if (res.status === 404) { s.activeId = null; s.draft = null; }
  }

  async function poll() {
    clearTimeout(pollTimer);
    if (!alive) return;
    const busy = s.drafts.some(d => BUSY.includes(d.status)) || (s.draft && BUSY.includes(s.draft.status));
    await refreshList();
    if (!s.saving && !s.dirty) await loadActive();
    lastActive = s.activeId;
    render();
    const again = s.drafts.some(d => BUSY.includes(d.status)) || (s.draft && BUSY.includes(s.draft.status));
    pollTimer = setTimeout(poll, busy || again ? 1200 : 8000);
    bus.emit('badge', { id: 'entry', text: s.drafts.filter(d => d.status === 'ready').length || '' });
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

  // ── 上传 ──────────────────────────────────────────
  async function upload(images, combine) {
    s.pending = null;
    if (!images.length) { toast('没有可用的图片', { tone: 'bad' }); render(); return; }
    toast(`上传 ${images.length} 张图片…`);
    const hint = s.hint || '';
    s.hint = '';
    const res = await post('/api/drafts', { images, combine, hint }, { timeout: 120000 });
    if (!res.ok) { toast(res.error.message, { tone: 'bad', ms: 6000 }); render(); return; }
    s.activeId = res.data.drafts[0].id;
    s.draft = null;
    await poll();
  }

  async function takeFiles(files) {
    const images = await readFiles(files || []);
    if (images.length > 1) { s.pending = images; render(); } else await upload(images, false);
  }

  async function open(id) {
    await flush();
    s.activeId = id; lastActive = id; s.draft = null; s.tab = 'draft';
    await loadActive();
    render();
  }

  async function call(path, body, { reload = true, timeout } = {}) {
    const res = await post(path, body, timeout ? { timeout } : {});
    if (!res.ok) { toast(res.error.message, { tone: 'bad', ms: 5000 }); return null; }
    if (reload && res.data?.id) applyDraft(res.data);
    return res.data;
  }

  const undefine = defineActions('entry', {
    open: ({ arg }) => open(arg),
    files: ({ el }) => { const files = [...el.files]; el.value = ''; takeFiles(files); },
    hint: ({ el }) => { s.hint = el.value; },
    upload: ({ arg }) => (arg === 'cancel' ? (s.pending = null, render()) : upload(s.pending || [], arg === 'combine')),
    async manual({ el }) {
      const genre = el.value; el.value = '';
      if (!genre) return;
      const res = await post('/api/drafts', { manual: genre });
      if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return; }
      await open(res.data.drafts[0].id);
      poll();
    },
    field({ el, event }) {
      const { field } = parsePath(el.dataset.path);
      const structural = event.type === 'change' || field === 'template' || field.startsWith('blank:');
      if (el.tagName === 'TEXTAREA') autosize(el);
      edit(setField(s.working, el.dataset.path, el.value), { now: event.type === 'change', rerender: structural });
    },
    lines: ({ el, arg }) => edit(stepLines(s.working, el.dataset.path, Number(arg)), { now: true }),
    add: ({ arg }) => edit(addItem(s.working, arg), { now: true }),
    addGroup({ el }) {
      const genre = el.value; el.value = '';
      if (genre) edit(addGroup(s.working, genre), { now: true });
    },
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
    async attach({ el }) { const files = [...el.files]; el.value = ''; s.attach.push(...await readFiles(files)); render(); },
    unattach: ({ arg }) => { s.attach.splice(Number(arg), 1); render(); },
    async stop() { if (await call('/api/draft/abort', { id: s.draft.id })) { toast('已停止'); render(); poll(); } },
    runlog({ arg }) {
      const i = Number(String(arg).split(':').pop());
      const running = s.draft?.messages?.[i]?.status === 'running';
      s.runLog.set(arg, !(s.runLog.has(arg) ? s.runLog.get(arg) : running));
      render();
    },
    async newChat() {
      const res = await post('/api/drafts', { chat: true });
      if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return; }
      await open(res.data.drafts[0].id);
      focusAfter = '#composer'; render();
      poll();
    },
    suggest: ({ arg }) => { s.composer = s.composer.trim() ? `${s.composer.trim()}\n${arg}` : arg; focusAfter = '#composer'; render(); },
    withImage: () => { s.withImage = !s.withImage; render(); },
    async send() {
      const text = s.composer.trim();
      const images = s.attach;
      if ((!text && !images.length) || !s.draft) return;
      await flush();
      s.composer = ''; s.attach = [];
      const box = root.querySelector('#composer');
      if (box) box.value = '';                 // morph 会保留聚焦输入框的值，发送后要手动清空
      const data = await call('/api/draft/message', { id: s.draft.id, text, with_image: s.withImage, images }, { timeout: 120000 });
      if (!data) { s.composer = text; s.attach = images; }
      scrollChat = true;
      render();
      poll();
    },
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
    async discard() {
      const ok = await confirmDialog({ title: '丢弃这份草稿？', body: '原图会保留在数据目录里，草稿和对话记录不再显示。', ok: '丢弃', danger: true });
      if (!ok) return;
      if (await call('/api/draft/discard', { id: s.draft.id }, { reload: false })) {
        s.activeId = null; s.draft = null;
        await poll();
      }
    },
    next() {
      const next = s.drafts.find(d => d.status !== 'committed' && d.id !== s.draft?.id);
      if (next) open(next.id); else { s.activeId = null; lastActive = null; s.draft = null; render(); }
    },
  });

  // ── 文档级监听：粘贴截图、拖放、Enter 发送 ──────────
  const onPaste = async event => {
    const files = [...(event.clipboardData?.files || [])].filter(f => f.type.startsWith('image/'));
    if (!files.length) return;
    event.preventDefault();
    if (event.target?.id === 'composer' && s.draft?.agent) { s.attach.push(...await readFiles(files)); render(); return; }
    takeFiles(files);
  };
  const onDragOver = event => {
    if (![...(event.dataTransfer?.types || [])].includes('Files')) return;
    event.preventDefault();
    if (!s.dragging) { s.dragging = true; render(); }
  };
  const onDragLeave = event => { if (event.target === root || !root.contains(event.relatedTarget)) { s.dragging = false; render(); } };
  const onDrop = event => {
    if (!event.dataTransfer?.files?.length) return;
    event.preventDefault();
    s.dragging = false;
    takeFiles(event.dataTransfer.files);
  };
  const onKey = event => {
    if (event.target.id === 'composer' && event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      root.querySelector('[data-action="entry.send"]')?.click();
    }
  };
  document.addEventListener('paste', onPaste);
  root.addEventListener('dragover', onDragOver);
  root.addEventListener('dragleave', onDragLeave);
  root.addEventListener('drop', onDrop);
  root.addEventListener('keydown', onKey);

  render();
  loadTaxonomy().then(t => { s.taxonomy = t; render(); });
  poll();

  return () => {
    alive = false;
    if (s.dirty) saveNow();
    clearTimeout(pollTimer); clearTimeout(flashTimer);
    undefine();
    document.removeEventListener('paste', onPaste);
    root.removeEventListener('dragover', onDragOver);
    root.removeEventListener('dragleave', onDragLeave);
    root.removeEventListener('drop', onDrop);
    root.removeEventListener('keydown', onKey);
  };
}
