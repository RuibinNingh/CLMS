/**
 * 评分视图的动作：换题、对答案、自评、撤销、反馈，以及键盘（← → 换题、空格对答案、0–3 自评、/ 问助手）。
 * 改评分时把已有的反馈一起带上（后端改评 = 作废旧记录 + 新记录，不带就丢了）；还没评分时写的反馈先暂存
 * （s.pendingNotes），评分时一起写入。
 */
import { post } from '../../core/api.js';
import { toast } from '../../ui/feedback.js';
import { gradesFor } from '../../domain/genres.js';
import { focusTarget, isShown } from './focus.js';

const TYPING = 'input, textarea, select, [contenteditable="true"], dialog';

export function gradingActions(s, { root, render, refresh, bus }) {
  const fail = res => toast(res.error.message, { tone: 'bad' });

  /** 换到某道题：题目从头看，答题卡滚到能看见这一行。 */
  function go(id) {
    if (!id || !s.session) return;
    s.railOpen = false;
    if (s.focus !== id) { s.focus = id; s.stickAi = true; s.quote = null; }
    render();
    root.querySelector('.rv-sheets')?.scrollTo?.({ top: 0 });
    root.querySelector('.rv-nav__row[aria-current="step"]')?.scrollIntoView?.({ block: 'nearest' });
  }

  function step(delta) {
    const t = focusTarget(s);
    const next = t && s.session.items[t.n - 1 + delta];
    if (next) go(next.id);
  }

  function reveal(id) {
    s.revealed.add(id); s.focus = id; render();
    // 焦点放在题目卡片上（不放在评分按钮上：再按一次空格会误评「不会」）
    root.querySelector('.rv-q')?.focus({ preventScroll: true });
  }

  async function grade(id, value) {
    const item = s.session.items.find(x => x.id === id);
    if (!item || s.busy) return;
    if (!gradesFor(item.genre).some(g => g.value === value)) return;
    s.busy = id; s.focus = id; render();
    const note = s.pendingNotes.get(id) ?? item.grade?.note ?? '';
    const r = await post('/api/session/grade', { session_id: s.session.id, item_id: id, grade: value, note });
    s.busy = null;
    if (!r.ok) { render(); fail(r); return; }
    s.pendingNotes.delete(id);
    s.revealed.add(id);
    s.session = r.data.session; render();
    bus.emit('library:changed');
    if (s.session.progress.complete) toast('这次复习评完了');
  }

  async function saveNote(id, value) {
    const item = s.session.items.find(x => x.id === id);
    const text = String(value || '').trim();
    if (!item) return;
    if (!item.grade) {
      if (text) s.pendingNotes.set(id, text); else s.pendingNotes.delete(id);
      render();
      return;
    }
    if (text === (item.grade.note || '')) return;
    const r = await post('/api/record/update', { commit_id: item.grade.commit_id, note: text });
    if (!r.ok) { fail(r); return; }
    toast('反馈已保存');
    await refresh();
  }

  const actions = {
    go: ({ arg }) => go(arg),
    step: ({ arg }) => step(Number(arg)),
    reveal: ({ arg }) => reveal(arg),
    grade: ({ arg }) => { const [id, value] = arg.split(':'); return grade(id, Number(value)); },
    note: ({ el, arg }) => saveNote(arg, el.value),
    dropNote: ({ arg }) => { s.pendingNotes.delete(arg); render(); },
    async ungrade({ arg }) {
      const r = await post('/api/session/ungrade', { session_id: s.session.id, item_id: arg });
      if (!r.ok) { fail(r); return; }
      s.session = r.data; render();
      bus.emit('library:changed');
    },
  };

  /** 文档级键盘：只在评分视图、焦点不在输入框里时生效。返回解绑函数。 */
  function bindKeys(openAssistant) {
    const doc = root.ownerDocument;
    const onKey = event => {
      if (!s.session || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
      if (!root.isConnected || !root.offsetParent) return;
      const target = event.target;
      if (target?.closest?.(TYPING)) return;
      const t = focusTarget(s);
      if (!t) return;
      const key = event.key;
      if (key === 'ArrowLeft' || key === 'ArrowRight') {
        event.preventDefault(); step(key === 'ArrowLeft' ? -1 : 1);
      } else if (key === ' ' && !isShown(t.it, s) && !target?.closest?.('button, a, summary')) {
        event.preventDefault(); reveal(t.it.id);
      } else if (/^[0-3]$/.test(key) && isShown(t.it, s)) {
        event.preventDefault(); grade(t.it.id, Number(key));
      } else if (key === '/') {
        event.preventDefault(); openAssistant();
      }
    };
    doc.addEventListener('keydown', onKey);
    return () => doc.removeEventListener('keydown', onKey);
  }

  return { actions, bindKeys, go };
}
