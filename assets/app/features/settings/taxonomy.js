/** 用户题型体系：配置操作经专用 API；迁移旧题时由后端追加 item.update。 */
import { html, each } from '../../core/html.js';
import { GENRES, setTaxonomy } from '../../domain/genres.js';

const READING = GENRES.filter(g => g.code !== 'dictation');
const key = (genre, name) => `${genre}|${name}`;

function editForm(s) {
  const e = s.taxEdit;
  if (!e) return '';
  const names = s.taxonomy?.qtypes?.[e.genre] || [];
  const count = s.taxonomy?.usage?.[e.genre]?.[e.name] || 0;
  return html`<form class="set__taxedit" data-submit="set.taxSave" data-key="${key(e.genre, e.name || '')}">
    <b>${e.mode === 'add' ? '新增题型' : e.mode === 'rename' ? `重命名「${e.name}」` : `删除「${e.name}」`}</b>
    ${e.mode === 'delete' ? html`<p class="muted">${count ? `还有 ${count} 道题使用它。请选择迁移目标，原题及复习记录会保留。` : '没有题使用它，可以直接删除。'}</p>
      ${count ? html`<label class="field"><span>迁移到</span><select class="select" name="replace_with">
        <option value="">未分类</option>${each(names.filter(n => n !== e.name), n => n, n => html`<option value="${n}">${n}</option>`)}
      </select></label>` : ''}`
      : html`<label class="field"><span>题型名称</span><input class="input" name="name" value="${e.mode === 'rename' ? e.name : ''}" required maxlength="80" autocomplete="off"></label>`}
    <div class="set__taxedit-foot"><button type="button" class="btn btn--sm" data-action="set.taxCancel">取消</button>
      <button class="btn btn--sm ${e.mode === 'delete' ? 'btn--danger' : 'btn--primary'}">${e.mode === 'delete' ? '确认删除并迁移' : '保存'}</button></div>
  </form>`;
}

export function taxonomyView(s) {
  if (!s.taxonomy) return html`<section class="card set__box"><h2>题型体系</h2><p class="muted">正在加载…</p></section>`;
  return html`<section class="card set__box" data-testid="taxonomy-settings">
    <h2>题型体系</h2><p class="set__desc">每个板块只使用你建立的题型。AI 拿不准时会留为「未分类」，入库后仍可整理。默写类型保持固定。</p>
    ${each(READING, g => g.code, g => {
      const names = s.taxonomy.qtypes[g.code] || [];
      return html`<div class="set__taxgroup" data-key="${g.code}">
        <header><h3>${g.name}</h3><span class="muted">${names.length} 个题型 · ${s.taxonomy.uncategorized?.[g.code] || 0} 道未分类</span></header>
        ${names.length ? html`<ol class="set__taxlist">${each(names, n => n, (name, i) => html`<li data-key="${name}">
          <span class="set__taxmove"><button class="btn btn--ghost btn--icon" data-action="set.taxMove" data-genre="${g.code}" data-name="${name}" data-dir="-1" aria-label="上移${name}" ${i ? '' : html`disabled`}>↑</button>
            <button class="btn btn--ghost btn--icon" data-action="set.taxMove" data-genre="${g.code}" data-name="${name}" data-dir="1" aria-label="下移${name}" ${i < names.length - 1 ? '' : html`disabled`}>↓</button></span>
          <span class="set__taxname">${name}<small>${s.taxonomy.usage?.[g.code]?.[name] || 0} 题</small></span>
          <select class="select" data-change="set.taxKind" data-genre="${g.code}" data-name="${name}" aria-label="${name}的记忆类型">
            <option value="skill" ${s.taxonomy.qtype_kinds?.[g.code]?.[name] === 'recall' ? '' : html`selected`}>理解型</option>
            <option value="recall" ${s.taxonomy.qtype_kinds?.[g.code]?.[name] === 'recall' ? html`selected` : ''}>记忆型</option></select>
          <button class="linkish" data-action="set.taxEdit" data-mode="rename" data-genre="${g.code}" data-name="${name}">重命名</button>
          <button class="linkish" data-action="set.taxEdit" data-mode="delete" data-genre="${g.code}" data-name="${name}">删除</button>
        </li>`)}</ol>` : html`<p class="muted">还没有题型。AI 录入这个板块时会先留为未分类。</p>`}
        <button class="btn btn--sm" data-action="set.taxEdit" data-mode="add" data-genre="${g.code}">+ 新增题型</button>
        ${s.taxEdit?.genre === g.code ? editForm(s) : ''}
      </div>`;
    })}
  </section>`;
}

export function taxonomyActions({ s, render, post, toast }) {
  const call = async (path, body, message) => {
    const res = await post(`/api/taxonomy/${path}`, body);
    if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return false; }
    s.taxonomy = res.data; setTaxonomy(res.data); s.taxEdit = null; render(); toast(message);
    return true;
  };
  return {
    taxEdit({ el }) { s.taxEdit = { mode: el.dataset.mode, genre: el.dataset.genre, name: el.dataset.name || '' }; render(); },
    taxCancel() { s.taxEdit = null; render(); },
    taxSave({ el }) {
      const e = s.taxEdit;
      if (!e) return;
      const f = new FormData(el);
      if (e.mode === 'add') return call('add', { genre: e.genre, name: String(f.get('name')).trim() }, '题型已新增');
      if (e.mode === 'rename') return call('rename', { genre: e.genre, old_name: e.name, new_name: String(f.get('name')).trim() }, '题型和已有题已重命名');
      return call('delete', { genre: e.genre, name: e.name, ...(s.taxonomy.usage?.[e.genre]?.[e.name] ? { replace_with: String(f.get('replace_with')) } : {}) }, '题型已删除');
    },
    taxMove({ el }) {
      const genre = el.dataset.genre;
      const names = [...s.taxonomy.qtypes[genre]];
      const i = names.indexOf(el.dataset.name), j = i + Number(el.dataset.dir);
      if (i < 0 || j < 0 || j >= names.length) return;
      [names[i], names[j]] = [names[j], names[i]];
      return call('reorder', { genre, names }, '顺序已调整');
    },
    taxKind({ el }) { return call('kind', { genre: el.dataset.genre, name: el.dataset.name, kind: el.value }, '记忆类型已保存'); },
  };
}
