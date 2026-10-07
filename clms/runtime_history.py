"""脱敏系统运行记录；辅助 SQLite 不参与学习投影，也不保存学习正文。"""

import datetime
import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from urllib.parse import quote

from .common import DATA_DIRNAME, DATA_ROOT, data_dir

_LOCK = threading.RLock()
_STARTED = {}
_SOURCES = {"assistant", "mcp", "entry", "review", "ocr", "ai", "system"}
_PRIVATE = re.compile(r"clms_mcp_\S+|omrs_mcp_\S+|\bsk-[\w-]+|\bbearer\s+\S+|https?://\S+|data:\S+", re.I)
_IDENTIFIERS = {"id", "item_id", "material_id", "session_id", "draft_id", "operation_id",
                "prompt_id", "attempt_id", "version_id", "evaluation_id", "note_id", "category_id",
                "classification_id", "conversation_id", "run_id", "call_id", "key_id", "commit_id"}
_NUMBERS = {"count", "total", "limit", "offset", "revision", "expected_revision", "minutes",
            "duration_ms", "input_total", "output_total", "turns", "tool_calls", "image_index"}
_ENUMS = {"source", "status", "genre", "view", "type", "kind", "error_code"}
_LISTS = {"items", "item_ids", "images", "sessions", "prompts", "attempts", "versions",
          "evaluations", "notes", "classifications", "tags", "records", "groups"}
TITLES = {"session.create": "创建正式复习", "item.update": "修改正式题目", "material.update": "修改正式材料",
          "review.approve": "批准审核操作", "review.reject": "拒绝审核操作", "review.update": "修订审核提案",
          "essay.ocr": "作文原图转写", "assistant.run": "全局助手运行", "draft.create": "创建录入草稿",
          "draft.update": "修改录入草稿", "essay.evaluation.add": "保存作文评价", "essay.note.add": "保存作文讨论笔记",
          "essay.classification.create": "创建作文分类", "essay.classification.set": "调整作文分类"}
TITLES.update({"list_taxonomy": "读取板块与题型", "search_items": "搜索正式题目", "get_item": "读取正式题目",
               "get_material": "读取材料", "get_overview": "查询学习概况", "get_recommendations": "推荐复习题目",
               "list_sessions": "查询正式复习", "get_session": "读取正式复习", "list_drafts": "查询录入草稿",
               "get_draft": "读取录入草稿", "get_operation": "查询审核结果", "create_draft": "创建录入草稿",
               "update_draft": "修改录入草稿", "create_review_session": "提交正式复习提案",
               "propose_item_update": "提交题目修改提案", "propose_material_update": "提交材料修改提案",
               "list_essay_prompts": "搜索作文题", "get_essay_prompt": "读取作文题", "get_essay_attempt": "读取写作练习",
               "get_essay_version": "读取正式作文", "get_essay_image": "读取作文原图", "list_essay_evaluations": "查询作文评价",
               "list_essay_classifications": "查询自由作文分类", "append_essay_evaluation": "追加作文评价",
               "append_essay_note": "保存作文讨论笔记", "create_essay_classification": "创建自由作文分类",
               "set_essay_classifications": "设置自由作文分类"})


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def path(vault):
    return os.path.join(os.path.abspath(vault), DATA_ROOT, DATA_DIRNAME, "runtime.db")


