"""Human review is the only bridge from MCP proposals to formal domain writes."""
from copy import deepcopy

from sqlalchemy import func, select

from backend.app.auth.service import recheck_actor
from backend.app.db.models import AssetPage, ReadReceipt, ReviewDecision, ReviewOperation, ReviewRevision
from backend.app.errors import DomainError, require

from . import dispatch
from .common import add_references, audit, cas, fields, get, hash_json, proposal_pages
from .query import paginated

EDITABLE = {
    "category": {"name", "description", "language_scope", "sort_order", "archived"},
    "prompt": {"title", "language", "instructions", "requirements", "source_note", "category_ids", "rubric", "materials"},
    "submission": {"prompt", "inline_categories", "pages", "written_at", "duration_minutes", "reflection", "change_note"},
    "revision": {"pages", "change_note"},
    "evaluation": {"coverage", "summary", "strengths", "score", "issues", "next_actions", "commentary_markdown"},
    "reflection": {"reflection"},
}


def view(record):
    return {**fields(record, "id kind source_actor request_id revision original_payload payload original_digest effective_digest target_snapshot status result created_at"),
            "operation_id": record.id, "requires_human_review": record.status == "pending", "review_path": f"/#/reviews?id={record.id}",
            "editable_fields": sorted(EDITABLE[record.kind])}


def visible(record, actor):
    require(actor.startswith("web:") or record.source_actor == actor, "permission_denied", "只能访问当前凭据的提案", 403)


def get_item(session, operation_id, actor):
    record = get(session, ReviewOperation, operation_id)
    visible(record, actor)
    result = view(record)
    result["revisions"] = [fields(r, "revision payload digest actor created_at") for r in session.scalars(select(ReviewRevision).where(ReviewRevision.operation_id == record.id).order_by(ReviewRevision.revision))]
    result["decisions"] = [fields(r, "review_revision decision actor decided_at") for r in session.scalars(select(ReviewDecision).where(ReviewDecision.operation_id == record.id))]
    return result


def list_items(session, actor, status="pending", kind=None, source=None, from_date=None, to_date=None, cursor=None, limit=30):
    stmt = select(ReviewOperation)
    if not actor.startswith("web:"):
        stmt = stmt.where(ReviewOperation.source_actor == actor)
    if status:
        require(status in ("pending", "applied", "rejected", "withdrawn", "conflict", "failed", "processed"), "validation_error", "审核状态无效")
        stmt = stmt.where(ReviewOperation.status != "pending" if status == "processed" else ReviewOperation.status == status)
    if kind:
        stmt = stmt.where(ReviewOperation.kind == kind)
    if source:
        stmt = stmt.where(ReviewOperation.source_actor.contains(source, autoescape=True))
    if from_date:
        stmt = stmt.where(ReviewOperation.created_at >= from_date)
    if to_date:
        stmt = stmt.where(ReviewOperation.created_at <= to_date + "T23:59:59.999999+00:00")
    result = paginated(session, stmt, ReviewOperation, view, cursor, limit)
    result["total"] = session.scalar(select(func.count()).select_from(stmt.subquery()))
    return result


def protect_files(session, record, actor):
    pages = proposal_pages(record.payload)
    if pages:
        # Material and manuscript lists have already been validated separately.
        # Their union must not inherit the per-manuscript page limit.
        refs = [{"asset_id": get(session, AssetPage, identity).asset_id} for identity in {p["page_id"] for p in pages}]
        add_references(session, "review", record.id, refs)


def check_read_receipt(session, payload, actor):
    if not actor.startswith("mcp:"):
        return
    read_pages = set()
    for receipt in session.scalars(select(ReadReceipt).where(ReadReceipt.credential_id == actor[4:], ReadReceipt.version_id == payload["version_id"])):
        read_pages.update(receipt.page_ids)
    require(set(payload["coverage"]["reviewed_page_ids"]) <= read_pages, "state_conflict", "提交评价前需通过MCP读取所评价稿件的页面", 409)


def propose(session, kind, payload, actor, request_id):
    credential = recheck_actor(session, actor, "proposals.write")
    require(isinstance(request_id, str) and 1 <= len(request_id) <= 160, "validation_error", "需要1–160字符request_id")
    original_digest = hash_json(payload)
    existing = session.scalar(select(ReviewOperation).where(ReviewOperation.credential_id == credential.id, ReviewOperation.kind == kind, ReviewOperation.request_id == request_id))
    if existing:
        require(existing.original_digest == original_digest, "idempotency_conflict", "相同request_id的原始内容不同", 409)
        return view(existing)
    normalized = dispatch.parsed(kind, payload)
    target = dispatch.validate(session, kind, normalized, actor)
    if kind == "evaluation":
        check_read_receipt(session, normalized, actor)
    record = ReviewOperation(kind=kind, source_actor=actor, credential_id=credential.id, request_id=request_id,
                original_payload=deepcopy(payload), payload=normalized, original_digest=original_digest,
                effective_digest=hash_json(normalized), target_snapshot=target)
    session.add(record)
    session.flush()
    session.add(ReviewRevision(operation_id=record.id, revision=1, payload=record.payload, digest=record.effective_digest, actor=actor))
    protect_files(session, record, actor)
    audit(session, actor, "proposal.create", {"operation_id": record.id, "status": "pending"}, operation_id=record.id)
    return view(record)


