import { get } from '../../core/api.js';
import { readImages } from '../../core/files.js';
import { toast } from '../../ui/feedback.js';
import { link } from './shared.js';

const formValue = (form, field) => form.elements.namedItem(field)?.value || '';
const rows = value => value.split('\n').map(x => x.trim()).filter(Boolean);

export function actions(h) {
  const { s, draw, send, navigate, refresh, alive } = h;
  return {
    navigate: ({ arg, event }) => { if (event.ctrlKey || event.metaKey || event.shiftKey) return; event.preventDefault(); navigate(arg); },
    search: ({ value }) => { s.q = value; h.search(); },
    filter: ({ value }) => { s.classificationId = value; h.loadList(); },
    more: () => h.loadList(true),
    listToggle: () => { s.listOpen = !s.listOpen; draw(); },
    newPrompt: async () => { if (s.busy || !await h.saveText() || !alive()) return;
      s.creatingPrompt = true; draw(); h.root.querySelector('[name="title"]')?.focus(); },
    cancelPrompt: () => { s.creatingPrompt = false; draw(); },
    async createPrompt({ el }) {
      const result = await send('/api/essay/prompt', { title: formValue(el, 'title'), text: formValue(el, 'text'),
        requirements: formValue(el, 'requirements'), metadata: { origin: formValue(el, 'origin') } });
      if (alive() && result) navigate(link('prompt', result.id));
    },
    async createAttempt({ el }) {
      const result = await send('/api/essay/attempt', { prompt_id: s.prompt.id, title: formValue(el, 'title') });
      if (alive() && result) navigate(link('attempt', result.id));
    },
    async classify({ el }) {
      const names = formValue(el, 'names').split(/[、,，\n]/).map(x => x.trim()).filter(Boolean);
      const result = await send('/api/essay/classify', { target_type: el.dataset.targetType,
        target_id: el.dataset.targetId, names });
      if (!alive() || !result) return;
      el.reset(); await refresh(); if (alive()) h.loadList();
    },
    showUpload: () => { s.showUpload = !s.showUpload; draw(); },
    async files({ el }) {
      const files = [...el.files];
      if (!files.length) return;
      if (s.files.length + files.length > 30 || files.some(f => f.size > 25 * 1024 * 1024)) {
        s.error = '一版最多 30 页，每张图片不超过 25MB。'; draw(); el.value = ''; return;
      }
      try {
        const images = await readImages(files);
        if (!alive()) return;
        if (!images.length) { s.error = '请选择 PNG、JPEG、GIF 或 WebP 作文图片。'; draw(); return; }
        s.files.push(...images); s.error = ''; el.value = ''; draw();
      } catch (_) { if (alive()) { s.error = '读取图片失败，请重新选择。'; draw(); } }
    },
    movePage: ({ arg }) => { const [index, direction] = arg.split(':').map(Number), to = index + direction;
      if (to < 0 || to >= s.files.length || s.busy) return;
      [s.files[index], s.files[to]] = [s.files[to], s.files[index]]; draw(); },
    removePage: ({ arg }) => { if (s.busy) return; s.files.splice(Number(arg), 1); draw(); },
    async upload() {
      if (!s.files.length || s.busy || !await h.saveText() || !alive()) return;
      const uploaded = [];
      for (const [index, file] of s.files.entries()) {
        s.uploadProgress = `正在保存第 ${index + 1} / ${s.files.length} 页…`;
        const result = await send('/api/image', file, { timeout: 120000 });
        if (!alive() || !result) return;
        uploaded.push(result.image);
      }
      const result = await send('/api/essay/version', { attempt_id: s.attempt.id, images: uploaded,
        metadata: { page_names: s.files.map(file => file.name) } });
      if (alive() && result) { s.files = []; s.uploadProgress = ''; navigate(link('version', result.id)); }
    },
    imagePage: ({ arg }) => { s.imagePage = Math.max(0, Math.min(s.version.images.length - 1, s.imagePage + Number(arg))); draw(); },
    text: ({ value }) => { s.textDraft = value; s.dirty = value !== s.version.corrected_text; draw(); },
    saveText: () => h.saveText(),
    async ocr() {
      const result = await send('/api/essay/ocr', { version_id: s.version.id });
      if (!alive() || !result) return;
      h.applyVersion(result); draw(); h.poll();
    },
    async confirm() {
      if (s.version.status !== 'proofreading' && !await h.saveText()) return;
      if (!alive()) return;
      const result = await send('/api/essay/confirm', { version_id: s.version.id,
        text: s.textDraft, revision: s.version.revision });
      if (!alive() || !result) return;
      s.dirty = false; h.applyVersion(result); await refresh();
      if (alive()) toast('正式转写已确认，修改次数保持不变');
    },
    refresh: () => refresh(),
    discuss: () => { const q = new URLSearchParams({ version: s.version.id, attempt: s.attempt.id, prompt: s.prompt.id });
      navigate(`#/assistant?${q}`); },
    async evaluate({ el }) {
      const result = await send('/api/essay/evaluation', { version_id: s.version.id,
        total_score: Number(formValue(el, 'total_score')), evaluator: formValue(el, 'evaluator'),
        summary: formValue(el, 'summary'), strengths: rows(formValue(el, 'strengths')),
        issues: rows(formValue(el, 'issues')), suggestions: rows(formValue(el, 'suggestions')) });
      if (!alive() || !result) return;
      el.reset(); await refresh(); if (alive()) toast('评价已保存到当前稿件');
    },
    async adopt({ arg }) {
      const result = await send('/api/essay/evaluation/adopt', { version_id: s.version.id, evaluation_id: arg });
      if (alive() && result) { h.applyVersion(result); draw(); }
    },
    async note({ el }) {
      const result = await send('/api/essay/note', { attempt_id: s.attempt.id, text: formValue(el, 'text'),
        version_id: el.elements.namedItem('version')?.checked ? s.version?.id : null });
      if (!alive() || !result) return;
      el.reset(); await refresh(); if (alive()) toast('讨论笔记已保存');
    },
    async compare({ arg }) {
      const versionId = s.version.id;
      const q = new URLSearchParams({ before_id: arg, after_id: versionId });
      const result = await get(`/api/essay/compare?${q}`);
      if (!alive() || s.version.id !== versionId) return;
      if (result.ok) s.diff = result.data; else s.error = result.error.message;
      draw();
    },
    closeDiff: () => { s.diff = null; draw(); },
  };
}
