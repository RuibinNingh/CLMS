import { html, each } from '../../core/html.js';
import { markdown } from '../../core/markdown.js';
import { icon } from '../../ui/icons.js';
import { blocks, isRunning, STATUS } from './model.js';

const pretty = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
const opened = (s, block) => s.open.has(block.id) ? s.open.get(block.id) : ['live', 'preparing'].includes(block.status);

function operation(row, s) {
  row = s.overrides.get(row.id) || row;
  const pending = row.status === 'pending_confirmation';
  const preview = row.preview || {};
  const session = row.tool === 'session.create';
  const result = row.result || {};
  return html`<section class="ga-review" data-testid="assistant-confirm" data-operation="${row.id}">
    <div class="ga-review__head"><strong>${row.label || '正式学习操作'}</strong><span class="chip">${STATUS[row.status] || row.status}</span></div>
    <p class="muted">版本 ${row.revision} · ${row.source === 'assistant' ? '内置助手' : row.source}</p>
    ${session ? html`<p>${preview.title || '语文复习'} · ${preview.minutes || 0} 分钟 · ${preview.count} 题</p>
      <ol class="ga-review__items">${each(preview.items || [], item => item.id, item => html`<li>${item.label || item.id}<small>${item.stem}</small></li>`)}</ol>`
      : html`<p>${preview.target?.label || preview.target?.id || ''}</p><div class="ga-review__compare"><div><b>修改前</b><pre>${pretty(preview.before)}</pre></div><div><b>提案</b><pre>${pretty(preview.after)}</pre></div></div>`}
    ${pending ? html`<div class="ga-review__actions"><button class="btn btn--primary" data-action="ga.decide" data-arg="${row.id}|${row.revision}|approve" ${s.deciding ? html`disabled` : ''}>批准并执行</button>
      <button class="btn" data-action="ga.decide" data-arg="${row.id}|${row.revision}|reject" ${s.deciding ? html`disabled` : ''}>拒绝</button>
      <a class="linkish" href="#/audit?id=${encodeURIComponent(row.id)}">到审核中心修订</a></div>` : ''}
    ${row.status === 'applied' && row.tool === 'session.create' ? html`<a class="btn btn--sm" href="#/review?session=${encodeURIComponent(result.id || '')}&preview=1">打开正式复习</a>` : ''}
    ${row.error_code ? html`<p class="ga-error">${row.error_code === 'content_conflict' ? '原对象内容已变化，请重新提出操作。' : row.error_code}</p>` : ''}
  </section>`;
}

function block(row, s) {
  if (row.kind === 'user') return html`<div class="ga-user" data-key="${row.id}"><p>${row.text}</p>${row.queued ? html`<small>补充消息</small>` : ''}</div>`;
  if (row.kind === 'assistant') return html`<div class="ga-message md" data-key="${row.id}" data-status="${row.status}">${markdown(row.text)}</div>`;
  if (row.kind === 'thinking') return html`<div class="ga-think" data-key="${row.id}"><button class="ga-disclosure" data-action="ga.toggle" data-arg="${row.id}" aria-expanded="${String(opened(s, row))}">${icon('spark')}<b>${row.status === 'live' ? '思考中' : '思考'}</b><span>${opened(s, row) ? '收起' : row.text.replace(/\s+/g, ' ').slice(0, 70)}</span></button>${opened(s, row) ? html`<p>${row.text}</p>` : ''}</div>`;
  if (row.kind === 'tool') return html`<section class="ga-tool" data-key="${row.id}" data-tool="${row.name}" data-status="${row.status}">
    <button class="ga-disclosure" data-action="ga.toggle" data-arg="${row.id}" aria-expanded="${String(opened(s, row))}">${row.status === 'done' ? icon('check') : icon('book')}<b>${row.label || row.name}</b><span>${row.status === 'waiting' ? '等待审核' : row.summary === row.label ? '' : row.summary || (row.status === 'preparing' ? '正在生成参数' : '执行中')}</span></button>
    ${opened(s, row) ? html`<div class="ga-tool__io"><b>参数</b><pre>${pretty(row.args || row.argsText || {})}</pre>${row.result ? html`<b>结果</b><pre>${row.result}</pre>` : ''}</div>` : ''}
    ${row.operation ? operation(row.operation, s) : ''}</section>`;
  const stats = row.stats || {};
  return html`<div class="ga-run" data-key="${row.id}"><b>${STATUS[row.status] || row.status}</b><span>${stats.turns || 0} 轮 · ${stats.tool_calls || 0} 次工具 · ${stats.seconds || 0} 秒 · ${stats.input_total || 0} / ${stats.output_total || 0} tokens</span>${row.error ? html`<p class="ga-error">${row.error}</p>` : ''}</div>`;
}