def revise(session, operation_id, changes, expected_revision, actor):
    record = get(session, ReviewOperation, operation_id)
    visible(record, actor)
    if actor.startswith("mcp:"):
        recheck_actor(session, actor, "proposals.write")
    require(record.status == "pending", "state_conflict", "提案已处理", 409)
    cas(record, expected_revision)
    require(bool(changes) and set(changes) <= EDITABLE[record.kind], "permission_denied", "修订含有不允许修改的字段", 403)
    candidate = dispatch.parsed(record.kind, {**record.payload, **deepcopy(changes)})
    # The nested inline prompt has no existing identity. It cannot replace prompt_id.
    require(dispatch.validate(session, record.kind, candidate, record.source_actor) == record.target_snapshot,
            "snapshot_conflict", "修订不能变更目标或基线", 409)
    if record.kind == "evaluation":
        check_read_receipt(session, candidate, actor)
    record.payload, record.effective_digest = candidate, hash_json(candidate)
    record.revision += 1
    session.add(ReviewRevision(operation_id=record.id, revision=record.revision, payload=candidate, digest=record.effective_digest, actor=actor))
    protect_files(session, record, record.source_actor)
    audit(session, actor, "proposal.revise", {"operation_id": record.id, "revision": record.revision}, operation_id=record.id)
    session.flush()
    return view(record)


def withdraw(session, operation_id, expected_revision, actor):
    record = get(session, ReviewOperation, operation_id)
    visible(record, actor)
    if actor.startswith("mcp:"):
        recheck_actor(session, actor, "proposals.write")
    require(record.status == "pending", "state_conflict", "提案已处理", 409)
    cas(record, expected_revision)
    record.status = "withdrawn"
    record.result = {"status": "withdrawn"}
    audit(session, actor, "proposal.withdraw", {"operation_id": record.id, "status": "withdrawn"}, operation_id=record.id)
    session.flush()
    return view(record)


def decide(session, operation_id, expected_revision, expected_digest, decision, actor):
    require(actor.startswith("web:"), "permission_denied", "只有网页登录用户可以决定", 403)
    record = get(session, ReviewOperation, operation_id)
    require(decision in ("approve", "reject"), "validation_error", "决定必须为approve/reject")
    cas(record, expected_revision)
    require(expected_digest == record.effective_digest, "revision_conflict", "提案内容已变化，请重新核对", 409)
    if record.status in ("applied", "rejected"):
        old = session.scalar(select(ReviewDecision).where(ReviewDecision.operation_id == record.id))
        require(old.decision == decision, "state_conflict", "提案已经作出不同决定", 409)
        return view(record)
    require(record.status == "pending", "state_conflict", "提案已处理", 409)
    if decision == "reject":
        result, status = {"status": "rejected"}, "rejected"
    else:
        try:
            recheck_actor(session, record.source_actor, "proposals.write")
            require(hash_json(record.payload) == record.effective_digest, "snapshot_conflict", "有效内容摘要不一致", 409)
            baseline = dispatch.validate(session, record.kind, record.payload, record.source_actor)
            require(baseline == record.target_snapshot, "snapshot_conflict", "目标基线已变化", 409)
        except DomainError as error:
            record.status, record.result = "conflict", error.payload()
            audit(session, actor, "proposal.conflict", {"operation_id": record.id, **error.payload()}, operation_id=record.id)
            session.flush()
            return view(record)
        # Savepoint ensures even a deliberately injected internal failure cannot
        # commit formal objects while leaving only a failed review.
        try:
            with session.begin_nested():
                result = dispatch.apply(session, record.kind, record.payload, record.source_actor)
                status = "applied"
                record.status, record.result = status, result
                session.add(ReviewDecision(operation_id=record.id, review_revision=record.revision, decision=decision, actor=actor))
                audit(session, actor, "proposal.apply", {"operation_id": record.id, **result}, operation_id=record.id)
                session.flush()
            return view(record)
        except Exception:
            record.status, record.result = "failed", {"error": {"code": "application_failed", "message": "入档失败，正式变更已回滚；请重新创建提案"}}
            audit(session, actor, "proposal.failed", {"operation_id": record.id, "status": "failed"}, operation_id=record.id)
            session.flush()
            return view(record)
    record.status, record.result = status, result
    session.add(ReviewDecision(operation_id=record.id, review_revision=record.revision, decision=decision, actor=actor))
    audit(session, actor, "proposal.reject", {"operation_id": record.id, **result}, operation_id=record.id)
    session.flush()
    return view(record)
