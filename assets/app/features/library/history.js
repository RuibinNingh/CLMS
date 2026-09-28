/**
 * 复习历史（题库页的「复习记录」分页）：全库所有评分记录，按日期倒序；可按板块、评分、时间、是否写了反馈筛选，
 * 可显示已撤销的。点一条打开右侧这道题的详情（在那里改评、改反馈、撤销、恢复）。数据来自 GET /api/records。
 */
import { html, each } from '../../core/html.js';
import { formatDay } from '../../core/format.js';
import { GENRES } from '../../domain/genres.js';

const SINCE = [['', '全部时间'], ['7', '近 7 天'], ['30', '近 30 天'], ['90', '近 90 天']];
const GRADE = [['', '全部评分'], ['low', '不会 / 部分 / 有错字'], ['mid', '基本'], ['high', '完整 / 全对']];
const TONE = g => (g <= 0 ? 'chip--bad' : g === 1 ? 'chip--warn' : 'chip--ok');

const opt = (value, label, current) => html`<option value="${value}" ${value === current ? html`selected` : ''}>${label}</option>`;

export function historyView(s) {
  const h = s.hist;
  return html`<div class="hst">
    <div class="lib__bar">
      <div class="seg" role="group" aria-label="板块">
        <button data-action="lib.histGenre" data-arg="" aria-pressed="${String(!h.genre)}">全部</button>
        ${each(GENRES, g => g.code, g => html`<button data-action="lib.histGenre" data-arg="${g.code}" aria-pressed="${String(h.genre === g.code)}">${g.short}</button>`)}
      </div>
      <select class="select lib__sel" data-change="lib.histFilter" data-arg="grade" aria-label="评分">${each(GRADE, x => x[0], x => opt(x[0], x[1], h.grade))}</select>
      <select class="select lib__sel" data-change="lib.histFilter" data-arg="since" aria-label="时间">${each(SINCE, x => x[0], x => opt(x[0], x[1], h.since))}</select>
      <label class="hst__check"><input type="checkbox" data-change="lib.histCheck" data-arg="note" ${h.note ? html`checked` : ''}>只看写了反馈的</label>
      <label class="hst__check"><input type="checkbox" data-change="lib.histCheck" data-arg="voided" ${h.voided ? html`checked` : ''}>显示已撤销的</label>
    </div>
    ${h.records.length ? html`<p class="lib__count muted">共 ${h.total} 条${h.records.length < h.total ? `，显示前 ${h.records.length} 条` : ''}</p>
      <ol class="hst__list">${each(h.records, r => r.commit_id, r => html`<li data-key="${r.commit_id}">
        <button class="hst__row ${r.voided ? 'is-void' : ''} ${r.item_id === s.selected ? 'is-active' : ''}" data-action="lib.select" data-arg="${r.item_id}" data-genre="${r.genre}">
          <time>${formatDay(r.at, { weekday: true })}</time>
          <span class="hst__what"><span class="genre-dot"></span>${r.item_name}${r.qtype && r.genre !== 'dictation' ? html`<span class="muted"> · ${r.qtype}</span>` : ''}</span>
          <span class="chip ${r.voided ? '' : TONE(r.grade)}">${r.grade_label}</span>
          <span class="hst__src muted">${r.session_id || '补记'}${r.voided ? ' · 已撤销' : ''}${r.item_deleted ? ' · 题已删除' : ''}</span>
          ${r.note ? html`<span class="hst__note">${r.note}</span>` : ''}
        </button></li>`)}</ol>
      ${h.records.length < h.total ? html`<div class="lib__more"><button class="btn" data-action="lib.histMore" ${h.loading ? html`disabled` : ''}>${h.loading ? '正在加载…' : '加载更多'}</button></div>` : ''}`
    : html`<p class="empty">${h.loading ? '正在加载…' : '这些条件下没有复习记录'}</p>`}
  </div>`;
}
