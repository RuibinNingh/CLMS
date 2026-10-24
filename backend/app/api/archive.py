from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field

from backend.app.db.models import Attempt, Evaluation, Version, now
from backend.app.domain import dispatch, query
from backend.app.domain.common import audit, cas, get
from backend.app.domain.schemas import (
    CategoryCreate,
    EvaluationInput,
    PageRef,
    PromptCreate,
    Strict,
    Submission,
)
from backend.app.errors import require

from .dependencies import web_actor

router = APIRouter()


class CategoryUpdate(Strict):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    language_scope: str | None = None
    sort_order: int | None = Field(default=None, ge=-10000, le=10000)
    archived: bool | None = None


class PromptUpdate(Strict):
    expected_revision: int = Field(ge=1)
    title: str | None = None
    language: str | None = None
    instructions: str | None = None
    requirements: str | None = None
    source_note: str | None = None
    category_ids: list[str] | None = None
    rubric: dict | None = None
    materials: list[PageRef] | None = None


class VersionInput(Strict):
    parent_version_id: str
    pages: list[PageRef] = Field(min_length=1, max_length=100)
    change_note: str = ""


class AttemptUpdate(Strict):
    expected_revision: int = Field(ge=1)
    reflection: str | None = None
    selected_version_id: str | None = None


def apply_web(request, kind, payload, actor):
    with request.app.state.db.transaction() as session:
        result = dispatch.apply(session, kind, payload, actor)
        audit(session, actor, kind + ".save", result)
        return result


@router.get("/categories")
def categories(request: Request, language: str | None = None, include_archived: bool = False,
               cursor: str | None = None, limit: int = Query(30, ge=1, le=100), actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return query.list_categories(session, language, include_archived, cursor, limit)


@router.post("/categories")
def category_create(payload: CategoryCreate, request: Request, actor=Depends(web_actor)):
    return apply_web(request, "category", {"action": "create", **payload.model_dump(mode="json")}, actor)["category"]


@router.post("/categories/{category_id}")
def category_update(category_id: str, payload: CategoryUpdate, request: Request, actor=Depends(web_actor)):
    return apply_web(request, "category", {"action": "update", "category_id": category_id,
                     **payload.model_dump(mode="json", exclude_unset=True)}, actor)["category"]


@router.get("/prompts")
def prompts(request: Request, q: str = "", language: str | None = None, category_ids: str | None = None,
            status: str | None = None, from_date: str | None = None, to_date: str | None = None,
            cursor: str | None = None, limit: int = Query(30, ge=1, le=100), actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return query.search_prompts(session, q, language, category_ids.split(",") if category_ids else None, status, from_date, to_date, cursor, limit)


@router.post("/prompts")
def prompt_create(payload: PromptCreate, request: Request, actor=Depends(web_actor)):
    return apply_web(request, "prompt", {"action": "create", **payload.model_dump(mode="json")}, actor)["prompt"]


@router.get("/prompts/{prompt_id}")
def prompt_detail(prompt_id: str, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return query.get_prompt(session, prompt_id)


@router.post("/prompts/{prompt_id}")
def prompt_update(prompt_id: str, payload: PromptUpdate, request: Request, actor=Depends(web_actor)):
    return apply_web(request, "prompt", {"action": "update", "prompt_id": prompt_id,
                     **payload.model_dump(mode="json", exclude_unset=True)}, actor)["prompt"]


@router.post("/submissions")
def submission(payload: Submission, request: Request, actor=Depends(web_actor)):
    return apply_web(request, "submission", payload.model_dump(mode="json"), actor)


@router.get("/attempts")
def attempts(prompt_id: str, request: Request, cursor: str | None = None, limit: int = Query(30, ge=1, le=100), actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return query.list_attempts(session, prompt_id, cursor, limit)


@router.get("/attempts/{attempt_id}")
def attempt_detail(attempt_id: str, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return query.get_attempt(session, attempt_id)


@router.post("/attempts/{attempt_id}")
def attempt_update(attempt_id: str, payload: AttemptUpdate, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.transaction() as session:
        record = get(session, Attempt, attempt_id)
        cas(record, payload.expected_revision)
        if payload.reflection is not None:
            record.reflection = payload.reflection
        if "selected_version_id" in payload.model_fields_set:
            if payload.selected_version_id:
                version = get(session, Version, payload.selected_version_id)
                require(version.attempt_id == record.id and not version.voided_at, "validation_error", "定稿需属于本次练习且未作废")
            record.selected_version_id = payload.selected_version_id
        record.revision += 1
        audit(session, actor, "attempt.update", {"attempt_id": record.id, "prompt_id": record.prompt_id})
        return query.get_attempt(session, record.id)


@router.post("/attempts/{attempt_id}/versions")
def version_create(attempt_id: str, payload: VersionInput, request: Request, actor=Depends(web_actor)):
    return apply_web(request, "revision", {"attempt_id": attempt_id, **payload.model_dump(mode="json")}, actor)


@router.get("/versions/{version_id}")
def version_detail(version_id: str, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return query.get_version(session, version_id)


@router.post("/versions/{version_id}/void")
def version_void(version_id: str, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.transaction() as session:
        record = get(session, Version, version_id)
        if not record.voided_at:
            record.voided_at = now()
            attempt = get(session, Attempt, record.attempt_id)
            if attempt.selected_version_id == record.id:
                attempt.selected_version_id = None
                attempt.revision += 1
            audit(session, actor, "version.void", {"version_id": record.id, "attempt_id": attempt.id, "prompt_id": attempt.prompt_id})
        return query.get_version(session, version_id)


@router.post("/evaluations")
def evaluation_create(payload: EvaluationInput, request: Request, actor=Depends(web_actor)):
    return apply_web(request, "evaluation", payload.model_dump(mode="json"), actor)


@router.get("/evaluations/{evaluation_id}")
def evaluation_detail(evaluation_id: str, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return query.get_evaluation(session, evaluation_id)


@router.post("/evaluations/{evaluation_id}/void")
def evaluation_void(evaluation_id: str, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.transaction() as session:
        record = get(session, Evaluation, evaluation_id)
        if not record.voided_at:
            record.voided_at = now()
            version = get(session, Version, record.version_id)
            attempt = get(session, Attempt, version.attempt_id)
            audit(session, actor, "evaluation.void", {"evaluation_id": record.id, "version_id": version.id, "attempt_id": attempt.id, "prompt_id": attempt.prompt_id})
        return query.get_evaluation(session, evaluation_id)


@router.get("/history")
def history(request: Request, prompt_id: str | None = None, attempt_id: str | None = None, version_id: str | None = None,
            cursor: str | None = None, limit: int = Query(30, ge=1, le=100), actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return query.get_history(session, prompt_id, attempt_id, version_id, cursor, limit)
