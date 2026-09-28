/**
 * 录入记录（左栏；≤1500 时是抽屉）：上传 / 新对话 / 手动录入，搜索，分组（全部 / 进行中 / 待入库 / 已入库 / 回收站），
 * 按日期分段的列表（缩略图、标题、状态、时间、页数 / 题数、最近一句话），重命名、丢弃到回收站、恢复、彻底删除，加载更多。
 */
import { html, each } from '../../core/html.js';
import { formatTime, formatDay } from '../../core/format.js';
import { icon } from '../../ui/icons.js';
import { GENRES } from '../../domain/genres.js';

export const VIEWS = [['all', '全部'], ['active', '进行中'], ['ready', '待入库'], ['committed', '已入库'], ['trash', '回收站']];
export const STATUS = {
  staged: ['待确认页面', 'stage'], queued: ['排队中', 'wait'], extracting: ['识别中', 'wait'], thinking: ['AI 执行中', 'wait'],
  ready: ['待入库', 'ready'], error: ['出错', 'bad'], committed: ['已入库', 'done'], discarded: ['回收站', 'done'],
};

const uploadButton = (label, primary = true) => html`
  <label class="btn btn--sm ${primary ? 'btn--primary' : ''} upload-btn">${icon('upload')}<span>${label}</span>
    <input type="file" accept="image/*" multiple class="visually-hidden" data-change="entry.files"></label>`;

function dayLabel(iso, today) {
  const d = (iso || '').slice(0, 10);
  if (d === today) return '今天';
  const y = new Date(Date.parse(`${today}T12:00:00`) - 86400000).toISOString().slice(0, 10);
  return d === y ? '昨天' : formatDay(d);
}

function statusText(d) {
  if (d.status === 'ready' && !d.genres?.length) return { chat: '对话', review: '批改完成' }[d.kind] || '待入库';
  return (STATUS[d.status] || [d.status])[0];
}

function row(d, s) {
  const [, tone] = STATUS[d.status] || ['', 'wait'];
  const trash = d.status === 'discarded';
  const meta = [statusText(d), formatTime(d.updated_at), d.units ? `${d.units} 题` : d.pages ? `${d.pages} 页` : '']
    .filter(Boolean).join(' · ');
  return html`<li class="hrow ${d.id === s.activeId ? 'is-active' : ''} ${trash ? 'is-trash' : ''}" data-tone="${tone}" data-key="${d.id}">
    ${s.renaming === d.id ? html`<input class="input hrow__rename" data-change="entry.rename" data-arg="${d.id}" value="${d.name || d.title}"
      aria-label="新名称（回车保存，清空恢复自动标题）">` : html`
    <button class="hrow__main" data-action="entry.open" data-arg="${d.id}" aria-current="${String(d.id === s.activeId)}" title="${d.title}">
      ${d.images?.[0] ? html`<img src="/api/image?id=${d.images[0]}" alt="">` : html`<span class="hrow__blank">${d.kind === 'chat' ? '话' : '手'}</span>`}
      <span class="hrow__text"><b>${d.title || '未命名'}</b><small><i class="qdot"></i>${meta}</small>
        ${d.snippet ? html`<small class="hrow__snip">${d.snippet}</small>` : ''}</span>
    </button>`}
    <span class="hrow__acts">${trash ? html`
      <button class="btn btn--ghost btn--icon btn--sm" data-action="entry.undiscard" data-arg="${d.id}" title="恢复" aria-label="恢复">${icon('undo')}</button>
      <button class="btn btn--ghost btn--icon btn--sm btn--danger" data-action="entry.purge" data-arg="${d.id}" title="彻底删除" aria-label="彻底删除">${icon('trash')}</button>` : html`
      <button class="btn btn--ghost btn--icon btn--sm" data-action="entry.renaming" data-arg="${d.id}" title="重命名" aria-label="重命名">${icon('entry')}</button>
      <button class="btn btn--ghost btn--icon btn--sm" data-action="entry.trash" data-arg="${d.id}" title="丢到回收站" aria-label="丢到回收站">${icon('trash')}</button>`}
    </span>
  </li>`;
}

export function renderHistory(s) {
  const rows = [];
  let lastDay = '';
  s.drafts.forEach(d => {
    const day = dayLabel(d.updated_at, s.today);
    if (day !== lastDay) { rows.push({ day }); lastDay = day; }
    rows.push(d);
  });
  return html`<aside class="hist" aria-label="录入记录" ${s.histCollapsed && s.wide ? html`inert` : ''}><div class="hist__inner">
    <div class="hist__head">
      <h1 class="hist__title">录入</h1>
      <button class="btn btn--ghost btn--icon btn--sm hist__collapse" data-action="entry.collapse" aria-label="收起录入记录" title="收起">${icon('panel')}</button>
      <button class="btn btn--ghost btn--icon btn--sm hist__close" data-action="entry.hist" aria-label="收起记录">${icon('close')}</button>
    </div>
    <div class="hist__actions">
      <button class="btn btn--sm btn--primary hist__new" data-action="entry.fresh" title="上传试卷照片，或直接和 AI 对话">${icon('plus')}新录入</button>
      ${uploadButton('上传', false)}
      <select class="select hist__manual" data-change="entry.manual" aria-label="不用 AI，手动录入">
        <option value="" selected>手动录入…</option>${each(GENRES, g => g.code, g => html`<option value="${g.code}">${g.name}</option>`)}
      </select>
    </div>
    <input class="input hist__search" type="search" placeholder="搜标题、最近的话" value="${s.q}" data-input="entry.search" aria-label="搜索录入记录">
    <div class="hist__views" role="group" aria-label="分组">${each(VIEWS, v => v[0], v => html`
      <button class="chip ${s.view === v[0] ? 'chip--info' : ''}" data-action="entry.view" data-arg="${v[0]}" aria-pressed="${String(s.view === v[0])}">${v[1]}<small>${s.counts[v[0]] ?? ''}</small></button>`)}</div>
    <ol class="hist__list">${each(rows, x => x.day ? `day-${x.day}` : x.id, x => (x.day ? html`<li class="hist__day">${x.day}</li>` : row(x, s)))}</ol>
    ${s.drafts.length < s.total ? html`<button class="btn btn--ghost btn--sm hist__more" data-action="entry.more">加载更多（还有 ${s.total - s.drafts.length} 份）</button>`
      : s.drafts.length ? '' : html`<p class="hist__empty">${s.view === 'trash' ? '回收站是空的' : s.q ? '没有找到' : '还没有录入记录'}</p>`}
  </div></aside>`;
}
