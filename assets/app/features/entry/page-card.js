/** 紧凑页面条和展开管理器共用同一张页面卡片、同一组编辑动作。 */
import { html } from '../../core/html.js';
import { icon } from '../../ui/icons.js';

export const NOTES = ['题目页', '答案页', '题目和答案', '学生作答'];

export function pageCard(p, i, n, locked = false) {
  const source = p.source ? `${p.source.name} · 第 ${p.source.page} 页` : `第 ${i + 1} 页`;
  return html`<li class="page" draggable="${String(!locked)}" data-page="${i}" data-key="${p.id}" title="${source}">
    <div class="page__img" data-rotate="${p.rotate || 0}">
      <button class="page__preview" data-action="entry.pagePreview" data-arg="${p.id}" aria-label="放大查看第 ${i + 1} 页" title="放大查看">
        <img src="/api/image?id=${p.image}" alt="第 ${i + 1} 页" draggable="false"></button>
      <span class="page__no">${i + 1}</span>
      <span class="page__tools">
        <button class="page__btn" data-action="entry.pageMove" data-arg="${i}:-1" ${i && !locked ? '' : html`disabled`} aria-label="往前" title="往前">${icon('chevron')}</button>
        <button class="page__btn" data-action="entry.pageRotate" data-arg="${i}" ${locked ? html`disabled` : ''} aria-label="顺时针转 90°" title="顺时针转 90°">${icon('rotate')}</button>
        <button class="page__btn" data-action="entry.pageRemove" data-arg="${i}" ${n > 1 && !locked ? '' : html`disabled`} aria-label="删掉这页" title="删掉这页">${icon('trash')}</button>
        <button class="page__btn" data-action="entry.pageMove" data-arg="${i}:1" ${i < n - 1 && !locked ? '' : html`disabled`} aria-label="往后" title="往后">${icon('chevron')}</button>
      </span>
    </div>
    <input class="page__note" list="page-notes" value="${p.note || ''}" data-change="entry.pageNote" data-arg="${i}" ${locked ? html`disabled` : ''} placeholder="这页是…" aria-label="第 ${i + 1} 页的说明">
  </li>`;
}
