"""Human HTTP, entry Agent, assistant and MCP share these domain services.

The registry classifies writes on the server. Model instructions cannot turn a
formal write into an automatic write; approval and execution use the same preview.
"""

import hashlib
import math
import os

from . import creation, drafts, ledger, library, records, sessions
from .projections import get_state


class DomainError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def fingerprint(value):
    return hashlib.sha256(ledger.canonical_json(value).encode("utf-8")).hexdigest()


_SPECS = {
    "session.create": {"risk": "confirm", "type": "session", "label": "创建正式复习"},
    "item.update": {"risk": "confirm", "type": "item", "label": "修改正式题目"},
    "material.update": {"risk": "confirm", "type": "material", "label": "修改正式材料"},
    "item.suspend": {"risk": "confirm", "type": "item", "label": "停用或恢复正式题目"},
    "item.delete": {"risk": "confirm", "type": "item", "label": "删除正式题目"},
    "item.restore": {"risk": "confirm", "type": "item", "label": "恢复已删除题目"},
    "record.update": {"risk": "confirm", "type": "feedback", "label": "修改复习记录"},
    "record.delete": {"risk": "confirm", "type": "feedback", "label": "作废复习记录"},
    "record.restore": {"risk": "confirm", "type": "feedback", "label": "恢复复习记录"},
    "draft.create": {"risk": "auto", "type": "draft", "label": "创建录入草稿"},
    "draft.update": {"risk": "auto", "type": "draft", "label": "修改录入草稿"},
    "essay.evaluation.add": {"risk": "auto", "type": "essay", "label": "保存作文评价"},
    "essay.note.add": {"risk": "auto", "type": "essay", "label": "保存作文讨论笔记"},
    "essay.classification.create": {"risk": "auto", "type": "essay", "label": "创建作文分类"},
    "essay.classification.set": {"risk": "auto", "type": "essay", "label": "调整作文分类"},
}


def register(tool, *, handler, prepare=None, recover=None, risk="auto", type="essay", label=""):
    """Extensions register at application startup, never from a user/model input."""
    if tool in _SPECS or risk not in {"auto", "confirm"}:
        raise ValueError("领域工具已注册或权限级别不合法")
    _SPECS[tool] = {"handler": handler, "prepare": prepare, "recover": recover,
                    "risk": risk, "type": type, "label": label or tool}


def spec(tool):
    if tool not in _SPECS:
        raise DomainError("unknown_tool", "此领域写工具没有服务端权限分类")
    return _SPECS[tool]


def _item_snapshot(item):
    # Learning reviews do not invalidate an unrelated text edit. Exact field
    # content plus identity/deletion/suspension does invalidate stale proposals.
    fields = creation.EDITABLE | {"id", "material_id", "genre", "key", "suspended", "deleted"}
    return {key: item.get(key) for key in sorted(fields)}


