import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { GenericEditor } from "../../src/features/review-center/GenericEditor";
import { reviewChanges } from "../../src/features/review-center/reviewDraft";

afterEach(() => {
  cleanup();
  localStorage.clear();
});
function EditableProposal({
  kind,
  original,
  invalid,
}: {
  kind: string;
  original: Record<string, unknown>;
  invalid: (invalid: boolean) => void;
}) {
  const [payload, setPayload] = useState(original);
  return (
    <>
      <GenericEditor
        kind={kind}
        payload={payload}
        draftKey="test-review-fields"
        onChange={setPayload}
        onInvalidChange={invalid}
      />
      <output aria-label="修订差异">
        {JSON.stringify(reviewChanges(kind, original, payload))}
      </output>
    </>
  );
}
it("lets a reviewer add a missing category description without changing untouched defaults or identity", () => {
  const invalid = vi.fn();
  const original = {
    action: "update",
    category_id: "category-1",
    expected_revision: 4,
    name: "现有分类",
  };
  render(
    <EditableProposal kind="category" original={original} invalid={invalid} />,
  );
  expect(screen.getByLabelText("修订差异").textContent).toBe("{}");
  expect(localStorage.length).toBe(0);
  fireEvent.change(
    screen.getByRole("textbox", { name: "分类说明" }),
    { target: { value: "补充人工说明" } },
  );
  expect(JSON.parse(screen.getByLabelText("修订差异").textContent!)).toEqual({
    description: "补充人工说明",
  });
  expect(original).toEqual({
    action: "update",
    category_id: "category-1",
    expected_revision: 4,
    name: "现有分类",
  });
  expect(invalid).not.toHaveBeenCalledWith(true);
});
it("shows absent prompt rubric/material fields as valid placeholders and only submits deliberate edits", () => {
  const invalid = vi.fn();
  const original = {
    action: "update",
    prompt_id: "prompt-1",
    expected_revision: 3,
    title: "原题目",
  };
  render(
    <EditableProposal kind="prompt" original={original} invalid={invalid} />,
  );
  expect(screen.getByLabelText("修订差异").textContent).toBe("{}");
  expect(
    (screen.getByRole("textbox", { name: /评分标准/ }) as HTMLTextAreaElement)
      .value,
  ).toBe("null");
  expect(
    (
      screen.getByRole("textbox", {
        name: /题目材料页清单/,
      }) as HTMLTextAreaElement
    ).value,
  ).toBe("[]");
  expect(invalid).not.toHaveBeenCalledWith(true);
  fireEvent.change(
    screen.getByRole("textbox", { name: "题目说明" }),
    { target: { value: "补充当次提案说明" } },
  );
  expect(JSON.parse(screen.getByLabelText("修订差异").textContent!)).toEqual({
    instructions: "补充当次提案说明",
  });
  expect(localStorage.getItem("test-review-fields-rubric")).toBeNull();
});
it("keeps an existing submission prompt target immutable in the UI and its change whitelist", () => {
  const original = {
    prompt_id: "existing-prompt",
    prompt: null,
    inline_categories: [],
    pages: [{ page_id: "page-1", rotation: 0 }],
    reflection: "",
  };
  render(
    <EditableProposal
      kind="submission"
      original={original}
      invalid={vi.fn()}
    />,
  );
  expect(screen.queryByRole("textbox", { name: /新题目/ })).toBeNull();
  expect(screen.queryByRole("textbox", { name: /内联新分类/ })).toBeNull();
  expect(
    reviewChanges("submission", original, {
      ...original,
      prompt_id: "replacement",
      prompt: { title: "另一个题目" },
      inline_categories: [{ name: "插入分类" }],
      reflection: "人工反思",
    }),
  ).toEqual({ reflection: "人工反思" });
});
