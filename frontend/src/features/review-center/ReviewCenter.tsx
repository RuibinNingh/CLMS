import { useEffect, useRef, useState } from "react";
import { go } from "../../app/App";
import { api, errorText, params } from "../../shared/api";
import { useLoad } from "../../shared/hooks";
import type { Paged, Review } from "../../shared/types";
import {
  date,
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  Tag,
} from "../../shared/ui";
import { ReviewDetail } from "./ReviewDetail";
import { hasLocalReviewDraft } from "./reviewDraft";
import { HelpTip } from "../../shared/HelpTip";
import {
  kindLabels,
  statusLabels,
  reviewAction,
  reviewImpact,
  reviewTitle,
} from "./reviewPresentation";
import { refreshReviewCount } from "./PendingReviewBadge";

export function ReviewCenter({ selectedId }: { selectedId: string | null }) {
  const queueRef = useRef<HTMLElement>(null);
  const [status, setStatus] = useState("pending"),
    [kind, setKind] = useState(""),
    [source, setSource] = useState(""),
    [from, setFrom] = useState(""),
    [to, setTo] = useState(""),
    [cursor, setCursor] = useState("");
  const [checked, setChecked] = useState<string[]>([]),
    [batchResult, setBatchResult] = useState<
      { id: string; result?: Review; error?: unknown }[]
    >([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const list = useLoad(
    () =>
      api<Paged<Review>>(
        `/reviews${params({ status, kind, source, from_date: from, to_date: to, cursor, limit: 20 })}`,
      ),
    [status, kind, source, from, to, cursor, selectedId],
  );
  useEffect(() => {
    setChecked([]);
  }, [status, kind, source, from, to, cursor]);
  const selected = selectedId || "";
  useEffect(() => {
    const queue = queueRef.current;
    const item = queue?.querySelector<HTMLElement>("li.selected");
    if (!queue || !item || queue.clientHeight === 0) return;
    const frame = queue.getBoundingClientRect(),
      row = item.getBoundingClientRect();
    if (row.bottom > frame.bottom) queue.scrollTop += row.bottom - frame.bottom;
    else if (row.top < frame.top) queue.scrollTop -= frame.top - row.top;
  }, [selected, list.data]);
  async function batch(decision: "approve" | "reject") {
    const items =
      list.data?.items.filter(
        (item) => checked.includes(item.id) && item.status === "pending",
      ) || [];
    if (!items.length) return;
    if (
      !window.confirm(
        `${decision === "approve" ? "通过并入档" : "驳回"}已选的 ${items.length} 项？仅处理当前已显示摘要的独立提案。`,
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ items: typeof batchResult }>(
        "/reviews/batch",
        {
          items: items.map((item) => ({
            id: item.id,
            expected_revision: item.revision,
            expected_digest: item.effective_digest,
            decision,
          })),
        },
      );
      setBatchResult(result.items);
      setChecked([]);
      list.reload();
      refreshReviewCount();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={`review-center ${selected ? "is-reviewing" : ""}`}>
      <PageHeading
        eyebrow="CLMS · 校阅工作台"
        title="审核中心"
        subtitle="先看清 AI 提交的内容，再决定是否入档。"
        actions={
          <button
            onClick={() => {
              list.reload();
              refreshReviewCount();
            }}
          >
            刷新队列
          </button>
        }
      />
      <div className="review-guide">
        <span>
          <strong>AI 提交提案</strong>
          <span aria-hidden="true"> → </span>你核对内容
          <span aria-hidden="true"> → </span>通过后入档
        </span>
        <HelpTip label="审核流程说明">
          这里显示外部 MCP
          客户端实际提交的提案。只有你点击“通过并入档”后，正式档案才会更新；驳回只结束这项提案。
        </HelpTip>
      </div>
      <section className="panel filters">
        <div className="filter-row">
          <select
            aria-label="审核状态"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setCursor("");
            }}
          >
            <option value="pending">待审核</option>
            <option value="">全部提案与记录</option>
            <option value="processed">全部处理记录</option>
            {Object.entries(statusLabels)
              .filter(([value]) => value !== "pending")
              .map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
          </select>
          <select
            aria-label="操作类型"
            value={kind}
            onChange={(event) => {
              setKind(event.target.value);
              setCursor("");
            }}
          >
            <option value="">全部操作类型</option>
            {Object.entries(kindLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <input
            aria-label="提案来源"
            placeholder="筛选来源"
            value={source}
            onChange={(event) => {
              setSource(event.target.value);
              setCursor("");
            }}
          />
          <input
            aria-label="审核开始日期"
            type="date"
            value={from}
            onChange={(event) => {
              setFrom(event.target.value);
              setCursor("");
            }}
          />
          <input
            aria-label="审核结束日期"
            type="date"
            value={to}
            onChange={(event) => {
              setTo(event.target.value);
              setCursor("");
            }}
          />
        </div>
      </section>
      <ErrorNotice message={error || list.error} retry={list.reload} />
      {batchResult.length > 0 && (
        <div className="panel batch-result">
          <h3>批量处理结果</h3>
          {batchResult.map((item) => (
            <p key={item.id}>
              <code>{item.id}</code> ·{" "}
              {item.error
                ? `未成功：${typeof item.error === "object" ? JSON.stringify(item.error) : String(item.error)}`
                : statusLabels[item.result?.status || ""] || "未取得结果"}{" "}
              {item.result?.status === "conflict" ||
              item.result?.status === "failed" ? (
                <span className="danger-text">
                  {" "}
                  · {JSON.stringify(item.result.result)}；需重新建立提案。
                </span>
              ) : null}
            </p>
          ))}
        </div>
      )}
      <div className={`review-layout ${selected ? "has-selection" : ""}`}>
        <aside ref={queueRef} className="review-queue panel">
          <div className="section-heading">
            <h2>
              {status === "pending"
                ? "待审核"
                : status === ""
                  ? "全部提案"
                  : "处理记录"}
            </h2>
            <Tag>
              {list.data?.total ?? list.data?.items.length ?? 0}
              {list.data?.total == null && list.data?.next_cursor ? "＋" : ""}
            </Tag>
          </div>
          {list.loading && <Loading />}
          {!list.loading && list.data?.items.length === 0 && (
            <Empty title="当前筛选下没有提案">
              <p className="muted">已处理的提案可以在处理记录中查看。</p>
              <button
                onClick={() => {
                  setStatus("");
                  setKind("");
                  setSource("");
                  setFrom("");
                  setTo("");
                  setCursor("");
                }}
              >
                查看全部提案
              </button>
            </Empty>
          )}
          <ul>
            {list.data?.items.map((item) => (
              <li
                key={item.id}
                className={selected === item.id ? "selected" : ""}
              >
                <div className="review-row-heading">
                  {item.status === "pending" && (
                    <input
                      aria-label={`选择提案 ${item.id}`}
                      type="checkbox"
                      checked={checked.includes(item.id)}
                      disabled={hasLocalReviewDraft(item.id, item.payload)}
                      onChange={(event) =>
                        setChecked(
                          event.target.checked
                            ? [...checked, item.id]
                            : checked.filter((id) => id !== item.id),
                        )
                      }
                    />
                  )}
                  <Tag>{reviewAction(item)}</Tag>
                  <Tag tone={item.status === "applied" ? "success" : ""}>
                    {statusLabels[item.status] || item.status}
                  </Tag>
                </div>
                <button
                  className="queue-item"
                  aria-current={selected === item.id ? "true" : undefined}
                  onClick={() => go(`reviews?id=${item.id}`)}
                >
                  <strong>{reviewTitle(item)}</strong>
                  <small className="queue-effect">{reviewImpact(item)}</small>
                  <small>
                    {item.source_actor.startsWith("mcp:")
                      ? "MCP 客户端"
                      : item.source_actor}{" "}
                    · {date(item.created_at)}
                  </small>
                  <small>修订 {item.revision}</small>
                </button>
              </li>
            ))}
          </ul>
          {list.data?.next_cursor && (
            <button onClick={() => setCursor(list.data!.next_cursor!)}>
              下一页队列
            </button>
          )}
          {cursor && <button onClick={() => setCursor("")}>返回第一页</button>}
          {checked.length > 0 && (
            <div className="batch-actions">
              <small>已选 {checked.length} 项</small>
              <button
                className="primary"
                disabled={busy}
                onClick={() => batch("approve")}
              >
                批量通过并入档
              </button>
              <button disabled={busy} onClick={() => batch("reject")}>
                批量驳回
              </button>
            </div>
          )}
        </aside>
        <section className="review-detail">
          {selected ? (
            <ReviewDetail
              key={selected}
              id={selected}
              onDecided={() => {
                list.reload();
                refreshReviewCount();
              }}
              onNext={() => {
                const next = list.data?.items.find(
                  (item) => item.id !== selected && item.status === "pending",
                );
                if (next) go(`reviews?id=${next.id}`);
                else go("reviews");
              }}
            />
          ) : (
            <Empty title="选择一项提案开始审核">
              <p className="muted">
                查看原稿、有效提案和评分要求，再决定是否入档。
              </p>
            </Empty>
          )}
        </section>
      </div>
    </div>
  );
}
