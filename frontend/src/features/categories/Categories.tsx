import { useState } from "react";
import { api, errorText } from "../../shared/api";
import { useLoad } from "../../shared/hooks";
import { allCategories } from "../../shared/categories";
import type { Category, Paged } from "../../shared/types";
import {
  Empty,
  ErrorNotice,
  Field,
  Loading,
  PageHeading,
  Tag,
} from "../../shared/ui";

export function Categories() {
  const list = useLoad(() => allCategories(true));
  const [editing, setEditing] = useState<Category | null>(null),
    [creating, setCreating] = useState(false),
    [error, setError] = useState("");
  async function update(category: Category, changes: Record<string, unknown>) {
    try {
      await api(`/categories/${category.id}`, {
        expected_revision: category.revision,
        ...changes,
      });
      list.reload();
    } catch (reason) {
      setError(errorText(reason));
    }
  }
  async function move(category: Category, direction: number) {
    const sorted = [...(list.data?.items || [])].sort(
      (a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name),
    );
    const index = sorted.findIndex((item) => item.id === category.id);
    const target = sorted[index + direction];
    if (!target) return;
    const ownOrder =
      category.sort_order === target.sort_order ? index : category.sort_order;
    const targetOrder =
      category.sort_order === target.sort_order
        ? index + direction
        : target.sort_order;
    try {
      await api(`/categories/${category.id}`, {
        expected_revision: category.revision,
        sort_order: targetOrder,
      });
      await api(`/categories/${target.id}`, {
        expected_revision: target.revision,
        sort_order: ownOrder,
      });
      list.reload();
    } catch (reason) {
      setError(errorText(reason));
      list.reload();
    }
  }
  const items = [...(list.data?.items || [])].sort(
    (a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name),
  );
  return (
    <>
      <PageHeading
        title="分类管理"
        subtitle="按你的需要创建分类。分类可以多选，停用后历史引用仍保留。"
        actions={
          <button
            className="primary"
            onClick={() => {
              setCreating(true);
              setEditing(null);
            }}
          >
            ＋ 创建分类
          </button>
        }
      />
      <ErrorNotice message={error || list.error} retry={list.reload} />
      {(creating || editing) && (
        <CategoryForm
          key={editing?.id || "create"}
          category={editing}
          nextOrder={items.length}
          onCancel={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={() => {
            setCreating(false);
            setEditing(null);
            list.reload();
          }}
        />
      )}
      {list.loading && <Loading />}
      {!list.loading && items.length === 0 && !creating && (
        <Empty title="还没有自定义分类">
          <p className="muted">语文与英语共用档案结构，分类由你决定。</p>
          <button className="primary" onClick={() => setCreating(true)}>
            创建分类
          </button>
        </Empty>
      )}
      <div className="category-list">
        {items.map((category, index) => (
          <section className="panel category-card" key={category.id}>
            <div>
              <div className="actions">
                <h2>{category.name}</h2>
                <Tag>
                  {category.language_scope === "all"
                    ? "通用"
                    : category.language_scope === "zh"
                      ? "语文"
                      : "英语"}
                </Tag>
                {category.archived_at && <Tag>已停用</Tag>}
              </div>
              <p className="muted">{category.description || "未填写说明"}</p>
            </div>
            <div className="actions">
              <button
                aria-label={`${category.name}上移`}
                disabled={index === 0}
                onClick={() => move(category, -1)}
              >
                ↑
              </button>
              <button
                aria-label={`${category.name}下移`}
                disabled={index === items.length - 1}
                onClick={() => move(category, 1)}
              >
                ↓
              </button>
              <button
                onClick={() => {
                  setEditing(category);
                  setCreating(false);
                }}
              >
                编辑
              </button>
              <button
                className="quiet"
                onClick={() =>
                  update(category, { archived: !category.archived_at })
                }
              >
                {category.archived_at ? "重新启用" : "停用"}
              </button>
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
function CategoryForm({
  category,
  nextOrder,
  onSaved,
  onCancel,
}: {
  category: Category | null;
  nextOrder: number;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(category?.name || ""),
    [description, setDescription] = useState(category?.description || ""),
    [scope, setScope] = useState(category?.language_scope || "all"),
    [sort, setSort] = useState(category?.sort_order ?? nextOrder),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <form
      className="panel form-section"
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        try {
          await api(category ? `/categories/${category.id}` : "/categories", {
            name,
            description,
            language_scope: scope,
            sort_order: sort,
            ...(category ? { expected_revision: category.revision } : {}),
          });
          onSaved();
        } catch (reason) {
          setError(errorText(reason));
        } finally {
          setBusy(false);
        }
      }}
    >
      <h2>{category ? "编辑分类" : "创建分类"}</h2>
      <div className="form-row">
        <Field label="分类名称">
          <input
            required
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <Field label="适用语言">
          <select
            value={scope}
            onChange={(event) =>
              setScope(event.target.value as Category["language_scope"])
            }
          >
            <option value="all">通用</option>
            <option value="zh">语文</option>
            <option value="en">英语</option>
          </select>
        </Field>
      </div>
      <Field label="分类说明">
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </Field>
      <Field label="排序值">
        <input
          type="number"
          value={sort}
          onChange={(event) => setSort(Number(event.target.value))}
        />
      </Field>
      <ErrorNotice message={error} />
      <div className="actions">
        <button className="primary" disabled={busy}>
          {busy ? "保存中…" : "保存分类"}
        </button>
        <button type="button" onClick={onCancel}>
          取消
        </button>
      </div>
    </form>
  );
}
