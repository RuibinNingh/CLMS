/** 日期与数字格式化：空值与非法值一律显示「—」。YYYY-MM-DD 按本地日期解析。 */
const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

export function parseDay(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value || ''));
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

export const weekdayName = value => { const d = parseDay(value); return d ? WEEK[d.getDay()] : '—'; };

export function formatDay(value, { weekday = false } = {}) {
  const d = parseDay(value);
  if (!d) return '—';
  const text = `${d.getMonth() + 1}月${d.getDate()}日`;
  return weekday ? `${text} ${WEEK[d.getDay()]}` : text;
}

export function relativeDay(value, today) {
  const d = parseDay(value); const t = parseDay(today);
  if (!d || !t) return '—';
  const diff = Math.round((d - t) / 86400000);
  if (diff === 0) return '今天';
  if (diff === 1) return '明天';
  if (diff === -1) return '昨天';
  return diff > 0 ? `${diff} 天后` : `${-diff} 天前`;
}

export function formatTime(iso) {
  const m = /T(\d{2}):(\d{2})/.exec(String(iso || ''));
  return m ? `${m[1]}:${m[2]}` : '';
}

export const percent = value => (Number.isFinite(Number(value)) ? `${Math.round(Number(value) * 100)}%` : '—');
