/**
 * 事件委托：模板里写 data-action="页面.动作"（点击）、data-change / data-input（表单控件）、data-submit（表单），
 * 动作用 defineActions('页面', { 动作(ctx) {} }) 登记，bindEvents(document) 在根上各绑一次监听。
 * 处理函数收到 { el, arg, value, event }：arg 取 data-arg 原样字符串，value 取控件当前值。
 * 只处理带点号的名字（命名空间约定）；禁用的元素不触发；未登记的名字打印一次警告。
 */
const registry = new Map();
const bound = new WeakSet();
const warned = new Set();
const KINDS = [['click', 'action'], ['change', 'change'], ['input', 'input'], ['submit', 'submit']];

export function defineActions(namespace, handlers) {
  const names = Object.keys(handlers).map(name => `${namespace}.${name}`);
  Object.entries(handlers).forEach(([name, fn]) => registry.set(`${namespace}.${name}`, fn));
  return () => names.forEach(name => registry.delete(name));
}

export const hasAction = name => registry.has(name);

export function dispatchAction(name, ctx = {}) {
  const fn = registry.get(name);
  if (!fn) {
    if (!warned.has(name)) { warned.add(name); console.warn(`[events] 未登记的动作：${name}`); }
    return false;
  }
  fn(ctx);
  return true;
}

export function bindEvents(root = document) {
  if (bound.has(root)) return root;
  bound.add(root);
  for (const [type, attr] of KINDS) {
    root.addEventListener(type, event => {
      const el = event.target.closest?.(`[data-${attr}]`);
      if (!el) return;
      const name = el.getAttribute(`data-${attr}`);
      if (!name || !name.includes('.')) return;
      if (el.disabled || el.getAttribute('aria-disabled') === 'true') return;
      if (type === 'submit') event.preventDefault();
      dispatchAction(name, { el, arg: el.dataset.arg, value: 'value' in el ? el.value : undefined, event });
    });
  }
  return root;
}
