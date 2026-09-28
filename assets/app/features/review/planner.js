/**
 * 安排复习的渲染：上半是「推荐清单」（程序按到期、上次评分、添加时间、薄弱题型推荐；可移除、换一批、放回），
 * 下半是「从题库挑题」（按板块 / 状态 / 添加时间 / 最近练习 / 上次评分 / 关键词筛选，点「加入」成为自选题）。
 * 自选题先占时间预算，推荐自动补足剩下的时间；两边的增删都会重新推荐。
 */
import { html, each } from '../../core/html.js';
import { formatDay, relativeDay } from '../../core/format.js';
import { icon } from '../../ui/icons.js';
import { GENRES, genreShort, gradeLabel } from '../../domain/genres.js';
import { blankLine } from '../../domain/paper.js';

const BUDGETS = [20, 30, 40, 60, 90];
const TAG_TONE = { leech: 'chip--bad', new: 'chip--info', overdue: 'chip--warn', due: 'chip--warn', weak: 'chip--warn', revive: '', early: '', manual: 'chip--ok' };
const STATUSES = [['', '全部状态'], ['新录入', '新录入'], ['待攻克', '待攻克'], ['巩固中', '巩固中'], ['已掌握', '已掌握'], ['leech', '顽固题']];
const ADDED = [['', '添加时间不限'], ['7', '近 7 天添加'], ['30', '近 30 天添加'], ['90', '近 90 天添加'], ['old', '90 天前添加']];
const LAST = [['', '练习时间不限'], ['never', '从没做过'], ['7', '近 7 天做过'], ['30', '近 30 天做过'], ['old', '30 天以上没做']];
const GRADE = [['', '上次评分不限'], ['low', '上次不会 / 部分'], ['mid', '上次基本'], ['high', '上次完整']];
const SORTS = [['priority', '推荐度'], ['created', '最近添加'], ['oldest', '最早添加'], ['last', '最近练习'], ['wrong', '出错多的'], ['mastery', '掌握度低的']];

const opt = (value, label, current, n) => html`<option value="${value}" ${value === current ? html`selected` : ''}>${label}${n === undefined ? '' : `（${n}）`}</option>`;
const select = (arg, list, current, label, counts) => html`<select class="select pk__sel" data-change="rv.pickFilter" data-arg="${arg}" aria-label="${label}">
  ${each(list, x => x[0], x => opt(x[0], x[1], current, x[0] && counts ? counts[x[0]] ?? 0 : undefined))}</select>`;

/** 一行题目的名字：《材料》第 7 题 · 意象作用题；默写显示挖空的句子。 */
export function itemName(it) {
  if (it.genre === 'dictation') return html`<span class="pk__dict">${blankLine(it.stem, {})}</span>`;
  return html`${it.no ? `第 ${it.no} 题 ` : ''}<b>${it.qtype || '未分类'}</b>`;
}

function groups(items) {
  const out = [];
  let last = null;
  items.forEach(x => {
    const key = x.item.material_id || (x.item.genre === 'dictation' ? 'dictation' : x.id);
    if (!last || last.key !== key) { last = { key, item: x.item, rows: [] }; out.push(last); }
    last.rows.push(x);
  });
  return out;
}

function planRow(x) {
  const manual = x.tag === 'manual';
  return html`<li class="pl__row" data-key="${x.id}" data-genre="${x.item.genre}">
    <span class="pl__what">${itemName(x.item)}</span>
    <span class="chip ${TAG_TONE[x.tag] ?? ''}">${x.reason}</span>
    <button class="btn btn--ghost btn--icon pl__drop" data-action="${manual ? 'rv.unpin' : 'rv.exclude'}" data-arg="${x.id}"
      title="${manual ? '移出自选' : '这次不做这道（会换上别的题）'}" aria-label="${manual ? '移出自选' : '从推荐里移除'}">${icon('close')}</button>
  </li>`;
}

