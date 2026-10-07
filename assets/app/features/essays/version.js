import { html, each } from '../../core/html.js';
import { time, disabled, sourceLabel } from './shared.js';

const STATUS = { uploaded: '待转写', ocr_running: '正在转写', ocr_failed: '转写失败', proofreading: '待人工校对', confirmed: '正式转写已确认' };

function evaluation(e, version, busy) {
  const adopted = version.adopted_evaluation_id === e.id;
  const block = (label, rows) => rows?.length ? html`<div><h4>${label}</h4><ul>${each(rows, (_, i) => i, row => html`<li>${row}</li>`)}</ul></div>` : '';
  return html`<article class="es-evaluation" data-key="${e.id}"><header><div class="es-score"><strong>${e.total_score}</strong><span>/ 60</span></div>
    <div><strong>${e.evaluator || '评价'}${e.model ? ` · ${e.model}` : ''}</strong><p>${time(e.created_at)} · ${sourceLabel(e.source)}</p></div>
    <button class="btn btn--sm" data-action="es.adopt" data-arg="${e.id}" ${disabled(adopted || busy)}>${adopted ? '当前采用' : '采用这份评价'}</button></header>
    <p>${e.summary}</p>${block('优点', e.strengths)}${block('问题', e.issues)}${block('下一稿建议', e.suggestions)}
    ${e.dimensions ? html`<details><summary>其它评价维度</summary><pre>${JSON.stringify(e.dimensions, null, 2)}</pre></details>` : ''}</article>`;
}

function evaluationForm(s) {
  return html`<details class="es-evaluation-form"><summary>保存一份评价</summary>
    <form class="es-form" data-submit="es.evaluate"><div class="es-form-pair">
      <label class="field"><span>总分 / 60</span><input class="input" name="total_score" type="number" min="0" max="60" step="0.5" required aria-label="作文评价总分"></label>
      <label class="field"><span>评价者</span><input class="input" name="evaluator" value="人工" maxlength="200" aria-label="作文评价者"></label></div>
      <label class="field"><span>评价摘要</span><textarea class="textarea" name="summary" rows="3" aria-label="作文评价摘要" required></textarea></label>
      <div class="es-form-pair"><label class="field"><span>优点（每行一项）</span><textarea class="textarea" name="strengths" rows="3" aria-label="作文优点"></textarea></label>
        <label class="field"><span>问题（每行一项）</span><textarea class="textarea" name="issues" rows="3" aria-label="作文问题"></textarea></label></div>
      <label class="field"><span>下一稿建议（每行一项）</span><textarea class="textarea" name="suggestions" rows="3" aria-label="下一稿建议"></textarea></label>
      <button class="btn" ${disabled(s.busy)}>保存评价</button></form></details>`;
}

function original(s) {
  const v = s.version;
  const selected = Math.min(s.imagePage, v.images.length - 1);
  return html`<section class="es-original"><div class="es-heading"><h3>原图</h3><div class="es-actions">
    <button class="btn btn--sm" data-action="es.imagePage" data-arg="-1" aria-label="上一页原图" ${disabled(selected === 0)}>←</button>
    <span>${selected + 1} / ${v.images.length} 页</span><button class="btn btn--sm" data-action="es.imagePage" data-arg="1" aria-label="下一页原图" ${disabled(selected + 1 >= v.images.length)}>→</button></div></div>
    <a class="es-original-image" href="${v.image_urls[selected]}" target="_blank" rel="noopener" aria-label="打开第 ${selected + 1} 页原图">
      <img src="${v.image_urls[selected]}" alt="作文第 ${v.number} 稿，第 ${selected + 1} 页原图"></a><small class="muted">点击图片查看原始尺寸。</small></section>`;
}

