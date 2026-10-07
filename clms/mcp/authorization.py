"""SDK-free authorization shared by external calls and later human approval."""
from . import keys

def authorize(vault, tool, actor):
    from ..ai_review import ReviewError
    from ..tool_catalog import build_tools
    registered = next((entry for entry in build_tools(vault, source="mcp", actor=actor)
                       if entry.name == tool or getattr(entry, "domain_tool", None) == tool), None)
    required = set(getattr(registered, "scopes", ()) or ())
    row = keys.active_key(vault, (actor or {}).get("key_id"))
    if not required or not required.issubset(keys.SCOPES) or not row or not required.issubset(row["scopes"]):
        raise ReviewError("forbidden", "MCP 密钥已失效或没有当前操作所需权限", 403)
    return row


def install():
    from ..ai_review import register_authorizer
    register_authorizer("mcp", authorize)
