import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get, post } from '../../core/api.js';
import { blocks, isRunning } from './model.js';
import { view } from './view.js';

export const page = {
  id: 'assistant', title: '全局助手', icon: 'spark', workbench: true,
  mount(root, { store, bus }) {
    const query = new URLSearchParams(location.hash.split('?')[1] || '');
    const context = { ...(store.get().assistantContext || {}) };
    for (const key of ['item', 'session', 'prompt', 'attempt', 'version']) if (query.get(key)) context[`${key}_id`] = query.get(key);
    const s = { conversations: [], conversation: null, events: [], cursor: 0, run: null, status: null, context,
      open: new Map(), overrides: new Map(), input: '', sending: false, deciding: false, error: '', loading: true, rail: false };
    let alive = true; let generation = 0; let timer = 0; let pollController = null;

    function draw() {
      if (!alive) return;
      const log = root.querySelector('#global-assistant-log');
      const stick = !log || log.scrollHeight - log.scrollTop - log.clientHeight < 80;
      morph(root, view(s));
      const next = root.querySelector('#global-assistant-log');
      if (next && stick) next.scrollTop = next.scrollHeight;
    }
    function fail(res) { if (alive) { s.error = res.error.message; draw(); } }
    function cancelPoll() { clearTimeout(timer); timer = 0; pollController?.abort(); pollController = null; }
    async function loadList() {
      const res = await get('/api/assistant/conversations');
      if (!alive) return;
      if (res.ok) { s.conversations = res.data.conversations; draw(); }
    }
    async function poll(id, mine) {
      if (!alive || mine !== generation) return;
      pollController = new AbortController();
      const res = await get(`/api/assistant/events?run_id=${encodeURIComponent(id)}&after=${s.cursor}&wait=20`, { signal: pollController.signal });
      if (!alive || mine !== generation) return;
      pollController = null;
      if (!res.ok) { if (res.error.code !== 'timeout') fail(res); timer = setTimeout(() => poll(id, mine), 1000); return; }
      const seen = new Set(s.events.map(event => event.i));
      s.events.push(...res.data.events.filter(event => !seen.has(event.i))); s.cursor = res.data.cursor; s.run = res.data.run;
      draw();
      if (res.data.has_more || isRunning(s.run)) timer = setTimeout(() => poll(id, mine), res.data.has_more ? 0 : 150);
      else { loadList(); bus.emit('library:changed'); }
    }
    async function open(id) {
      cancelPoll(); const mine = ++generation; s.loading = true; s.error = ''; s.rail = false; s.sending = false; s.deciding = false; draw();
      const res = await get(`/api/assistant/conversation?id=${encodeURIComponent(id)}`);
      if (!alive || mine !== generation) return;
      s.loading = false;
      if (!res.ok) { fail(res); return; }
      s.conversation = res.data.conversation; s.events = s.conversation.events; s.cursor = s.conversation.cursor;
      s.run = s.conversation.runs.at(-1) || null; s.open = new Map(); s.overrides = new Map();
      if (!Object.keys(s.context).length) s.context = s.conversation.context || {};
      draw(); if (isRunning(s.run)) poll(s.run.id, mine);
    }
    async function create() {
      const res = await post('/api/assistant/conversation/create', { context: s.context });
      if (!alive) return null;
      if (!res.ok) { fail(res); return null; }
      await loadList(); return res.data.conversation;
    }
    async function send() {
      const text = s.input.trim(); if (!text || s.sending) return;
      const mine = generation; s.sending = true; s.error = ''; draw();
      let conversation = s.conversation;
      if (!conversation) conversation = await create();
      if (!alive || mine !== generation) return;
      if (!conversation) { s.sending = false; draw(); return; }
      s.conversation = conversation;
      const res = await post('/api/assistant/message', { conversation_id: conversation.id, text, context: s.context });
      if (!alive || mine !== generation) return;
      s.sending = false;
      if (!res.ok) { fail(res); return; }
      s.input = ''; const input = root.querySelector('#global-assistant-input'); if (input) input.value = '';
      cancelPoll(); s.run = { id: res.data.run_id, status: 'running' }; draw(); poll(res.data.run_id, mine); loadList();
    }
    const undefine = defineActions('ga', {
      input({ value }) { s.input = value; draw(); },
      send,
      quick({ arg }) { s.input = arg; const input = root.querySelector('#global-assistant-input'); if (input) input.value = arg; send(); },
      open: ({ arg }) => open(arg),
      async new() { cancelPoll(); ++generation; s.conversation = null; s.events = []; s.cursor = 0; s.run = null; s.input = ''; s.loading = false; s.error = ''; s.sending = false; s.deciding = false; s.rail = false; s.overrides = new Map(); draw(); root.querySelector('#global-assistant-input')?.focus(); },
      rail() { s.rail = !s.rail; draw(); },
      clearContext() { s.context = {}; store.set({ assistantContext: null }); draw(); },
      toggle({ arg }) { const row = blocks(s.events).find(item => item.id === arg); const current = s.open.has(arg) ? s.open.get(arg) : ['live', 'preparing'].includes(row?.status); s.open.set(arg, !current); draw(); },
      async stop() { if (!s.run) return; const mine = generation; const res = await post('/api/assistant/abort', { run_id: s.run.id }); if (!alive || mine !== generation) return; if (!res.ok) fail(res); },
      async decide({ arg }) {
        if (s.deciding) return;
        const mine = generation; const [id, revision, decision] = arg.split('|'); s.deciding = true; s.error = ''; draw();
        const res = await post('/api/ai-review/decide', { id, expected_revision: Number(revision), decision });
        if (!alive || mine !== generation) return;
        s.deciding = false;
        if (!res.ok) {
          fail(res); const detail = await get(`/api/ai-review/detail?id=${encodeURIComponent(id)}`);
          if (alive && mine === generation && detail.ok) { s.overrides.set(id, detail.data.item); draw(); } return;
        }
        s.overrides.set(id, res.data.item); draw(); bus.emit('library:changed');
      },
    });
    function keydown(event) {
      if (event.target.id === 'global-assistant-input' && event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send(); }
      if (event.key === 'Escape' && s.rail) { s.rail = false; draw(); }
    }
    root.addEventListener('keydown', keydown);
    (async () => {
      const res = await get('/api/assistant/status'); if (!alive) return;
      if (res.ok) s.status = res.data; else fail(res);
      await loadList(); if (!alive) return;
      const linked = query.get('conversation') || query.get('id');
      if (linked) await open(linked);
      else if (!Object.keys(s.context).length && s.conversations.length) await open(s.conversations[0].id);
      else { s.loading = false; draw(); }
    })();
    draw();
    return () => { alive = false; ++generation; cancelPoll(); undefine(); root.removeEventListener('keydown', keydown); };
  },
};
