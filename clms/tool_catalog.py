"""Shared, allowlisted learning tools for the global assistant and external MCP.

Each tool has one schema, one permission classification, and one scope set.
Adapters can present different transports; no transport reimplements a write.
"""

import copy
import math
import re

from . import ai_review, creation, drafts, essays, library, sessions, taxonomy
from .harness import Aborted, Tool


def obj(properties=None, required=None, **extra):
    return {"type": "object", "properties": properties or {}, "required": required or [],
            "additionalProperties": False, **extra}


def string(maximum=100000, **extra):
    return {"type": "string", "maxLength": maximum, **extra}


ID = string(160, minLength=1)
TEXT = string()
NUMBER = {"type": "number"}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 100}
OFFSET = {"type": "integer", "minimum": 0}
STRINGS = {"type": "array", "items": TEXT, "maxItems": 100}
IDS = {"type": "array", "items": ID, "minItems": 1, "maxItems": 500}
GENRE = string(20, enum=["modern", "classical", "poetry", "dictation"])
FREE_OBJECT = {"type": "object", "additionalProperties": True}


def validate(schema, value, path="参数"):
    """Validate recursively at the server boundary, including nested unknown fields."""
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    checks = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
              "string": lambda x: isinstance(x, str), "boolean": lambda x: isinstance(x, bool),
              "integer": lambda x: type(x) is int,
              "number": lambda x: type(x) in (int, float) and math.isfinite(x), "null": lambda x: x is None}
    if kind and not any(checks.get(k, lambda _: False)(value) for k in kinds):
        raise ai_review.ReviewError("invalid_arguments", path + " 类型不正确")
    if "enum" in schema and value not in schema["enum"]:
        raise ai_review.ReviewError("invalid_arguments", path + " 不在可选值中")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - props.keys():
            raise ai_review.ReviewError("invalid_arguments", path + " 含未开放字段")
        if set(schema.get("required", [])) - value.keys():
            raise ai_review.ReviewError("invalid_arguments", path + " 缺少必填字段")
        for key, field in value.items():
            if key in props:
                validate(props[key], field, path + "." + key)
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 10000):
            raise ai_review.ReviewError("invalid_arguments", path + " 条目数量不合法")
        for n, field in enumerate(value):
            if schema.get("items"):
                validate(schema["items"], field, path + f"[{n}]")
    if isinstance(value, str) and not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 1000000):
        raise ai_review.ReviewError("invalid_arguments", path + " 文本长度不合法")
    if isinstance(value, str) and schema.get("pattern") and not re.search(schema["pattern"], value):
        raise ai_review.ReviewError("invalid_arguments", path + " 文本格式不合法")
    if type(value) in (int, float):
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ai_review.ReviewError("invalid_arguments", path + " 数值超出范围")


def _version(vault, version_id):
    result = essays.version_detail(vault, version_id)
    keys = ("id", "prompt_id", "attempt_id", "number", "status", "revision", "text", "created_at",
            "evaluations", "adopted_evaluation_id", "notes", "classifications", "prompt")
    out = {key: result.get(key) for key in keys}
    out["images_count"] = len(result.get("images", []))
    if result["status"] != "confirmed":
        out["text"] = ""
    return out


def _image(vault, args):
    from .mcp.images import read_essay_image
    return read_essay_image(vault, args["version_id"], args.get("image_index", 0))


