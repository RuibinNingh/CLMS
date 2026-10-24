import { useRef, useState } from "react";
import { api, errorText, pageUrl } from "../../shared/api";
import type { Asset, PageRef } from "../../shared/types";
import { ErrorNotice } from "../../shared/ui";

export function movePage(pages: PageRef[], index: number, delta: number) {
  const target = index + delta;
  if (target < 0 || target >= pages.length) return pages;
  const next = [...pages];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
export function PageUploader({
  label,
  pages,
  onChange,
  onBusyChange,
}: {
  label: string;
  pages: PageRef[];
  onChange: (pages: PageRef[]) => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const latest = useRef({ pages, onChange });
  latest.current = { pages, onChange };
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [staged, setStaged] = useState<Asset[]>([]);
  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    onBusyChange?.(true);
    setError("");
    const added: PageRef[] = [];
    try {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        const asset = await api<Asset>("/assets", form);
        added.push(
          ...asset.pages.map((page) => ({
            ...page,
            asset_id: asset.id,
            rotation: page.rotation || 0,
          })),
        );
      }
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      if (added.length)
        latest.current.onChange(mergePages(latest.current.pages, added));
      setUploading(false);
      onBusyChange?.(false);
    }
  }
  return (
    <section className="upload-section">
      <div className="section-heading">
        <h3>{label}</h3>
        <small className="muted">{pages.length} 页</small>
      </div>
      <label className="upload-zone">
        <span>
          {uploading ? "正在上传与准备页面…" : "选择图片或 PDF，可多选"}
        </span>
        <small>JPEG、PNG、WebP、PDF · 原始文件完整保留</small>
        <input
          aria-label={label}
          type="file"
          accept="image/jpeg,image/png,image/webp,application/pdf"
          multiple
          disabled={uploading}
          onChange={(event) => {
            void upload(event.target.files);
            event.target.value = "";
          }}
        />
      </label>
      <ErrorNotice message={error} />
      {pages.length > 0 && (
        <ol className="page-grid">
          {pages.map((page, index) => (
            <li className="page-card" key={`${page.page_id}-${index}`}>
              <img
                src={pageUrl(page.page_id, page.rotation)}
                alt={`${label}第 ${index + 1} 页`}
                loading="lazy"
              />
              <div className="page-card-caption">
                <strong>第 {index + 1} 页</strong>
                <small>
                  原件页 {page.source_page || 1} · {page.rotation}°
                </small>
              </div>
              <div className="actions">
                <button
                  type="button"
                  aria-label={`第 ${index + 1} 页上移`}
                  disabled={index === 0}
                  onClick={() => onChange(movePage(pages, index, -1))}
                >
                  ↑
                </button>
                <button
                  type="button"
                  aria-label={`第 ${index + 1} 页下移`}
                  disabled={index === pages.length - 1}
                  onClick={() => onChange(movePage(pages, index, 1))}
                >
                  ↓
                </button>
                <button
                  type="button"
                  aria-label={`第 ${index + 1} 页旋转`}
                  onClick={() =>
                    onChange(
                      pages.map((item, number) =>
                        number === index
                          ? { ...item, rotation: (item.rotation + 90) % 360 }
                          : item,
                      ),
                    )
                  }
                >
                  ↻
                </button>
                <button
                  type="button"
                  aria-label={`移除第 ${index + 1} 页`}
                  onClick={() =>
                    onChange(pages.filter((_, number) => number !== index))
                  }
                >
                  ×
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}
      <details>
        <summary
          onClick={() => {
            if (!staged.length)
              void api<{ items: Asset[] }>("/assets/staged")
                .then((value) => setStaged(value.items))
                .catch((reason) => setError(errorText(reason)));
          }}
        >
          恢复已上传的暂存附件
        </summary>
        <div className="staged-list">
          {staged.map((asset) => (
            <button
              type="button"
              key={asset.id}
              onClick={() => {
                const merged = mergePages(
                  pages,
                  asset.pages.map((page) => ({
                    ...page,
                    asset_id: asset.id,
                    rotation: 0,
                  })),
                );
                if (merged.length === pages.length)
                  setError("该附件的页面已在当前清单中。");
                else {
                  setError("");
                  onChange(merged);
                }
              }}
            >
              {asset.original_name} · {asset.page_count} 页
            </button>
          ))}
          {!staged.length && (
            <small className="muted">没有可恢复的暂存附件。</small>
          )}
        </div>
      </details>
    </section>
  );
}
export function mergePages(existing: PageRef[], added: PageRef[]) {
  const ids = new Set(existing.map((page) => page.page_id));
  return [
    ...existing,
    ...added.filter((page) => {
      if (ids.has(page.page_id)) return false;
      ids.add(page.page_id);
      return true;
    }),
  ];
}
