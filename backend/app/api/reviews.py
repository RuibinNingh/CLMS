from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field

from backend.app.domain import reviews
from backend.app.domain.schemas import Strict
from backend.app.errors import DomainError

from .dependencies import web_actor

router = APIRouter()


class Revise(Strict):
    expected_revision: int = Field(ge=1)
    changes: dict


class Decide(Strict):
    expected_revision: int = Field(ge=1)
    expected_digest: str = Field(min_length=64, max_length=64)
    decision: str


class Withdraw(Strict):
    expected_revision: int = Field(ge=1)


class BatchItem(Decide):
    id: str


class Batch(Strict):
    items: list[BatchItem] = Field(min_length=1, max_length=50)


@router.get("/reviews")
def list_items(request: Request, status: str | None = "pending", kind: str | None = None, source: str | None = None,
               from_date: str | None = None, to_date: str | None = None, cursor: str | None = None,
               limit: int = Query(30, ge=1, le=100), actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return reviews.list_items(session, actor, status, kind, source, from_date, to_date, cursor, limit)


@router.post("/reviews/batch")
def batch(payload: Batch, request: Request, actor=Depends(web_actor)):
    results = []
    for item in payload.items:
        try:
            with request.app.state.db.transaction() as session:
                result = reviews.decide(session, item.id, item.expected_revision, item.expected_digest, item.decision, actor)
                results.append({"id": item.id, "result": result})
        except DomainError as error:
            results.append({"id": item.id, **error.payload()})
    return {"items": results}


@router.get("/reviews/{operation_id}")
def detail(operation_id: str, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return reviews.get_item(session, operation_id, actor)


@router.post("/reviews/{operation_id}/revise")
def revise(operation_id: str, payload: Revise, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.transaction() as session:
        return reviews.revise(session, operation_id, payload.changes, payload.expected_revision, actor)


@router.post("/reviews/{operation_id}/decide")
def decide(operation_id: str, payload: Decide, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.transaction() as session:
        return reviews.decide(session, operation_id, payload.expected_revision, payload.expected_digest, payload.decision, actor)


@router.post("/reviews/{operation_id}/withdraw")
def withdraw(operation_id: str, payload: Withdraw, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.transaction() as session:
        return reviews.withdraw(session, operation_id, payload.expected_revision, actor)
