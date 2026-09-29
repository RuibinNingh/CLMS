/** 页面条溢出时展开管理器：网格调大小、拖动排序，单页预览连续缩放。所有修改复用准备页动作。 */
import { html, each } from '../../core/html.js';
import { showModal, closeModal, setVars } from '../../core/dom.js';
import { FILE_ACCEPT } from '../../core/pdf.js';
import { icon } from '../../ui/icons.js';
import { pageCard } from './page-card.js';
import { fileCard } from './file-card.js';

export function renderPageManager(s) {
  if (!s.manager.open) return '';
  const pages = s.draft?.pages || [];
  const m = s.manager;
  const index = pages.findIndex(p => p.id === m.preview);
  const p = pages[index];
  return html`<dialog open class="page-manager" data-key="page-manager" aria-labelledby="page-manager-title" data-action="entry.managerBackdrop">
    <header class="page-manager__head">
      <div><h2 id="page-manager-title">${p ? '查看页面' : '页面管理'}</h2><p>${p ? `第 ${index + 1} 页 / 共 ${pages.length} 页` : `${pages.length} 页${s.imports.length ? ` · ${s.imports.length} 个文件处理中` : ''}`}</p></div>
      <button class="btn btn--sm" data-action="entry.managerClose" title="收起，返回录入框">${icon('shrink')}收起</button>
    </header>
    <div class="page-manager__bar">
      ${p ? html`<button class="btn btn--ghost btn--sm" data-action="entry.managerGrid">${icon('panel')}所有页面</button>
        <span class="page-manager__filename" title="${p.source?.name || ''}">${p.source ? `${p.source.name} · 原第 ${p.source.page} 页` : p.note || '原图'}</span>
        <label class="page-manager__scale"><span>缩放</span><input type="range" min="50" max="250" step="5" value="${m.zoom}" data-input="entry.managerZoom" aria-label="页面缩放"><output>${m.zoom}%</output></label>
        <button class="btn btn--ghost btn--sm" data-action="entry.managerFit">适合窗口</button>`
        : html`<span class="page-manager__help">${s.imports.length ? '拆分完成后即可调整页面' : '拖动排序，点击图片放大查看'}</span>
          <label class="page-manager__scale"><span>缩略图</span><input type="range" min="120" max="300" step="20" value="${m.size}" data-input="entry.managerSize" aria-label="缩略图大小"></label>
          <label class="btn btn--sm">${icon('plus')}添加文件<input class="visually-hidden" type="file" accept="${FILE_ACCEPT}" multiple data-change="entry.pageAdd"></label>`}
    </div>
    ${p ? html`<div class="page-manager__preview"><div class="page-manager__paper" data-key="preview-${p.id}" data-rotate="${p.rotate || 0}">
      <img src="/api/image?id=${p.image}" alt="第 ${index + 1} 页完整图片" draggable="false"></div></div>
      <footer class="page-manager__foot">
        <button class="btn btn--sm" data-action="entry.managerStep" data-arg="-1" ${index ? '' : html`disabled`}>上一页</button>
        <button class="btn btn--ghost btn--sm" data-action="entry.pageRotate" data-arg="${index}" ${s.imports.length ? html`disabled` : ''}>${icon('rotate')}旋转</button>
        <button class="btn btn--sm" data-action="entry.managerStep" data-arg="1" ${index < pages.length - 1 ? '' : html`disabled`}>下一页</button>
      </footer>`
      : html`<ol class="page-manager__grid ${s.dragPage !== null ? 'is-dragging' : ''}" aria-label="管理所有页面">
        ${each(pages, p => p.id, (p, i) => pageCard(p, i, pages.length, Boolean(s.imports.length)))}
        ${each(s.imports, j => j.id, fileCard)}
      </ol><footer class="page-manager__foot"><span>页序、方向和说明自动保存</span><button class="btn btn--primary btn--sm" data-action="entry.managerClose">完成，收起</button></footer>`}
  </dialog>`;
}

