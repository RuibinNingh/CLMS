# 实施契约 v1

应用版本 0.10.2；API 前缀 `/api`；生产前端同源。错误 `{error:{code,message,details}}`，分页 `{items,next_cursor}`，审核列表另有过滤结果 `total`。默认每页 30，配置和 schema 上限均不超过 100。写入为 POST（避免不一致的 CSRF 处理）。所有 ID 为服务端 UUID 前缀，服务器生成时间为 ISO UTC；written_at 保留用户填写的日期/日期时间。

## 数据

Category: id,name,description,language_scope(zh/en/all),sort_order,revision,archived_at。
Prompt: id,title,language,instructions,requirements,source_note,category_ids,rubric|null,materials(PageRef[]),revision,created_at；文字或 materials 至少一种。
Rubric: max_score:number>0, criteria:string, aggregation:none/sum, dimensions:[{name,max_score}]。
PageRef 输入: page_id,rotation(0/90/180/270)。输出追加 asset_id,asset_sha256,source_page(从1开始),order(从1开始),width,height。
Asset: id,sha256,mime,original_name,byte_size,page_count,created_at,original_url,pages:[PageRef]。
Attempt: id,prompt_id,prompt_snapshot,snapshot_hash,written_at|null,duration_minutes|null,reflection,selected_version_id|null,revision,created_at,versions:[Version]。
Version: id,attempt_id,version_no,parent_version_id|null,manifest:[PageRef],manifest_hash,change_note,voided_at,created_at,status(pending/evaluated),evaluations:[Evaluation]。
Evaluation: id,version_id,manifest_hash,prompt_snapshot_hash,payload_schema_version,payload,source,created_at,supersedes_id|null,voided_at。payload 严格采用计划7.3结构，score={value,max_value,rubric_snapshot,dimensions:[{name,value,max_value}]}|null，compared_version_ids 可选。
Review: id,operation_id,kind,source_actor,request_id,revision,original_payload,payload,original_digest,effective_digest,target_snapshot,status,result,created_at,requires_human_review,review_path,editable_fields；revisions/decisions 仅详情返回。kind=category/prompt/submission/revision/evaluation/reflection。review_path 为 `/#/reviews?id={id}`；状态 pending/applied/rejected/withdrawn/conflict/failed，只有 pending 需要人工决定。修改目标的 target_snapshot.before 保留原正式值；评价目标快照包含冻结题目与稿件页清单。

## Web API

