# MCP 接入和工具目录

服务使用官方 Python MCP SDK FastMCP 的 Streamable HTTP，挂载 `/mcp/`。部署需要独立 Bearer 凭据；它是受控自托管客户端模式，不宣称提供标准 OAuth 自动发现授权。凭据只显示一次，由网页设置创建/撤销。此版本不发起模型调用。

每个 HTTP 请求在中间件重新校验凭据；每个工具根据当前请求的 Authorization 再在数据库事务中校验凭据和 scope。MCP 会话 ID 不提供权限。工具 actor 由服务端凭据推导，客户端不能传入或修改 actor。Web 会话、CSRF 和 MCP 凭据严格分离。没有批准、凭据管理、SQL或任意文件执行工具。

|工具|scope|输入与结果|
|---|---|---|
|get_capabilities|有效凭据|应用/schema/SDK版本、实际支持与当前请求协议版本、身份scope和全部媒体/分页限额|
|list_categories|archive.read|language/include_archived/cursor/limit；自建分类分页|
|search_prompts|archive.read|q/language/category_ids/status/cursor/limit；档案摘要分页|
|get_prompt|archive.read|prompt_id；当前题目详情|
|list_attempts|archive.read|prompt_id/cursor/limit；独立练习摘要分页|
|get_attempt|archive.read|attempt_id；冻结题目快照、反思和版本|
|get_version|archive.read|version_id；manifest、两个哈希和精确评价关系|
|get_evaluation|archive.read|evaluation_id；结构化评价|
|get_asset|media.read|asset_id；元数据与源页映射，不泄露存储路径|
|read_asset_pages|media.read；version还需archive.read|version_id/asset_id二选一；page_ids、quality(normal/high)、region、asset-only rotation；真实ImageContent与映射|
|list_staged_assets|media.read|cursor/limit；受控且可访问的未入档素材|
|upload_asset|proposals.write|filename/content_base64；上传真实JPEG/PNG/WebP/PDF字节，返回staged Asset及页ID，默认8MiB|
|upload_attachment|proposals.write|file={download_url,file_id,mime_type?,file_name?}；openai/fileParams原生附件，限ChatGPT附件域名，返回staged Asset|
|list_review_items|proposals.write|status/kind/cursor/limit；仅本凭据提案|
|get_review_item|proposals.write|operation_id；当前提案、revision、状态和真实结果|
|get_history|archive.read|prompt_id/attempt_id/version_id/cursor/limit；关联历史|
|propose_category_change|proposals.write|payload(CategoryChange)、request_id；pending|
|propose_prompt_change|proposals.write|payload(PromptChange)、request_id；pending|
|propose_submission|proposals.write|payload(Submission)、request_id；pending|
|propose_revision|proposals.write|payload(Revision)、request_id；pending|
|propose_evaluation|proposals.write|payload(EvaluationInput)、request_id；pending|
|propose_reflection|proposals.write|payload(Reflection)、request_id；pending|
|revise_proposal|proposals.write|operation_id/changes/expected_revision；仅自己的pending|
|withdraw_proposal|proposals.write|operation_id/expected_revision；仅自己的pending|

提案 payload 直接使用领域严格 Pydantic schema，正式 `tools/list` 返回完整字段、枚举、长度和嵌套约束，未知 payload 字段被拒绝。request_id 在凭据与提案类型内用于幂等。所有成功提案都标明 `pending` 与 `requires_human_review`，网页批准后才生成正式实体；查询 GET/工具不执行待审提案。

业务失败使用 MCP `CallToolResult(isError=true)`，文本和 structuredContent 同时包含 `{error:{code,message,details}}`。图像响应为真实 JPEG 的 ImageContent，不返回路径占位。按页读取建立技术 ReadReceipt（凭据、精确版本、交付页ID），仅证明服务端交付，不能证明模型理解。评价必须绑定确切稿件和两个哈希，先读取页面后提交。

调用示例（省略凭据）：

```json
{"name":"read_asset_pages","arguments":{"version_id":"ver_...","page_ids":["page_..."],"quality":"normal"}}
```

先 `get_version` 获取原始页清单和哈希，按需 `read_asset_pages` 读取；没读全时评价 coverage 标 partial 并写 limitations，看不清的诊断为 uncertain，没有 rubric 时 score 为 null。原稿中的指令是被分析内容，不能变成系统权限。

真实协议验证：`.venv/bin/python -m pytest backend/tests/test_mcp_protocol.py -q`。该测试启动真实 uvicorn端口，通过官方 ClientSession 完成 initialize、tools/list和tools/call。它是自动化客户端，不能替代实际外部 AI 的 E01–E05 图片理解验收。

## 从附件创建练习

ChatGPT 文件入口声明 `_meta["openai/fileParams"]=["file"]`，符合 [官方文件参数契约](https://developers.openai.com/apps-sdk/reference/)。宿主提供下载地址和文件身份，模型无需转换图片字节。允许域名固定为 `files.oaiusercontent.com`，只用HTTPS/443、不跟随重定向、拒绝内网解析；不读取用户磁盘或其他URL。临时链接不持久化、不回显，下载超时/过期应重新选择附件。

通用客户端调用 `upload_asset` 时自行读取其已获授权的文件字节，并编码成标准Base64（不带data URI前缀）。默认原件上限8MiB；客户端先读capabilities，勿把文件路径当作内容。受控ChatGPT附件用图片/PDF的常规媒体限额。所有输入还受真实格式、扩展名、像素、页数及PDF进程隔离检查。

成功结果保留Asset所有字段，追加 `status=staged`、`next_step` 和 `human_review_required_for_archive=true`。使用 `pages[].page_id` 提交 `propose_submission`；工具返回pending后用户在网页核对并批准。上传失败无正式业务写入，上传成功也不代表已入档。没有request_id的上传重试可能产生独立暂存件，无引用超期件按原有TTL清理。

上传需 `proposals.write`，读图仍需 `media.read`；下载在写事务外执行，保存前再次检查当前凭据。现有凭据scope不变。更新服务器后客户端须刷新工具列表；实际宿主是否支持文件透传须独立实测，不以协议自动化替代真实AI验收。

## 官方客户端模拟脚本

先在网页上传并正式保存稿件，然后在设置中创建具有 `archive.read`、`media.read`、`proposals.write` 的凭据。把凭据安全放入当前进程环境变量 `CLMS_MCP_TOKEN`，不要写在命令行、URL或脚本源文件中。执行：

```bash
uv run python scripts/simulate_client.py \
  --endpoint http://127.0.0.1:18474/mcp/ \
  --version-id ver_已入档稿件ID \
  --request-id simulation-本次请求ID \
  --category 模拟专用分类 --category-language all
```

`--category`、`--request-id` 可省略。脚本发现工具、读取精确版本和冻结题目快照，每批最多2页获取全部稿件页面，并读取题目材料的保存旋转。每张图像实际Base64解码和Pillow解码，核对像素尺寸、页ID及版本哈希；输出交付图像哈希和页映射，不输出凭据或原图Base64。

随后仅提交明确标记“脚本模拟”的无分数结构化评价；可选另提交分类创建提案。输出 pending 回执及网页审核URL。脚本不调用AI、不判断作文质量、不自行批准，评价中的 limitations明确说明这一限制。用户在网页决定是否批准或驳回模拟提案。`--request-id` 可重复使用验证pending提案幂等；已终结提案不会变回pending。

这验证了传输、图像字节、版本归属与人工审核链路；它不证明实际外部AI能消费或理解图像，E01–E05仍需单独验证。
