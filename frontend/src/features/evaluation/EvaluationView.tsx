import type {
  Evaluation,
  EvaluationPayload,
  IssueKind,
} from "../../shared/types";
import { date, Tag } from "../../shared/ui";
import { Icon } from "../../shared/Icon";

export const issueLabels: Record<IssueKind, string> = {
  error: "明确问题",
  improvement: "优化建议",
  uncertain: "待确认",
};
export function isComplete(payload: EvaluationPayload) {
  return payload.coverage.scope === "full";
}
export function EvaluationView({
  evaluation,
  onPage,
}: {
  evaluation: Evaluation;
  onPage?: (id: string) => void;
}) {
  const payload = evaluation.payload;
  return (
    <article className="evaluation-view">
      <div className="section-heading">
        <h3>
          {evaluation.source === "web" ||
          evaluation.source === "human" ||
          evaluation.source.startsWith("web:")
            ? "教师 / 人工评价"
            : "AI 参考评价"}
        </h3>
        <Tag tone={isComplete(payload) ? "success" : "warning"}>
          {isComplete(payload) ? "完整评价" : "部分评价"}
        </Tag>
      </div>
      <small className="muted">{date(evaluation.created_at)}</small>
      {payload.score ? (
        <p className="score">
          <strong>{payload.score.value}</strong> / {payload.score.max_value}
          <small>
            依据：{payload.score.rubric_snapshot.criteria || "保存的评分标准"}
          </small>
        </p>
      ) : (
        <p className="muted">未提供数值评分</p>
      )}
      <section className="evaluation-summary">
        <h4>总体评价</h4>
        <p className="preserve-lines">{payload.summary}</p>
      </section>
      {payload.coverage.limitations.length > 0 && (
        <div className="notice warning">
          <strong>覆盖与限制</strong>
          <ul>
            {payload.coverage.limitations.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {payload.strengths.length > 0 && (
        <section>
          <h4>值得保留</h4>
          <ul>
            {payload.strengths.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </section>
      )}
      {(["error", "improvement", "uncertain"] as IssueKind[]).map((kind) => {
        const issues = payload.issues.filter((issue) => issue.kind === kind);
        return issues.length ? (
          <section className={`issue-section ${kind}`} key={kind}>
            <h4>
              {issueLabels[kind]} <small>{issues.length}</small>
            </h4>
            {issues.map((issue, index) => (
              <div className="issue" key={index}>
                <strong>{issue.dimension}</strong>
                {onPage ? (
                  <button
                    className="quiet location"
                    onClick={() => onPage?.(issue.location.page_id)}
                  >
                    <Icon name="locate" />{" "}
                    {issue.location.description || "查看对应原稿页"}
                  </button>
                ) : (
                  <span className="muted">
                    {issue.location.description || "对应原稿页"}
                  </span>
                )}
                {issue.quote && <blockquote>{issue.quote}</blockquote>}
                <p>{issue.reason}</p>
                <p className="muted">{issue.suggestion}</p>
              </div>
            ))}
          </section>
        ) : null;
      })}
      {payload.next_actions.length > 0 && (
        <section>
          <h4>接下来先做</h4>
          <ol>
            {payload.next_actions.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ol>
        </section>
      )}
      {payload.commentary_markdown && (
        <details>
          <summary>完整评语</summary>
          <div className="preserve-lines">{payload.commentary_markdown}</div>
        </details>
      )}
      <details className="evaluation-metadata">
        <summary>评价记录信息</summary>
        <p className="id-line muted">
          来源：{evaluation.source}
          <br />
          评价 ID：{evaluation.id}
          <br />
          稿件 ID：{evaluation.version_id}
        </p>
        {payload.compared_version_ids?.length ? (
          <p className="id-line muted">
            对比版本：{payload.compared_version_ids.join("、")}
          </p>
        ) : null}
      </details>
    </article>
  );
}
