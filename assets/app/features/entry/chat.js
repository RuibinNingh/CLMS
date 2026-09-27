/**
 * 对话栏：用户消息（可带图片缩略图、插话排队标记）、AI 回复（Agent 模式是执行记录，见 run.js；旧模式是一次性回复）、
 * 手动修改记录、处理中指示，以及底部输入框（Enter 发送、Shift+Enter 换行、附原图 / 附图、快捷指令、停止）。
 * Agent 模式下 AI 执行时也能继续发话（插话，下一轮读到）；已入库的草稿也能继续聊（查改题库、记复习反馈）。
 */
import { html, each } from '../../core/html.js';
import { formatTime } from '../../core/format.js';
import { icon } from '../../ui/icons.js';
import { changes, renderRun } from './run.js';

const BUSY_TEXT = {
  queued: '排队中，前面还有图片在识别…',
  extracting: '正在读图：拆分原文和小题、判断题型、估计留白…',
  thinking: '正在按你说的修改…',
};

export const SUGGESTIONS = [
  { label: '核对原文错字', text: '对照原图逐字核对原文，改掉识别错的字，其它不动。' },
  { label: '答案按采分点重写', text: '把没有分条的答案按采分点重写，每条一个要点，与分值匹配。' },
  { label: '重判题型', text: '重新判断每道小题的题型，只改判断错的。' },
  { label: '按分值调留白', text: '按分值和答案长度重新估计每道题的留白行数。' },
];

export const CHAT_SUGGESTIONS = [
  { label: '反复出错的题', text: '查一下题库里的顽固题和又错过的题，按板块列出来，说说共同的问题。' },
  { label: '补记复习', text: '我今天复习了题库里的一道题，帮我补记一条复习记录：' },
  { label: '改题库里的题', text: '帮我改题库里的一道题：' },
];

function message(msg, i, ctx) {
  const time = html`<time>${msg.queued ? '排队中 · AI 下一步会读到' : msg.dropped ? '已停止，没有送达' : formatTime(msg.at)}</time>`;
  if (msg.role === 'user') {
    return html`<li class="msg msg--user ${msg.queued ? 'is-queued' : ''} ${msg.dropped ? 'is-dropped' : ''}" data-key="m${i}">
      ${msg.images?.length ? html`<div class="msg__imgs">${each(msg.images, x => x, x => html`
        <button class="msg__img" data-action="entry.pane" data-arg="image" title="看原图"><img src="/api/image?id=${x}" alt="上传的图片"></button>`)}</div>` : ''}
      ${msg.text ? html`<div class="bubble"><p class="msg__text">${msg.text}</p></div>` : ''}${time}</li>`;
  }
  if (msg.role === 'ai' && msg.run) return renderRun(msg, i, ctx);
  if (msg.role === 'edit') {
    const labels = (msg.changes || []).map(c => c.label);
    const text = labels.length ? `${msg.text}：${labels.slice(0, 4).join('、')}${labels.length > 4 ? ` 等 ${labels.length} 处` : ''}` : msg.text;
    const undo = msg.base_revision && !ctx.busy && !ctx.done && msg.revision === ctx.revision
      ? html`<button class="linkish" data-action="entry.restore" data-arg="${msg.base_revision}">${icon('undo')}撤销</button>` : '';
    return html`<li class="msg msg--note" data-key="m${i}"><span>${text}</span>${undo}${time}</li>`;
  }
  if (msg.role === 'system') {
    return html`<li class="msg msg--done" data-key="m${i}">${icon('check')}<span>${msg.text}</span>${time}</li>`;
  }
  const last = i === ctx.count - 1;
  return html`<li class="msg msg--ai ${msg.error ? 'msg--error' : ''}" data-key="m${i}">
    <div class="bubble"><p class="msg__text">${msg.text}</p>
      ${msg.notes ? html`<p class="msg__notes"><b>拿不准的地方</b>${msg.notes}</p>` : ''}
      ${changes(msg, ctx.busy || ctx.done)}
      ${msg.error && last && ctx.canRetry ? html`<button class="btn btn--sm" data-action="entry.retry">${icon('retry')}重试</button>` : ''}
    </div>${time}</li>`;
}

function renderActivity(draft, busy) {
  const activity = draft.activity;
  if (!activity?.steps?.length) {
    return busy ? html`<li class="msg msg--ai msg--busy" data-key="busy"><div class="bubble"><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>${BUSY_TEXT[draft.status]}</div></li>` : '';
  }
  const started = Date.parse(activity.started_at);
  const ended = Date.parse(activity.finished_at || '') || Date.now();
  const elapsed = Number.isFinite(started) ? Math.max(0, Math.floor((ended - started) / 1000)) : 0;
  const state = busy ? 'running' : draft.status === 'error' ? 'error' : 'done';
  const heading = busy ? '思考与执行中' : state === 'error' ? '执行中断' : '执行完成';
  const kindName = { queue: '排队', local: '本地处理', model: '模型请求' };
  return html`<li class="msg msg--ai msg--activity" data-key="activity">
    <div class="activity" data-state="${state}" aria-label="本次 AI 执行步骤">
      <div class="activity__head">
        <span class="activity__beacon" aria-hidden="true"></span>
        <strong>${heading}</strong>
        <span class="activity__time">${elapsed} 秒</span>
      </div>
      <ol class="activity__steps">${each(activity.steps, step => step.id, step => html`
        <li class="activity__step" data-status="${step.status}" data-kind="${step.kind}">
          <span class="activity__mark" aria-hidden="true">${step.status === 'done' ? icon('check') : ''}</span>
          <span class="activity__label">${step.label}</span>
          <small>${kindName[step.kind] || '执行'}</small>
        </li>`)}</ol>
      ${busy && activity.steps.at(-1)?.kind === 'model' ? html`<p class="activity__note">模型正在分析并生成草稿，完成后会显示结果。</p>` : ''}
    </div>
  </li>`;
}

