"""Human-only MCP key lifecycle. External MCP credentials cannot enter Web routes."""
import json

from .http_registry import Raw, route
from .mcp import keys
from .mcp.authorization import install

install()


def _response(value):
    return Raw(json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8",
               {"Cache-Control": "no-store"})


def _fields(body, allowed, required=()):
    if not isinstance(body, dict) or set(body) - set(allowed) or not set(required).issubset(body):
        raise ValueError("MCP 密钥管理包含未知字段或缺少必填字段")


@route("GET", "/api/mcp/keys")
def list_keys(vault, q, b):
    return _response({"keys": keys.list_keys(vault), "scopes": keys.scope_options()})


@route("POST", "/api/mcp/keys")
def create_key(vault, q, b):
    _fields(b, {"name", "scopes", "expires_at"})
    created = keys.create_key(vault, b.get("name", ""), b.get("scopes"), b.get("expires_at"))
    return _response({"key": created.pop("secret"), "metadata": created})


@route("POST", "/api/mcp/keys/revoke")
def revoke(vault, q, b):
    _fields(b, {"key_id"}, {"key_id"})
    return _response({"key": keys.revoke_key(vault, b["key_id"])})


@route("POST", "/api/mcp/keys/update")
def update(vault, q, b):
    _fields(b, {"key_id", "scopes"}, {"key_id", "scopes"})
    return _response({"key": keys.update_scopes(vault, b["key_id"], b["scopes"])})
