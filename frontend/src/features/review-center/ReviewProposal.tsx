import type {
  EvaluationPayload,
  PageRef,
  Review,
  Version,
} from "../../shared/types";
import { ErrorNotice } from "../../shared/ui";
import { EvaluationEditor } from "../evaluation/EvaluationEditor";
import { EvaluationView } from "../evaluation/EvaluationView";
import { GenericEditor } from "./GenericEditor";
import { ProposalContent } from "./ProposalContent";
import { HelpTip } from "../../shared/HelpTip";

export function ReviewProposal({
  review,
  payload,
  pages,
  version,
  versionError,
  onReloadVersion,
  editing,
  onToggleEditing,
  onChange,
  onInvalid,
  onPage,
  onSave,
  busy,
  dirty,
  stale,
  invalid,
}: {
  review: Review;
  payload: Record<string, unknown>;
  pages: PageRef[];
  version: Version | null | undefined;
  versionError: string;
  onReloadVersion: () => void;
  editing: boolean;
  onToggleEditing: () => void;
  onChange: (payload: Record<string, unknown>) => void;
  onInvalid: (invalid: boolean) => void;
  onPage: (id: string) => void;
  onSave: () => void;
  busy: boolean;
  dirty: boolean;
  stale: boolean;
  invalid: boolean;
}) {
  const pending = review.status === "pending";
  const versionId = String(
    review.payload.version_id ||
      review.target_snapshot.version_id ||
      review.payload.parent_version_id ||
      "",
  );
  return (
    <section className="panel review-proposal">
      <div className="section-heading">
        <div className="actions">
          <h2>{editing ? "修订提案" : "有效提案预览"}</h2>
          <HelpTip label="有效提案说明">
            通过时执行的是已保存的当前修订。你可以先修改内容、保存修订，再核对新的预览；原始请求会一直保留。
          </HelpTip>
        </div>
        {pending && (
          <button onClick={onToggleEditing}>
            {editing ? "查看本地预览" : "修订提案"}
          </button>
        )}
      </div>
      <ErrorNotice message={versionError} retry={onReloadVersion} />
      {editing && pending ? (
        review.kind === "evaluation" ? (
          <EvaluationEditor
            value={payload as unknown as EvaluationPayload}
            onChange={(value) =>
              onChange(value as unknown as Record<string, unknown>)
            }
            pages={pages}
            rubric={version?.prompt_snapshot?.rubric}
          />
        ) : (
          <GenericEditor
            kind={review.kind}
            payload={payload}
            draftKey={`clms-review-fields-${review.id}-${review.revision}`}
            onInvalidChange={onInvalid}
            onChange={onChange}
          />
        )
      ) : review.kind === "evaluation" ? (
        <EvaluationView
          onPage={onPage}
          evaluation={{
            id: review.id,
            version_id: versionId,
            payload: payload as unknown as EvaluationPayload,
            source: review.source_actor,
            created_at: review.created_at,
            supersedes_id: null,
            voided_at: null,
          }}
        />
      ) : (
        <ProposalContent review={review} payload={payload} version={version} />
      )}
      <details className="review-raw-payload">
        <summary>
          {dirty ? "查看本地预览 JSON（尚未保存）" : "查看有效提案 JSON"}
        </summary>
        <pre>{JSON.stringify(payload, null, 2)}</pre>
      </details>
      {pending && dirty && (
        <button
          className="primary"
          disabled={busy || stale || invalid}
          onClick={onSave}
        >
          保存修订
        </button>
      )}
      {!pending && review.result && (
        <div
          className={`notice ${review.status === "applied" ? "success" : review.status === "conflict" || review.status === "failed" ? "error" : ""}`}
        >
          <h3>真实执行结果</h3>
          <pre>{JSON.stringify(review.result, null, 2)}</pre>
          {review.result.prompt_id || version?.prompt_id ? (
            <a
              className="button"
              href={`#/prompt/${review.result.prompt_id || version?.prompt_id}${review.result.version_id || versionId ? `?version=${review.result.version_id || versionId}` : ""}`}
            >
              打开对应档案
            </a>
          ) : null}
        </div>
      )}
    </section>
  );
}
