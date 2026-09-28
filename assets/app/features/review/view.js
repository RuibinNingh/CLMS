/** 复习页渲染：复习列表、评分视图（左边纸面逐题评分 + 反馈，右边复习助手）。安排复习在 planner.js。 */
import { html, each } from '../../core/html.js';
import { formatDay } from '../../core/format.js';
import { icon } from '../../ui/icons.js';
import { genreShort, gradesFor } from '../../domain/genres.js';
import { blankLine, passage, redPen } from '../../domain/paper.js';
import { assistant } from './assistant.js';

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
  const pending = !item.grade && s.pendingNotes.get(item.id);
  return html`<div class="rv__grades" role="group" aria-label="自评">
    ${each(gradesFor(item.genre), g => g.value, g => html`<button class="gbtn" data-grade="${g.value}" data-action="rv.grade" data-arg="${item.id}:${g.value}"
      aria-pressed="${String(current === g.value)}" title="${g.hint}" ${s.busy === item.id ? html`disabled` : ''}>${g.label}</button>`)}
    ${item.grade ? html`<button class="linkish" data-action="rv.noteEdit" data-arg="${item.id}">${item.grade.note ? '改反馈' : '写反馈'}</button>
      <button class="linkish" data-action="rv.ungrade" data-arg="${item.id}">撤销</button>` : ''}
  </div>
  ${item.grade && s.noteFor === item.id ? html`<input class="input rv__noteinput" data-change="rv.note" data-arg="${item.id}" value="${item.grade.note || ''}"
    placeholder="错在哪、漏了哪个采分点（回车保存）" aria-label="复习反馈">`
    : item.grade?.note ? html`<p class="rv__note">${item.grade.note}</p>`
      : pending ? html`<p class="rv__note is-pending">反馈（评分时一起写入）：${pending} <button class="linkish" data-action="rv.dropNote" data-arg="${item.id}">不要了</button></p>` : ''}`;
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
  return html`<div class="rv__q ${item.grade ? 'is-done' : ''} ${s.focus === item.id ? 'is-focus' : ''}" data-key="${item.id}" data-action="rv.focus" data-arg="${item.id}">
    <div class="rv__qhead"><span class="rv__n">${n}</span>${isDict ? html`<span class="muted">${item.source || '默写'}</span>` : html`<span class="chip chip--info">${item.qtype || '未分类'}</span>`}
      ${item.score ? html`<span class="muted">${item.score} 分</span>` : ''}
      <button class="linkish rv__ask" data-action="rv.ask" data-arg="${item.id}">${icon('spark')}问 AI</button></div>
    <div class="rv__stem">${isDict ? dictationStem(item, s) : item.stem}</div>
    ${shown ? (isDict ? '' : redPen(item.answer, 'rv__ans')) : html`<button class="btn btn--sm rv__reveal" data-action="rv.reveal" data-arg="${item.id}">对答案</button>`}
    ${shown ? gradeRow(item, s) : ''}
  </div>`;
}

function materialHead(m, mid, s) {
  const byline = [m.author, m.source].filter(Boolean).join(' ');
  return html`<details class="rv__mat" data-key="mat-${mid}" ${s.openMats.has(mid) ? html`open` : ''}>
    <summary data-action="rv.mat" data-arg="${mid}"><span class="rv__mattitle">《${m.title || '无题'}》</span>
      ${byline ? html`<span class="rv__by">${byline}</span>` : ''}<span class="rv__toggle">${s.openMats.has(mid) ? '收起原文' : '展开原文'}</span></summary>
    ${passage(m.text, m.genre)}</details>`;
}

export function grading(s) {
  const x = s.session;
  const blocks = [];
  let lastMat = null;
  x.items.forEach((item, i) => {
    const mid = item.material_id || null;
    if (mid && mid !== lastMat) blocks.push(materialHead(x.materials[mid] || {}, mid, s));
    if (!mid && lastMat !== 'dictation' && item.genre === 'dictation') blocks.push(html`<h3 class="rv__sec" data-key="sec-dict">名句默写</h3>`);
    lastMat = mid || (item.genre === 'dictation' ? 'dictation' : null);
    blocks.push(itemBlock(item, i + 1, s));
  });
  return html`<div class="rv__grading ${s.ai.open ? 'is-ai-open' : ''}">
    <header class="rv__ghead">
      <button class="btn btn--ghost btn--sm" data-action="rv.back">${icon('undo')}返回</button>
      <h2>${x.title || `${formatDay(x.planned_for, { weekday: true })}的复习`}</h2>
      <span class="muted">评了 ${x.progress.done}/${x.progress.total}</span>
      <a class="btn btn--sm" href="/print/session?id=${x.id}" target="_blank" rel="noopener">${icon('print')}打印</a>
      <button class="btn btn--sm rv__aitoggle" data-action="rv.aiToggle" aria-pressed="${String(s.ai.open)}">${icon('spark')}复习助手</button>
    </header>
    <p class="muted rv__tip">在纸上做完后逐题对答案、自评。复习助手可以随时问这道题、帮你打分或写反馈，点「采用」才会记下；评分会立即更新下次复习的时间。</p>
    <div class="rv__desk">
      <div class="paper rv__paper">${blocks}</div>
      ${assistant(s)}
    </div>
    ${x.progress.complete ? html`<p class="callout rv__end">这次复习评完了。下次复习日会自动排上到期的题。</p>` : ''}
  </div>`;
}
