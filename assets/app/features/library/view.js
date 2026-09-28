/**
 * 题库列表：左侧分面筛选（板块 / 状态 / 题型 / 类型 / 添加时间 / 最近练习 / 上次评分，每项显示题数），
 * 顶部工具条（搜索、按题 / 按篇、排序、批量选择），列表分页「加载更多」；按篇时每篇一张卡片，列出其下的题与掌握情况。
 * 批量模式下点行是勾选，底部批量条可以加入复习、停用、恢复、删除。
 */
import { html, each } from '../../core/html.js';
import { formatDay, relativeDay } from '../../core/format.js';
import { icon } from '../../ui/icons.js';
import { GENRES, genreShort, gradeLabel, masteryTone } from '../../domain/genres.js';
import { blankLine } from '../../domain/paper.js';

export const STATUS_TONE = { 新录入: 'chip--info', 待攻克: 'chip--bad', 巩固中: 'chip--warn', 已掌握: 'chip--ok' };
export const NEVER = '9999-12-31';
const SORTS = [['priority', '按优先级'], ['due', '按到期日'], ['mastery', '掌握度低的在前'], ['wrong', '出错多的在前'],
  ['last', '最近练习'], ['created', '最近录入'], ['oldest', '最早录入']];
const FACETS = [
  ['status', '状态', [['新录入', '新录入'], ['待攻克', '待攻克'], ['巩固中', '巩固中'], ['已掌握', '已掌握'], ['leech', '顽固题'], ['suspended', '已停用'], ['deleted', '已删除']]],
  ['kind', '记忆类型', [['skill', '理解型（阅读、鉴赏）'], ['recall', '记忆型（默写、实词）']]],
  ['added', '添加时间', [['7', '近 7 天'], ['30', '近 30 天'], ['90', '近 90 天'], ['old', '90 天以前']]],
  ['last', '最近练习', [['never', '从没做过'], ['7', '近 7 天做过'], ['30', '近 30 天做过'], ['old', '30 天以上没做']]],
  ['grade', '上次评分', [['low', '不会 / 部分 / 有错字'], ['mid', '基本'], ['high', '完整 / 全对'], ['none', '还没评过']]],
];

export const dueText = (sc, today) => (sc.due === NEVER ? '不再安排' : `${relativeDay(sc.due, today)}到期`);

const option = (dim, value, label, n, current) => {
  const on = current === value;
  return html`<button class="fct__opt" data-action="lib.facet" data-arg="${dim}:${value}" aria-pressed="${String(on)}" ${!n && !on ? html`disabled` : ''}>
    <span>${label}</span><small>${n ?? 0}</small></button>`;
};

export function facets(s) {
  const f = s.filter;
  const c = s.facets || {};
  const qtypes = Object.entries(c.qtype || {}).sort((a, b) => b[1] - a[1]);
  const active = ['status', 'qtype', 'kind', 'added', 'last', 'grade'].filter(k => f[k]).length + (f.q ? 1 : 0);
  return html`<aside class="fct ${s.facetsOpen ? 'is-open' : ''}" aria-label="筛选">
    <div class="fct__head"><b>筛选</b>${active ? html`<button class="linkish" data-action="lib.clear">清除 ${active} 项</button>` : ''}</div>
    ${each(FACETS, x => x[0], ([dim, title, opts]) => html`<section class="fct__grp">
      <h3>${title}</h3>
      ${each(opts, o => o[0], ([value, label]) => option(dim, value, label, dim === 'status' && value === 'deleted' ? s.deletedCount : c[dim]?.[value], f[dim]))}
    </section>`)}
    ${qtypes.length ? html`<section class="fct__grp fct__grp--qtype" data-key="qtype">
      <h3>题型${f.genre ? '' : html`<small>（选板块可细分）</small>`}</h3>
      ${each(qtypes, x => x[0] || '-', ([value, n]) => option('qtype', value, value || '未分类', n, f.qtype))}
    </section>` : ''}
  </aside>`;
}

