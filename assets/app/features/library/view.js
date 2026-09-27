/**
 * 题库渲染：筛选条、题目列表、右侧详情（原文、题干、红笔答案、复习记录、编辑表单）。
 * 复习记录可增删改查（对标 OMRS 历史修正）：补记一次、改评分、改反馈、撤销、恢复已撤销的；全部是追加提交。
 * 「已删除」筛选列出删除过的题，可以恢复。
 */
import { html, each } from '../../core/html.js';
import { formatDay, relativeDay } from '../../core/format.js';
import { icon } from '../../ui/icons.js';
import { GENRES, genreShort, gradesFor, masteryTone } from '../../domain/genres.js';
import { blankLine, bluePen, passage, redPen } from '../../domain/paper.js';

const STATUSES = ['新录入', '待攻克', '巩固中', '已掌握'];
const STATUS_TONE = { 新录入: 'chip--info', 待攻克: 'chip--bad', 巩固中: 'chip--warn', 已掌握: 'chip--ok' };
const SORTS = [['priority', '按优先级'], ['due', '按到期日'], ['mastery', '掌握度低的在前'], ['created', '最近录入']];

const opt = (value, label, current) => html`<option value="${value}" ${value === current ? html`selected` : ''}>${label}</option>`;

export function filters(s) {
  const f = s.filter;
  const qtypes = f.genre ? s.taxonomy?.qtypes?.[f.genre] || [] : [];
  return html`<div class="lib__filters">
    <div class="seg" role="group" aria-label="板块">
      <button data-action="lib.genre" data-arg="" aria-pressed="${String(!f.genre)}">全部</button>
      ${each(GENRES, g => g.code, g => html`<button data-action="lib.genre" data-arg="${g.code}" aria-pressed="${String(f.genre === g.code)}">${g.short} <small>${s.counts[g.code] ?? 0}</small></button>`)}
    </div>
    <select class="select lib__sel" data-change="lib.filter" data-arg="status" aria-label="状态">
      ${opt('', '全部状态', f.status)}${each(STATUSES, x => x, x => opt(x, x, f.status))}${opt('leech', '顽固题', f.status)}${opt('deleted', `已删除${s.deletedCount ? `（${s.deletedCount}）` : ''}`, f.status)}
    </select>
    ${qtypes.length ? html`<select class="select lib__sel" data-change="lib.filter" data-arg="qtype" aria-label="题型">
      ${opt('', '全部题型', f.qtype)}${each(qtypes, x => x, x => opt(x, x, f.qtype))}</select>` : ''}
    <select class="select lib__sel" data-change="lib.filter" data-arg="sort" aria-label="排序">${each(SORTS, x => x[0], x => opt(x[0], x[1], f.sort))}</select>
    <input class="input lib__search" type="search" placeholder="搜题干、答案、篇名、出处" value="${f.q}" data-input="lib.search" aria-label="搜索">
  </div>`;
}

const stemPreview = it => (it.genre === 'dictation' ? blankLine(it.stem, { '': it.answer }) : it.stem.split('\n')[0]);

export function list(s) {
  if (s.loading && !s.items.length) return html`<p class="empty">正在加载…</p>`;
  if (!s.items.length) return html`<p class="empty">没有符合条件的题。${s.total ? '' : html`<a href="#/entry">去录入第一道错题</a>`}</p>`;
  return html`<ul class="lib__list">${each(s.items, it => it.id, it => html`
    <li><button class="row ${it.id === s.selected ? 'is-active' : ''} ${it.suspended ? 'is-off' : ''}" data-action="lib.select" data-arg="${it.id}" data-genre="${it.genre}">
      <span class="row__meta"><span class="genre-dot"></span>${genreShort(it.genre)}${it.qtype ? html` · ${it.qtype}` : ''}${it.material_title ? html` · 《${it.material_title}》` : ''}${it.source ? html` · ${it.source}` : ''}</span>
      <span class="row__stem">${stemPreview(it)}</span>
      <span class="row__side">
        <span class="chip ${STATUS_TONE[it.sched.status] || ''}">${it.sched.leech ? '顽固' : it.sched.status}</span>
        <span class="meter" data-tone="${masteryTone(it.sched.decayed)}"><i data-w="${Math.round(it.sched.decayed * 20) * 5}"></i></span>
        <small>${it.deleted ? '已删除' : it.suspended ? '已停用' : `${relativeDay(it.sched.due, s.today)}到期`}</small>
      </span>
    </button></li>`)}</ul>`;
}

function editor(d, s) {
  const qtypes = s.taxonomy?.qtypes?.[d.genre] || [];
  return html`<form class="lib__edit" data-submit="lib.save">
    ${d.genre === 'dictation' ? '' : html`<label class="field"><span>题型</span><select class="select" name="qtype">
      ${opt('', '未分类', d.qtype)}${each(qtypes.includes(d.qtype) || !d.qtype ? qtypes : [d.qtype, ...qtypes], x => x, x => opt(x, x, d.qtype))}</select></label>`}
    <label class="field"><span>${d.genre === 'dictation' ? '题面（用 {书写区域} 标出要写的空）' : '题干'}</span><textarea class="textarea" name="stem" rows="3">${d.stem}</textarea></label>
    <label class="field"><span>参考答案</span><textarea class="textarea" name="answer" rows="4">${d.answer}</textarea></label>
    ${d.genre === 'dictation' ? html`<label class="field"><span>出处</span><input class="input" name="source" value="${d.source || ''}"></label>`
      : html`<label class="field"><span>留白行数</span><input class="input" type="number" min="0" max="24" name="blank_lines" value="${d.blank_lines ?? 0}"></label>`}
    <label class="field"><span>错因</span><textarea class="textarea" name="note" rows="2">${d.note || ''}</textarea></label>
    <div class="lib__edit-foot"><button type="button" class="btn" data-action="lib.edit">取消</button><button class="btn btn--primary">保存修改</button></div>
  </form>`;
}

