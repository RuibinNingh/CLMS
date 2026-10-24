import { useState } from "react";
import { api, errorText } from "../../shared/api";
import { useBeforeUnload, useDraft } from "../../shared/hooks";
import type { Attempt, Version } from "../../shared/types";
import { ErrorNotice } from "../../shared/ui";
import { createEvaluation, EvaluationEditor } from "./EvaluationEditor";

export function TeacherEvaluation({
  version,
  attempt,
  onSaved,
}: {
  version: Version;
  attempt: Attempt;
  onSaved: () => void;
}) {
  const initial = createEvaluation(
    version.id,
    version.manifest_hash,
    attempt.snapshot_hash,
    version.manifest,
  );
  const draft = useDraft(`clms-teacher-${version.id}`, initial);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [open, setOpen] = useState(false);
  const dirty = JSON.stringify(draft.value) !== JSON.stringify(initial);
  useBeforeUnload(dirty);
  return (
    <details
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      className="teacher-editor"
    >
      <summary>记录教师 / 人工评价</summary>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setError("");
          setBusy(true);
          try {
            await api("/evaluations", draft.value);
            draft.setValue(initial);
            draft.clear();
            setOpen(false);
            onSaved();
          } catch (reason) {
            setError(errorText(reason));
          } finally {
            setBusy(false);
          }
        }}
      >
        <EvaluationEditor
          value={draft.value}
          onChange={draft.setValue}
          pages={version.manifest}
          rubric={attempt.prompt_snapshot.rubric}
        />
        <ErrorNotice message={error} />
        <button className="primary" disabled={busy}>
          {busy ? "保存中…" : "保存人工评价"}
        </button>
      </form>
    </details>
  );
}
