import { html, each } from '../../core/html.js';
import { icon } from '../../ui/icons.js';
import { versionView } from './version.js';
import { time, link, disabled, sourceLabel } from './shared.js';
export const tags = values => html`<div class="es-tags">${each(values || [], c => c.id,
  c => html`<span class="chip">${c.name}</span>`)}</div>`;

function classifications(s, targetType, targetId, values) {
  return html`<div class="es-classify">${tags(values)}<form class="es-inline" data-submit="es.classify"
    data-target-type="${targetType}" data-target-id="${targetId}">
    <input class="input" name="names" aria-label="添加自由分类" placeholder="添加分类，如：成长、亲情" maxlength="200" required>
    <button class="btn btn--sm" ${disabled(s.busy)}>添加</button></form></div>`;
}

function sidebar(s) {
  return html`<aside class="es-library card" aria-label="作文题列表">
    <div class="es-heading"><h2>作文题</h2><span class="muted">${s.total}</span></div>
    <input class="input" type="search" aria-label="搜索作文题" placeholder="搜索题目、要求或分类" value="${s.q}" data-input="es.search">
    <select class="select" aria-label="按作文分类筛选" data-change="es.filter"><option value="">全部分类</option>
      ${each(s.classifications, c => c.id, c => html`<option value="${c.id}" ${c.id === s.classificationId ? html`selected` : ''}>${c.name}</option>`)}</select>
    <button class="btn" data-action="es.newPrompt">${icon('plus')}新增作文题</button>
    <div class="es-prompt-list">${each(s.prompts, p => p.id, p => html`
      <a class="es-prompt" href="${link('prompt', p.id)}" data-action="es.navigate" data-arg="${link('prompt', p.id)}"
        data-key="${p.id}" aria-current="${s.prompt?.id === p.id ? 'true' : 'false'}">
        <strong>${p.title}</strong><span>${p.text.slice(0, 70)}</span>
        <small>${p.attempt_count} 次练习${p.last_attempt_at ? ` · 最近 ${p.last_attempt_at.slice(0, 10)}` : ''}</small>
        ${tags(p.classifications)}</a>`)}</div>
    ${!s.prompts.length ? html`<p class="empty">${s.loading ? '正在加载…' : '没有匹配的作文题'}</p>` : ''}
    ${s.prompts.length < s.total ? html`<button class="btn btn--ghost" data-action="es.more">加载更多</button>` : ''}
  </aside>`;
}

function promptForm(s) {
  return html`<section class="es-panel card" data-key="prompt-form"><div class="es-heading"><h2>新增完整作文题</h2>
    <button class="btn btn--ghost" data-action="es.cancelPrompt">取消</button></div>
    <form class="es-form" data-submit="es.createPrompt">
      <label class="field"><span>题目名称</span><input class="input" name="title" aria-label="作文题名称" maxlength="200" required></label>
      <label class="field"><span>题目正文</span><textarea class="textarea" name="text" aria-label="作文题正文" rows="6" required placeholder="输入作文题目、材料或写作任务"></textarea></label>
      <label class="field"><span>写作要求</span><textarea class="textarea" name="requirements" aria-label="作文写作要求" rows="3" placeholder="字数、限制或其它要求"></textarea></label>
      <label class="field"><span>出处（可选）</span><input class="input" name="origin" aria-label="作文题出处" placeholder="例如：学校周练"></label>
      <div class="es-actions"><button class="btn btn--primary" ${disabled(s.busy)}>创建作文题</button><span class="muted">完整作文 · 满分 60</span></div>
    </form></section>`;
}

