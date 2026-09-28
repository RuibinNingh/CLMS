/**
 * 准备阶段（上传后先到这里，不直接执行）：按 AI 读图的顺序排好页——拖动或用箭头调整、旋转、删页、加页，
 * 给每页写一句说明（「答案页」之类，会告诉 AI），写补充说明；然后「开始识别」（合成一份）或「每页一份，分别识别」。
 * 复习批改的照片也走这一步，按钮是「开始批改」。每次调整立即保存到服务端（/api/draft/pages）。
 */
import { html, each } from '../../core/html.js';
import { icon } from '../../ui/icons.js';

const NOTES = ['题目页', '答案页', '题目和答案', '学生作答', '只看第一大题'];

function page(p, i, n) {
  return html`<li class="page" draggable="true" data-page="${i}" data-key="${p.image}">
    <div class="page__img" data-rotate="${p.rotate || 0}"><img src="/api/image?id=${p.image}" alt="第 ${i + 1} 页" draggable="false"></div>
    <div class="page__bar">
      <b>第 ${i + 1} 页</b>
      <button class="btn btn--ghost btn--icon btn--sm" data-action="entry.pageMove" data-arg="${i}:-1" ${i ? '' : html`disabled`} aria-label="往前">←</button>
      <button class="btn btn--ghost btn--icon btn--sm" data-action="entry.pageMove" data-arg="${i}:1" ${i < n - 1 ? '' : html`disabled`} aria-label="往后">→</button>
      <button class="btn btn--ghost btn--icon btn--sm" data-action="entry.pageRotate" data-arg="${i}" aria-label="顺时针转 90°" title="顺时针转 90°">${icon('retry')}</button>
      <button class="btn btn--ghost btn--icon btn--sm btn--danger" data-action="entry.pageRemove" data-arg="${i}" ${n > 1 ? '' : html`disabled`} aria-label="删掉这页">${icon('trash')}</button>
    </div>
    <input class="input page__note" list="page-notes" value="${p.note || ''}" data-change="entry.pageNote" data-arg="${i}"
      placeholder="这页是…（可选）" aria-label="第 ${i + 1} 页的说明">
  </li>`;
}

export function renderStage(d, s) {
  const pages = d.pages || [];
  const review = d.kind === 'review';
  return html`<section class="stage" aria-label="准备">
    <header class="stage__head">
      <div><h2>${review ? `准备批改 ${d.session_id}` : '确认页面，再开始识别'}</h2>
        <p class="muted">AI 会按下面的顺序读图。拖动或用箭头调整顺序，转正拍歪的照片，删掉不需要的页；给页面写一句说明会一起告诉 AI。</p></div>
      <span class="stage__count"><button class="btn btn--ghost btn--sm hist-toggle" data-action="entry.hist">${icon('library')}记录</button>${pages.length} 页</span>
    </header>
    <ol class="stage__pages ${s.dragPage !== null ? 'is-dragging' : ''}">${each(pages, p => p.image, (p, i) => page(p, i, pages.length))}
      <li class="page page--add" data-key="add"><label class="page__addbtn">${icon('plus')}<span>加一页</span>
        <input type="file" accept="image/*" multiple class="visually-hidden" data-change="entry.pageAdd"></label></li>
    </ol>
    <datalist id="page-notes">${each(NOTES, x => x, x => html`<option value="${x}"></option>`)}</datalist>
    <label class="field stage__hint"><span>补充说明（可选）</span>
      <textarea class="textarea" rows="2" data-change="entry.stageHint" placeholder="${review ? '例如：第 3 题我空着没写' : '例如：只录第二大题；第 3 页是参考答案'}">${d.hint || ''}</textarea></label>
    <footer class="stage__foot">
      <button class="btn btn--ghost" data-action="entry.trash" data-arg="${d.id}">丢弃</button>
      <span class="stage__spacer"></span>
      ${!review && pages.length > 1 ? html`<button class="btn" data-action="entry.start" data-arg="split" title="每页是独立的题（例如几张不相关的截图）">每页一份，分别识别</button>` : ''}
      <button class="btn btn--primary" data-action="entry.start" data-arg="" ${s.starting ? html`disabled` : ''}>${icon('send')}${review ? '开始批改' : `开始识别${pages.length > 1 ? `（${pages.length} 页合成一份）` : ''}`}</button>
    </footer>
  </section>`;
}