function composer(draft, s, ctx) {
  const agent = Boolean(draft.agent);
  const legacyLocked = ctx.busy || ctx.done || !draft.revision;
  if (!agent && ctx.done) return html`<p class="composer__done">这份已经入库。继续上传下一张，或去题库查看。</p>`;
  const locked = agent ? false : legacyLocked;
  const chips = draft.revision && !ctx.done ? SUGGESTIONS : agent ? CHAT_SUGGESTIONS : [];
  const placeholder = locked ? '等 AI 处理完再说…'
    : ctx.busy ? 'AI 正在执行，可以补充要求（下一步就会读到）'
      : ctx.done ? '已入库。还可以让 AI 查题库、改题、补记复习、记反馈…'
        : draft.revision ? '例如：第 7 题答案太简略，按 6 分重写；第 8 题题型应该是表达技巧题' : '想让 AI 做什么？可以附图';
  const canSend = !locked && (s.composer.trim() || s.attach.length);
  return html`
    ${chips.length ? html`<div class="composer__chips">${each(chips, x => x.label, x => html`
      <button class="chip" data-action="entry.suggest" data-arg="${x.text}" ${locked ? html`disabled` : ''}>${x.label}</button>`)}</div>` : ''}
    <div class="composer__box">
      ${s.attach.length ? html`<div class="composer__attach">${each(s.attach, (_, n) => n, (a, n) => html`
        <span class="attach"><img src="${a.data}" alt="${a.name}"><button class="attach__x" data-action="entry.unattach" data-arg="${n}" aria-label="移除这张图">${icon('close')}</button></span>`)}</div>` : ''}
      <textarea id="composer" rows="2" data-input="entry.composer" data-autosize placeholder="${placeholder}"
        aria-label="给 AI 的话" ${locked ? html`disabled` : ''}>${s.composer}</textarea>
      <div class="composer__row">
        <span class="composer__tools">
          ${draft.images?.length && !ctx.busy ? html`<button class="chip ${s.withImage ? 'chip--info' : ''}" data-action="entry.withImage" aria-pressed="${String(s.withImage)}"
            title="发送时附上原图，AI 可以对照原图核对">${icon('image')}附原图</button>` : ''}
          ${agent ? html`<label class="chip composer__file" title="附一张图发给 AI（例如做完的复习卷）">${icon('upload')}附图
            <input type="file" accept="image/*" multiple class="visually-hidden" data-change="entry.attach"></label>` : ''}
        </span>
        ${agent && ctx.busy ? html`<button class="btn btn--sm" data-action="entry.stop">${icon('close')}停止</button>` : ''}
        <button class="btn btn--primary btn--sm" data-action="entry.send" ${canSend ? '' : html`disabled`}>${icon('send')}${agent && ctx.busy ? '插话' : '发送'}</button>
      </div>
    </div>`;
}

export function renderChat(draft, s) {
  const busy = ['queued', 'extracting', 'thinking'].includes(draft.status);
  const done = draft.status === 'committed' || Boolean(draft.committed && busy);
  const msgs = draft.messages || [];
  const ctx = { busy, done, count: msgs.length, canRetry: draft.can_retry, revision: draft.revision, runLog: s.runLog };
  const running = msgs.some(m => m.status === 'running');
  const legacy = !draft.agent || !msgs.some(m => m.run);
  const activity = legacy ? busy || (draft.activity && msgs.at(-1)?.role === 'ai' && !msgs.at(-1)?.run) : busy && !running;
  return html`
  <section class="chat" aria-label="对话">
    <ol class="chat__log" id="chat-log" aria-live="polite">
      ${msgs.length ? '' : html`<li class="msg msg--note" data-key="hello"><span>${draft.kind === 'chat'
        ? '这是一段空白对话：可以让 AI 查改题库、增删改查复习记录、对着作答照片批改；让它录题的话，题会出现在右侧草稿里。' : ''}</span></li>`}
      ${each(msgs, (_, i) => `m${i}`, (m, i) => message(m, i, ctx))}
      ${activity ? renderActivity(draft, busy) : ''}
    </ol>
    <div class="composer ${!draft.agent && (busy || done || !draft.revision) ? 'is-locked' : ''}">${composer(draft, s, ctx)}</div>
  </section>`;
}
