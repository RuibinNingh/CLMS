import unicodedata

from sqlalchemy import select

from backend.app.db.models import Category, now
from backend.app.errors import require

from .common import cas, fields, get


def normalized(name):
    return unicodedata.normalize("NFKC", name.strip()).casefold()


def view(record):
    return fields(record, "id name description language_scope sort_order revision archived_at")


def validate(session, payload, actor):
    action = payload["action"]
    target = None
    if action != "create":
        target = get(session, Category, payload.get("category_id"))
        cas(target, payload.get("expected_revision"))
    else:
        require(not payload.get("category_id") and not payload.get("expected_revision"), "validation_error", "新分类不能指定身份或版本")
        require(payload.get("name") is not None, "validation_error", "分类名称不能为空")
    name = payload.get("name") if payload.get("name") is not None else target.name
    scope = payload.get("language_scope") or (target.language_scope if target else "all")
    require(bool(normalized(name)), "validation_error", "分类名称不能为空")
    duplicate = session.scalar(select(Category).where(Category.normalized_name == normalized(name), Category.language_scope == scope))
    require(duplicate is None or (target and duplicate.id == target.id), "state_conflict", "同范围分类名称已存在", 409)
    return {"category_id": target.id, "expected_revision": target.revision, "before": view(target)} if target else {}


def apply(session, payload, actor):
    validate(session, payload, actor)
    if payload["action"] == "create":
        record = Category(name=payload["name"].strip(), normalized_name=normalized(payload["name"]),
                          description=payload.get("description") or "", language_scope=payload.get("language_scope") or "all",
                          sort_order=payload.get("sort_order") or 0)
        session.add(record)
    else:
        record = get(session, Category, payload["category_id"])
        for name in ("name", "description", "language_scope", "sort_order"):
            if payload.get(name) is not None:
                setattr(record, name, payload[name])
        record.name = record.name.strip()
        record.normalized_name = normalized(record.name)
        if payload["action"] == "archive" or payload.get("archived") is True:
            record.archived_at = now()
        elif payload.get("archived") is False:
            record.archived_at = None
        record.revision += 1
    session.flush()
    return {"category_id": record.id, "path": "/#/categories", "category": view(record)}
