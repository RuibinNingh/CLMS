import { useState } from "react";
import { api, ApiError, errorText } from "../../shared/api";
import { allCategories } from "../../shared/categories";
import { useBeforeUnload, useDraft, useLoad } from "../../shared/hooks";
import type { Prompt } from "../../shared/types";
import { ErrorNotice, Field } from "../../shared/ui";
import { RubricEditor } from "../../shared/RubricEditor";
import { PageUploader } from "../submission/PageUploader";

export function PromptEdit({
  prompt,
  onSaved,
  onReload,
}: {
  prompt: Prompt;
  onSaved: () => void;
  onReload: () => void;
}) {
  const initial = {
    expected_revision: prompt.revision,
    title: prompt.title,
    language: prompt.language,
    instructions: prompt.instructions,
    requirements: prompt.requirements,
    source_note: prompt.source_note,
    category_ids: prompt.category_ids,
    rubric: prompt.rubric,
    materials: prompt.materials,
  };
  const draft = useDraft(`clms-prompt-${prompt.id}`, initial);
  const value = draft.value;
  const categories = useLoad(() => allCategories());
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [uploading, setUploading] = useState(false);
  const dirty = JSON.stringify(value) !== JSON.stringify(initial);
  useBeforeUnload(dirty);
  const set = <K extends keyof typeof initial>(
    key: K,
    next: (typeof initial)[K],
  ) => draft.setValue({ ...value, [key]: next });
  const available =
    categories.data?.items.filter(
      (item) =>
        item.language_scope === "all" || item.language_scope === value.language,
    ) || [];
  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (uploading) return;
        setError("");
        if (!value.instructions.trim() && !value.materials.length) {
          setError("题目说明与材料至少保留一项。");
          return;
        }
        setBusy(true);
        try {
          await api(`/prompts/${prompt.id}`, {
            ...value,
            materials: value.materials.map(({ page_id, rotation }) => ({
              page_id,
              rotation,
            })),
          });
          draft.clear();
          onSaved();
        } catch (reason) {
          setError(errorText(reason));
          if (reason instanceof ApiError && reason.status === 409) onReload();
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="form-row">
        <Field label="编辑题目标题">
          <input
            required
            value={value.title}
            onChange={(event) => set("title", event.target.value)}
          />
        </Field>
        <Field label="编辑题目语言">
          <select
            value={value.language}
            onChange={(event) => {
              const language = event.target.value as Prompt["language"];
              const compatible =
                categories.data?.items
                  .filter(
                    (item) =>
                      item.language_scope === "all" ||
                      item.language_scope === language,
                  )
                  .map((item) => item.id) || [];
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
      <Field label="编辑题目说明">
        <textarea
          value={value.instructions}
          onChange={(event) => set("instructions", event.target.value)}
        />
      </Field>
      <Field label="编辑写作要求">
        <textarea
          value={value.requirements}
          onChange={(event) => set("requirements", event.target.value)}
        />
      </Field>
      <Field label="编辑来源备注">
        <input
          value={value.source_note}
          onChange={(event) => set("source_note", event.target.value)}
        />
      </Field>
      <fieldset>
        <legend>编辑题目分类</legend>
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
                      : value.category_ids.filter((id) => id !== category.id),
                  )
                }
              />
              {category.name}
            </label>
          ))}
        </div>
        {!available.length && (
          <p className="muted">没有适用分类，未分类合法。</p>
        )}
      </fieldset>
      <RubricEditor
        value={value.rubric}
        onChange={(rubric) => set("rubric", rubric)}
      />
      <PageUploader
        label="编辑题目材料"
        pages={value.materials}
        onChange={(pages) => set("materials", pages)}
        onBusyChange={setUploading}
      />
      <ErrorNotice message={error || categories.error} />
      {value.expected_revision !== prompt.revision && (
        <div className="notice warning">
          题目已由其他窗口更新。你的修改仍保留，请重新核对后保存。
          <button
            type="button"
            onClick={() =>
              navigator.clipboard
                .writeText(JSON.stringify(value, null, 2))
                .catch(() => setError("无法自动复制，请手动保存当前字段内容。"))
            }
          >
            复制本地修改
          </button>
          <button
            type="button"
            onClick={() => {
              if (
                window.confirm("已保留需要的修改？载入当前题目会替换本地草稿。")
              ) {
                draft.setValue(initial);
                draft.clear();
              }
            }}
          >
            载入当前题目
          </button>
        </div>
      )}
      <div className="actions">
        <button
          className="primary"
          disabled={
            busy || uploading || value.expected_revision !== prompt.revision
          }
        >
          {busy ? "保存中…" : "保存题目"}
        </button>
        <small className="muted">已有练习的题目材料与评分快照不会变化。</small>
      </div>
    </form>
  );
}
