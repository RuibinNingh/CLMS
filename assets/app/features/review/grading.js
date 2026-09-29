/**
 * 评分视图（一次看一道题）。页头：返回、这次复习、进度、打印。主区：
 * - 原文（有材料时）：题目区够宽（容器查询，见 grading.css）时在题目左边、各自滚动；不够宽时排在题目下面。
 *   原文没有自带 ①②③ 时加段号。选中文字可以「引用」给助手。
 * - 这道题：题干 → 对答案 → 参考答案（红笔）与解析 → 自评（评分档和说明常显，数字键直接评）→ 反馈 → 上一题 / 下一题。
 * - 右边复习助手（assistant.js）。
 * 同一材料的题前后切换时原文的滚动位置保留（按材料 data-key 复用节点）；换材料时从头看。
 */
import { html, each } from '../../core/html.js';
import { formatDay } from '../../core/format.js';
import { icon } from '../../ui/icons.js';
import { genreShort, gradesFor } from '../../domain/genres.js';
import { blankLine, passage } from '../../domain/paper.js';
import { meterWidth, sessionTitle } from './rail.js';
import { assistant } from './assistant.js';
import { NEVER, focusTarget, isShown } from './focus.js';

/** 默写题面：同一道默写拆出的其它空若也在这次复习里、还没对答案，就把题面里现成的那句挖掉（标上它的题号）。 */
function dictationStem(item, s) {
  let stem = item.stem;
  s.session.items.forEach((other, i) => {
    if (other.id === item.id || other.genre !== 'dictation' || !other.template || other.template !== item.template) return;
    if (!other.answer || !stem.includes(other.answer) || isShown(other, s)) return;
    stem = stem.replace(other.answer, `{书写区域${i + 1}}`);
  });
  return blankLine(stem, { '': item.answer }, { reveal: isShown(item, s) });
}

function top(s) {
  const x = s.session;
  const p = x.progress;
  return html`<header class="rv-top">
    <button class="btn btn--ghost btn--icon rv-top__rail" data-action="rv.rail" aria-label="打开答题卡" title="答题卡">${icon('panel')}</button>
    <button class="btn btn--ghost btn--sm rv-top__back" data-action="rv.back">${icon('back')}全部复习</button>
    <div class="rv-top__title"><h2>${sessionTitle(x)}</h2>
      <small>${x.items.length} 题${x.minutes ? ` · 约 ${x.minutes} 分钟` : ''}</small></div>
    <span class="rv-top__prog" title="评了 ${p.done}/${p.total}"><span class="meter" data-tone="${p.complete ? 'high' : 'mid'}"><i data-w="${meterWidth(p)}"></i></span>
      <em>${p.complete ? '已评完' : `评了 ${p.done}/${p.total}`}</em></span>
    <span class="rv-top__acts">
      <a class="btn btn--sm" href="/print/session?id=${x.id}" target="_blank" rel="noopener" aria-label="打印这次复习">${icon('print')}<span class="rv-top__lab">打印</span></a>
      <a class="btn btn--sm btn--ghost rv-top__more" href="/print/session?id=${x.id}&answers=1" target="_blank" rel="noopener">含答案</a>
    </span>
    <button class="btn btn--sm rv-top__ai" data-action="rv.aiToggle" aria-pressed="${String(s.ai.open)}" aria-label="复习助手">${icon('spark')}<span class="rv-top__lab">助手</span></button>
  </header>`;
}

const CIRCLED = /^[\u2460-\u2473\u3251-\u325f]/;      // 原文自带 ①②③ 段号时不再另加

function material(mat, mid) {
  const byline = [mat.author, mat.source].filter(Boolean).join(' ');
  return html`<section class="rv-mat" data-key="mat-${mid}" data-mid="${mid}" data-title="${mat.title || '无题'}" aria-label="原文《${mat.title || '无题'}》">
    <div class="paper rv-mat__sheet">
      <header class="rv-mat__head"><h3>《${mat.title || '无题'}》</h3>${byline ? html`<p>${byline}</p>` : ''}</header>
      ${passage(mat.text, mat.genre, { numbered: !CIRCLED.test(String(mat.text || '').trim()) })}
    </div>
  </section>`;
}

const reveal = item => html`<div class="rv-reveal">
  <p>先在纸上写完这道，再对答案。</p>
  <button class="btn btn--primary rv-reveal__btn" data-action="rv.reveal" data-arg="${item.id}" aria-keyshortcuts="Space">对答案<kbd>空格</kbd></button>
</div>`;

function answer(item, n) {
  const isDict = item.genre === 'dictation';
  return html`<section class="rv-ans" aria-label="参考答案">
    ${isDict ? '' : html`<h4 class="rv-lab">参考答案</h4>
      <div class="red-pen rv-ans__pen" data-q="${n}" data-part="answer">${(item.answer || '').trim() || '（没有答案）'}</div>`}
    ${(item.analysis || '').trim() ? html`<h4 class="rv-lab">解析</h4><p class="rv-ans__note">${item.analysis.trim()}</p>` : ''}
  </section>`;
}