export function view(s) {
  const running = isRunning(s.run); const stats = s.run?.stats || {};
  return html`<div class="ga" data-rail="${s.rail ? 'open' : 'closed'}" aria-busy="${String(s.loading)}">
    <aside class="ga-rail" aria-label="助手对话"><div class="ga-rail__head"><strong>对话</strong><button class="btn btn--sm" data-action="ga.new">${icon('plus')}新对话</button></div>
      <nav>${each(s.conversations, row => row.id, row => html`<button class="ga-conversation ${row.id === s.conversation?.id ? 'is-active' : ''}" data-action="ga.open" data-arg="${row.id}" aria-current="${row.id === s.conversation?.id ? 'page' : 'false'}">${row.title}</button>`)}</nav></aside>
    ${s.rail ? html`<button class="ga-scrim" data-action="ga.rail" aria-label="收起对话列表"></button>` : ''}
    <section class="ga-main" aria-label="助手会话"><header class="ga-head"><div><button class="btn btn--sm ga-mobile" data-action="ga.rail" aria-label="打开对话列表">${icon('panel')}</button><h1>${s.conversation?.title || '全局助手'}</h1></div><a class="btn btn--sm" href="#/audit">审核中心</a></header>
      ${s.context && Object.keys(s.context).length ? html`<div class="ga-context">当前学习对象：${Object.values(s.context).join(' · ')}<button class="linkish" data-action="ga.clearContext">清除上下文</button></div>` : ''}
      ${s.error ? html`<p class="ga-error" role="alert">${s.error}</p>` : ''}
      ${s.status && !s.status.ready ? html`<div class="ga-empty"><h2>开启全局语文助手</h2><p>查询学习情况、安排复习、讨论作文。正式学习操作会等待你审核。</p><a class="btn btn--primary" href="#/settings">前往 AI 助手设置</a></div>` : html`<div class="ga-log" id="global-assistant-log" role="log" aria-live="polite" aria-relevant="additions text">
        ${s.loading ? html`<p class="muted">正在加载对话…</p>` : ''}
        ${s.events.length ? each(blocks(s.events), row => row.id, row => block(row, s)) : html`<div class="ga-empty"><h2>从现在的学习开始</h2><p>我可以查询题目和复习情况，也可以阅读正式作文、保存评价与下一稿重点。</p><div class="ga-quick"><button class="btn" data-action="ga.quick" data-arg="给我创建一份30分钟的现代文复习">安排 30 分钟现代文复习</button><button class="btn" data-action="ga.quick" data-arg="看看我最近的学习情况">看看最近的学习情况</button></div></div>`}
      </div><footer class="ga-composer"><div class="ga-usage">${running ? s.run.status === 'waiting_confirmation' ? '等待人工审核' : '助手正在执行' : '可以继续提问'}${stats.context ? ` · 上下文 ${stats.context} / ${stats.window}` : ''}</div>
        <form data-submit="ga.send"><label class="sr-only" for="global-assistant-input">给全局助手的消息</label><textarea id="global-assistant-input" name="text" rows="3" placeholder="例如：给我创建一份 30 分钟的现代文复习" data-input="ga.input">${s.input}</textarea><div><small>Enter 发送 · Shift+Enter 换行</small>${running ? html`<button type="button" class="btn" data-action="ga.stop">停止</button>` : ''}<button type="submit" class="btn btn--primary" ${s.sending || !s.input.trim() ? html`disabled` : ''}>${running ? '发送补充' : '发送'}</button></div></form>
      </footer>`}</section></div>`;
}
