import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  PageUploader,
  mergePages,
} from "../../src/features/submission/PageUploader";
import { ListField } from "../../src/shared/ListField";
import {
  clearReviewDraft,
  hasLocalReviewDraft,
} from "../../src/features/review-center/reviewDraft";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});
it("allows a newline while editing structured strengths", () => {
  function Editor() {
    const [value, setValue] = useState<string[]>([]);
    return <ListField label="优点" value={value} onChange={setValue} />;
  }
  render(<Editor />);
  fireEvent.change(screen.getByLabelText("优点"), {
    target: { value: "第一项\n" },
  });
  expect((screen.getByLabelText("优点") as HTMLTextAreaElement).value).toBe(
    "第一项\n",
  );
  fireEvent.change(screen.getByLabelText("优点"), {
    target: { value: "第一项\n第二项" },
  });
  expect((screen.getByLabelText("优点") as HTMLTextAreaElement).value).toBe(
    "第一项\n第二项",
  );
});
it("merges a late upload into the current page list instead of resurrecting a deleted page", async () => {
  let complete!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          complete = resolve;
        }),
    ),
  );
  const changeBefore = vi.fn(),
    changeAfter = vi.fn(),
    busy = vi.fn();
  const uploader = render(
    <PageUploader
      label="上传"
      pages={[{ page_id: "deleted", rotation: 0 }]}
      onChange={changeBefore}
      onBusyChange={busy}
    />,
  );
  fireEvent.change(screen.getByLabelText("上传"), {
    target: {
      files: [new File(["pixels"], "page.png", { type: "image/png" })],
    },
  });
  uploader.rerender(
    <PageUploader
      label="上传"
      pages={[{ page_id: "kept", rotation: 90 }]}
      onChange={changeAfter}
      onBusyChange={busy}
    />,
  );
  complete(
    new Response(
      JSON.stringify({
        id: "new-asset",
        pages: [{ page_id: "new-page", rotation: 0, source_page: 1 }],
      }),
      { status: 200 },
    ),
  );
  await waitFor(() => expect(changeAfter).toHaveBeenCalledOnce());
  expect(changeBefore).not.toHaveBeenCalled();
  expect(
    changeAfter.mock.calls[0][0].map(
      (page: { page_id: string }) => page.page_id,
    ),
  ).toEqual(["kept", "new-page"]);
  expect(busy.mock.calls.map((call) => call[0])).toEqual([true, false]);
});
it("does not duplicate staged page identities", () => {
  const pages = [{ page_id: "p1", rotation: 0 }];
  expect(
    mergePages(pages, [
      { page_id: "p1", rotation: 90 },
      { page_id: "p2", rotation: 0 },
    ]),
  ).toEqual([
    { page_id: "p1", rotation: 0 },
    { page_id: "p2", rotation: 0 },
  ]);
});
it("keeps dirty or incomplete review fields out of batch decisions and clears them only explicitly", () => {
  const payload = { summary: "原评语" };
  localStorage.setItem(
    "clms-review-item",
    JSON.stringify({ base_revision: 1, payload: { summary: "修订" } }),
  );
  expect(hasLocalReviewDraft("item", payload)).toBe(true);
  clearReviewDraft("item");
  expect(hasLocalReviewDraft("item", payload)).toBe(false);
  localStorage.setItem("clms-review-fields-item-1-pages", "[incomplete");
  expect(hasLocalReviewDraft("item", payload)).toBe(true);
  clearReviewDraft("item");
  expect(localStorage.length).toBe(0);
});