function nextText(item, today) {
  const due = item.sched?.due;
  if (!due) return '已记下';
  if (due === NEVER) return '已记下，掌握了，不再安排';
  return `已记下，下次 ${formatDay(due, { weekday: true })}${due <= today ? '（今天就到期）' : ''}`;
}

function score(item, s) {
  const current = item.grade?.grade;
  const busy = s.busy === item.id;
  return html`<section class="rv-score" aria-labelledby="rv-score-lab">
    <h4 class="rv-lab" id="rv-score-lab">自评</h4>
    <div class="rv-score__opts" role="group" aria-label="自评">
      ${each(gradesFor(item.genre), g => g.value, g => html`<button class="rv-score__opt" data-grade="${g.value}" data-action="rv.grade"
        data-arg="${item.id}:${g.value}" aria-pressed="${String(current === g.value)}" aria-keyshortcuts="${g.value}" ${busy ? html`disabled` : ''}>
        <span class="rv-score__top"><b>${g.label}</b><kbd>${g.value}</kbd></span><small>${g.hint}</small></button>`)}
    </div>
    ${item.grade ? html`<p class="rv-score__after">${icon('check')}<span>${nextText(item, s.today)}</span>
      <button class="linkish" data-action="rv.ungrade" data-arg="${item.id}">撤销评分</button></p>` : ''}
  </section>`;
}

function feedback(item, s) {
  const pending = !item.grade ? s.pendingNotes.get(item.id) || '' : '';
  const value = item.grade ? item.grade.note || '' : pending;
  return html`<section class="rv-fb ${pending ? 'is-pending' : ''}">
    <label class="rv-lab" for="rv-fb-${item.id}">反馈</label>
    <input id="rv-fb-${item.id}" class="input rv-fb__input" data-change="rv.note" data-arg="${item.id}" value="${value}" maxlength="200"
      autocomplete="off" placeholder="${item.grade ? '错在哪、漏了哪个采分点（回车保存）' : '可以先写，评分时一起记下'}">
    ${pending ? html`<p class="rv-fb__hint">评分时一起写入 · <button class="linkish" data-action="rv.dropNote" data-arg="${item.id}">不要了</button></p>` : ''}
  </section>`;
}

function stepper(n, s) {
  const x = s.session;
  const item = x.items[n - 1];
  const next = x.items[n];
  const todo = x.items.find(it => !it.grade && it.id !== item.id);
  let end = '';
  if (!next) {
    end = x.progress.complete ? html`<span class="rv-step__end">${icon('check')}这次复习评完了，下次复习日会自动排上到期的题</span>`
      : todo ? html`<button class="btn" data-action="rv.go" data-arg="${todo.id}">去第 ${x.items.indexOf(todo) + 1} 题（还没评）</button>` : '';
  }
  return html`<nav class="rv-step" aria-label="换题">
    <button class="btn btn--ghost" data-action="rv.step" data-arg="-1" aria-keyshortcuts="ArrowLeft" ${n > 1 ? '' : html`disabled`}>${icon('back')}上一题</button>
    ${next ? html`<button class="btn ${item.grade ? 'btn--primary' : ''}" data-action="rv.step" data-arg="1" aria-keyshortcuts="ArrowRight">下一题${icon('chevron')}</button>` : end}
  </nav>`;
}

function question(item, n, s) {
  const x = s.session;
  const shown = isShown(item, s);
  const isDict = item.genre === 'dictation';
  const mat = item.material_id ? x.materials[item.material_id] : null;
  const kind = isDict ? item.source || '名句默写' : item.qtype || '未分类';
  return html`<article class="rv-q paper" data-key="q-${item.id}" data-genre="${item.genre}" aria-label="第 ${n} 题" tabindex="-1">
    <header class="rv-q__head">
      <p class="rv-q__pos"><b>${n}</b><span>/ ${x.items.length}</span></p>
      <p class="rv-q__meta"><span class="genre-dot"></span><span>${genreShort(item.genre)}</span><span>${kind}</span>
        ${item.score ? html`<span>${item.score} 分</span>` : ''}${item.no ? html`<span>原卷第 ${item.no} 题</span>` : ''}</p>
      ${mat ? html`<p class="rv-q__src">${icon('book')}《${mat.title || '无题'}》</p>` : ''}
    </header>
    <div class="rv-q__stem" data-q="${n}" data-part="stem">${isDict ? dictationStem(item, s) : item.stem}</div>
    ${shown ? html`${answer(item, n)}${score(item, s)}${feedback(item, s)}` : reveal(item)}
    ${stepper(n, s)}
  </article>`;
}

export function gradingView(s) {
  const t = focusTarget(s);
  if (!t) return html`${top(s)}<p class="empty">这次复习里没有题</p>`;
  const { it, n } = t;
  const mat = it.material_id ? s.session.materials[it.material_id] : null;
  return html`${top(s)}
    <div class="rv-desk">
      <div class="rv-stage">
        <div class="rv-sheets" data-mat="${mat ? 'yes' : 'no'}">
          <div class="rv-qcol" data-key="qcol-${it.id}">${question(it, n, s)}</div>
          ${mat ? material(mat, it.material_id) : ''}
        </div>
      </div>
      ${assistant(s)}
    </div>`;
}
