import type { ReactNode } from "react";
import { allCategories } from "../../shared/categories";
import { useLoad } from "../../shared/hooks";
import type { Category, Review, Version } from "../../shared/types";
import { ErrorNotice, Tag } from "../../shared/ui";
import { HelpTip } from "../../shared/HelpTip";
import { Viewer } from "../document-viewer/Viewer";
import { pageRefs, record } from "./reviewPresentation";

const languageLabels: Record<string, string> = {
  zh: "语文",
  en: "英语",
  all: "中英通用",
};
const fields: Record<string, string> = {
  title: "题目标题",
  language: "语言",
  instructions: "题目说明",
  requirements: "写作要求",
  source_note: "来源备注",
  category_ids: "分类",
  rubric: "评分标准",
  materials: "题目材料",
  name: "分类名称",
  description: "分类说明",
  language_scope: "适用语言",
  sort_order: "排序值",
  archived: "分类状态",
  pages: "作文原稿",
  written_at: "写作日期",
  duration_minutes: "写作用时",
  reflection: "写作反思",
  change_note: "修改说明",
};
const promptFields = [
  "title",
  "language",
  "instructions",
  "requirements",
  "rubric",
  "category_ids",
  "materials",
  "source_note",
];

function comparable(field: string, value: unknown) {
  return field === "materials" || field === "pages"
    ? pageRefs(value).map((page) => ({
        page_id: page.page_id,
        rotation: page.rotation || 0,
      }))
    : value;
}

function valueView(
  field: string,
  value: unknown,
  categories: Category[],
): ReactNode {
  if (field === "language" || field === "language_scope")
    return languageLabels[String(value)] || "未填写";
  if (field === "archived") return value ? "停用，保留历史引用" : "启用";
  if (field === "rubric") {
    if (!value) return <span className="muted">未提供评分细则</span>;
    const rubric = record(value),
      dimensions = Array.isArray(rubric.dimensions) ? rubric.dimensions : [];
    return (
      <div>
        <strong>总分上限 {String(rubric.max_score)} 分</strong>
        <p>{rubric.aggregation === "sum" ? "分项加总计分" : "总分独立评定"}</p>
        {rubric.criteria ? (
          <p className="preserve-lines">{String(rubric.criteria)}</p>
        ) : null}
        {dimensions.map((item, index) => {
          const dimension = record(item);
          return (
            <Tag key={index}>
              {String(dimension.name)} · 上限 {String(dimension.max_score)} 分
            </Tag>
          );
        })}
      </div>
    );
  }
  if (field === "category_ids") {
    const ids = Array.isArray(value) ? (value as string[]) : [];
    if (!ids.length) return <span className="muted">未分类</span>;
    return (
      <div className="actions">
        {ids.map((id) => {
          const category = categories.find((item) => item.id === id);
          return <Tag key={id}>{category?.name || `分类 ${id}`}</Tag>;
        })}
      </div>
    );
  }
  if (field === "materials" || field === "pages") {
    const pages = pageRefs(value);
    if (!pages.length)
      return (
        <span className="muted">
          {field === "materials" ? "未附原始材料图" : "未附作文原稿"}
        </span>
      );
    return (
      <div>
        <strong>{pages.length} 页</strong>
        <ol className="proposal-pages">
          {pages.map((page, index) => (
            <li key={`${page.page_id}-${index}`}>
              第 {index + 1} 页
              {page.source_page ? ` · 原件第 ${page.source_page} 页` : ""} ·{" "}
              {page.rotation || 0}°
            </li>
          ))}
        </ol>
      </div>
    );
  }
  if (value == null || value === "")
    return <span className="muted">未填写</span>;
  return (
    <span className="preserve-lines">
      {String(value)}
      {field === "duration_minutes" ? " 分钟" : ""}
    </span>
  );
}

