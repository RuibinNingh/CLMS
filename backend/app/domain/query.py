"""Read paths never execute proposals or mutate business records."""
from sqlalchemy import Text, cast, exists, func, or_, select, tuple_

from backend.app.db.models import (
    Attempt,
    AuditEvent,
    Category,
    Evaluation,
    Prompt,
    Version,
    prompt_categories,
)
from backend.app.errors import require

from . import categories, prompts
from .common import fields, get


def paginated(session, stmt, model, transform, cursor=None, limit=30):
    settings = session.info.get("settings")
    maximum = min(100, settings.max_page_size) if settings else 100
    require(1 <= limit <= maximum, "validation_error", f"分页数量需为1–{maximum}")
    if cursor:
        stmt = stmt.where(model.id > cursor)
    rows = session.scalars(stmt.order_by(model.id).limit(limit + 1)).all()
    return {"items": [transform(row) for row in rows[:limit]], "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


def list_categories(session, language=None, include_archived=False, cursor=None, limit=30):
    stmt = select(Category)
    if not include_archived:
        stmt = stmt.where(Category.archived_at.is_(None))
    if language:
        require(language in ("zh", "en"), "validation_error", "语种无效")
        stmt = stmt.where(Category.language_scope.in_((language, "all")))
    maximum = min(100, session.info["settings"].max_page_size) if session.info.get("settings") else 100
    require(1 <= limit <= maximum, "validation_error", f"分页数量需为1–{maximum}")
    if cursor:
        previous = get(session, Category, cursor)
        stmt = stmt.where(tuple_(Category.sort_order, Category.normalized_name, Category.id) >
                          (previous.sort_order, previous.normalized_name, previous.id))
    rows = session.scalars(stmt.order_by(Category.sort_order, Category.normalized_name, Category.id).limit(limit + 1)).all()
    return {"items": [categories.view(row) for row in rows[:limit]],
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


def evaluation_view(record):
    return fields(record, "id version_id manifest_hash prompt_snapshot_hash payload_schema_version payload source created_at supersedes_id voided_at")


def version_view(session, record):
    result = fields(record, "id attempt_id version_no parent_version_id manifest manifest_hash change_note created_at voided_at")
    result["evaluations"] = [evaluation_view(e) for e in session.scalars(select(Evaluation).where(Evaluation.version_id == record.id).order_by(Evaluation.created_at))]
    effective = [e for e in result["evaluations"] if not e["voided_at"]]
    result["status"] = "evaluated" if effective and effective[-1]["payload"]["coverage"]["scope"] == "full" else "pending"
    return result


def attempt_view(session, record):
    result = fields(record, "id prompt_id prompt_snapshot snapshot_hash written_at duration_minutes reflection selected_version_id revision created_at")
    result["versions"] = [version_view(session, v) for v in session.scalars(select(Version).where(Version.attempt_id == record.id).order_by(Version.version_no))]
    return result


def get_attempt(session, attempt_id):
    return attempt_view(session, get(session, Attempt, attempt_id))


def get_version(session, version_id):
    version = get(session, Version, version_id)
    attempt = get(session, Attempt, version.attempt_id)
    return {**version_view(session, version), "prompt_id": attempt.prompt_id,
            "prompt_snapshot": attempt.prompt_snapshot, "prompt_snapshot_hash": attempt.snapshot_hash}


def get_evaluation(session, evaluation_id):
    return evaluation_view(get(session, Evaluation, evaluation_id))


def list_attempts(session, prompt_id, cursor=None, limit=30):
    get(session, Prompt, prompt_id)
    def summary(row):
        result = fields(row, "id prompt_id written_at duration_minutes reflection selected_version_id revision created_at")
        result["version_count"] = session.scalar(select(func.count()).select_from(Version).where(Version.attempt_id == row.id))
        return result
    return paginated(session, select(Attempt).where(Attempt.prompt_id == prompt_id), Attempt, summary, cursor, limit)


def get_prompt(session, prompt_id):
    prompt = get(session, Prompt, prompt_id)
    return {**prompts.view(session, prompt), "attempts": [attempt_view(session, a) for a in session.scalars(select(Attempt).where(Attempt.prompt_id == prompt.id).order_by(Attempt.created_at))]}


def search_prompts(session, q="", language=None, category_ids=None, status=None, from_date=None, to_date=None, cursor=None, limit=30):
    stmt = select(Prompt)
    if language:
        require(language in ("zh", "en"), "validation_error", "语种无效")
        stmt = stmt.where(Prompt.language == language)
    if category_ids:
        stmt = stmt.where(exists(select(prompt_categories).where(prompt_categories.c.prompt_id == Prompt.id,
                                                               prompt_categories.c.category_id.in_(category_ids))))
    if q:
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cat_match = exists(select(prompt_categories).join(Category).where(prompt_categories.c.prompt_id == Prompt.id, Category.name.ilike(pattern, escape="\\")))
        ref_match = exists(select(Attempt.id).where(Attempt.prompt_id == Prompt.id, Attempt.reflection.ilike(pattern, escape="\\")))
        eval_match = exists(select(Evaluation.id).join(Version).join(Attempt, Version.attempt_id == Attempt.id).where(Attempt.prompt_id == Prompt.id, cast(Evaluation.payload, Text).ilike(pattern, escape="\\")))
        stmt = stmt.where(or_(Prompt.title.ilike(pattern, escape="\\"), Prompt.instructions.ilike(pattern, escape="\\"), Prompt.requirements.ilike(pattern, escape="\\"), cat_match, ref_match, eval_match))
    if from_date or to_date:
        dates = select(Attempt.id).where(Attempt.prompt_id == Prompt.id)
        if from_date:
            dates = dates.where(func.coalesce(Attempt.written_at, Attempt.created_at) >= from_date)
        if to_date:
            dates = dates.where(func.substr(func.coalesce(Attempt.written_at, Attempt.created_at), 1, 10) <= to_date)
        stmt = stmt.where(exists(dates))
    # The latest non-void manuscript of each attempt determines pending status.
    from sqlalchemy.orm import aliased
    newer = aliased(Version)
    later_eval = aliased(Evaluation)
    latest = ~exists(select(newer.id).where(newer.attempt_id == Version.attempt_id, newer.version_no > Version.version_no, newer.voided_at.is_(None)))
    full = exists(select(Evaluation.id).where(Evaluation.version_id == Version.id, Evaluation.voided_at.is_(None),
                  func.json_extract(Evaluation.payload, "$.coverage.scope") == "full",
                  ~exists(select(later_eval.id).where(later_eval.version_id == Version.id, later_eval.voided_at.is_(None), later_eval.created_at > Evaluation.created_at))))
    pending = exists(select(Version.id).join(Attempt, Version.attempt_id == Attempt.id).where(Attempt.prompt_id == Prompt.id, Version.voided_at.is_(None), latest, ~full))
    has_version = exists(select(Version.id).join(Attempt, Version.attempt_id == Attempt.id).where(Attempt.prompt_id == Prompt.id, Version.voided_at.is_(None)))
    if status:
        require(status in ("pending", "evaluated"), "validation_error", "评价状态无效")
        stmt = stmt.where(pending if status == "pending" else has_version & ~pending)
    def summary(row):
        result = prompts.view(session, row)
        # List never includes manuscripts, original images or full evaluations.
        result.pop("materials", None)
        result["instructions"] = row.instructions[:240]
        result.pop("rubric", None)
        result.pop("requirements", None)
        result.pop("source_note", None)
        result["attempt_count"] = session.scalar(select(func.count()).select_from(Attempt).where(Attempt.prompt_id == row.id))
        result["latest_written_at"] = session.scalar(select(func.max(func.coalesce(Attempt.written_at, Attempt.created_at))).where(Attempt.prompt_id == row.id))
        result["status"] = "pending" if session.scalar(select(pending).where(Prompt.id == row.id)) else "evaluated"
        return result
    return paginated(session, stmt, Prompt, summary, cursor, limit)


def get_history(session, prompt_id=None, attempt_id=None, version_id=None, cursor=None, limit=30):
    if version_id:
        version = get(session, Version, version_id)
        attempt_id = version.attempt_id
    if attempt_id:
        prompt_id = get(session, Attempt, attempt_id).prompt_id
    stmt = select(AuditEvent)
    if prompt_id:
        stmt = stmt.where(func.json_extract(AuditEvent.entity_refs, "$.prompt_id") == prompt_id)
    if version_id:
        stmt = stmt.where(func.json_extract(AuditEvent.entity_refs, "$.version_id") == version_id)
    elif attempt_id:
        stmt = stmt.where(func.json_extract(AuditEvent.entity_refs, "$.attempt_id") == attempt_id)
    return paginated(session, stmt, AuditEvent, lambda r: fields(r, "id actor action entity_refs operation_id result created_at"), cursor, limit)
