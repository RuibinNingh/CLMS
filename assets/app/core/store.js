/**
 * 状态容器：createStore(initial) → { get, set, subscribe, batch }。
 * - set(patch)：对象浅合并；传函数则 set(state => next)，返回同一对象视为没变。
 * - subscribe(fn, selector = 整个状态, equal = Object.is)：选中的值变化时才回调 fn(next, prev)，返回退订函数。
 * - batch(fn)：fn 里的多次 set 只通知一次。
 */
export function createStore(initial = {}) {
  let state = initial;
  let depth = 0;
  let dirty = false;
  const subs = new Set();

  const notify = () => {
    if (depth) { dirty = true; return; }
    for (const sub of [...subs]) sub.check(state);
  };

  return {
    get: () => state,
    set(patch) {
      const next = typeof patch === 'function' ? patch(state) : { ...state, ...patch };
      if (next === state) return;
      state = next;
      notify();
    },
    subscribe(fn, selector = s => s, equal = Object.is) {
      const sub = {
        last: selector(state),
        check(s) {
          const value = selector(s);
          if (equal(value, sub.last)) return;
          const prev = sub.last;
          sub.last = value;
          fn(value, prev);
        },
      };
      subs.add(sub);
      return () => subs.delete(sub);
    },
    batch(fn) {
      depth += 1;
      try { fn(); } finally {
        depth -= 1;
        if (!depth && dirty) { dirty = false; notify(); }
      }
    },
  };
}