export function toolbar(s) {
  const f = s.filter;
  return html`<div class="lib__bar">
    <div class="seg" role="group" aria-label="板块">
      <button data-action="lib.genre" data-arg="" aria-pressed="${String(!f.genre)}">全部</button>
      ${each(GENRES, g => g.code, g => html`<button data-action="lib.genre" data-arg="${g.code}" aria-pressed="${String(f.genre === g.code)}">${g.short} <small>${s.counts[g.code] ?? 0}</small></button>`)}
    </div>
    <input class="input lib__search" type="search" placeholder="搜题干、答案、篇名、出处、题号" value="${f.q}" data-input="lib.search" aria-label="搜索">
    <div class="seg" role="group" aria-label="列表方式">
      <button data-action="lib.group" data-arg="item" aria-pressed="${String(s.group === 'item')}">按题</button>
      <button data-action="lib.group" data-arg="material" aria-pressed="${String(s.group === 'material')}">按篇</button>
    </div>
    <select class="select lib__sel" data-change="lib.filter" data-arg="sort" aria-label="排序">
      ${each(SORTS, x => x[0], x => html`<option value="${x[0]}" ${x[0] === f.sort ? html`selected` : ''}>${x[1]}</option>`)}</select>
    <button class="btn btn--sm lib__facetbtn" data-action="lib.facets" aria-pressed="${String(s.facetsOpen)}">筛选</button>
    <button class="btn btn--sm ${s.selecting ? 'btn--primary' : ''}" data-action="lib.selecting" aria-pressed="${String(s.selecting)}">${s.selecting ? '完成选择' : '批量选择'}</button>
  </div>`;
}

const stemPreview = it => (it.genre === 'dictation' ? blankLine(it.stem, { '': it.answer }) : it.stem.split('\n')[0]);

function facts(it, s) {
  const sc = it.sched;
  const parts = [sc.reviews ? `上次 ${formatDay(sc.last_review)}「${gradeLabel(it.genre, sc.last_grade)}」` : '还没复习过',
    `${relativeDay((it.created_at || '').slice(0, 10), s.today)}录入`];
  if (it.wrong) parts.push(`错 ${it.wrong} 次`);
  return parts.join(' · ');
}

/** 行首的一串说明：板块 · 第 N 题 · 题型 · 《篇名》 · 出处；按篇分组时篇名 / 出处已在卡片头上，省掉。 */
const meta = (it, compact) => [compact ? '' : genreShort(it.genre), it.no ? `第 ${it.no} 题` : '', it.qtype || '',
  !compact && it.material_title ? `《${it.material_title}》` : '', !compact && it.source ? it.source : ''].filter(Boolean).join(' · ');

function row(it, s, { compact = false } = {}) {
  const picked = s.picked.has(it.id);
  const sc = it.sched;
  return html`<li data-key="${it.id}"><button class="row ${s.selecting ? 'row--pick' : ''} ${it.id === s.selected && !s.selecting ? 'is-active' : ''} ${it.suspended ? 'is-off' : ''} ${picked ? 'is-picked' : ''}"
    data-action="${s.selecting ? 'lib.pick' : 'lib.select'}" data-arg="${it.id}" data-genre="${it.genre}" aria-pressed="${s.selecting ? String(picked) : 'false'}">
    ${s.selecting ? html`<span class="row__check" aria-hidden="true">${picked ? icon('check') : ''}</span>` : ''}
    <span class="row__meta"><span class="genre-dot"></span>${meta(it, compact)}</span>
    <span class="row__stem">${stemPreview(it)}</span>
    <span class="row__facts">${facts(it, s)}</span>
    <span class="row__side">
      <span class="chip ${STATUS_TONE[sc.status] || ''}">${sc.leech ? '顽固' : sc.status}</span>
      <span class="meter" data-tone="${masteryTone(sc.decayed)}"><i data-w="${Math.round(sc.decayed * 20) * 5}"></i></span>
      <small>${it.deleted ? '已删除' : it.suspended ? '已停用' : dueText(sc, s.today)}</small>
    </span>
  </button></li>`;
}

