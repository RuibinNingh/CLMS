/** 复习页渲染：「安排这次复习」（按时间预算出清单）、复习列表、逐题评分 + 反馈，以及「拍照交给 AI 批改」。 */
import { html, each } from '../../core/html.js';
import { formatDay } from '../../core/format.js';
import { icon } from '../../ui/icons.js';
import { GENRES, genreShort, gradesFor } from '../../domain/genres.js';
import { blankLine, passage, redPen } from '../../domain/paper.js';

const BUDGETS = [20, 30, 40, 60];
const REASON_TONE = { 顽固: 'chip--bad', 新录入: 'chip--info', 提前复习: '' };

export function planner(s) {
  const p = s.plan;
  return html`<section class="card rv__plan">
    <header class="rv__head"><h2>安排这次复习</h2><span class="muted">${s.horizon ? `按 ${formatDay(s.horizon, { weekday: true })} 到期计算` : ''}</span></header>
    <div class="rv__opts">
      <div class="seg" role="group" aria-label="时间">${each(BUDGETS, m => m, m => html`<button data-action="rv.budget" data-arg="${m}" aria-pressed="${String(s.minutes === m)}">${m} 分钟</button>`)}</div>
      <div class="rv__genres">${each(GENRES, g => g.code, g => html`<button class="chip ${s.genres.has(g.code) ? 'chip--info' : ''}" data-action="rv.genre" data-arg="${g.code}" aria-pressed="${String(s.genres.has(g.code))}" data-genre="${g.code}"><span class="genre-dot"></span>${g.short}</button>`)}</div>
      <label class="rv__fill"><input type="checkbox" data-change="rv.fill" ${s.fill ? html`checked` : ''}>时间有富余时提前复习掌握度低的题</label>
      <button class="btn btn--primary" data-action="rv.plan">${p ? '重新生成' : '生成清单'}</button>
    </div>
    ${p ? html`
      <p class="rv__sum">${p.items.length ? html`共 <b>${p.items.length}</b> 题，约 <b>${Math.round(p.minutes)}</b> 分钟（含读原文）` : '没有可排的题'}${p.due_left ? html`；还有 ${p.due_left} 道到期题这次放不下` : ''}</p>
      ${p.items.length ? html`<ol class="rv__pick">${each(p.items, x => x.id, x => html`<li data-genre="${x.item.genre}">
        <span class="genre-dot"></span><span class="rv__what">${x.item.material_title ? `《${x.item.material_title}》` : ''}${x.item.no ? `第 ${x.item.no} 题 ` : ''}${x.item.genre === 'dictation' ? blankLine(x.item.stem, {}) : x.item.qtype || x.item.stem}</span>
        <span class="chip ${REASON_TONE[x.reason] ?? 'chip--warn'}">${x.reason}</span></li>`)}</ol>
      <div class="rv__confirm"><button class="btn btn--primary" data-action="rv.create">${icon('check')}确认安排</button></div>` : ''}` : ''}
  </section>`;
}

export function sessionList(s) {
  if (!s.sessions.length) return html`<p class="empty">还没有安排过复习</p>`;
  return html`<ul class="rv__list">${each(s.sessions, x => x.id, x => html`<li class="rv__row card">
    <div class="rv__rowmain"><b>${x.title || `${formatDay(x.planned_for, { weekday: true })}的复习`}</b>
      <span class="muted">${x.id} · ${x.progress.total} 题 · ${x.genres.map(genreShort).join('、')}</span></div>
    <div class="meter rv__meter" data-tone="${x.progress.complete ? 'high' : 'mid'}"><i data-w="${Math.round((x.progress.done / Math.max(1, x.progress.total)) * 20) * 5}"></i></div>
    <span class="rv__prog">${x.progress.complete ? '已评完' : `评了 ${x.progress.done}/${x.progress.total}`}</span>
    <a class="btn btn--sm" href="/print/session?id=${x.id}" target="_blank" rel="noopener">${icon('print')}打印</a>
    <a class="btn btn--sm btn--ghost" href="/print/session?id=${x.id}&answers=1" target="_blank" rel="noopener">含答案</a>
    <button class="btn btn--sm ${x.progress.complete ? '' : 'btn--primary'}" data-action="rv.open" data-arg="${x.id}">${x.progress.complete ? '查看' : '评分'}</button>
    <button class="btn btn--sm btn--ghost btn--icon" data-action="rv.cancel" data-arg="${x.id}" aria-label="删除这次复习" title="删除这次复习">${icon('trash')}</button>
  </li>`)}</ul>`;
}

