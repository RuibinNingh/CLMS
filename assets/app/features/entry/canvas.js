/**
 * 草稿画布：一张「试卷」——每个 group 是一个板块（材料 + 小题，或一组默写）。
 * 原文默认折叠到约 8 行，点「展开原文」可全文编辑；AI 刚改过的字段带 data-flash，由 CSS 做一次性底色。
 */
import { html, each } from '../../core/html.js';
import { icon } from '../../ui/icons.js';
import { GENRES } from '../../domain/genres.js';
import { passage } from '../../domain/paper.js';
import { dictationCard, isFlash, itemCard } from './canvas-items.js';

function genreSelect(group, ro) {
  return html`<select class="grp__genre" data-path="${group.gid}||genre" data-change="entry.field" aria-label="板块" ${ro ? html`disabled` : ''}>
    ${each(GENRES, g => g.code, g => html`<option value="${g.code}" ${g.code === group.genre ? html`selected` : ''}>${g.name}</option>`)}
  </select>`;
}

function material(group, o) {
  const m = group.material;
  const base = `${group.gid}|`;
  const open = o.expanded.has(group.gid);
  const chars = (m.text || '').replace(/\s/g, '').length;
  const fl = field => (isFlash(o.flash, group.gid, '', field) ? html`data-flash` : '');
  return html`
  <div class="mat">
    <div class="mat__line">
      <span class="mat__title" ${fl('title')}><input value="${m.title}" data-path="${base}|title" data-input="entry.field" placeholder="标题" aria-label="标题" ${o.ro ? html`readonly` : ''}></span>
      <span class="mat__by" ${fl('author')}><input value="${m.author}" data-path="${base}|author" data-input="entry.field" placeholder="作者" aria-label="作者" ${o.ro ? html`readonly` : ''}></span>
      <span class="mat__by" ${fl('source')}><input value="${m.source}" data-path="${base}|source" data-input="entry.field" placeholder="出处" aria-label="出处" ${o.ro ? html`readonly` : ''}></span>
    </div>
    <div class="mat__text ${open ? 'is-open' : ''}" ${fl('text')}>
      ${open ? html`<textarea class="ta ta--read ta--passage" data-path="${base}|text" data-input="entry.field" data-autosize
        placeholder="原文（段落之间换行）" aria-label="原文" ${o.ro ? html`readonly` : ''}>${m.text || ''}</textarea>`
    : html`<div class="mat__read">${passage(m.text, group.genre)}</div>`}
    </div>
    <button class="linkish mat__toggle" data-action="entry.expand" data-arg="${group.gid}">${open ? '收起原文' : `展开${o.ro ? '' : '并编辑'}原文 · ${chars} 字`}</button>
  </div>`;
}

function groupCard(group, o) {
  const info = o.dedupe?.groups?.[group.gid] || {};
  const match = info.material_match;
  const isDict = group.genre === 'dictation';
  const entries = isDict ? group.dictation : group.items;
  const opts = { ...o, dedupe: info, qtypes: o.taxonomy?.qtypes?.[group.genre] || [] };
  return html`
  <article class="grp" data-key="${group.gid}" data-genre="${group.genre}" data-anchor="${group.gid}|"
    ${isFlash(o.flash, group.gid, '', '*') || isFlash(o.flash, group.gid, '', 'genre') ? html`data-flash` : ''}>
    <header class="grp__head">
      <span class="genre-dot"></span>${genreSelect(group, o.ro)}
      <span class="grp__count">${isDict ? `${entries.length} 道默写` : `${entries.length} 道小题`}</span>
      ${match ? html`<span class="chip chip--info" title="${match.id}">这篇已在题库（${match.items} 题），新题会挂到它下面</span>` : ''}
    </header>
    ${isDict ? '' : material(group, o)}
    <div class="grp__entries">
      ${each(entries, e => e.iid, e => (isDict ? dictationCard(group, e, opts) : itemCard(group, e, opts)))}
    </div>
    ${o.ro ? '' : html`<button class="btn btn--ghost btn--sm grp__add" data-action="entry.add" data-arg="${group.gid}">${icon('plus')}${isDict ? '添加默写' : '添加小题'}</button>`}
  </article>`;
}

/** 画布末尾「添加板块」：AI 漏掉某一篇或一组默写时手动补上。 */
const addGroup = () => html`<label class="canvas__more">${icon('plus')}
  <select class="select" data-change="entry.addGroup" aria-label="添加板块">
    <option value="" selected>添加板块…</option>
    ${each(GENRES, g => g.code, g => html`<option value="${g.code}">${g.name}</option>`)}
  </select></label>`;

export function renderCanvas(groups, o) {
  if (!groups?.length) return html`<div class="empty">草稿还是空的${o.ro ? '' : html`<div>${addGroup()}</div>`}</div>`;
  return html`<div class="canvas">${each(groups, g => g.gid, g => groupCard(g, o))}${o.ro ? '' : addGroup()}</div>`;
}

export function renderImages(images, zoom) {
  if (!images?.length) return html`<div class="empty">这份草稿没有原图（手动录入）</div>`;
  return html`<div class="shots ${zoom ? 'is-zoom' : ''}">
    ${each(images, i => i, i => html`<button class="shot" data-action="entry.zoom" title="${zoom ? '缩小' : '放大'}"><img src="/api/image?id=${i}" alt="原图" loading="lazy"></button>`)}
  </div>`;
}
