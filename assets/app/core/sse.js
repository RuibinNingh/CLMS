/** SSE 订阅：subscribe(url, onEvent, { onError }) → close()。EventSource 断线会自动重连（带 Last-Event-ID）。 */
export function subscribe(url, onEvent, { onError } = {}) {
  if (typeof EventSource === 'undefined') return () => {};
  const es = new EventSource(url);
  es.onmessage = event => {
    try { onEvent(JSON.parse(event.data)); } catch (err) { console.error(err); }
  };
  es.onerror = () => onError?.();
  return () => es.close();
}