function promptView(s) {
  const p = s.prompt;
  return html`<section class="es-panel card" data-key="${p.id}"><div class="es-heading"><div><p class="es-eyebrow">完整作文题</p><h2>${p.title}</h2></div>
    <span class="chip">${p.attempt_count} 次练习</span></div>
    <p class="es-reading">${p.text}</p>${p.requirements ? html`<div class="es-requirements"><strong>写作要求</strong><p>${p.requirements}</p></div>` : ''}
    ${p.metadata?.origin ? html`<p class="muted">出处：${p.metadata.origin}</p>` : ''}
    ${classifications(s, 'prompt', p.id, p.classifications)}
    <div class="es-heading es-section-head"><h3>历次写作练习</h3></div>
    <form class="es-inline" data-submit="es.createAttempt"><input class="input" name="title" aria-label="练习名称" placeholder="这次练习的名称（可选）" maxlength="200">
      <button class="btn btn--primary" ${disabled(s.busy)}>${icon('plus')}新建一次练习</button></form>
    <div class="es-attempt-list">${each(p.attempts, a => a.id, a => html`
      <a class="es-attempt" data-key="${a.id}" href="${link('attempt', a.id)}" data-action="es.navigate" data-arg="${link('attempt', a.id)}">
        <div><strong>${a.title || '作文练习'}</strong><small>${time(a.created_at)}</small></div>
        <span>${a.version_count} 版 · 修改 ${a.modification_count} 次</span>${icon('chevron')}</a>`)}</div>
    ${!p.attempts?.length ? html`<p class="empty">从第一稿开始，保留每一次写作与修改。</p>` : ''}</section>`;
}

function upload(s) {
  return html`<section class="es-panel card" data-key="upload"><div class="es-heading"><div><h3>${s.attempt.version_count ? '上传下一版作文' : '上传第一版作文'}</h3>
    <p class="muted">按阅读顺序选择原图。多页合为一版。</p></div></div>
    <label class="es-upload"><span>${icon('upload')}选择作文图片</span><input type="file" accept="image/*" multiple
      aria-label="选择作文图片" data-change="es.files" ${disabled(s.busy)}></label>
    ${s.files.length ? html`<ol class="es-upload-pages">${each(s.files, (_, i) => i, (file, i) => html`<li data-key="upload-${i}">
      <img src="${file.data}" alt="待上传第 ${i + 1} 页"><span>${i + 1}. ${file.name}</span>
      <div class="es-actions"><button class="btn btn--sm" data-action="es.movePage" data-arg="${i}:-1" aria-label="第 ${i + 1} 页前移" ${disabled(i === 0 || s.busy)}>←</button>
        <button class="btn btn--sm" data-action="es.movePage" data-arg="${i}:1" aria-label="第 ${i + 1} 页后移" ${disabled(i === s.files.length - 1 || s.busy)}>→</button>
        <button class="btn btn--sm btn--ghost" data-action="es.removePage" data-arg="${i}" aria-label="移除第 ${i + 1} 页" ${disabled(s.busy)}>移除</button></div></li>`)}</ol>
      <div class="es-actions"><button class="btn btn--primary" data-action="es.upload" ${disabled(s.busy)}>上传 ${s.files.length} 页为第 ${s.attempt.version_count + 1} 版</button>
        <span class="muted">${s.uploadProgress || '上传后开始原样转写'}</span></div>` : ''}
  </section>`;
}

function noteList(s) {
  return html`<section class="es-panel card" data-key="notes"><div class="es-heading"><h3>讨论笔记与下一稿重点</h3></div>
    <form class="es-form" data-submit="es.note"><textarea class="textarea" name="text" aria-label="作文讨论笔记" rows="3" required
      placeholder="记录你想保留的讨论结论，如：下一稿重点处理第二段和结尾。"></textarea>
      <div class="es-actions"><label class="es-check"><input type="checkbox" name="version" ${s.version ? html`checked` : ''} ${disabled(!s.version)}>关联当前第 ${s.version?.number || '—'} 稿</label>
        <button class="btn" ${disabled(s.busy)}>保存笔记</button></div></form>
    <div class="es-notes">${each(s.attempt.notes, n => n.id, n => html`<article data-key="${n.id}"><p>${n.text}</p>
      <small>${time(n.created_at)} · ${sourceLabel(n.source)}${n.version_id ? ` · 第 ${s.attempt.versions.find(v => v.id === n.version_id)?.number || ''} 稿` : ' · 本次练习'}</small></article>`)}</div></section>`;
}

