/** Reduce persistent harness events into stable chat blocks; no model context is rendered as HTML. */
export function blocks(events) {
  const rows = []; const messages = new Map(); const calls = new Map(); const preparing = new Map(); const turns = new Map();
  const add = block => { rows.push(block); return block; };
  const current = event => messages.get(`${event.run_id}:${turns.get(event.run_id) || 1}`);
  for (const event of events) {
    const run = event.run_id; const turn = turns.get(run) || 1;
    if (event.type === 'user_message') add({ id: `u:${event.i}`, kind: 'user', text: event.text, queued: event.queued });
    if (event.type === 'turn_start') turns.set(run, event.turn);
    if (event.type === 'message_start') {
      const id = `${run}:${event.turn}`;
      const think = add({ id: `think:${id}`, kind: 'thinking', text: '', status: 'live' });
      const message = add({ id: `text:${id}`, kind: 'assistant', text: '', status: 'live', think });
      messages.set(id, message);
    }
    if (event.type === 'delta') {
      const message = current(event);
      if (message) { if (event.kind === 'thinking') message.think.text += event.text || ''; else message.text += event.text || ''; }
    }
    if (event.type === 'message_end') {
      const message = current(event);
      if (message) { message.text = event.message?.content || message.text; message.think.text = event.message?.thinking || message.think.text; message.status = 'done'; message.think.status = 'done'; }
    }
    if (event.type === 'toolcall_delta') {
      const key = `${run}:${turn}:${event.index}`;
      let block = preparing.get(key);
      if (!block) { block = add({ id: `tool:${key}`, kind: 'tool', status: 'preparing', argsText: '', name: event.name }); preparing.set(key, block); }
      block.name = event.name || block.name; block.argsText += event.delta || '';
    }
    if (event.type === 'tool_start') {
      const key = `${run}:${turn}:${event.index}`;
      const block = preparing.get(key) || add({ id: `tool:${key}`, kind: 'tool' });
      Object.assign(block, { name: event.name, label: event.label, args: event.args, status: 'running' });
      calls.set(`${run}:${event.id}`, block);
    }
    if (['tool_waiting', 'tool_decision'].includes(event.type)) {
      const block = calls.get(`${run}:${event.id}`);
      if (block) { block.operation = event.operation; block.status = event.type === 'tool_waiting' ? 'waiting' : 'running'; }
    }
    if (event.type === 'tool_end') {
      const block = calls.get(`${run}:${event.id}`);
      if (block) {
        Object.assign(block, { status: event.error ? 'error' : 'done', summary: event.summary, result: event.content });
        try { const value = JSON.parse(event.content); if (value.operation_id) block.operation = value; } catch (_) { /* plain text result */ }
      }
    }
    if (event.type === 'run_end') {
      rows.filter(row => ['live', 'running', 'preparing', 'waiting'].includes(row.status)).forEach(row => { row.status = event.status === 'done' ? 'done' : event.status; });
      add({ id: `end:${run}`, kind: 'run', status: event.status, error: event.error, stats: event.stats });
    }
  }
  return rows.filter(row => !['assistant', 'thinking'].includes(row.kind) || row.text);
}

export const isRunning = run => ['running', 'waiting_confirmation'].includes(run?.status);
export const STATUS = { applied: '已执行', pending_confirmation: '待人工审核', applying: '正在执行', rejected: '已拒绝', expired: '已到期', conflict: '对象已变化', failed: '执行失败', cancelled: '已停止', interrupted: '已中断', done: '完成', stopped: '已停止', error: '出错' };