def build_tools(vault, source="assistant", actor=None):
    if source not in {"assistant", "mcp", "entry"}:
        raise ValueError("工具来源不合法")
    actor, tools = dict(actor or {}), []

    def add(name, description, parameters, fn, scopes, permission="read", domain_tool=None):
        schema = copy.deepcopy(parameters)
        if permission != "read":
            schema["properties"]["request_id"] = string(128, minLength=1, pattern=r"^[^\x00-\x1f?#/\\]{1,128}$",
                                                          description="本次写请求的幂等编号")
            schema["required"].append("request_id")

        def execute(args, ctx):
            validate(schema, args)
            if ctx is not None and getattr(ctx, "aborted", False):
                raise Aborted()
            if source == "mcp":
                authorize = getattr(ctx, "authorize", None)
                if not callable(authorize):
                    raise ai_review.ReviewError("forbidden", "外部调用必须经实时密钥授权", 403)
                authorize()
            if permission == "read":
                return fn(args)
            payload = {key: value for key, value in args.items() if key != "request_id"}
            origin_actor = dict(actor)
            if source in {"assistant", "entry"} and getattr(ctx, "call", None):
                origin_actor["call_id"] = str(ctx.call["id"])
            return ai_review.propose(vault, source, domain_tool, args["request_id"], payload, origin_actor)

        tool = Tool(name, description, schema, execute)
        tool.permission, tool.scopes, tool.domain_tool = permission, set(scopes), domain_tool
        tools.append(tool)

    read = {"clms:read"}
    add("list_taxonomy", "读取语文板块及用户题型。", obj(), lambda a: taxonomy.taxonomy_payload(vault), read)
    add("search_items", "按关键词和板块、题型、状态查询题库。", obj({"query": string(300), "genre": GENRE,
        "qtype": string(200), "status": string(40), "sort": string(30), "offset": OFFSET, "limit": LIMIT}),
        lambda a: library.list_items(vault, q=a.get("query", ""), genre=a.get("genre", ""), qtype=a.get("qtype", ""),
        status=a.get("status", ""), sort=a.get("sort", "priority"), offset=a.get("offset", 0), limit=a.get("limit", 30)), read)
    add("get_item", "读取指定正式题目、答案、材料和复习记录。", obj({"item_id": ID}, ["item_id"]),
        lambda a: library.item_detail(vault, a["item_id"]), read)
    add("get_material", "读取指定材料的原文和题目。", obj({"material_id": ID}, ["material_id"]),
        lambda a: library.material_detail(vault, a["material_id"]), read)
    add("get_overview", "读取学习概况、到期情况及薄弱题型。", obj(), lambda a: sessions.summary(vault), read)
    add("get_recommendations", "按时长和板块推荐题目，尚不创建正式复习。", obj({"minutes": {"type": "number", "minimum": 1,
        "maximum": 1440}, "genres": {"type": "array", "items": GENRE, "maxItems": 4}, "fill": {"type": "boolean"}}),
        lambda a: sessions.plan(vault, a.get("minutes"), a.get("genres"), a.get("fill", True)), read)
    add("list_sessions", "读取已有正式复习及进度。", obj(), lambda a: {"sessions": sessions.list_sessions(vault)}, read)
    add("get_session", "读取指定正式复习的题目和进度。", obj({"session_id": ID}, ["session_id"]),
        lambda a: sessions.view(vault, a["session_id"]), read)
    add("list_drafts", "查询尚未入库的录入草稿。", obj({"query": string(300), "view": string(30), "offset": OFFSET,
        "limit": LIMIT}), lambda a: drafts.list_drafts(vault, a.get("view", "active"), a.get("query", ""),
        a.get("offset", 0), a.get("limit", 30)), read)
    add("get_draft", "读取草稿及当前内容版本。", obj({"draft_id": ID}, ["draft_id"]),
        lambda a: drafts.view(vault, a["draft_id"]), read)
    add("get_operation", "查询本人写请求的审核及执行结果；不批准操作。", obj({"operation_id": ID}, ["operation_id"]),
        lambda a: ai_review.get(vault, a["operation_id"], key_id=actor.get("key_id") if source == "mcp" else None), read)

    # Groups remain the existing draft schema, rather than a second question model.
    item_props = {key: string() for key in creation.EDITABLE - {"score", "blank_lines"}}
    item_props.update(score=NUMBER, blank_lines={"type": "integer", "minimum": 0, "maximum": 1000}, iid=ID)
    group = obj({"gid": ID, "genre": GENRE, "material": obj({key: TEXT for key in creation.MATERIAL_EDITABLE}),
                 "items": {"type": "array", "items": obj(item_props), "maxItems": 500},
                 "dictation": {"type": "array", "items": obj({"iid": ID, "template": TEXT, "source": TEXT,
                    "blanks": {"type": ["array", "object"], "additionalProperties": True}, "qtype": TEXT}), "maxItems": 500}})
    groups = {"type": "array", "items": group, "maxItems": 30}
    add("create_draft", "创建未入库草稿，自动留痕；正式录入由用户校对并入库。", obj({"genre": GENRE, "name": string(200),
        "hint": TEXT, "groups": groups}), None, {"draft:create"}, "auto", "draft.create")
    add("update_draft", "按当前版本修改未入库草稿，冲突时请刷新。", obj({"draft_id": ID, "expected_revision":
        {"type": "integer", "minimum": 0}, "groups": groups}, ["draft_id", "expected_revision", "groups"]),
        None, {"clms:read", "draft:update"}, "auto", "draft.update")
    changes = {key: string() for key in creation.EDITABLE - {"score", "blank_lines"}}
    changes.update(score=NUMBER, blank_lines={"type": "integer", "minimum": 0, "maximum": 1000})
    add("create_review_session", "提交正式复习审核。人工批准以后才创建 Session。", obj({"item_ids": IDS,
        "minutes": {"type": "number", "minimum": 0, "maximum": 1440}, "title": string(200)}, ["item_ids"]),
        None, {"clms:read", "session:create"}, "confirm", "session.create")
    add("propose_item_update", "提出正式题目修改，显示前后对照并等待人工批准。", obj({"item_id": ID,
        "changes": obj(changes)}, ["item_id", "changes"]), None, {"clms:read", "question:propose"}, "confirm", "item.update")
    add("propose_material_update", "提出正式材料修改，必须经人工审核。", obj({"material_id": ID,
        "changes": obj({key: TEXT for key in creation.MATERIAL_EDITABLE})}, ["material_id", "changes"]),
        None, {"clms:read", "material:propose"}, "confirm", "material.update")

    essay_read = {"essay:read"}
    add("list_essay_prompts", "搜索完整作文题及自由分类。", obj({"query": string(300), "classification_id": ID,
        "offset": OFFSET, "limit": LIMIT}), lambda a: essays.list_prompts(vault, a.get("query", ""),
        a.get("classification_id", ""), a.get("offset", 0), a.get("limit", 30)), essay_read)
    add("get_essay_prompt", "读取作文题、要求和历次独立写作练习。", obj({"prompt_id": ID}, ["prompt_id"]),
        lambda a: essays.prompt_detail(vault, a["prompt_id"]), essay_read)
    add("get_essay_attempt", "读取一次写作练习的各稿版本、修改次数与笔记。", obj({"attempt_id": ID}, ["attempt_id"]),
        lambda a: essays.attempt_detail(vault, a["attempt_id"]), essay_read)
    add("get_essay_version", "读取指定稿件的正式全文；未确认的转写不会作为正式正文返回。",
        obj({"version_id": ID}, ["version_id"]), lambda a: _version(vault, a["version_id"]), essay_read)
    add("list_essay_evaluations", "读取指定版本的全部历史评价，不把旧评价移到新稿。",
        obj({"version_id": ID}, ["version_id"]), lambda a: {"version_id": a["version_id"],
        "evaluations": essays.version_detail(vault, a["version_id"])["evaluations"]}, essay_read)
    add("list_essay_classifications", "读取自由作文分类，没有预定义必选分组。", obj(),
        lambda a: {"classifications": essays.list_classifications(vault)}, essay_read)
    if source == "mcp":
        add("get_essay_image", "读取指定作文版本的一页原图。只接受已归属该版本的图片，页下标从 0 开始。",
            obj({"version_id": ID, "image_index": {"type": "integer", "minimum": 0, "maximum": 29}}, ["version_id"]),
            lambda a: _image(vault, a), {"essay:read", "essay:images"})
    add("append_essay_evaluation", "追加指定正式稿件的评价，满分固定 60，保留其它历史评价。", obj({"version_id": ID,
        "total_score": {"type": "number", "minimum": 0, "maximum": 60}, "summary": TEXT, "strengths": STRINGS,
        "issues": STRINGS, "suggestions": STRINGS, "dimensions": FREE_OBJECT, "evaluator": string(200),
        "model": string(200)}, ["version_id", "total_score"]), None, {"essay:read", "essay:evaluate"}, "auto", "essay.evaluation.add")
    add("append_essay_note", "保存简短讨论笔记或下一稿重点；不保存完整聊天。", obj({"attempt_id": ID,
        "version_id": ID, "text": TEXT}, ["attempt_id", "text"]), None, {"essay:read", "essay:note"}, "auto", "essay.note.add")
    add("create_essay_classification", "创建合理的自由作文分类，可选 group；不要求归入固定分组。",
        obj({"name": string(200, minLength=1), "group": string(200)}, ["name"]), None, {"essay:classify"}, "auto",
        "essay.classification.create")
    add("set_essay_classifications", "给作文题、练习或稿件组合自由分类，允许按名称创建新分类。", obj({"target_type":
        string(20, enum=["prompt", "attempt", "version"]), "target_id": ID,
        "classification_ids": {"type": "array", "items": ID, "maxItems": 100}, "names": STRINGS},
        ["target_type", "target_id"]), None, {"essay:read", "essay:classify"}, "auto", "essay.classification.set")
    return tools


def tool_scopes():
    """Metadata discovery does no I/O; transports use this same source of truth."""
    return {tool.name: set(tool.scopes) for tool in build_tools("", "mcp")}
