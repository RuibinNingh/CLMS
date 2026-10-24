import { useState } from "react";
import { api, errorText } from "../../shared/api";
import { useBeforeUnload, useDraft } from "../../shared/hooks";
import type { Attempt } from "../../shared/types";
import { ErrorNotice, Field } from "../../shared/ui";

export function AttemptNotes({
  attempt,
  onSaved,
}: {
  attempt: Attempt;
  onSaved: () => void;
}) {
  const draft = useDraft(`clms-reflection-${attempt.id}`, {
    reflection: attempt.reflection,
    selected_version_id: attempt.selected_version_id || "",
  });
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const dirty =
    draft.value.reflection !== attempt.reflection ||
    draft.value.selected_version_id !== (attempt.selected_version_id || "");
  useBeforeUnload(dirty);
  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        try {
          await api(`/attempts/${attempt.id}`, {
            expected_revision: attempt.revision,
            reflection: draft.value.reflection,
            selected_version_id: draft.value.selected_version_id || null,
          });
          draft.clear();
          onSaved();
        } catch (reason) {
          setError(errorText(reason));
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="form-row">
        <Field label="写作反思">
          <textarea
            value={draft.value.reflection}
            onChange={(event) =>
              draft.setValue({ ...draft.value, reflection: event.target.value })
            }
          />
        </Field>
        <Field label="选定定稿" hint="定稿可以与最近上传稿不同。">
          <select
            value={draft.value.selected_version_id}
            onChange={(event) =>
              draft.setValue({
                ...draft.value,
                selected_version_id: event.target.value,
              })
            }
          >
            <option value="">未选定</option>
            {attempt.versions
              .filter((version) => !version.voided_at)
              .map((version) => (
                <option key={version.id} value={version.id}>
                  V{version.version_no}
                </option>
              ))}
          </select>
        </Field>
      </div>
      <ErrorNotice message={error} />
      <button disabled={!dirty || busy}>
        {busy ? "保存中…" : "保存反思与定稿"}
      </button>
      {dirty && <small className="muted">修改已暂存在本浏览器。</small>}
    </form>
  );
}