def preview(vault, tool, payload):
    entry = spec(tool)
    if not isinstance(payload, dict):
        raise DomainError("invalid_arguments", "领域操作参数必须是对象")
    state = get_state(vault)
    if tool in {"item.suspend", "item.delete", "item.restore"}:
        allowed = {"item_id", "suspended"} if tool == "item.suspend" else {"item_id"}
        if set(payload) - allowed:
            raise DomainError("invalid_arguments", "题目操作含未知参数")
        item_id = str(payload.get("item_id") or "")
        item = (state.deleted if tool == "item.restore" else state.items).get(item_id)
        if not item:
            raise KeyError("找不到操作的题目：" + item_id)
        clean = {"item_id": item_id}
        if tool == "item.suspend":
            if not isinstance(payload.get("suspended", True), bool):
                raise DomainError("invalid_arguments", "suspended 必须是布尔值")
            clean["suspended"] = payload.get("suspended", True)
        before = _item_snapshot(item)
        before["deleted"] = item_id in state.deleted
        return {"payload": clean, "preview": {"target": {"id": item_id, "label": sessions.describe(state, item_id)},
                                               "before": before, "after": clean, "action": tool},
                "snapshot": {"item_id": item_id, "digest": fingerprint(before)}, "editable_fields": []}
    if tool in {"record.update", "record.delete", "record.restore"}:
        allowed = {"commit_id", "grade", "note"} if tool == "record.update" else {"commit_id"}
        if set(payload) - allowed:
            raise DomainError("invalid_arguments", "复习记录操作含未知参数")
        commit_id = str(payload.get("commit_id") or "")
        record = state.reviews.get(commit_id)
        if record is None:
            raise KeyError("找不到这条复习记录：" + commit_id)
        if tool != "record.restore" and record.get("voided_by"):
            raise DomainError("state_conflict", "这条复习记录已经作废")
        if tool == "record.restore" and not record.get("voided_by"):
            raise DomainError("state_conflict", "这条复习记录没有作废")
        clean = dict(payload, commit_id=commit_id)
        if "grade" in clean:
            clean["grade"] = records.check_grade(state.items[record["item_id"]]["genre"], clean["grade"])
        if "note" in clean:
            clean["note"] = str(clean["note"] or "")
        session = state.sessions.get(record.get("session_id"), {})
        snapshot = {"record": record, "current_grade": session.get("grades", {}).get(record["item_id"]),
                    "cancelled": session.get("cancelled"), "item": _item_snapshot(state.items.get(record["item_id"], {}))}
        return {"payload": clean, "preview": {"target": {"id": commit_id, "item_id": record["item_id"]},
                                               "before": dict(record), "after": clean, "action": tool},
                "snapshot": {"digest": fingerprint(snapshot)},
                "editable_fields": [key for key in ("grade", "note") if key in payload]}
    if tool == "item.update":
        if set(payload) - {"item_id", "changes"}:
            raise DomainError("invalid_arguments", "题目修改含未知参数")
        item_id, changes = str(payload.get("item_id") or ""), payload.get("changes")
        if not isinstance(changes, dict) or set(changes) - creation.EDITABLE:
            raise DomainError("invalid_arguments", "题目修改字段不合法")
        if item_id not in state.items:
            raise KeyError("找不到正式题目：" + item_id)
        clean = creation.prepare_item_changes(vault, item_id, changes, state)["changes"]
        before = _item_snapshot(state.items[item_id])
        return {"payload": {"item_id": item_id, "changes": clean},
                "preview": {"target": {"id": item_id, "label": sessions.describe(state, item_id)},
                            "before": {key: before.get(key) for key in clean}, "after": clean},
                "snapshot": {"item_id": item_id, "digest": fingerprint(before)}, "editable_fields": sorted(clean)}
    if tool == "material.update":
        if set(payload) - {"material_id", "changes"}:
            raise DomainError("invalid_arguments", "材料修改含未知参数")
        mid, changes = str(payload.get("material_id") or ""), payload.get("changes")
        if mid not in state.materials:
            raise KeyError("找不到正式材料：" + mid)
        if not isinstance(changes, dict) or not changes or set(changes) - creation.MATERIAL_EDITABLE:
            raise DomainError("invalid_arguments", "材料修改字段不合法")
        clean = {key: str(value) for key, value in changes.items()}
        before = {key: state.materials[mid].get(key) for key in sorted(creation.MATERIAL_EDITABLE | {"id", "genre", "key"})}
        return {"payload": {"material_id": mid, "changes": clean},
                "preview": {"target": {"id": mid, "label": before.get("title") or mid},
                            "before": {key: before.get(key) for key in clean}, "after": clean},
                "snapshot": {"material_id": mid, "digest": fingerprint(before)}, "editable_fields": sorted(clean)}
    if tool == "session.create":
        if set(payload) - {"item_ids", "minutes", "title"}:
            raise DomainError("invalid_arguments", "复习创建含未知参数")
        ids = payload.get("item_ids")
        if not isinstance(ids, list) or not ids or len(ids) > 500 or any(not isinstance(x, str) for x in ids):
            raise DomainError("invalid_arguments", "必须选择 1–500 道正式题目")
        ids = list(dict.fromkeys(ids))
        for item_id in ids:
            if item_id not in state.items or state.items[item_id].get("suspended"):
                raise DomainError("not_found", "复习题目已不存在或已停用：" + item_id)
        minutes = payload.get("minutes", 0)
        if type(minutes) not in (int, float) or not math.isfinite(minutes) or not 0 <= minutes <= 1440:
            raise DomainError("invalid_arguments", "复习分钟数必须在 0–1440 之间")
        title = str(payload.get("title") or "")[:200]
        objects = {iid: _item_snapshot(state.items[iid]) for iid in ids}
        mids = {state.items[iid].get("material_id") for iid in ids} - {None, ""}
        materials = {mid: {key: state.materials.get(mid, {}).get(key) for key in ("id", "title", "author", "source", "text")}
                     for mid in sorted(mids)}
        return {"payload": {"item_ids": ids, "minutes": minutes, "title": title},
                "preview": {"title": title, "minutes": minutes, "count": len(ids),
                            "items": [{"id": iid, "label": sessions.describe(state, iid),
                                       "stem": state.items[iid].get("stem", "")} for iid in ids]},
                "snapshot": {"digest": fingerprint({"items": objects, "materials": materials})},
                "editable_fields": [key for key in ("title", "minutes") if key in payload]}
    if tool == "draft.create":
        if set(payload) - {"genre", "groups", "hint", "name"}:
            raise DomainError("invalid_arguments", "草稿创建含未知参数")
        genre = str(payload.get("genre") or "modern")
        if genre not in {"modern", "classical", "poetry", "dictation"}:
            raise DomainError("invalid_arguments", "草稿板块不合法")
    elif tool == "draft.update":
        if set(payload) - {"draft_id", "groups", "expected_revision"}:
            raise DomainError("invalid_arguments", "草稿修改含未知参数")
        if not isinstance(payload.get("groups"), list) or type(payload.get("expected_revision")) is not int:
            raise DomainError("invalid_arguments", "草稿修改需要板块列表和当前版本")
        draft = drafts.load(vault, str(payload.get("draft_id") or ""))
        drafts.editable(draft)
    elif entry.get("prepare"):
        return entry["prepare"](vault, payload)
    return {"payload": dict(payload), "preview": {}, "snapshot": {}, "editable_fields": []}