export function detail(s) {
  const d = s.detail;
  if (!d) return html`<div class="lib__none">${s.items.length ? '选一道题看详情' : ''}</div>`;
  const sc = d.sched;
  return html`<article class="lib__detail" data-genre="${d.genre}">
    <header class="lib__dhead">
      <span class="genre-dot"></span><b>${genreShort(d.genre)}${d.qtype ? ` · ${d.qtype}` : ''}</b><span class="muted">${d.id}</span>
      <button class="btn btn--ghost btn--icon lib__close" data-action="lib.close" aria-label="关闭">${icon('close')}</button>
    </header>
    <dl class="lib__stats">
      <div><dt>状态</dt><dd>${sc.leech ? '顽固' : sc.status}</dd></div>
      <div><dt>掌握度</dt><dd>${Math.round(sc.decayed * 100)}%</dd></div>
      <div><dt>下次</dt><dd>${formatDay(sc.due)}</dd></div>
      <div><dt>出错</dt><dd>${d.encounters} 次录入</dd></div>
    </dl>
    ${s.editing ? editor(d, s) : html`
    <div class="paper lib__paper">
      ${d.material ? html`<details class="lib__mat"><summary>《${d.material.title || '无题'}》${d.material.author ? ` ${d.material.author}` : ''} · 原文</summary>${passage(d.material.text, d.genre)}</details>` : ''}
      <div class="lib__stem">${d.genre === 'dictation' ? blankLine(d.stem, { '': d.answer }) : d.stem}</div>
      ${d.genre === 'dictation' ? '' : html`<div class="ruled">${Array.from({ length: Math.min(d.blank_lines || 0, 6) }, () => html`<i></i>`)}</div>`}
      <p class="lib__lab">参考答案</p>${redPen(d.answer)}
      ${d.user_answer ? html`<p class="lib__lab">当时的作答</p>${bluePen(d.user_answer)}` : ''}
      ${d.note ? html`<p class="lib__lab">错因</p><p class="lib__note">${d.note}</p>` : ''}
    </div>
    ${records(d, s)}
    <div class="lib__acts">${d.deleted ? html`
      <button class="btn btn--sm btn--primary" data-action="lib.restore">恢复到题库</button><span class="muted">删除于 ${formatDay(d.deleted_at)}</span>` : html`
      <button class="btn btn--sm" data-action="lib.edit">编辑</button>
      <button class="btn btn--sm" data-action="lib.suspend">${d.suspended ? '恢复复习' : '停用（不再安排复习）'}</button>
      <button class="btn btn--sm btn--ghost btn--danger" data-action="lib.delete">删除</button>`}
    </div>`}
  </article>`;
}

function record(r, d, s) {
  const grades = gradesFor(d.genre);
  return html`<li class="rec ${r.voided ? 'is-void' : ''}" data-key="${r.commit_id}">
    <time>${formatDay(r.at)}</time>
    ${r.voided ? html`<span class="chip">${r.grade_label}</span>` : html`<select class="select rec__grade" data-change="lib.regrade" data-arg="${r.commit_id}" aria-label="改评分">
      ${each(grades, g => g.value, g => opt(String(g.value), g.label, String(r.grade)))}</select>`}
    <span class="muted rec__src">${r.session_id || '补记'}${r.voided ? ' · 已撤销' : ''}${r.restored_from ? ' · 恢复的' : ''}</span>
    <span class="rec__acts">${r.voided ? (r.restored_by ? '' : html`<button class="linkish" data-action="lib.unvoid" data-arg="${r.commit_id}">恢复</button>`) : html`
      <button class="linkish" data-action="lib.noteEdit" data-arg="${r.commit_id}">反馈</button>
      <button class="linkish" data-action="lib.void" data-arg="${r.commit_id}">撤销</button>`}</span>
    ${s.noteFor === r.commit_id ? html`<input class="input rec__noteinput" data-change="lib.note" data-arg="${r.commit_id}" value="${r.note || ''}"
      placeholder="这次错在哪、漏了哪个采分点（回车保存）" aria-label="复习反馈">` : r.note ? html`<p class="rec__note">${r.note}</p>` : ''}
  </li>`;
}

function records(d, s) {
  const all = d.records || [];
  const shown = s.showVoided ? all : all.filter(r => !r.voided);
  const voided = all.length - all.filter(r => !r.voided).length;
  return html`<section class="lib__hist">
    <header class="lib__histhead"><h3>复习记录</h3>
      ${voided ? html`<button class="linkish" data-action="lib.showVoided">${s.showVoided ? '隐藏' : '显示'}已撤销（${voided}）</button>` : ''}</header>
    ${shown.length ? html`<ol class="recs">${each(shown, r => r.commit_id, r => record(r, d, s))}</ol>`
      : html`<p class="muted">还没复习过${d.encounters > 1 ? `，已经第 ${d.encounters} 次作为错题录入` : ''}</p>`}
    ${d.deleted ? '' : html`<form class="rec__add" data-submit="lib.addRecord" aria-label="补记一次复习">
      <select class="select" name="grade" aria-label="评分">${each(gradesFor(d.genre), g => g.value, g => opt(String(g.value), g.label, '2'))}</select>
      <input class="input" type="date" name="date" max="${s.today}" value="${s.today}" aria-label="日期">
      <input class="input rec__addnote" name="note" placeholder="反馈（可选）" aria-label="反馈">
      <button class="btn btn--sm">补记一次</button>
    </form>`}
  </section>`;
}
