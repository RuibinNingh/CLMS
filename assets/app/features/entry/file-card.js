/** 拆分状态只属于文件卡片；完成时卡片裂开，图片页接替这个位置。 */
import { html, each } from '../../core/html.js';
import { icon } from '../../ui/icons.js';

export function fileCard(job) {
  const failed = job.state === 'error';
  const bursting = job.state === 'burst';
  const queued = job.state === 'queued';
  const progress = job.total ? Math.round(job.done / job.total * 100) : 0;
  const label = failed ? (job.pdf ? '拆分失败' : '上传失败') : bursting ? '拆分完成'
    : queued ? (job.pdf ? '等待拆分' : '等待上传') : job.pdf ? '拆分中' : '上传中';
  return html`<li class="page file-card" data-import="${job.id}" data-key="import-${job.id}" data-state="${job.state}" aria-label="${job.name}，${label}">
    <div class="file-card__body">
      <div class="file-card__paper" aria-hidden="true"><span>${job.pdf ? 'PDF' : 'IMG'}</span><i></i><i></i><i></i></div>
      <div class="file-card__status" role="status"><b>${label}</b>
        ${failed ? html`<span class="file-card__error" title="${job.error}">${job.error}</span>`
          : html`<span>${job.total ? `${job.done} / ${job.total} 页` : queued ? '稍后就好' : '正在读取文件'}</span>`}
      </div>
      ${job.pdf && !failed ? html`<progress class="file-card__progress" max="100" value="${progress}" aria-label="${job.name} 拆分进度">${progress}%</progress>` : ''}
      ${failed ? html`<button class="file-card__retry" data-action="entry.importRetry" data-arg="${job.id}">重试</button>` : ''}
      ${bursting ? '' : html`<button class="file-card__remove" data-action="entry.importRemove" data-arg="${job.id}" aria-label="移除 ${job.name}" title="移除文件">${icon('close')}</button>`}
    </div>
    <span class="file-card__name" title="${job.name}">${job.name}</span>
    ${bursting ? html`<span class="file-card__burst" aria-hidden="true">${each([0, 1, 2, 3, 4, 5, 6, 7], n => n, n => html`<i data-shard="${n}"></i>`)}</span>` : ''}
  </li>`;
}