function groupCard(g, s) {
  const st = g.stats;
  const all = g.items.every(it => s.picked.has(it.id));
  const title = g.material_id ? `《${g.title || '无题'}》` : g.title || '未归类';
  return html`<li class="grpc" data-key="${g.key}" data-genre="${g.genre}">
    <header class="grpc__head">
      <span class="genre-dot"></span><b class="grpc__title">${title}</b>
      ${g.author ? html`<span class="grpc__by">${g.author}</span>` : ''}
      <span class="grpc__stats">${genreShort(g.genre)} · ${g.size > st.total ? `显示 ${st.total} / 共 ${g.size} 题` : `${st.total} 题`}
        · 已掌握 ${st.mastered}${st.new ? ` · 新 ${st.new}` : ''}${st.leech ? ` · 顽固 ${st.leech}` : ''} · ${formatDay(g.created_at)}录入</span>
      <span class="meter grpc__meter" data-tone="${masteryTone(st.mastery)}" title="平均掌握度 ${Math.round(st.mastery * 100)}%"><i data-w="${Math.round(st.mastery * 20) * 5}"></i></span>
      ${s.selecting ? html`<button class="linkish" data-action="lib.pickGroup" data-arg="${g.key}">${all ? '取消这一篇' : '选这一篇'}</button>` : ''}
    </header>
    ${g.source ? html`<p class="grpc__src">${g.source}</p>` : ''}
    <ul class="grpc__items">${each(g.items, it => it.id, it => row(it, s, { compact: true }))}</ul>
  </li>`;
}

export function list(s) {
  const rows = s.group === 'material' ? s.groups : s.items;
  if (s.loading && !rows.length) return html`<p class="empty">正在加载…</p>`;
  if (!rows.length) return html`<p class="empty">没有符合条件的题。${s.libraryTotal ? html`<button class="linkish" data-action="lib.clear">清除筛选</button>` : html`<a href="#/entry">去录入第一道错题</a>`}</p>`;
  const shown = s.group === 'material' ? s.groups.length : s.items.length;
  const total = s.group === 'material' ? s.totalGroups : s.total;
  return html`<p class="lib__count muted">${s.group === 'material' ? `${s.total} 题，分在 ${total} 篇 / 组` : `共 ${total} 题`}${shown < total ? `，显示前 ${shown} ${s.group === 'material' ? '组' : '题'}` : ''}</p>
    ${s.group === 'material' ? html`<ul class="lib__groups">${each(s.groups, g => g.key, g => groupCard(g, s))}</ul>`
    : html`<ul class="lib__list">${each(s.items, it => it.id, it => row(it, s))}</ul>`}
    ${shown < total ? html`<div class="lib__more"><button class="btn" data-action="lib.more" ${s.loading ? html`disabled` : ''}>${s.loading ? '正在加载…' : '加载更多'}</button></div>` : ''}
    ${s.selecting ? batchBar(s) : ''}`;
}

function batchBar(s) {
  const n = s.picked.size;
  const off = n ? '' : html`disabled`;
  return html`<div class="lib__batch" role="toolbar" aria-label="批量操作">
    <b>已选 ${n} 题</b>
    <button class="linkish" data-action="lib.pickPage">全选已加载的</button>
    ${n ? html`<button class="linkish" data-action="lib.pickNone">清空</button>` : ''}
    <span class="lib__batchacts">
      <button class="btn btn--sm btn--primary" data-action="lib.batchReview" ${off}>${icon('review')}加入复习</button>
      <button class="btn btn--sm" data-action="lib.batch" data-arg="suspend" ${off}>停用</button>
      <button class="btn btn--sm" data-action="lib.batch" data-arg="resume" ${off}>恢复复习</button>
      <button class="btn btn--sm btn--ghost btn--danger" data-action="lib.batch" data-arg="delete" ${off}>删除</button>
    </span>
  </div>`;
}
