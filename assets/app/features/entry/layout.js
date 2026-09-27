/** 录入页整体布局：队列 + （对话 | 草稿 / 原图）+ 底栏（待补问题、去重结果、入库）。 */
import { html, each } from '../../core/html.js';
import { icon } from '../../ui/icons.js';
import { renderQueue, renderEmpty } from './queue.js';
import { renderChat } from './chat.js';
import { renderCanvas, renderImages } from './canvas.js';

export const BUSY = ['queued', 'extracting', 'thinking'];

export function issueText(groups, issue) {
  const group = (groups || []).find(g => g.gid === issue.gid);
  const entry = group && [...group.items, ...group.dictation].find(e => e.iid === issue.iid);
  let where = '';
  if (entry && group.genre === 'dictation') where = `默写 ${entry.source || ''}`.trim();
  else if (entry) where = `第 ${entry.no || '?'} 题`;
  else if (group) where = group.material?.title ? `《${group.material.title}》` : '';
  return where ? `${where}：${issue.message}` : issue.message;
}

function footer(s) {
  const d = s.draft;
  if (d.status === 'committed') {
    const c = d.committed || {};
    return html`<div class="sheet__foot is-done">${icon('check')}
      <span>已入库 ${c.created} 题${c.reencountered ? `，${c.reencountered} 题库里已有、记为又错一次` : ''}</span>
      <a class="btn btn--sm" href="#/library">去题库</a>
      <button class="btn btn--sm btn--primary" data-action="entry.next">录下一份</button></div>`;
  }
  const busy = BUSY.includes(d.status);
  const issues = d.issues || [];
  const dd = d.dedupe;
  let check = '';
  if (!d.revision) check = html`<span class="muted">${d.kind === 'chat' || d.kind === 'review' ? '让 AI 录题的话，题会出现在这里' : '识别完成后在这里校对'}</span>`;
  else if (issues.length) {
    check = html`<button class="linkish is-warn" data-action="entry.jump" data-arg="${issues[0].gid}|${issues[0].iid}">
      还有 ${issues.length} 处要补 · ${issueText(s.working, issues[0])}</button>`;
  } else if (dd) {
    check = html`<span>入库后新增 <b>${dd.new_units}</b> 题${dd.dup_units ? html`；<b>${dd.dup_units}</b> 题库里已有或本稿重复，不重复建题` : ''}</span>`;
  }
  const blocked = busy || !d.revision || issues.length > 0 || s.saving || s.dirty;
  return html`<div class="sheet__foot">
    <div class="sheet__check">${check}</div>
    <button class="btn btn--ghost btn--sm" data-action="entry.discard" ${busy ? html`disabled` : ''}>丢弃</button>
    <button class="btn btn--primary" data-action="entry.commit" ${blocked ? html`disabled` : ''}>${icon('check')}${dd && d.revision ? `入库 ${dd.new_units} 题` : '入库'}</button>
  </div>`;
}

const STATUS_TEXT = { queued: '排队中', extracting: '识别中', thinking: 'AI 执行中', ready: '可编辑', error: '出错了', committed: '已入库' };

function sheet(s) {
  const d = s.draft;
  const busy = BUSY.includes(d.status);
  const ro = busy || d.status === 'committed';
  const showImage = s.pane === 'image' || !d.revision;
  const saving = s.saving || s.dirty ? '保存中…' : '已保存';
  return html`<section class="sheet" aria-label="草稿">
    <div class="sheet__bar">
      <div class="seg" role="group" aria-label="草稿或原图">
        <button data-action="entry.pane" data-arg="draft" aria-pressed="${String(!showImage)}" ${d.revision ? '' : html`disabled`}>草稿</button>
        <button data-action="entry.pane" data-arg="image" aria-pressed="${String(showImage)}">原图</button>
      </div>
      <span class="sheet__status" data-tone="${busy ? 'wait' : d.status}">${STATUS_TEXT[d.status] || d.status}</span>
      ${d.revision ? html`<span class="sheet__rev">第 ${d.revision} 版 · ${ro ? '只读' : saving}</span>` : ''}
    </div>
    <div class="sheet__scroll" id="sheet-scroll">
      ${showImage && !d.images?.length ? html`<p class="sheet__empty">${d.kind === 'review' ? '批改结果写在复习记录里，去「复习」或「题库」查看。' : '这段对话还没有草稿。'}</p>`
        : showImage ? renderImages(d.images, s.zoom) : html`<div class="paper sheet__paper">${renderCanvas(s.working || d.groups, {
        ro, flash: s.flash, expanded: s.expanded, opened: s.opened, taxonomy: s.taxonomy, dedupe: d.dedupe })}</div>`}
    </div>
    ${footer(s)}
  </section>`;
}

export function view(s) {
  if (!s.draft) return html`<div class="entry">${renderQueue(s)}${renderEmpty(s)}</div>`;
  const tabs = [['chat', '对话'], ['draft', '草稿'], ['image', '原图']];
  const pressed = id => (id === 'chat' ? s.tab === 'chat' : s.tab === 'draft' && (s.pane === 'image' || !s.draft.revision) === (id === 'image'));
  return html`<div class="entry" data-tab="${s.tab}">
    ${renderQueue(s)}
    <div class="work__tabs seg" role="group" aria-label="切换">
      ${each(tabs, t => t[0], t => html`<button data-action="entry.tab" data-arg="${t[0]}" aria-pressed="${String(pressed(t[0]))}">${t[1]}</button>`)}
    </div>
    <div class="work">${renderChat(s.draft, s)}${sheet(s)}</div>
  </div>`;
}
