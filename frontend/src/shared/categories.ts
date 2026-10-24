import { api, params } from "./api";
import type { Category, Paged } from "./types";

export async function allCategories(
  includeArchived = false,
): Promise<Paged<Category>> {
  const items: Category[] = [];
  let cursor: string | null = null;
  const seen = new Set<string>();
  do {
    const page: Paged<Category> = await api(
      `/categories${params({ include_archived: includeArchived ? "true" : "false", limit: 100, cursor })}`,
    );
    items.push(...page.items);
    cursor = page.next_cursor;
    if (cursor && seen.has(cursor))
      throw new Error("分类分页发生冲突，请重试。");
    if (cursor) seen.add(cursor);
  } while (cursor);
  return { items, next_cursor: null, total: items.length };
}
