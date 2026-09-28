/**
 * POST 流式：postStream(path, body, onEvent, { signal }) → Promise<{ ok, error }>，永不抛出。
 * 服务端按 SSE 格式回（`data: {json}\n\n`，`: ping` 心跳忽略）；每条 data 解析成对象交给 onEvent。
 * EventSource 只能 GET，所以带请求体的流式（复习助手）走 fetch + ReadableStream。
 * 服务端在开始流式之前就拒绝的请求（400 / 404）照常返回 { ok: false, error: { status, message } }；
 * signal 取消时返回 { ok: false, error: { code: 'aborted' } }，已经收到的事件不受影响。
 */
export async function postStream(path, body, onEvent, { signal, fetchImpl = globalThis.fetch } = {}) {
  let res;
  try {
    res = await fetchImpl(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body), signal, credentials: 'same-origin',
    });
  } catch (err) {
    return { ok: false, error: { status: 0, code: err?.name === 'AbortError' ? 'aborted' : 'network', message: err?.name === 'AbortError' ? '已停止' : '网络连接失败' } };
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    return { ok: false, error: { status: res.status, code: data?.error || `http_${res.status}`, message: data?.msg || `HTTP ${res.status}` } };
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const flush = chunk => {
    const data = chunk.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!data) return;
    try { onEvent(JSON.parse(data)); } catch (err) { console.error(err); }
  };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let at = buffer.indexOf('\n\n');
      while (at >= 0) {
        flush(buffer.slice(0, at));
        buffer = buffer.slice(at + 2);
        at = buffer.indexOf('\n\n');
      }
    }
    if (buffer.trim()) flush(buffer);
    return { ok: true, error: null };
  } catch (err) {
    const aborted = err?.name === 'AbortError';
    return { ok: false, error: { status: 0, code: aborted ? 'aborted' : 'network', message: aborted ? '已停止' : '连接中断' } };
  }
}
