/**
 * html`` 标签模板：插值默认转义；需要原样输出的片段必须显式 raw()。
 * 产出 HtmlResult，只有 core/dom.js 能把它写进文档（check_ui R6）。
 */
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;' };

export class HtmlResult {
  constructor(text) { this.text = text; }
  toString() { return this.text; }
}

export const escape = value => String(value ?? '').replace(/[&<>"'`]/g, ch => ESC[ch]);
export const raw = text => new HtmlResult(String(text ?? ''));
export const isHtml = value => value instanceof HtmlResult;

function part(value) {
  if (value == null || value === false || value === true) return '';
  if (value instanceof HtmlResult) return value.text;
  if (Array.isArray(value)) return value.map(part).join('');
  return escape(value);
}

export function html(strings, ...values) {
  let out = strings[0];
  for (let i = 0; i < values.length; i += 1) out += part(values[i]) + strings[i + 1];
  return new HtmlResult(out);
}

/**
 * 列表渲染：each(items, it => it.id, it => html`<li data-key="${it.id}">…</li>`)。
 * key 同时写进模板的 data-key，供 dom.js 的 morph 对齐列表项；重复 key 会让 morph 对不齐，直接报错。
 */
export function each(list, keyOf, render) {
  const seen = new Set();
  return new HtmlResult(Array.from(list || [], (item, i) => {
    const key = String(keyOf(item, i));
    if (seen.has(key)) throw new Error(`each()：重复的 key「${key}」`);
    seen.add(key);
    return part(render(item, i));
  }).join(''));
}

/** 拼 class：cls('a', cond && 'b', ['c']) → "a b c" */
export const cls = (...names) => names.flat(Infinity).filter(Boolean).join(' ');
