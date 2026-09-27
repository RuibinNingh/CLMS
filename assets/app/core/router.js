/**
 * hash 路由：地址形如 #/questions。createRouter({ win, fallback, onEnter }) → { register, go, start, resolve, current, page, pages }。
 * - go(id)：同步切页，并用 pushState 写一条历史；
 *   replace:true 时改写当前历史。未登记的 id 落到 fallback。
 * - start()：监听前进 / 后退（popstate + hashchange），按当前地址进入页面；地址无效时改写成 fallback。
 * - 地址变成不是路由的 hash（如 href="#" 的链接）时不切页，并把地址改回当前页，刷新仍停在原页。
 * onEnter(page, prevId) 只在页面真正变化时调用。
 */
export function parseHash(hash) {
  const m = /^#\/([\w-]+)\/?(?:\?(.*))?$/.exec(hash || '');
  return m ? { id: m[1], query: m[2] || '' } : null;
}

export function createRouter({ win = globalThis.window, fallback = 'dashboard', onEnter } = {}) {
  const pages = new Map();
  let current = null;
  let started = false;

  const target = id => (pages.has(id) ? id : fallback);
  const setHash = (id, replace) => {
    const hash = `#/${id}`;
    if (win.location.hash === hash) return;
    win.history[replace ? 'replaceState' : 'pushState'](null, '', hash);
  };
  const activate = id => {
    if (id === current) return;
    const prev = current;
    current = id;
    onEnter?.(pages.get(id), prev);
  };

  const api = {
    register(page) { pages.set(page.id, page); return api; },
    resolve(hash) { const r = parseHash(hash); return r && pages.has(r.id) ? r.id : fallback; },
    go(id, { replace = false } = {}) {
      const to = target(id);
      setHash(to, replace);
      activate(to);
      return to;
    },
    start() {
      if (!started) {
        started = true;
        const onNavigate = () => {
          const r = parseHash(win.location.hash);
          if (!r) { if (current) win.history.replaceState(null, '', `#/${current}`); return; }
          if (!pages.has(r.id)) { api.go(fallback, { replace: true }); return; }
          activate(r.id);
        };
        win.addEventListener('popstate', onNavigate);
        win.addEventListener('hashchange', onNavigate);
      }
      return api.go(api.resolve(win.location.hash), { replace: true });
    },
    current: () => current,
    page: id => pages.get(id ?? current),
    pages: () => [...pages.values()],
  };
  return api;
}
