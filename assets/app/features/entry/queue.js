/**
 * 批量录入：顶部草稿队列（每张图一份草稿，后台排队识别，状态实时刷新）、上传 / 粘贴 / 拖放、
 * 多张图时的「每张一份 / 合成一份」选择，以及没有草稿时的空状态。
 */
import { html, each } from '../../core/html.js';
import { icon } from '../../ui/icons.js';
import { GENRES } from '../../domain/genres.js';

const STATUS = {
  queued: ['排队中', 'wait'], extracting: ['识别中', 'wait'], thinking: ['AI 执行中', 'wait'],
  ready: ['待确认', 'ready'], error: ['出错', 'bad'], committed: ['已入库', 'done'],
};

export const readFiles = files => Promise.all([...files].filter(f => f.type.startsWith('image/')).map(file => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve({ name: file.name || '截图.png', data: reader.result });
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(file);
})));

const uploadButton = (label, primary = true) => html`
  <label class="btn ${primary ? 'btn--primary' : ''} upload-btn">${icon('upload')}<span>${label}</span>
    <input type="file" accept="image/*" multiple class="visually-hidden" data-change="entry.files"></label>`;

const manualSelect = () => html`
  <select class="select manual-select" data-change="entry.manual" aria-label="不用 AI，手动录入">
    <option value="" selected>手动录入…</option>
    ${each(GENRES, g => g.code, g => html`<option value="${g.code}">${g.name}</option>`)}
  </select>`;

function chip(d, activeId) {
  const [label, tone] = STATUS[d.status] || [d.status, 'wait'];
  return html`<li data-key="${d.id}">
    <button class="qchip ${d.id === activeId ? 'is-active' : ''}" data-tone="${tone}" data-action="entry.open" data-arg="${d.id}"
      aria-current="${String(d.id === activeId ? 'true' : 'false')}" title="${d.title || '识别中的图片'}">
      ${d.images?.[0] ? html`<img src="/api/image?id=${d.images[0]}" alt="">` : html`<span class="qchip__blank">${d.kind === 'chat' ? '话' : '手'}</span>`}
      <span class="qchip__text"><b>${d.title || (tone === 'wait' ? '正在识别…' : '未命名')}</b><small><i class="qdot"></i>${tone === 'ready' && !d.genres?.length && { chat: '对话', review: '批改' }[d.kind] || label}${d.status === 'committed' && d.committed ? ` ${d.committed.created} 题` : ''}</small></span>
    </button></li>`;
}

export function renderQueue(s) {
  const waiting = s.drafts.filter(d => STATUS[d.status]?.[1] === 'wait').length;
  return html`
  <div class="queue">
    <div class="queue__head">
      <h1 class="queue__title">录入</h1>
      <span class="queue__meta">${waiting ? `${waiting} 份在处理` : s.drafts.filter(d => d.status === 'ready').length ? '点一份开始校对' : ''}</span>
    </div>
    <ol class="queue__list" aria-label="草稿队列">${each(s.drafts, d => d.id, d => chip(d, s.activeId))}</ol>
    <div class="queue__actions">${manualSelect()}<button class="btn" data-action="entry.newChat" title="不上传图片，直接和 AI 对话：查改题库、复习记录、复习反馈">新对话</button>${uploadButton('上传图片')}</div>
  </div>
  ${s.pending ? html`<div class="pending" role="group" aria-label="多张图片怎么处理">
    <span>选了 ${s.pending.length} 张图：</span>
    <input class="input pending__hint" value="${s.hint || ''}" data-input="entry.hint" aria-label="给 AI 的补充说明"
      placeholder="补充说明（可选），如：第二张是答案页">
    <button class="btn btn--sm btn--primary" data-action="entry.upload" data-arg="split">每张一份草稿</button>
    <button class="btn btn--sm" data-action="entry.upload" data-arg="combine">合成一份（同一篇跨了几页）</button>
    <button class="btn btn--sm btn--ghost" data-action="entry.upload" data-arg="cancel">取消</button>
  </div>` : ''}`;
}

export function renderEmpty(s) {
  return html`
  <div class="drop ${s.dragging ? 'is-over' : ''}">
    <div class="drop__sheet" aria-hidden="true"><i></i><i></i><i></i><b></b><i></i><i></i><b></b></div>
    <h2>把试卷照片交给我</h2>
    <p>一张图里同时有原文、题目和答案也没关系。AI 会拆出原文和每道小题，标好题型，估好留白；默写题会按空拆开并自动去重。你在对话里告诉它哪里要改，没问题就入库。</p>
    <div class="drop__actions">${uploadButton('选择图片')}<span class="drop__hint">也可以直接 Ctrl+V 粘贴截图，或把图片拖进来；一次可以选多张</span></div>
    ${s.aiReady ? '' : html`<p class="callout callout--warn drop__warn">还没有配置 AI，图片识别用不了。<a href="#/settings">去设置</a>填写模型地址和 Key；或者先用右上角「手动录入」。</p>`}
  </div>`;
}
