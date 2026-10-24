import type { PageRef, Review, Version } from "../../shared/types";

export const kindLabels: Record<string, string> = {
  category: "分类变更",
  prompt: "题目变更",
  submission: "新作文入档",
  revision: "上传修改稿",
  evaluation: "作文评价",
  reflection: "写作反思",
};
export const statusLabels: Record<string, string> = {
  pending: "待审核",
  applied: "已入档",
  rejected: "已驳回",
  withdrawn: "已撤回",
  conflict: "冲突",
  failed: "失败",
};
export function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
export function pageRefs(value: unknown): PageRef[] {
  return Array.isArray(value) ? (value as PageRef[]) : [];
}
export function reviewAction(review: Review) {
  const payload = review.payload;
  if (review.kind === "prompt")
    return payload.action === "create" ? "新建题目" : "修改题目";
  if (review.kind === "category") {
    if (payload.action === "create") return "新建分类";
    if (payload.action === "archive" || payload.archived === true)
      return "停用分类";
    if (payload.archived === false) return "启用 / 修改分类";
    return "修改分类";
  }
  if (review.kind === "evaluation" && payload.supersedes_id)
    return "修订作文评价";
  return kindLabels[review.kind];
}
export function reviewTitle(review: Review) {
  const p = review.payload,
    before = record(review.target_snapshot.before);
  const prompt = record(p.prompt || review.target_snapshot.prompt_snapshot);
  return String(
    p.title ||
      p.name ||
      prompt.title ||
      before.title ||
      before.name ||
      (review.kind === "reflection"
        ? "本次写作的反思"
        : p.summary || p.change_note || kindLabels[review.kind]),
  );
}
export function reviewImpact(review: Review, payload = review.payload) {
  switch (review.kind) {
    case "prompt":
      return payload.action === "create"
        ? "新增一份题目档案，保存题目说明、写作要求和所附材料。"
        : "更新题目资料；已有写作的冻结题目与要求继续保留。";
    case "category":
      return payload.action === "create"
        ? "新增一个可用于归类作文的分类。"
        : payload.action === "archive" || payload.archived === true
          ? "停用这个分类，保留已有档案的历史引用。"
          : "更新这个分类的资料与启用状态。";
    case "submission":
      return `新增一次独立写作和第 1 稿，共 ${pageRefs(payload.pages).length} 页。${payload.prompt ? "同时创建下面的新题目" + (Array.isArray(payload.inline_categories) && payload.inline_categories.length ? `及 ${payload.inline_categories.length} 个新分类` : "") + "，整项一起入档。" : "关联已有题目。"}`;
    case "revision":
      return `在这次写作下新增一份 ${pageRefs(payload.pages).length} 页的修改稿，保留上一稿与历史评价。`;
    case "evaluation":
      return `${payload.supersedes_id ? "追加一条评价修订，保留原评价" : "将这份评价保存到指定稿件"}。${record(payload.coverage).scope === "partial" ? "本次仅评价部分页面，入档后仍待完整评价。" : "评价与原稿、当时的题目要求绑定。"}`;
    case "reflection":
      return "更新这次写作的反思，保留稿件和评价。";
  }
}
// Pending revisions must show their proposed manuscript, never the parent version's pages.
export function reviewPages(
  review: Review,
  payload: Record<string, unknown>,
  version?: Version | null,
) {
  if (review.kind === "submission" || review.kind === "revision")
    return pageRefs(payload.pages);
  if (review.kind === "prompt") {
    return pageRefs(
      "materials" in payload
        ? payload.materials
        : record(review.target_snapshot.before).materials,
    );
  }
  if (review.kind === "evaluation")
    return version?.manifest || pageRefs(review.target_snapshot.manifest);
  return [];
}
export function reviewPaperTitle(review: Review) {
  const state = review.status === "applied" ? "已入档" : "待入档";
  return review.kind === "prompt"
    ? "题目材料"
    : review.kind === "revision"
      ? `${state}修改稿`
      : review.kind === "submission"
        ? `${state}原稿`
        : "目标原稿";
}
