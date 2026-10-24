# API、认证与运行

FastAPI API 前缀 `/api`。完整路由和字段在 `../docs/architecture/contract.md`。错误统一为 `{error:{code,message,details}}`，列表为 `{items,next_cursor}`。写入使用 POST 和严格白名单；分页有配置上限。GET 只读，不批准或恢复执行。

题目列表说明截断至 240 字符，不包含 rubric、完整要求、来源备注、材料页、练习或评价全文；详情按 ID 单独读取。分类按 sort_order、normalized_name（NFKC+casefold）、ID 全局排序，cursor 以稳定 ID 定位这个组合排序；审核列表另返回过滤结果 `total`。

## Web

同源页面 `/` 与构建后的 `/assets/`、`/icons/` 由服务提供公开静态资源。`icons` 只包含随应用构建的品牌 SVG/ICO/Apple touch icon，不挂载任意 public 或数据目录；作文原件和派生页仍经过下述鉴权媒体接口。

首次本机 CLI 创建 `bootstrap.token`，网页用令牌设置管理员密码（12–256 字符）。登录创建独立 HttpOnly/SameSite 会话 Cookie，HTTPS 使用 Secure。初始化/登录校验 Origin 和 JSON；后续 POST 同时校验同源及 `X-CSRF-Token`。受保护写请求在读取或解析 JSON/multipart 正文前验证会话与 CSRF，路由执行前再次检查。管理员退出撤销会话。MCP Bearer 不能授权 Web API。

类别、题目、提交、新稿、人工评价、反思、作废和凭据管理通过网页 API。审核 `revise`/`decide`/`withdraw` 带 expected_revision，决定同时带 expected_digest。批量决定逐项返回真实结果或错误。

## 媒体

multipart POST `/assets` 上传实际文件，鉴权 GET `/assets/{id}/original` 下载原始字节，GET `/pages/{page_id}` 返回派生图。不公开静态原件目录，不接受用户路径或任意 URL。文件大小、图像像素、PDF 页数、渲染时间/内存/并发和 MCP 响应预算集中在 Settings，公开安全限额到 capabilities/settings。

支持 JPEG、PNG、WebP、普通 PDF。损坏、加密、假扩展名、路径穿越、符号链接和越界页明确失败。PDF 在受限工作进程渲染，无脚本执行或文本提取。

上传 body 在 multipart 暂存前受 ASGI 字节预算限制，既检查 Content-Length，也累积实际 chunked 消息，超限返回 413；文件格式与单文件限额随后继续校验。

## CLI 与部署

```bash
uv run --frozen python -m backend.app.cli init
uv run --frozen alembic upgrade head
uv run --frozen python -m backend.app.cli serve
uv run --frozen python -m backend.app.cli cleanup
```

`cleanup` 默认只列出符合 TTL 与引用条件的暂存候选；实际清理须加 `--apply`，仍在事务内复查引用，只在提交后移除文件。

`CLMS_DATA_DIR` 指向新数据目录；`CLMS_PUBLIC_ORIGIN` 是用户真实访问 origin；`CLMS_SECURE_COOKIE=true` 用于 HTTPS。健康检查 `/api/health` 仅返回状态和应用版本。生产静态前端来自构建产物，字体/资源不依赖 CDN。

官方 MCP SDK 使用 stateless Streamable HTTP 和 JSON response，客户端端点为 `/mcp/`，主应用驱动 lifecycle，独立凭据逐请求/逐工具授权。scope 只有 `archive.read`、`media.read`、`proposals.write`。受限 Bearer 不是 OAuth，客户端兼容需实测，不声称所有客户端支持。运维命令、数据卷、代理边界、备份和回滚见 operations 文档。

## MCP 上传

0.10.2 新增 `upload_attachment` 原生ChatGPT附件和 `upload_asset` Base64字节入口，均使用独立Bearer的 `proposals.write`，不授权Web API。共享媒体校验、来源隔离、页ID及TTL；后续正式练习/版本仍走人工审核。Base64默认8MiB，MCP JSON在解析前按编码开销限额，拒绝超长及chunked正文；原生附件常规图片/PDF限额不变。详见 `ai.md` 和 `../docs/mcp/tools.md`。
