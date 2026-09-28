/**
 * 对话栏：顶部状态条（标题、状态、执行计时、停止、记录抽屉开关）、时间线（timeline.js）、输入框。
 * Agent 模式：执行中输入框照样能用（插话，下一轮读到）；已入库的草稿也能继续聊；可附图、在输入框里粘贴截图。
 * 旧流程（关掉 Agent 模式）：一次性回复，处理中显示 activity 步骤卡，执行时锁住输入框。
 */
import { html, each } from '../../core/html.js';
import { icon } from '../../ui/icons.js';
import { isLive, renderTimeline, seconds } from './timeline.js';
import { renderGauge } from './gauge.js';

export const BUSY = ['queued', 'extracting', 'thinking'];
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
const STATUS_TEXT = { queued: '排队中', extracting: '识别中', thinking: 'AI 执行中', ready: '可编辑', error: '出错了', committed: '已入库' };

function renderActivity(draft, busy) {
  const activity = draft.activity;
  if (!activity?.steps?.length) return '';
  const state = busy ? 'running' : draft.status === 'error' ? 'error' : 'done';
  const kindName = { queue: '排队', local: '本地处理', model: '模型请求' };
  return html`<li class="tl__item" data-key="activity"><div class="activity" data-state="${state}">
    <div class="activity__head"><span class="activity__beacon"></span><strong>${busy ? '执行中' : state === 'error' ? '执行中断' : '执行完成'}</strong>
      <span class="activity__time">${seconds(activity.started_at, activity.finished_at)} 秒</span></div>
    <ol class="activity__steps">${each(activity.steps, x => x.id, x => html`<li class="activity__step" data-status="${x.status}">
      <span class="activity__mark">${x.status === 'done' ? icon('check') : ''}</span><span>${x.label}</span><small>${kindName[x.kind] || '执行'}</small></li>`)}</ol>
  </div></li>`;
}

function liveTail(draft) {
  const top = (draft.messages || []).filter(m => !m.parent);
  const last = top.at(-1);
  if (last && isLive(last)) return '';
  const since = draft.running?.started_at;
  const first = !top.some(m => m.role === 'thinking' || m.role === 'tool' || m.role === 'assistant');
  const text = draft.status === 'queued' ? '排队等待处理位'
    : first && draft.pages?.length ? `AI 正在读 ${draft.pages.length} 页图` : last?.role === 'tool' ? '看完工具结果，想下一步' : 'AI 正在组织回答';
  return html`<li class="tl__item tl__live is-enter" data-key="live"><span class="dots"><i></i><i></i><i></i></span><span class="shimmer">${text}</span>${since ? html`<small>${seconds(since)} 秒</small>` : ''}</li>`;
}

function head(draft, busy) {
  return html`<div class="chat__head">
    <button class="btn btn--ghost btn--icon btn--sm hist-toggle" data-action="entry.hist" aria-label="录入记录" title="录入记录">${icon('panel')}</button>
    <b class="chat__title" title="${draft.title}">${draft.title || '未命名'}</b>
    <span class="pill" data-tone="${busy ? 'wait' : draft.status}">${busy && draft.running ? `执行中 · ${seconds(draft.running.started_at)} 秒` : STATUS_TEXT[draft.status] || draft.status}</span>
    ${busy && draft.agent ? html`<button class="btn btn--sm" data-action="entry.stop">${icon('close')}停止</button>` : ''}
  </div>`;
}

function composer(draft, s, ctx) {
  const agent = Boolean(draft.agent);
  if (!agent && ctx.done) return html`<p class="composer__done">这份已经入库。继续上传下一份，或去题库查看。</p>`;
  const locked = agent ? false : ctx.busy || ctx.done || !draft.revision;
  const chips = draft.revision && !ctx.done ? SUGGESTIONS : agent ? CHAT_SUGGESTIONS : [];
  const placeholder = locked ? '等 AI 处理完再说…'
    : ctx.busy ? 'AI 正在执行，可以补充要求（下一步就会读到）'
      : ctx.done ? '已入库。还可以让 AI 查题库、改题、补记复习、记反馈…'
        : draft.revision ? '例如：第 7 题答案太简略，按 6 分重写；第 8 题题型应该是表达技巧题' : '想让 AI 做什么？可以附图';
  const canSend = !locked && (s.composer.trim() || s.attach.length);
  return html`
    ${chips.length && !ctx.busy ? html`<div class="composer__chips">${each(chips, x => x.label, x => html`
      <button class="chip" data-action="entry.suggest" data-arg="${x.text}" ${locked ? html`disabled` : ''}>${x.label}</button>`)}</div>` : ''}
    <div class="composer__box">
      ${s.attach.length ? html`<div class="composer__attach">${each(s.attach, (_, n) => n, (a, n) => html`
        <span class="attach"><img src="${a.data}" alt="${a.name}"><button class="attach__x" data-action="entry.unattach" data-arg="${n}" aria-label="移除这张图">${icon('close')}</button></span>`)}</div>` : ''}
      <textarea id="composer" rows="2" data-input="entry.composer" data-autosize placeholder="${placeholder}" aria-label="给 AI 的话" ${locked ? html`disabled` : ''}>${s.composer}</textarea>
      <div class="composer__row">
        <span class="composer__tools">
          ${draft.images?.length && !ctx.busy ? html`<button class="chip ${s.withImage ? 'chip--info' : ''}" data-action="entry.withImage" aria-pressed="${String(s.withImage)}"
            title="发送时附上原图，AI 可以对照原图核对">${icon('image')}附原图</button>` : ''}
          ${agent ? html`<label class="chip composer__file" title="附一张图发给 AI">${icon('upload')}附图
            <input type="file" accept="image/*" multiple class="visually-hidden" data-change="entry.attach"></label>` : ''}
        </span>
        ${agent ? renderGauge(draft, s.liveTps) : ''}
        <button class="btn btn--primary btn--sm composer__send" data-action="entry.send" ${canSend ? '' : html`disabled`}>${icon('arrow')}${agent && ctx.busy ? '插话' : '发送'}</button>
      </div>
    </div>`;
}

export function renderChat(draft, s) {
  const busy = BUSY.includes(draft.status);
  const done = draft.status === 'committed' || Boolean(draft.committed);
  const msgs = draft.messages || [];
  const ctx = { busy, done, canRetry: draft.can_retry, revision: draft.revision, open: s.open, known: s.known };
  const legacy = !draft.agent;
  return html`<section class="chat" aria-label="对话">
    ${head(draft, busy)}
    <ol class="chat__log tl" id="chat-log" aria-live="polite">
      ${msgs.length ? '' : html`<li class="tl__item msg msg--note" data-key="hello"><span>${draft.kind === 'chat'
        ? '这是一段空白对话：可以让 AI 查改题库、增删改查复习记录、对着作答照片批改；让它录题的话，题会出现在右侧草稿里。' : ''}</span></li>`}
      ${renderTimeline(draft, ctx)}
      ${legacy && (busy || msgs.at(-1)?.role === 'ai') ? renderActivity(draft, busy) : ''}
      ${!legacy && busy ? liveTail(draft) : ''}
    </ol>
    <div class="composer ${locked(draft, busy, done) ? 'is-locked' : ''}">${composer(draft, s, ctx)}</div>
  </section>`;
}

const locked = (draft, busy, done) => !draft.agent && (busy || done || !draft.revision);
