import { useEffect, useState } from "react";
import { useBeforeUnload, useDraft } from "../../shared/hooks";
import { Field } from "../../shared/ui";
import { editableFields } from "./reviewDraft";

const labels: Record<string, string> = {
  name: "分类名称",
  description: "分类说明",
  language_scope: "适用语言",
  sort_order: "排序值",
  archived: "停用状态",
  title: "题目标题",
  language: "语言",
  instructions: "题目说明",
  requirements: "写作要求",
  source_note: "来源备注",
  category_ids: "分类 ID 清单",
  rubric: "评分标准",
  materials: "题目材料页清单",
  prompt: "新题目",
  inline_categories: "内联新分类",
  pages: "稿件页清单",
  written_at: "写作日期",
  duration_minutes: "写作分钟数",
  reflection: "写作反思",
  change_note: "修改说明",
};
export function GenericEditor({
  kind,
  payload,
  draftKey,
  onChange,
  onInvalidChange,
}: {
  kind: string;
  payload: Record<string, unknown>;
  draftKey: string;
  onChange: (payload: Record<string, unknown>) => void;
  onInvalidChange: (invalid: boolean) => void;
}) {
  const [invalidFields, setInvalidFields] = useState<string[]>([]);
  useEffect(() => {
    onInvalidChange(invalidFields.length > 0);
  }, [invalidFields.length, onInvalidChange]);
  return (
    <div>
      {editableFields(kind, payload)
        .filter(
          (key) => kind === "category" || kind === "prompt" || key in payload,
        )
        .map((key) => (
          <GenericField
            key={key}
            field={key}
            label={labels[key] || key}
            value={payload[key]}
            storageKey={`${draftKey}-${key}`}
            onChange={(next) => onChange({ ...payload, [key]: next })}
            onInvalid={(invalid) =>
              setInvalidFields((fields) =>
                invalid
                  ? [...new Set([...fields, key])]
                  : fields.filter((field) => field !== key),
              )
            }
          />
        ))}
    </div>
  );
}
function GenericField({
  field,
  label,
  value,
  storageKey,
  onChange,
  onInvalid,
}: {
  field: string;
  label: string;
  value: unknown;
  storageKey: string;
  onChange: (value: unknown) => void;
  onInvalid: (invalid: boolean) => void;
}) {
  const json = [
    "category_ids",
    "rubric",
    "materials",
    "prompt",
    "inline_categories",
    "pages",
  ].includes(field);
  const numeric = ["sort_order", "duration_minutes"].includes(field);
  const defaultValue = field === "rubric" || field === "prompt" ? null : [];
  const initial = json
    ? JSON.stringify(value === undefined ? defaultValue : value, null, 2)
    : String(value ?? "");
  const draft = useDraft(storageKey, initial);
  const [invalid, setInvalid] = useState(false);
  useBeforeUnload(draft.value !== initial);
  useEffect(() => {
    if (json) {
      try {
        JSON.parse(draft.value);
      } catch {
        setInvalid(true);
        onInvalid(true);
      }
    }
  }, []);
  function edit(raw: string) {
    draft.setValue(raw);
    if (json) {
      try {
        const parsed = JSON.parse(raw);
        setInvalid(false);
        onInvalid(false);
        onChange(parsed);
      } catch {
        setInvalid(true);
        onInvalid(true);
      }
    } else if (numeric) onChange(raw === "" ? null : Number(raw));
    else if (field === "archived") onChange(raw === "" ? null : raw === "true");
    else onChange(raw);
  }
  const choices: Record<string, [string, string][]> = {
    language: [
      ["zh", "语文"],
      ["en", "英语"],
    ],
    language_scope: [
      ["all", "通用"],
      ["zh", "语文"],
      ["en", "英语"],
    ],
    archived: [
      ["false", "启用"],
      ["true", "停用"],
    ],
  };
  return (
    <Field
      label={label}
      hint={json ? "结构化 JSON；格式正确后可保存修订。" : undefined}
    >
      {choices[field] ? (
        <select
          value={draft.value}
          onChange={(event) => edit(event.target.value)}
        >
          <option value="">保持当前值</option>
          {choices[field].map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      ) : numeric ? (
        <input
          type="number"
          value={draft.value}
          onChange={(event) => edit(event.target.value)}
        />
      ) : (
        <textarea
          rows={json ? 6 : 2}
          value={draft.value}
          onChange={(event) => edit(event.target.value)}
        />
      )}
      {invalid && (
        <small className="danger-text" role="alert">
          格式尚未完整，原始输入已暂存。
        </small>
      )}
    </Field>
  );
}
