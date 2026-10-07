"""Global-assistant HTTP adapter. Human confirmation delegates to ai_review."""

from . import assistant, assistant_store
from .http_registry import route


@route("GET", "/api/assistant/status")
def status(vault, q, b):
    return assistant.status(vault)


@route("GET", "/api/assistant/conversations")
def conversations(vault, q, b):
    return assistant_store.conversations(vault)


@route("POST", "/api/assistant/conversation/create")
def create(vault, q, b):
    return {"conversation": assistant_store.create(vault, b.get("title", "新对话"), assistant.clean_context(b.get("context")))}


@route("GET", "/api/assistant/conversation")
def conversation(vault, q, b):
    return {"conversation": assistant_store.conversation(vault, q.get("id", ""))}


@route("POST", "/api/assistant/message")
def message(vault, q, b):
    return assistant.get_runtime(vault).post_message(b.get("conversation_id"), b.get("text"), b.get("context"))


@route("GET", "/api/assistant/events")
def events(vault, q, b):
    return assistant.get_runtime(vault).events(q.get("run_id"), int(q.get("after") or 0), float(q.get("wait") or 0))


@route("POST", "/api/assistant/abort")
def abort(vault, q, b):
    return {"run": assistant.get_runtime(vault).stop(b.get("run_id"))}
