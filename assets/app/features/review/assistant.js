/**
 * 复习助手（评分页右侧，窄屏为底部抽屉）：跟着当前选中的题，随时提问、让 AI 打分、写反馈（POST /api/review/ai，流式）。
 * 对话按「复习 + 题」存在模块级 Map 里：在页面之间切换不丢，刷新浏览器清空；不写 Ledger。
 * AI 的评分 / 反馈只是建议：点「采用」才经 /api/session/grade、/api/record/update 写入；
 * 题还没评分时「填入反馈」先暂存（s.pendingNotes），评分时一起写入。
 */
import { html, each } from '../../core/html.js';
import { markdown } from '../../core/markdown.js';
import { postStream } from '../../core/stream.js';
import { post } from '../../core/api.js';
import { readImages } from '../../core/files.js';
import { icon } from '../../ui/icons.js';
import { toast } from '../../ui/feedback.js';
import { genreShort } from '../../domain/genres.js';

const chats = new Map();
const MODE_TEXT = { grade: '请帮我打分', feedback: '帮我写一条复习反馈' };
const MARK = '【建议】';
const QUICK = [['怎么答', '这道题该从哪几个方面答？'], ['差在哪', '我的答案和参考答案差在哪？']];
let seq = 0;

const keyOf = (s, id) => `${s.session.id}:${id}`;
const chatOf = (s, id) => chats.get(keyOf(s, id)) || [];

export const initialAssistant = () => ({ text: '', attach: [], busy: null, open: false });

export function focusTarget(s) {
  const items = s.session?.items || [];
  const n = items.findIndex(x => x.id === s.focus);
  return n >= 0 ? { it: items[n], n: n + 1 } : null;
}

const toneOf = g => (g <= 0 ? 'chip--bad' : g === 1 ? 'chip--warn' : 'chip--ok');

function userMsg(m) {
  const pics = m.images?.length ? m.images.map(id => `/api/image?id=${encodeURIComponent(id)}`) : m.previews || [];
  return html`<div class="ai__msg ai__msg--user" data-key="${m.id}">
    ${pics.length ? html`<div class="ai__thumbs">${each(pics, (_, i) => i, src => html`<img src="${src}" alt="作答照片">`)}</div>` : ''}
    ${m.text ? html`<p>${m.text}</p>` : ''}
  </div>`;
}

function suggestion(m, it) {
  const sug = m.suggestion;
  if (!sug) return '';
  const hasGrade = sug.grade !== undefined;
  return html`<div class="ai__sug">
    <dl class="ai__sugbody">
      ${hasGrade ? html`<div><dt>建议评分</dt><dd><span class="chip ${toneOf(sug.grade)}">${sug.grade_label}</span></dd></div>` : ''}
      ${sug.note ? html`<div><dt>反馈</dt><dd>${sug.note}</dd></div>` : ''}
    </dl>
    ${m.adopted ? html`<p class="ai__adopted">${icon('check')}${m.adopted}</p>` : html`<div class="ai__sugacts">
      ${hasGrade ? html`<button class="btn btn--sm btn--primary" data-action="rv.aiAdopt" data-arg="${m.id}:all">${sug.note ? '采用评分和反馈' : '采用这个评分'}</button>` : ''}
      ${sug.note ? html`<button class="btn btn--sm" data-action="rv.aiAdopt" data-arg="${m.id}:note" title="${it.grade ? '改写这次记录的反馈' : '先放着，评分时一起写入'}">${hasGrade ? '只填反馈' : '填入反馈'}</button>` : ''}
    </div>`}
  </div>`;
}

function botMsg(m, it) {
  const live = m.status === 'streaming';
  const text = live ? m.text.split(MARK)[0] : m.text;
  return html`<div class="ai__msg ai__msg--bot" data-key="${m.id}" data-status="${m.status}">
    ${live && !text.trim() ? html`<p class="shimmer ai__wait">${m.thinking ? '正在思考…' : '正在看题…'}</p>` : ''}
    ${text.trim() ? html`<div class="md ${live ? 'is-live' : ''}">${markdown(text)}</div>` : ''}
    ${m.status === 'error' ? html`<p class="callout callout--bad ai__err">${m.error}
      <button class="linkish" data-action="rv.aiRetry" data-arg="${m.id}">重试</button></p>` : ''}
    ${m.status === 'stopped' ? html`<p class="ai__note">已停止</p>` : ''}
    ${suggestion(m, it)}
  </div>`;
}

