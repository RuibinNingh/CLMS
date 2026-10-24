import { useEffect, useState } from "react";
import type { PageRef } from "../../shared/types";
import { originalUrl, pageUrl } from "../../shared/api";
import { Empty } from "../../shared/ui";

export function Viewer({
  pages,
  title = "原稿",
  selectedPage,
  onPage,
}: {
  pages: PageRef[];
  title?: string;
  selectedPage?: string;
  onPage?: (id: string) => void;
}) {
  const [index, setIndex] = useState(0);
  const [zoom, setZoom] = useState(100);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const next = pages.findIndex((page) => page.page_id === selectedPage);
    if (next >= 0) setIndex(next);
  }, [selectedPage, pages]);
  useEffect(() => {
    setIndex(0);
  }, [pages.length]);
  useEffect(() => {
    setFailed(false);
  }, [index, pages]);
  if (!pages.length) return <Empty title="暂无页面" />;
  const page = pages[Math.min(index, pages.length - 1)];
  const navigate = (next: number) => {
    setIndex(next);
    onPage?.(pages[next].page_id);
  };
  const assets = [
    ...new Set(pages.map((item) => item.asset_id).filter(Boolean)),
  ] as string[];
  return (
    <section className="viewer panel" aria-label={title}>
      <div className="viewer-toolbar">
        <strong>{title}</strong>
        <div className="actions">
          <button
            aria-label="缩小"
            onClick={() => setZoom((value) => Math.max(25, value - 25))}
          >
            −
          </button>
          <output aria-label="缩放比例">{zoom}%</output>
          <button
            aria-label="放大"
            onClick={() => setZoom((value) => Math.min(300, value + 25))}
          >
            ＋
          </button>
          <button onClick={() => setZoom(100)}>适宽</button>
        </div>
      </div>
      <div className="page-navigation">
        <button disabled={index === 0} onClick={() => navigate(index - 1)}>
          上一页
        </button>
        <label>
          <span>稿件页</span>
          <select
            aria-label="稿件页"
            value={index}
            onChange={(event) => navigate(Number(event.target.value))}
          >
            {pages.map((item, number) => (
              <option key={`${item.page_id}-${number}`} value={number}>
                {number + 1} / {pages.length} · 原件页 {item.source_page || 1}
              </option>
            ))}
          </select>
        </label>
        <button
          disabled={index === pages.length - 1}
          onClick={() => navigate(index + 1)}
        >
          下一页
        </button>
      </div>
      <div className="viewer-canvas">
        {failed ? (
          <div className="notice error" role="alert">
            页面加载失败。<button onClick={() => setFailed(false)}>重试</button>
          </div>
        ) : (
          <img
            src={pageUrl(page.page_id, page.rotation)}
            alt={`${title}，稿件第 ${index + 1} 页，原件第 ${page.source_page || 1} 页`}
            style={{ width: `${zoom}%` }}
            onError={() => setFailed(true)}
          />
        )}
      </div>
      <div className="viewer-footer">
        <small className="muted">
          稿件页 {index + 1} · 原件页 {page.source_page || 1} ·{" "}
          {page.rotation || 0}°
        </small>
        <div className="actions">
          {assets.map((id, number) => (
            <a
              className="button quiet"
              key={id}
              href={originalUrl(id)}
              download
            >
              下载原件{assets.length > 1 ? ` ${number + 1}` : ""}
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}
