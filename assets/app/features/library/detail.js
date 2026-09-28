/**
 * 题库详情（右侧）：状态卡、纸面题目与红笔答案、同篇的其它题、复习记录（补记 / 改评 / 反馈 / 撤销 / 恢复）、编辑表单。
 * 复习记录的增删改查全部是追加提交（对标 OMRS 历史修正）；「已删除」的题可以恢复。
 */
import { html, each } from '../../core/html.js';
import { formatDay } from '../../core/format.js';
import { icon } from '../../ui/icons.js';
import { genreShort, gradeLabel, gradesFor } from '../../domain/genres.js';
import { blankLine, bluePen, passage, redPen } from '../../domain/paper.js';
import { dueText } from './view.js';

const KIND = { skill: '理解型', recall: '记忆型' };
const opt = (value, label, current) => html`<option value="${value}" ${value === current ? html`selected` : ''}>${label}</option>`;

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

function siblings(d, s) {
  const others = (d.siblings || []).filter(x => x.id !== d.id);
  if (!others.length) return '';
  return html`<p class="lib__sibs"><span class="muted">同一篇还有</span>
    ${each(others, x => x.id, x => html`<button class="chip" data-action="lib.select" data-arg="${x.id}">${x.no ? `第 ${x.no} 题 ` : ''}${x.qtype || x.id}</button>`)}</p>`;
}

export function detail(s) {
  const d = s.detail;
  if (!d) return html`<div class="lib__none">${s.items.length || s.groups.length ? '选一道题看详情' : ''}</div>`;
  const sc = d.sched;
  return html`<article class="lib__detail" data-genre="${d.genre}">
    <header class="lib__dhead">
      <span class="genre-dot"></span><b>${genreShort(d.genre)}${d.qtype ? ` · ${d.qtype}` : ''}</b><span class="muted">${d.id}</span>
      <button class="btn btn--ghost btn--icon lib__close" data-action="lib.close" aria-label="关闭">${icon('close')}</button>
    </header>
    <dl class="lib__stats">
      <div><dt>状态</dt><dd>${sc.leech ? '顽固' : sc.status}</dd></div>
      <div><dt>类型</dt><dd title="${sc.kind === 'skill' ? '做对一次就算掌握，很久才抽查' : '按间隔重复反复考'}">${KIND[sc.kind] || '—'}</dd></div>
      <div><dt>掌握度</dt><dd>${Math.round(sc.decayed * 100)}%</dd></div>
      <div><dt>下次</dt><dd>${d.deleted || d.suspended ? '—' : dueText(sc, s.today)}</dd></div>
      <div><dt>上次</dt><dd>${sc.reviews ? `${formatDay(sc.last_review)} ${gradeLabel(d.genre, sc.last_grade)}` : '没复习过'}</dd></div>
      <div><dt>出错</dt><dd>${d.encounters} 次录入</dd></div>
    </dl>
    ${s.editing ? editor(d, s) : html`
    <div class="paper lib__paper">
      ${d.material ? html`<details class="lib__mat"><summary><span class="lib__mattitle">《${d.material.title || '无题'}》</span>${d.material.author ? html`<span class="lib__matby">${d.material.author}</span>` : ''}<span class="lib__matby">原文</span></summary>
        ${d.material.source ? html`<p class="lib__matsrc">${d.material.source}</p>` : ''}${passage(d.material.text, d.genre)}</details>` : ''}
      <div class="lib__stem">${d.genre === 'dictation' ? blankLine(d.stem, { '': d.answer }) : d.stem}</div>
      ${d.genre === 'dictation' ? '' : html`<div class="ruled">${Array.from({ length: Math.min(d.blank_lines || 0, 6) }, () => html`<i></i>`)}</div>`}
      <p class="lib__lab">参考答案</p>${redPen(d.answer)}
      ${d.user_answer ? html`<p class="lib__lab">当时的作答</p>${bluePen(d.user_answer)}` : ''}
      ${d.note ? html`<p class="lib__lab">错因</p><p class="lib__note">${d.note}</p>` : ''}
    </div>
    ${siblings(d, s)}
    ${records(d, s)}
    <div class="lib__acts">${d.deleted ? html`
      <button class="btn btn--sm btn--primary" data-action="lib.restore">恢复到题库</button><span class="muted">删除于 ${formatDay(d.deleted_at)}</span>` : html`
      <button class="btn btn--sm btn--primary" data-action="lib.toReview" title="带到复习页，作为自选题排进下一次复习">${icon('review')}加入复习</button>
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
