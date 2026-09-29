/** PDF 在浏览器逐页转图。仅首次选 PDF 时加载本地 PDF.js；不上传原件、不依赖 Python 扩展。 */
import { toElement } from './dom.js';
import { html } from './html.js';

export const FILE_ACCEPT = 'image/*,application/pdf,.pdf';
export const isPdf = file => file.type === 'application/pdf' || /\.pdf$/i.test(file.name || '');
const BASE = '/assets/vendor/pdfjs/';
const MAX_BYTES = 50 * 1024 * 1024;
const MAX_PAGES = 60;
let library;

async function pdfLibrary() {
  library ||= import('/assets/vendor/pdfjs/build/pdf.min.mjs').then(pdf => {
    pdf.GlobalWorkerOptions.workerSrc = `${BASE}build/pdf.worker.min.mjs`;
    return pdf;
  }).catch(error => { library = null; throw error; });
  return library;
}

export function pdfError(error) {
  if (error?.name === 'PasswordException') return '这份 PDF 需要密码，请先解锁后重新上传。';
  if (error?.name === 'InvalidPDFException') return '无法读取这份 PDF，文件可能已损坏。';
  if (error?.message?.includes('dynamically imported')) return 'PDF 组件加载失败，请重试。';
  return error?.message || '拆分失败，请重试。';
}

/** 一次只保留一张画布；start 可从已经上传成功的页之后继续。 */
export async function* splitPdf(file, { signal, onCount, start = 0 }) {
  if (file.size > MAX_BYTES) throw new Error('PDF 超过 50 MB，请先缩小文件或分成几份。');
  if (!file.size) throw new Error('这份 PDF 是空文件。');
  const pdf = await pdfLibrary();
  signal.throwIfAborted();
  const data = new Uint8Array(await file.arrayBuffer());
  signal.throwIfAborted();
  const task = pdf.getDocument({ data, cMapUrl: `${BASE}cmaps/`, cMapPacked: true,
    standardFontDataUrl: `${BASE}standard_fonts/`, wasmUrl: `${BASE}wasm/`, isEvalSupported: false, verbosity: 0 });
  let renderTask;
  const abort = () => { renderTask?.cancel(); task.destroy().catch(() => {}); };
  signal.addEventListener('abort', abort, { once: true });
  try {
    const doc = await task.promise;
    if (doc.numPages > MAX_PAGES) throw new Error(`这份 PDF 有 ${doc.numPages} 页，单次最多拆分 ${MAX_PAGES} 页，请先分成几份。`);
    onCount(doc.numPages);
    for (let n = start + 1; n <= doc.numPages; n += 1) {
      signal.throwIfAborted();
      const page = await doc.getPage(n);
      const base = page.getViewport({ scale: 1 });
      const scale = Math.min(1600 / base.width, Math.sqrt(8000000 / (base.width * base.height)));
      const viewport = page.getViewport({ scale });
      const canvas = toElement(html`<canvas></canvas>`);
      canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
      try {
        renderTask = page.render({ canvasContext: canvas.getContext('2d'), viewport });
        await renderTask.promise;
        signal.throwIfAborted();
        yield { name: `${file.name} · 第 ${n} 页`, data: canvas.toDataURL('image/jpeg', 0.9),
          source: { name: file.name, page: n } };
      } finally {
        canvas.width = 0; canvas.height = 0;
        page.cleanup(); renderTask = null;
      }
    }
  } finally {
    signal.removeEventListener('abort', abort);
    await task.destroy();
  }
}
