/**
 * 卷面引用：在评分页的原文或题目里选中文字 → 选区末尾浮出「引用」按钮 → 点了放进助手输入框上方。
 * 引用带位置：原文按 data-mid / data-para 记成《篇名》第 n 段；题目按 data-q / data-part 记成第 n 题的题干或参考答案。
 * 选区变化用 selectionchange（鼠标拖选和手机长按都能收到），停下 180ms 后才更新，避免拖选时反复重画。
 */
import { html } from '../../core/html.js';
import { setVars } from '../../core/dom.js';
import { icon } from '../../ui/icons.js';

const MAX = 400;
const host = node => (node?.nodeType === 1 ? node : node?.parentElement);

/** 当前选区 → { text, where, label, x, y }；不在卷面上、太短或跨出卷面时返回 null。 */
export function readQuote(root) {
  const sel = root.ownerDocument.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
  const text = sel.toString().replace(/\s+/g, ' ').trim();
  if (text.length < 2) return null;
  const range = sel.getRangeAt(0);
  const start = host(range.startContainer);
  const end = host(range.endContainer);
  const stage = start?.closest('.rv-stage');
  if (!stage || !root.contains(stage) || !stage.contains(end) || start.closest('input, textarea, button, .rv-score, .rv-fb, .rv-step')) return null;
  const mat = start.closest('[data-mid]');
  const para = start.closest('[data-para]');
  const part = start.closest('[data-part]');
  let where = {};
  let label = '卷面';
  if (mat) {
    where = { material_id: mat.dataset.mid, ...(para ? { para: para.dataset.para } : {}) };
    label = `《${mat.dataset.title}》${para ? `第 ${para.dataset.para} 段` : ''}`;
  } else if (part) {
    where = { n: part.dataset.q, part: part.dataset.part };
    label = `第 ${part.dataset.q} 题${part.dataset.part === 'answer' ? '参考答案' : '题干'}`;
  }
  const rects = range.getClientRects();
  const r = rects[rects.length - 1] || range.getBoundingClientRect();
  return { text: text.length > MAX ? `${text.slice(0, MAX)}…` : text, where, label, x: r.right, y: r.bottom };
}

export const quoteButton = s => (s.quote ? html`<button class="rv-quote" data-action="rv.quote" aria-label="引用选中的文字问助手">${icon('quote')}引用</button>` : '');

/** 把浮动按钮放到选区末尾下方（夹在视口里）。 */
export function placeQuote(root, s) {
  const btn = root.querySelector('.rv-quote');
  if (!btn || !s.quote) return;
  const view = root.ownerDocument.documentElement;
  const x = Math.min(Math.max(8, s.quote.x - btn.offsetWidth / 2), view.clientWidth - btn.offsetWidth - 8);
  const y = Math.min(s.quote.y + 8, view.clientHeight - btn.offsetHeight - 8);
  setVars(btn, { '--qx': `${Math.round(x)}px`, '--qy': `${Math.round(y)}px` });
}

/** 监听选区与滚动；返回解绑函数。 */
export function bindQuote(root, s, render) {
  const doc = root.ownerDocument;
  let timer = 0;
  const update = () => {
    const q = s.session ? readQuote(root) : null;
    if (!q && !s.quote) return;
    if (q && s.quote && q.text === s.quote.text && q.x === s.quote.x && q.y === s.quote.y) return;
    s.quote = q;
    render();
  };
  const onSelection = () => { clearTimeout(timer); timer = setTimeout(update, 180); };
  const onScroll = event => {
    if (s.quote && event.target?.closest?.('.rv-sheets, .rv-mat, .rv-qcol')) { s.quote = null; render(); }
  };
  // 按下「引用」时不让浏览器收起选区、挪走焦点（否则按住稍久按钮就先消失了）
  const onDown = event => { if (event.target?.closest?.('.rv-quote')) event.preventDefault(); };
  doc.addEventListener('selectionchange', onSelection);
  root.addEventListener('scroll', onScroll, true);
  root.addEventListener('mousedown', onDown);
  return () => {
    clearTimeout(timer);
    doc.removeEventListener('selectionchange', onSelection);
    root.removeEventListener('scroll', onScroll, true);
    root.removeEventListener('mousedown', onDown);
  };
}
