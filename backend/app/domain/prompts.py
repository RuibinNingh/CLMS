from sqlalchemy import delete, insert, select

from backend.app.db.models import Category, Prompt, prompt_categories
from backend.app.errors import require

from .common import add_references, cas, fields, get, page_manifest
from .schemas import PromptCreate


def view(session, record):
    result = fields(record, "id title language instructions requirements source_note rubric materials revision created_at")
    result["category_ids"] = list(session.scalars(select(prompt_categories.c.category_id).where(prompt_categories.c.prompt_id == record.id)))
    return result


def validate_category_ids(session, ids, language):
    require(len(ids) == len(set(ids)), "validation_error", "分类不能重复")
    for identity in ids:
        category = get(session, Category, identity)
        require(not category.archived_at, "state_conflict", "停用分类不能用于新归类", 409)
        require(category.language_scope in ("all", language), "validation_error", "分类语种与题目不一致")


def prepared(session, payload, actor):
    target = None
    if payload["action"] == "update":
        target = get(session, Prompt, payload.get("prompt_id"))
        cas(target, payload.get("expected_revision"))
        base = view(session, target)
        base = {key: value for key, value in base.items() if key in PromptCreate.model_fields}
        base["materials"] = [{"page_id": p["page_id"], "rotation": p["rotation"]} for p in base["materials"]]
        base.update({k: v for k, v in payload.items() if k in PromptCreate.model_fields})
    else:
        require(not payload.get("prompt_id") and not payload.get("expected_revision"), "validation_error", "新题目不能指定身份或版本")
        base = {k: v for k, v in payload.items() if k in PromptCreate.model_fields}
    model = PromptCreate.model_validate(base)
    data = model.model_dump(mode="json")
    data["title"] = data["title"].strip() or ("语文作文" if data["language"] == "zh" else "English writing")
    # Existing archived assignments may remain when editing unrelated fields.
    original_ids = view(session, target)["category_ids"] if target else []
    if not target or data["category_ids"] != original_ids or data["language"] != target.language:
        validate_category_ids(session, data["category_ids"], data["language"])
    data["materials"] = page_manifest(session, data["materials"], actor) if data["materials"] else []
    return target, data


def validate(session, payload, actor):
    target, _ = prepared(session, payload, actor)
    return {"prompt_id": target.id, "expected_revision": target.revision, "before": view(session, target)} if target else {}


def apply(session, payload, actor):
    target, data = prepared(session, payload, actor)
    ids = data.pop("category_ids")
    if target:
        for name, value in data.items():
            setattr(target, name, value)
        target.revision += 1
        session.execute(delete(prompt_categories).where(prompt_categories.c.prompt_id == target.id))
    else:
        target = Prompt(**data)
        session.add(target)
    session.flush()
    for category_id in ids:
        session.execute(insert(prompt_categories).values(prompt_id=target.id, category_id=category_id))
    add_references(session, "prompt", target.id, data["materials"])
    return {"prompt_id": target.id, "path": f"/#/prompt/{target.id}", "prompt": view(session, target)}
