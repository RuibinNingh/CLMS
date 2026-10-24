import type { Auth } from "./types";

let csrf = "";
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public details?: unknown,
    public status?: number,
  ) {
    super(message);
  }
}
export function setAuth(auth: Auth) {
  csrf = auth.csrf_token || "";
}
export async function api<T>(path: string, data?: unknown): Promise<T> {
  const multipart = data instanceof FormData;
  const response = await fetch(`/api${path}`, {
    method: data === undefined ? "GET" : "POST",
    credentials: "same-origin",
    headers:
      data === undefined
        ? {}
        : {
            ...(multipart ? {} : { "Content-Type": "application/json" }),
            ...(csrf ? { "X-CSRF-Token": csrf } : {}),
          },
    body:
      data === undefined ? undefined : multipart ? data : JSON.stringify(data),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = body.error || {};
    throw new ApiError(
      error.code || "request_failed",
      error.message || `请求失败 (${response.status})`,
      error.details,
      response.status,
    );
  }
  return body as T;
}
export function params(
  values: Record<string, string | number | null | undefined>,
) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value !== "" && value != null) query.set(key, String(value));
  return query.size ? `?${query}` : "";
}
export function errorText(error: unknown) {
  if (error instanceof ApiError && Array.isArray(error.details)) {
    const fields = error.details
      .map((item) => {
        if (!item || typeof item !== "object") return "";
        const issue = item as { loc?: unknown[]; msg?: string };
        return issue.msg
          ? `${issue.loc?.filter((part) => part !== "body").join(".") || "表单"}：${issue.msg}`
          : "";
      })
      .filter(Boolean);
    if (fields.length) return `${error.message} · ${fields.join("；")}`;
  }
  return error instanceof Error ? error.message : "操作失败，请重试。";
}
export function pageUrl(pageId: string, rotation = 0) {
  return `/api/pages/${encodeURIComponent(pageId)}?rotation=${rotation}&quality=normal`;
}
export function originalUrl(assetId: string) {
  return `/api/assets/${encodeURIComponent(assetId)}/original`;
}
