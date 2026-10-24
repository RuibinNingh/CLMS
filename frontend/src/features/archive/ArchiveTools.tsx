import { useState } from "react";
import { api, params } from "../../shared/api";
import { useLoad } from "../../shared/hooks";
import type { Paged, Version } from "../../shared/types";
import { date, ErrorNotice } from "../../shared/ui";
import { Viewer } from "../document-viewer/Viewer";
import { EvaluationView } from "../evaluation/EvaluationView";
export function Comparison({ left, right }: { left: Version; right: Version }) {
  const [selected, setSelected] = useState(left.id);
  return (
    <>
      <div
        className="comparison-switch segments"
        role="group"
        aria-label="对比稿件"
      >
        {[left, right].map((version) => (
          <button
            key={version.id}
            aria-pressed={selected === version.id}
            onClick={() => setSelected(version.id)}
          >
            V{version.version_no} 原稿
          </button>
        ))}
      </div>
      <div className="comparison-layout" data-selected={selected}>
        {[left, right].map((version) => (
          <div
            className="comparison-side"
            data-active={selected === version.id}
            key={version.id}
          >
            <ComparisonSide version={version} />
          </div>
        ))}
      </div>
    </>
  );
}
function ComparisonSide({ version }: { version: Version }) {
  const [pageId, setPageId] = useState("");
  return (
    <div className="comparison-content">
      <Viewer
        pages={version.manifest}
        selectedPage={pageId}
        title={`V${version.version_no} 原稿`}
      />
      {version.evaluations
        .filter((item) => !item.voided_at)
        .slice(-1)
        .map((evaluation) => (
          <section className="panel evaluation-panel" key={evaluation.id}>
            <EvaluationView evaluation={evaluation} onPage={setPageId} />
          </section>
        ))}
    </div>
  );
}
export function History({ promptId }: { promptId: string }) {
  const [cursor, setCursor] = useState("");
  const history = useLoad(
    () =>
      api<Paged<Record<string, unknown>>>(
        `/history${params({ prompt_id: promptId, cursor, limit: 20 })}`,
      ),
    [promptId, cursor],
  );
  return (
    <details className="panel history">
      <summary>关联操作记录</summary>
      <ErrorNotice message={history.error} retry={history.reload} />
      {history.data?.items.map((event, index) => (
        <p key={String(event.id || index)}>
          <strong>{String(event.action || "")}</strong> ·{" "}
          {String(event.actor || "")} · {date(String(event.created_at || ""))}
        </p>
      ))}
      <div className="actions">
        {history.data?.next_cursor && (
          <button onClick={() => setCursor(history.data!.next_cursor!)}>
            下一页操作记录
          </button>
        )}
        {cursor && <button onClick={() => setCursor("")}>返回首批记录</button>}
      </div>
    </details>
  );
}
