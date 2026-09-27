/**
 * fetch 封装：request(path, options) → Promise<{ ok, status, data, error }>，永不抛出，调用方按 ok 分支。
 * options：method、body（对象按 JSON 发；字符串 / FormData / Blob 原样）、headers、signal、timeout（毫秒，默认 30000）、
 * redirectOn401（CLMS 只在本机运行，默认 false）、fetchImpl（测试替身）。
 * error = { status, code, message }：服务端 JSON 的 msg / error 优先；网络失败 code 为 'network'，超时或取消为 'timeout'。
 */
const isRaw = body => typeof body === 'string'
  || (typeof FormData !== 'undefined' && body instanceof FormData)
  || (typeof Blob !== 'undefined' && body instanceof Blob);

export async function request(path, options = {}) {
  const { method = 'GET', body, headers = {}, signal, timeout = 30000, redirectOn401 = false, fetchImpl = globalThis.fetch } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  if (signal) signal.addEventListener('abort', () => controller.abort(), { once: true });
  const init = { method, headers: { ...headers }, signal: controller.signal, credentials: 'same-origin' };
  if (body !== undefined) {
    if (isRaw(body)) init.body = body;
    else { init.body = JSON.stringify(body); init.headers['Content-Type'] = 'application/json'; }
  }
  try {
    const res = await fetchImpl(path, init);
    const type = (res.headers && res.headers.get('content-type')) || '';
    const data = type.includes('application/json') ? await res.json().catch(() => null) : await res.text();
    if (res.status === 401 && redirectOn401 && typeof location !== 'undefined') {
      location.assign(`/login?next=${encodeURIComponent(location.pathname + location.search)}`);
    }
    if (!res.ok) {
      const message = (data && typeof data === 'object' && (data.msg || data.error)) || `HTTP ${res.status}`;
      const code = (data && typeof data === 'object' && typeof data.error === 'string' && /^[\w.-]+$/.test(data.error)) ? data.error : `http_${res.status}`;
      return { ok: false, status: res.status, data, error: { status: res.status, code, message } };
    }
    return { ok: true, status: res.status, data, error: null };
  } catch (err) {
    const aborted = err && err.name === 'AbortError';
    return { ok: false, status: 0, data: null, error: { status: 0, code: aborted ? 'timeout' : 'network', message: aborted ? '请求超时或已取消' : '网络连接失败' } };
  } finally {
    clearTimeout(timer);
  }
}

export const get = (path, options = {}) => request(path, { ...options, method: 'GET' });
export const post = (path, body, options = {}) => request(path, { ...options, method: 'POST', body });
