/** 预览即时排版与短防抖保存。队列按序落库，旧响应不能覆盖新手改。 */
import { post } from '../../core/api.js';
import { toast } from '../../ui/feedback.js';

export const initialPreview = () => ({ open: false, ready: false, pages: 0, focus: null, answers: false,
  saving: false, pending: false, error: '' });
const SESSION_KEY = 'clms-print-session';
export function rememberedPreview() { try { return sessionStorage.getItem(SESSION_KEY); } catch (_) { return null; } }

export function previewActions(s, { root, render, bus, isAlive }) {
  const pending = new Map();
  let timer = 0; let flight = null;
  const frame = () => root.querySelector('#review-print-frame');
  const paper = () => frame()?.contentWindow?.clmsPrint;
  const draw = () => { if (isAlive()) render(); };
  function remember(id) { try { if (id) sessionStorage.setItem(SESSION_KEY, id); else sessionStorage.removeItem(SESSION_KEY); } catch (_) { /* 隐私模式 */ } }

  function open() {
    s.preview = { ...initialPreview(), open: true, focus: s.session.items.find(x => x.genre !== 'dictation')?.id || s.focus };
    remember(s.session.id); draw();
  }

  function adjust(id, count) {
    if (!s.preview.ready || !Number.isInteger(count) || count < 0 || count > 1000) return;
    const item = s.session?.items.find(x => x.id === id);
    if (!item || item.blank_lines === count) return;
    item.blank_lines = count; pending.set(id, count); s.preview.pending = true; s.preview.error = '';
    const layout = paper()?.setLines({ [id]: count });
    if (layout) s.preview.pages = layout.pages;
    draw(); clearTimeout(timer); timer = setTimeout(flush, 450);
  }

  async function flush() {
    clearTimeout(timer);
    if (flight) { await flight; if (pending.size && !s.preview.error) return flush(); return !s.preview.error; }
    if (!pending.size) return true;
    const sessionId = s.session.id;
    const changes = [...pending].map(([item_id, blank_lines]) => ({ item_id, blank_lines }));
    pending.clear(); s.preview.saving = true; s.preview.pending = false; s.preview.error = ''; draw();
    flight = post('/api/session/blank-lines', { session_id: sessionId, changes });
    const result = await flight; flight = null;
    if (result.ok) bus.emit('library:changed');
    else changes.forEach(change => { if (!pending.has(change.item_id)) pending.set(change.item_id, change.blank_lines); });
    if (!isAlive() || s.session?.id !== sessionId) return result.ok;
    s.preview.saving = false; s.preview.pending = pending.size > 0;
    if (!result.ok) { s.preview.error = `未保存：${result.error.message}`; draw(); return false; }
    draw();
    if (pending.size) return flush();
    return true;
  }

  async function start() {
    if (!await flush() || !isAlive()) return;
    s.preview.open = false; remember(null); draw();
  }

  function auto(ids) {
    try {
      const counts = ids.map(id => [id, paper().fitAnswer(id)]);
      counts.forEach(([id, count]) => adjust(id, count));
      toast('已按参考答案的实际排版适配留白');
    } catch (error) { toast(error.message, { tone: 'bad' }); }
  }

  function onMessage(event) {
    const data = event.data;
    if (!isAlive() || event.origin !== location.origin || event.source !== frame()?.contentWindow
      || data?.session_id !== s.session?.id || !s.preview.open) return;
    if (data.type === 'clms-print-ready' || data.type === 'clms-print-layout') {
      s.preview.ready = data.type === 'clms-print-ready' || s.preview.ready;
      s.preview.pages = data.layout.pages; draw();
    }
  }
  function onPageHide() {
    if (!pending.size || !s.session) return;
    const changes = [...pending].map(([item_id, blank_lines]) => ({ item_id, blank_lines }));
    pending.clear(); clearTimeout(timer);
    fetch('/api/session/blank-lines', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: s.session.id, changes }), keepalive: true }).catch(() => {});
  }
  window.addEventListener('message', onMessage); window.addEventListener('pagehide', onPageHide);

  return {
    open, flush, clearRemembered: () => remember(null),
    actions: {
      printPreview: () => open(),
      printStep: ({ arg }) => { const [id, delta] = arg.split(':'); const item = s.session.items.find(x => x.id === id); adjust(id, (item.blank_lines || 0) + Number(delta)); },
      printLines: ({ el, arg }) => { if (el.value !== '') adjust(arg, Number(el.value)); },
      printAuto: ({ arg }) => auto([arg]),
      printAutoAll: () => auto(s.session.items.filter(x => x.genre !== 'dictation').map(x => x.id)),
      printSave: flush,
      printFocus: ({ arg }) => { s.preview.focus = arg; const page = paper()?.layout.item_pages[arg]?.[0];
        frame()?.contentDocument?.querySelector(`[data-page="${page}"]`)?.scrollIntoView({ block: 'start' }); draw(); },
      printAnswers: ({ el }) => { s.preview.answers = el.checked; const layout = paper()?.setAnswers(el.checked); if (layout) s.preview.pages = layout.pages; draw(); },
      printNow: async () => { if (await flush() && isAlive()) paper()?.print(); },
      printStart: start,
    },
    dispose() { clearTimeout(timer); flush(); window.removeEventListener('message', onMessage); window.removeEventListener('pagehide', onPageHide); },
  };
}