def _connect(vault, write=False):
    target = path(vault)
    if os.path.islink(target):
        raise ValueError("运行数据库不能是符号链接")
    if not write and not os.path.isfile(target):
        return None
    if write:
        data_dir(vault)
        db = sqlite3.connect(target, timeout=5)
        os.chmod(target, 0o600)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS records (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT UNIQUE NOT NULL,
            source TEXT NOT NULL, tool TEXT NOT NULL, title TEXT NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
            duration_ms INTEGER, arguments_json TEXT NOT NULL, result_json TEXT NOT NULL,
            actor_json TEXT NOT NULL, error_code TEXT NOT NULL DEFAULT '')""")
        db.execute("CREATE INDEX IF NOT EXISTS runtime_source_time ON records(source,started_at)")
        db.commit()
    else:
        db = sqlite3.connect("file:" + quote(target, safe="/") + "?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def _text(value):
    if not isinstance(value, str):
        return ""
    return _PRIVATE.sub("[已隐藏]", value[:512]).replace("\x00", "")[:96]


def summary(value):
    """Positive allowlist: free text, keys, request IDs, URLs and image bytes are omitted."""
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, field in value.items():
        if key in _IDENTIFIERS and isinstance(field, str):
            safe = _text(field)
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,95}", safe):
                out[key] = safe
        elif key in _ENUMS and isinstance(field, str):
            safe = _text(field)
            if re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", safe):
                out[key] = safe
        elif key in _NUMBERS and type(field) in (int, float) and math.isfinite(field) and abs(field) <= 1e12:
            out[key] = field
        elif key in _LISTS and isinstance(field, list):
            out[key + "_count"] = len(field)
        elif key in {"reused", "wrote", "complete"} and isinstance(field, bool):
            out[key] = field
    for nested in ("result", "operation", "session"):
        if isinstance(value.get(nested), dict):
            for key, field in summary(value[nested]).items():
                out.setdefault(key, field)
    # An operation's id and its domain result's id are distinct identities.
    # Keep both so a Session proposal links to the operation and actual Session.
    domain_id = out.get("id", "")
    for prefix, key in (("S", "session_id"), ("Q", "item_id"), ("EV", "version_id"),
                        ("EA", "attempt_id"), ("EP", "prompt_id"), ("EE", "evaluation_id")):
        if re.fullmatch(prefix + r"-\d{4,}", domain_id):
            out.setdefault(key, domain_id)
    return out


argument_summary = summary
result_summary = summary


def _row(row):
    out = dict(row)
    for field in ("arguments", "result", "actor"):
        out[field] = json.loads(out.pop(field + "_json"))
    out["id"] = out["call_id"]
    out["created_at"] = out["started_at"]
    return out


def begin(vault, source, tool, arguments=None, actor=None):
    if source not in _SOURCES:
        raise ValueError("未知运行来源")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", str(tool)) or _PRIVATE.search(str(tool)):
        raise ValueError("运行工具名不合法")
    call_id = "call_" + uuid.uuid4().hex
    with _LOCK, closing(_connect(vault, True)) as db:
        db.execute("INSERT INTO records(call_id,source,tool,title,started_at,status,arguments_json,result_json,actor_json) "
                   "VALUES(?,?,?,?,?,'running',?,'{}',?)", (call_id, source, tool, TITLES.get(tool, tool), _now(),
                   json.dumps(summary(arguments), ensure_ascii=False), json.dumps(summary(actor), ensure_ascii=False)))
        db.commit()
        _STARTED[(os.path.abspath(vault), call_id)] = time.monotonic()
    return call_id


def finish(vault, call_id, result=None, error_code="", status=None, duration_ms=None):
    status = status or ("failure" if error_code else "success")
    if status not in {"success", "failure", "interrupted", "pending_confirmation", "rejected", "expired", "conflict"}:
        raise ValueError("运行结束状态不合法")
    error_code = _text(error_code)
    if error_code and not re.fullmatch(r"[a-z0-9_]{1,64}", error_code):
        error_code = "internal_error"
    with _LOCK, closing(_connect(vault, True)) as db:
        start = _STARTED.pop((os.path.abspath(vault), call_id), None)
        if duration_ms is None and start is not None:
            duration_ms = round((time.monotonic() - start) * 1000)
        if duration_ms is not None:
            duration_ms = max(0, int(duration_ms))
        db.execute("UPDATE records SET finished_at=?,status=?,duration_ms=?,result_json=?,error_code=? "
                   "WHERE call_id=? AND status='running'", (_now(), status, duration_ms,
                   json.dumps(summary(result), ensure_ascii=False), error_code, call_id))
        db.commit()
    return detail(vault, call_id)


def detail(vault, record_id):
    db = _connect(vault)
    if db is None:
        raise KeyError("找不到这条运行记录")
    with closing(db):
        row = db.execute("SELECT * FROM records WHERE call_id=? OR CAST(seq AS TEXT)=?",
                         (str(record_id), str(record_id))).fetchone()
        if not row:
            raise KeyError("找不到这条运行记录")
        return _row(row)


def list_records(vault, options=None):
    options = options or {}
    offset, limit = max(0, int(options.get("offset") or 0)), max(1, min(100, int(options.get("limit") or 50)))
    out = {"items": [], "records": [], "total": 0, "offset": offset, "limit": limit, "has_more": False,
           "next_offset": None, "sources": sorted(_SOURCES), "types": []}
    db = _connect(vault)
    if db is None:
        return out
    where, args = [], []
    for key, column in (("source", "source"), ("tool", "tool"), ("type", "tool"), ("status", "status")):
        if options.get(key):
            where.append(column + "=?")
            args.append(str(options[key]))
    for key, sign in (("from", ">="), ("to", "<=")):
        if options.get(key):
            where.append("started_at" + sign + "?")
            stamp = str(options[key])
            args.append(stamp + "T23:59:59.999Z" if key == "to" and len(stamp) == 10 else stamp)
    if options.get("q"):
        where.append("(title LIKE ? OR tool LIKE ? OR arguments_json LIKE ? OR result_json LIKE ?)")
        args.extend(["%" + str(options["q"])[:200] + "%"] * 4)
    clause = " WHERE " + " AND ".join(where) if where else ""
    with closing(db):
        out["types"] = [row[0] for row in db.execute("SELECT DISTINCT tool FROM records ORDER BY tool")]
        out["total"] = db.execute("SELECT COUNT(*) FROM records" + clause, args).fetchone()[0]
        out["items"] = [_row(row) for row in db.execute("SELECT * FROM records" + clause + " ORDER BY seq DESC LIMIT ? OFFSET ?",
                                                      args + [limit, offset])]
    out["records"] = out["items"]
    out["has_more"] = offset + len(out["items"]) < out["total"]
    out["next_offset"] = offset + limit if out["has_more"] else None
    return out


def recover(vault):
    """Startup only: an abandoned run is interrupted, never inferred successful."""
    if not os.path.isfile(path(vault)):
        return 0
    with _LOCK, closing(_connect(vault, True)) as db:
        result = db.execute("UPDATE records SET status='interrupted',finished_at=?,error_code='interrupted' "
                            "WHERE status='running'", (_now(),))
        db.commit()
        return result.rowcount


recover_interrupted = recover


def safely(fn, *args, **kwargs):
    """Telemetry must not change a successful domain outcome."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None
