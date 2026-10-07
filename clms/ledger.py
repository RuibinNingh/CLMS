"""不可变提交链（对标 OMRS ledger.py）：<vault>/语文/.clms/ledger.db 是唯一事实源。

- commits.seq 自增，commit_id 形如 C-000001；每条保存 prev_hash 与 commit_hash。
- 哈希输入 = prev_hash + created_at + source + commit_type + canonical_json(payload)。
- 编号（材料 M-、小题 Q-、复习 S-）由 counters 表分配，与提交在同一事务里，失败整体回滚。
- 修正永远是追加新提交（如 review.void），从不改写旧行。
"""

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager

from .common import data_dir, now_iso

GENESIS_HASH = "0" * 64
_write_lock = threading.Lock()
_operation_local = threading.local()


class OperationConflict(ValueError):
    """The same operation identity cannot be reused for different content."""

    code = "request_conflict"


def operation_current():
    """Return trusted server operation context; never accept this from a model payload."""
    return getattr(_operation_local, "current", None)


@contextmanager
def operation(vault, operation_id, digest, *, source="", actor=None, validate=None):
    """Attach provenance and an atomic native receipt to an existing domain transaction.

    Waiting for a model or reviewer happens outside this context. Domain functions
    keep their original implementation; a receipt is committed together with their
    learning events. A recovered receipt proves that execution happened.
    """
    if operation_current() is not None:
        raise ValueError("不能嵌套领域操作")
    current = {"vault": os.path.abspath(vault), "operation_id": str(operation_id),
               "digest": str(digest), "source": str(source), "actor": dict(actor or {}),
               "validate": validate, "receipt": None}
    _operation_local.current = current
    try:
        yield current
    finally:
        _operation_local.current = None


