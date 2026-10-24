from datetime import datetime

from sqlalchemy import func, select

from backend.app.db.models import Attempt, Category, Prompt, Version
from backend.app.errors import DomainError, require

from . import categories, prompts
from .common import add_references, cas, get, hash_json, page_manifest


def validate_submission(session, payload, actor):
    page_manifest(session, payload["pages"], actor)
    if payload.get("prompt_id"):
        prompt = get(session, Prompt, payload["prompt_id"])
        baseline = {"prompt_id": prompt.id, "prompt_revision": prompt.revision, "before": prompts.view(session, prompt)}
    else:
        baseline = {}
        prompts.prepared(session, {"action": "create", **payload["prompt"]}, actor)
    seen = set()
    for category in payload.get("inline_categories", []):
        categories.validate(session, {"action": "create", **category}, actor)
        key = (category["language_scope"], categories.normalized(category["name"]))
        require(key not in seen, "state_conflict", "组合入档中有重名分类", 409)
        require(category["language_scope"] in ("all", payload["prompt"]["language"]), "validation_error", "内联分类语种不匹配")
        seen.add(key)
    if payload.get("written_at"):
        try:
            datetime.fromisoformat(payload["written_at"].replace("Z", "+00:00"))
        except ValueError as error:
            raise DomainError("validation_error", "写作日期格式无效") from error
    return baseline


def validate_revision(session, payload, actor):
    attempt = get(session, Attempt, payload["attempt_id"])
    parent = get(session, Version, payload["parent_version_id"])
    require(parent.attempt_id == attempt.id and not parent.voided_at, "snapshot_conflict", "上一稿归属无效或已作废", 409)
    page_manifest(session, payload["pages"], actor)
    return {"attempt_id": attempt.id, "parent_version_id": parent.id, "parent_manifest_hash": parent.manifest_hash,
            "before": {"version_no": parent.version_no, "manifest": parent.manifest, "change_note": parent.change_note}}


def create_version(session, attempt, pages, parent_id, note, actor):
    manifest = page_manifest(session, pages, actor)
    number = (session.scalar(select(func.max(Version.version_no)).where(Version.attempt_id == attempt.id)) or 0) + 1
    version = Version(attempt_id=attempt.id, version_no=number, parent_version_id=parent_id,
                      manifest=manifest, manifest_hash=hash_json(manifest), change_note=note)
    session.add(version)
    session.flush()
    add_references(session, "version", version.id, manifest)
    return {"prompt_id": attempt.prompt_id, "attempt_id": attempt.id, "version_id": version.id,
            "path": f"/#/prompt/{attempt.prompt_id}?version={version.id}"}


def submission(session, payload, actor):
    validate_submission(session, payload, actor)
    prompt_id = payload.get("prompt_id")
    if not prompt_id:
        inline_ids = [categories.apply(session, {"action": "create", **cat}, actor)["category_id"] for cat in payload.get("inline_categories", [])]
        data = {**payload["prompt"], "category_ids": payload["prompt"].get("category_ids", []) + inline_ids}
        prompt_id = prompts.apply(session, {"action": "create", **data}, actor)["prompt_id"]
    prompt = get(session, Prompt, prompt_id)
    snapshot = prompts.view(session, prompt)
    snapshot["categories"] = [categories.view(get(session, Category, cid)) for cid in snapshot["category_ids"]]
    attempt = Attempt(prompt_id=prompt.id, prompt_snapshot=snapshot, snapshot_hash=hash_json(snapshot),
                      written_at=payload.get("written_at"), duration_minutes=payload.get("duration_minutes"),
                      reflection=payload.get("reflection", ""))
    session.add(attempt)
    session.flush()
    add_references(session, "attempt", attempt.id, snapshot["materials"])
    return create_version(session, attempt, payload["pages"], None, payload.get("change_note", ""), actor)


def revision(session, payload, actor):
    validate_revision(session, payload, actor)
    return create_version(session, get(session, Attempt, payload["attempt_id"]), payload["pages"],
                          payload["parent_version_id"], payload.get("change_note", ""), actor)


def reflection(session, payload, actor):
    attempt = get(session, Attempt, payload["attempt_id"])
    cas(attempt, payload["expected_revision"])
    attempt.reflection = payload["reflection"]
    attempt.revision += 1
    session.flush()
    return {"attempt_id": attempt.id, "prompt_id": attempt.prompt_id, "path": f"/#/prompt/{attempt.prompt_id}"}
