/** 重启当前服务，确认新实例上线后刷新；离页取消等待，超时后只检查状态。 */
import { html } from '../../core/html.js';
import { get, post } from '../../core/api.js';
import { confirmDialog, toast } from '../../ui/feedback.js';

export function serviceView(s) {
  return html`<section class="card set__box"><h2>重启程序</h2>
    <p class="set__desc">按当前设置重新启动 CLMS。正在进行的 AI 任务会中断，已保存的数据会保留；未完成任务可在重启后重试。请先保存正在编辑的内容。</p>
    <div class="set__foot set__foot--start">
      <button class="btn btn--primary" data-action="set.restart" ${s.restartBusy || s.restartPending || !s.status?.restart_supported ? html`disabled` : ''}>${s.restartBusy ? '正在重启…' : '重启程序'}</button>
      ${s.restartPending && !s.restartBusy ? html`<button class="btn" data-action="set.checkRestart">检查运行状态</button><button class="btn btn--ghost" data-action="set.reload">刷新页面</button>` : ''}
    </div>
    ${s.restartMessage ? html`<p class="set__desc" role="status" aria-live="polite">${s.restartMessage}</p>` : ''}
    ${s.status && !s.status.restart_supported ? html`<p class="set__desc">当前服务不支持页面重启，请用命令行 serve 启动程序。</p>` : ''}
  </section>`;
}

export function serviceActions({ s, draw, alive }) {
  let controller = null, timer = null, wake = null;
  try {
    if (sessionStorage.getItem('clms-restart-complete')) {
      sessionStorage.removeItem('clms-restart-complete'); toast('程序已重启');
    }
  } catch (_) { /* 私密模式 */ }

  async function waitForRestart() {
    s.restartBusy = true;
    s.restartMessage = '正在等待程序重新上线，完成后页面会自动刷新…'; draw();
    controller = new AbortController();
    const deadline = Date.now() + 45000;
    while (alive() && Date.now() < deadline) {
      const r = await get('/api/status', { signal: controller.signal, timeout: 2000 });
      if (!alive()) return;
      if (r.ok && r.data.instance_id && r.data.instance_id !== s.restartFrom && !r.data.restarting) {
        try { sessionStorage.setItem('clms-restart-complete', '1'); } catch (_) {}
        location.reload(); return;
      }
      await new Promise(resolve => { wake = resolve; timer = setTimeout(resolve, 1000); });
      timer = null; wake = null;
    }
    if (!alive()) return;
    s.restartBusy = false;
    s.restartMessage = '暂未确认程序重新上线。可以检查运行状态，或刷新页面查看。'; draw();
  }

  return {
    handlers: {
      async restart() {
        if (s.restartBusy || s.restartPending || !s.status?.restart_supported) return;
        s.restartBusy = true; draw();
        const confirmed = await confirmDialog({ title: '重启程序？',
          body: '正在进行的 AI 任务会中断，已保存的数据会保留。请确认正在编辑的内容已保存。', ok: '重启程序' });
        if (!alive()) return;
        if (!confirmed) { s.restartBusy = false; draw(); return; }
        s.restartFrom = s.status.instance_id;
        s.restartMessage = '正在发送重启请求…'; draw();
        controller = new AbortController();
        const r = await post('/api/service/restart', { instance_id: s.restartFrom }, { signal: controller.signal, timeout: 5000 });
        if (!alive()) return;
        if (!r.ok && r.status !== 0) {
          s.restartBusy = false; s.restartMessage = r.error.message; draw(); return;
        }
        // 网络断开可能发生在服务已接受请求之后；只查新实例，不能自动再次发送重启。
        s.restartPending = true;
        await waitForRestart();
      },
      checkRestart() { if (!s.restartBusy && s.restartPending) waitForRestart(); },
      reload() { location.reload(); },
    },
    resume(status) {
      if (!status.restarting || s.restartBusy) return;
      s.restartFrom = status.instance_id; s.restartPending = true; waitForRestart();
    },
    dispose() { controller?.abort(); if (timer) clearTimeout(timer); wake?.(); },
  };
}