def _receipt_table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS operation_receipts (
        operation_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
        result_json TEXT NOT NULL, commits_json TEXT NOT NULL, created_at TEXT NOT NULL)""")


def _receipt_row(row):
    if row is None:
        return None
    return {"operation_id": row["operation_id"], "digest": row["digest"],
            "result": json.loads(row["result_json"]), "commits": json.loads(row["commits_json"]),
            "created_at": row["created_at"]}


def operation_receipt(vault, operation_id):
    """Read receipts without creating a database or migrating it during a query."""
    path = os.path.join(os.path.abspath(vault), "语文", ".clms", "ledger.db")
    if not os.path.isfile(path):
        return None
    from urllib.parse import quote
    db = sqlite3.connect("file:" + quote(path, safe="/") + "?mode=ro", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='operation_receipts'").fetchone():
            return None
        return _receipt_row(db.execute("SELECT * FROM operation_receipts WHERE operation_id=?",
                                      (operation_id,)).fetchone())
    finally:
        db.close()


def ledger_path(vault: str) -> str:
    return os.path.join(data_dir(vault), "ledger.db")


def connect(vault: str):
    db = sqlite3.connect(ledger_path(vault), timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS commits (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        commit_id TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL,
        source TEXT NOT NULL,
        commit_type TEXT NOT NULL,
        message TEXT NOT NULL,
        payload TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        commit_hash TEXT NOT NULL)""")
    db.execute("CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
    return db


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_hash(prev_hash, created_at, source, commit_type, payload) -> str:
    text = prev_hash + created_at + source + commit_type + canonical_json(payload)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Tx:
    """事务内的句柄：next_id() 分配编号，append() 追加提交。"""

    def __init__(self, db):
        self.db = db
        self.commits = []

    def next_id(self, prefix: str, width: int = 6) -> str:
        row = self.db.execute("SELECT value FROM counters WHERE name=?", (prefix,)).fetchone()
        value = (row["value"] if row else 0) + 1
        self.db.execute("INSERT INTO counters(name, value) VALUES(?, ?) "
                        "ON CONFLICT(name) DO UPDATE SET value=excluded.value", (prefix, value))
        return f"{prefix}-{value:0{width}d}"

    def append(self, source: str, commit_type: str, message: str, payload: dict) -> dict:
        last = self.db.execute("SELECT seq, commit_hash FROM commits ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = last["commit_hash"] if last else GENESIS_HASH
        created_at = payload.get("_at") or now_iso()
        payload = {k: v for k, v in payload.items() if k != "_at"}
        current = operation_current()
        if current:
            payload["_operation"] = {"id": current["operation_id"], "digest": current["digest"],
                                     "source": current["source"]}
            for key in ("key_id", "conversation_id", "run_id", "call_id"):
                if current["actor"].get(key):
                    payload["_operation"][key] = current["actor"][key]
        commit_id = self.next_id("C")
        commit_hash = compute_hash(prev_hash, created_at, source, commit_type, payload)
        cur = self.db.execute(
            "INSERT INTO commits(commit_id, created_at, source, commit_type, message, payload, prev_hash, commit_hash)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (commit_id, created_at, source, commit_type, message, canonical_json(payload), prev_hash, commit_hash))
        commit = {"seq": cur.lastrowid, "commit_id": commit_id, "created_at": created_at, "source": source,
                  "commit_type": commit_type, "message": message, "payload": payload}
        self.commits.append(commit)
        return commit


def transact(vault: str, fn):
    """在单个写事务里执行 fn(tx)，返回 (fn 的返回值, 本次追加的提交列表)。"""
    with _write_lock:
        db = connect(vault)
        try:
            db.execute("BEGIN IMMEDIATE")
            current = operation_current()
            if current:
                if current["vault"] != os.path.abspath(vault):
                    raise ValueError("操作不能写入其它数据目录")
                _receipt_table(db)
                receipt = _receipt_row(db.execute("SELECT * FROM operation_receipts WHERE operation_id=?",
                                                 (current["operation_id"],)).fetchone())
                if receipt:
                    if receipt["digest"] != current["digest"]:
                        raise OperationConflict("同一操作编号的内容不同")
                    current["receipt"] = receipt
                    db.execute("COMMIT")
                    return receipt["result"], receipt["commits"]
                if current["validate"]:
                    current["validate"]()
            tx = Tx(db)
            result = fn(tx)
            if current:
                if current["validate"]:
                    current["validate"]()
                stamp = now_iso()
                db.execute("INSERT INTO operation_receipts VALUES(?,?,?,?,?)",
                           (current["operation_id"], current["digest"], canonical_json(result),
                            canonical_json(tx.commits), stamp))
                current["receipt"] = {"operation_id": current["operation_id"], "digest": current["digest"],
                                      "result": result, "commits": tx.commits, "created_at": stamp}
            db.execute("COMMIT")
            return result, tx.commits
        except Exception:
            db.execute("ROLLBACK")
            raise
        finally:
            db.close()


def append_commit(vault: str, source: str, commit_type: str, message: str, payload: dict) -> dict:
    _, commits = transact(vault, lambda tx: tx.append(source, commit_type, message, payload))
    return commits[0]


def _row(row) -> dict:
    return {"seq": row["seq"], "commit_id": row["commit_id"], "created_at": row["created_at"],
            "source": row["source"], "commit_type": row["commit_type"], "message": row["message"],
            "payload": json.loads(row["payload"])}


def read_commits(vault: str, after_seq: int = 0) -> list:
    db = connect(vault)
    try:
        rows = db.execute("SELECT * FROM commits WHERE seq > ? ORDER BY seq", (after_seq,)).fetchall()
        return [_row(r) for r in rows]
    finally:
        db.close()


def recent_commits(vault: str, limit: int = 30) -> list:
    db = connect(vault)
    try:
        rows = db.execute("SELECT * FROM commits ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [_row(r) for r in rows]
    finally:
        db.close()


def verify_ledger(vault: str) -> dict:
    db = connect(vault)
    try:
        prev_hash, expected_seq, count = GENESIS_HASH, None, 0
        for row in db.execute("SELECT * FROM commits ORDER BY seq"):
            count += 1
            if expected_seq is not None and row["seq"] != expected_seq:
                return {"ok": False, "count": count, "error": f"seq 不连续：{row['seq']}"}
            expected_seq = row["seq"] + 1
            if row["prev_hash"] != prev_hash:
                return {"ok": False, "count": count, "error": f"{row['commit_id']} 的 prev_hash 断链"}
            payload = json.loads(row["payload"])
            digest = compute_hash(row["prev_hash"], row["created_at"], row["source"], row["commit_type"], payload)
            if digest != row["commit_hash"]:
                return {"ok": False, "count": count, "error": f"{row['commit_id']} 的哈希不符"}
            prev_hash = row["commit_hash"]
        return {"ok": True, "count": count, "error": ""}
    finally:
        db.close()
