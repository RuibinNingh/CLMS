import { useState } from "react";
import { api } from "../../shared/api";
import { useLoad } from "../../shared/hooks";
import { Icon } from "../../shared/Icon";
import type { Prompt } from "../../shared/types";
import {
  date,
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
} from "../../shared/ui";
import { Viewer } from "../document-viewer/Viewer";
import { AttemptNotes } from "./AttemptNotes";
import { History } from "./ArchiveTools";
import { PromptEdit } from "./PromptEdit";
import { VersionWorkspace } from "./VersionWorkspace";

export function PromptDetail({
  id,
  selectedVersionId,
}: {
  id: string;
  selectedVersionId: string | null;
}) {
  const prompt = useLoad(() => api<Prompt>(`/prompts/${id}`), [id]);
  const [attemptId, setAttemptId] = useState("");
  const [versionId, setVersionId] = useState(selectedVersionId || "");
  const [editing, setEditing] = useState(false);
  const value = prompt.data;
  const attempts = value?.attempts || [];
  const attempt =
    attempts.find((item) => item.id === attemptId) ||
    attempts.find((item) =>
      item.versions.some((version) => version.id === versionId),
    ) ||
    attempts[0];
  const versions = attempt?.versions || [];
  const version =
    versions.find((item) => item.id === versionId) ||
    [...versions].reverse().find((item) => !item.voided_at) ||
    versions[0];
  const snapshot = attempt?.prompt_snapshot || value;
  if (!value || !snapshot)
    return (
      <>
        <ErrorNotice message={prompt.error} retry={prompt.reload} />
        {prompt.loading && <Loading />}
      </>
    );
  return (
    <>
      <PageHeading
        eyebrow="作文档案 · 原稿与评价"
        title={value.title}
        subtitle={`${value.language === "zh" ? "语文" : "英语"} · ${attempts.length} 次独立练习`}
        actions={
          <>
            <a className="button quiet" href="#/archive">
              <Icon name="back" />
              返回档案
            </a>
            <button onClick={() => setEditing(!editing)}>
              {editing ? "收起编辑" : "编辑题目"}
            </button>
            <a className="button primary" href={`#/submit?prompt=${id}`}>
              <Icon name="plus" />
              重新写一篇
            </a>
          </>
        }
      />
      <ErrorNotice message={prompt.error} retry={prompt.reload} />
      {editing && (
        <section className="panel prompt-material">
          <h2>编辑当前题目</h2>
          <PromptEdit
            prompt={value}
            onReload={prompt.reload}
            onSaved={() => {
              setEditing(false);
              prompt.reload();
            }}
          />
        </section>
      )}
      {attempts.length > 0 && (
        <div className="attempt-tabs" role="tablist" aria-label="独立练习">
          {attempts.map((item, index) => (
            <button
              role="tab"
              aria-selected={item.id === attempt?.id}
              className={item.id === attempt?.id ? "selected" : ""}
              key={item.id}
              onClick={() => {
                setAttemptId(item.id);
                setVersionId("");
              }}
            >
              第 {index + 1} 次写作{" "}
              <small>
                {date(item.written_at || item.versions[0]?.created_at)}
              </small>
            </button>
          ))}
        </div>
      )}
      <details
        className="panel prompt-material compact-details"
        key={attempt?.id || id}
      >
        <summary>
          题目与要求{" "}
          <span className="muted">
            {attempt ? "· 本次写作的冻结快照" : "· 当前题目"}
          </span>
        </summary>
        <h3>{snapshot.title}</h3>
        <p className="preserve-lines">
          {snapshot.instructions || "题目以附件材料保存"}
        </p>
        {snapshot.requirements && (
          <p className="muted preserve-lines">{snapshot.requirements}</p>
        )}
        {snapshot.source_note && (
          <p className="muted">来源：{snapshot.source_note}</p>
        )}
        <p className="muted">
          {snapshot.rubric
            ? `满分 ${snapshot.rubric.max_score} · ${snapshot.rubric.criteria || "未填写说明"}`
            : "未设置数值评分标准"}
        </p>
        {snapshot.materials.length > 0 && (
          <Viewer pages={snapshot.materials} title="题目材料" />
        )}
      </details>
      {!attempt ? (
        <Empty title="此题目还没有练习">
          <a className="button primary" href={`#/submit?prompt=${id}`}>
            上传第一篇原稿
          </a>
        </Empty>
      ) : (
        <>
          <div className="attempt-context">
            <p className="muted">
              写作日期 {date(attempt.written_at)} ·{" "}
              {attempt.duration_minutes == null
                ? "未记录用时"
                : `${attempt.duration_minutes} 分钟`}
            </p>
            {version && (
              <a
                className="button"
                href={`#/submit?attempt=${attempt.id}&parent=${version.id}`}
              >
                <Icon name="document" />
                上传修改稿
              </a>
            )}
          </div>
          <div className="version-strip" role="group" aria-label="稿件版本">
            {versions.map((item) => (
              <button
                key={item.id}
                className={item.id === version?.id ? "selected" : ""}
                aria-pressed={item.id === version?.id}
                onClick={() => setVersionId(item.id)}
              >
                V{item.version_no}
                {item.voided_at
                  ? " · 已作废"
                  : attempt.selected_version_id === item.id
                    ? " · 定稿"
                    : ""}
                <small>{date(item.created_at)}</small>
              </button>
            ))}
          </div>
          {version && (
            <VersionWorkspace
              key={version.id}
              prompt={value}
              attempt={attempt}
              version={version}
              onReload={prompt.reload}
            />
          )}
          <details className="panel attempt-info compact-details">
            <summary>写作反思与定稿选择</summary>
            <AttemptNotes
              key={`${attempt.id}-${attempt.revision}`}
              attempt={attempt}
              onSaved={prompt.reload}
            />
          </details>
          <History promptId={id} />
        </>
      )}
    </>
  );
}
