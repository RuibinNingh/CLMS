import { morph } from '../../core/dom.js';
import { get, post } from '../../core/api.js';
import { defineActions } from '../../core/events.js';
import { view } from './view.js';
import { actions } from './actions.js';

export const page = {
  id: 'essays', title: '作文', icon: 'entry',
  mount(root, ctx) {
    const query = new URLSearchParams(location.hash.split('?')[1] || '');
    const s = { prompts: [], total: 0, classifications: [], classificationId: '', q: '', limit: 60,
      prompt: null, attempt: null, version: null, files: [], imagePage: 0, textDraft: '', dirty: false,
      showUpload: false, creatingPrompt: false, diff: null, error: '', loading: true,
      detailLoading: true, busy: false, uploadProgress: '', listOpen: false };
    let alive = true, listSeq = 0, detailSeq = 0, searchTimer = 0, pollTimer = 0;
    const draw = () => { if (alive) morph(root, view(s)); };
    const context = () => ctx.bus.emit('context', { prompt_id: s.prompt?.id,
      attempt_id: s.attempt?.id, version_id: s.version?.id, essay_version_id: s.version?.id });

    async function loadList(more = false) {
      const mine = ++listSeq;
      const q = new URLSearchParams({ q: s.q, classification_id: s.classificationId, limit: s.limit,
        offset: more ? s.prompts.length : 0 });
      s.loading = true;
      const result = await get(`/api/essays?${q}`);
      if (!alive || mine !== listSeq) return;
      s.loading = false;
      if (result.ok) {
        s.prompts = more ? [...s.prompts, ...result.data.prompts] : result.data.prompts;
        s.total = result.data.total; s.classifications = result.data.classifications;
      } else s.error = result.error.message;
      draw();
    }

    function applyVersion(version) {
      const same = s.version?.id === version?.id;
      if (!same || !s.dirty) s.textDraft = version?.corrected_text || '';
      if (!same) { s.dirty = false; s.imagePage = 0; s.diff = null; }
      s.version = version;
    }

    function schedulePoll() {
      clearTimeout(pollTimer);
      if (alive && s.version?.status === 'ocr_running') {
        pollTimer = setTimeout(() => refresh(), 1200);
      }
    }

    async function refresh() {
      const mine = ++detailSeq;
      if (s.attempt) {
        const result = await get(`/api/essay/attempt?id=${encodeURIComponent(s.attempt.id)}`);
        if (!alive || mine !== detailSeq) return false;
        if (result.ok) {
          const selected = s.version?.id || result.data.current_version_id;
          s.attempt = result.data; s.prompt = result.data.prompt;
          applyVersion(result.data.versions.find(v => v.id === selected) || result.data.versions.at(-1));
        } else { s.error = result.error.message; draw(); return false; }
      } else if (s.prompt) {
        const result = await get(`/api/essay/prompt?id=${encodeURIComponent(s.prompt.id)}`);
        if (!alive || mine !== detailSeq) return false;
        if (result.ok) s.prompt = result.data;
        else { s.error = result.error.message; draw(); return false; }
      }
      context(); draw(); schedulePoll();
      return true;
    }

    async function selectInitial() {
      const mine = ++detailSeq;
      const versionId = query.get('version'), attemptId = query.get('attempt'), promptId = query.get('prompt');
      let version, attempt;
      if (versionId) {
        const result = await get(`/api/essay/version?id=${encodeURIComponent(versionId)}`);
        if (!alive || mine !== detailSeq) return;
        if (!result.ok) { s.error = result.error.message; s.detailLoading = false; draw(); return; }
        version = result.data;
      }
      if (attemptId || version) {
        const result = await get(`/api/essay/attempt?id=${encodeURIComponent(version?.attempt_id || attemptId)}`);
        if (!alive || mine !== detailSeq) return;
        if (result.ok) attempt = result.data; else s.error = result.error.message;
        if (attempt) {
          s.attempt = attempt; s.prompt = attempt.prompt;
          applyVersion(version || attempt.versions.at(-1));
        }
      } else if (promptId) {
        const result = await get(`/api/essay/prompt?id=${encodeURIComponent(promptId)}`);
        if (!alive || mine !== detailSeq) return;
        if (result.ok) s.prompt = result.data; else s.error = result.error.message;
      }
      s.detailLoading = false; context(); draw(); schedulePoll();
    }

    async function send(path, body, options = {}) {
      if (!alive || s.busy) return null;
      s.busy = true; s.error = ''; draw();
      const result = await post(path, body, options);
      if (!alive) return null;
      s.busy = false;
      if (!result.ok) { s.error = result.error.message; draw(); return null; }
      draw(); return result.data;
    }

    async function saveText() {
      if (!s.dirty) return true;
      const result = await send('/api/essay/correct', { version_id: s.version.id,
        text: s.textDraft, revision: s.version.revision });
      if (!alive || !result) return false;
      s.dirty = false; applyVersion(result); draw();
      return true;
    }

    async function navigate(hash) {
      if (s.busy || !await saveText() || !alive) return;
      location.hash = hash;
    }

    const helpers = { s, root, ctx, draw, loadList, refresh, send, saveText, navigate, applyVersion,
      alive: () => alive, poll: schedulePoll,
      search: () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadList(), 250); } };
    const off = defineActions('es', actions(helpers));
    draw(); loadList(); selectInitial();
    return () => { alive = false; ++listSeq; ++detailSeq; clearTimeout(searchTimer); clearTimeout(pollTimer); off(); };
  },
};
