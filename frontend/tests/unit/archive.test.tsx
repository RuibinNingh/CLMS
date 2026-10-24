import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { movePage } from "../../src/features/submission/PageUploader";
import { createEvaluation } from "../../src/features/evaluation/EvaluationEditor";
import { EvaluationView } from "../../src/features/evaluation/EvaluationView";
import { reviewChanges } from "../../src/features/review-center/ReviewDetail";
import { useDraft } from "../../src/shared/hooks";
import type { Evaluation } from "../../src/shared/types";

afterEach(() => {
  cleanup();
  localStorage.clear();
});
describe("archive evidence and review boundaries", () => {
  it("reorders mixed PDF/image pages without changing source mappings", () => {
    const pages = [
      { page_id: "pdf-2", source_page: 2, asset_id: "pdf", rotation: 90 },
      { page_id: "image", source_page: 1, asset_id: "photo", rotation: 0 },
    ];
    const moved = movePage(pages, 0, 1);
    expect(
      moved.map((page) => [page.asset_id, page.source_page, page.rotation]),
    ).toEqual([
      ["photo", 1, 0],
      ["pdf", 2, 90],
    ]);
    expect(pages[0].page_id).toBe("pdf-2");
  });
  it("binds teacher evaluation to the exact manifest and frozen prompt", () => {
    const payload = createEvaluation("v1", "manifest-1", "snapshot-1", [
      { page_id: "p1", rotation: 0 },
    ]);
    expect(payload.version_id).toBe("v1");
    expect(payload.expected_manifest_hash).toBe("manifest-1");
    expect(payload.expected_prompt_snapshot_hash).toBe("snapshot-1");
    expect(payload.score).toBeNull();
    expect(payload.coverage.reviewed_page_ids).toEqual(["p1"]);
  });
  it("shows partial evaluation and uncertain judgement without converting null score to zero", () => {
    const payload = createEvaluation("v1", "hash", "snapshot", [
      { page_id: "p1", rotation: 0 },
    ]);
    payload.coverage = {
      scope: "partial",
      reviewed_page_ids: ["p1"],
      limitations: ["第二页未读取"],
    };
    payload.summary = "需结合第二页判断。";
    payload.issues = [
      {
        kind: "uncertain",
        dimension: "字迹",
        location: { page_id: "p1", description: "首段", bbox: null },
        quote: null,
        reason: "字迹不清",
        suggestion: "请确认",
      },
    ];
    const evaluation: Evaluation = {
      id: "evaluation-1",
      version_id: "v1",
      payload,
      source: "mcp:key",
      created_at: "2026-10-10T10:00:00Z",
      supersedes_id: null,
      voided_at: null,
    };
    render(<EvaluationView evaluation={evaluation} />);
    expect(screen.getByText("部分评价")).toBeTruthy();
    expect(screen.getByText("未提供数值评分")).toBeTruthy();
    expect(screen.getByText(/待确认/)).toBeTruthy();
    expect(screen.getByText("第二页未读取")).toBeTruthy();
  });
  it("only sends editable comments, keeping version identity and hashes immutable", () => {
    const original = {
      version_id: "v1",
      expected_manifest_hash: "h1",
      summary: "原评语",
      source_actor: "mcp:a",
    };
    const edited = {
      ...original,
      version_id: "v2",
      expected_manifest_hash: "h2",
      summary: "人工修订",
      source_actor: "web:admin",
    };
    expect(reviewChanges("evaluation", original, edited)).toEqual({
      summary: "人工修订",
    });
  });
  it("escapes user commentary and never interprets markdown as executable HTML", () => {
    const payload = createEvaluation("v1", "hash", "snapshot", []);
    payload.summary = "<img src=x onerror=alert(1)>";
    payload.commentary_markdown = "<script>window.hacked=true</script>";
    const { container } = render(
      <EvaluationView
        evaluation={{
          id: "e",
          version_id: "v1",
          payload,
          source: "mcp:a",
          created_at: "2026-10-10T00:00:00Z",
          supersedes_id: null,
          voided_at: null,
        }}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(payload.summary)).toBeTruthy();
  });
  it("persists an edit synchronously and restores it after navigation/remount", () => {
    function DraftField() {
      const draft = useDraft("review-draft", { summary: "" });
      return (
        <input
          aria-label="draft"
          value={draft.value.summary}
          onChange={(event) => draft.setValue({ summary: event.target.value })}
        />
      );
    }
    const first = render(<DraftField />);
    fireEvent.change(screen.getByLabelText("draft"), {
      target: { value: "未保存的人工修改" },
    });
    expect(JSON.parse(localStorage.getItem("review-draft")!).summary).toBe(
      "未保存的人工修改",
    );
    first.unmount();
    render(<DraftField />);
    expect((screen.getByLabelText("draft") as HTMLInputElement).value).toBe(
      "未保存的人工修改",
    );
  });
});
