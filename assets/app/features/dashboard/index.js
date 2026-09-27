/**
 * 概览：下次复习（两周日历条上标出复习日，一周两三次的节奏一眼可见）、到期量与估时、
 * 四个板块的掌握度、题型薄弱榜、未完成的复习与最近动态。数据来自 /api/summary 与 /api/activity。
 */
import { html, each } from '../../core/html.js';
import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get } from '../../core/api.js';
import { formatDay, parseDay, relativeDay, formatTime } from '../../core/format.js';
import { icon } from '../../ui/icons.js';
import { GENRES, genreShort, masteryTone } from '../../domain/genres.js';

const WEEK = ['一', '二', '三', '四', '五', '六', '日'];
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

function strip(sum) {
  const today = parseDay(sum.today);
  const monday = new Date(today); monday.setDate(today.getDate() - ((today.getDay() + 6) % 7));
  const days = Array.from({ length: 14 }, (_, i) => { const d = new Date(monday); d.setDate(monday.getDate() + i); return d; });
  return html`<ol class="days" aria-label="两周复习日">${each(days, iso, d => {
    const key = iso(d);
    const review = sum.weekdays.includes((d.getDay() + 6) % 7);
    return html`<li class="day ${review ? 'is-review' : ''} ${key === sum.today ? 'is-today' : ''} ${key === sum.next_review ? 'is-next' : ''} ${key < sum.today ? 'is-past' : ''}">
      <small>${WEEK[(d.getDay() + 6) % 7]}</small><span>${d.getDate()}</span></li>`;
  })}</ol>`;
}

function load(sum) {
  if (sum.due) return html`到期 <b>${sum.due}</b> 题，约 <b>${sum.due_minutes}</b> 分钟`;
  if (sum.upcoming) return html`这天没有到期的题；下一批在 ${formatDay(sum.upcoming.date, { weekday: true })}，<b>${sum.upcoming.count}</b> 题。刚录入的错题至少隔两天再复习`;
  return '题库里还没有要复习的题';
}

function hero(sum) {
  const when = sum.is_review_day ? '今天是复习日' : `下次复习 · ${formatDay(sum.next_review, { weekday: true })}`;
  return html`<section class="hero card">
    <div class="hero__text">
      <p class="hero__when">${when}${sum.is_review_day ? '' : html`<span>${relativeDay(sum.next_review, sum.today)}</span>`}</p>
      <p class="hero__load">${load(sum)}</p>
      <div class="hero__actions">
        <a class="btn btn--primary" href="#/review" data-action="dash.plan">${icon('review')}排这次复习</a>
        <a class="btn" href="#/entry">${icon('entry')}录入错题</a>
      </div>
    </div>
    ${strip(sum)}
  </section>`;
}

function genreCard(g, row) {
  const r = row || { total: 0, due: 0, mastery: 0, leech: 0, mastered: 0 };
  return html`<article class="gcard card" data-genre="${g.code}" data-key="${g.code}">
    <header><span class="genre-dot"></span><h3>${g.name}</h3></header>
    <p class="gcard__num"><b>${r.total}</b> 题${r.due ? html`<span class="chip chip--info">${r.due} 题到期</span>` : ''}</p>
    <div class="meter" data-tone="${masteryTone(r.mastery)}"><i data-w="${Math.round(r.mastery * 20) * 5}"></i></div>
    <p class="gcard__foot">掌握度 ${Math.round(r.mastery * 100)}%${r.leech ? ` · 顽固 ${r.leech}` : ''}${r.mastered ? ` · 已掌握 ${r.mastered}` : ''}</p>
  </article>`;
}

function weak(sum) {
  if (!sum.qtypes.length) return html`<p class="empty">录入阅读题并复习几次后，这里会列出最薄弱的题型</p>`;
  return html`<ol class="weak">${each(sum.qtypes, q => `${q.genre}-${q.qtype}`, q => html`<li>
    <span class="weak__name">${q.qtype}<small>${genreShort(q.genre)}</small></span>
    <div class="meter" data-tone="${masteryTone(q.mastery)}"><i data-w="${Math.round(q.mastery * 20) * 5}"></i></div>
    <span class="weak__n">${q.total} 题${q.wrong ? ` · 错 ${q.wrong} 次` : ''}</span></li>`)}</ol>`;
}

function view(sum, acts) {
  if (!sum) return html`<p class="empty">正在加载…</p>`;
  const rows = Object.fromEntries(sum.genres.map(g => [g.code, g]));
  return html`<div class="dash">
    ${hero(sum)}
    ${sum.total ? '' : html`<p class="callout">题库还是空的。去「录入」上传一张做错的试卷照片，AI 会帮你拆好原文和题目。</p>`}
    <div class="gcards">${each(GENRES, g => g.code, g => genreCard(g, rows[g.code]))}</div>
    <div class="dash__cols">
      <section class="card dash__box"><h2>题型薄弱榜</h2>${weak(sum)}</section>
      <section class="card dash__box"><h2>最近动态</h2>
        ${sum.open_sessions.length ? html`<ul class="opens">${each(sum.open_sessions, x => x.id, x => html`<li>
          <a href="#/review" data-action="dash.session" data-arg="${x.id}">${x.title || x.id}</a>
          <span>${formatDay(x.planned_for)} 的复习，评了 ${x.progress.done}/${x.progress.total}</span></li>`)}</ul>` : ''}
        <ol class="acts">${each(acts, a => a.commit_id, a => html`<li><time>${formatDay(a.created_at)} ${formatTime(a.created_at)}</time><span>${a.message}</span></li>`)}</ol>
        ${acts.length ? '' : html`<p class="empty">还没有记录</p>`}
      </section>
    </div>
  </div>`;
}

export const page = {
  id: 'dashboard', title: '概览', icon: 'home',
  mount(root, { store }) {
    let sum = null; let acts = [];
    const render = () => morph(root, view(sum, acts));
    const undefine = defineActions('dash', {
      plan: () => store.set({ reviewIntent: { plan: true } }),
      session: ({ arg }) => store.set({ reviewIntent: { session: arg } }),
    });
    Promise.all([get('/api/summary'), get('/api/activity?limit=8')]).then(([a, b]) => {
      if (a.ok) sum = a.data;
      if (b.ok) acts = b.data.items;
      render();
    });
    render();
    return undefine;
  },
};