def check_snapshot(vault, tool, payload, snapshot):
    if snapshot is None:
        return
    try:
        changed = preview(vault, tool, payload)["snapshot"] != snapshot
    except (KeyError, ValueError):
        changed = True
    if changed:
        raise DomainError("content_conflict", "原对象内容已经变化，请重新提交提案")


def _draft_receipt(vault, operation_id):
    target = os.path.join(os.path.abspath(vault), "语文", ".clms", "drafts")
    if not os.path.isdir(target):
        return None
    for filename in sorted(os.listdir(target)):
        if not filename.endswith(".json"):
            continue
        try:
            draft = drafts.load(vault, filename[:-5])
        except (OSError, ValueError, KeyError):
            continue
        value = draft.get("_operation_receipts", {}).get(operation_id)
        if isinstance(value, dict):
            return {"operation_id": operation_id, "digest": value.get("digest"),
                    "result": {"draft_id": draft["id"]}, "commits": []}
    return None


def receipt(vault, operation_id, tool=None):
    native = ledger.operation_receipt(vault, operation_id)
    if native is None and tool and tool.startswith("draft."):
        native = _draft_receipt(vault, operation_id)
    return native


def recover_result(vault, tool, native):
    entry = spec(tool)
    if isinstance(native["result"], dict) and "_outer_result" in native["result"]:
        return native["result"]["_outer_result"]
    if tool.startswith("record."):
        result = native["result"]
        commit_id = result["payload"]["commit_id"] if tool == "record.delete" else result["commit_id"]
        return records.get_record(vault, commit_id)
    if tool == "session.create":
        session_id = native["result"]
        if isinstance(session_id, str):
            try:
                return sessions.view(vault, session_id)
            except KeyError:
                return {"id": session_id, "session_id": session_id, "unavailable": True}
        return native["result"]
    if tool.startswith("draft."):
        return drafts.view(vault, native["result"]["draft_id"])
    if tool.startswith("essay."):
        from . import essays
        result = native["result"]
        if tool == "essay.evaluation.add":
            return essays.evaluation_detail(vault, result["evaluation_id"])
        if tool == "essay.note.add":
            return essays.note_detail(vault, result["note_id"])
        if tool == "essay.classification.create":
            return dict(get_state(vault).essay_classifications[result["classification_id"]])
        readers = {"prompt": essays.prompt_detail, "attempt": essays.attempt_detail, "version": essays.version_detail}
        return readers[result["target_type"]](vault, result["target_id"])
    if entry.get("recover"):
        return entry["recover"](vault, native)
    return native["result"]


