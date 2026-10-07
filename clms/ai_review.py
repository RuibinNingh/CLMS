"""Unified authority for assistant/entry/MCP write proposals and human decisions.

Full private proposals live here; only their IDs and counts reach runtime history.
Learning facts stay in the native domain and Ledger. Reads never execute a write.
"""

import datetime
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from urllib.parse import quote

from . import domain_ops, ledger, runtime_history
from .common import DATA_DIRNAME, DATA_ROOT, data_dir

_LOCK = threading.RLock()
_AUTHORIZERS = {}
_TERMINAL = {"applied", "rejected", "expired", "conflict", "failed", "interrupted", "cancelled"}
_SOURCES = {"assistant", "mcp", "entry"}


class ReviewError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


fingerprint = domain_ops.fingerprint


def path(vault):
    return os.path.join(os.path.abspath(vault), DATA_ROOT, DATA_DIRNAME, "ai_review.db")


def _connect(vault, write=False):
    target = path(vault)
    if os.path.islink(target):
        raise ReviewError("invalid_request", "审核数据库不能是符号链接")
    if not write and not os.path.isfile(target):
        return None
    if write:
        data_dir(vault)
        db = sqlite3.connect(target, timeout=10)
        os.chmod(target, 0o600)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS operations (
            operation_id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL,
            source TEXT NOT NULL, tool TEXT NOT NULL, actor_json TEXT NOT NULL,
            original_payload_json TEXT NOT NULL, payload_json TEXT NOT NULL,
            original_digest TEXT NOT NULL, effective_digest TEXT NOT NULL,
            preview_json TEXT NOT NULL, snapshot_json TEXT NOT NULL,
            editable_fields_json TEXT NOT NULL, status TEXT NOT NULL,
            revision INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
            expires_at REAL, result_json TEXT NOT NULL DEFAULT '{}',
            error_code TEXT NOT NULL DEFAULT '', commits_json TEXT NOT NULL DEFAULT '[]')""")
        db.execute("""CREATE TABLE IF NOT EXISTS revisions (
            operation_id TEXT NOT NULL, revision INTEGER NOT NULL, payload_json TEXT NOT NULL,
            effective_digest TEXT NOT NULL, created_at REAL NOT NULL,
            PRIMARY KEY(operation_id,revision))""")
        db.execute("""CREATE TABLE IF NOT EXISTS decisions (
            operation_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, decision TEXT NOT NULL,
            reviewer_json TEXT NOT NULL, created_at REAL NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS review_status_time ON operations(status,created_at)")
        db.commit()
    else:
        db = sqlite3.connect("file:" + quote(target, safe="/") + "?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def _stamp(value):
    return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat() if value is not None else None


def _decode(row, db=None):
    if row is None:
        raise ReviewError("not_found", "审核操作不存在", 404)
    out = dict(row)
    for field in ("actor", "original_payload", "payload", "preview", "snapshot", "editable_fields", "result", "commits"):
        out[field] = json.loads(out.pop(field + "_json"))
    if out["status"] == "pending_confirmation" and out["expires_at"] <= time.time():
        out["status"], out["error_code"] = "expired", "expired"
    out["id"] = out["operation_id"]
    entry = domain_ops.spec(out["tool"])
    out.update(type=entry["type"], label=entry["label"], kind="operation", impact=out["preview"])
    if db is not None:
        out["revisions"] = [{"revision": row["revision"], "payload": json.loads(row["payload_json"]),
                             "digest": row["effective_digest"], "created_at": _stamp(row["created_at"])}
                            for row in db.execute("SELECT * FROM revisions WHERE operation_id=? ORDER BY revision", (out["id"],))]
        out["decisions"] = [{"revision": row["revision"], "decision": row["decision"],
                             "reviewer": json.loads(row["reviewer_json"]), "created_at": _stamp(row["created_at"])}
                            for row in db.execute("SELECT * FROM decisions WHERE operation_id=?", (out["id"],))]
    for field in ("created_at", "updated_at", "expires_at"):
        out[field] = _stamp(out[field])
    return out


def register_authorizer(source, fn):
    if source not in _SOURCES:
        raise ValueError("未知审核来源")
    _AUTHORIZERS[source] = fn


def _authorize(vault, row):
    check = _AUTHORIZERS.get(row["source"])
    if check:
        check(vault, row["tool"], row["actor"])
    elif row["source"] == "mcp":
        raise ReviewError("forbidden", "外部密钥授权服务尚未就绪", 403)


def get(vault, operation_id, key_id=None):
    db = _connect(vault)
    if db is None:
        raise ReviewError("not_found", "审核操作不存在", 404)
    with closing(db):
        row = _decode(db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone(), db)
    if key_id is not None and (row["source"] != "mcp" or row["actor"].get("key_id") != key_id):
        raise ReviewError("not_found", "审核操作不存在", 404)
    return row


def _json(value):
    return ledger.canonical_json(value)


def _state(vault, operation_id, status, *, result=None, error_code="", commits=None):
    with _LOCK, closing(_connect(vault, True)) as db:
        db.execute("UPDATE operations SET status=?,updated_at=?,result_json=COALESCE(?,result_json),"
                   "error_code=?,commits_json=COALESCE(?,commits_json) WHERE operation_id=?",
                   (status, time.time(), _json(result) if result is not None else None, error_code,
                    _json(commits) if commits is not None else None, operation_id))
        db.commit()
    return get(vault, operation_id)


def _trace(vault, source, tool, arguments, result=None, code="", status=None):
    call_id = runtime_history.safely(runtime_history.begin, vault, source, tool, arguments)
    if call_id:
        runtime_history.safely(runtime_history.finish, vault, call_id, result, code, status)


def propose(vault, source, tool, request_id, payload, actor=None, ttl_seconds=600):
    """Register once. Confirm writes return pending; automatic writes execute and leave a receipt."""
    if source not in _SOURCES or not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200:
        raise ReviewError("invalid_request", "写操作需要合法来源和 request_id")
    if type(ttl_seconds) not in (int, float) or not 0 < ttl_seconds <= 86400:
        raise ReviewError("invalid_request", "审核有效期不合法")
    if not isinstance(actor or {}, dict):
        raise ReviewError("invalid_request", "来源身份不合法")
    allowed_actor = {"kind", "key_id", "conversation_id", "run_id", "call_id"}
    if set(actor or {}) - allowed_actor:
        raise ReviewError("invalid_request", "来源身份不能保存凭据或任意字段")
    actor = {key: str(value)[:160] for key, value in (actor or {}).items()}
    if source == "mcp" and not actor.get("key_id"):
        raise ReviewError("forbidden", "外部调用缺少密钥身份", 403)
    entry = domain_ops.spec(tool)
    identity = fingerprint({"source": source, "tool": tool, "actor": actor.get("key_id") or actor.get("conversation_id") or "",
                            "request_id": request_id})
    digest = fingerprint({"tool": tool, "payload": payload})
    # Retried originals must not overwrite a human revision, or revalidate an
    # already applied operation against the newly changed target.
    with _LOCK, closing(_connect(vault, True)) as db:
        old = db.execute("SELECT * FROM operations WHERE identity=?", (identity,)).fetchone()
        if old:
            if old["original_digest"] != digest:
                raise ReviewError("request_conflict", "同一 request_id 的内容不同", 409)
            return _decode(old, db)
        prepared = domain_ops.preview(vault, tool, payload)
        op_id, now = "op_" + uuid.uuid4().hex, time.time()
        status = "pending_confirmation" if entry["risk"] == "confirm" else "running"
        values = (op_id, identity, source, tool, _json(actor), _json(payload), _json(prepared["payload"]), digest,
                  fingerprint(prepared["payload"]), _json(prepared["preview"]), _json(prepared["snapshot"]),
                  _json(prepared["editable_fields"]), status, 1, now, now,
                  now + ttl_seconds if status == "pending_confirmation" else None)
        db.execute("INSERT INTO operations(operation_id,identity,source,tool,actor_json,original_payload_json,payload_json,"
                   "original_digest,effective_digest,preview_json,snapshot_json,editable_fields_json,status,revision,"
                   "created_at,updated_at,expires_at) VALUES(" + ",".join("?" for _ in values) + ")", values)
        db.commit()
    row = get(vault, op_id)
    if entry["risk"] == "auto":
        return _apply(vault, row)
    _trace(vault, source, tool, {"operation_id": op_id}, row, status="pending_confirmation")
    return row


def _apply(vault, row):
    try:
        def validate():
            _authorize(vault, row)
            if row["expires_at"] is not None and datetime.datetime.fromisoformat(row["expires_at"]).timestamp() <= time.time():
                raise ReviewError("expired", "审核提案已经到期", 409)
        result = domain_ops.execute(vault, row["tool"], row["payload"], operation_id=row["id"],
                                    digest=row["effective_digest"], snapshot=row["snapshot"],
                                    source=row["source"], actor=row["actor"], validate=validate)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as error:
        # Never turn a committed learning transaction into a failed/retryable write
        # merely because reading its projected result or auxiliary DB failed.
        native = domain_ops.receipt(vault, row["id"], row["tool"])
        if native and native["digest"] == row["effective_digest"]:
            return _complete(vault, row, domain_ops.recover_result(vault, row["tool"], native), native)
        code = getattr(error, "code", "not_found" if isinstance(error, KeyError) else "invalid_arguments")
        status = "conflict" if code in {"content_conflict", "request_conflict"} else "expired" if code == "expired" else "failed"
        final = _state(vault, row["id"], status, error_code=code)
        _trace(vault, row["source"], row["tool"], {"operation_id": row["id"]}, final, code,
               status if status in {"conflict", "expired"} else "failure")
        return final
    native = domain_ops.receipt(vault, row["id"], row["tool"])
    return _complete(vault, row, result, native)


def _complete(vault, row, result, native):
    commits = [commit["commit_id"] for commit in native["commits"]] if native else []
    try:
        final = _state(vault, row["id"], "applied", result=result, commits=commits)
    except (OSError, sqlite3.Error):
        # Persisted native evidence lets startup reconcile this exact operation.
        final = dict(row, status="applied", result=result, commits=commits, recovery_pending=True)
    _trace(vault, row["source"], row["tool"], {"operation_id": row["id"]}, final)
    return final


def _revision(value):
    if type(value) is not int or value < 1:
        raise ReviewError("invalid_request", "必须提供有效的 expected_revision")


def decide(vault, operation_id, expected_revision, decision, reviewer=None):
    _revision(expected_revision)
    if not isinstance(reviewer, dict) or reviewer.get("kind") != "human":
        raise ReviewError("forbidden", "只有网页人工决定可以批准或拒绝操作", 403)
    if decision not in {"approve", "reject"}:
        raise ReviewError("invalid_request", "decision 只能是 approve 或 reject")
    with _LOCK, closing(_connect(vault, True)) as db:
        db.execute("BEGIN IMMEDIATE")
        row = _decode(db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone(), db)
        if row["revision"] != expected_revision:
            raise ReviewError("revision_conflict", "提案版本已经变化，请重新查看", 409)
        if row["status"] in _TERMINAL or row["status"] == "applying":
            return row
        if row["status"] != "pending_confirmation":
            raise ReviewError("state_conflict", "操作状态已变化", 409)
        status = "applying" if decision == "approve" else "rejected"
        db.execute("INSERT INTO decisions VALUES(?,?,?,?,?)", (operation_id, expected_revision, decision,
                   _json({"kind": "human", "channel": str(reviewer.get("channel") or "web")[:32]}), time.time()))
        db.execute("UPDATE operations SET status=?,updated_at=? WHERE operation_id=? AND status='pending_confirmation'",
                   (status, time.time(), operation_id))
        db.commit()
    _trace(vault, "review", "review." + decision, {"operation_id": operation_id}, {"status": status, "operation_id": operation_id})
    return _apply(vault, get(vault, operation_id)) if decision == "approve" else get(vault, operation_id)


def update(vault, operation_id, expected_revision, patch):
    _revision(expected_revision)
    if not isinstance(patch, dict) or not patch:
        raise ReviewError("invalid_request", "修订需要非空字段补丁")
    with _LOCK, closing(_connect(vault, True)) as db:
        db.execute("BEGIN IMMEDIATE")
        row = _decode(db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone(), db)
        if row["revision"] != expected_revision:
            raise ReviewError("revision_conflict", "提案版本已经变化，请重新查看", 409)
        if row["status"] != "pending_confirmation":
            raise ReviewError("state_conflict", "操作已结束、批准或到期，不能修订", 409)
        if not set(patch).issubset(row["editable_fields"]):
            raise ReviewError("forbidden", "不能扩大原请求的字段或目标范围", 403)
        payload = dict(row["payload"])
        if row["tool"] in {"item.update", "material.update"}:
            payload["changes"] = dict(payload["changes"], **patch)
        else:
            payload.update(patch)
        prepared = domain_ops.preview(vault, row["tool"], payload)
        if prepared["snapshot"] != row["snapshot"]:
            raise ReviewError("content_conflict", "原对象内容已变化，请重新提交提案", 409)
        db.execute("INSERT INTO revisions VALUES(?,?,?,?,?)", (operation_id, expected_revision, _json(row["payload"]),
                   row["effective_digest"], time.time()))
        db.execute("UPDATE operations SET payload_json=?,preview_json=?,effective_digest=?,revision=revision+1,updated_at=? "
                   "WHERE operation_id=?", (_json(prepared["payload"]), _json(prepared["preview"]),
                   fingerprint(prepared["payload"]), time.time(), operation_id))
        db.commit()
    final = get(vault, operation_id)
    _trace(vault, "review", "review.update", {"operation_id": operation_id, "revision": final["revision"]}, final)
    return final


def items(vault, options=None):
    options = options or {}
    offset, limit = max(0, int(options.get("offset") or 0)), max(1, min(100, int(options.get("limit") or 50)))
    db = _connect(vault)
    if db is None:
        return {"items": [], "total": 0, "offset": offset, "limit": limit, "has_more": False, "next_offset": None}
    # Derive expiry without mutating either the review DB or learning facts.
    with closing(db):
        rows = [_decode(row) for row in db.execute("SELECT * FROM operations ORDER BY created_at DESC")]
    result = []
    for row in rows:
        if options.get("view", "pending") == "pending" and row["status"] != "pending_confirmation":
            continue
        if any(options.get(key) and str(options[key]) != row[key] for key in ("source", "type", "status")):
            continue
        if options.get("from") and row["created_at"] < str(options["from"]):
            continue
        if options.get("to") and row["created_at"][:10] > str(options["to"])[:10]:
            continue
        if options.get("q") and str(options["q"]).lower() not in _json(row).lower():
            continue
        result.append(row)
    page = result[offset:offset + limit]
    more = offset + len(page) < len(result)
    return {"items": page, "total": len(result), "offset": offset, "limit": limit,
            "has_more": more, "next_offset": offset + limit if more else None}


def counts(vault):
    count = items(vault, {"view": "pending", "limit": 1})["total"]
    return {"pending": count, "operations": count, "drafts": 0}


def recover(vault):
    """Startup reconciliation uses exact native receipts and never invokes a domain write."""
    if not os.path.isfile(path(vault)):
        return {"reconciled": 0, "interrupted": 0}
    with _LOCK, closing(_connect(vault, True)) as db:
        rows = [_decode(row) for row in db.execute("SELECT * FROM operations WHERE status IN ('running','applying')")]
    result = {"reconciled": 0, "interrupted": 0}
    for row in rows:
        native = domain_ops.receipt(vault, row["id"], row["tool"])
        if native and native["digest"] == row["effective_digest"]:
            _complete(vault, row, domain_ops.recover_result(vault, row["tool"], native), native)
            result["reconciled"] += 1
        else:
            _state(vault, row["id"], "interrupted", error_code="interrupted")
            result["interrupted"] += 1
    return result


initialize = recover
detail = get


def pending_creators(vault, source):
    """Private recovery metadata; never execute proposals or initialize a DB."""
    db = _connect(vault)
    if db is None:
        return []
    with closing(db):
        return [{"id": row["operation_id"], "actor": json.loads(row["actor_json"])}
                for row in db.execute("SELECT operation_id,actor_json FROM operations WHERE source=? AND status='pending_confirmation'", (source,))]


def cancel(vault, operation_id, *, source, actor):
    """An aborted creator can close its own pending intent, but cannot decide it."""
    with _LOCK, closing(_connect(vault, True)) as db:
        db.execute("BEGIN IMMEDIATE")
        row = _decode(db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone())
        if row["source"] != source or any(row["actor"].get(key) != actor.get(key) for key in ("conversation_id", "run_id")):
            raise ReviewError("forbidden", "不能中止其它运行的提案", 403)
        if row["status"] == "pending_confirmation":
            db.execute("UPDATE operations SET status='cancelled',updated_at=?,error_code='aborted' WHERE operation_id=?",
                       (time.time(), operation_id))
            db.commit()
    return get(vault, operation_id)
