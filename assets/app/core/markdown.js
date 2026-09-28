/**
 * 轻量 Markdown → HtmlResult（模型的回复用）。先转义、再套结构，模型输出里的 HTML 一律当文字。
 * 支持：段落与换行、# 标题、- / * / 1. 列表（一层）、> 引用、``` 代码块、| 表格 |、**粗体**、*斜体*、`代码`、
 * [文字](http…) 链接（只放行 http / https）。流式输出里没闭合的标记先原样显示，闭合后自然变成格式。
 */
import { escape, raw } from './html.js';

function inline(text) {
  return String(text).split(/(`[^`\n]+`)/).map((piece, n) => {
    if (n % 2) return `<code>${escape(piece.slice(1, -1))}</code>`;
    return escape(piece)
      .replace(/\*\*([^*\n]+?)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*\w])\*([^*\s][^*\n]*?)\*(?!\*)/g, '$1<em>$2</em>')
      .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  }).join('');
}

const cells = line => line.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());

export function markdown(source) {
  const lines = String(source || '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let para = [];
  const flush = () => { if (para.length) out.push(`<p>${para.map(inline).join('<br>')}</p>`); para = []; };
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (/^```/.test(line)) {
      flush();
      const body = [];
      for (i += 1; i < lines.length && !/^```/.test(lines[i]); i += 1) body.push(lines[i]);
      out.push(`<pre class="md__code"><code>${escape(body.join('\n'))}</code></pre>`);
    } else if (/^\s*$/.test(line)) {
      flush();
    } else if (/^#{1,6}\s/.test(line)) {
      flush();
      out.push(`<p class="md__h">${inline(line.replace(/^#+\s*/, ''))}</p>`);
    } else if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] || '')) {
      flush();
      const head = cells(line);
      const rows = [];
      for (i += 2; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i += 1) rows.push(cells(lines[i]));
      i -= 1;
      out.push(`<div class="md__table"><table><thead><tr>${head.map(c => `<th>${inline(c)}</th>`).join('')}</tr></thead>`
        + `<tbody>${rows.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
    } else if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      flush();
      const ordered = /^\s*\d/.test(line);
      const items = [];
      const marker = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/;
      for (; i < lines.length && marker.test(lines[i]); i += 1) {
        let item = lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, '');
        while (i + 1 < lines.length && /^\s{2,}\S/.test(lines[i + 1]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i + 1])) { i += 1; item += `\n${lines[i].trim()}`; }
        items.push(`<li>${item.split('\n').map(inline).join('<br>')}</li>`);
      }
      i -= 1;
      out.push(ordered ? `<ol>${items.join('')}</ol>` : `<ul>${items.join('')}</ul>`);
    } else if (/^>\s?/.test(line)) {
      flush();
      const quote = [];
      for (; i < lines.length && /^>\s?/.test(lines[i]); i += 1) quote.push(lines[i].replace(/^>\s?/, ''));
      i -= 1;
      out.push(`<blockquote>${quote.map(inline).join('<br>')}</blockquote>`);
    } else {
      para.push(line);
    }
  }
  flush();
  return raw(out.join(''));
}
