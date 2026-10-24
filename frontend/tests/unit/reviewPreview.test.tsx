import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { ProposalContent } from "../../src/features/review-center/ProposalContent";
import { HelpTip } from "../../src/shared/HelpTip";
import {
  reviewImpact,
  reviewPages,
} from "../../src/features/review-center/reviewPresentation";
import type { Review, Version } from "../../src/shared/types";

vi.mock("../../src/shared/categories", () => ({
  allCategories: () => Promise.resolve({ items: [] }),
}));
afterEach(cleanup);
function proposal(
  kind: Review["kind"],
  payload: Record<string, unknown>,
  before?: unknown,
): Review {
  return {
    id: "test",
    kind,
    payload,
    target_snapshot: before ? { before } : {},
    original_payload: payload,
    source_actor: "mcp:test",
    request_id: "test",
    revision: 1,
    original_digest: "a",
    effective_digest: "b",
    created_at: "2026-10-11T00:00:00Z",
    status: "pending",
    result: null,
  };
}
it("makes a text-only prompt readable and keeps absent original material and scoring explicit", () => {
  const review = proposal("prompt", {
    action: "create",
    title: "熟悉的陌生地",
    language: "zh",
    instructions:
      "阅读下面的材料，根据要求写作。\n<img src=x onerror=alert(1)>",
    requirements: "不少于 800 字。",
    source_note: "满分 60 分，未提供具体评分细则。",
  });
  const { container } = render(
    <ProposalContent review={review} payload={review.payload} />,
  );
  expect(screen.getByText("熟悉的陌生地")).toBeTruthy();
  expect(screen.getByText("不少于 800 字。")).toBeTruthy();
  expect(screen.getByText("未提供评分细则")).toBeTruthy();
  expect(screen.getByText("未附原始材料图")).toBeTruthy();
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("pre")).toBeNull();
});
it("compares changed prompt fields while retaining omitted rubric and materials from the frozen baseline", () => {
  const material = [{ page_id: "material", rotation: 90 }];
  const review = proposal(
    "prompt",
    { action: "update", requirements: "至少 800 字。" },
    {
      title: "原题目",
      requirements: "至少 600 字。",
      language: "zh",
      materials: material,
      rubric: {
        max_score: 60,
        aggregation: "none",
        criteria: "整体评价",
        dimensions: [],
      },
    },
  );
  render(<ProposalContent review={review} payload={review.payload} />);
  const changed = screen
    .getByText("写作要求")
    .closest(".proposal-field") as HTMLElement;
  expect(within(changed).getByText("至少 600 字。")).toBeTruthy();
  expect(within(changed).getByText("至少 800 字。")).toBeTruthy();
  expect(screen.getByText("总分上限 60 分")).toBeTruthy();
  expect(reviewPages(review, review.payload)).toEqual(material);
  expect(reviewPages(review, { ...review.payload, materials: [] })).toEqual([]);
  cleanup();
  render(
    <ProposalContent
      review={review}
      payload={{ ...review.payload, rubric: null }}
    />,
  );
  expect(screen.getByText("未提供评分细则")).toBeTruthy();
});
it("shows the incoming revision pages rather than the parent manuscript", () => {
  const oldPages = [{ page_id: "old", rotation: 0 }],
    newPages = [{ page_id: "new", rotation: 180 }];
  const review = proposal(
    "revision",
    { pages: newPages, change_note: "调整结尾" },
    { version_no: 2, manifest: oldPages },
  );
  expect(
    reviewPages(review, review.payload, { manifest: oldPages } as Version),
  ).toEqual(newPages);
  render(<ProposalContent review={review} payload={review.payload} />);
  expect(screen.getByText("调整结尾")).toBeTruthy();
  expect(screen.getByText("基于 V2 的修改稿")).toBeTruthy();
});
it("expands all parts of a combined submission and explains their atomic effect", () => {
  const review = proposal("submission", {
    prompt: {
      title: "新题目",
      language: "en",
      instructions: "Describe a place.",
    },
    pages: [{ page_id: "new", rotation: 0 }],
    inline_categories: [{ name: "生活观察", language_scope: "en" }],
    reflection: "观察更多细节",
    duration_minutes: 0,
  });
  render(<ProposalContent review={review} payload={review.payload} />);
  expect(screen.getByText("新题目")).toBeTruthy();
  expect(screen.getByText("生活观察")).toBeTruthy();
  expect(screen.getByText("观察更多细节")).toBeTruthy();
  expect(screen.getByText("0 分钟")).toBeTruthy();
  expect(reviewImpact(review)).toContain("整项一起入档");
});
it("shows category archiving and reflection changes, and never treats partial feedback as complete", () => {
  const category = proposal(
    "category",
    { action: "archive" },
    { name: "观察", archived_at: null },
  );
  render(<ProposalContent review={category} payload={category.payload} />);
  expect(screen.getByText("停用，保留历史引用")).toBeTruthy();
  cleanup();
  const reflection = proposal(
    "reflection",
    { reflection: "新的反思" },
    { reflection: "原来的反思" },
  );
  render(<ProposalContent review={reflection} payload={reflection.payload} />);
  expect(screen.getByText("原来的反思")).toBeTruthy();
  expect(screen.getByText("新的反思")).toBeTruthy();
  expect(
    reviewImpact(
      proposal("evaluation", { coverage: { scope: "partial" }, score: null }),
    ),
  ).toContain("仍待完整评价");
});
it("opens help on keyboard focus and click, dismisses with Escape and outside clicks", () => {
  render(
    <>
      <HelpTip label="审核帮助">只有通过后才入档。</HelpTip>
      <button>外部按钮</button>
    </>,
  );
  const trigger = screen.getByRole("button", { name: "审核帮助" });
  fireEvent.focus(trigger);
  expect(screen.getByRole("tooltip").textContent).toBe("只有通过后才入档。");
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.click(trigger);
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  fireEvent.pointerDown(screen.getByRole("button", { name: "外部按钮" }));
  expect(screen.queryByRole("tooltip")).toBeNull();
});
