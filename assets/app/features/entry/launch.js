/**
 * 主区的「开始」界面：没有打开的草稿（新对话），或刚上传、还在准备的草稿（staged）。
 * 居中的大输入框就是和 AI 说的第一句话——有图时它就是补充说明；上方是页面条（拖动或箭头排序、旋转、删页、
 * 加页、每页一句说明）。回车或点按钮开始后，输入框借 View Transition 平滑落到对话底部（CSS 里同名 composer），
 * 标题淡出，时间线接着出现第一条消息和 AI 的思考。复习批改的照片也走这里（按钮是「开始批改」）。
 */
import { html, each } from '../../core/html.js';
import { icon } from '../../ui/icons.js';
import { CHAT_SUGGESTIONS } from './chat.js';

const NOTES = ['题目页', '答案页', '题目和答案', '学生作答'];

function page(p, i, n) {
  return html`<li class="page" draggable="true" data-page="${i}" data-key="${p.image}">
    <div class="page__img" data-rotate="${p.rotate || 0}"><img src="/api/image?id=${p.image}" alt="第 ${i + 1} 页" draggable="false">
      <span class="page__no">${i + 1}</span>
      <span class="page__tools">
        <button class="page__btn" data-action="entry.pageMove" data-arg="${i}:-1" ${i ? '' : html`disabled`} aria-label="往前" title="往前">${icon('chevron')}</button>
        <button class="page__btn" data-action="entry.pageRotate" data-arg="${i}" aria-label="顺时针转 90°" title="顺时针转 90°">${icon('rotate')}</button>
        <button class="page__btn" data-action="entry.pageRemove" data-arg="${i}" ${n > 1 ? '' : html`disabled`} aria-label="删掉这页" title="删掉这页">${icon('trash')}</button>
        <button class="page__btn" data-action="entry.pageMove" data-arg="${i}:1" ${i < n - 1 ? '' : html`disabled`} aria-label="往后" title="往后">${icon('chevron')}</button>
      </span>
    </div>
    <input class="page__note" list="page-notes" value="${p.note || ''}" data-change="entry.pageNote" data-arg="${i}" placeholder="这页是…" aria-label="第 ${i + 1} 页的说明">
  </li>`;
}

export function renderLaunch(d, s) {
  const staged = d?.status === 'staged';
  const pages = staged ? d.pages || [] : [];
  const review = d?.kind === 'review';
  const title = review ? `准备批改 ${d.session_id}` : staged ? '确认页面，告诉 AI 怎么录' : '今天录点什么？';
  const sub = staged ? 'AI 会按这个顺序读图：拖动排序，转正拍歪的照片。有要交代的写在下面，也可以直接开始。'
    : '拖进来、粘贴或选择试卷照片，AI 会拆题、标题型、估留白；也可以直接问它题库和复习的事。';
  const placeholder = staged ? (review ? '补充说明（可选），例如：第 3 题我空着没写' : '补充说明（可选），例如：只录第二大题；第 3 页是参考答案')
    : '说点什么，或者粘贴一张截图…';
  const canSend = staged || s.heroText.trim();
  return html`<section class="launch ${s.dragging ? 'is-over' : ''}" aria-label="${staged ? '准备' : '新对话'}">
    <div class="launch__inner">
      <button class="btn btn--ghost btn--sm hist-toggle launch__hist" data-action="entry.hist">${icon('panel')}录入记录</button>
      <h2 class="launch__title">${title}</h2>
      <p class="launch__sub">${sub}</p>
      <div class="composer__box launch__box">
        ${pages.length ? html`<ol class="launch__pages ${s.dragPage !== null ? 'is-dragging' : ''}">
          ${each(pages, p => p.image, (p, i) => page(p, i, pages.length))}
          <li class="page page--add" data-key="add"><label class="page__addbtn" title="再加几页">${icon('plus')}
            <input type="file" accept="image/*" multiple class="visually-hidden" data-change="entry.pageAdd"></label></li>
        </ol><datalist id="page-notes">${each(NOTES, x => x, x => html`<option value="${x}"></option>`)}</datalist>` : ''}
        <textarea id="composer" class="launch__input" rows="${staged ? 2 : 3}" data-input="entry.heroText" ${staged ? html`data-change="entry.stageHint"` : ''}
          data-autosize placeholder="${placeholder}" aria-label="${staged ? '补充说明' : '给 AI 的话'}">${s.heroText}</textarea>
        <div class="composer__row">
          <span class="composer__tools">
            <label class="chip composer__file" title="选择图片">${icon('upload')}${staged ? '加图' : '上传图片'}
              <input type="file" accept="image/*" multiple class="visually-hidden" data-change="${staged ? 'entry.pageAdd' : 'entry.files'}"></label>
            ${staged && pages.length > 1 && !review ? html`<span class="seg seg--sm" role="group" aria-label="怎么识别">
              <button data-action="entry.split" data-arg="" aria-pressed="${String(!s.split)}" title="同一份试卷的几页">合成一份</button>
              <button data-action="entry.split" data-arg="each" aria-pressed="${String(s.split)}" title="几张不相关的截图">每页一份</button></span>` : ''}
            ${staged ? html`<button class="chip" data-action="entry.trash" data-arg="${d.id}">丢弃</button>` : ''}
          </span>
          <button class="btn btn--primary composer__send ${s.starting ? 'is-busy' : ''}" data-action="${staged ? 'entry.start' : 'entry.send'}" data-arg="${s.split ? 'split' : ''}"
            ${canSend && !s.starting ? '' : html`disabled`}>${icon('arrow')}${staged ? (review ? '开始批改' : `开始识别${pages.length > 1 ? ` ${pages.length} 页` : ''}`) : '发送'}</button>
        </div>
      </div>
      ${staged ? '' : html`<div class="launch__chips">${each(CHAT_SUGGESTIONS, x => x.label, x => html`
        <button class="chip" data-action="entry.heroSuggest" data-arg="${x.text}">${x.label}</button>`)}</div>`}
      ${s.aiReady ? '' : html`<p class="callout callout--warn launch__warn">还没有配置 AI。<a href="#/settings">去设置</a>填写模型地址和 Key；或者在左侧「手动录入」。</p>`}
    </div>
  </section>`;
}
