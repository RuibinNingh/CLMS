/**
 * 安排复习的数据与动作：推荐（POST /api/sessions/plan，带自选 pinned、移除 exclude、题型）与挑题（GET /api/items 分页）。
 * 任何一个条件变了都重新推荐；连续变化用 seq 丢弃过期的回复。
 */
import { get, post } from '../../core/api.js';
import { toast } from '../../ui/feedback.js';

const PAGE = 20;

export function initialPlanState(genres) {
  return {
    minutes: 40, genres, fill: true, qtype: '', plan: null, horizon: '', planning: false, pinned: [], excluded: [],
    pick: { genre: '', status: '', added: '', last: '', grade: '', q: '', sort: 'priority', items: [], total: 0, facets: {}, loading: true },
  };
}

export function planActions(s, { render, afterCreate }) {
  let planSeq = 0; let pickSeq = 0; let searchTimer = 0;

  async function makePlan() {
    const mine = ++planSeq;
    s.planning = true; render();
    const body = { minutes: s.minutes, genres: [...s.genres], fill: s.fill, qtypes: s.qtype ? [s.qtype] : [],
      pinned: s.pinned, exclude: s.excluded };
    const r = await post('/api/sessions/plan', body);
    if (mine !== planSeq) return;
    s.planning = false;
    if (!r.ok) { render(); toast(r.error.message, { tone: 'bad' }); return; }
    s.plan = r.data; s.horizon = r.data.horizon; render();
  }

  async function loadPick(more = false) {
    const mine = ++pickSeq;
    const k = s.pick;
    k.loading = true; render();
    const q = new URLSearchParams({ genre: k.genre, status: k.status, added: k.added, last: k.last, grade: k.grade,
      q: k.q, sort: k.sort, offset: more ? k.items.length : 0, limit: PAGE });
    const r = await get(`/api/items?${q}`);
    if (mine !== pickSeq) return;
    k.loading = false;
    if (r.ok) {
      k.items = more ? [...k.items, ...r.data.items] : r.data.items;
      k.total = r.data.total; k.facets = r.data.facets;
    }
    render();
  }

  const replan = () => makePlan();

  const actions = {
    budget: ({ arg }) => { s.minutes = Number(arg); replan(); },
    genre: ({ arg }) => {
      if (s.genres.has(arg) && s.genres.size > 1) s.genres.delete(arg); else s.genres.add(arg);
      replan();
    },
    qtype: ({ el }) => { s.qtype = el.value; replan(); },
    fill: ({ el }) => { s.fill = el.checked; replan(); },
    plan: makePlan,
    exclude: ({ arg }) => { s.excluded.push(arg); replan(); },
    unexclude: () => { s.excluded = []; replan(); },
    shuffle: () => { s.excluded.push(...(s.plan?.items || []).filter(x => x.tag !== 'manual').map(x => x.id)); replan(); },
    pin: ({ arg }) => { if (!s.pinned.includes(arg)) s.pinned.push(arg); s.excluded = s.excluded.filter(x => x !== arg); replan(); },
    unpin: ({ arg }) => { s.pinned = s.pinned.filter(x => x !== arg); s.excluded.push(arg); replan(); },
    async create() {
      if (!s.plan?.items.length) return null;
      const r = await post('/api/sessions', { item_ids: s.plan.items.map(x => x.id), minutes: Math.round(s.plan.minutes) });
      if (!r.ok) { toast(r.error.message, { tone: 'bad' }); return null; }
      toast(`已安排 ${r.data.items.length} 题，可以打印了`);
      s.plan = null; s.pinned = []; s.excluded = [];
      return afterCreate(r.data.id);
    },
    pickGenre: ({ arg }) => { s.pick.genre = arg; loadPick(); },
    pickFilter: ({ el, arg }) => { s.pick[arg] = el.value; loadPick(); },
    pickSearch: ({ el }) => { clearTimeout(searchTimer); s.pick.q = el.value; searchTimer = setTimeout(() => loadPick(), 250); },
    pickMore: () => loadPick(true),
  };
  return { actions, makePlan, loadPick };
}