function proof(s) {
  const v = s.version;
  return html`<section class="es-proof" data-key="proof-${v.id}"><div class="es-heading"><h3>人工校对</h3><span class="muted">${s.dirty ? '校对尚未保存' : '校对不增加版本'}</span></div>
    <p class="muted">只修正识别错误，保留作文原来的用字、句子和标点。</p>
    ${v.status === 'ocr_running' ? html`<div class="callout" role="status">正在按页原样转写，请稍候…</div>` : html`
      <label class="field"><span>校对后的全文</span><textarea class="textarea es-text-editor" aria-label="校对后的作文全文" rows="15"
        data-input="es.text" data-key="text-${v.id}">${s.textDraft}</textarea></label>
      <div class="es-actions"><button class="btn" data-action="es.saveText" ${disabled(!s.dirty || s.busy)}>保存校对</button>
        <button class="btn btn--primary" data-action="es.confirm" ${disabled(!s.textDraft.trim() || s.busy)}>确认正式转写</button></div>
      <small class="muted">确认后保留正式正文。重写或修改作文时上传下一稿。</small>`}
    ${v.uncertainties?.length ? html`<details open><summary>OCR 存疑 ${v.uncertainties.length} 处</summary><ul class="es-uncertainties">
      ${each(v.uncertainties, (_, i) => i, u => html`<li>${typeof u === 'string' ? u : `第 ${u.page || '?'} 页：${u.text || ''}${u.reason ? `（${u.reason}）` : ''}`}</li>`)}</ul></details>` : ''}
    ${v.raw_ocr_text ? html`<details><summary>查看原始 OCR 文本</summary><pre class="es-raw-text">${v.raw_ocr_text}</pre></details>` : ''}</section>`;
}

export function versionView(s, classifications) {
  const v = s.version;
  const previous = s.attempt.versions.filter(x => x.number < v.number && x.status === 'confirmed').at(-1);
  return html`<section class="es-panel card" data-key="version-${v.id}"><div class="es-heading"><div><p class="es-eyebrow">第 ${v.number} 稿 · ${v.images.length} 页</p>
    <h2>${STATUS[v.status]}</h2></div><span class="chip ${v.status === 'confirmed' ? 'chip--ok' : v.status === 'ocr_failed' ? 'chip--bad' : 'chip--info'}">${STATUS[v.status]}</span></div>
    <ol class="es-steps" aria-label="当前稿件进度"><li data-done="true">原图已保存</li><li data-done="${String(['proofreading', 'confirmed'].includes(v.status))}">原样转写</li>
      <li data-done="${String(v.status === 'confirmed')}">人工确认</li><li data-done="${String(v.evaluations.length > 0)}">作文评价</li></ol>
    ${v.error ? html`<div class="callout callout--bad" role="alert">${v.error}</div>` : ''}
    ${['uploaded', 'ocr_failed'].includes(v.status) ? html`<div class="es-actions"><button class="btn btn--primary" data-action="es.ocr" ${disabled(s.busy || s.dirty)}>
      ${v.can_retry ? '重试原样转写' : '开始原样转写'}</button><a class="muted" href="#/settings?section=recognition">AI 识别设置</a></div>` : ''}
    ${v.status === 'confirmed' ? html`<div class="es-actions"><button class="btn" data-action="es.discuss">与 AI 讨论这篇作文</button>
      ${previous ? html`<button class="btn" data-action="es.compare" data-arg="${previous.id}" ${disabled(s.busy)}>与上一稿对比</button>` : ''}
      <span class="muted">${v.evaluation_pending ? '待评价' : `${v.evaluations.length} 份评价`}</span></div>` : ''}
    <div class="es-proof-layout">${original(s)}${v.status === 'confirmed' ? html`<article class="es-final"><div class="es-heading"><h3>正式转写</h3><span class="chip chip--ok">已确认</span></div>
      <p class="es-reading">${v.text}</p><small class="muted">确认于 ${time(v.confirmed_at)}</small>
      ${v.raw_ocr_text ? html`<details><summary>原始 OCR 文本</summary><pre class="es-raw-text">${v.raw_ocr_text}</pre></details>` : ''}</article>` : proof(s)}</div>
    ${classifications(s, 'version', v.id, v.classifications)}
    ${v.status === 'confirmed' ? html`<section class="es-evaluations"><div class="es-heading"><h3>第 ${v.number} 稿的评价</h3><button class="btn btn--sm" data-action="es.refresh">刷新评价</button></div>
      ${!v.evaluations.length ? html`<p class="callout">正式转写已确认。可以与 AI 讨论后保存评价和修改重点，也可以自行填写评价。</p>` : ''}
      ${each(v.evaluations, e => e.id, e => evaluation(e, v, s.busy))}${evaluationForm(s)}</section>` : ''}
  </section>`;
}