function planGroup(g) {
  const it = g.item;
  const head = it.genre === 'dictation' ? html`<span class="pl__gtitle">名句默写</span>`
    : it.material_id ? html`<span class="pl__gtitle">《${it.material_title || '无题'}》</span><span class="muted">${genreShort(it.genre)} · 读原文约 ${it.material_minutes} 分钟</span>`
      : html`<span class="pl__gtitle">${genreShort(it.genre)}</span>`;
  return html`<li class="pl__group" data-key="g-${g.key}" data-genre="${it.genre}">
    <div class="pl__ghead"><span class="genre-dot"></span>${head}</div>
    <ul class="pl__rows">${each(g.rows, x => x.id, planRow)}</ul></li>`;
}

function qtypeSelect(s) {
  const table = s.taxonomy?.qtypes || {};
  return html`<select class="select pl__qtype" data-change="rv.qtype" aria-label="只推荐某个题型">
    ${opt('', '全部题型', s.qtype)}
    ${each(GENRES.filter(g => s.genres.has(g.code) && table[g.code]?.length), g => g.code, g => html`<optgroup label="${g.short}">
      ${each(table[g.code], q => `${g.code}-${q}`, q => opt(q, q, s.qtype))}</optgroup>`)}
  </select>`;
}

function summary(p, s) {
  if (s.planning && !p) return html`<p class="pl__sum muted">正在推荐…</p>`;
  if (!p) return '';
  const notes = [];
  if (p.due_left) notes.push(`还有 ${p.due_left} 道到期题这次放不下`);
  if (p.busy_skipped) notes.push(`${p.busy_skipped} 道已在未完成的复习里，没再推荐`);
  if (s.excluded.length) notes.push(html`移除了 ${s.excluded.length} 道 <button class="linkish" data-action="rv.unexclude">全部放回</button>`);
  return html`<div class="pl__sum">
    ${p.items.length ? html`<p>共 <b>${p.items.length}</b> 题，约 <b>${Math.round(p.minutes)}</b> / ${p.budget} 分钟（含读原文）${p.pinned ? html`，其中自选 ${p.pinned} 道` : ''}</p>`
      : html`<p>这些条件下没有要复习的题。可以放宽板块 / 题型，或者到下面的题库里挑题。</p>`}
    ${notes.length ? html`<p class="muted">${each(notes, (_, i) => i, (n, i) => html`${i ? '；' : ''}${n}`)}</p>` : ''}
    ${p.weak?.length ? html`<p class="muted">薄弱题型：${p.weak.map(w => w.qtype).join('、')}（优先补同题型的其它题）</p>` : ''}
  </div>`;
}

export function planner(s) {
  const p = s.plan;
  return html`<section class="card pl">
    <header class="pl__head"><h2>安排这次复习</h2>
      <span class="muted">${s.horizon ? `按 ${formatDay(s.horizon, { weekday: true })}（下个复习日）计算到期` : ''}</span></header>
    <div class="pl__opts">
      <div class="seg" role="group" aria-label="时间">${each(BUDGETS, m => m, m => html`<button data-action="rv.budget" data-arg="${m}" aria-pressed="${String(s.minutes === m)}">${m} 分钟</button>`)}</div>
      <div class="pl__genres">${each(GENRES, g => g.code, g => html`<button class="chip ${s.genres.has(g.code) ? 'chip--info' : ''}" data-action="rv.genre" data-arg="${g.code}" aria-pressed="${String(s.genres.has(g.code))}" data-genre="${g.code}"><span class="genre-dot"></span>${g.short}</button>`)}</div>
      ${qtypeSelect(s)}
      <label class="pl__fill"><input type="checkbox" data-change="rv.fill" ${s.fill ? html`checked` : ''}>时间有富余时提前复习</label>
    </div>
    ${summary(p, s)}
    ${p?.items.length ? html`<ol class="pl__list ${s.planning ? 'is-busy' : ''}">${each(groups(p.items), g => `g-${g.key}`, planGroup)}</ol>` : ''}
    <div class="pl__foot">
      <button class="btn btn--ghost btn--sm" data-action="rv.shuffle" ${p?.items.some(x => x.tag !== 'manual') ? '' : html`disabled`} title="把这批推荐都换掉（自选的保留）">${icon('retry')}换一批</button>
      <button class="btn btn--primary" data-action="rv.create" ${p?.items.length && !s.planning ? '' : html`disabled`}>${icon('check')}确认安排${p?.items.length ? ` ${p.items.length} 题` : ''}</button>
    </div>
  </section>`;
}

