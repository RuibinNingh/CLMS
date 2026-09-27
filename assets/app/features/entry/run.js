/**
 * Agent 执行记录（对标 Pi 的工具调用流）：一条 AI 消息 = 一次 run 的一段。
 * 模型的每次工具调用一行（进行中 / 完成 / 出错 / 已停止），模型中途说的话穿插其中；
 * delegate 展开成子代理卡片（板块、页码、状态、工具次数、正在做什么）。最终回复、改动芯片、「回到修改前」在下面。
 * 「执行过程」进行中默认展开、完成后收起；用户点过就按用户的来（s.runLog）。
 */
import { html, each } from '../../core/html.js';
import { icon } from '../../ui/icons.js';
import { genreShort } from '../../domain/genres.js';

const TASK_TEXT = { queued: '排队', running: '录入中', done: '完成', error: '失败', stopped: '已停止' };
const GENRE_CODE = { 现代文阅读: 'modern', 文言文阅读: 'classical', 古代诗歌阅读: 'poetry', 名句默写: 'dictation' };

export function pagesText(pages = []) {
  const p = [...pages].sort((a, b) => a - b);
  if (p.length > 1 && p.at(-1) - p[0] === p.length - 1) return `第 ${p[0]}–${p.at(-1)} 页`;
  return p.length ? `第 ${p.join('、')} 页` : '';
}

export function changes(msg, busy) {
  const list = msg.changes || [];
  if (!list.length) return '';
  const shown = list.slice(0, 8);
  return html`<div class="msg__changes">
    ${each(shown, (c, i) => i, c => html`<button class="chip chip--info" data-action="entry.jump" data-arg="${c.gid}|${c.iid}">${c.label}</button>`)}
    ${list.length > shown.length ? html`<span class="chip">等 ${list.length} 处</span>` : ''}
    ${msg.base_revision && !busy ? html`<button class="linkish" data-action="entry.restore" data-arg="${msg.base_revision}">${icon('undo')}回到修改前</button>` : ''}
  </div>`;
}

function task(t) {
  const genre = GENRE_CODE[t.genre] || t.genre;
  return html`<li class="run__task" data-status="${t.status}" data-genre="${genre}">
    <span class="genre-dot"></span>
    <b>${genreShort(genre)}${t.title ? `《${t.title}》` : ''}</b>
    <span class="run__pages">${pagesText(t.pages)}</span>
    <small>${TASK_TEXT[t.status] || t.status}${t.tools ? ` · ${t.tools} 次工具调用` : ''}${t.status === 'running' && t.last ? ` · ${t.last}` : ''}${t.error ? ` · ${t.error}` : ''}</small>
  </li>`;
}

function step(x, n) {
  if (x.type === 'say') return html`<li class="run__say" data-key="s${n}">${x.text}</li>`;
  return html`<li class="run__step" data-status="${x.status}" data-key="s${n}">
    <span class="run__mark" aria-hidden="true">${x.status === 'done' ? icon('check') : x.status === 'error' ? icon('close') : ''}</span>
    <span class="run__label">${x.label || x.name}</span>
    ${x.summary && x.status !== 'running' ? html`<small class="run__sum">${x.summary}</small>` : ''}
    ${x.tasks?.length ? html`<ol class="run__tasks">${each(x.tasks, t => t.n, task)}</ol>` : ''}
  </li>`;
}

export function renderRun(msg, i, ctx) {
  const running = msg.status === 'running';
  const steps = msg.steps || [];
  const key = `${msg.run}:${i}`;
  const open = ctx.runLog.has(key) ? ctx.runLog.get(key) : running;
  const tools = steps.filter(x => x.type === 'tool').length;
  const head = running ? `执行中 · 第 ${msg.turn || 1} 轮` : msg.status === 'stopped' ? '已停止' : msg.status === 'error' ? '执行出错' : '执行过程';
  return html`<li class="msg msg--ai msg--run ${msg.error ? 'msg--error' : ''}" data-key="m${i}">
    <div class="run" data-state="${msg.status || 'done'}">
      ${steps.length || running ? html`<div class="run__log">
        <button class="run__head" data-action="entry.runlog" data-arg="${key}" aria-expanded="${String(open)}">
          <span class="run__beacon" aria-hidden="true"></span><strong>${head}</strong>
          <span class="run__count">${tools ? `${tools} 次工具调用` : ''}</span></button>
        ${open && steps.length ? html`<ol class="run__steps">${each(steps, (_, n) => `s${n}`, step)}</ol>` : ''}
        ${running && !steps.length ? html`<p class="run__wait"><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>模型在看题、决定下一步…</p>` : ''}
      </div>` : ''}
      ${msg.text ? html`<div class="bubble"><p class="msg__text">${msg.text}</p>
        ${changes(msg, ctx.busy)}
        ${msg.error && i === ctx.count - 1 && ctx.canRetry ? html`<button class="btn btn--sm" data-action="entry.retry">${icon('retry')}重试</button>` : ''}
      </div>` : (msg.changes?.length ? html`<div class="bubble">${changes(msg, ctx.busy)}</div>` : '')}
    </div></li>`;
}
