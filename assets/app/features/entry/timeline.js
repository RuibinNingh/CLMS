/**
 * 对话时间线（对标 Pi 交互界面的消息流）：草稿的 messages 是一串块，按顺序画出来。
 * - user：右侧气泡（图片、插话排队 / 没送达）。
 * - thinking：模型的思考，逐字出现；进行中展开，结束后收成一行预览，点开看全文。
 * - assistant：模型说的话，逐字出现（末尾有光标）。
 * - tool：一次工具调用。一行：状态、工具名、说明、摘要、用时；点开看「参数」（生成中逐字显示）和「结果」。
 *   delegate 的子代理卡片常显，每张卡点开是那个子代理自己的时间线（它的思考、说的话、工具调用）。
 * - run：一次执行的收尾：完成 / 停止 / 出错、轮数、工具次数、用时、改动芯片、回到修改前、重试。
 * - edit / system / ai（旧流程的一次性回复）照旧。
 * 展开状态在 ctx.open（Map：块 id → 是否展开，用户点过才有；没点过按默认）。
 * 模型说的话按 Markdown 渲染（core/markdown.js，先转义）。打开草稿之后新到的块带 is-enter（入场动效），
 * 打开时已有的块不带（ctx.known 是打开那一刻已有的块 id）。
 */
import { html, each } from '../../core/html.js';
import { formatTime } from '../../core/format.js';
import { icon } from '../../ui/icons.js';
import { genreShort } from '../../domain/genres.js';
import { markdown } from '../../core/markdown.js';

const LIVE = ['streaming', 'preparing', 'pending', 'running'];
const TASK_TEXT = { queued: '排队', running: '录入中', done: '完成', error: '失败', stopped: '已停止' };
const RUN_TEXT = { done: '完成', stopped: '已停止', error: '出错' };

export const isLive = b => LIVE.includes(b.status);
const isOpen = (ctx, id, def) => (ctx.open.has(id) ? ctx.open.get(id) : def);

export function seconds(from, to) {
  const a = Date.parse(from || ''); const b = to ? Date.parse(to) : Date.now();
  return Number.isFinite(a) && Number.isFinite(b) ? Math.max(0, Math.round((b - a) / 1000)) : 0;
}

export function pagesText(pages = []) {
  const p = [...pages].sort((a, b) => a - b);
  if (p.length > 1 && p.at(-1) - p[0] === p.length - 1) return `第 ${p[0]}–${p.at(-1)} 页`;
  return p.length ? `第 ${p.join('、')} 页` : '';
}

function pretty(text) {
  if (!text) return '';
  try { return JSON.stringify(JSON.parse(text), null, 2); } catch (_) { return text; }
}

export function changes(b, busy) {
  const list = b.changes || [];
  if (!list.length) return '';
  const shown = list.slice(0, 8);
  return html`<div class="msg__changes">
    ${each(shown, (c, i) => i, c => html`<button class="chip chip--info" data-action="entry.jump" data-arg="${c.gid}|${c.iid}">${c.label}</button>`)}
    ${list.length > shown.length ? html`<span class="chip">等 ${list.length} 处</span>` : ''}
    ${b.base_revision && !busy ? html`<button class="linkish" data-action="entry.restore" data-arg="${b.base_revision}">${icon('undo')}回到修改前</button>` : ''}
  </div>`;
}

function thinking(b, ctx) {
  const live = isLive(b);
  const open = isOpen(ctx, b.id, live);
  const text = b.text || '';
  return html`<div class="blk blk--thinking" data-status="${b.status || 'done'}">
    <button class="blk__head" data-action="entry.toggle" data-arg="${b.id}" aria-expanded="${String(open)}">
      <span class="blk__icon">${icon('spark')}</span><b class="${live ? 'shimmer' : ''}">${live ? '思考中' : '思考'}</b>
      <small>${live ? `${seconds(b.at)} 秒` : `${seconds(b.at, b.ended_at)} 秒`}</small>
      ${open ? '' : html`<span class="blk__peek">${text.replace(/\s+/g, ' ').slice(0, 80)}</span>`}
      <span class="blk__chev">${icon('chevron')}</span>
    </button>
    ${open ? html`<p class="blk__think">${text}${live ? html`<i class="caret"></i>` : ''}</p>` : ''}
  </div>`;
}

function taskCard(t, parent, ctx) {
  const key = `${parent.id}:${t.n}`;
  const kids = (ctx.children.get(parent.id) || []).filter(x => x.task === t.n);
  const open = isOpen(ctx, key, false);
  return html`<li class="task" data-status="${t.status}" data-genre="${t.genre}" data-key="${key}">
    <button class="task__head" data-action="entry.toggle" data-arg="${key}" aria-expanded="${String(open)}" ${kids.length ? '' : html`disabled`}>
      <span class="blk__chev">${icon('chevron')}</span><span class="genre-dot"></span><b>${genreShort(t.genre)}${t.title ? `《${t.title}》` : ''}</b>
      <span class="task__pages">${pagesText(t.pages)}</span>
      <small>${TASK_TEXT[t.status] || t.status}${t.tools ? ` · ${t.tools} 次工具` : ''}${t.status === 'running' && t.last ? ` · ${t.last}` : ''}${t.error ? ` · ${t.error}` : ''}</small>
    </button>
    ${open ? html`<ol class="task__log">${each(kids, x => x.id, x => block(x, ctx))}</ol>` : ''}
  </li>`;
}

