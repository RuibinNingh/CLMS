"""Finite public tool catalog; proposal inputs use the domain's strict Pydantic schemas."""
from mcp.server.fastmcp import Context
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import ToolAnnotations

from backend.app.auth.service import recheck_actor
from backend.app.config import SCOPES
from backend.app.domain import query, reviews
from backend.app.domain.schemas import (
    CategoryChange,
    EvaluationInput,
    PromptChange,
    Reflection,
    Revision,
    Submission,
)
from backend.app.media import asset_view, staged_assets

from .media_tools import read_pages
from .uploads import CHAT_FILE_HOST, ChatFile, chat_file_stream, stage_base64, stage_chat_file


def register_tools(server, runtime, sdk_version, app_version):
    @server.tool(description="查询应用、schema、SDK和限额；Bearer是受控自托管凭据，不是通用OAuth。")
    async def get_capabilities(ctx: Context):
        def capabilities(session, actor):
            credential = recheck_actor(session, actor)
            return {"application": "CLMS 作文档案馆", "application_version": app_version,
                    "schema_version": 1, "mcp_sdk_version": sdk_version,
                    "supported_protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
                    "request_protocol_version": ctx.request_context.request.headers.get("mcp-protocol-version"),
                    "transport": "streamable-http", "authentication": "restricted-bearer",
                    "available_scopes": list(SCOPES), "credential_scopes": credential.scopes,
                    "limits": runtime.settings.limits, "human_review_required": True,
                    "attachment_upload": {"chatgpt_tool": "upload_attachment", "bytes_tool": "upload_asset",
                        "chatgpt_download_hosts": [CHAT_FILE_HOST], "creates_formal_records": False},
                    "ocr": False, "model_calls": False}
        return await runtime.call(ctx, None, capabilities)

    @server.tool(description="先查询用户自建分类避免重复。初始分类为空；停用分类保留历史引用。")
    async def list_categories(ctx: Context, language: str | None = None, include_archived: bool = False,
                              cursor: str | None = None, limit: int = 30):
        return await runtime.call(ctx, "archive.read", lambda s, a: query.list_categories(
            s, language=language, include_archived=include_archived, cursor=cursor, limit=limit))

    @server.tool(description="分页检索手填题目、分类及保存评价，不搜索原稿全文。")
    async def search_prompts(ctx: Context, q: str = "", language: str | None = None,
                             category_ids: list[str] | None = None, status: str | None = None,
                             cursor: str | None = None, limit: int = 30):
        return await runtime.call(ctx, "archive.read", lambda s, a: query.search_prompts(
            s, q=q, language=language, category_ids=category_ids, status=status, cursor=cursor, limit=limit))

    @server.tool(description="当前题目详情；评价时使用练习保存的快照，不能用当前题目覆盖历史依据。")
    async def get_prompt(ctx: Context, prompt_id: str):
        return await runtime.call(ctx, "archive.read", lambda s, a: query.get_prompt(s, prompt_id))

    @server.tool(description="同题每次重新写作均为独立练习。分页返回练习摘要和版本数。")
    async def list_attempts(ctx: Context, prompt_id: str, cursor: str | None = None, limit: int = 30):
        return await runtime.call(ctx, "archive.read", lambda s, a: query.list_attempts(s, prompt_id, cursor, limit))

    @server.tool(description="评价前获取本次练习冻结的题目、材料和rubric快照，以及反思和版本清单。")
    async def get_attempt(ctx: Context, attempt_id: str):
        return await runtime.call(ctx, "archive.read", lambda s, a: query.get_attempt(s, attempt_id))

    @server.tool(description="获取精确稿件页清单和两个哈希。评价绑定version_id，不使用最新稿作为目标。")
    async def get_version(ctx: Context, version_id: str):
        return await runtime.call(ctx, "archive.read", lambda s, a: query.get_version(s, version_id))

    @server.tool(description="查看结构化评价、来源和精确版本关系；新版不会继承旧稿评价。")
    async def get_evaluation(ctx: Context, evaluation_id: str):
        return await runtime.call(ctx, "archive.read", lambda s, a: query.get_evaluation(s, evaluation_id))

    @server.tool(description="受控文件的元数据和原始页映射；路径不公开，原件需要独立网页登录读取。")
    async def get_asset(ctx: Context, asset_id: str):
        return await runtime.call(ctx, "media.read", lambda s, a: asset_view(s, asset_id, a))

    @server.tool(description="必须实际读取本稿图像后评价。version_id/asset_id二选一，默认1页最多2页。"
                             "返回真实ImageContent及精确页映射；region为旋转后[x,y,width,height]归一化区域。asset可指定rotation；version固定保存旋转。")
    async def read_asset_pages(ctx: Context, version_id: str | None = None, asset_id: str | None = None,
                               page_ids: list[str] | None = None, quality: str = "normal",
                               region: list[float] | None = None, rotation: int = 0):
        return await runtime.call(ctx, "media.read", lambda s, a: read_pages(s, runtime.settings, a,
            version_id=version_id, asset_id=asset_id, page_ids=page_ids, quality=quality, region=region, rotation=rotation))

    @server.tool(description="仅列出当前凭据可访问的受控暂存附件；不导入聊天路径或任意URL。")
    async def list_staged_assets(ctx: Context, cursor: str | None = None, limit: int = 30):
        return await runtime.call(ctx, "media.read", lambda s, a: staged_assets(s, a, cursor, limit))

    @server.tool(description="上传客户端实际读取的 JPEG/PNG/WebP/PDF 原件字节（标准 Base64，不是路径、URL或data URI）。"
                             "仅暂存附件，返回可用于 propose_submission/propose_revision 的 page_id；不代表练习已入档。",
                 annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
    async def upload_asset(ctx: Context, filename: str, content_base64: str):
        return await runtime.call(ctx, "proposals.write", lambda s, a: stage_base64(
            s, runtime.settings, a, filename, content_base64))

    @server.tool(description="接收用户在 ChatGPT 中提供的作文图片/PDF附件并保存原件。"
                             "由宿主传入附件 file 对象；仅允许 ChatGPT 附件域名，不接受自填URL或路径。"
                             "上传只暂存，下一步用返回的 page_id 调用 propose_submission，等待网页审核。",
                 meta={"openai/fileParams": ["file"]},
                 annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
    async def upload_attachment(ctx: Context, file: ChatFile):
        return await runtime.call(ctx, "proposals.write", lambda s, a, prepared: stage_chat_file(
            s, runtime.settings, a, prepared), prepare=lambda: chat_file_stream(runtime.settings, file))

    server._tool_manager.get_tool("upload_asset").parameters["properties"]["content_base64"]["maxLength"] = (
        4 * ((runtime.settings.mcp_upload_max_bytes + 2) // 3))

    @server.tool(description="仅查看本凭据提出的提案。工具成功表示pending，不表示业务已入档。")
    async def list_review_items(ctx: Context, status: str = "pending", kind: str | None = None,
                                cursor: str | None = None, limit: int = 30):
        return await runtime.call(ctx, "proposals.write", lambda s, a: reviews.list_items(
            s, a, status=status, kind=kind, cursor=cursor, limit=limit))

    @server.tool(description="查询自己提案的当前revision、状态及真实应用结果；不能推断网页已经批准。")
    async def get_review_item(ctx: Context, operation_id: str):
        return await runtime.call(ctx, "proposals.write", lambda s, a: reviews.get_item(s, operation_id, a))

    @server.tool(description="分页查询档案的实际操作与评价历史；读取不会重新执行任何提案。")
    async def get_history(ctx: Context, prompt_id: str | None = None, attempt_id: str | None = None,
                           version_id: str | None = None, cursor: str | None = None, limit: int = 30):
        return await runtime.call(ctx, "archive.read", lambda s, a: query.get_history(s,
            prompt_id=prompt_id, attempt_id=attempt_id, version_id=version_id, cursor=cursor, limit=limit))

    @server.tool(description="提出创建、修改或停用自定义分类。已有分类修改带expected_revision；等待人工审核。")
    async def propose_category_change(ctx: Context, payload: CategoryChange, request_id: str):
        return await runtime.call(ctx, "proposals.write", lambda s, a: reviews.propose(
            s, "category", payload.model_dump(exclude_unset=True), a, request_id))

    @server.tool(description="提出题目/材料/评分标准/分类修改，严格字段白名单。等待人工审核后正式生效。")
    async def propose_prompt_change(ctx: Context, payload: PromptChange, request_id: str):
        return await runtime.call(ctx, "proposals.write", lambda s, a: reviews.propose(
            s, "prompt", payload.model_dump(exclude_unset=True), a, request_id))

    @server.tool(description="以已暂存页创建独立练习和V1，可内联题目及分类；一次人工审核原子入档。")
    async def propose_submission(ctx: Context, payload: Submission, request_id: str):
        return await runtime.call(ctx, "proposals.write", lambda s, a: reviews.propose(
            s, "submission", payload.model_dump(exclude_unset=True), a, request_id))

    @server.tool(description="给已有练习提出新稿件版本，保留父版本原件。等待人工审核，不能覆盖旧manifest。")
    async def propose_revision(ctx: Context, payload: Revision, request_id: str):
        return await runtime.call(ctx, "proposals.write", lambda s, a: reviews.propose(
            s, "revision", payload.model_dump(exclude_unset=True), a, request_id))

    @server.tool(description="在读取精确版本原图后提出结构化评价。问题/改进/待确认分开；缺页标partial；"
                             "无rubric时score=null。带version_id及两个哈希，仅保存待审。")
    async def propose_evaluation(ctx: Context, payload: EvaluationInput, request_id: str):
        return await runtime.call(ctx, "proposals.write", lambda s, a: reviews.propose(
            s, "evaluation", payload.model_dump(exclude_unset=True), a, request_id))

    @server.tool(description="提出练习反思/备注修改；带expected_revision，不改变任何版本归属。")
    async def propose_reflection(ctx: Context, payload: Reflection, request_id: str):
        return await runtime.call(ctx, "proposals.write", lambda s, a: reviews.propose(
            s, "reflection", payload.model_dump(exclude_unset=True), a, request_id))

    @server.tool(description="仅修订自己pending提案的允许字段，带expected_revision；不能改来源/身份/目标。")
    async def revise_proposal(ctx: Context, operation_id: str, changes: dict, expected_revision: int):
        return await runtime.call(ctx, "proposals.write", lambda s, a: reviews.revise(
            s, operation_id, changes, expected_revision, a))

    @server.tool(description="仅撤回自己的pending提案，带expected_revision；终态不能重新执行。")
    async def withdraw_proposal(ctx: Context, operation_id: str, expected_revision: int):
        return await runtime.call(ctx, "proposals.write", lambda s, a: reviews.withdraw(
            s, operation_id, expected_revision, a))
