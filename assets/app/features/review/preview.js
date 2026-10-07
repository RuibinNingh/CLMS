/** A4 预览的人工控件；纸面由独立打印文档统一产生。 */
import { html, each } from '../../core/html.js';
import { icon } from '../../ui/icons.js';
import { sessionTitle } from './rail.js';

export function previewRail(s) {
  const p = s.preview;
  return html`<div class="rv-rail rv-print-controls">
    <header class="rv-rail__head"><h2>答题留白</h2><button class="btn btn--ghost btn--icon rv-rail__close" data-action="rv.rail" aria-label="收起留白设置">${icon('close')}</button></header>
    <div class="rv-rail__scroll">
      <p class="rv-print-controls__hint">调整会保存为题目默认值，以后的复习也会采用。自动适配按参考答案的真实打印排版测量。</p>
      <button class="btn btn--sm" data-action="rv.printAutoAll" ${!p.ready ? html`disabled` : ''}>自动适配全部题</button>
      <p class="rv-print-controls__status" role="status">${p.error || (p.saving ? '正在保存…' : p.pending ? '等待保存…' : '默认留白已保存')}
        ${p.error ? html`<button class="linkish" data-action="rv.printSave">重试保存</button>` : ''}</p>
      <ol class="rv-print-controls__items">${each(s.session.items, item => item.id, (item, i) => html`<li class="rv-print-item" data-key="${item.id}" data-current="${p.focus === item.id}">
        <button class="rv-print-item__select" data-action="rv.printFocus" data-arg="${item.id}"><b>第 ${i + 1} 题</b><span>${item.qtype || '未分类'}</span></button>
        <p>${item.stem}</p>
        ${item.genre === 'dictation' ? html`<small>默写使用题面内的书写区域</small>` : html`
          <div class="rv-print-lines" role="group" aria-label="第 ${i + 1} 题默认留白">
            <button class="btn btn--sm btn--icon" data-action="rv.printStep" data-arg="${item.id}:-1" aria-label="第 ${i + 1} 题减少一行" ${!p.ready || !item.blank_lines ? html`disabled` : ''}>−</button>
            <input class="input" type="number" min="0" max="1000" value="${item.blank_lines || 0}" data-input="rv.printLines" data-arg="${item.id}" aria-label="第 ${i + 1} 题留白行数" ${!p.ready ? html`disabled` : ''}>
            <button class="btn btn--sm btn--icon" data-action="rv.printStep" data-arg="${item.id}:1" aria-label="第 ${i + 1} 题增加一行" ${!p.ready || item.blank_lines >= 1000 ? html`disabled` : ''}>+</button><small>行</small>
          </div>
          <button class="linkish" data-action="rv.printAuto" data-arg="${item.id}" ${!p.ready ? html`disabled` : ''}>自动适配当前题</button>`}
      </li>`)}</ol>
    </div>
  </div>`;
}

export function previewView(s) {
  const p = s.preview;
  return html`<header class="rv-top rv-print-top">
    <button class="btn btn--ghost btn--icon rv-top__rail" data-action="rv.rail" aria-label="打开留白设置">${icon('panel')}</button>
    <button class="btn btn--ghost btn--sm" data-action="rv.back">${icon('back')}全部复习</button>
    <div class="rv-top__title"><h2>${sessionTitle(s.session)} · 打印预览</h2><small>A4 · ${s.session.items.length} 题 · ${p.ready ? `${p.pages} 页` : '正在排版…'}</small></div>
    <label class="rv-print-answers"><input type="checkbox" data-change="rv.printAnswers" ${p.answers ? html`checked` : ''}>附参考答案</label>
    <span class="rv-top__acts"><button class="btn btn--sm" data-action="rv.printNow" ${!p.ready ? html`disabled` : ''}>${icon('print')}打印</button>
      <button class="btn btn--sm btn--primary" data-action="rv.printStart">开始复习</button></span>
  </header>
  <div class="rv-print-stage"><iframe id="review-print-frame" data-key="print-${s.session.id}" data-morph="skip"
    src="/print/session?id=${s.session.id}" title="A4 复习卷打印预览"></iframe></div>`;
}