function gradeRow(item, s) {
  const current = item.grade?.grade;
  return html`<div class="rv__grades" role="group" aria-label="自评">
    ${each(gradesFor(item.genre), g => g.value, g => html`<button class="gbtn" data-grade="${g.value}" data-action="rv.grade" data-arg="${item.id}:${g.value}"
      aria-pressed="${String(current === g.value)}" title="${g.hint}" ${s.busy === item.id ? html`disabled` : ''}>${g.label}</button>`)}
    ${item.grade ? html`<button class="linkish" data-action="rv.noteEdit" data-arg="${item.id}">${item.grade.note ? '改反馈' : '写反馈'}</button>
      <button class="linkish" data-action="rv.ungrade" data-arg="${item.id}">撤销</button>` : ''}
  </div>
  ${item.grade && s.noteFor === item.id ? html`<input class="input rv__noteinput" data-change="rv.note" data-arg="${item.id}" value="${item.grade.note || ''}"
    placeholder="错在哪、漏了哪个采分点（回车保存）" aria-label="复习反馈">`
    : item.grade?.note ? html`<p class="rv__note">${item.grade.note}</p>` : ''}`;
}

const isShown = (item, s) => s.revealed.has(item.id) || Boolean(item.grade);

/** 默写题面：同一道默写拆出的其它空若也在这次复习里、还没对答案，就把题面里现成的那句挖掉（标上它的题号）。 */
function dictationStem(item, s) {
  let stem = item.stem;
  const answers = { '': item.answer };
  s.session.items.forEach((other, i) => {
    if (other.id === item.id || other.genre !== 'dictation' || !other.template || other.template !== item.template) return;
    if (!other.answer || !stem.includes(other.answer) || isShown(other, s)) return;
    stem = stem.replace(other.answer, `{书写区域${i + 1}}`);
  });
  return blankLine(stem, answers, { reveal: isShown(item, s) });
}

function itemBlock(item, n, s) {
  const shown = isShown(item, s);
  const isDict = item.genre === 'dictation';
  return html`<div class="rv__q ${item.grade ? 'is-done' : ''}" data-key="${item.id}">
    <div class="rv__qhead"><span class="rv__n">${n}</span>${isDict ? html`<span class="muted">${item.source || '默写'}</span>` : html`<span class="chip chip--info">${item.qtype || '未分类'}</span>`}
      ${item.score ? html`<span class="muted">${item.score} 分</span>` : ''}</div>
    <div class="rv__stem">${isDict ? dictationStem(item, s) : item.stem}</div>
    ${shown ? (isDict ? '' : redPen(item.answer, 'rv__ans')) : html`<button class="btn btn--sm rv__reveal" data-action="rv.reveal" data-arg="${item.id}">对答案</button>`}
    ${shown ? gradeRow(item, s) : ''}
  </div>`;
}

export function grading(s) {
  const x = s.session;
  const blocks = [];
  let lastMat = null;
  x.items.forEach((item, i) => {
    const mid = item.material_id || null;
    if (mid && mid !== lastMat) {
      const m = x.materials[mid] || {};
      blocks.push(html`<details class="rv__mat" data-key="mat-${mid}" ${s.openMats.has(mid) ? html`open` : ''}>
        <summary data-action="rv.mat" data-arg="${mid}">《${m.title || '无题'}》${m.author ? ` ${m.author}` : ''}<span class="muted"> · 原文</span></summary>${passage(m.text, m.genre)}</details>`);
    }
    if (!mid && lastMat !== 'dictation' && item.genre === 'dictation') blocks.push(html`<h3 class="rv__sec" data-key="sec-dict">名句默写</h3>`);
    lastMat = mid || (item.genre === 'dictation' ? 'dictation' : null);
    blocks.push(itemBlock(item, i + 1, s));
  });
  return html`<div class="rv__grading">
    <header class="rv__ghead">
      <button class="btn btn--ghost btn--sm" data-action="rv.back">${icon('undo')}返回</button>
      <h2>${x.title || `${formatDay(x.planned_for, { weekday: true })}的复习`}</h2>
      <span class="muted">评了 ${x.progress.done}/${x.progress.total}</span>
      <a class="btn btn--sm" href="/print/session?id=${x.id}" target="_blank" rel="noopener">${icon('print')}打印</a>
      <label class="btn btn--sm btn--primary rv__ai" title="上传做完的复习卷照片，AI 对照参考答案逐题评分并写反馈">${icon('spark')}${s.aiBusy ? '上传中…' : '拍照交给 AI 批改'}
        <input type="file" accept="image/*" multiple class="visually-hidden" data-change="rv.aiGrade" ${s.aiBusy ? html`disabled` : ''}></label>
    </header>
    <p class="muted rv__tip">在纸上做完后逐题对答案、自评，或者拍照交给 AI 批改（结果可以在这里改、撤销）；评分会立即更新下次复习的时间。</p>
    <div class="paper rv__paper">${blocks}</div>
    ${x.progress.complete ? html`<p class="callout rv__end">这次复习评完了。下次复习日会自动排上到期的题。</p>` : ''}
  </div>`;
}