function pickRow(it, s) {
  const inPlan = s.plan?.items.find(x => x.id === it.id);
  const pinned = s.pinned.includes(it.id);
  const sc = it.sched;
  const last = sc.reviews ? `${relativeDay(sc.last_review, s.today)}做过 · ${gradeLabel(it.genre, sc.last_grade)}` : '没做过';
  return html`<li class="pk__row" data-key="${it.id}" data-genre="${it.genre}">
    <div class="pk__main">
      <span class="pk__meta"><span class="genre-dot"></span>${genreShort(it.genre)}${it.material_title ? html` · 《${it.material_title}》` : it.source ? html` · ${it.source}` : ''}</span>
      <span class="pk__name">${itemName(it)}${it.genre === 'dictation' ? '' : html`<span class="pk__stem">${it.stem.split('\n')[0]}</span>`}</span>
      <span class="pk__facts">${sc.leech ? '顽固' : sc.status} · ${relativeDay(it.created_at, s.today)}添加 · ${last}</span>
    </div>
    ${pinned ? html`<button class="btn btn--sm is-on" data-action="rv.unpin" data-arg="${it.id}">${icon('check')}已加入</button>`
      : inPlan ? html`<span class="muted pk__in">已在推荐里</span>`
        : html`<button class="btn btn--sm" data-action="rv.pin" data-arg="${it.id}">${icon('plus')}加入</button>`}
  </li>`;
}

export function picker(s) {
  const k = s.pick;
  const f = k.facets || {};
  return html`<section class="card pk">
    <header class="pl__head"><h2>从题库挑题</h2><span class="muted">加入的题一定会排进这次复习，推荐会自动补足剩下的时间</span></header>
    <div class="pk__filters">
      <input class="input pk__search" type="search" placeholder="搜题干、篇名、出处、题号" value="${k.q}" data-input="rv.pickSearch" aria-label="搜索题库">
      <div class="seg" role="group" aria-label="板块">
        <button data-action="rv.pickGenre" data-arg="" aria-pressed="${String(!k.genre)}">全部</button>
        ${each(GENRES, g => g.code, g => html`<button data-action="rv.pickGenre" data-arg="${g.code}" aria-pressed="${String(k.genre === g.code)}">${g.short} <small>${f.genre?.[g.code] ?? 0}</small></button>`)}
      </div>
      ${select('status', STATUSES, k.status, '状态', f.status)}
      ${select('added', ADDED, k.added, '添加时间', f.added)}
      ${select('last', LAST, k.last, '最近练习', f.last)}
      ${select('grade', GRADE, k.grade, '上次评分', f.grade)}
      <select class="select pk__sel" data-change="rv.pickFilter" data-arg="sort" aria-label="排序">${each(SORTS, x => x[0], x => opt(x[0], `按${x[1]}`, k.sort))}</select>
    </div>
    ${k.items.length ? html`<ul class="pk__list">${each(k.items, it => it.id, it => pickRow(it, s))}</ul>`
      : html`<p class="empty">${k.loading ? '正在加载…' : '没有符合条件的题'}</p>`}
    ${k.items.length ? html`<p class="pk__more muted">显示 ${k.items.length} / 共 ${k.total} 题
      ${k.items.length < k.total ? html`<button class="btn btn--sm" data-action="rv.pickMore" ${k.loading ? html`disabled` : ''}>加载更多</button>` : ''}</p>` : ''}
  </section>`;
}