function diffView(s) {
  if (!s.diff) return '';
  return html`<section class="es-panel card" data-key="diff"><div class="es-heading"><h3>版本文本对比</h3>
    <button class="btn btn--ghost" data-action="es.closeDiff">收起</button></div>
    <div class="es-diff"><article><h4>上一稿</h4><p>${each(s.diff.changes, (_, i) => i, c =>
      c.kind === 'equal' ? html`${c.before}` : html`<del>${c.before}</del>`)}</p></article>
      <article><h4>当前稿</h4><p>${each(s.diff.changes, (_, i) => i, c =>
        c.kind === 'equal' ? html`${c.after}` : html`<ins>${c.after}</ins>`)}</p></article></div></section>`;
}

function attemptView(s) {
  const a = s.attempt;
  return html`<section class="es-panel card" data-key="${a.id}"><div class="es-heading"><div><a href="${link('prompt', s.prompt.id)}" data-action="es.navigate" data-arg="${link('prompt', s.prompt.id)}">${s.prompt.title}</a>
    <h2>${a.title || '作文练习'}</h2><p class="muted">${time(a.created_at)}</p></div><div class="es-count"><strong>${a.version_count} 版</strong><span>修改 ${a.modification_count} 次</span></div></div>
    <details class="es-attempt-prompt"><summary>查看作文题目与要求</summary><p class="es-reading">${s.prompt.text}</p>
      ${s.prompt.requirements ? html`<p class="muted">写作要求：${s.prompt.requirements}</p>` : ''}</details>
    <div class="es-version-tabs" aria-label="稿件版本">${each(a.versions, v => v.id, v => html`
      <a href="${link('version', v.id)}" data-key="${v.id}" data-action="es.navigate" data-arg="${link('version', v.id)}"
        aria-current="${s.version?.id === v.id ? 'true' : 'false'}"><strong>第 ${v.number} 稿</strong><small>${time(v.created_at)}</small>
        <span>${v.evaluations.length ? `${v.evaluations.length} 份评价` : v.status === 'confirmed' ? '待评价' : '待确认'}</span></a>`)}</div>
    ${classifications(s, 'attempt', a.id, a.classifications)}
    <div class="es-actions"><button class="btn" data-action="es.showUpload">${icon('upload')}${a.version_count ? '上传下一稿' : '上传第一稿'}</button>
      <span class="muted">${a.version_count ? '重写作文增加版本；校对转写不计修改次数。' : '多张图片仍然只算一个版本。'}</span></div></section>
    ${s.showUpload || !a.version_count ? upload(s) : ''}
    ${s.version ? versionView(s, classifications) : ''}${diffView(s)}${noteList(s)}`;
}

export function view(s) {
  return html`<div class="es" data-has-selection="${String(Boolean(s.prompt || s.attempt || s.creatingPrompt))}" data-list-open="${String(s.listOpen)}">
    <header class="es-intro"><div><h2>完整作文练习</h2><p>保留原稿、每一版转写和每一次评价。</p></div><div class="es-actions">
    <button class="btn es-mobile-list" data-action="es.listToggle" aria-expanded="${String(s.listOpen)}">作文题 ${s.total}</button><span class="chip">60 分制</span></div></header>
    ${s.error ? html`<div class="callout callout--bad" role="alert">${s.error}</div>` : ''}
    <div class="es-layout">${sidebar(s)}<section class="es-work" aria-label="作文练习工作区" aria-busy="${String(s.busy || s.detailLoading)}">
      ${s.creatingPrompt ? promptForm(s) : s.attempt ? attemptView(s) : s.prompt ? promptView(s)
        : html`<section class="es-panel es-empty card"><div>${icon('entry')}<h2>${s.detailLoading ? '正在打开作文…' : '从一篇完整作文开始'}</h2>
          <p>选择一个作文题，或创建题目并上传第一稿。</p><button class="btn btn--primary" data-action="es.newPrompt">新增作文题</button></div></section>`}
    </section></div></div>`;
}
