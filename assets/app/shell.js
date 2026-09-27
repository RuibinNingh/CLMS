/**
 * 外壳（对标 OMRS shell.js）：建 bus / store / router，登记页面，切页时挂载 / 卸载，同步标题、导航高亮与工作台布局。
 * 页面契约：{ id, title, icon, workbench, mount(root, ctx) → unmount }，ctx = { bus, store, router }。
 * 页面之间不互相 import，联动走 bus（事件表见 AI/frontend.md）。
 */
import { createBus } from './core/bus.js';
import { createStore } from './core/store.js';
import { createRouter } from './core/router.js';
import { bindEvents, defineActions } from './core/events.js';
import { html, each } from './core/html.js';
import { render } from './core/dom.js';
import { icon } from './ui/icons.js';

export function startShell(pages) {
  const bus = createBus();
  const store = createStore({ summary: null });
  let unmount = null;
  const main = document.getElementById('main');

  const router = createRouter({
    win: window,
    fallback: 'dashboard',
    onEnter(page, prev) {
      if (unmount) { try { unmount(); } catch (err) { console.error(err); } unmount = null; }
      document.querySelectorAll('.panel').forEach(p => p.classList.toggle('is-active', p.id === `panel-${page.id}`));
      document.querySelectorAll('#nav a').forEach(a => {
        if (a.dataset.page === page.id) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
      });
      document.getElementById('page-title').textContent = page.title;
      document.title = `${page.title} · CLMS`;
      main.classList.toggle('is-workbench', Boolean(page.workbench));
      const root = document.getElementById(`panel-${page.id}`);
      unmount = page.mount(root, ctx) || null;
      bus.emit('page:change', { id: page.id, prev });
    },
  });
  const ctx = { bus, store, router };
  pages.forEach(p => router.register(p));

  render(document.getElementById('nav'), each(pages, p => p.id, p => html`
    <a href="#/${p.id}" data-page="${p.id}">${icon(p.icon)}<span>${p.title}</span><span class="nav__badge" data-badge="${p.id}"></span></a>`));

  const themeButton = document.getElementById('theme-toggle');
  const syncTheme = () => { themeButton.textContent = document.documentElement.dataset.theme === 'dark' ? '切换浅色' : '切换深色'; };
  syncTheme();
  defineActions('app', {
    theme() {
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem('clms-theme', next); } catch (_) { /* 隐私模式 */ }
      syncTheme();
    },
  });
  bus.on('badge', ({ id, text }) => {
    const el = document.querySelector(`[data-badge="${id}"]`);
    if (el) el.textContent = text || '';
  });
  bindEvents(document);
  return ctx;
}
