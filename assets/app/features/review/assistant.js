/**
 * 复习助手面板（评分页右侧；≤ 1160 是浮动面板）：跟着正在看的题，一题一段对话（存在模块级 Map，切页面不丢、刷新清空）。
 * 一条回答按块画出来：思考（进行中展开、逐字；结束收成一行，点开看全文）、查阅（工具调用：看第几题、读哪几段，
 * 点开看查到的内容）、正文（Markdown，「【建议】」之后的内容流式期间隐藏）、建议卡片（采用 / 只填反馈）、用量。
 * 输入框上方是引用（在卷面上选中文字 →「引用」）和作答照片。动作在 assistant-actions.js。
 */
import { html, each } from '../../core/html.js';
import { markdown } from '../../core/markdown.js';
import { icon } from '../../ui/icons.js';
import { genreShort, gradesFor } from '../../domain/genres.js';
import { focusTarget } from './focus.js';

export const chats = new Map();
export const MARK = '【建议】';
export const keyOf = (s, id) => `${s.session.id}:${id}`;
export const chatOf = (s, id) => chats.get(keyOf(s, id)) || [];
const QUICK = [['怎么答', '这道题该从哪几个方面答？'], ['差在哪', '我的答案和参考答案差在哪？']];
const TOOL_NAME = { review_outline: '看题目清单', question_get: '看题目', material_read: '读原文', item_history: '查以前的复习' };
const LIVE = ['live', 'preparing', 'running'];

const secondsOf = b => Math.max(1, Math.round(((b.ended || Date.now()) - b.at) / 1000));
const isOpen = (s, key, def) => (s.open.has(key) ? s.open.get(key) : def);
const tokens = n => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

function thinking(m, b, s) {
  const live = b.status === 'live';
  const key = `${m.id}:${b.id}`;
  const open = isOpen(s, key, live);
  return html`<div class="ai-think" data-status="${live ? 'live' : 'done'}">
    <button class="ai-think__head" data-action="rv.aiFold" data-arg="${key}" aria-expanded="${String(open)}">
      <span class="ai-think__icon">${icon('spark')}</span><b class="${live ? 'shimmer' : ''}">${live ? '思考中' : '思考'}</b><small>${secondsOf(b)} 秒</small>
      ${open ? '' : html`<span class="ai-think__peek">${b.text.replace(/\s+/g, ' ').slice(0, 60)}</span>`}
      <span class="ai-fold">${icon('chevron')}</span>
    </button>
    ${open ? html`<p class="ai-think__body">${b.text}</p>` : ''}
  </div>`;
}

function tool(m, b, s) {
  const live = LIVE.includes(b.status);
  const key = `${m.id}:${b.id}`;
  const open = isOpen(s, key, false) && Boolean(b.result);
  const mark = b.status === 'done' ? icon('check') : b.status === 'error' ? icon('close') : '';
  return html`<div class="ai-tool" data-status="${b.status}" data-tool="${b.name}">
    <button class="ai-tool__head" data-action="rv.aiFold" data-arg="${key}" aria-expanded="${String(open)}" ${b.result ? '' : html`disabled`}>
      <span class="ai-tool__mark">${mark}</span><span class="ai-tool__label">${b.label || TOOL_NAME[b.name] || b.name}</span>
      <small class="${live ? 'shimmer' : ''}">${live ? '查阅中' : b.summary || ''}</small>
      ${b.result ? html`<span class="ai-fold">${icon('chevron')}</span>` : ''}
    </button>
    ${open ? html`<pre class="ai-tool__out">${b.result}</pre>` : ''}
  </div>`;
}

function text(m, b, last) {
  const shown = b.text.split(MARK)[0];
  if (!shown.trim()) return '';
  return html`<div class="md ai-text ${m.status === 'streaming' && last ? 'is-live' : ''}">${markdown(shown)}</div>`;
}

const hintOf = (genre, value) => (gradesFor(genre).find(g => g.value === value) || {}).hint || '';

