"""Private, restart-safe global-assistant conversations, events and run summaries."""

import datetime
import json
import os
import sqlite3
import threading
import uuid
from contextlib import closing
from urllib.parse import quote

from .common import DATA_DIRNAME, DATA_ROOT, data_dir

_LOCK = threading.RLock()


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def path(vault):
    return os.path.join(os.path.abspath(vault), DATA_ROOT, DATA_DIRNAME, "assistant.db")


def _connect(vault, write=False):
    target = path(vault)
    if os.path.islink(target):
        raise ValueError("助手数据库不能是符号链接")
    if not write and not os.path.isfile(target):
        return None
    if write:
        data_dir(vault)
        db = sqlite3.connect(target, timeout=10)
        os.chmod(target, 0o600)
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, context_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                conversation_id TEXT NOT NULL, position INTEGER NOT NULL, message_json TEXT NOT NULL,
                PRIMARY KEY(conversation_id,position));
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, status TEXT NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT, error TEXT NOT NULL DEFAULT '',
                stats_json TEXT NOT NULL DEFAULT '{}', pending_operation_id TEXT);
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, event_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS assistant_conversation_events ON events(conversation_id,seq);
            CREATE INDEX IF NOT EXISTS assistant_run_events ON events(run_id,seq);
            CREATE INDEX IF NOT EXISTS assistant_conversation_runs ON runs(conversation_id,started_at);""")
        db.commit()
    else:
        db = sqlite3.connect("file:" + quote(target, safe="/") + "?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def create(vault, title="新对话", context=None):
    conversation_id, now = "A-" + uuid.uuid4().hex, _now()
    with _LOCK, closing(_connect(vault, True)) as db:
        db.execute("INSERT INTO conversations VALUES(?,?,?,?,?)", (conversation_id, str(title or "新对话")[:100], now,
                   now, _json(context or {})))
        db.commit()
    return conversation(vault, conversation_id)


def conversations(vault):
    db = _connect(vault)
    if db is None:
        return {"conversations": []}
    with closing(db):
        rows = [dict(row) for row in db.execute("SELECT id,title,created_at,updated_at FROM conversations ORDER BY updated_at DESC LIMIT 200")]
    return {"conversations": rows}


def _run(row):
    out = dict(row)
    out["stats"] = json.loads(out.pop("stats_json"))
    return out


def conversation(vault, conversation_id):
    db = _connect(vault)
    if db is None:
        raise KeyError("助手对话不存在")
    with closing(db):
        row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not row:
            raise KeyError("助手对话不存在")
        result = dict(row)
        result["context"] = json.loads(result.pop("context_json"))
        result["messages"] = [json.loads(row[0]) for row in db.execute("SELECT message_json FROM messages WHERE conversation_id=? ORDER BY position",
                                                                     (conversation_id,))]
        result["runs"] = [_run(row) for row in db.execute("SELECT * FROM runs WHERE conversation_id=? ORDER BY started_at", (conversation_id,))]
        # Bound a reopened conversation; live polling follows seq without a gap.
        rows = db.execute("SELECT * FROM events WHERE conversation_id=? ORDER BY seq DESC LIMIT 6000", (conversation_id,)).fetchall()
        result["events"] = [dict(json.loads(row["event_json"]), i=row["seq"], created_at=row["created_at"])
                            for row in reversed(rows)]
        result["cursor"] = rows[0]["seq"] if rows else 0
    return result


def rename(vault, conversation_id, title):
    with _LOCK, closing(_connect(vault, True)) as db:
        db.execute("UPDATE conversations SET title=?,updated_at=? WHERE id=?", (str(title)[:100], _now(), conversation_id))
        db.commit()


def set_context(vault, conversation_id, context):
    with _LOCK, closing(_connect(vault, True)) as db:
        db.execute("UPDATE conversations SET context_json=?,updated_at=? WHERE id=?", (_json(context), _now(), conversation_id))
        db.commit()


def save_messages(vault, conversation_id, messages):
    cleaned = [{key: value for key, value in message.items() if key != "thinking"} for message in messages]
    with _LOCK, closing(_connect(vault, True)) as db:
        db.executemany("INSERT INTO messages VALUES(?,?,?) ON CONFLICT(conversation_id,position) DO UPDATE SET message_json=excluded.message_json",
                       [(conversation_id, index, _json(message)) for index, message in enumerate(cleaned)])
        db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), conversation_id))
        db.commit()


def start_run(vault, conversation_id):
    run_id = "R-" + uuid.uuid4().hex
    with _LOCK, closing(_connect(vault, True)) as db:
        db.execute("INSERT INTO runs(id,conversation_id,status,started_at) VALUES(?,?,'running',?)", (run_id, conversation_id, _now()))
        db.commit()
    return run_id


def run(vault, run_id):
    db = _connect(vault)
    if db is None:
        raise KeyError("助手运行不存在")
    with closing(db):
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError("助手运行不存在")
        return _run(row)


def update_run(vault, run_id, status=None, stats=None, error="", pending_operation_id=None, finish=False):
    with _LOCK, closing(_connect(vault, True)) as db:
        db.execute("UPDATE runs SET status=COALESCE(?,status),stats_json=COALESCE(?,stats_json),error=?,pending_operation_id=?,"
                   "finished_at=COALESCE(?,finished_at) WHERE id=?", (status, _json(stats) if stats is not None else None,
                   str(error)[:500], pending_operation_id, _now() if finish else None, run_id))
        db.commit()


def emit(vault, conversation_id, run_id, event):
    now = _now()
    with _LOCK, closing(_connect(vault, True)) as db:
        cursor = db.execute("INSERT INTO events(run_id,conversation_id,created_at,event_json) VALUES(?,?,?,?)",
                            (run_id, conversation_id, now, _json(dict(event, run_id=run_id))))
        db.commit()
        return dict(event, i=cursor.lastrowid, run_id=run_id, created_at=now)


def events(vault, run_id, after=0, limit=500):
    db = _connect(vault)
    if db is None:
        raise KeyError("助手运行不存在")
    limit = max(1, min(1000, int(limit)))
    with closing(db):
        rows = db.execute("SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                          (run_id, max(0, int(after)), limit + 1)).fetchall()
    out = [dict(json.loads(row["event_json"]), i=row["seq"], created_at=row["created_at"]) for row in rows[:limit]]
    return {"events": out, "cursor": out[-1]["i"] if out else int(after), "run": run(vault, run_id), "has_more": len(rows) > limit}


def recover(vault):
    if not os.path.isfile(path(vault)):
        return []
    with _LOCK, closing(_connect(vault, True)) as db:
        rows = [_run(row) for row in db.execute("SELECT * FROM runs WHERE status IN ('running','waiting_confirmation')")]
        for row in rows:
            db.execute("UPDATE runs SET status='interrupted',finished_at=?,error='服务重启，运行已中断' WHERE id=?", (_now(), row["id"]))
        db.commit()
    for row in rows:
        try:
            emit(vault, row["conversation_id"], row["id"], {"type": "run_end", "status": "interrupted", "error": "服务重启，运行已中断"})
        except (OSError, sqlite3.Error):
            # The committed run state remains authoritative; a display event
            # failure must not prevent cancellation of its abandoned proposals.
            pass
    return rows
