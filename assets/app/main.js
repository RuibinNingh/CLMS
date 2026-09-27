/** 启动入口：登记页面 → 外壳 → 路由开始。 */
import { startShell } from './shell.js';
import { get } from './core/api.js';
import { page as dashboard } from './features/dashboard/index.js';
import { page as entry } from './features/entry/index.js';
import { page as library } from './features/library/index.js';
import { page as review } from './features/review/index.js';
import { page as settings } from './features/settings/index.js';

const ctx = startShell([dashboard, entry, library, review, settings]);
ctx.router.start();

get('/api/summary').then(res => {
  if (!res.ok) return;
  document.getElementById('app-version').textContent = `v${res.data.version}`;
  if (res.data.due) ctx.bus.emit('badge', { id: 'review', text: String(res.data.due) });
});
