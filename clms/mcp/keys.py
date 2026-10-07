"""Separate MCP credentials: one-time secret, safe digest, realtime authorization."""
import contextlib
import datetime
import hashlib
import hmac
import json
import os
import secrets
import stat
import tempfile
import threading
import uuid

from ..common import DATA_DIRNAME, DATA_ROOT

_LOCK = threading.RLock()
SCOPES = {
    "clms:read": "查询语文学习数据", "draft:create": "创建未入库草稿", "draft:update": "修订未入库草稿",
    "session:create": "提交正式复习审核", "question:propose": "提交正式题目修改审核",
    "material:propose": "提交正式材料修改审核", "essay:read": "查询作文与正式转写",
    "essay:images": "读取作文原图", "essay:evaluate": "追加作文评价", "essay:note": "追加作文讨论笔记",
    "essay:classify": "创建作文分类与组合标签",
}
DEFAULT_SCOPES = ("clms:read", "essay:read", "draft:create")


def _directory(vault):
    parent = os.path.abspath(vault)
    for part in (DATA_ROOT, DATA_DIRNAME):
        parent = os.path.join(parent, part)
        if os.path.islink(parent):
            raise ValueError("MCP 安全存储目录不能是符号链接")
        os.makedirs(parent, mode=0o700, exist_ok=True)
        if not os.path.isdir(parent):
            raise ValueError("MCP 安全存储目录不合法")
    return parent


def path(vault):
    return os.path.join(_directory(vault), "mcp_keys.json")


def _open_regular(target, flags, mode=0o600):
    if os.path.islink(target):
        raise ValueError("MCP 安全文件不能是符号链接")
    descriptor = os.open(target, flags | getattr(os, "O_NOFOLLOW", 0), mode)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(descriptor)
        raise ValueError("MCP 安全文件必须是独立普通文件")
    os.fchmod(descriptor, 0o600)
    return descriptor


