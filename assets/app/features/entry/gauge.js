/**
 * 输入框旁的圆环：上下文占用（主代理最近一次请求的输入 + 输出 ÷ 设置里的上下文窗口）。
 * 悬浮或键盘聚焦时弹出明细：速度（执行中是前端按逐字事件算的实时值）、首字延迟、轮数、工具次数、累计 token。
 * 服务没返回用量时按字数估算，并注明。approxTokens 与后端 ai_assist.approx_tokens 同一口径。
 */
import { html } from '../../core/html.js';

const R = 8;
const C = 2 * Math.PI * R;
const k = n => (n >= 10000 ? `${(n / 1000).toFixed(n >= 100000 ? 0 : 1)}k` : String(n || 0));

export function approxTokens(text) {
  let wide = 0;
  for (const ch of String(text || '')) if (ch.codePointAt(0) > 0x2E7F) wide += 1;
  return wide + Math.ceil((String(text || '').length - wide) / 4);
}

/** 实时速度：最近 3 秒内逐字事件的 token 数。 */
export function createRate() {
  const samples = [];
  return {
    add(text) { samples.push([performance.now(), approxTokens(text)]); },
    tps() {
      const now = performance.now();
      while (samples.length && now - samples[0][0] > 3000) samples.shift();
      if (samples.length < 2) return 0;
      const span = Math.max(1000, now - samples[0][0]);
      return Math.round(samples.reduce((n, x) => n + x[1], 0) / (span / 1000));
    },
  };
}

const row = (label, value) => html`<span class="gauge__row"><b>${label}</b><span>${value}</span></span>`;

export function renderGauge(draft, liveTps) {
  const st = draft.stats || {};
  const size = st.window || 128000;
  const used = st.context || 0;
  const pct = Math.min(1, used / size);
  const level = pct >= 0.9 ? 'full' : pct >= 0.7 ? 'warn' : 'ok';
  const busy = ['queued', 'extracting', 'thinking'].includes(draft.status);
  const tps = busy && liveTps ? liveTps : st.tps;
  const percent = used ? `${pct < 0.01 ? '<1' : Math.round(pct * 100)}%` : '0%';
  return html`<span class="gauge" data-level="${level}" data-busy="${String(busy)}" tabindex="0" aria-label="上下文已用 ${percent}，悬浮查看用量">
    <svg class="gauge__ring" viewBox="0 0 20 20" aria-hidden="true">
      <circle class="gauge__track" cx="10" cy="10" r="${R}"></circle>
      <circle class="gauge__fill" cx="10" cy="10" r="${R}" stroke-dasharray="${(pct * C).toFixed(2)} ${C.toFixed(2)}" transform="rotate(-90 10 10)"></circle>
    </svg>
    <span class="gauge__pop" role="tooltip">
      <span class="gauge__head"><b>${percent}</b><small>上下文 ${k(used)} / ${k(size)} token</small></span>
      ${row('速度', tps ? `${tps} tok/s${busy && liveTps ? ' · 实时' : ''}` : '—')}
      ${row('首字延迟', st.ttft ? `${st.ttft} 秒` : '—')}
      ${row('轮数', `主代理 ${st.turns || 0} · 子代理 ${st.sub_turns || 0}`)}
      ${row('工具调用', `${st.tool_calls || 0} 次`)}
      ${row('累计', `输入 ${k(st.input_total)} · 输出 ${k(st.output_total)}`)}
      ${st.estimated ? html`<small class="gauge__note">模型服务没返回用量，按字数估算</small>` : ''}
    </span>
  </span>`;
}
