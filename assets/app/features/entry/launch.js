/**
 * 主区的「开始」界面：没有打开的草稿（新对话），或刚上传、还在准备的草稿（staged）。
 * 居中的大输入框就是和 AI 说的第一句话——有图时它就是补充说明；上方是页面条（拖动或箭头排序、旋转、删页、
 * 加页、每页一句说明）。回车或点按钮开始后，输入框借 View Transition 平滑落到对话底部（CSS 里同名 composer），
 * 标题淡出，时间线接着出现第一条消息和 AI 的思考。复习批改的照片也走这里（按钮是「开始批改」）。
 */
import { html, each } from '../../core/html.js';
import { icon } from '../../ui/icons.js';
import { CHAT_SUGGESTIONS } from './chat.js';
import { FILE_ACCEPT } from '../../core/pdf.js';
import { fileCard } from './file-card.js';
import { pageCard, NOTES } from './page-card.js';

export function renderLaunch(d, s) {
  const staged = d?.status === 'staged';
  const importing = Boolean(s.imports?.length);
  const pages = staged ? d.pages || [] : [];
  const review = d?.kind === 'review';
  const title = review ? `准备批改 ${d.session_id}` : staged ? '确认页面，告诉 AI 怎么录' : '今天录点什么？';
  const sub = staged ? 'AI 会按这个顺序读图：拖动排序，转正拍歪的照片。有要交代的写在下面，也可以直接开始。'
    : '拖入 PDF 或试卷照片，也可以粘贴截图。AI 会拆题、标题型、估留白；还可以直接问它题库和复习的事。';
  const placeholder = staged ? (review ? '补充说明（可选），例如：第 3 题我空着没写' : '补充说明（可选），例如：只录第二大题；第 3 页是参考答案')
    : '说点什么，或者粘贴一张截图…';
  const canSend = !importing && (staged || s.heroText.trim());
  return html`<section class="launch ${s.dragging ? 'is-over' : ''}" aria-label="${staged ? '准备' : '新对话'}">
    <div class="launch__inner">
      <button class="btn btn--ghost btn--sm hist-toggle launch__hist" data-action="entry.hist">${icon('panel')}录入记录</button>
      <h2 class="launch__title">${title}</h2>
      <p class="launch__sub">${sub}</p>
      <div class="composer__box launch__box">
        ${pages.length || importing ? html`<div class="launch__pagebar"><ol class="launch__pages ${s.dragPage !== null ? 'is-dragging' : ''}" aria-label="上传的文件与页面">
          ${each(pages, p => p.id, (p, i) => pageCard(p, i, pages.length, importing))}
          ${each(s.imports || [], job => job.id, fileCard)}
          <li class="page page--add" data-key="add"><label class="page__addbtn" title="再加几页">${icon('plus')}
            <input type="file" accept="${FILE_ACCEPT}" multiple class="visually-hidden" data-change="entry.pageAdd"></label>
            <span class="page__addnote">继续添加</span></li>
        </ol>${s.pageOverflow ? html`<button class="launch__expand" data-action="entry.managerOpen" aria-label="展开页面管理器" title="展开管理所有页面">${icon('expand')}<span>展开</span></button>` : ''}
        </div><datalist id="page-notes">${each(NOTES, x => x, x => html`<option value="${x}"></option>`)}</datalist>` : ''}
        <textarea id="composer" class="launch__input" rows="${staged ? 2 : 3}" data-input="entry.heroText" ${staged ? html`data-change="entry.stageHint"` : ''}
          data-autosize placeholder="${placeholder}" aria-label="${staged ? '补充说明' : '给 AI 的话'}">${s.heroText}</textarea>
        <div class="composer__row">
          <span class="composer__tools">
            <label class="chip composer__file" title="选择 PDF 或图片">${icon('upload')}${staged ? '加页' : '上传文件'}
              <input type="file" accept="${FILE_ACCEPT}" multiple class="visually-hidden" data-change="${staged ? 'entry.pageAdd' : 'entry.files'}"></label>
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
