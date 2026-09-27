/**
 * 草稿画布里的单题卡片：阅读小题（题号、题型、分值、题干、留白横线、红笔答案、我的作答 / 解析 / 错因）
 * 与默写题（模板预览、模板、答案表、逐空去重结果）。输入一律 data-input="entry.field" + data-path。
 */
import { html, each } from '../../core/html.js';
import { icon } from '../../ui/icons.js';
import { blankLine } from '../../domain/paper.js';
import { blankNumbers } from './edit.js';

const ORIGIN = { image: ['图中答案', 'chip--ok'], ai: ['AI 补写', 'chip--warn'], user: ['手改', 'chip--info'] };

export const isFlash = (flash, gid, iid, field) =>
  Boolean(flash && (flash.has(`${gid}|${iid}|${field}`) || flash.has(`${gid}|${iid}|*`)));

const area = (path, value, { cls = '', placeholder = '', ro, rows = 1 } = {}) => html`
  <textarea class="ta ${cls}" rows="${rows}" data-path="${path}" data-input="entry.field" data-autosize
    placeholder="${placeholder}" ${ro ? html`readonly` : ''}>${value || ''}</textarea>`;

function qtypeSelect(path, value, options, ro) {
  const list = options.includes(value) || !value ? options : [value, ...options];
  return html`<select class="qtype ${value ? '' : 'qtype--empty'}" data-path="${path}" data-change="entry.field"
    aria-label="题型" ${ro ? html`disabled` : ''}>
    <option value="" ${value ? '' : html`selected`}>选择题型</option>
    ${each(list, q => q, q => html`<option value="${q}" ${q === value ? html`selected` : ''}>${q}${options.includes(q) ? '' : '（新）'}</option>`)}
  </select>`;
}

function extra(path, label, value, cls, ro, open) {
  if (!value && !open) {
    return ro ? '' : html`<button class="linkish" data-action="entry.reveal" data-arg="${path}">+ ${label}</button>`;
  }
  return html`<div class="q__extra"><span class="q__label">${label}</span>${area(path, value, { cls, ro })}</div>`;
}

export function itemCard(group, item, o) {
  const base = `${group.gid}|${item.iid}`;
  const dup = o.dedupe?.items?.[item.iid]?.dup_item_id;
  const origin = ORIGIN[item.answer_origin];
  const fl = field => (isFlash(o.flash, group.gid, item.iid, field) ? html`data-flash` : '');
  const open = field => o.opened.has(`${base}|${field}`);
  const n = item.blank_lines || 0;
  return html`
  <div class="q" data-key="${item.iid}" data-anchor="${base}" ${isFlash(o.flash, group.gid, item.iid, '*') ? html`data-flash` : ''}>
    <div class="q__head">
      <input class="q__no" value="${item.no}" data-path="${base}|no" data-input="entry.field" aria-label="题号" placeholder="#" ${o.ro ? html`readonly` : ''}>
      <span class="q__slot" ${fl('qtype')}>${qtypeSelect(`${base}|qtype`, item.qtype, o.qtypes, o.ro)}</span>
      <label class="q__score" ${fl('score')}><input type="number" min="0" max="30" step="1" value="${item.score ?? ''}"
        data-path="${base}|score" data-input="entry.field" aria-label="分值" ${o.ro ? html`readonly` : ''}>分</label>
      ${dup ? html`<span class="chip chip--warn" title="题库里已有 ${dup}">库中已有 · 记又错一次</span>` : ''}
      <span class="q__tools">${o.ro ? '' : html`<button class="btn btn--ghost btn--icon" data-action="entry.remove" data-arg="${base}" title="删除这道题" aria-label="删除这道题">${icon('trash')}</button>`}</span>
    </div>
    <div class="q__stem" ${fl('stem')}>${area(`${base}|stem`, item.stem, { cls: 'ta--read', placeholder: '题干', ro: o.ro })}</div>
    <div class="q__blank" ${fl('blank_lines')}>
      <div class="ruled ruled--mini" aria-hidden="true">${Array.from({ length: n }, () => html`<i></i>`)}</div>
      <div class="stepper">
        <button class="btn btn--sm btn--icon" data-action="entry.lines" data-arg="-1" data-path="${base}" aria-label="少留一行" ${o.ro || n <= 0 ? html`disabled` : ''}>${icon('minus')}</button>
        <span>${n ? `留白 ${n} 行` : '不留白'}</span>
        <button class="btn btn--sm btn--icon" data-action="entry.lines" data-arg="1" data-path="${base}" aria-label="多留一行" ${o.ro || n >= 24 ? html`disabled` : ''}>${icon('plus')}</button>
      </div>
    </div>
    <div class="q__ans" ${fl('answer')}>
      <span class="q__label">参考答案 ${origin ? html`<span class="chip ${origin[1]}">${origin[0]}</span>` : ''}</span>
      ${area(`${base}|answer`, item.answer, { cls: 'ta--red', placeholder: '参考答案（红笔）', ro: o.ro })}
    </div>
    <div class="q__more">
      <span ${fl('user_answer')}>${extra(`${base}|user_answer`, '我的作答', item.user_answer, 'ta--blue', o.ro, open('user_answer'))}</span>
      <span ${fl('analysis')}>${extra(`${base}|analysis`, '解析', item.analysis, '', o.ro, open('analysis'))}</span>
      <span ${fl('note')}>${extra(`${base}|note`, '错因', item.note, '', o.ro, open('note'))}</span>
    </div>
  </div>`;
}

