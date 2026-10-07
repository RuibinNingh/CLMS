/** 唯一打印版面：同一文档在独立打印与预览 iframe 中用真实 A4 几何排版。 */
import { html, raw } from '../core/html.js';
import { render, setVars } from '../core/dom.js';
import { bindEvents, defineActions } from '../core/events.js';

const payload = JSON.parse(document.getElementById('print-data').textContent);
const session = payload.session;
const source = document.getElementById('print-source');
const measureRoot = document.getElementById('print-measure');
const pagesRoot = document.getElementById('print-pages');
let withAnswers = payload.with_answers;
let layout = { pages: 0, item_pages: {} };
let ready = false;
const embedded = window.parent !== window;
let stopped = false; let initializeFrame = 0;
const items = new Map(session.items.map(item => [item.id, item]));

const markup = node => raw(node.outerHTML);
const rules = n => html`<div class="lines">${Array.from({ length: n }, () => html`<div></div>`)}</div>`;
const question = (block, count, continued = false, stem = block.stem) => html`
  <div class="q" data-item="${block.id}" data-no="${block.no}">
    ${continued ? html`<div class="q-continued">第 ${block.no} 题（续）</div>` : stem}${rules(count)}
  </div>`;

function height(content) {
  render(measureRoot, html`${content}`);
  const el = measureRoot.firstElementChild;
  const css = getComputedStyle(el);
  return el.getBoundingClientRect().height + parseFloat(css.marginTop) + parseFloat(css.marginBottom);
}

function textBlock(text, cls = '', genre = '') {
  return { kind: 'text', text, template: value => html`<div class="text ${genre}"><p class="${cls}">${value}</p></div>` };
}

function blocks() {
  const result = [];
  for (const child of source.children) {
    if (child.matches('header')) { result.push({ kind: 'fixed', content: markup(child) }); continue; }
    if (child.matches('.answers')) continue;
    for (const node of child.children) {
      if (node.matches('.text')) {
        for (const p of node.children) result.push(textBlock(p.textContent, p.className, node.classList.contains('poetry') ? 'poetry' : ''));
      } else if (node.matches('.q[data-item]')) {
        result.push({ kind: 'question', id: node.dataset.item, no: node.dataset.no,
          stem: markup(node.querySelector('.stem')), text: node.querySelector('.stem').textContent });
      } else {
        result.push({ kind: 'fixed', content: markup(node) });
      }
    }
  }
  if (withAnswers) {
    result.push({ kind: 'new-page' }, { kind: 'fixed', content: html`<h2>参考答案</h2>` });
    session.items.forEach((item, i) => result.push({ kind: 'text', text: `${i + 1}. ${item.answer || ''}`,
      template: value => html`<div class="answer-entry">${value}</div>` }));
  }
  return result;
}

/** 二分搜索能放下的文字片段；只以浏览器测得的真实高度判断，不估算字数或每行字数。 */
function fittingText(text, template, available) {
  const chars = Array.from(text);
  let low = 0; let high = chars.length;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (height(template(chars.slice(0, mid).join(''))) <= available + .1) low = mid;
    else high = mid - 1;
  }
  return [chars.slice(0, low).join(''), chars.slice(low).join('')];
}

