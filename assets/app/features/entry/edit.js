/**
 * 草稿工作副本上的纯函数操作。路径统一写成 "gid|iid|field"：iid 为空表示材料字段；
 * 默写答案表的字段写成 "blank:n"。所有函数返回新数组（不改入参），由 index.js 决定何时保存。
 */
export const clone = value => JSON.parse(JSON.stringify(value ?? null));

export function parsePath(path) {
  const [gid = '', iid = '', field = ''] = String(path || '').split('|');
  return { gid, iid, field };
}

const locate = (groups, gid, iid) => {
  const group = groups.find(g => g.gid === gid);
  if (!group) return { group: null, entry: null };
  const entry = iid ? [...group.items, ...group.dictation].find(e => e.iid === iid) : null;
  return { group, entry };
};

export function setField(groups, path, value) {
  const next = clone(groups);
  const { gid, iid, field } = parsePath(path);
  const { group, entry } = locate(next, gid, iid);
  if (!group) return next;
  if (!iid) {
    if (field !== 'genre') { group.material[field] = value; return next; }
    group.genre = value;
    // 换板块时保证新板块下至少有一道空题（默写与阅读的题目结构不同）
    if (value === 'dictation' && !group.dictation.length) return addItem(next, gid);
    if (value !== 'dictation' && !group.items.length) return addItem(next, gid);
    return next;
  }
  if (!entry) return next;
  if (field.startsWith('blank:')) {
    entry.blanks = { ...(entry.blanks || {}), [field.slice(6)]: value };
  } else if (field === 'score') {
    entry.score = value === '' ? null : Number(value);
  } else if (field === 'blank_lines') {
    entry.blank_lines = Math.max(0, Math.min(24, Number(value) || 0));
  } else {
    entry[field] = value;
    if (field === 'answer') entry.answer_origin = 'user';
  }
  return next;
}

export function stepLines(groups, path, delta) {
  const { gid, iid } = parsePath(path);
  const { entry } = locate(groups, gid, iid);
  return setField(groups, `${gid}|${iid}|blank_lines`, (entry?.blank_lines || 0) + delta);
}

const nextId = (groups, prefix) => {
  const used = new Set(groups.flatMap(g => [...g.items, ...g.dictation].map(e => e.iid)));
  let n = 1;
  while (used.has(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
};

export function addItem(groups, gid) {
  const next = clone(groups);
  const group = next.find(g => g.gid === gid);
  if (!group) return next;
  if (group.genre === 'dictation') {
    group.dictation.push({ iid: nextId(next, 'd'), template: '', blanks: {}, source: '', kind: '直接默写' });
  } else {
    const last = group.items[group.items.length - 1];
    const no = last && /^\d+$/.test(last.no) ? String(Number(last.no) + 1) : '';
    group.items.push({ iid: nextId(next, 'i'), no, qtype: '', stem: '', answer: '', answer_origin: '', analysis: '',
      score: null, blank_lines: 4, user_answer: '', note: '' });
  }
  return next;
}

export function removeEntry(groups, path) {
  const next = clone(groups);
  const { gid, iid } = parsePath(path);
  const group = next.find(g => g.gid === gid);
  if (!group) return next;
  group.items = group.items.filter(e => e.iid !== iid);
  group.dictation = group.dictation.filter(e => e.iid !== iid);
  return next.filter(g => g.items.length || g.dictation.length);
}

/** 模板里出现的空编号（与后端 dictation.blank_numbers 一致，支持全角括号）。 */
export function blankNumbers(template) {
  const seen = [];
  for (const m of String(template || '').matchAll(/[{｛]\s*书写区域\s*(\d+)\s*[}｝]/g)) {
    if (!seen.includes(m[1])) seen.push(m[1]);
  }
  return seen;
}

/** 在模板末尾插入下一个空。 */
export function insertBlank(groups, path) {
  const { gid, iid } = parsePath(path);
  const { entry } = locate(groups, gid, iid);
  if (!entry) return groups;
  const nums = blankNumbers(entry.template).map(Number);
  const n = (nums.length ? Math.max(...nums) : 0) + 1;
  return setField(groups, `${gid}|${iid}|template`, `${entry.template || ''}{书写区域${n}}`);
}

/** 在草稿末尾加一个板块（AI 漏识别某一篇或默写时手动补）。 */
export function addGroup(groups, genre) {
  const next = clone(groups);
  const used = new Set(next.map(g => g.gid));
  let n = 1;
  while (used.has(`g${n}`)) n += 1;
  const group = { gid: `g${n}`, genre, material: { title: '', author: '', source: '', text: '' }, items: [], dictation: [] };
  next.push(group);
  return addItem(next, group.gid);
}

/** 草稿里的题量：阅读按小题、默写按空计（与后端 count_units 一致）。 */
export function countUnits(groups) {
  let items = 0; let blanks = 0; let materials = 0;
  for (const g of groups || []) {
    if (g.genre === 'dictation') blanks += g.dictation.reduce((sum, e) => sum + blankNumbers(e.template).length, 0);
    else { materials += 1; items += g.items.length; }
  }
  return { items, blanks, materials };
}