- GET /auth/status → {initialized,authenticated,csrf_token?,username?}；POST /auth/bootstrap {username,password,bootstrap_token}；POST /auth/login {username,password}；POST /auth/logout {}。首次 token 来自本机 CLI，bootstrap/login 同源并以 JSON 提交，后续写入带 X-CSRF-Token。
- GET /categories?language=&include_archived=true&cursor=&limit=；POST /categories {name,description?,language_scope?,sort_order?}；POST /categories/{id} {expected_revision,name?,description?,language_scope?,sort_order?,archived?}。全局排序为 sort_order、normalized_name（NFKC+casefold）、id；cursor 用稳定 ID 定位组合排序。
- GET /prompts?q=&language=&category_ids=逗号分隔&status=pending/evaluated&from_date=&to_date=&cursor=&limit=；GET /prompts/{id} → Prompt + attempts；POST /prompts Prompt输入；POST /prompts/{id} {expected_revision,...允许字段}。
- 题目列表返回元数据摘要：instructions 最多 240 字符，另有 attempt_count/latest_written_at/status，不返回 rubric、完整 requirements/source_note/materials 或练习/评价正文。附件与详情单独按 ID 读取。
- POST /assets multipart file → Asset；GET /assets/staged；GET /assets/{id}；GET /assets/{id}/original；GET /pages/{page_id}?rotation=0&quality=normal。
- POST /submissions {prompt_id?:string,prompt?:Prompt输入,inline_categories?:Category输入[],pages:PageRef[],written_at?,duration_minutes?,reflection?,change_note?} → {prompt_id,attempt_id,version_id,path}。prompt_id/prompt 二选一，path 指向精确版本 `/#/prompt/{prompt_id}?version={version_id}`。
- POST /attempts/{id}/versions {parent_version_id,pages,change_note?} → {prompt_id,attempt_id,version_id,path}；GET /attempts/{id}；GET /versions/{id} → Version + prompt_snapshot + prompt_snapshot_hash + prompt_id；POST /attempts/{id} {expected_revision,reflection?,selected_version_id?}。
- GET /attempts?prompt_id=&cursor=&limit= → 练习摘要分页，含 version_count，不展开稿件/评价；题目详情仍返回该题目的练习历史。
- POST /versions/{id}/void {}；POST /evaluations 手工评价payload；POST /evaluations/{id}/void {}；GET /evaluations/{id}。评价输入用 expected_manifest_hash/expected_prompt_snapshot_hash 校验目标，正式输出的实际字段为 manifest_hash/prompt_snapshot_hash。
- GET /reviews?status=&kind=&source=&from_date=&to_date=&cursor=&limit=；GET /reviews/{id}；POST /reviews/{id}/revise {expected_revision,changes}；POST /reviews/{id}/decide {expected_revision,expected_digest,decision:approve/reject}；POST /reviews/batch {items:[决定含id]} → {items:[{id,result?,error?}]}；POST /reviews/{id}/withdraw {expected_revision}。
- 审核列表 status 默认 pending，空值查询全部，processed 查询所有非 pending；结果含 total。决定仅由 Web 会话发起，重复同决定返回原回执；conflict/failed 保留提案且不伪称入档。
- GET /history?prompt_id=&attempt_id=&version_id=&cursor=&limit= → 关联审计分页。
- GET /settings → {version,limits,mcp_endpoint,scopes,data_storage,theme_options}；GET /credentials；POST /credentials {name,scopes,expires_at?} → credential+secret 一次；POST /credentials/{id}/revoke {}。
- GET /health → {status,version}，不泄露路径或业务。

## 分层接口

`backend.app.config.Settings` 提供 data_dir(Path)、媒体限额、public_origin、bootstrap_token_file。
`backend.app.db.base.Database` 提供 engine, session_factory；`db.transaction()` 使用 SQLite BEGIN IMMEDIATE 写事务。SQLAlchemy Session 由调用者管理；领域模块内部只 flush，不 commit。
媒体模块 `upload(session,settings,stream,filename,actor)->dict`、`asset_view(session,asset_id,actor?)`、`page_image(session,settings,page_id,rotation=0,quality='normal',bbox=None)->(bytes,metadata)`、`original_path(...)`、`cleanup(...)`。媒体模型在 db.models: Asset(id,sha256,mime,original_name,byte_size,page_count,storage_key,created_by,created_at)、AssetPage(id,asset_id,source_page,width,height,preview_key)。FileReference(owner_type,owner_id,asset_id) 保护正式和待审引用。
领域入口 `domain.dispatch.apply(session,kind,payload,actor)->dict`；`domain.dispatch.validate(session,kind,payload,actor)->dict`（只读校验）；`domain.query` 返回 JSON。审核模块负责事务、权限、幂等和 FileReference；Web/MCP 不直接实现业务写入。
官方 FastMCP app 挂载 `/mcp`，客户端端点为 `/mcp/`，服务生命周期由主应用驱动。独立 Bearer 中间件每个 HTTP 请求查凭据；工具从官方 Context.request_context.request 读取当前 Bearer，再在事务内推导服务端 actor 并实时校验 scope。工具表按计划第9节全部实现，无批准工具。

## MCP附件输入扩展（0.10.2）

`upload_asset(filename:string,content_base64:string)` 和 `upload_attachment(file:{download_url:string,file_id:string,mime_type?:string,file_name?:string})` 都需 `proposals.write`，返回Asset加 `{status:"staged",next_step,human_review_required_for_archive:true}`。原生工具meta为 `openai/fileParams:["file"]`；输入对象严格白名单，必填仅download_url/file_id。受控域名、安全下载及限额见媒体契约。上传不创建正式记录、不增加schema迁移、不修改已有scope。
