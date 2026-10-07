"""审核、历史、打印留白与服务状态的 HTTP 领域适配。"""
import importlib.util

from . import history, printing, runtime_history
from .http_registry import route
from .version import VERSION

@route("GET", "/api/ai-review/items")
def audit_items(vault, q, b):
    from . import ai_review
    return ai_review.items(vault, q)


@route("GET", "/api/ai-review/detail")
def audit_detail(vault, q, b):
    from . import ai_review
    return {"item": ai_review.get(vault, q.get("id") or q.get("operation_id") or "")}


@route("GET", "/api/ai-review/counts")
def audit_counts(vault, q, b):
    from . import ai_review
    return {"counts": ai_review.counts(vault)}


@route("POST", "/api/ai-review/update")
def audit_update(vault, q, b):
    from . import ai_review
    return {"item": ai_review.update(vault, b.get("id", ""), b.get("expected_revision"), b.get("patch"))}


@route("POST", "/api/ai-review/decide")
def audit_decide(vault, q, b):
    from . import ai_review
    return {"item": ai_review.decide(vault, b.get("id", ""), b.get("expected_revision"),
                                   b.get("decision"), reviewer={"kind": "human", "channel": "web"})}


@route("GET", "/api/history")
def learning(vault, q, b):
    return history.list_learning(vault, q)


@route("GET", "/api/history/detail")
def learning_detail(vault, q, b):
    return {"item": history.detail(vault, q.get("id", ""))}


@route("GET", "/api/runtime/records")
def runtime(vault, q, b):
    return runtime_history.list_records(vault, q)


@route("GET", "/api/runtime/records/detail")
def runtime_detail(vault, q, b):
    return {"item": runtime_history.detail(vault, q.get("id", ""))}


@route("POST", "/api/session/blank-lines")
def blank_lines(vault, q, b):
    return printing.update_blank_lines(vault, b.get("session_id", ""), b.get("changes"))


@route("GET", "/api/status", server=True)
def status(server, q, b):
    from .mcp.server import status as mcp_status
    return {"version": VERSION, **server.status(), "mcp": mcp_status(server.vault),
            "mcp_sdk_installed": importlib.util.find_spec("mcp") is not None}


@route("POST", "/api/service/restart", server=True)
def restart(server, q, b):
    return server.request_restart(b.get("instance_id"))
