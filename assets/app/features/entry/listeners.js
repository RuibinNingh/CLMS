/**
 * 录入页的文档级监听：粘贴截图（输入框里且是 Agent 草稿 → 当附图；其余 → 上传）、拖放（外部文件 → 上传 / 加页；
 * 页面缩略图 → 调整页序）、Enter 发送（Shift+Enter 换行，输入法组字时不触发）；标题 / 作者 / 出处（data-oneline）回车不换行。返回解绑函数。
 */
export function bindListeners(root, { s, render, takeFiles, readImages, movePage }) {
  const onPaste = async event => {
    const files = [...(event.clipboardData?.files || [])].filter(f => f.type.startsWith('image/'));
    if (!files.length) return;
    event.preventDefault();
    if (event.target?.id === 'composer' && s.draft?.agent && s.draft.status !== 'staged') { s.attach.push(...await readImages(files)); render(); return; }
    takeFiles(files);
  };
  const pageOf = el => el?.closest?.('.page[data-page]');
  const onDragStart = event => {
    const p = pageOf(event.target);
    if (!p) return;
    s.dragPage = Number(p.dataset.page);
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', p.dataset.page);
  };
  const onDragOver = event => {
    if (s.dragPage !== null && pageOf(event.target)) { event.preventDefault(); return; }
    if (![...(event.dataTransfer?.types || [])].includes('Files')) return;
    event.preventDefault();
    if (!s.dragging) { s.dragging = true; render(); }
  };
  const onDragLeave = event => { if (event.target === root || !root.contains(event.relatedTarget)) { s.dragging = false; render(); } };
  const onDrop = event => {
    if (s.dragPage !== null) {
      event.preventDefault();
      const target = pageOf(event.target);
      const from = s.dragPage; s.dragPage = null;
      if (target) movePage(from, Number(target.dataset.page)); else render();
      return;
    }
    if (!event.dataTransfer?.files?.length) return;
    event.preventDefault();
    s.dragging = false;
    takeFiles(event.dataTransfer.files);
  };
  const onDragEnd = () => { if (s.dragPage !== null) { s.dragPage = null; render(); } };
  const onKey = event => {
    if (event.target.dataset?.oneline !== undefined && event.key === 'Enter' && !event.isComposing) { event.preventDefault(); return; }
    if (event.target.id === 'composer' && event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      root.querySelector('.composer__send')?.click();
    }
  };
  const listeners = [['dragstart', onDragStart], ['dragover', onDragOver], ['dragleave', onDragLeave], ['drop', onDrop], ['dragend', onDragEnd], ['keydown', onKey]];
  document.addEventListener('paste', onPaste);
  listeners.forEach(([type, fn]) => root.addEventListener(type, fn));
  return () => {
    document.removeEventListener('paste', onPaste);
    listeners.forEach(([type, fn]) => root.removeEventListener(type, fn));
  };
}
