import { html, each } from '../../core/html.js';

const expired = key => key.expires_at && new Date(key.expires_at).getTime() <= Date.now();

const LABELS = { 'clms:read': '学习查询', 'draft:create': '创建草稿', 'draft:update': '修改草稿',
  'session:create': '提交复习审核', 'question:propose': '提交改题审核', 'material:propose': '提交材料审核',
  'essay:read': '作文查询', 'essay:images': '作文原图', 'essay:evaluate': '追加作文评价',
  'essay:note': '追加讨论笔记', 'essay:classify': '作文自由分类' };

export function mcpView(s) {
  return html`<section class="card set__box"><h2>外部 AI / MCP</h2>
    <p class="set__desc">官方 MCP SDK 使用独立端口，默认仅监听本机。密钥独立于模型 Key；正式复习和改题先提交审核，由你在网页批准。</p>
    <p class="set__desc">启动：<code>python3 clms_engine.py serve --mcp-port 18473</code>。安装可选依赖：<code>pip install -r requirements-mcp.txt</code>。</p>
    ${s.mcpError ? html`<p role="alert">${s.mcpError}</p>` : ''}
    ${s.newKey ? html`<section class="set__key" role="region" aria-label="新密钥"><h3>明文仅显示这一次</h3>
      <input class="input" aria-label="新 MCP Key" data-mcp-secret value="${s.newKey}" readonly autocomplete="off">
      <button class="btn" data-action="set.forgetKey">我已保存，关闭</button></section>` : ''}
    <form class="workspace__form" data-submit="set.createMcpKey"><label class="field"><span>密钥名称</span><input class="input" name="name" maxlength="80" placeholder="例如：我的外部助手"></label>
      <label class="field"><span>到期时间（可留空）</span><input class="input" type="datetime-local" name="expires_at"></label>
      <fieldset class="set__scopes"><legend>权限</legend>${each(s.scopes || Object.keys(LABELS), x => typeof x === 'string' ? x : x.scope || x.id, x => {
        const id = typeof x === 'string' ? x : x.scope || x.id;
        return html`<label class="set__check"><input type="checkbox" name="scope" value="${id}" ${(typeof x === 'object' ? x.default : ['clms:read', 'essay:read', 'draft:create'].includes(id)) ? html`checked` : ''}><span>${LABELS[id] || id}<small> ${id}</small></span></label>`;
      })}</fieldset><button class="btn btn--primary" ${s.keyBusy ? html`disabled` : ''}>创建密钥</button></form>
    <h3>已有密钥</h3>${each(s.keys || [], k => k.key_id || k.id, k => html`<div class="set__key">
      <strong>${k.name || '未命名密钥'}</strong><p class="muted">${k.prefix || k.key_prefix || k.key_id || k.id} · ${k.revoked_at || k.revoked ? '已吊销' : expired(k) ? '已到期' : '有效'}</p>
      <p class="set__desc">${(k.scopes || []).join(' · ')}</p><small class="muted">到期：${k.expires_at || '永不过期'} · 最近使用：${k.last_used_at || '尚未使用'}</small>
      ${!k.revoked_at && !k.revoked && !expired(k) ? html`<div class="set__foot set__foot--start"><button class="btn btn--sm" data-action="set.editMcp" data-arg="${k.key_id || k.id}">编辑权限</button>
        <button class="btn btn--sm btn--danger" data-action="set.revokeMcp" data-arg="${k.key_id || k.id}" ${s.keyBusy ? html`disabled` : ''}>吊销</button></div>` : ''}
      ${s.keyEdit === (k.key_id || k.id) ? html`<form data-submit="set.updateMcp" data-arg="${k.key_id || k.id}" class="workspace__form"><fieldset class="set__scopes"><legend>密钥权限</legend>${each(Object.keys(LABELS), x => x, id => html`
        <label class="set__check"><input type="checkbox" name="scope" value="${id}" ${(k.scopes || []).includes(id) ? html`checked` : ''}><span>${LABELS[id]}</span></label>`)}</fieldset>
        <button class="btn" ${s.keyBusy ? html`disabled` : ''}>保存权限</button></form>` : ''}</div>`)}
  </section>`;
}

export function mcpActions({ s, draw, get, post, alive, toast }) {
  async function load() {
    const r = await get('/api/mcp/keys');
    if (!alive()) return;
    if (r.ok) { s.keys = r.data.keys || []; s.scopes = r.data.scopes; s.mcpError = ''; }
    else s.mcpError = r.error.message;
    draw();
  }
  return { load, handlers: {
    async createMcpKey({ el }) {
      if (s.keyBusy) return;
      const f = new FormData(el), date = f.get('expires_at');
      s.keyBusy = true; draw();
      const r = await post('/api/mcp/keys', { name: f.get('name'), scopes: f.getAll('scope'), expires_at: date ? new Date(date).toISOString() : '' });
      if (!alive()) return;
      s.keyBusy = false;
      if (r.ok) { s.newKey = typeof r.data.key === 'string' ? r.data.key : r.data.key?.secret || r.data.key?.token || r.data.token || ''; await load(); }
      else { s.mcpError = r.error.message; draw(); }
    },
    forgetKey() { s.newKey = ''; draw(); },
    editMcp({ arg }) { s.keyEdit = s.keyEdit === arg ? null : arg; draw(); },
    async updateMcp({ el, arg }) {
      if (s.keyBusy) return;
      const scopes = new FormData(el).getAll('scope');
      s.keyBusy = true; draw();
      const r = await post('/api/mcp/keys/update', { key_id: arg, scopes });
      if (!alive()) return;
      s.keyBusy = false;
      if (r.ok) { s.keyEdit = null; toast('权限已保存'); load(); } else { s.mcpError = r.error.message; draw(); }
    },
    async revokeMcp({ arg }) {
      if (s.keyBusy) return;
      s.keyBusy = true; draw();
      const r = await post('/api/mcp/keys/revoke', { key_id: arg });
      if (!alive()) return;
      s.keyBusy = false;
      if (r.ok) { toast('密钥已吊销'); load(); } else { s.mcpError = r.error.message; draw(); }
    },
  } };
}
