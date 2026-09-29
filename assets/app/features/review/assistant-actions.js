/**
 * 复习助手的动作：发送（提问 / 打分 / 写反馈）、流式事件、停止、重试、采用建议、引用、作答照片、折叠思考与查阅。
 * 流式协议见 AI/api.md「复习助手」：start → block / delta / end / tool … → done | error。
 * 发给后端的历史只带每轮的文字（助手那边另带「查阅过什么」的标签），不带查到的内容：需要时模型会再查。
 */
import { post } from '../../core/api.js';
import { postStream } from '../../core/stream.js';
import { readImages } from '../../core/files.js';
import { toast } from '../../ui/feedback.js';
import { chats, chatOf, keyOf } from './assistant.js';
import { focusTarget } from './focus.js';

const MODE_TEXT = { grade: '请对照参考答案给我的作答打分。', feedback: '帮我写一条这次的复习反馈。' };
const LIVE = ['live', 'preparing', 'running'];
let seq = 0;

export const initialAssistant = () => ({ text: '', attach: [], refs: [], busy: null, open: false });

export function assistantActions(s, { root, render, soon, refresh, bus }) {
  let controller = null;

  const toolLabels = m => (m.blocks || []).filter(b => b.kind === 'tool' && b.status === 'done').map(b => b.label || b.name);
  const replyOf = m => m.text || (m.blocks || []).filter(b => b.kind === 'text').map(b => b.text).join('\n').trim();

  function history(log) {
    return log.flatMap(m => {
      if (m.role === 'user') return [{ role: 'user', text: m.text || '', images: m.images || [], refs: (m.refs || []).map(r => ({ text: r.text, where: r.where, label: r.label })) }];
      if (m.status === 'error' || !replyOf(m)) return [];
      return [{ role: 'assistant', text: replyOf(m), tools: toolLabels(m) }];
    });
  }

  function settle(bot) {
    const now = Date.now();
    for (const b of bot.blocks) if (LIVE.includes(b.status)) { b.status = b.kind === 'tool' ? 'error' : 'done'; b.ended = now; }
  }

  function apply(bot, user, ev, it, mode) {
    const find = id => bot.blocks.find(b => b.id === id);
    if (ev.type === 'start') {
      if (ev.images?.length) { user.images = ev.images; user.previews = []; }
    } else if (ev.type === 'block') {
      bot.blocks.push({ id: ev.id, kind: ev.kind, text: '', status: ev.kind === 'tool' ? ev.status || 'preparing' : 'live', name: ev.name || '', at: Date.now() });
    } else if (ev.type === 'delta') {
      const b = find(ev.id);
      if (b) b.text += ev.text;
    } else if (ev.type === 'end') {
      const b = find(ev.id);
      if (b) { b.status = 'done'; b.ended = Date.now(); }
    } else if (ev.type === 'tool') {
      const b = find(ev.id);
      if (b) {
        for (const k of ['status', 'label', 'summary', 'result', 'name']) if (ev[k] !== undefined) b[k] = ev[k];
        if (ev.status === 'done' || ev.status === 'error') b.ended = Date.now();
      }
    } else if (ev.type === 'done') {
      settle(bot);
      const texts = bot.blocks.filter(b => b.kind === 'text');
      if (texts.length) texts[texts.length - 1].text = ev.reply;
      else if (ev.reply) bot.blocks.push({ id: 'final', kind: 'text', text: ev.reply, status: 'done', at: Date.now() });
      Object.assign(bot, { status: 'done', text: ev.reply, suggestion: ev.suggestion, usage: ev.usage, tools: ev.tools, seconds: ev.timing?.seconds });
      if (mode !== 'ask') s.revealed.add(it.id);        // 打分 / 写反馈时答案已经摆在面前了
    } else if (ev.type === 'error') {
      settle(bot);
      bot.status = 'error'; bot.error = ev.msg;
    }
    s.stickAi = true;
    soon();
  }

  async function send(mode = 'ask', override = null) {
    const t = focusTarget(s);
    const a = s.ai;
    if (!t || a.busy) return;
    const { it } = t;
    const text = (override ? override.text : a.text).trim();
    const attach = override ? override.attach : a.attach;
    const refs = override ? override.refs : a.refs;
    if (mode === 'ask' && !text && !attach.length && !refs.length) return;
    const key = keyOf(s, it.id);
    const log = [...chatOf(s, it.id)];
    const past = history(log);
    const user = { id: `m${++seq}`, role: 'user', text: text || (refs.length && mode === 'ask' ? '' : MODE_TEXT[mode] || ''),
      images: [], previews: attach.map(x => x.data), refs: refs.map(r => ({ ...r })) };
    const bot = { id: `m${++seq}`, role: 'assistant', status: 'streaming', blocks: [], text: '', retry: { mode, text, attach, refs } };
    chats.set(key, [...log, user, bot]);
    if (!override) { a.text = ''; a.attach = []; a.refs = []; }
    a.busy = key; s.stickAi = true; render();
    controller = new AbortController();
    const body = {
      session_id: s.session.id, item_id: it.id, mode, text,
      images: attach.map(x => ({ name: x.name, data: x.data })),
      refs: refs.map(r => ({ text: r.text, where: r.where, label: r.label })),
      history: past, revealed: [...s.revealed],
    };
    const r = await postStream('/api/review/ai', body, ev => apply(bot, user, ev, it, mode), { signal: controller.signal });
    controller = null;
    a.busy = null;
    if (bot.status === 'streaming') {
      settle(bot);
      if (!r.ok && r.error.code === 'aborted') bot.status = 'stopped';
      else { bot.status = 'error'; bot.error = r.ok ? '回答中断了，可以重试' : r.error.message; }
    }
    render();
    if (bot.status === 'done' && !root.querySelector('#rv-ai')?.contains(root.ownerDocument.activeElement)) {
      root.querySelector('#ai-composer')?.focus({ preventScroll: true });
    }
  }

  async function adopt(msgId, what) {
    const t = focusTarget(s);
    if (!t) return;
    const { it } = t;
    const msg = chatOf(s, it.id).find(m => m.id === msgId);
    const sug = msg?.suggestion;
    if (!sug) return;
    const done = label => { msg.adopted = label; render(); bus.emit('library:changed'); };
    if (what === 'all' && sug.grade !== undefined) {
      const note = sug.note ?? s.pendingNotes.get(it.id) ?? it.grade?.note ?? '';
      const r = await post('/api/session/grade', { session_id: s.session.id, item_id: it.id, grade: sug.grade, note });
      if (!r.ok) { toast(r.error.message, { tone: 'bad' }); return; }
      s.pendingNotes.delete(it.id); s.revealed.add(it.id);
      s.session = r.data.session;
      done(`已记为「${sug.grade_label}」${sug.note ? '，反馈已写入' : ''}`);
      return;
    }
    if (!sug.note) return;
    if (it.grade) {
      const r = await post('/api/record/update', { commit_id: it.grade.commit_id, note: sug.note });
      if (!r.ok) { toast(r.error.message, { tone: 'bad' }); return; }
      await refresh();
      done('反馈已写入这次记录');
    } else {
      s.pendingNotes.set(it.id, sug.note); s.revealed.add(it.id);
      done('已填进反馈，评分时一起写入');
    }
  }

  function composerFocus() {
    root.querySelector('#ai-composer')?.focus({ preventScroll: true });
  }

  function open() {
    s.ai.open = true; s.stickAi = true; render();
    composerFocus();
  }

  const actions = {
    aiText: ({ el }) => { s.ai.text = el.value; },
    aiSend: () => send('ask'),
    aiMode: ({ arg }) => send(arg),
    aiAsk: ({ arg }) => { s.ai.text = arg; return send('ask'); },
    aiStop: () => controller?.abort(),
    aiToggle: () => { s.ai.open = !s.ai.open; render(); if (s.ai.open) composerFocus(); },
    aiFold: ({ arg, el }) => {
      const now = el.getAttribute('aria-expanded') === 'true';
      s.open.set(arg, !now); render();
    },
    aiUnref: ({ arg }) => { s.ai.refs.splice(Number(arg), 1); render(); },
    aiUnattach: ({ arg }) => { s.ai.attach.splice(Number(arg), 1); render(); },
    async aiAttach({ el }) {
      const list = await readImages(el.files);
      el.value = '';
      s.ai.attach.push(...list); render();
    },
    aiAdopt: ({ arg }) => { const [id, what] = arg.split(':'); return adopt(id, what); },
    aiRetry({ arg }) {
      const t = focusTarget(s);
      if (!t || s.ai.busy) return;
      const log = chatOf(s, t.it.id);
      const at = log.findIndex(m => m.id === arg);
      const bot = log[at];
      if (!bot?.retry) return;
      chats.set(keyOf(s, t.it.id), log.slice(0, Math.max(0, at - 1)));
      return send(bot.retry.mode, bot.retry);
    },
    /** 选中卷面文字后点「引用」：放进输入框上方，打开助手。 */
    quote: () => {
      const q = s.quote;
      if (!q) return;
      if (!s.ai.refs.some(r => r.text === q.text)) s.ai.refs.push({ text: q.text, where: q.where, label: q.label });
      s.quote = null;
      root.ownerDocument.getSelection()?.removeAllRanges();
      open();
    },
  };

  /** 回车发送（Shift+回车换行、输入法组字时不算）；在输入框里粘贴图片当作答照片。返回解绑函数。 */
  function bindComposer() {
    const doc = root.ownerDocument;
    const onKey = event => {
      if (event.target?.id !== 'ai-composer') return;
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send('ask'); }
      if (event.key === 'Escape') event.target.blur();
    };
    const onPaste = async event => {
      if (event.target?.id !== 'ai-composer') return;
      const files = [...(event.clipboardData?.files || [])].filter(f => f.type.startsWith('image/'));
      if (!files.length) return;
      event.preventDefault();
      s.ai.attach.push(...await readImages(files)); render();
    };
    doc.addEventListener('keydown', onKey);
    doc.addEventListener('paste', onPaste);
    return () => { doc.removeEventListener('keydown', onKey); doc.removeEventListener('paste', onPaste); };
  }

  return { actions, bindComposer, open, abort: () => controller?.abort() };
}