function tool(b, ctx) {
  const live = isLive(b);
  const open = isOpen(ctx, b.id, false);
  const took = b.started_at ? seconds(b.started_at, b.ended_at) : 0;
  const mark = b.status === 'done' ? icon('check') : b.status === 'error' ? icon('close') : '';
  const args = b.args_text || '';
  return html`<div class="blk blk--tool" data-status="${b.status}" data-tool="${b.name}">
    <button class="blk__head" data-action="entry.toggle" data-arg="${b.id}" aria-expanded="${String(open)}">
      <span class="blk__mark">${mark}</span><code>${b.name}</code>
      <span class="blk__label">${b.label && b.label !== b.name ? b.label : ''}</span>
      <small class="${live ? 'shimmer' : ''}">${b.status === 'preparing' ? `生成参数 · ${args.length} 字` : b.status === 'pending' ? '等待执行'
        : live ? `执行中 ${took} 秒` : `${b.summary || ''}${took ? ` · ${took} 秒` : ''}`}</small>
      <span class="blk__chev">${icon('chevron')}</span>
    </button>
    ${b.tasks?.length ? html`<ol class="tasks">${each(b.tasks, t => t.n, t => taskCard(t, b, ctx))}</ol>` : ''}
    ${open || b.status === 'preparing' ? html`<div class="blk__io">
      <p class="blk__io-lab">参数</p><pre class="blk__pre">${b.status === 'preparing' ? args.slice(-600) : pretty(args) || '{}'}</pre>
      ${b.result ? html`<p class="blk__io-lab">结果</p><pre class="blk__pre">${pretty(b.result)}</pre>` : ''}
    </div>` : ''}
  </div>`;
}

function runEnd(b, ctx) {
  const stats = [b.turns ? `${b.turns} 轮` : '', b.tool_calls ? `${b.tool_calls} 次工具调用` : '', b.seconds ? `${b.seconds} 秒` : '']
    .filter(Boolean).join(' · ');
  return html`<div class="blk blk--run" data-status="${b.status}">
    <div class="blk__runline"><span class="blk__mark">${b.status === 'done' ? icon('check') : icon('close')}</span>
      <b>${RUN_TEXT[b.status] || b.status}</b><small>${stats}</small></div>
    ${b.text && b.status === 'error' ? html`<p class="blk__err">${b.text}</p>` : ''}
    ${changes(b, ctx.busy)}
    ${b.status === 'error' && ctx.last === b.id && ctx.canRetry ? html`<button class="btn btn--sm" data-action="entry.retry">${icon('retry')}重试</button>` : ''}
  </div>`;
}

function user(b) {
  const time = b.queued ? '排队中 · AI 下一步会读到' : b.dropped ? '已停止，没有送达' : formatTime(b.at);
  return html`<div class="msg msg--user ${b.queued ? 'is-queued' : ''} ${b.dropped ? 'is-dropped' : ''}">
    ${b.images?.length ? html`<div class="msg__imgs">${each(b.images, x => x, x => html`
      <button class="msg__img" data-action="entry.pane" data-arg="image" title="看原图"><img src="/api/image?id=${x}" alt="图片"></button>`)}</div>` : ''}
    ${b.text ? html`<div class="bubble"><p class="msg__text">${b.text}</p></div>` : ''}<time>${time}</time></div>`;
}

function legacy(b, ctx) {
  if (b.role === 'edit') {
    const labels = (b.changes || []).map(c => c.label);
    const text = labels.length ? `${b.text}：${labels.slice(0, 4).join('、')}${labels.length > 4 ? ` 等 ${labels.length} 处` : ''}` : b.text;
    const undo = b.base_revision && !ctx.busy && !ctx.done && b.revision === ctx.revision
      ? html`<button class="linkish" data-action="entry.restore" data-arg="${b.base_revision}">${icon('undo')}撤销</button>` : '';
    return html`<div class="msg msg--note"><span>${text}</span>${undo}<time>${formatTime(b.at)}</time></div>`;
  }
  if (b.role === 'system') return html`<div class="msg msg--done">${icon('check')}<span>${b.text}</span><time>${formatTime(b.at)}</time></div>`;
  return html`<div class="msg msg--ai ${b.error ? 'msg--error' : ''}"><div class="bubble"><div class="msg__text md">${markdown(b.text)}</div>
    ${b.notes ? html`<p class="msg__notes"><b>拿不准的地方</b>${b.notes}</p>` : ''}${changes(b, ctx.busy || ctx.done)}
    ${b.error && ctx.last === b.id && ctx.canRetry ? html`<button class="btn btn--sm" data-action="entry.retry">${icon('retry')}重试</button>` : ''}
  </div><time>${formatTime(b.at)}</time></div>`;
}

function block(b, ctx) {
  const body = { thinking, tool, run: runEnd, user }[b.role];
  const enter = ctx.known && !ctx.known.has(b.id) ? 'is-enter' : '';
  if (b.role === 'assistant') {
    return html`<li class="tl__item ${enter}" data-key="${b.id}" data-role="assistant"><div class="blk blk--text md ${isLive(b) ? 'is-live' : ''}">${markdown(b.text)}</div></li>`;
  }
  return html`<li class="tl__item ${enter}" data-key="${b.id}" data-role="${b.role}">${body ? body(b, ctx) : legacy(b, ctx)}</li>`;
}

/** 顶层时间线；子代理的块（有 parent）收在对应的 delegate 卡片里。 */
export function renderTimeline(draft, ctx) {
  const all = draft.messages || [];
  const children = new Map();
  all.forEach(m => { if (m.parent) { if (!children.has(m.parent)) children.set(m.parent, []); children.get(m.parent).push(m); } });
  const top = all.filter(m => !m.parent);
  const c = { ...ctx, children, last: top.at(-1)?.id };
  return each(top, m => m.id, m => block(m, c));
}
