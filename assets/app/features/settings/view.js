import { html, each } from '../../core/html.js';
import { aiView, reviewView, dataView } from './sections.js';
import { mcpView } from './mcp.js';
import { serviceView } from './service.js';

export const SECTIONS = [['appearance', '外观与显示'], ['review', '复习与打印'], ['ai', 'AI 识别'],
  ['assistant', 'AI 助手'], ['mcp', '外部 AI / MCP'], ['data', '数据与存储'], ['service', '服务与运行']];

function content(s) {
  const c = s.cfg;
  if (s.section === 'ai') return aiView(s);
  if (s.section === 'review') return html`${reviewView(s)}<section class="card set__box"><h2>A4 打印与默认留白</h2>
    <p class="set__desc">创建复习后先进入打印预览。自动适配使用浏览器按实际宽度与字体排版参考答案；− / 行数 / + 永久保存为题目默认值。打开预览不会自动修改题库。</p></section>`;
  if (s.section === 'data') return dataView(s);
  if (s.section === 'mcp') return mcpView(s);
  if (s.section === 'appearance') return html`<section class="card set__box"><h2>外观与显示</h2>
    <label class="field"><span>主题</span><select class="select" data-change="set.theme"><option value="light" ${document.documentElement.dataset.theme === 'light' ? html`selected` : ''}>浅色</option><option value="dark" ${document.documentElement.dataset.theme === 'dark' ? html`selected` : ''}>深色</option></select></label>
    <label class="field"><span>主导航</span><select class="select" data-change="set.nav"><option value="full" ${document.documentElement.dataset.nav !== 'mini' ? html`selected` : ''}>完整</option><option value="mini" ${document.documentElement.dataset.nav === 'mini' ? html`selected` : ''}>仅图标</option></select></label></section>`;
  if (s.section === 'assistant') return html`<form class="card set__box" data-submit="set.saveAssistant"><h2>全局 AI 助手</h2>
    <p class="set__desc">与录入 Agent 共用模型协议和工具循环。可查询学习与作文、操作草稿、追加评价和笔记；正式改题、改材料、创建复习先进入统一审核。</p>
    <label class="set__check"><input type="checkbox" name="assistant_enabled" ${c.assistant_enabled !== false ? html`checked` : ''}><span>启用全局助手</span></label>
    <label class="field"><span>API 地址（留空沿用 AI 识别）</span><input class="input" name="assistant_base_url" value="${c.assistant_base_url || ''}"></label>
    <label class="field"><span>模型（留空沿用 AI 识别）</span><input class="input" name="assistant_model" value="${c.assistant_model || ''}"></label>
    <label class="field"><span>独立模型 Key（留空保留）</span><input class="input" name="assistant_api_key" type="password" autocomplete="off" placeholder="${c.assistant_api_key_set ? '已保存' : '未单独设置，沿用 AI 识别'}"></label>
    <div class="set__foot">${c.assistant_api_key_set ? html`<button class="btn btn--danger" type="button" data-action="set.clearAssistantKey">清除独立密钥</button>` : ''}<button class="btn btn--primary">保存</button></div></form>`;
  return html`<section class="card set__box"><h2>服务与运行</h2>${s.status ? html`
    <dl class="set__status"><dt>版本</dt><dd>${s.status.version}</dd><dt>Web</dt><dd>${s.status.host}:${s.status.port}</dd>
      <dt>MCP SDK</dt><dd>${s.status.mcp_sdk_installed ? '已安装' : '尚未安装（Web 正常使用）'}</dd><dt>MCP 服务</dt><dd>${s.status.mcp?.running ? s.status.mcp.url : '未启动'}</dd></dl>` : '正在读取运行状态…'}
    <p class="set__desc">系统运行与学习变更分别留痕，可以在历史记录中查询。</p><a class="btn" href="#/history">打开历史记录</a></section>${serviceView(s)}`;
}

export function view(s) {
  if (!s.cfg) return html`<p class="empty">${s.error || '正在加载…'}</p>`;
  return html`<div class="set-layout"><nav class="set-nav" role="tablist" aria-label="设置分区">${each(SECTIONS, x => x[0], ([id, title]) => html`
    <button class="btn btn--ghost" role="tab" id="set-tab-${id}" aria-controls="set-content" aria-selected="${String(s.section === id)}" tabindex="${s.section === id ? 0 : -1}" data-setting-tab="${id}" data-action="set.section" data-arg="${id}">${title}</button>`)}</nav>
    <div class="set" id="set-content" role="tabpanel" aria-labelledby="set-tab-${s.section}">${s.error ? html`<p role="alert">${s.error}</p>` : ''}${content(s)}</div></div>`;
}
