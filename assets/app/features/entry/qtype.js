/** 草稿校对时由用户显式新增题型；AI 工具没有这个入口。 */
import { setTaxonomy } from '../../domain/genres.js';
import { parsePath, setField } from './edit.js';

export function qtypeActions({ s, post, toast, render, edit, focus }) {
  return {
    begin(el) {
      if (el.value !== '__add__' || parsePath(el.dataset.path).field !== 'qtype') return false;
      const { gid } = parsePath(el.dataset.path);
      s.addQtype = { path: el.dataset.path, genre: s.working?.find(g => g.gid === gid)?.genre };
      focus('.qtype__add input'); render(); return true;
    },
    actions: {
      qtypeCancel() { s.addQtype = null; render(); },
      async qtypeSave({ el }) {
        const add = s.addQtype;
        if (!add) return;
        const name = String(new FormData(el).get('name') || '').trim();
        const res = await post('/api/taxonomy/add', { genre: add.genre, name });
        if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return; }
        s.taxonomy = res.data; setTaxonomy(res.data); s.addQtype = null;
        edit(setField(s.working, add.path, name), { now: true });
        toast('题型已新增并选中');
      },
    },
  };
}