function ReadableFields({
  data,
  keys,
  before,
  categories = [],
}: {
  data: Record<string, unknown>;
  keys: string[];
  before?: Record<string, unknown>;
  categories?: Category[];
}) {
  return (
    <dl className="proposal-fields">
      {keys.map((field) => {
        const old =
          field === "archived" ? Boolean(before?.archived_at) : before?.[field];
        const changed =
          before != null &&
          JSON.stringify(comparable(field, old)) !==
            JSON.stringify(comparable(field, data[field]));
        return (
          <div
            key={field}
            className={`proposal-field ${changed ? "is-changed" : ""}`}
          >
            <dt>
              {fields[field] || field}
              {field === "materials" && (
                <HelpTip label="题目材料说明">
                  这里只预览提案包含的文件。提交了题目文字，并不代表试卷原图已经上传；未附原图时，请核对来源备注。
                </HelpTip>
              )}
              {field === "rubric" && (
                <HelpTip label="评分标准说明">
                  试卷总分只说明分数上限。没有具体评分细则时，评价可以不打分，系统不会自动补满分。
                </HelpTip>
              )}
              {changed && <Tag tone="warning">有变更</Tag>}
            </dt>
            <dd>
              {changed ? (
                <div className="proposal-diff">
                  <div className="proposal-before">
                    <small>原值</small>
                    {valueView(field, old, categories)}
                  </div>
                  <div className="proposal-after">
                    <small>提案</small>
                    {valueView(field, data[field], categories)}
                  </div>
                </div>
              ) : (
                valueView(field, data[field], categories)
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

export function PromptPreview({
  data,
  before,
  categories = [],
}: {
  data: Record<string, unknown>;
  before?: Record<string, unknown>;
  categories?: Category[];
}) {
  const frozenCategories = Array.isArray(data.categories)
    ? (data.categories as Category[])
    : [];
  return (
    <ReadableFields
      data={data}
      keys={promptFields}
      before={before}
      categories={[...frozenCategories, ...categories]}
    />
  );
}

export function ProposalContent({
  review,
  payload,
  version,
}: {
  review: Review;
  payload: Record<string, unknown>;
  version?: Version | null;
}) {
  const before = record(review.target_snapshot.before);
  const needsCategories =
    review.kind === "prompt" || review.kind === "submission";
  const categories = useLoad(
    () => (needsCategories ? allCategories(true) : Promise.resolve(null)),
    [needsCategories],
  );
  const names = categories.data?.items || [];
  let content: ReactNode;
  if (review.kind === "prompt") {
    content = (
      <PromptPreview
        data={{ ...before, ...payload }}
        before={payload.action === "update" ? before : undefined}
        categories={names}
      />
    );
  } else if (review.kind === "category") {
    const data = {
      ...before,
      ...Object.fromEntries(
        Object.entries(payload).filter(([, value]) => value != null),
      ),
    };
    data.archived =
      payload.action === "archive" ||
      payload.archived === true ||
      (payload.archived == null && Boolean(before.archived_at));
    data.language_scope ??= "all";
    data.sort_order ??= 0;
    content = (
      <ReadableFields
        data={data}
        keys={[
          "name",
          "description",
          "language_scope",
          "sort_order",
          "archived",
        ]}
        before={payload.action === "create" ? undefined : before}
      />
    );
  } else if (review.kind === "submission") {
    const prompt = payload.prompt_id ? before : record(payload.prompt);
    content = (
      <>
        <div className="proposal-section">
          <h3>{payload.prompt_id ? "关联已有题目" : "同时新建的题目"}</h3>
          <PromptPreview data={prompt} categories={names} />
          {pageRefs(prompt.materials).length > 0 && (
            <details>
              <summary>查看题目材料原图</summary>
              <Viewer title="题目材料" pages={pageRefs(prompt.materials)} />
            </details>
          )}
        </div>
        {Array.isArray(payload.inline_categories) &&
          payload.inline_categories.length > 0 && (
            <div className="proposal-section">
              <h3>同时新建的分类 · {payload.inline_categories.length} 个</h3>
              {payload.inline_categories.map((item, index) => (
                <ReadableFields
                  key={index}
                  data={record(item)}
                  keys={["name", "description", "language_scope", "sort_order"]}
                />
              ))}
            </div>
          )}
        <div className="proposal-section">
          <h3>新的独立写作 · 第 1 稿</h3>
          <ReadableFields
            data={payload}
            keys={[
              "pages",
              "written_at",
              "duration_minutes",
              "reflection",
              "change_note",
            ]}
          />
        </div>
      </>
    );
  } else if (review.kind === "revision") {
    content = (
      <>
        <p className="muted">
          基于 V{String(before.version_no || version?.version_no || "—")}{" "}
          的修改稿
        </p>
        <ReadableFields data={payload} keys={["pages", "change_note"]} />
        {pageRefs(before.manifest).length > 0 && (
          <details>
            <summary>查看上一稿 V{String(before.version_no)}</summary>
            <Viewer
              title={`上一稿 V${String(before.version_no)}`}
              pages={pageRefs(before.manifest)}
            />
          </details>
        )}
      </>
    );
  } else if (review.kind === "reflection") {
    content = (
      <ReadableFields data={payload} keys={["reflection"]} before={before} />
    );
  }
  return (
    <div className="proposal-content">
      <ErrorNotice message={categories.error} retry={categories.reload} />
      {content}
    </div>
  );
}
