import { useState } from "react";
import { api, ApiError, errorText } from "../../shared/api";
import { useBeforeUnload, useDraft, useLoad } from "../../shared/hooks";
import type { Review, Version } from "../../shared/types";
import { date, ErrorNotice, Loading, Tag } from "../../shared/ui";
import { Viewer } from "../document-viewer/Viewer";
import { ReadingLayout, type ReadingPanel } from "../../shared/ReadingLayout";
import { Icon } from "../../shared/Icon";
import { ReviewProposal } from "./ReviewProposal";
import { HelpTip } from "../../shared/HelpTip";
import { PromptPreview } from "./ProposalContent";
import {
  record,
  reviewAction,
  reviewImpact,
  reviewPages,
  reviewPaperTitle,
  reviewTitle,
  statusLabels,
} from "./reviewPresentation";
import { refreshReviewCount } from "./PendingReviewBadge";

import { clearReviewDraft, reviewChanges } from "./reviewDraft";
export { reviewChanges } from "./reviewDraft";
export function ReviewDetail({
  id,
  onDecided,
  onNext,
}: {
  id: string;
  onDecided: () => void;
  onNext: () => void;
}) {
  const review = useLoad(() => api<Review>(`/reviews/${id}`), [id]);
  const [panel, setPanel] = useState<ReadingPanel>("paper");
  return (
    <>
      <a className="button quiet review-back" href="#/reviews">
        <Icon name="back" /> 返回队列
      </a>
      <ErrorNotice message={review.error} retry={review.reload} />
      {review.loading && !review.data && <Loading />}
      {review.data && (
        <ReviewForm
          key={`${id}-${review.data.revision}-${review.data.status}`}
          review={review.data}
          panel={panel}
          onPanel={setPanel}
          onSaved={review.reload}
          onDecided={() => {
            review.reload();
            onDecided();
          }}
          onNext={onNext}
        />
      )}
    </>
  );
}
function ReviewForm({
  review,
  panel,
  onPanel,
  onSaved,
  onDecided,
  onNext,
}: {
  review: Review;
  panel: ReadingPanel;
  onPanel: (panel: ReadingPanel) => void;
  onSaved: () => void;
  onDecided: () => void;
  onNext: () => void;
}) {
  const draft = useDraft(`clms-review-${review.id}`, {
    base_revision: review.revision,
    payload: review.payload,
  });
  const changes = reviewChanges(
    review.kind,
    review.payload,
    draft.value.payload,
  );
  const dirty = Object.keys(changes).length > 0;
  const [invalid, setInvalid] = useState(false);
  const [pageId, setPageId] = useState("");
  const [locationKey, setLocationKey] = useState(0);
  useBeforeUnload(dirty || invalid);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [editing, setEditing] = useState(dirty),
    [showPreview, setShowPreview] = useState(!dirty);
  const stale = draft.value.base_revision !== review.revision && dirty;
  const versionId = String(
    review.payload.version_id ||
      review.target_snapshot.version_id ||
      review.payload.parent_version_id ||
      "",
  );
  const version = useLoad(
    () =>
      versionId
        ? api<Version>(`/versions/${versionId}`)
        : Promise.resolve(null),
    [versionId],
  );
  const pages = reviewPages(review, draft.value.payload, version.data);
  const frozenPrompt = record(
    review.target_snapshot.prompt_snapshot || version.data?.prompt_snapshot,
  );
  const pending = review.status === "pending";
  async function save() {
    setBusy(true);
    setError("");
    try {
      await api(`/reviews/${review.id}/revise`, {
        expected_revision: draft.value.base_revision,
        changes,
      });
      clearReviewDraft(review.id);
      setEditing(false);
      setShowPreview(true);
      refreshReviewCount();
      onSaved();
    } catch (reason) {
      setError(errorText(reason));
      if (reason instanceof ApiError && reason.status === 409) onSaved();
    } finally {
      setBusy(false);
    }
  }
  async function decide(decision: "approve" | "reject") {
    if (dirty || stale || invalid) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Review>(`/reviews/${review.id}/decide`, {
        expected_revision: review.revision,
        expected_digest: review.effective_digest,
        decision,
      });
      if (result.status === "applied" || result.status === "rejected")
        clearReviewDraft(review.id);
      onDecided();
    } catch (reason) {
      setError(errorText(reason));
      if (reason instanceof ApiError && reason.status === 409) onDecided();
    } finally {
      setBusy(false);
    }
  }
  const proposal = (
    <ReviewProposal
      review={review}
      payload={draft.value.payload}
      pages={pages}
      version={version.data}
      versionError={version.error}
      onReloadVersion={version.reload}
      editing={editing}
      onToggleEditing={() => {
        setEditing(!editing);
        setShowPreview(editing);
      }}
      onChange={(payload) => {
        draft.setValue({ ...draft.value, payload });
        setShowPreview(false);
      }}
      onInvalid={setInvalid}
      onPage={(id) => {
        setPageId(id);
        setLocationKey((value) => value + 1);
        onPanel("paper");
      }}
      onSave={save}
      busy={busy}
      dirty={dirty}
      stale={stale}
      invalid={invalid}
    />
  );
  return (
    <>
      <section className="panel review-summary">
        <div className="section-heading">
          <div className="actions">
            <span className="review-brief-label">AI 提案</span>
            <h2>{reviewAction(review)}</h2>
            <HelpTip label="AI 提交内容说明">
              本页依据实际提案展示操作与内容。来源只能确认提交凭据；如果客户端声明了模型名称，会另行标注为自报信息。
            </HelpTip>
          </div>
          <Tag tone={review.status === "applied" ? "success" : "warning"}>
            {statusLabels[review.status]}
          </Tag>
        </div>
        <h3 className="review-operation-title">{reviewTitle(review)}</h3>
        <p className="muted review-provenance">
          {review.source_actor.startsWith("mcp:")
            ? "外部 MCP 客户端"
            : review.source_actor}{" "}
          · {date(review.created_at)} · 修订 {review.revision}
        </p>
        <div className="review-impact">
          <Icon name="review" />
          <div>
            <strong>
              {review.status === "pending"
                ? "通过后会发生"
                : review.status === "applied"
                  ? "已入档的操作"
                  : "这项提案未执行"}
            </strong>
            <p>
              {review.status === "pending" || review.status === "applied"
                ? reviewImpact(review, draft.value.payload)
                : "正式档案未发生这项变更。处理结果与原提案保留在下方。"}
            </p>
          </div>
        </div>
        {version.data && (
          <div className="review-target">
            <div className="actions">
              <Tag>
                {review.kind === "revision" ? "基于 " : "审核目标 "}V
                {version.data.version_no}
              </Tag>
              <small className="muted">
                {pages.length} 页 ·{" "}
                {review.kind === "revision"
                  ? reviewPaperTitle(review)
                  : "本次写作的冻结题目"}
              </small>
              {version.data.prompt_id && (
                <a
                  href={`#/prompt/${version.data.prompt_id}?version=${version.data.id}`}
                >
                  查看档案
                </a>
              )}
            </div>
          </div>
        )}
        <ErrorNotice message={error} />
        {(review.status === "conflict" || review.status === "failed") && (
          <div className="notice error" role="alert">
            <strong>
              {review.status === "conflict"
                ? "提案发生冲突，未入档"
                : "提案执行失败，未入档"}
            </strong>
            <pre>{JSON.stringify(review.result, null, 2)}</pre>
            <p>
              当前提案和人工修订仍保留。请让外部 AI
              读取当前目标与基线后重新建立提案，再进行审核。
            </p>
            <button
              onClick={() =>
                navigator.clipboard
                  .writeText(JSON.stringify(review.payload, null, 2))
                  .catch(() =>
                    setError("无法自动复制，请手动复制下方有效提案。"),
                  )
              }
            >
              复制有效提案
            </button>
          </div>
        )}
        {stale && (
          <div className="notice warning">
            服务器提案已有新修订。你的修改仍保存在本浏览器；请先复制修改内容，再重新核对当前提案。
            <button
              onClick={() =>
                navigator.clipboard
                  .writeText(JSON.stringify(draft.value.payload, null, 2))
                  .catch(() =>
                    setError("无法自动复制，请在下方内容中手动复制。"),
                  )
              }
            >
              复制本地修改
            </button>
            <button
              onClick={() => {
                if (
                  window.confirm(
                    "已保存需要保留的修改？重新核对会载入服务器当前提案。",
                  )
                ) {
                  clearReviewDraft(review.id);
                  draft.setValue({
                    base_revision: review.revision,
                    payload: review.payload,
                  });
                  setEditing(false);
                  setShowPreview(true);
                  setInvalid(false);
                }
              }}
            >
              载入当前提案
            </button>
          </div>
        )}
        {dirty && (
          <div className="notice warning">
            有未保存修订，已保存在本浏览器。请先保存并核对新预览，才能决定。
          </div>
        )}
        {Object.keys(frozenPrompt).length > 0 && (
          <details className="review-frozen-prompt">
            <summary>查看本次写作的题目与评分要求</summary>
            <PromptPreview data={frozenPrompt} />
          </details>
        )}
        <details className="review-records">
          <summary>来源、原始请求与目标快照</summary>
          <p className="id-line">
            来源 {review.source_actor} · 请求 {review.request_id}
          </p>
          {review.payload.declared_model ? (
            <p>客户端自报模型：{String(review.payload.declared_model)}</p>
          ) : null}
          <div className="diff-columns">
            <div>
              <h4>原始请求</h4>
              <pre>{JSON.stringify(review.original_payload, null, 2)}</pre>
            </div>
            <div>
              <h4>当前有效提案</h4>
              <pre>{JSON.stringify(review.payload, null, 2)}</pre>
            </div>
          </div>
          <h4>目标与评分要求快照</h4>
          <pre>{JSON.stringify(review.target_snapshot, null, 2)}</pre>
        </details>
      </section>
      {pages.length > 0 ? (
        <ReadingLayout
          panel={panel}
          onPanel={onPanel}
          location={pageId}
          locationKey={locationKey}
          className="review-reading"
          evaluationLabel={review.kind === "evaluation" ? "评价" : "提案"}
          paperLabel={review.kind === "prompt" ? "材料" : "原稿"}
          paper={
            <Viewer
              pages={pages}
              selectedPage={pageId}
              title={reviewPaperTitle(review)}
            />
          }
          evaluation={proposal}
        />
      ) : (
        proposal
      )}
      <footer className="review-action-bar">
        <div className="review-decision-hint">
          <strong>{pending ? "核对完成后，决定是否入档" : "审核已结束"}</strong>
          <HelpTip label="入档决定说明">
            通过会执行上方列出的整项变更；驳回不会写入正式档案。有本地修改时，需要先保存修订并核对预览。
          </HelpTip>
        </div>
        {pending ? (
          <>
            <button
              className="primary"
              disabled={busy || dirty || stale || invalid || !showPreview}
              onClick={() => decide("approve")}
            >
              {busy ? "处理中…" : "通过并入档"}
            </button>
            <button
              disabled={busy || dirty || stale || invalid}
              onClick={() => decide("reject")}
            >
              驳回
            </button>
          </>
        ) : (
          <Tag>{statusLabels[review.status]}</Tag>
        )}
        <button disabled={busy} onClick={onNext}>
          下一项
        </button>
        <small className="muted">
          {dirty ? "本地修改已暂存" : `当前有效修订 ${review.revision}`}
        </small>
      </footer>
    </>
  );
}