const empty = () => html`<div class="ai__empty">
  <p>对着这道题随便问：思路、采分点、你的答案哪里不够。</p>
  <p>把作答打出来或拍照发来，点「打分」让 AI 对照采分点给建议，点「写反馈」生成一句复习反馈。点「采用」才会记下。</p>
</div>`;

export function assistant(s) {
  const t = focusTarget(s);
  const a = s.ai;
  if (!t) return html`<aside class="ai ${a.open ? 'is-open' : ''}" aria-label="复习助手"><p class="empty">点一道题开始</p></aside>`;
  const { it, n } = t;
  const log = chatOf(s, it.id);
  const busy = a.busy === keyOf(s, it.id);
  const locked = Boolean(a.busy);
  const off = locked ? html`disabled` : '';
  return html`<aside class="ai ${a.open ? 'is-open' : ''}" aria-label="复习助手" data-genre="${it.genre}">
    <header class="ai__head">
      <span class="ai__title">${icon('spark')}复习助手</span>
      <span class="ai__target"><span class="genre-dot"></span>第 ${n} 题 · ${it.genre === 'dictation' ? '默写' : it.qtype || genreShort(it.genre)}</span>
      <button class="btn btn--ghost btn--icon ai__close" data-action="rv.aiToggle" aria-label="收起复习助手">${icon('close')}</button>
    </header>
    <div class="ai__log" id="ai-log" aria-live="polite">${log.length ? each(log, m => m.id, m => (m.role === 'user' ? userMsg(m) : botMsg(m, it))) : empty()}</div>
    <div class="ai__quick">
      <button class="chip chip--info" data-action="rv.aiMode" data-arg="grade" ${off} title="对照参考答案的采分点给出评分建议">${icon('check')}打分</button>
      <button class="chip chip--info" data-action="rv.aiMode" data-arg="feedback" ${off} title="写一句复习反馈：错在哪、漏了哪个采分点">写反馈</button>
      ${each(QUICK, q => q[0], q => html`<button class="chip" data-action="rv.aiAsk" data-arg="${q[1]}" ${off}>${q[0]}</button>`)}
    </div>
    <div class="ai__composer">
      ${a.attach.length ? html`<div class="ai__thumbs ai__thumbs--attach">${each(a.attach, (_, i) => i, (x, i) => html`<span class="ai__att">
        <img src="${x.data}" alt="${x.name}"><button class="btn btn--icon btn--sm" data-action="rv.aiUnattach" data-arg="${i}" aria-label="去掉这张">${icon('close')}</button></span>`)}</div>` : ''}
      <textarea id="ai-composer" class="ai__input" rows="2" data-input="rv.aiText" placeholder="问这道题，或写下你的作答（回车发送，Shift+回车换行）" aria-label="问复习助手">${a.text}</textarea>
      <div class="ai__bar">
        <label class="btn btn--ghost btn--sm ai__pic" title="拍照或选图：你的作答">${icon('image')}作答照片
          <input type="file" accept="image/*" multiple class="visually-hidden" data-change="rv.aiAttach"></label>
        ${busy ? html`<button class="btn btn--sm" data-action="rv.aiStop">停止</button>`
    : html`<button class="btn btn--sm btn--primary ai__send" data-action="rv.aiSend" ${off}>${icon('send')}发送</button>`}
      </div>
    </div>
  </aside>`;
}

