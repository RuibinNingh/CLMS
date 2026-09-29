/**
 * 复习页左栏。安排时是「复习记录」：进行中的在上、评完的在下，点一行进入评分，悬浮出现打印 / 删除。
 * 评分时是这次复习的「答题卡」：按材料分组的题号，方框里的数字就是卷上题序；评过的按评分着色并写出评分，
 * 对过答案还没评的方框是虚线，正在看的这道填墨蓝。≤ 1160 左栏变抽屉（页头左边的按钮打开）。
 */
import { html, each } from '../../core/html.js';
import { formatDay } from '../../core/format.js';
import { icon } from '../../ui/icons.js';
import { genreShort, gradeLabel } from '../../domain/genres.js';
import { blankLine } from '../../domain/paper.js';

export const sessionTitle = x => x.title || `${formatDay(x.planned_for, { weekday: true })}的复习`;
export const meterWidth = p => Math.round((p.done / Math.max(1, p.total)) * 20) * 5;

const closeButton = label => html`<button class="btn btn--ghost btn--icon rv-rail__close" data-action="rv.rail" aria-label="${label}">${icon('close')}</button>`;

function sessRow(x) {
  const p = x.progress;
  return html`<li class="rv-sess" data-key="${x.id}" data-done="${String(p.complete)}">
    <button class="rv-sess__main" data-action="rv.open" data-arg="${x.id}">
      <b>${sessionTitle(x)}</b>
      <small>${p.total} 题 · ${x.genres.map(genreShort).join('、') || '—'}</small>
      <span class="rv-sess__prog"><span class="meter" data-tone="${p.complete ? 'high' : 'mid'}"><i data-w="${meterWidth(p)}"></i></span>
        <em>${p.complete ? '已评完' : `评了 ${p.done}/${p.total}`}</em></span>
    </button>
    <span class="rv-sess__acts">
      <a class="btn btn--ghost btn--icon btn--sm" href="/print/session?id=${x.id}" target="_blank" rel="noopener" title="打印" aria-label="打印${sessionTitle(x)}">${icon('print')}</a>
      <button class="btn btn--ghost btn--icon btn--sm" data-action="rv.cancel" data-arg="${x.id}" title="删除" aria-label="删除${sessionTitle(x)}">${icon('trash')}</button>
    </span>
  </li>`;
}

export function sessionsRail(s) {
  const all = s.sessions || [];
  const open = all.filter(x => !x.progress.complete);
  const done = all.filter(x => x.progress.complete);
  let body = '';
  if (s.sessions === null) body = html`<p class="rv-rail__empty">正在加载…</p>`;
  else if (!all.length) body = html`<p class="rv-rail__empty">还没有安排过复习。在右边排好题、确认之后，会出现在这里，可以打印和评分。</p>`;
  return html`<div class="rv-rail" data-kind="sessions">
    <header class="rv-rail__head"><h2>复习记录</h2>${closeButton('收起复习记录')}</header>
    <button class="rv-rail__new" data-action="rv.newPlan" aria-current="${s.session ? 'false' : 'page'}">${icon('plus')}安排新的复习</button>
    <div class="rv-rail__scroll">
      ${body}
      ${open.length ? html`<h3 class="rv-rail__sec">进行中<small>${open.length}</small></h3><ul class="rv-sess-list">${each(open, x => x.id, sessRow)}</ul>` : ''}
      ${done.length ? html`<h3 class="rv-rail__sec">已评完<small>${done.length}</small></h3><ul class="rv-sess-list">${each(done, x => x.id, sessRow)}</ul>` : ''}
    </div>
  </div>`;
}

/** 这次复习按材料分组（默写合成一组），保持卷上顺序；n 是卷上题序。 */
export function navGroups(x) {
  const out = [];
  let last = null;
  x.items.forEach((item, i) => {
    const key = item.material_id || (item.genre === 'dictation' ? 'dictation' : `solo-${item.id}`);
    if (!last || last.key !== key) {
      const mat = item.material_id ? x.materials[item.material_id] : null;
      last = { key, genre: item.genre, title: mat ? `《${mat.title || '无题'}》` : item.genre === 'dictation' ? '名句默写' : genreShort(item.genre), rows: [] };
      out.push(last);
    }
    last.rows.push({ item, n: i + 1 });
  });
  return out;
}

/** 默写只取挖空前后几个字（「感时花溅泪，____。」），同一句拆出的几空才分得清。 */
function dictShort(stem) {
  const at = stem.indexOf('{书写区域}');
  if (at < 0) return stem;
  const before = stem.slice(0, at).split(/[：:]/).pop().slice(-8);
  return `${before}{书写区域}${stem.slice(at + 6, at + 14)}`;
}

const what = item => (item.genre === 'dictation' ? html`<span class="rv-nav__dict">${blankLine(dictShort(item.stem), {})}</span>` : item.qtype || '未分类');

function navRow({ item, n }, s) {
  const g = item.grade;
  const state = g ? 'graded' : s.revealed.has(item.id) ? 'revealed' : 'todo';
  const said = g ? `已评：${gradeLabel(item.genre, g.grade)}` : state === 'revealed' ? '对过答案，还没评' : '还没对答案';
  return html`<li data-key="${item.id}"><button class="rv-nav__row" data-action="rv.go" data-arg="${item.id}" data-state="${state}"
    data-grade="${g ? g.grade : ''}" ${s.focus === item.id ? html`aria-current="step"` : ''}
    aria-label="第 ${n} 题，${item.genre === 'dictation' ? '默写' : item.qtype || '未分类'}，${said}">
    <span class="rv-nav__n">${n}</span><span class="rv-nav__what">${what(item)}</span>
    <span class="rv-nav__grade">${g ? gradeLabel(item.genre, g.grade) : ''}</span>
  </button></li>`;
}

export function questionNav(s) {
  const x = s.session;
  return html`<div class="rv-rail" data-kind="nav">
    <header class="rv-rail__head"><h2>答题卡</h2><small>${x.progress.done}/${x.progress.total}</small>${closeButton('收起答题卡')}</header>
    <div class="rv-rail__scroll">
      <ol class="rv-nav">${each(navGroups(x), g => g.key, g => html`<li class="rv-nav__group" data-genre="${g.genre}">
        <p class="rv-nav__gtitle"><span class="genre-dot"></span><span>${g.title}</span></p>
        <ol class="rv-nav__rows">${each(g.rows, r => r.item.id, r => navRow(r, s))}</ol></li>`)}</ol>
    </div>
    <dl class="rv-keys" aria-label="快捷键">
      <div><dt><kbd>←</kbd><kbd>→</kbd></dt><dd>换题</dd></div>
      <div><dt><kbd>空格</kbd></dt><dd>对答案</dd></div>
      <div><dt><kbd>0</kbd>–<kbd>3</kbd></dt><dd>自评</dd></div>
      <div><dt><kbd>/</kbd></dt><dd>问助手</dd></div>
    </dl>
  </div>`;
}
