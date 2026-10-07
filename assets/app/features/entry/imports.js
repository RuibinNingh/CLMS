/** 录入文件队列：每个 PDF 独立进度，整份拆完才一次性加入草稿。失败保留卡片，可接着重试。 */
import { readImages } from '../../core/files.js';
import { isPdf, splitPdf, pdfError } from '../../core/pdf.js';
import { revealFrom } from '../../core/dom.js';
import { toast } from '../../ui/feedback.js';

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
// getRandomValues 在内网 HTTP 也可用；后端导入幂等键保持 32 位小写 hex。
function uploadId() {
  if (typeof globalThis.crypto?.getRandomValues !== 'function') {
    throw new Error('当前浏览器无法生成安全的上传编号，请刷新页面或更换浏览器后重试。');
  }
  return Array.from(crypto.getRandomValues(new Uint8Array(16)),
    byte => byte.toString(16).padStart(2, '0')).join('');
}

export function fileImports({ s, root, render, post, applyDraft, connect, refreshList, fresh }) {
  s.imports = [];
  let running = false;
  let epoch = 0;
  const paint = () => render();
  const motion = name => parseFloat(getComputedStyle(root).getPropertyValue(name)) || 0;

  async function upload(job, image) {
    const res = await post('/api/image', image, { timeout: 120000, signal: job.controller.signal });
    job.controller.signal.throwIfAborted();
    if (!res.ok) throw new Error(res.error.message);
    job.refs.push({ image: res.data.image, name: image.name,
      ...(image.source ? { source: { ...image.source, import_id: job.id } } : {}) });
    job.done = job.refs.length;
    paint();
  }

  async function prepare(job) {
    job.state = 'splitting'; paint();
    if (job.pdf) {
      for await (const image of splitPdf(job.file, { signal: job.controller.signal, start: job.refs.length,
        onCount: total => { job.total = total; paint(); } })) await upload(job, image);
    } else if (!job.refs.length) {
      const images = await readImages([job.file]);
      if (!images.length) throw new Error('请选择 PDF、PNG、JPEG、GIF 或 WebP 文件。');
      job.total = 1;
      await upload(job, images[0]);
    }
  }

  async function finish(job) {
    if (!job.result) {
      const path = job.target ? '/api/draft/pages' : '/api/drafts';
      const body = job.target ? { id: job.target, add: job.refs }
        : { images: job.refs, hint: s.heroText.trim(), upload_id: job.id };
      const res = await post(path, body, { timeout: 120000, signal: job.controller.signal });
      job.controller.signal.throwIfAborted();
      if (!res.ok) throw new Error(res.error.message);
      job.result = job.target ? res.data : res.data.drafts[0];
    }
    const surface = root.querySelector('.page-manager') || root;
    const source = surface.querySelector(`[data-import="${job.id}"]`)?.getBoundingClientRect();
    if (job.pdf) { job.state = 'burst'; paint(); await delay(motion('--dur-pdf-burst')); }
    job.controller.signal.throwIfAborted();
    const oldPages = new Set((s.draft?.pages || []).map(p => p.id));
    const text = s.heroText;
    s.imports = s.imports.filter(x => x !== job);
    s.activeId = job.result.id;
    applyDraft(job.result);
    s.heroText = text;
    connect(); paint();
    if (job.pdf) {
      const added = [...(root.querySelector('.page-manager') || root).querySelectorAll('.page[data-page]')].filter(el => !oldPages.has(el.dataset.key));
      revealFrom(added, source, { duration: motion('--dur-pdf-reveal'), stagger: motion('--dur-pdf-stagger'),
        easing: getComputedStyle(root).getPropertyValue('--ease-out').trim() });
    }
    await refreshList(); paint();
  }

  async function pump() {
    if (running) return;
    running = true;
    const mine = epoch;
    try {
      while (mine === epoch && s.imports.length) {
        const job = s.imports[0];
        if (job.state === 'error') break;
        job.controller = new AbortController();
        job.target ??= s.draft?.status === 'staged' ? s.draft.id : null;
        try { await prepare(job); await finish(job); }
        catch (error) {
          if (!job.controller.signal.aborted && mine === epoch) {
            job.state = 'error'; job.error = pdfError(error); paint(); break;
          }
        }
      }
    } finally {
      running = false;
      if (s.imports.length && s.imports[0].state === 'queued') pump();
    }
  }

  async function take(files) {
    if (!files?.length) return;
    try {
      // 先完整准备新批次，再切换页面/追加队列；初始化失败不清掉已有草稿或队列。
      const jobs = [...files].map(file => ({ id: uploadId(), file,
        pdf: isPdf(file), name: file.name, state: 'queued', refs: [], done: 0, total: 0 }));
      if (s.draft && s.draft.status !== 'staged') await fresh();
      s.imports.push(...jobs);
      paint(); pump();
    } catch (error) {
      toast(`文件准备失败：${pdfError(error)}`, { tone: 'bad', ms: 6000 });
    }
  }

  function clear() {
    epoch += 1;
    s.imports.forEach(job => job.controller?.abort());
    s.imports = [];
  }

  return { take, clear,
    retry({ arg }) {
      const job = s.imports.find(x => x.id === arg);
      if (job?.state === 'error') { job.state = 'queued'; job.error = ''; paint(); pump(); }
    },
    remove({ arg }) {
      const job = s.imports.find(x => x.id === arg);
      if (job?.state === 'burst') return;
      job?.controller?.abort();
      s.imports = s.imports.filter(x => x.id !== arg);
      paint(); pump();
    },
  };
}
