/**
 * 设置：AI 模型（OpenAI 兼容）与 Agent（工具调用、子代理并发、每次最多轮数）、复习日与默认时长、
 * 数据（校验提交链、导出脱敏源码包——不依赖 Git，只收源码目录，API Key 替换掉）。密钥不回显，留空保存即保留旧密钥。
 */
import { html, each } from '../../core/html.js';
import { morph } from '../../core/dom.js';
import { defineActions } from '../../core/events.js';
import { get, post } from '../../core/api.js';
import { toast } from '../../ui/feedback.js';

const DAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

function view(s) {
  const c = s.cfg;
  if (!c) return html`<p class="empty">正在加载…</p>`;
  return html`<div class="set">
    <form class="card set__box" data-submit="set.saveAi">
      <h2>AI 模型</h2>
      <p class="set__desc">用于读图拆题和对话修改。任何兼容 OpenAI 接口、支持看图的模型都可以（如 GPT-4o、Qwen-VL、Doubao-Vision、GLM-4V）。</p>
      <label class="field"><span>API 地址</span><input class="input" name="ai_base_url" value="${c.ai_base_url}" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"></label>
      <label class="field"><span>API Key</span><input class="input" name="ai_api_key" type="password" autocomplete="off" placeholder="${c.ai_api_key_set ? '已保存，留空则不修改' : 'sk-…'}"></label>
      <label class="field"><span>模型名</span><input class="input" name="ai_model" value="${c.ai_model}" placeholder="qwen-vl-max"></label>
      <div class="set__row">
        <label class="field"><span>超时（秒）</span><input class="input" name="ai_timeout" type="number" min="20" max="600" value="${c.ai_timeout}"></label>
        <label class="field"><span>输出上限（token）</span><input class="input" name="ai_max_tokens" type="number" min="1000" max="64000" step="1000" value="${c.ai_max_tokens}"><small>原文较长或模型会思考时，可适当调高</small></label>
        <label class="field"><span>上下文窗口（token）</span><input class="input" name="ai_context_window" type="number" min="4000" max="2000000" step="1000" value="${c.ai_context_window}"><small>输入框旁的圆环按它显示上下文占用</small></label>
        <label class="field"><span>同时识别几张</span><input class="input" name="ai_concurrency" type="number" min="1" max="6" value="${c.ai_concurrency}"><small>模型限流时调小；新任务立即按新值排队</small></label>
      </div>
      <label class="set__check"><input type="checkbox" name="ai_agent" ${c.ai_agent ? html`checked` : ''}>
        <span><b>Agent 模式</b>：录入对话直连工具调用的 Agent，逐题读写草稿，可以查改题库、增删改查复习记录、拍照批改；大试卷自动委派子代理按大题并行录入。模型需要支持工具调用（function calling）；不支持时关掉，回到一次性识图。</span></label>
      <div class="set__row">
        <label class="field"><span>子代理同时跑几个</span><input class="input" name="agent_subagents" type="number" min="1" max="6" value="${c.agent_subagents}"><small>大试卷按大题分派，限流时调小</small></label>
        <label class="field"><span>每次最多几轮</span><input class="input" name="agent_max_turns" type="number" min="4" max="80" value="${c.agent_max_turns}"><small>一轮 = 一次模型请求 + 它要的工具</small></label>
      </div>
      <div class="set__foot">
        ${c.ai_api_key_set ? html`<button type="button" class="btn btn--ghost btn--danger" data-action="set.clearKey">清除密钥</button>` : ''}
        <button class="btn btn--primary">保存</button>
      </div>
    </form>
    <form class="card set__box" data-submit="set.saveReview">
      <h2>复习安排</h2>
      <p class="set__desc">选出每周固定复习的日子（建议两到三天）。到期日会对齐到这些日子，不会出现「周三到期、周五才做」的假逾期。</p>
      <div class="set__days" role="group" aria-label="复习日">${each(DAYS, (_, i) => i, (d, i) => html`
        <label class="set__day"><input type="checkbox" name="day" value="${i}" ${c.review_weekdays.includes(i) ? html`checked` : ''}><span>${d}</span></label>`)}</div>
      <label class="field set__mins"><span>每次复习默认时长（分钟）</span><input class="input" name="session_minutes" type="number" min="10" max="180" value="${c.session_minutes}"></label>
      <div class="set__foot"><button class="btn btn--primary">保存</button></div>
    </form>
    <section class="card set__box">
      <h2>数据</h2>
      <p class="set__desc">所有录入、评分与修改都写进 <code>语文/.clms/ledger.db</code> 的提交链，只追加、不改写；草稿和原图在同一目录下。</p>
      <div class="set__foot set__foot--start"><button class="btn" data-action="set.verify">校验提交链</button>
        ${s.verify ? html`<span class="chip ${s.verify.ok ? 'chip--ok' : 'chip--bad'}">${s.verify.ok ? `完整 · ${s.verify.count} 条提交` : s.verify.error}</span>` : ''}</div>
    </section>
    <section class="card set__box">
      <h2>导出脱敏源代码</h2>
      <p class="set__desc">把当前程序的源代码打成 zip，发给 AI 助手或别人看代码用。不依赖 Git：直接收集 <code>AI/</code>、<code>assets/</code>、<code>clms/</code>、<code>deploy/</code>、<code>tests/</code> 和根目录的项目文件，包括没提交的改动；不含你的数据（提交链、草稿、原图、<code>config.json</code>）、缓存和日志；源码里出现的 API Key 会替换成「已脱敏」。包里附一份文件清单。</p>
      <div class="set__foot set__foot--start"><a class="btn" href="/api/source/export" download data-testid="source-export">导出 zip</a>
        <span class="muted">也可以用命令行：<code>python3 clms_engine.py export-source</code></span></div>
    </section>
  </div>`;
}

export const page = {
  id: 'settings', title: '设置', icon: 'settings',
  mount(root) {
    const s = { cfg: null, verify: null };
    let alive = true;
    const render = () => alive && morph(root, view(s));
    const save = async (patch, message) => {
      const res = await post('/api/config', patch);
      if (!res.ok) { toast(res.error.message, { tone: 'bad' }); return; }
      s.cfg = res.data; toast(message); render();
      root.querySelector('input[name="ai_api_key"]')?.form?.reset?.();
    };
    const undefine = defineActions('set', {
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
    get('/api/config').then(r => { if (r.ok) { s.cfg = r.data; render(); } });
    render();
    return () => { alive = false; undefine(); };
  },
};
