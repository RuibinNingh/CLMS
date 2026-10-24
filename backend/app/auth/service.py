import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.app.config import SCOPES
from backend.app.db.models import Credential, User, WebSession, now
from backend.app.errors import DomainError, require


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${hashed}"


def password_matches(password, stored):
    _, salt, _ = stored.split("$")
    return hmac.compare_digest(password_hash(password, salt), stored)


def ensure_bootstrap(settings):
    path = settings.bootstrap_token_file
    if not path.exists():
        import os
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(secrets.token_urlsafe(32))
    require(not path.is_symlink(), "permission_denied", "Bootstrap token path is unsafe", 403)


def bootstrap(session, settings, username, password, token):
    require(session.scalar(select(User)) is None, "state_conflict", "管理员已设置", 409)
    require(hmac.compare_digest(token, settings.bootstrap_token_file.read_text().strip()),
            "permission_denied", "首次设置令牌无效", 403)
    require(1 <= len(username.strip()) <= 80, "validation_error", "用户名不能为空")
    require(12 <= len(password) <= 256, "validation_error", "密码需为12–256个字符")
    user = User(username=username.strip(), password_hash=password_hash(password))
    session.add(user)
    session.flush()
    return create_session(session, settings, user)


def login(session, settings, username, password):
    user = session.scalar(select(User).where(User.username == username))
    # Equal password work for absent users; no account existence disclosure.
    stored = user.password_hash if user else password_hash("invalid-account", "0" * 32)
    valid = password_matches(password, stored)
    require(user is not None and valid, "permission_denied", "用户名或密码不正确", 401)
    return create_session(session, settings, user)


def create_session(session, settings, user):
    secret, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)).isoformat()
    session.add(WebSession(id_hash=digest(secret), user_id=user.id, expires_at=expiry, csrf_state=csrf))
    return {"secret": secret, "csrf_token": csrf, "username": user.username, "authenticated": True}


def authenticate_web(session, secret):
    record = session.get(WebSession, digest(secret or ""))
    require(record is not None and record.expires_at > now(), "permission_denied", "请先登录", 401)
    return record, session.get(User, record.user_id)


def credential_view(record):
    return {name: getattr(record, name) for name in ("id", "name", "scopes", "expires_at", "revoked_at", "last_used_at", "created_at")}


def create_credential(session, name, scopes, expires_at=None):
    require(bool(name.strip()) and len(name) <= 120, "validation_error", "凭据名称不能为空")
    require(bool(scopes) and len(scopes) == len(set(scopes)) and set(scopes) <= set(SCOPES),
            "validation_error", "不支持的 MCP 权限")
    if expires_at:
        try:
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError as error:
            raise DomainError("validation_error", "到期时间格式不正确") from error
        require(expires_at > now(), "validation_error", "到期时间必须在未来")
    secret = "clms_mcp_" + secrets.token_urlsafe(32)
    record = Credential(name=name, secret_hash=digest(secret), scopes=scopes, expires_at=expires_at)
    session.add(record)
    session.flush()
    return {**credential_view(record), "secret": secret}


def recheck_actor(session, actor, required_scope=None):
    require(actor.startswith("mcp:"), "permission_denied", "需要独立 MCP 凭据", 403)
    record = session.get(Credential, actor[4:])
    require(record is not None, "permission_denied", "无效的 MCP 凭据", 401)
    require(record.revoked_at is None, "credential_revoked", "MCP 凭据已撤销", 401)
    require(not record.expires_at or record.expires_at > now(), "credential_revoked", "MCP 凭据已到期", 401)
    require(required_scope is None or required_scope in record.scopes, "permission_denied", "MCP 权限不足", 403)
    return record


def authenticate_mcp(session, secret, required_scope=None):
    record = session.scalar(select(Credential).where(Credential.secret_hash == digest(secret)))
    require(record is not None, "permission_denied", "需要有效的 MCP Bearer 凭据", 401)
    actor = "mcp:" + record.id
    recheck_actor(session, actor, required_scope)
    record.last_used_at = now()
    return actor
