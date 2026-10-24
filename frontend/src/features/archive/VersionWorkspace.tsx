import { useState } from "react";
import { api, errorText } from "../../shared/api";
import { Icon } from "../../shared/Icon";
import { ReadingLayout, type ReadingPanel } from "../../shared/ReadingLayout";
import type { Attempt, Prompt, Version } from "../../shared/types";
import { date, ErrorNotice, Field, Tag } from "../../shared/ui";
import { Viewer } from "../document-viewer/Viewer";
import { EvaluationView } from "../evaluation/EvaluationView";
import { TeacherEvaluation } from "../evaluation/TeacherEvaluation";
import { Comparison } from "./ArchiveTools";

export function VersionWorkspace({
  prompt,
  attempt,
  version,
  onReload,
}: {
  prompt: Prompt;
  attempt: Attempt;
  version: Version;
  onReload: () => void;
}) {
  const [evaluationId, setEvaluationId] = useState("");
  const [pageId, setPageId] = useState("");
  const [locationKey, setLocationKey] = useState(0);
  const [panel, setPanel] = useState<ReadingPanel>("paper");
  const [compareId, setCompareId] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [context, setContext] = useState("");
  const evaluations = version.evaluations;
  const evaluation =
    evaluations.find((item) => item.id === evaluationId) ||
    [...evaluations].reverse().find((item) => !item.voided_at) ||
    evaluations[0];
  const compare = attempt.versions.find(
    (item) => item.id === compareId && item.id !== version.id,
  );
  async function copyContext() {
    const snapshot = attempt.prompt_snapshot;
    const text = `请通过 CLMS MCP 评价这份${snapshot.language === "zh" ? "语文" : "英语"}作文。\n题目：${snapshot.title}\nprompt_id: ${prompt.id}\nattempt_id: ${attempt.id}\nversion_id: ${version.id}\nmanifest_hash: ${version.manifest_hash}\nprompt_snapshot_hash: ${attempt.snapshot_hash}\n页数：${version.manifest.length}\n使用 get_version / get_attempt 获取冻结题目要求，再用 read_asset_pages 按页阅读原稿，提交 propose_evaluation 待审提案。缺页或看不清时标明部分评价与限制，不自行转写全文。评分标准为空时 score=null。正式评价需网页人工审核。`;
    try {
      await navigator.clipboard.writeText(text);
      setError("");
      setCopied(true);
      setContext("");
    } catch {
      setContext(text);
    }
  }
  async function voidRecord(path: string, message: string) {
    if (!window.confirm(message)) return;
    try {
      await api(path, {});
      setError("");
      onReload();
    } catch (reason) {
      setError(errorText(reason));
    }
  }
  return (
    <>
      <div className="section-heading version-heading">
        <div>
          <h2>
            第 {version.version_no} 稿{version.voided_at ? " · 已作废" : ""}
          </h2>
          <small className="muted">
            {version.change_note || "原稿已归档"} · {version.manifest.length} 页
          </small>
        </div>
        <div className="actions">
          <Tag tone={version.status === "evaluated" ? "success" : "warning"}>
            {version.status === "evaluated" ? "已有完整评价" : "待完整评价"}
          </Tag>
          <button
            onClick={copyContext}
            aria-label={copied ? "已复制评价任务" : "复制评价任务"}
            title={copied ? "已复制评价任务" : "复制评价任务"}
          >
            <Icon name="copy" />
            <span className="copy-label">
              {copied ? "已复制评价任务" : "复制评价任务"}
            </span>
          </button>
          {attempt.versions.length > 1 && (
            <select
              aria-label="选择对比版本"
              value={compareId}
              onChange={(event) => setCompareId(event.target.value)}
            >
              <option value="">对比另一稿</option>
              {attempt.versions
                .filter((item) => item.id !== version.id)
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    V{item.version_no}
                    {item.voided_at ? "（作废）" : ""}
                  </option>
                ))}
            </select>
          )}
        </div>
      </div>
      <ErrorNotice message={error} />
      {copied && (
        <p className="task-feedback muted" role="status">
          评价任务已复制，可交给已连接 CLMS 的外部 AI。
        </p>
      )}
      {context && (
        <Field label="评价任务（可手动复制）">
          <textarea readOnly rows={8} value={context} />
        </Field>
      )}
      {compare ? (
        <Comparison left={version} right={compare} />
      ) : (
        <ReadingLayout
          panel={panel}
          onPanel={setPanel}
          location={pageId}
          locationKey={locationKey}
          paper={
            <Viewer
              pages={version.manifest}
              selectedPage={pageId}
              title={`V${version.version_no} 原稿`}
            />
          }
          evaluation={
            <section className="panel evaluation-panel">
              <div className="section-heading">
                <h2>稿件评价</h2>
                <Tag>V{version.version_no}</Tag>
              </div>
              {evaluations.length > 0 && (
                <details className="evaluation-history">
                  <summary>评价历史 · {evaluations.length} 次</summary>
                  <select
                    aria-label="选择评价历史"
                    value={evaluation?.id || ""}
                    onChange={(event) => setEvaluationId(event.target.value)}
                  >
                    {[...evaluations].reverse().map((item, index) => (
                      <option key={item.id} value={item.id}>
                        第 {evaluations.length - index} 次 ·{" "}
                        {date(item.created_at)}
                        {item.voided_at ? "（作废）" : ""}
                        {item.payload.coverage.scope === "partial"
                          ? " · 部分"
                          : ""}
                      </option>
                    ))}
                  </select>
                </details>
              )}
              {evaluation ? (
                <>
                  {evaluation.voided_at && (
                    <div className="notice warning">
                      此评价已作废，保留用于历史查阅。
                    </div>
                  )}
                  <EvaluationView
                    evaluation={evaluation}
                    onPage={(id) => {
                      setPageId(id);
                      setLocationKey((value) => value + 1);
                      setPanel("paper");
                    }}
                  />
                  {!evaluation.voided_at && (
                    <details>
                      <summary>管理这次评价</summary>
                      <button
                        className="quiet danger-text"
                        onClick={() =>
                          voidRecord(
                            `/evaluations/${evaluation.id}/void`,
                            "作废这次评价？历史记录仍然保留。",
                          )
                        }
                      >
                        作废评价
                      </button>
                    </details>
                  )}
                </>
              ) : (
                <div className="evaluation-empty">
                  <Icon name="review" />
                  <h3>这份稿件还没有正式评价</h3>
                  <p className="muted">
                    复制评价任务交给外部 AI，或在下方记录教师评价。
                  </p>
                </div>
              )}
              {!version.voided_at && (
                <TeacherEvaluation
                  version={version}
                  attempt={attempt}
                  onSaved={onReload}
                />
              )}
            </section>
          }
        />
      )}
      <details className="version-information">
        <summary>稿件信息与管理</summary>
        <p className="id-line muted">
          稿件 {version.id}
          <br />
          原稿清单哈希 {version.manifest_hash}
          <br />
          题目快照哈希 {attempt.snapshot_hash}
        </p>
        {!version.voided_at && (
          <button
            className="quiet danger-text"
            onClick={() =>
              voidRecord(
                `/versions/${version.id}/void`,
                "作废这份稿件？原件与历史评价仍会保留。",
              )
            }
          >
            作废稿件
          </button>
        )}
      </details>
    </>
  );
}
