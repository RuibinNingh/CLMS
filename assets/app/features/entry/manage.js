/**
 * 录入页的「管理」动作：录入记录（分组、搜索、加载更多、重命名、回收站、恢复、彻底删除、抽屉开关）、
 * 准备阶段（页序、旋转、删页、加页、每页说明、补充说明、开始），以及时间线块的展开 / 收起。
 * 由 index.js 注入状态与工具函数，合并进 defineActions('entry', …)。
 */
export function manageActions(c) {
  const { s, render, refreshList, open, fresh, post, toast, confirmDialog, readImages, applyDraft, poll } = c;
  let searchTimer = 0;

  async function savePages(pages, extra = {}) {
    s.draft.pages = pages;
    render();
    const res = await post('/api/draft/pages', { id: s.draft.id, pages, ...extra }, { timeout: 120000 });
    if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return; }
    applyDraft(res.data);
    render();
  }
  const pages = () => (s.draft?.pages || []).map(p => ({ ...p }));

  return {
    view: ({ arg }) => { s.view = arg; s.limit = 60; refreshList().then(render); },
    search({ el }) { s.q = el.value; clearTimeout(searchTimer); searchTimer = setTimeout(() => refreshList().then(render), 250); },
    more: () => { s.limit += 60; refreshList().then(render); },
    renaming: ({ arg }) => { s.renaming = arg; render(); c.root.querySelector('.hrow__rename')?.select(); },
    async rename({ el, arg }) {
      s.renaming = null;
      const res = await post('/api/draft/rename', { id: arg, name: el.value });
      if (!res.ok) toast(res.error.message, { tone: 'bad' });
      else if (s.draft?.id === arg) applyDraft(res.data);
      await refreshList(); render();
    },
    async trash({ arg }) {
      const d = s.drafts.find(x => x.id === arg) || s.draft;
      const ok = await confirmDialog({ title: '丢到回收站？', ok: '丢弃', danger: true,
        body: d?.status === 'committed' ? '只是把这条录入记录收起来，题库里已经入库的题不受影响。可以在「回收站」恢复。' : '可以在「回收站」恢复；草稿和对话都会保留。' });
      if (!ok) return;
      const res = await post('/api/draft/discard', { id: arg });
      if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return; }
      await refreshList();
      if (s.activeId === arg) await fresh(); else render();
    },
    async undiscard({ arg }) {
      const res = await post('/api/draft/undiscard', { id: arg });
      if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return; }
      toast('已恢复');
      await refreshList(); render();
    },
    async purge({ arg }) {
      const ok = await confirmDialog({ title: '彻底删除？', body: '草稿和对话记录会被删掉，不能恢复。已入库的题不受影响。', ok: '彻底删除', danger: true });
      if (!ok) return;
      const res = await post('/api/draft/delete', { id: arg });
      if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return; }
      if (s.activeId === arg) { s.activeId = null; s.draft = null; }
      await refreshList(); render();
    },
    toggle({ arg, el }) {
      const now = el.getAttribute('aria-expanded') === 'true';
      s.open.set(arg, !now);
      render();
    },
    pageMove({ arg }) {
      const [i, step] = String(arg).split(':').map(Number);
      const list = pages();
      const j = i + step;
      if (j < 0 || j >= list.length) return;
      [list[i], list[j]] = [list[j], list[i]];
      savePages(list);
    },
    movePage(from, to) {
      const list = pages();
      if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return;
      const [item] = list.splice(from, 1);
      list.splice(to, 0, item);
      savePages(list);
    },
    pageRotate: ({ arg }) => { const list = pages(); const p = list[Number(arg)]; p.rotate = ((p.rotate || 0) + 90) % 360; savePages(list); },
    pageRemove: ({ arg }) => { const list = pages(); list.splice(Number(arg), 1); savePages(list); },
    pageNote: ({ el, arg }) => { const list = pages(); list[Number(arg)].note = el.value.trim(); savePages(list); },
    async pageAdd({ el }) { const add = await readImages(el.files); el.value = ''; if (add.length) savePages(pages(), { add }); },
    stageHint({ el }) {
      if (s.starting || s.draft?.status !== 'staged' || el.value === (s.draft.hint || '')) return;
      const draft = s.draft;
      s.hintSave = post('/api/draft/pages', { id: draft.id, hint: el.value }).then(res => { if (res.ok) draft.hint = res.data.hint; });
    },
    async start({ arg }) {
      if (s.starting) return;
      s.starting = true; render();
      await s.hintSave;                                  // 失焦时的保存还在路上：等它落地，免得和「开始」赛跑
      const hint = s.heroText.trim();
      if (hint !== (s.draft.hint || '')) await post('/api/draft/pages', { id: s.draft.id, hint });
      const res = await post('/api/draft/start', { id: s.draft.id, split: arg === 'split' });
      s.starting = false;
      if (!res.ok) { toast(res.error.message, { tone: 'bad', ms: 6000 }); render(); return; }
      if (res.data.ids.length > 1) toast(`已拆成 ${res.data.ids.length} 份，分别识别`);
      s.heroText = '';
      await open(res.data.ids[0], { fromHero: true });
      poll();
    },
  };
}
