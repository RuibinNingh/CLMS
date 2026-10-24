export const allowed: Record<string, string[]> = {
  category: ["name", "description", "language_scope", "sort_order", "archived"],
  prompt: [
    "title",
    "language",
    "instructions",
    "requirements",
    "source_note",
    "category_ids",
    "rubric",
    "materials",
  ],
  submission: [
    "prompt",
    "inline_categories",
    "pages",
    "written_at",
    "duration_minutes",
    "reflection",
    "change_note",
  ],
  revision: ["pages", "change_note"],
  evaluation: [
    "coverage",
    "summary",
    "strengths",
    "score",
    "issues",
    "next_actions",
    "commentary_markdown",
  ],
  reflection: ["reflection"],
};
export function editableFields(kind: string, payload: Record<string, unknown>) {
  const fields = allowed[kind] || [];
  return kind === "submission" && payload.prompt_id
    ? fields.filter((key) => key !== "prompt" && key !== "inline_categories")
    : fields;
}
export function reviewChanges(
  kind: string,
  original: Record<string, unknown>,
  edited: Record<string, unknown>,
) {
  return Object.fromEntries(
    editableFields(kind, original)
      .filter(
        (key) => JSON.stringify(original[key]) !== JSON.stringify(edited[key]),
      )
      .map((key) => [key, edited[key]]),
  );
}
export function clearReviewDraft(id: string) {
  localStorage.removeItem(`clms-review-${id}`);
  for (const key of Object.keys(localStorage))
    if (key.startsWith(`clms-review-fields-${id}-`))
      localStorage.removeItem(key);
}
export function hasLocalReviewDraft(
  id: string,
  payload: Record<string, unknown>,
) {
  try {
    const saved = localStorage.getItem(`clms-review-${id}`);
    if (
      saved &&
      JSON.stringify(JSON.parse(saved).payload) !== JSON.stringify(payload)
    )
      return true;
    return Object.keys(localStorage).some((key) =>
      key.startsWith(`clms-review-fields-${id}-`),
    );
  } catch {
    return false;
  }
}
