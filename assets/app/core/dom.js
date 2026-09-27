/**
 * DOM 写入口：assets/app/ 里唯一允许写 innerHTML 的文件（check_ui R6）。只接受 core/html.js 的 HtmlResult。
 *
 * - render(el, result)：整体替换。
 * - morph(root, result)：差量更新，只改变化的部分，保留未变节点（及其事件、滚动位置、KaTeX 渲染结果）：
 *   · 带 data-key 的子节点按 key 对齐（可重排），其余按位置与标签名对齐；
 *   · 当前聚焦的输入框不改 value 与选区；
 *   · data-morph="skip" 的节点整棵不动（iframe、第三方渲染）；
 *   · data-hash 相同的节点整棵跳过（题面 KaTeX 靠这一条避免重算）。
 */
import { isHtml } from './html.js';

function markup(result) {
  if (!isHtml(result)) throw new TypeError('dom.js 只接受 html`` 的结果');
  return result.text;
}

export function render(el, result) {
  el.innerHTML = markup(result);
  return el;
}

/** 解析成 DocumentFragment（不插入文档）。节点归属 doc（template 内容属于惰性文档，需 importNode）。 */
export function toFragment(result, doc = document) {
  const tpl = doc.createElement('template');
  tpl.innerHTML = markup(result);
  return doc.importNode(tpl.content, true);
}

export function toElement(result, doc = document) {
  return toFragment(result, doc).firstElementChild;
}

const ELEMENT = 1;
const keyOf = node => (node.nodeType === ELEMENT ? node.getAttribute('data-key') : null);
const sameKind = (a, b) => a.nodeType === b.nodeType && (a.nodeType !== ELEMENT
  || (a.tagName === b.tagName && (a.tagName !== 'INPUT' || a.type === b.type)));

function syncAttributes(from, to) {
  for (const { name } of [...from.attributes]) if (!to.hasAttribute(name)) from.removeAttribute(name);
  for (const { name, value } of [...to.attributes]) if (from.getAttribute(name) !== value) from.setAttribute(name, value);
}

function syncFormState(from, to, active) {
  if (from === active) return;
  const tag = from.tagName;
  if (tag === 'INPUT') {
    if (from.type === 'checkbox' || from.type === 'radio') from.checked = to.hasAttribute('checked');
    else if (from.value !== to.value) from.value = to.value;
  } else if (tag === 'TEXTAREA') {
    if (from.value !== to.value) from.value = to.value;
  } else if (tag === 'SELECT') {
    const want = [...to.options].findIndex(o => o.hasAttribute('selected'));
    if (want >= 0 && from.selectedIndex !== want) from.selectedIndex = want;
  }
}

function update(from, to, active) {
  if (from.nodeType !== ELEMENT) {
    if (from.nodeValue !== to.nodeValue) from.nodeValue = to.nodeValue;
    return;
  }
  if (from.getAttribute('data-morph') === 'skip') return;
  const hash = to.getAttribute('data-hash');
  if (hash !== null && hash === from.getAttribute('data-hash')) return;
  syncAttributes(from, to);
  if (from.tagName !== 'TEXTAREA') morphChildren(from, to, active);
  syncFormState(from, to, active);
}

function morphChildren(from, to, active) {
  const keyed = new Map();
  for (const node of from.childNodes) {
    const key = keyOf(node);
    if (key !== null) keyed.set(key, node);
  }
  let cursor = from.firstChild;
  for (const next of [...to.childNodes]) {
    const key = keyOf(next);
    let match = null;
    if (key !== null) {
      match = keyed.get(key) || null;
      if (match && !sameKind(match, next)) match = null;
      if (match) keyed.delete(key);
    } else if (cursor && keyOf(cursor) === null && sameKind(cursor, next)) {
      match = cursor;
    }
    if (!match) {
      from.insertBefore(next, cursor);
      continue;
    }
    if (match === cursor) cursor = cursor.nextSibling;
    else from.insertBefore(match, cursor);
    update(match, next, active);
  }
  while (cursor) {
    const stale = cursor;
    cursor = cursor.nextSibling;
    from.removeChild(stale);
  }
}

export function morph(root, result) {
  const doc = root.ownerDocument;
  const active = doc.activeElement;
  const selection = active && typeof active.selectionStart === 'number'
    ? [active.selectionStart, active.selectionEnd, active.selectionDirection] : null;
  morphChildren(root, toFragment(result, doc), active);
  if (active && active !== doc.activeElement && active.isConnected && root.contains(active)) {
    active.focus({ preventScroll: true });
    if (selection) { try { active.setSelectionRange(...selection); } catch (_) { /* 该类型不支持选区 */ } }
  }
  return root;
}