function blankRow(base, num, entry, rows, o) {
  const row = (rows || []).find(r => r.blank === num);
  let chip = html`<span class="chip chip--ok">新</span>`;
  if (row?.dup_item_id) chip = html`<span class="chip chip--warn" title="${row.dup_item_id}">库中已有 · 记又错一次</span>`;
  else if (row?.dup_in_draft) chip = html`<span class="chip">本稿重复 · 跳过</span>`;
  if (!row) chip = '';
  return html`<div class="dict__blank" data-key="${num}">
    <span class="dict__n">${num}</span>
    <input class="dict__ans" value="${entry.blanks?.[num] || ''}" data-path="${base}|blank:${num}" data-input="entry.field"
      placeholder="书写区域${num} 的答案" ${o.ro ? html`readonly` : ''}>
    ${chip}
  </div>`;
}

export function dictationCard(group, entry, o) {
  const base = `${group.gid}|${entry.iid}`;
  const nums = blankNumbers(entry.template);
  const rows = o.dedupe?.dictation?.[entry.iid];
  const fl = field => (isFlash(o.flash, group.gid, entry.iid, field) ? html`data-flash` : '');
  return html`
  <div class="dict" data-key="${entry.iid}" data-anchor="${base}" ${isFlash(o.flash, group.gid, entry.iid, '*') ? html`data-flash` : ''}>
    <div class="dict__preview" ${fl('template')}>${entry.template ? blankLine(entry.template, entry.blanks || {}, { reveal: true }) : html`<span class="paper-empty">（题面为空）</span>`}</div>
    <div class="dict__edit">
      ${area(`${base}|template`, entry.template, { cls: 'ta--read', placeholder: '床前明月光，{书写区域1}。', ro: o.ro })}
      ${o.ro ? '' : html`<button class="btn btn--sm" data-action="entry.insertBlank" data-arg="${base}" title="在末尾插入一个书写区域">插入空</button>`}
    </div>
    <div class="dict__blanks" ${fl('blanks')}>${nums.length ? each(nums, n => n, n => blankRow(base, n, entry, rows, o))
      : html`<span class="q__hint">用 {书写区域1}、{书写区域2} 标出要默写的空，每个空入库后是一道独立小题</span>`}</div>
    <div class="dict__meta">
      <input class="input dict__src" value="${entry.source}" data-path="${base}|source" data-input="entry.field" placeholder="出处，如 李白《静夜思》" ${o.ro ? html`readonly` : ''}>
      <select class="select dict__kind" data-path="${base}|kind" data-change="entry.field" aria-label="默写类型" ${o.ro ? html`disabled` : ''}>
        ${each(['直接默写', '理解性默写'], k => k, k => html`<option value="${k}" ${k === entry.kind ? html`selected` : ''}>${k}</option>`)}
      </select>
      ${o.ro ? '' : html`<button class="btn btn--ghost btn--icon" data-action="entry.remove" data-arg="${base}" aria-label="删除这道默写" title="删除这道默写">${icon('trash')}</button>`}
    </div>
  </div>`;
}