@contextlib.contextmanager
def _key_lock(vault):
    with _LOCK:
        descriptor = _open_regular(path(vault) + ".lock", os.O_CREAT | os.O_RDWR)
        try:
            if os.name == "nt":
                import msvcrt
                if not os.fstat(descriptor).st_size:
                    os.write(descriptor, b"\0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            if os.name == "nt":
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _load(vault):
    try:
        descriptor = _open_regular(path(vault), os.O_RDONLY)
    except FileNotFoundError:
        return {"keys": []}
    with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
        try:
            data = json.load(stream)
        except (ValueError, UnicodeError):
            raise ValueError("MCP 密钥存储损坏，不能覆盖") from None
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise ValueError("MCP 密钥存储格式不正确，不能覆盖")
    return {"keys": [row for row in data["keys"] if isinstance(row, dict)]}


def _save(vault, data):
    target = path(vault)
    if os.path.islink(target):
        raise ValueError("MCP 密钥存储不能是符号链接")
    descriptor, temp = tempfile.mkstemp(prefix=".mcp-keys-", dir=os.path.dirname(target))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        if os.path.islink(target):
            raise ValueError("MCP 密钥存储不能是符号链接")
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _scopes(value):
    if value is None:
        return list(DEFAULT_SCOPES)
    if not isinstance(value, list) or not value or any(not isinstance(scope, str) or scope not in SCOPES for scope in value):
        raise ValueError("scopes 必须是非空的已登记 MCP 权限列表")
    return list(dict.fromkeys(value))


def _public(row):
    return {key: row.get(key) for key in ("key_id", "name", "prefix", "scopes", "created_at", "expires_at", "revoked_at", "last_used_at")}


def _parse_expiry(value):
    try:
        stamp = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.replace(tzinfo=datetime.timezone.utc) if stamp.tzinfo is None else stamp
    except (TypeError, ValueError, AttributeError):
        raise ValueError("expires_at 必须是 ISO-8601 时间") from None


def _active(row):
    if not isinstance(row, dict) or row.get("revoked_at"):
        return None
    try:
        _scopes(row.get("scopes") or [])
        if row.get("expires_at") and _parse_expiry(row["expires_at"]) <= datetime.datetime.now(datetime.timezone.utc):
            return None
    except ValueError:
        return None
    key_id = row.get("key_id")
    if not isinstance(key_id, str) or len(key_id) != 20 or not key_id.startswith("mcp_"):
        return None
    if any(c not in "0123456789abcdef" for c in key_id[4:]):
        return None
    return row


def create_key(vault, name="", scopes=None, expires_at=None):
    if not isinstance(name, str) or len(name.strip()) > 80:
        raise ValueError("密钥名称必须是最多 80 字的文本")
    scopes = _scopes(scopes)
    if expires_at is not None and not isinstance(expires_at, str):
        raise ValueError("expires_at 必须是 ISO-8601 时间")
    if expires_at:
        stamp = _parse_expiry(expires_at)
        if stamp <= datetime.datetime.now(datetime.timezone.utc):
            raise ValueError("密钥到期时间必须晚于当前时间")
        expires_at = stamp.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")
    key_id = "mcp_" + uuid.uuid4().hex[:16]
    secret = "clms_mcp_" + key_id + "_" + secrets.token_urlsafe(32)
    row = {"key_id": key_id, "name": name.strip() or key_id, "prefix": secret[:22], "scopes": scopes,
           "secret_sha256": hashlib.sha256(secret.encode()).hexdigest(), "created_at": _now(),
           "expires_at": expires_at or None, "revoked_at": None, "last_used_at": None}
    with _key_lock(vault):
        data = _load(vault); data["keys"].append(row); _save(vault, data)
    return {**_public(row), "secret": secret}


def list_keys(vault):
    with _key_lock(vault):
        return [_public(row) for row in _load(vault)["keys"]]


def key_for_id(vault, key_id):
    with _key_lock(vault):
        row = next((row for row in _load(vault)["keys"] if row.get("key_id") == key_id), None)
        return _public(row) if row else None


def active_key(vault, key_id):
    with _key_lock(vault):
        row = next((row for row in _load(vault)["keys"] if row.get("key_id") == key_id), None)
        return _public(row) if _active(row) else None


def verify_key(vault, secret):
    if not isinstance(secret, str) or not secret.startswith("clms_mcp_") or len(secret) > 512:
        return None
    digest = hashlib.sha256(secret.encode()).hexdigest()
    try:
        with _key_lock(vault):
            data = _load(vault)
            row = next((row for row in data["keys"] if isinstance(row.get("secret_sha256"), str)
                        and len(row["secret_sha256"]) == 64 and all(ch in "0123456789abcdef" for ch in row["secret_sha256"])
                        and hmac.compare_digest(row["secret_sha256"], digest)), None)
            if not _active(row):
                return None
            used = _now()
            if row.get("last_used_at") != used:
                row["last_used_at"] = used; _save(vault, data)
            return _public(row)
    except (OSError, ValueError):
        return None


def revoke_key(vault, key_id):
    with _key_lock(vault):
        data = _load(vault)
        row = next((row for row in data["keys"] if row.get("key_id") == key_id), None)
        if not row:
            raise ValueError("MCP 密钥不存在")
        if not row.get("revoked_at"):
            row["revoked_at"] = _now(); _save(vault, data)
        return _public(row)


def update_scopes(vault, key_id, scopes):
    scopes = _scopes(scopes)
    with _key_lock(vault):
        data = _load(vault)
        row = next((row for row in data["keys"] if row.get("key_id") == key_id), None)
        if not _active(row):
            raise ValueError("密钥不存在、已吊销或已到期")
        row["scopes"] = scopes; _save(vault, data)
        return _public(row)


def scope_options():
    return [{"scope": scope, "label": label, "default": scope in DEFAULT_SCOPES} for scope, label in SCOPES.items()]
