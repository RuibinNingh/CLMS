import hashlib
import json

from backend.app.db.models import AssetPage, AuditEvent, FileReference
from backend.app.errors import require
from backend.app.media.service import get_asset


def hash_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def get(session, model, identity):
    record = session.get(model, identity)
    require(record is not None, "not_found", "目标档案不存在", 404)
    return record


def cas(record, revision):
    require(revision is not None and record.revision == revision, "revision_conflict", "目标已修改，请重新读取", 409)


def page_manifest(session, pages, actor):
    settings = session.info.get("settings")
    maximum = min(100, settings.version_max_pages) if settings else 100
    require(1 <= len(pages) <= maximum, "media_limit_exceeded", f"页清单需为1–{maximum}页")
    require(len({p["page_id"] for p in pages}) == len(pages), "validation_error", "页清单不能重复引用同一页")
    output = []
    for index, entry in enumerate(pages):
        page = get(session, AssetPage, entry["page_id"])
        asset = get_asset(session, page.asset_id, actor)
        rotation = entry.get("rotation", 0)
        require(rotation in (0, 90, 180, 270), "validation_error", "旋转角度无效")
        width, height = (page.height, page.width) if rotation in (90, 270) else (page.width, page.height)
        output.append({"page_id": page.id, "asset_id": asset.id, "asset_sha256": asset.sha256,
                       "source_page": page.source_page, "order": index + 1, "rotation": rotation,
                       "width": width, "height": height})
    return output


def add_references(session, owner_type, owner_id, manifest):
    for asset_id in {p["asset_id"] for p in manifest}:
        key = (owner_type, owner_id, asset_id)
        if session.get(FileReference, key) is None:
            session.add(FileReference(owner_type=owner_type, owner_id=owner_id, asset_id=asset_id))


def proposal_pages(payload):
    pages = list(payload.get("pages") or payload.get("materials") or [])
    if payload.get("prompt"):
        pages += payload["prompt"].get("materials", [])
    return pages


def audit(session, actor, action, result, refs=None, operation_id=None):
    safe_refs = refs or {k: v for k, v in result.items() if k.endswith("_id")}
    event = AuditEvent(actor=actor, action=action, entity_refs=safe_refs, operation_id=operation_id, result=result)
    session.add(event)
    session.flush()
    return event


def fields(record, names):
    return {name: getattr(record, name) for name in names.split()}
