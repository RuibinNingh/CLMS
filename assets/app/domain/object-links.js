import { html, each } from '../core/html.js';

export function objectLinks(item) {
  const links = [...(item?.links || [])];
  const sessionId = item?.result?.session_id || (item?.result?.id?.startsWith('S-') ? item.result.id : null);
  if (item?.tool === 'session.create' && sessionId) links.push({ page: 'review', field: 'session', id: sessionId, preview: true, label: '打开已创建复习' });
  for (const obj of [item, item?.result, item?.arguments, item?.payload, item?.actor]) {
    if (!obj) continue;
    for (const [key, page, field, label] of [
      ['operation_id', 'audit', 'id', '打开审核'], ['session_id', 'review', 'session', '打开复习'],
      ['item_id', 'library', 'item', '打开题目'], ['version_id', 'essays', 'version', '打开作文版本'],
      ['attempt_id', 'essays', 'attempt', '打开写作练习'], ['prompt_id', 'essays', 'prompt', '打开作文题'],
      ['draft_id', 'entry', 'draft', '打开草稿'], ['conversation_id', 'assistant', 'conversation', '打开助手会话'],
    ]) {
      if (obj[key] && !links.some(l => l.id === obj[key] && l.page === page)) links.push({ id: obj[key], page, field, label });
    }
  }
  return html`<div class="workspace__links">${each(links, l => `${l.page}-${l.id}`, l => html`
    <a class="btn btn--sm" href="#/${l.page}?${l.field}=${encodeURIComponent(l.id)}${l.preview ? '&preview=1' : ''}">${l.label}</a>`)}</div>`;
}

export const showTime = value => value ? String(value).replace('T', ' ').replace(/\..*$/, '') : '—';
export const pretty = value => JSON.stringify(value ?? {}, null, 2);
