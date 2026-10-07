import { html } from '../../core/html.js';

export const time = value => (value || '').replace('T', ' ').slice(0, 16);
export const link = (kind, id) => `#/essays?${kind}=${encodeURIComponent(id)}`;
export const disabled = value => value ? html`disabled` : '';
export const sourceLabel = value => ({ web: '网页', mcp: '外部 AI', assistant: '全局助手', ocr: 'OCR' })[value] || value;
