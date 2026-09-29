/** 评分视图的公共小工具：当前看的是哪道题、这道题的答案是否已经亮出来（对过答案或评过分）。 */
export const NEVER = '9999-12-31';
export const isShown = (item, s) => s.revealed.has(item.id) || Boolean(item.grade);

export function focusTarget(s) {
  const items = s.session?.items || [];
  const n = items.findIndex(x => x.id === s.focus);
  return n >= 0 ? { it: items[n], n: n + 1 } : null;
}