/** 复习助手的动作。ctx：render / soon（下一帧重画）/ clearComposer / refresh（重新拉复习）/ bus。 */
export function assistantActions(s, { render, soon, clearComposer, refresh, bus }) {
  let controller = null;

  async function send(mode, override) {
    const t = focusTarget(s);
    if (!t || s.ai.busy) return;
    const { it } = t;
    const text = String(override?.text ?? s.ai.text).trim();
    const attach = override ? override.attach || [] : s.ai.attach;
    if (mode === 'ask' && !text && !attach.length) return;
    const key = keyOf(s, it.id);
    if (!chats.has(key)) chats.set(key, []);
    const log = chats.get(key);
    const history = log.filter(m => m.status !== 'error' && (m.text || m.images?.length))
      .map(m => ({ role: m.role, text: m.text, images: m.images || [] }));
    const user = { id: `m${++seq}`, role: 'user', text: text || MODE_TEXT[mode] || '', images: [], previews: attach.map(x => x.data) };
    const bot = { id: `m${++seq}`, role: 'assistant', text: '', status: 'streaming', thinking: false, retry: { mode, text, attach } };
    log.push(user, bot);
    if (!override) { s.ai.text = ''; s.ai.attach = []; clearComposer(); }
    s.ai.busy = key; s.stickAi = true; render();
    controller = new AbortController();
    const body = { session_id: s.session.id, item_id: it.id, mode, text, images: attach, history,
      revealed: s.revealed.has(it.id) || Boolean(it.grade) };
    const res = await postStream('/api/review/ai', body, ev => {
      if (ev.type === 'start') { user.images = ev.images || []; if (user.images.length) user.previews = []; } else if (ev.type === 'delta') {
        if (ev.kind === 'thinking') bot.thinking = true; else bot.text += ev.text;
        soon();
      } else if (ev.type === 'done') { bot.text = ev.reply; bot.suggestion = ev.suggestion; bot.status = 'done'; } else if (ev.type === 'error') { bot.status = 'error'; bot.error = ev.msg; }
    }, { signal: controller.signal });
    controller = null;
    if (!res.ok) { bot.status = res.error.code === 'aborted' ? 'stopped' : 'error'; bot.error = res.error.message; } else if (bot.status === 'streaming') { bot.status = 'error'; bot.error = '回答中断了，可以重试'; }
    if (mode !== 'ask' && bot.status === 'done') s.revealed.add(it.id);
    s.ai.busy = null; render();
  }

  async function adopt(message, what) {
    const t = focusTarget(s);
    const sug = message?.suggestion;
    if (!t || !sug) return;
    const { it } = t;
    if (what === 'all') {
      const note = sug.note ?? s.pendingNotes.get(it.id) ?? it.grade?.note ?? '';
      const r = await post('/api/session/grade', { session_id: s.session.id, item_id: it.id, grade: sug.grade, note });
      if (!r.ok) { toast(r.error.message, { tone: 'bad' }); return; }
      s.session = r.data.session; s.revealed.add(it.id); s.pendingNotes.delete(it.id);
      message.adopted = `已记为「${sug.grade_label}」${sug.note ? '，反馈已写入' : ''}`;
      bus.emit('library:changed'); toast('已按建议评分');
    } else if (it.grade) {
      const r = await post('/api/record/update', { commit_id: it.grade.commit_id, note: sug.note });
      if (!r.ok) { toast(r.error.message, { tone: 'bad' }); return; }
      message.adopted = '反馈已写入这次记录';
      await refresh(); toast('反馈已保存');
    } else {
      s.pendingNotes.set(it.id, sug.note);
      message.adopted = '已填入反馈，评分时一起写入';
    }
    render();
  }

  const find = id => { const t = focusTarget(s); return t ? chatOf(s, t.it.id).find(m => m.id === id) : null; };

  const actions = {
    aiText: ({ el }) => { s.ai.text = el.value; },
    aiSend: () => send('ask'),
    aiMode: ({ arg }) => send(arg),
    aiAsk: ({ arg }) => send('ask', { text: arg }),
    aiStop: () => controller?.abort(),
    async aiAttach({ el }) { const files = [...el.files]; el.value = ''; s.ai.attach.push(...await readImages(files)); render(); },
    aiUnattach: ({ arg }) => { s.ai.attach.splice(Number(arg), 1); render(); },
    aiToggle: () => { s.ai.open = !s.ai.open; render(); },
    aiAdopt: ({ arg }) => { const [id, what] = arg.split(':'); return adopt(find(id), what); },
    aiRetry: ({ arg }) => {
      const t = focusTarget(s);
      const log = t ? chatOf(s, t.it.id) : [];
      const at = log.findIndex(m => m.id === arg);
      if (at < 1 || s.ai.busy) return null;
      const { retry } = log[at];
      log.splice(at - 1, 2);
      return send(retry.mode, { text: retry.text, attach: retry.attach });
    },
  };

  /** 文档级：回车发送（Shift+回车换行、输入法组字时不算）、往输入框里粘贴截图当作答照片。返回解绑函数。 */
  function bindKeys(root) {
    const onKey = event => {
      if (event.target.id !== 'ai-composer' || event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      send('ask');
    };
    const onPaste = async event => {
      if (event.target.id !== 'ai-composer') return;
      const files = [...(event.clipboardData?.files || [])].filter(f => f.type.startsWith('image/'));
      if (!files.length) return;
      event.preventDefault();
      s.ai.attach.push(...await readImages(files)); render();
    };
    root.addEventListener('keydown', onKey);
    root.addEventListener('paste', onPaste);
    return () => { root.removeEventListener('keydown', onKey); root.removeEventListener('paste', onPaste); };
  }

  return { actions, bindKeys, abort: () => controller?.abort() };
}
