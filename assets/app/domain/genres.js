/** 板块、评分与题型表（题型表来自 /api/taxonomy，页面共用一份缓存）。 */
import { get } from '../core/api.js';

export const GENRES = [
  { code: 'modern', name: '现代文阅读', short: '现代文' },
  { code: 'classical', name: '文言文阅读', short: '文言文' },
  { code: 'poetry', name: '古代诗歌阅读', short: '古诗' },
  { code: 'dictation', name: '名句默写', short: '默写' },
];
export const genreName = code => (GENRES.find(g => g.code === code) || { name: code }).name;
export const genreShort = code => (GENRES.find(g => g.code === code) || { short: code }).short;

export const GRADES = [
  { value: 0, label: '不会', hint: '没思路 / 答偏' },
  { value: 1, label: '部分', hint: '只答到少量要点' },
  { value: 2, label: '基本', hint: '主要要点都有' },
  { value: 3, label: '完整', hint: '要点齐全、表述到位' },
];
export const DICTATION_GRADES = [
  { value: 0, label: '不会', hint: '写不出' },
  { value: 1, label: '有错字', hint: '写出来但有错别字' },
  { value: 3, label: '全对', hint: '一字不差' },
];
export const gradesFor = genre => (genre === 'dictation' ? DICTATION_GRADES : GRADES);
export const gradeLabel = (genre, value) => (gradesFor(genre).find(g => g.value === value) || { label: '—' }).label;

let taxonomy = null;
export async function loadTaxonomy() {
  if (taxonomy) return taxonomy;
  const res = await get('/api/taxonomy');
  if (res.ok) taxonomy = res.data;
  return taxonomy || { genres: GENRES, qtypes: {} };
}

export const masteryTone = value => (value < 0.35 ? 'low' : value < 0.7 ? 'mid' : 'high');
