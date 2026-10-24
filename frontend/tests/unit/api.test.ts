import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, params, setAuth } from "../../src/shared/api";
import { allCategories } from "../../src/shared/categories";

afterEach(() => {
  vi.unstubAllGlobals();
  setAuth({ initialized: true, authenticated: false });
});
describe("authenticated API transport", () => {
  it("loads every category page so classifications beyond the first 100 stay selectable", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [{ id: "category-one" }],
            next_cursor: "next-page",
          }),
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [{ id: "category-two" }],
            next_cursor: null,
          }),
        ),
      );
    vi.stubGlobal("fetch", fetcher);
    const result = await allCategories(true);
    expect(result.items.map((item) => item.id)).toEqual([
      "category-one",
      "category-two",
    ]);
    expect(fetcher.mock.calls[1][0]).toContain("cursor=next-page");
    expect(result.total).toBe(2);
  });
  it("sends same-origin session and CSRF for writes", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ id: "category" }), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetcher);
    setAuth({
      initialized: true,
      authenticated: true,
      csrf_token: "csrf-state",
    });
    await api("/categories", { name: "观点" });
    expect(fetcher.mock.calls[0][0]).toBe("/api/categories");
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-CSRF-Token": "csrf-state",
        "Content-Type": "application/json",
      },
    });
  });
  it("keeps CAS error semantics and server details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "revision_conflict",
              message: "请重新核对",
              details: { revision: 2 },
            },
          }),
          { status: 409 },
        ),
      ),
    );
    await expect(api("/reviews/id/revise", {})).rejects.toMatchObject({
      code: "revision_conflict",
      status: 409,
      details: { revision: 2 },
    });
  });
  it("safely encodes metadata searches without adding empty filters", () => {
    expect(params({ q: "题目 & 反思", language: "", limit: 20 })).toBe(
      "?q=%E9%A2%98%E7%9B%AE+%26+%E5%8F%8D%E6%80%9D&limit=20",
    );
  });
});
