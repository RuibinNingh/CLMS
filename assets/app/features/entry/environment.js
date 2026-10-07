/** 录入工作台的视口、设备偏好与本地日期。 */
export const reduceMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
export const wide = () => window.matchMedia?.('(min-width: 1501px)').matches;
export const stored = key => { try { return localStorage.getItem(key); } catch (_) { return null; } };
export const localDay = () => {
  const day = new Date();
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
};