export function pageManager({ s, root, render }) {
  s.manager = { open: false, size: 180, preview: null, zoom: 100 };
  s.pageOverflow = false;
  let frame = 0;
  let returnTo = null;
  const dialog = () => root.querySelector('.page-manager');

  function fitPreview() {
    const area = root.querySelector('.page-manager__preview');
    const paper = area?.querySelector('.page-manager__paper');
    const img = paper?.querySelector('img');
    if (!img?.naturalWidth) return;
    const rotated = Number(paper.dataset.rotate) % 180 !== 0;
    const w = rotated ? img.naturalHeight : img.naturalWidth;
    const h = rotated ? img.naturalWidth : img.naturalHeight;
    const padding = parseFloat(getComputedStyle(area).paddingLeft) * 2;
    const scale = Math.min((area.clientWidth - padding) / w, (area.clientHeight - padding) / h) * s.manager.zoom / 100;
    setVars(paper, { '--preview-width': `${w * scale}px`, '--preview-height': `${h * scale}px`,
      '--image-width': `${img.naturalWidth * scale}px`, '--image-height': `${img.naturalHeight * scale}px`,
      '--image-rotate': `${paper.dataset.rotate}deg` });
  }

  function measure() {
    frame = 0;
    const strip = root.querySelector('.launch__pages');
    const overflow = Boolean(strip && strip.scrollWidth > strip.clientWidth + 1);
    if (s.pageOverflow !== overflow) { s.pageOverflow = overflow; render(); }
    fitPreview();
  }
  const later = () => { if (!frame) frame = requestAnimationFrame(measure); };
  const observer = new ResizeObserver(later);
  observer.observe(root);

  function close() {
    closeModal(dialog());
    s.manager.open = false; s.manager.preview = null;
    render();
    if (returnTo?.isConnected) returnTo.focus({ preventScroll: true });
    else root.querySelector('[data-action="entry.managerOpen"]')?.focus({ preventScroll: true });
  }
  function step(amount) {
    const pages = s.draft?.pages || [];
    const index = pages.findIndex(p => p.id === s.manager.preview);
    if (pages[index + amount]) { s.manager.preview = pages[index + amount].id; render(); }
  }
  function onKey(event) {
    if (!s.manager.open) return;
    if (event.key === 'Escape') {
      event.preventDefault(); event.stopPropagation();
      if (s.manager.preview) { s.manager.preview = null; render(); } else close();
    } else if (s.manager.preview && !['INPUT', 'TEXTAREA'].includes(event.target.tagName) && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
      event.preventDefault(); step(event.key === 'ArrowLeft' ? -1 : 1);
    }
  }
  // 挂在 document 上：关掉预览后聚焦的节点被移除，焦点落到 body，挂在 root 上就收不到第二次 Esc
  root.ownerDocument.addEventListener('keydown', onKey);
  root.addEventListener('load', later, true);

  return {
    sync() {
      showModal(dialog());
      setVars(dialog(), { '--page-size': `${s.manager.size}px` });
      later();
    },
    reset() { closeModal(dialog()); s.manager.open = false; s.manager.preview = null; },
    dispose() { observer.disconnect(); cancelAnimationFrame(frame); closeModal(dialog()); root.ownerDocument.removeEventListener('keydown', onKey); root.removeEventListener('load', later, true); },
    actions: {
      managerOpen({ el }) { returnTo = el; s.manager.open = true; s.manager.preview = null; render(); },
      managerClose: close,
      managerBackdrop({ el, event }) {
        const r = el.getBoundingClientRect();
        if (event.target === el && (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom)) close();
      },
      pagePreview({ arg, el }) { if (!s.manager.open) returnTo = el; s.manager.open = true; s.manager.preview = arg; s.manager.zoom = 100; render(); },
      managerGrid() { s.manager.preview = null; render(); },
      managerSize({ el }) { s.manager.size = Number(el.value); render(); },
      managerZoom({ el }) { s.manager.zoom = Number(el.value); render(); },
      managerFit() { s.manager.zoom = 100; render(); },
      managerStep: ({ arg }) => step(Number(arg)),
    },
  };
}
