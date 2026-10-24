# MCP 与外部评价

CLMS 不配置、不调用任何模型；AI 对话在外部客户端发生。没有内置助手、模型运行队列、OCR、全稿转写或 Agent harness。官方 Python MCP SDK 提供 Streamable HTTP，Web/MCP 共用领域服务。

## 权限

端点 `/mcp/`，每个 HTTP 请求重新检查独立 Bearer 凭据的到期与撤销状态。工具再检查当前 scope：`archive.read`、`media.read`、`proposals.write`。协议 session ID 不能替代身份。没有 admin、approve、任意文件、任意 URL 下载、SQL 或 HTTP 转发工具。

只读查询不执行提案。默认只能读取当前凭据创建的待审提案，网页管理员可读取全部。撤销凭据后旧连接失效，其 pending 提案也不得继续批准。

## 工具目录

只读：`get_capabilities`、`list_categories`、`search_prompts`、`get_prompt`、`list_attempts`、`get_attempt`、`get_version`、`get_evaluation`、`get_asset`、`read_asset_pages`、`list_staged_assets`、`list_review_items`、`get_review_item`、`get_history`。

写入提案：`propose_category_change`、`propose_prompt_change`、`propose_submission`、`propose_revision`、`propose_evaluation`、`propose_reflection`；另有 `revise_proposal`、`withdraw_proposal`，仅能操作自己 pending 提案。工具输入是严格 schema，必须提供 request ID；修改既有目标携带 revision/hash。

评价 schema 按计划第 7.3 节及实施契约。批改先读 Attempt 的题目/rubric 快照与 Version 的页面，随后针对稳定 version ID 和两个 hash 提案。不能把“最新稿”当持久目标。每种问题包含 kind、理由、建议及页面定位，允许 quote、bbox 为空；看不清标 uncertain，缺页标 partial。

`read_asset_pages` 返回实际 image content、精确页映射、受限页数和响应预算。PDF 逐页栅格化，页号不是稿件排序号。read_receipt 只证明服务器交付页面，不能证明模型阅读或理解。

## 附件录入（0.10.2）

`upload_attachment(file)` 声明 `_meta["openai/fileParams"]=["file"]`；file 包含必填 `download_url`、`file_id` 和可选 `mime_type`、`file_name`。支持宿主提供附件的 ChatGPT 客户端可直接传入图片/PDF，不要求模型生成 Base64。仅接受 `https://files.oaiusercontent.com/`，端口443，无用户名密码；拒绝重定向、内网解析及其他域名。链接只用于本次受限流式下载，不存库、不回显，也不转发 MCP Bearer/Cookie。下载前后分别核对 `proposals.write`、撤销及到期，下载不占用 SQLite 写事务。

其他 MCP 客户端可用 `upload_asset(filename,content_base64)` 上传实际原件的标准 Base64；默认原始字节8MiB，完整 MCP 请求上限为对应 Base64 长度加64KiB。网页/ChatGPT附件仍受图片25MiB、PDF100MiB和既有解码/渲染限额约束。`get_capabilities.attachment_upload` 宣告工具和允许域名，`limits.mcp_upload_max_bytes` 公布字节入口限额。

两个工具均需 `proposals.write`；只创建由当前凭据拥有的暂存 Asset/页面。返回 `status=staged` 和真实页 ID，不生成正式题目/练习/版本。先按需 `read_asset_pages(asset_id)` 查看，再把页ID用于 `propose_submission` 或 `propose_revision`，由网页审核入档。正式引用建立前，其他 MCP 凭据不可读取或提交这些页面。刷新/重新扫描客户端工具后才会发现新入口；宿主不传附件对象时应准确说明限制，不尝试任意路径/URL。

文件参数声明依据 [OpenAI Apps SDK reference](https://developers.openai.com/apps-sdk/reference/)。真实 ChatGPT 附件透传与模型识图仍须 E01–E05 单独记录；自动化使用官方SDK和受控下载响应。

## 客户端验收边界

官方 SDK 经实际 TCP 端口调用证明协议实现；脚本模拟评价者证明 pending → 网页决定 → 正确版本评价的闭环。二者不等于真实外部 AI。用户当前选择先执行脚本模拟自测，实际外部 AI E01–E05 保持未执行。

真实客户端接入时记录客户端名称/版本、鉴权方式、协议协商版本、模型识图证据、pending 回执及网页入档关系，见 `../docs/plans/essay-archive-rebuild/external-client-verification.md`。原稿内的命令只是待分析内容，不能授权任何系统操作。
