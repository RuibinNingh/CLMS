import { useState } from "react";
import { api, errorText } from "../../shared/api";
import { useLoad } from "../../shared/hooks";
import { saveTheme } from "../../shared/theme";
import type { Credential, Paged, Settings } from "../../shared/types";
import {
  date,
  ErrorNotice,
  Field,
  Loading,
  PageHeading,
  Tag,
} from "../../shared/ui";

const limitLabels: Record<string, string> = {
  image_max_bytes: "单张图片字节上限",
  pdf_max_bytes: "单个 PDF 字节上限",
  pdf_max_pages: "单个 PDF 页数上限",
  version_max_pages: "单稿页数上限",
  image_max_pixels: "图片解码像素上限",
  media_normal_edge: "常规预览长边像素",
  media_high_edge: "高清预览长边像素",
  media_ttl_hours: "暂存保留小时数",
  pdf_render_timeout: "PDF 渲染超时秒数",
  pdf_render_memory_mb: "PDF 渲染内存（MiB）",
  pdf_render_concurrency: "PDF 同时渲染数",
  mcp_max_pages: "MCP 单次页数上限",
  mcp_image_budget: "MCP 图像字节预算",
  mcp_upload_max_bytes: "MCP 原件字节上传上限",
  max_page_size: "列表每页条目上限",
  max_image_bytes: "单张图片字节上限",
  max_pdf_bytes: "单个 PDF 字节上限",
  max_pdf_pages: "单个 PDF 页数上限",
  max_version_pages: "单稿页数上限",
  max_image_pixels: "图片解码像素上限",
  staged_ttl_hours: "暂存保留小时数",
  max_mcp_pages: "MCP 单次页数上限",
  max_mcp_image_bytes: "MCP 图像字节预算",
  preview_max_edge: "预览图长边像素",
};
const scopeLabels: Record<string, string> = {
  "archive.read": "读取正式档案",
  "media.read": "读取原稿页面",
  "proposals.write": "上传附件与提交提案",
};
export function SettingsPage() {
  const settings = useLoad(() => api<Settings>("/settings"));
  const credentials = useLoad(async () => {
    const value = await api<Paged<Credential> | Credential[]>("/credentials");
    return Array.isArray(value) ? value : value.items;
  });
  const [theme, setTheme] = useState(
    localStorage.getItem("clms-theme") || "system",
  );
  const [name, setName] = useState(""),
    [scopes, setScopes] = useState<string[]>([]),
    [expiry, setExpiry] = useState(""),
    [secret, setSecret] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  function changeTheme(choice: string) {
    setTheme(choice);
    saveTheme(choice);
  }
  return (
    <>
      <PageHeading
        title="设置"
        subtitle="阅读偏好、存储限额与外部 MCP 连接。"
      />
      <ErrorNotice
        message={error || settings.error || credentials.error}
        retry={() => {
          settings.reload();
          credentials.reload();
        }}
      />
      <section className="panel form-section">
        <h2>阅读外观</h2>
        <Field label="主题">
          <select
            value={theme}
            onChange={(event) => changeTheme(event.target.value)}
          >
            <option value="system">跟随系统</option>
            <option value="light">浅色纸面</option>
            <option value="dark">深色石墨</option>
          </select>
        </Field>
      </section>
      {settings.loading && <Loading />}
      {settings.data && (
        <>
          <section className="panel form-section">
            <h2>存储与限额</h2>
            <p className="muted">
              版本 {settings.data.version} · 原件与档案持久保存
            </p>
            <p>{settings.data.data_storage}</p>
            <dl className="limits-grid">
              {Object.entries(settings.data.limits).map(([key, value]) => (
                <div key={key}>
                  <dt>{limitLabels[key] || key}</dt>
                  <dd>{value.toLocaleString()}</dd>
                </div>
              ))}
            </dl>
          </section>
          <section className="panel form-section">
            <h2>MCP 连接</h2>
            <p className="muted">
              外部 AI
              读取已归档资料并提交待审提案。凭据仅有所选权限，不能自行批准。
            </p>
            <Field label="MCP 地址">
              <input readOnly value={settings.data.mcp_endpoint} />
            </Field>
            <p className="muted">
              配置 Streamable HTTP 地址与 Bearer 凭据；密钥仅在创建时显示一次。
            </p>
            {secret && (
              <div className="notice warning">
                <strong>新凭据 · 仅显示这一次</strong>
                <Field label="新 MCP 凭据">
                  <input readOnly value={secret} />
                </Field>
                <div className="actions">
                  <button
                    onClick={() =>
                      navigator.clipboard
                        .writeText(secret)
                        .catch(() =>
                          setError("无法自动复制，请手动复制上方凭据。"),
                        )
                    }
                  >
                    复制凭据
                  </button>
                  <button onClick={() => setSecret("")}>
                    已保存，关闭显示
                  </button>
                </div>
              </div>
            )}
            <form
              onSubmit={async (event) => {
                event.preventDefault();
                setBusy(true);
                setError("");
                try {
                  const result = await api<{ secret: string }>("/credentials", {
                    name,
                    scopes,
                    expires_at: expiry ? new Date(expiry).toISOString() : null,
                  });
                  setSecret(result.secret);
                  setName("");
                  credentials.reload();
                } catch (reason) {
                  setError(errorText(reason));
                } finally {
                  setBusy(false);
                }
              }}
            >
              <div className="form-row">
                <Field label="凭据名称">
                  <input
                    required
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                  />
                </Field>
                <Field label="到期时间（可选）">
                  <input
                    type="datetime-local"
                    value={expiry}
                    onChange={(event) => setExpiry(event.target.value)}
                  />
                </Field>
              </div>
              <fieldset>
                <legend>访问权限</legend>
                <div className="check-list">
                  {settings.data.scopes.map((scope) => (
                    <label key={scope}>
                      <input
                        type="checkbox"
                        checked={scopes.includes(scope)}
                        onChange={(event) =>
                          setScopes(
                            event.target.checked
                              ? [...scopes, scope]
                              : scopes.filter((item) => item !== scope),
                          )
                        }
                      />
                      {scopeLabels[scope] || scope}
                    </label>
                  ))}
                </div>
              </fieldset>
              <button className="primary" disabled={busy || !scopes.length}>
                {busy ? "创建中…" : "创建 MCP 凭据"}
              </button>
            </form>
            <div className="credential-list">
              {credentials.data?.map((credential) => (
                <div className="credential-row" key={credential.id}>
                  <div>
                    <strong>{credential.name}</strong>{" "}
                    <Tag>{credential.revoked_at ? "已撤销" : "有效"}</Tag>
                    <p className="muted">
                      {credential.scopes.join(" · ")}
                      <br />
                      到期 {date(credential.expires_at)} · 最近使用{" "}
                      {date(credential.last_used_at)}
                    </p>
                  </div>
                  {!credential.revoked_at && (
                    <button
                      onClick={async () => {
                        if (
                          !window.confirm(
                            "撤销此 MCP 凭据？将立即停止访问，尚未应用的提案也不能执行。",
                          )
                        )
                          return;
                        try {
                          await api(`/credentials/${credential.id}/revoke`, {});
                          credentials.reload();
                        } catch (reason) {
                          setError(errorText(reason));
                        }
                      }}
                    >
                      撤销
                    </button>
                  )}
                </div>
              ))}
            </div>
          </section>
        </>
      )}
      <section className="panel form-section">
        <h2>登录会话</h2>
        <button
          onClick={async () => {
            try {
              await api("/auth/logout", {});
              window.location.reload();
            } catch (reason) {
              setError(errorText(reason));
            }
          }}
        >
          退出登录
        </button>
      </section>
    </>
  );
}
