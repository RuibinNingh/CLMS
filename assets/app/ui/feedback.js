/** 吐司与确认框。toast(text, { tone }) 三秒后消失；confirmDialog({ title, body, ok, danger }) → Promise<boolean>。 */
import { html } from '../core/html.js';
import { toElement } from '../core/dom.js';

let host = null;

export function toast(text, { tone = '', ms = 3200 } = {}) {
  if (!host) { host = document.createElement('div'); host.className = 'toasts'; host.setAttribute('role', 'status'); document.body.append(host); }
  const el = toElement(html`<div class="toast ${tone ? `toast--${tone}` : ''}">${text}</div>`);
  host.append(el);
  setTimeout(() => el.remove(), ms);
}

export function confirmDialog({ title, body = '', ok = '确定', danger = false }) {
  return new Promise(resolve => {
    const dlg = toElement(html`<dialog class="dlg"><form method="dialog"><div class="dlg__body"><h3>${title}</h3>${body ? html`<p>${body}</p>` : ''}</div>
      <div class="dlg__foot"><button class="btn" value="no">取消</button><button class="btn ${danger ? 'btn--danger' : 'btn--primary'}" value="yes">${ok}</button></div></form></dialog>`);
    document.body.append(dlg);
    dlg.addEventListener('close', () => { resolve(dlg.returnValue === 'yes'); dlg.remove(); });
    dlg.showModal();
  });
}
