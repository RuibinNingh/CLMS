/**
 * 纸面渲染（录入草稿、题库详情、复习共用）：原文分段、答题横线、默写下划线、红笔答案。
 * 原文按换行分段；以「注」开头的段落按注释排小字；古诗不缩进。每段带 data-para（段号，1 起），
 * 与复习助手 material_read 的段号一致，评分页选中文字「引用」时靠它定位。
 */
import { html, each } from '../core/html.js';

export const TARGET = '{书写区域}';
const PLACEHOLDER = /[{｛]\s*书写区域\s*(\d*)\s*[}｝]/g;

export function passage(text, genre, { numbered = false } = {}) {
  const paras = String(text || '').split('\n').map(p => p.trim()).filter(Boolean);
  if (!paras.length) return html`<p class="paper-empty">（没有原文）</p>`;
  return html`<div class="passage ${genre === 'poetry' ? 'passage--poem' : ''}">${each(paras, (_, i) => i, (p, i) => html`
    <p class="${p.startsWith('注') ? 'passage__note' : ''}" data-para="${i + 1}">${numbered && genre !== 'poetry' ? html`<span class="passage__n">${i + 1}</span>` : ''}${p}</p>`)}</div>`;
}

export const ruled = n => html`<div class="ruled" aria-label="${n} 行答题区">${Array.from({ length: Math.max(0, n) }, () => html`<i></i>`)}</div>`;

/** 默写题面：把 {书写区域} / {书写区域n} 画成下划线；reveal 时把答案用红笔写在线上。 */
export function blankLine(template, answers = {}, { reveal = false, target = null } = {}) {
  const parts = [];
  let last = 0;
  const text = String(template || '');
  for (const m of text.matchAll(PLACEHOLDER)) {
    parts.push(text.slice(last, m.index));
    const n = m[1] || '';
    const answer = n ? answers[n] : answers[''] ?? answers.answer;
    const width = Math.max(4, Math.round(String(answer || '').length * 1.15 + 1.5));
    parts.push(html`<span class="blank ${target && n === target ? 'blank--target' : ''}" data-w="${Math.min(width, 16)}">${n && !reveal ? html`<sup>${n}</sup>` : ''}${reveal && answer ? html`<b>${answer}</b>` : ''}</span>`);
    last = m.index + m[0].length;
  }
  parts.push(text.slice(last));
  return html`<span class="blank-line">${parts}</span>`;
}

export const redPen = (text, cls = '') => html`<div class="red-pen ${cls}">${String(text || '').trim() || '（没有答案）'}</div>`;
export const bluePen = text => html`<div class="blue-pen">${text}</div>`;
