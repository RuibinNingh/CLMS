import type {
  EvaluationPayload,
  Issue,
  IssueKind,
  PageRef,
  Rubric,
} from "../../shared/types";
import { Field } from "../../shared/ui";
import { ListField } from "../../shared/ListField";
import { issueLabels } from "./EvaluationView";

export function createEvaluation(
  versionId: string,
  manifestHash: string,
  snapshotHash: string,
  pages: PageRef[],
): EvaluationPayload {
  return {
    schema_version: 1,
    version_id: versionId,
    expected_manifest_hash: manifestHash,
    expected_prompt_snapshot_hash: snapshotHash,
    coverage: {
      reviewed_page_ids: pages.map((page) => page.page_id),
      scope: "full",
      limitations: [],
    },
    summary: "",
    strengths: [],
    score: null,
    issues: [],
    next_actions: [],
    commentary_markdown: "",
    declared_model: null,
  };
}
const lines = (text: string) =>
  text
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
export function EvaluationEditor({
  value,
  onChange,
  pages,
  rubric,
}: {
  value: EvaluationPayload;
  onChange: (value: EvaluationPayload) => void;
  pages: PageRef[];
  rubric?: Rubric | null;
}) {
  const update = <K extends keyof EvaluationPayload>(
    field: K,
    next: EvaluationPayload[K],
  ) => onChange({ ...value, [field]: next });
  const issueUpdate = (index: number, next: Issue) =>
    update(
      "issues",
      value.issues.map((item, number) => (number === index ? next : item)),
    );
  return (
    <div className="evaluation-editor">
      <Field label="总体评价">
        <textarea
          required
          rows={4}
          value={value.summary}
          onChange={(event) => update("summary", event.target.value)}
        />
      </Field>
      <div className="form-row">
        <Field label="评价覆盖">
          <select
            value={value.coverage.scope}
            onChange={(event) =>
              update("coverage", {
                ...value.coverage,
                scope: event.target.value as "full" | "partial",
              })
            }
          >
            <option value="full">完整评价</option>
            <option value="partial">部分评价</option>
          </select>
        </Field>
        <ListField
          label="覆盖限制（每行一项）"
          value={value.coverage.limitations}
          onChange={(limitations) =>
            update("coverage", {
              ...value.coverage,
              limitations,
            })
          }
        />
      </div>
      <fieldset>
        <legend>已评价页面</legend>
        <div className="check-list">
          {pages.map((page, index) => (
            <label key={`${page.page_id}-${index}`}>
              <input
                type="checkbox"
                checked={value.coverage.reviewed_page_ids.includes(
                  page.page_id,
                )}
                onChange={(event) =>
                  update("coverage", {
                    ...value.coverage,
                    reviewed_page_ids: event.target.checked
                      ? [...value.coverage.reviewed_page_ids, page.page_id]
                      : value.coverage.reviewed_page_ids.filter(
                          (id) => id !== page.page_id,
                        ),
                  })
                }
              />
              第 {index + 1} 页
            </label>
          ))}
        </div>
      </fieldset>
      <div className="form-row">
        <ListField
          label="具体优点（每行一项）"
          value={value.strengths}
          onChange={(strengths) => update("strengths", strengths)}
        />
        <ListField
          label="下一步行动（每行一项）"
          max={3}
          value={value.next_actions}
          onChange={(actions) => update("next_actions", actions)}
        />
      </div>
      <details open={Boolean(value.score)}>
        <summary>数值评分（可选）</summary>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={Boolean(value.score)}
            disabled={!rubric && !value.score}
            onChange={(event) =>
              update(
                "score",
                event.target.checked && rubric
                  ? {
                      value: 0,
                      max_value: rubric.max_score,
                      rubric_snapshot: rubric,
                      dimensions: rubric.dimensions.map((dimension) => ({
                        name: dimension.name,
                        max_value: dimension.max_score,
                        value: 0,
                      })),
                    }
                  : null,
              )
            }
          />
          保存数值评分
        </label>
        {!rubric && !value.score && (
          <p className="muted">
            当前题目未提供满分与评分标准，评价仍可以保存。
          </p>
        )}
        {value.score && (
          <>
            <Field label={`得分 / ${value.score.max_value}`}>
              <input
                type="number"
                min="0"
                max={value.score.max_value}
                step="any"
                inputMode="decimal"
                value={value.score.value}
                onChange={(event) =>
                  update("score", {
                    ...value.score!,
                    value: Number(event.target.value),
                  })
                }
              />
            </Field>
            {value.score.dimensions.map((dimension, index) => (
              <Field
                key={index}
                label={`${dimension.name} / ${dimension.max_value}`}
              >
                <input
                  type="number"
                  min="0"
                  max={dimension.max_value}
                  step="any"
                  value={dimension.value}
                  onChange={(event) =>
                    update("score", {
                      ...value.score!,
                      dimensions: value.score!.dimensions.map((item, number) =>
                        number === index
                          ? { ...item, value: Number(event.target.value) }
                          : item,
                      ),
                    })
                  }
                />
              </Field>
            ))}
          </>
        )}
      </details>
      <section>
        <div className="section-heading">
          <h3>结构化诊断</h3>
          <button
            type="button"
            onClick={() =>
              update("issues", [
                ...value.issues,
                {
                  kind: "improvement",
                  dimension: "",
                  location: {
                    page_id: pages[0]?.page_id || "",
                    description: "",
                    bbox: null,
                  },
                  quote: null,
                  reason: "",
                  suggestion: "",
                },
              ])
            }
          >
            ＋ 添加诊断
          </button>
        </div>
        {value.issues.map((issue, index) => (
          <div className="issue-editor" key={index}>
            <div className="form-row">
              <Field label={`诊断 ${index + 1} 类型`}>
                <select
                  value={issue.kind}
                  onChange={(event) =>
                    issueUpdate(index, {
                      ...issue,
                      kind: event.target.value as IssueKind,
                    })
                  }
                >
                  {Object.entries(issueLabels).map(([kind, label]) => (
                    <option key={kind} value={kind}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="诊断维度">
                <input
                  required
                  value={issue.dimension}
                  onChange={(event) =>
                    issueUpdate(index, {
                      ...issue,
                      dimension: event.target.value,
                    })
                  }
                />
              </Field>
            </div>
            <div className="form-row">
              <Field label="对应页面">
                <select
                  value={issue.location.page_id}
                  onChange={(event) =>
                    issueUpdate(index, {
                      ...issue,
                      location: {
                        ...issue.location,
                        page_id: event.target.value,
                      },
                    })
                  }
                >
                  {pages.map((page, number) => (
                    <option key={page.page_id} value={page.page_id}>
                      第 {number + 1} 页
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="页内位置描述">
                <input
                  value={issue.location.description}
                  onChange={(event) =>
                    issueUpdate(index, {
                      ...issue,
                      location: {
                        ...issue.location,
                        description: event.target.value,
                      },
                    })
                  }
                />
              </Field>
            </div>
            <Field label="局部引用（可选）">
              <input
                value={issue.quote || ""}
                onChange={(event) =>
                  issueUpdate(index, {
                    ...issue,
                    quote: event.target.value || null,
                  })
                }
              />
            </Field>
            <Field label="判断理由">
              <textarea
                required
                value={issue.reason}
                onChange={(event) =>
                  issueUpdate(index, { ...issue, reason: event.target.value })
                }
              />
            </Field>
            <Field label="修改建议">
              <textarea
                value={issue.suggestion}
                onChange={(event) =>
                  issueUpdate(index, {
                    ...issue,
                    suggestion: event.target.value,
                  })
                }
              />
            </Field>
            <button
              type="button"
              className="quiet danger-text"
              onClick={() =>
                update(
                  "issues",
                  value.issues.filter((_, number) => number !== index),
                )
              }
            >
              移除此诊断
            </button>
          </div>
        ))}
      </section>
      <Field label="完整评语">
        <textarea
          rows={5}
          value={value.commentary_markdown}
          onChange={(event) =>
            update("commentary_markdown", event.target.value)
          }
        />
      </Field>
    </div>
  );
}