def _run(vault, tool, payload):
    if tool == "item.suspend":
        return library.set_suspended(vault, payload["item_id"], payload["suspended"])
    if tool == "item.delete":
        return library.delete(vault, payload["item_id"])
    if tool == "item.restore":
        return library.restore(vault, payload["item_id"])
    if tool in {"record.update", "record.delete", "record.restore"}:
        handlers = {"record.update": records.update, "record.delete": records.delete, "record.restore": records.restore}
        return handlers[tool](vault, **payload)
    if tool == "item.update":
        return creation.update_item(vault, payload["item_id"], payload["changes"])
    if tool == "material.update":
        return creation.update_material(vault, payload["material_id"], payload["changes"])
    if tool == "session.create":
        return sessions.create(vault, payload["item_ids"], payload.get("minutes", 0), payload.get("title", ""))
    if tool == "draft.create":
        current = ledger.operation_current()
        upload_id = hashlib.sha256(current["operation_id"].encode()).hexdigest()[:32] if current else ""
        draft = drafts.create(vault, [], payload.get("hint", ""), payload.get("genre") or "modern", upload_id=upload_id,
                              initial_groups=payload.get("groups"), name=str(payload.get("name") or "")[:200])
        return drafts.view(vault, draft["id"])
    if tool == "draft.update":
        return drafts.manual_edit(vault, payload["draft_id"], payload["groups"], payload["expected_revision"])
    if tool.startswith("essay."):
        from . import essays
        current = ledger.operation_current()
        source = current["source"] if current else "web"
        allowed = {
            "essay.evaluation.add": {"version_id", "total_score", "summary", "strengths", "issues", "suggestions",
                                      "dimensions", "evaluator", "model", "metadata"},
            "essay.note.add": {"attempt_id", "text", "version_id", "metadata"},
            "essay.classification.create": {"name", "group", "metadata"},
            "essay.classification.set": {"target_type", "target_id", "classification_ids", "names", "metadata"},
        }
        if tool in allowed:
            if set(payload) - allowed[tool]:
                raise DomainError("invalid_arguments", "作文写操作含未知参数")
            handlers = {"essay.evaluation.add": essays.add_evaluation, "essay.note.add": essays.add_note,
                        "essay.classification.create": essays.create_classification, "essay.classification.set": essays.classify}
            return handlers[tool](vault, **payload, source=source)
    return spec(tool)["handler"](vault, payload)


def execute(vault, tool, payload, *, operation_id=None, digest=None, snapshot=None, source="manual", actor=None, validate=None):
    spec(tool)
    if operation_id:
        native = receipt(vault, operation_id, tool)
        if native:
            if native["digest"] != digest:
                raise DomainError("request_conflict", "同一操作编号的内容不同")
            return recover_result(vault, tool, native)
        def check():
            if validate:
                validate()
            check_snapshot(vault, tool, payload, snapshot)
        with ledger.operation(vault, operation_id, digest, source=source, actor=actor, validate=check) as current:
            check()
            result = _run(vault, tool, payload)
            if current["receipt"] is None and not tool.startswith("draft."):
                ledger.transact(vault, lambda tx: {"_outer_result": result})
            return result
    prepared = preview(vault, tool, payload)
    return _run(vault, tool, prepared["payload"])


def update_item(vault, item_id, changes):
    return execute(vault, "item.update", {"item_id": item_id, "changes": changes})


def update_material(vault, material_id, changes):
    return execute(vault, "material.update", {"material_id": material_id, "changes": changes})


def create_session(vault, item_ids, minutes=0, title=""):
    return execute(vault, "session.create", {"item_ids": item_ids, "minutes": minutes, "title": title})
