/**
 * 设置：AI 模型（OpenAI 兼容）与 Agent（工具调用、子代理并发、每次最多轮数）、复习日与默认时长、
 * 数据（校验提交链、导出脱敏源码包——不依赖 Git，只收源码目录，API Key 替换掉）。密钥不回显，留空保存即保留旧密钥。
 */
import { html, each } from '../../core/html.js';
import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get, post } from '../../core/api.js';
import { toast } from '../../ui/feedback.js';
import { loadTaxonomy } from '../../domain/genres.js';
import { taxonomyActions } from './taxonomy.js';
import { view, SECTIONS } from './view.js';
import { mcpActions } from './mcp.js';
import { serviceActions } from './service.js';

export const page = {
  id: 'settings', title: '设置', icon: 'settings',
  mount(root, { bus }) {
    const s = { cfg: null, verify: null, taxonomy: null, taxEdit: null, section: 'appearance', keys: [], scopes: null, newKey: '', keyBusy: false, mcpError: '', status: null, error: '' };
    try { const last = localStorage.getItem('clms-settings-section'); if (SECTIONS.some(x => x[0] === last)) s.section = last; } catch (_) { /* 私密模式 */ }
    let alive = true;
    const render = () => alive && morph(root, view(s));
    const save = async (patch, message) => {
      const res = await post('/api/config', patch);
      if (!alive) return;
      if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return; }
      s.cfg = res.data; toast(message); render();
      root.querySelector('input[name="ai_api_key"]')?.form?.reset?.();
    };
    const mcp = mcpActions({ s, draw: render, get, post, alive: () => alive, toast });
    const service = serviceActions({ s, draw: render, alive: () => alive });
    const undefine = defineActions('set', {
      ...mcp.handlers,
      ...service.handlers,
      section({ arg }) { s.newKey = ''; s.section = arg; try { localStorage.setItem('clms-settings-section', arg); } catch (_) {} render(); if (arg === 'mcp') mcp.load(); },
      theme({ value }) { document.documentElement.dataset.theme = value; try { localStorage.setItem('clms-theme', value); } catch (_) {} bus.emit('theme:changed'); },
      nav({ value }) { document.documentElement.dataset.nav = value; try { localStorage.setItem('clms-nav', value); } catch (_) {} bus.emit('nav:changed'); },
      saveAssistant({ el }) { const f = new FormData(el); save({ assistant_enabled: f.get('assistant_enabled') === 'on', assistant_model: f.get('assistant_model').trim(), assistant_base_url: f.get('assistant_base_url').trim(), assistant_api_key: f.get('assistant_api_key').trim() }, '助手设置已保存'); },
      clearAssistantKey: () => save({ clear_assistant_api_key: true }, '助手独立密钥已清除'),
      ...taxonomyActions({ s, render, post, toast }),
      saveAi({ el }) {
        const f = new FormData(el);
        save({ ai_base_url: f.get('ai_base_url').trim(), ai_api_key: f.get('ai_api_key').trim(), ai_model: f.get('ai_model').trim(),
          ai_timeout: Number(f.get('ai_timeout')) || 150, ai_max_tokens: Number(f.get('ai_max_tokens')) || 16000,
          ai_concurrency: Number(f.get('ai_concurrency')) || 2, ai_agent: f.get('ai_agent') === 'on',
          ai_context_window: Number(f.get('ai_context_window')) || 128000,
          agent_subagents: Number(f.get('agent_subagents')) || 3, agent_max_turns: Number(f.get('agent_max_turns')) || 30 }, 'AI 设置已保存');
      },
      saveReview({ el }) {
        const f = new FormData(el);
        const days = f.getAll('day').map(Number);
        if (!days.length) { toast('至少选一天', { tone: 'bad' }); return; }
        save({ review_weekdays: days, session_minutes: Number(f.get('session_minutes')) || 40 }, '复习安排已保存');
      },
      clearKey: () => save({ clear_api_key: true }, '密钥已清除'),
      async verify() { const r = await get('/api/ledger/verify'); if (r.ok) { s.verify = r.data; render(); } },
    });
    get('/api/config').then(r => { if (!alive) return; if (r.ok) { s.cfg = r.data; render(); } });
    loadTaxonomy().then(t => { if (!alive) return; s.taxonomy = t; render(); });
    get('/api/status').then(r => { if (alive && r.ok) { s.status = r.data; render(); service.resume(r.data); } });
    if (s.section === 'mcp') mcp.load();
    function keydown(event) {
      const tab = event.target.closest('[data-setting-tab]');
      if (!tab || !['ArrowDown','ArrowUp','ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      const current = SECTIONS.findIndex(x => x[0] === tab.dataset.settingTab);
      const index = event.key === 'Home' ? 0 : event.key === 'End' ? SECTIONS.length - 1 : (current + (['ArrowUp','ArrowLeft'].includes(event.key) ? -1 : 1) + SECTIONS.length) % SECTIONS.length;
      const id = SECTIONS[index][0]; root.querySelector(`[data-setting-tab="${id}"]`).click(); root.querySelector(`[data-setting-tab="${id}"]`).focus();
    }
    root.addEventListener('keydown', keydown);
    render();
    return () => { root.querySelectorAll('[data-mcp-secret]').forEach(el => { el.value = ''; el.removeAttribute('value'); }); alive = false; service.dispose(); s.newKey = ''; undefine(); root.removeEventListener('keydown', keydown); };
  },
};
