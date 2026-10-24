import { useState } from "react";
import { api, params } from "../../shared/api";
import { useLoad } from "../../shared/hooks";
import { allCategories } from "../../shared/categories";
import type { Paged, Prompt } from "../../shared/types";
import { Icon } from "../../shared/Icon";
import {
  date,
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  Tag,
} from "../../shared/ui";

export function Archive() {
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [language, setLanguage] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [cursor, setCursor] = useState("");
  const categories = useLoad(() => allCategories(true));
  const list = useLoad(
    () =>
      api<Paged<Prompt>>(
        `/prompts${params({ q: search, language, category_ids: category, status, from_date: from, to_date: to, cursor, limit: 20 })}`,
      ),
    [search, language, category, status, from, to, cursor],
  );
  const change = (setter: (value: string) => void, value: string) => {
    setter(value);
    setCursor("");
  };
  return (
    <>
      <PageHeading
        eyebrow="CLMS · 写作的每一步"
        title="作文档案"
        subtitle="从原稿到定稿，留下每一次写作的轨迹。"
        actions={
          <a className="button primary" href="#/submit">
            <Icon name="plus" /> 新建作文 / 上传原稿
          </a>
        }
      />
      <section className="archive-filters" aria-label="档案筛选">
        <div className="archive-filter-top">
          <div className="segments" role="group" aria-label="筛选语言">
            {(
              [
                ["", "全部"],
                ["zh", "语文"],
                ["en", "英语"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                aria-pressed={language === value}
                onClick={() => change(setLanguage, value)}
              >
                {label}
              </button>
            ))}
          </div>
          <form
            className="search-form"
            onSubmit={(event) => {
              event.preventDefault();
              change(setSearch, q);
            }}
          >
            <input
              aria-label="搜索作文"
              type="search"
              enterKeyHint="search"
              placeholder="搜索题目、反思与已保存评价"
              value={q}
              onChange={(event) => setQ(event.target.value)}
            />
            <button type="submit">
              <Icon name="search" /> 搜索
            </button>
          </form>
        </div>
        <div className="filter-row">
          <select
            aria-label="筛选分类"
            value={category}
            onChange={(event) => change(setCategory, event.target.value)}
          >
            <option value="">全部分类</option>
            {categories.data?.items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
                {item.archived_at ? "（停用）" : ""}
              </option>
            ))}
          </select>
          <select
            aria-label="筛选评价状态"
            value={status}
            onChange={(event) => change(setStatus, event.target.value)}
          >
            <option value="">全部状态</option>
            <option value="pending">待完整评价</option>
            <option value="evaluated">已有完整评价</option>
          </select>
          <details className="date-filters">
            <summary>写作日期{from || to ? " · 已筛选" : ""}</summary>
            <div className="date-range">
              <label className="date-filter">
                从{" "}
                <input
                  type="date"
                  aria-label="开始日期"
                  value={from}
                  onChange={(event) => change(setFrom, event.target.value)}
                />
              </label>
              <label className="date-filter">
                至{" "}
                <input
                  type="date"
                  aria-label="结束日期"
                  value={to}
                  onChange={(event) => change(setTo, event.target.value)}
                />
              </label>
            </div>
          </details>
          {(search || language || category || status || from || to) && (
            <button
              className="quiet"
              onClick={() => {
                setQ("");
                setSearch("");
                setLanguage("");
                setCategory("");
                setStatus("");
                setFrom("");
                setTo("");
                setCursor("");
              }}
            >
              清除筛选
            </button>
          )}
        </div>
      </section>
      <ErrorNotice message={categories.error} retry={categories.reload} />
      <ErrorNotice message={list.error} retry={list.reload} />
      {list.loading && <Loading />}
      {!list.loading && list.data?.items.length === 0 && (
        <Empty
          title={
            search || language || category || status || from || to
              ? "没有符合筛选的作文"
              : "还没有作文档案"
          }
        >
          <p className="muted">上传第一份图片或 PDF 原稿，开始记录。</p>
          <a className="button primary" href="#/submit">
            新建作文 / 上传原稿
          </a>
        </Empty>
      )}
      {list.data && !list.loading && list.data.items.length > 0 && (
        <p className="archive-count muted">
          当前页 {list.data.items.length} 份题目档案
        </p>
      )}
      <div className="archive-list">
        {list.data?.items.map((prompt) => (
          <a
            className="panel archive-card"
            href={`#/prompt/${prompt.id}`}
            key={prompt.id}
          >
            <div className="archive-card-body">
              <div className="archive-card-heading">
                <div className="actions">
                  <Tag>{prompt.language === "zh" ? "语文" : "英语"}</Tag>
                  {prompt.category_ids.map((id) => (
                    <Tag key={id}>
                      {categories.data?.items.find((item) => item.id === id)
                        ?.name || "分类"}
                    </Tag>
                  ))}
                </div>
                <Icon name="arrow" />
              </div>
              <h2>{prompt.title}</h2>
              <p className="muted preview-text">
                {prompt.instructions || "题目以附件材料保存"}
              </p>
            </div>
            <div className="archive-card-meta">
              <Tag tone={prompt.status === "evaluated" ? "success" : "warning"}>
                {prompt.status === "evaluated" ? "已有完整评价" : "待完整评价"}
              </Tag>
              <div className="archive-card-footer muted">
                <small>
                  {prompt.attempt_count ?? prompt.attempts?.length ?? 0} 次练习
                </small>
                <small>
                  {prompt.latest_written_at ? "最近写作" : "建档"}{" "}
                  {date(prompt.latest_written_at || prompt.created_at)}
                </small>
              </div>
            </div>
          </a>
        ))}
      </div>
      {list.data?.next_cursor && (
        <div className="pagination">
          <button onClick={() => setCursor(list.data!.next_cursor!)}>
            下一页
          </button>
        </div>
      )}
      {cursor && (
        <button className="quiet" onClick={() => setCursor("")}>
          返回第一页
        </button>
      )}
    </>
  );
}
