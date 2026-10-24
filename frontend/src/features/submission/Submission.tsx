import { useState } from "react";
import { go } from "../../app/App";
import { api, errorText } from "../../shared/api";
import { useBeforeUnload, useDraft, useLoad } from "../../shared/hooks";
import { allCategories } from "../../shared/categories";
import type {
  Category,
  PageRef,
  Paged,
  Prompt,
  Rubric,
} from "../../shared/types";
import { ErrorNotice, Field, PageHeading } from "../../shared/ui";
import { PageUploader } from "./PageUploader";

interface Draft {
  title: string;
  language: "zh" | "en";
  instructions: string;
  requirements: string;
  source_note: string;
  category_ids: string[];
  materials: PageRef[];
  pages: PageRef[];
  written_at: string;
  duration: string;
  reflection: string;
  change_note: string;
  max_score: string;
  criteria: string;
}
const blank: Draft = {
  title: "",
  language: "zh",
  instructions: "",
  requirements: "",
  source_note: "",
  category_ids: [],
  materials: [],
  pages: [],
  written_at: "",
  duration: "",
  reflection: "",
  change_note: "",
  max_score: "",
  criteria: "",
};
export function Submission({
  promptId,
  attemptId,
  parentId,
}: {
  promptId: string | null;
  attemptId: string | null;
  parentId: string | null;
}) {
  const key = `clms-submission-${attemptId || promptId || "new"}`;
  const draft = useDraft<Draft>(key, blank);
  const value = draft.value;
  const [busy, setBusy] = useState(false);
  const [uploads, setUploads] = useState({ materials: false, pages: false });
  const [error, setError] = useState("");
  const categories = useLoad(() => allCategories());
  const prompt = useLoad(
    () =>
      promptId ? api<Prompt>(`/prompts/${promptId}`) : Promise.resolve(null),
    [promptId],
  );
  const dirty = JSON.stringify(value) !== JSON.stringify(blank);
  useBeforeUnload(dirty);
  const set = <K extends keyof Draft>(field: K, next: Draft[K]) =>
    draft.setValue({ ...value, [field]: next });
  const revision = Boolean(attemptId);
  const available =
    categories.data?.items.filter(
      (category) =>
        !category.archived_at &&
        (category.language_scope === "all" ||
          category.language_scope === value.language),
    ) || [];
  async function save() {
    if (uploads.materials || uploads.pages) return;
    setError("");
    if (!value.pages.length) {
      setError("请至少上传一页作文原稿。");
      return;
    }
    if (
      !revision &&
      !promptId &&
      !value.instructions.trim() &&
      !value.materials.length
    ) {
      setError("题目说明与题目材料至少填写一项。");
      return;
    }
    if (
      value.max_score &&
      (!Number.isFinite(Number(value.max_score)) ||
        Number(value.max_score) <= 0)
    ) {
      setError("满分必须大于 0，或留空。");
      return;
    }
    setBusy(true);
    try {
      if (revision) {
        await api(`/attempts/${attemptId}/versions`, {
          parent_version_id: parentId,
          pages: value.pages.map(({ page_id, rotation }) => ({
            page_id,
            rotation,
          })),
          change_note: value.change_note,
        });
        const attempt = await api<{ prompt_id: string }>(
          `/attempts/${attemptId}`,
        );
        draft.clear();
        go(`prompt/${attempt.prompt_id}`);
      } else {
        const rubric: Rubric | null = value.max_score
          ? {
              max_score: Number(value.max_score),
              criteria: value.criteria,
              aggregation: "none",
              dimensions: [],
            }
          : null;
        const result = await api<{ prompt_id: string }>("/submissions", {
          ...(promptId
            ? { prompt_id: promptId }
            : {
                prompt: {
                  title: value.title,
                  language: value.language,
                  instructions: value.instructions,
                  requirements: value.requirements,
                  source_note: value.source_note,
                  category_ids: value.category_ids,
                  materials: value.materials.map(({ page_id, rotation }) => ({
                    page_id,
                    rotation,
                  })),
                  rubric,
                },
              }),
          pages: value.pages.map(({ page_id, rotation }) => ({
            page_id,
            rotation,
          })),
          written_at: value.written_at || null,
          duration_minutes: value.duration ? Number(value.duration) : null,
          reflection: value.reflection,
          change_note: value.change_note,
        });
        draft.clear();
        go(`prompt/${result.prompt_id}`);
      }
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        title={
          revision
            ? "上传修改稿"
            : promptId
              ? "同题重新练习"
              : "新建作文 / 上传原稿"
        }
        subtitle={
          revision
            ? "新稿单独归档，先前原件与评价完整保留。"
            : "图片与 PDF 就是正式原稿，无需录入全文。"
        }
        actions={
          <a
            className="button quiet"
            href={promptId ? `#/prompt/${promptId}` : "#/archive"}
          >
            返回档案
          </a>
        }
      />
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
        className="submission-layout"
      >
        {!promptId && !revision && (
          <section className="panel form-section">
            <h2>题目与要求</h2>
            <div className="form-row">
              <Field label="题目标题" hint="可以留空，保存时自动命名。">
                <input
                  value={value.title}
                  onChange={(event) => set("title", event.target.value)}
                />
              </Field>
              <Field label="语言">
                <select
                  value={value.language}
                  onChange={(event) => {
                    const language = event.target.value as "zh" | "en";
                    const compatible =
                      categories.data?.items
                        .filter(
                          (category) =>
                            !category.archived_at &&
                            (category.language_scope === "all" ||
                              category.language_scope === language),
                        )
                        .map((category) => category.id) || [];
                    draft.setValue({
                      ...value,
                      language,
                      category_ids: value.category_ids.filter((id) =>
                        compatible.includes(id),
                      ),
                    });
                  }}
                >
                  <option value="zh">语文</option>
                  <option value="en">英语</option>
                </select>
              </Field>
            </div>
            <Field label="题目说明" hint="只上传题目材料也可以。">
              <textarea
                rows={3}
                value={value.instructions}
                onChange={(event) => set("instructions", event.target.value)}
              />
            </Field>
            <Field label="写作要求">
              <textarea
                rows={2}
                value={value.requirements}
                onChange={(event) => set("requirements", event.target.value)}
              />
            </Field>
            <Field label="来源备注">
              <input
                value={value.source_note}
                onChange={(event) => set("source_note", event.target.value)}
              />
            </Field>
            <fieldset>
              <legend>自定义分类 · 可多选</legend>
              <div className="check-list">
                {available.map((category) => (
                  <label key={category.id}>
                    <input
                      type="checkbox"
                      checked={value.category_ids.includes(category.id)}
                      onChange={(event) =>
                        set(
                          "category_ids",
                          event.target.checked
                            ? [...value.category_ids, category.id]
                            : value.category_ids.filter(
                                (id) => id !== category.id,
                              ),
                        )
                      }
                    />
                    {category.name}
                  </label>
                ))}
              </div>
              {!available.length && (
                <p className="muted">
                  尚无可用分类，未分类也能保存。
                  <a href="#/categories">创建分类</a>
                </p>
              )}
            </fieldset>
            <details>
              <summary>评分标准（可选）</summary>
              <div className="form-row">
                <Field label="满分">
                  <input
                    type="number"
                    min="0.01"
                    step="any"
                    inputMode="decimal"
                    value={value.max_score}
                    onChange={(event) => set("max_score", event.target.value)}
                  />
                </Field>
                <Field label="评分依据">
                  <textarea
                    value={value.criteria}
                    onChange={(event) => set("criteria", event.target.value)}
                  />
                </Field>
              </div>
            </details>
            <PageUploader
              label="题目材料"
              pages={value.materials}
              onChange={(pages) => set("materials", pages)}
              onBusyChange={(busy) =>
                setUploads((current) => ({ ...current, materials: busy }))
              }
            />
          </section>
        )}
        {promptId && (
          <section className="panel form-section">
            <h2>{prompt.data?.title || "当前题目"}</h2>
            <p className="muted">
              此次写作建立独立练习，从 V1 开始，并冻结当前题目与评分要求。
            </p>
            <ErrorNotice message={prompt.error} retry={prompt.reload} />
          </section>
        )}
        <section className="panel form-section">
          <h2>{revision ? "新版本原稿" : "作文原稿"}</h2>
          <PageUploader
            label="作文原稿"
            pages={value.pages}
            onChange={(pages) => set("pages", pages)}
            onBusyChange={(busy) =>
              setUploads((current) => ({ ...current, pages: busy }))
            }
          />
          {!revision && (
            <div className="form-row">
              <Field label="写作日期">
                <input
                  type="date"
                  value={value.written_at}
                  onChange={(event) => set("written_at", event.target.value)}
                />
              </Field>
              <Field label="写作用时（分钟）">
                <input
                  type="number"
                  min="0"
                  inputMode="numeric"
                  value={value.duration}
                  onChange={(event) => set("duration", event.target.value)}
                />
              </Field>
            </div>
          )}
          <Field label={revision ? "本次修改说明" : "稿件备注"}>
            <textarea
              value={value.change_note}
              onChange={(event) => set("change_note", event.target.value)}
            />
          </Field>
          {!revision && (
            <Field label="写作反思（可选）">
              <textarea
                value={value.reflection}
                onChange={(event) => set("reflection", event.target.value)}
              />
            </Field>
          )}
        </section>
        <div className="save-bar">
          <small className="muted">
            {dirty
              ? "草稿已保留在本浏览器；附件尚未入档。"
              : "保存后原件与页顺序不可覆盖。"}
          </small>
          <ErrorNotice message={error} />
          <button
            className="primary"
            disabled={busy || uploads.materials || uploads.pages}
          >
            {busy ? "正在归档…" : "保存并归档"}
          </button>
        </div>
      </form>
    </>
  );
}
