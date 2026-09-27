/**
 * 轻量事件总线：createBus() → { on, once, off, emit }。页面之间的联动一律走这里，不直接调用别的页面的函数。
 * 约定的事件：'data'（domain/data.js 每次加载完发出，载荷为统计快照）、'page:change'（{id, prev}）。
 * 某个监听抛错只记日志，不影响其余监听。
 */
export function createBus() {
  const map = new Map();
  const off = (type, fn) => { map.get(type)?.delete(fn); };
  const on = (type, fn) => {
    if (!map.has(type)) map.set(type, new Set());
    map.get(type).add(fn);
    return () => off(type, fn);
  };
  const once = (type, fn) => {
    const stop = on(type, payload => { stop(); fn(payload); });
    return stop;
  };
  const emit = (type, payload) => {
    for (const fn of [...(map.get(type) || [])]) {
      try { fn(payload); } catch (error) { console.error(`[bus] ${type} 的监听出错`, error); }
    }
  };
  return { on, once, off, emit };
}