function suggestion(m, it) {
  const sug = m.suggestion;
  if (!sug) return '';
  const hasGrade = sug.grade !== undefined;
  return html`<div class="ai-sug" data-grade="${hasGrade ? sug.grade : ''}">
    <p class="ai-sug__head"><small>${hasGrade ? '建议评分' : '建议反馈'}</small>
      ${hasGrade ? html`<b>${sug.grade_label}</b><span>${hintOf(it.genre, sug.grade)}</span>` : ''}</p>
    ${sug.note ? html`<p class="ai-sug__note">${sug.note}</p>` : ''}
    ${m.adopted ? html`<p class="ai-sug__done">${icon('check')}${m.adopted}</p>` : html`<div class="ai-sug__acts">
      ${hasGrade ? html`<button class="btn btn--sm btn--primary" data-action="rv.aiAdopt" data-arg="${m.id}:all">${sug.note ? '采用评分和反馈' : '采用这个评分'}</button>` : ''}
      ${sug.note ? html`<button class="btn btn--sm" data-action="rv.aiAdopt" data-arg="${m.id}:note"
        title="${it.grade ? '改写这次记录的反馈' : '先填进反馈，评分时一起写入'}">${hasGrade ? '只填反馈' : '填入反馈'}</button>` : ''}
    </div>`}
  </div>`;
}

function meta(m) {
  if (m.status !== 'done') return '';
  const parts = [];
  if (m.tools) parts.push(`查阅 ${m.tools} 次`);
  if (m.seconds) parts.push(`${m.seconds} 秒`);
  const total = (m.usage?.input || 0) + (m.usage?.output || 0);
  if (total) parts.push(`${m.usage.estimated ? '约 ' : ''}${tokens(total)} token`);
  return parts.length ? html`<p class="ai-meta">${parts.join(' · ')}</p>` : '';
}

function botMsg(m, it, s) {
  const blocks = m.blocks || [];
  const lastText = blocks.map(b => b.kind).lastIndexOf('text');
  const waiting = m.status === 'streaming' && !blocks.some(b => LIVE.includes(b.status));
  return html`<div class="ai__msg ai__msg--bot" data-key="${m.id}" data-status="${m.status}">
    ${each(blocks, b => b.id, (b, i) => (b.kind === 'thinking' ? thinking(m, b, s) : b.kind === 'tool' ? tool(m, b, s) : text(m, b, i === lastText)))}
    ${waiting ? html`<p class="shimmer ai-wait">${blocks.length ? '整理回答…' : '正在看题…'}</p>` : ''}
    ${m.status === 'error' ? html`<p class="callout callout--bad ai-err">${m.error}
      <button class="linkish" data-action="rv.aiRetry" data-arg="${m.id}">重试</button></p>` : ''}
    ${m.status === 'stopped' ? html`<p class="ai-meta">已停止</p>` : ''}
    ${suggestion(m, it)}${meta(m)}
  </div>`;
}

const quotes = refs => html`<div class="ai-quotes">${each(refs, (_, i) => i, r => html`<blockquote class="ai-quote"><small>${r.label}</small><p>${r.text}</p></blockquote>`)}</div>`;

function userMsg(m) {
  const pics = m.images?.length ? m.images.map(id => `/api/image?id=${encodeURIComponent(id)}`) : m.previews || [];
  return html`<div class="ai__msg ai__msg--user" data-key="${m.id}">
    ${m.refs?.length ? quotes(m.refs) : ''}
    ${pics.length ? html`<div class="ai__thumbs">${each(pics, (_, i) => i, src => html`<img src="${src}" alt="作答照片">`)}</div>` : ''}
    ${m.text ? html`<p class="ai__bubble">${m.text}</p>` : ''}
  </div>`;
}