function paginate() {
  if (stopped || !visible()) return layout;
  const capacity = height(html`<div class="print-content"></div>`);
  const pages = [[]]; const itemPages = {};
  let used = 0;
  const next = () => { if (pages.at(-1).length) pages.push([]); used = 0; };
  const add = (content, id = null) => {
    pages.at(-1).push(content); used += height(content);
    if (id) { itemPages[id] ||= []; if (!itemPages[id].includes(pages.length)) itemPages[id].push(pages.length); }
  };
  const available = () => capacity - used;

  function flowText(block, id = null) {
    let remaining = block.text;
    if (!remaining) { if (height(block.template('')) > available()) next(); add(block.template(''), id); return; }
    while (remaining) {
      const content = block.template(remaining);
      if (height(content) <= available() + .1) { add(content, id); break; }
      if (used && height(content) <= capacity) { next(); continue; }
      const [part, rest] = fittingText(remaining, block.template, available());
      if (!part) { if (!used) throw new Error('打印内容无法放进 A4 可用高度'); next(); continue; }
      add(block.template(part), id); remaining = rest;
      if (remaining) next();
    }
  }

  for (const block of blocks()) {
    if (block.kind === 'new-page') { next(); continue; }
    if (block.kind === 'text') { flowText(block); continue; }
    if (block.kind === 'fixed') {
      if (height(block.content) > available()) next();
      add(block.content); continue;
    }
    let count = Math.max(0, Number(items.get(block.id)?.blank_lines) || 0);
    const full = question(block, count);
    if (height(full) <= capacity && height(full) > available()) next();
    if (height(full) <= available() + .1) { add(full, block.id); continue; }

    let continued = false;
    if (height(question(block, 0)) > capacity) {
      flowText({ text: block.text, template: value => html`<div class="q" data-item="${block.id}"><div class="stem">${value}</div></div>` }, block.id);
      continued = true;
    }
    do {
      let low = 0; let high = count;
      while (low < high) {
        const mid = Math.ceil((low + high) / 2);
        if (height(question(block, mid, continued)) <= available() + .1) low = mid;
        else high = mid - 1;
      }
      if (!low && count > 0) { next(); continue; }
      add(question(block, low, continued), block.id);
      count -= low; continued = true;
      if (count) next();
    } while (count);
  }
  render(pagesRoot, html`${pages.map((page, i) => html`<article class="print-page" data-page="${i + 1}">
    <div class="print-content">${page}</div><footer class="print-page-number">${i + 1} / ${pages.length}</footer></article>`)}`);
  layout = { pages: pages.length, item_pages: itemPages };
  window.dispatchEvent(new CustomEvent('clms-print-layout', { detail: layout }));
  if (window.parent !== window) window.parent.postMessage({ type: 'clms-print-layout', session_id: session.id, layout }, location.origin);
  resize();
  return layout;
}

function visible() {
  if (!embedded) return true;
  const frame = window.frameElement;
  return Boolean(frame?.isConnected && frame.getClientRects().length && frame.getBoundingClientRect().width > 0);
}

function resize() {
  const page = pagesRoot.firstElementChild;
  if (!page) return;
  const width = page.offsetWidth;
  const scale = Math.min(1, Math.max(.1, (document.documentElement.clientWidth - 24) / width));
  setVars(pagesRoot, { '--print-scale': scale });
}

/** 与答题横线一致的宽度、字体、字号、行高与换行规则；不可见但参与真实布局。 */
function fitAnswer(id) {
  const item = items.get(id);
  if (!item || item.genre === 'dictation') return item?.blank_lines || 0;
  const answer = String(item.answer || '');
  if (!answer) return 0;
  render(measureRoot, html`<div class="answer-measure">${answer}</div>`);
  const el = measureRoot.firstElementChild;
  const css = getComputedStyle(el);
  const measuredHeight = el.getBoundingClientRect().height;
  const lineHeight = parseFloat(css.lineHeight);
  const count = Math.max(1, Math.ceil((measuredHeight - .1) / lineHeight));
  if (count > 1000) throw new Error('参考答案超过 1000 行，请先检查题目内容');
  return count;
}

window.clmsPrint = {
  get ready() { return ready; }, get layout() { return layout; },
  fitAnswer,
  setLines(changes) {
    Object.entries(changes).forEach(([id, value]) => { if (items.has(id)) items.get(id).blank_lines = value; });
    return paginate();
  },
  setAnswers(value) { withAnswers = Boolean(value); return paginate(); },
  print() { window.focus(); window.print(); },
};
bindEvents(document);
defineActions('paper', { print: () => window.clmsPrint.print() });
if (embedded) document.querySelector('.toolbar').hidden = true;
window.addEventListener('resize', resize);
window.addEventListener('beforeprint', () => { if (ready) paginate(); });
window.addEventListener('pagehide', () => { stopped = true; cancelAnimationFrame(initializeFrame); });
await document.fonts.ready;
function initialize() {
  if (stopped) return;
  if (!visible()) { initializeFrame = requestAnimationFrame(initialize); return; }
  paginate(); ready = true;
  if (embedded) window.parent.postMessage({ type: 'clms-print-ready', session_id: session.id, layout }, location.origin);
}
initialize();