const empty = it => html`<div class="ai__empty">
  <p>对着这道题随便问：思路、采分点、你的答案哪里不够。助手会自己去查题目和原文，只读需要的部分。</p>
  <p>把作答打出来或拍照发来，点「打分」对照采分点给建议；点「写反馈」生成一句复习反馈。建议要点「采用」才会记下。</p>
  ${it.material_id ? html`<p>在卷面上选中一段文字，可以把它「引用」到这里来问。</p>` : ''}
</div>`;

function composer(s, busy, off) {
  const a = s.ai;
  return html`<div class="ai__composer">
    <div class="ai__box">
      ${a.refs.length ? html`<div class="ai-refs">${each(a.refs, (_, i) => i, (r, i) => html`<span class="ai-ref">
        <span class="ai-ref__where">${icon('quote')}${r.label}</span><span class="ai-ref__text">${r.text}</span>
        <button class="ai-ref__x" data-action="rv.aiUnref" data-arg="${i}" aria-label="去掉这段引用">${icon('close')}</button></span>`)}</div>` : ''}
      ${a.attach.length ? html`<div class="ai__thumbs ai__thumbs--attach">${each(a.attach, (_, i) => i, (x, i) => html`<span class="ai__att">
        <img src="${x.data}" alt="${x.name}"><button class="ai-ref__x" data-action="rv.aiUnattach" data-arg="${i}" aria-label="去掉这张">${icon('close')}</button></span>`)}</div>` : ''}
      <textarea id="ai-composer" class="ai__input" rows="2" data-input="rv.aiText" aria-label="问复习助手"
        placeholder="问这道题，或写下你的作答（回车发送，Shift+回车换行）">${a.text}</textarea>
      <div class="ai__bar">
        <label class="btn btn--ghost btn--sm ai__pic" title="拍照或选图：你的作答">${icon('image')}作答照片
          <input type="file" accept="image/*" multiple class="visually-hidden" data-change="rv.aiAttach"></label>
        ${busy ? html`<button class="btn btn--sm" data-action="rv.aiStop">停止</button>`
    : html`<button class="btn btn--sm btn--primary ai__send" data-action="rv.aiSend" ${off}>${icon('send')}发送</button>`}
      </div>
    </div>
  </div>`;
}

export function assistant(s) {
  const t = focusTarget(s);
  if (!t) return html`<aside class="ai" id="rv-ai" aria-label="复习助手"><p class="empty">选一道题开始</p></aside>`;
  const { it, n } = t;
  const log = chatOf(s, it.id);
  const busy = s.ai.busy === keyOf(s, it.id);
  const off = s.ai.busy ? html`disabled` : '';
  const kind = it.genre === 'dictation' ? '默写' : it.qtype || genreShort(it.genre);
  return html`<aside class="ai" id="rv-ai" aria-label="复习助手" data-genre="${it.genre}">
    <header class="ai__head">
      <span class="ai__title">${icon('spark')}复习助手</span>
      <span class="ai__target"><span class="genre-dot"></span>第 ${n} 题 · ${kind}</span>
      <button class="btn btn--ghost btn--icon ai__close" data-action="rv.aiToggle" aria-label="收起复习助手">${icon('close')}</button>
    </header>
    <div class="ai__log" id="ai-log" aria-live="polite">${log.length ? each(log, m => m.id, m => (m.role === 'user' ? userMsg(m) : botMsg(m, it, s))) : empty(it)}</div>
    <div class="ai__quick" role="group" aria-label="快捷提问">
      <button class="chip chip--info" data-action="rv.aiMode" data-arg="grade" ${off} title="对照参考答案的采分点给出评分建议">${icon('check')}打分</button>
      <button class="chip chip--info" data-action="rv.aiMode" data-arg="feedback" ${off} title="写一句复习反馈：错在哪、漏了哪个采分点">写反馈</button>
      ${each(QUICK, q => q[0], q => html`<button class="chip" data-action="rv.aiAsk" data-arg="${q[1]}" ${off}>${q[0]}</button>`)}
    </div>
    ${composer(s, busy, off)}
  </aside>`;
}
