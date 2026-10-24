import time

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import select

from backend.app.auth import service
from backend.app.db.models import Credential, User, WebSession, now
from backend.app.domain.schemas import Strict
from backend.app.errors import DomainError, require

from .dependencies import web_actor

router = APIRouter()


class Login(Strict):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class Bootstrap(Login):
    bootstrap_token: str = Field(min_length=1, max_length=160)


class CredentialInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=3)
    expires_at: str | None = None


def rate_limit(request):
    key = request.client.host
    state = request.app.state
    with state.login_rate_lock:
        recent = [t for t in state.login_attempts[key] if time.monotonic() - t < 60]
        require(len(recent) < 10, "permission_denied", "登录尝试过于频繁，请稍后重试", 429)
        recent.append(time.monotonic())
        state.login_attempts[key] = recent


def set_cookie(response, settings, result):
    secret = result.pop("secret")
    response.set_cookie("clms_session", secret, httponly=True, secure=settings.secure_cookie,
                        samesite="strict", max_age=settings.session_hours * 3600, path="/")
    return result


@router.get("/auth/status")
def status(request: Request):
    with request.app.state.db.read() as session:
        initialized = session.scalar(select(User)) is not None
        result = {"initialized": initialized, "authenticated": False}
        try:
            record, user = service.authenticate_web(session, request.cookies.get("clms_session"))
            result.update(authenticated=True, csrf_token=record.csrf_state, username=user.username)
        except DomainError:
            result["authenticated"] = False
        return result


@router.post("/auth/bootstrap")
def bootstrap(payload: Bootstrap, request: Request, response: Response):
    rate_limit(request)
    with request.app.state.db.transaction() as session:
        result = service.bootstrap(session, request.app.state.settings, payload.username, payload.password, payload.bootstrap_token)
    return set_cookie(response, request.app.state.settings, result)


@router.post("/auth/login")
def login(payload: Login, request: Request, response: Response):
    rate_limit(request)
    with request.app.state.db.transaction() as session:
        result = service.login(session, request.app.state.settings, payload.username, payload.password)
    return set_cookie(response, request.app.state.settings, result)


@router.post("/auth/logout")
def logout(request: Request, response: Response, actor=Depends(web_actor)):
    with request.app.state.db.transaction() as session:
        record = session.get(WebSession, service.digest(request.cookies.get("clms_session")))
        if record:
            session.delete(record)
    response.delete_cookie("clms_session", path="/")
    return {"authenticated": False}


@router.get("/credentials")
def credentials(request: Request, actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return {"items": [service.credential_view(c) for c in session.scalars(select(Credential).order_by(Credential.created_at))], "next_cursor": None}


@router.post("/credentials")
def create_credential(payload: CredentialInput, request: Request, actor=Depends(web_actor)):
    from backend.app.domain.common import audit
    with request.app.state.db.transaction() as session:
        result = service.create_credential(session, payload.name, payload.scopes, payload.expires_at)
        audit(session, actor, "credential.create", {"credential_id": result["id"]})
        return result


@router.post("/credentials/{credential_id}/revoke")
def revoke_credential(credential_id: str, request: Request, actor=Depends(web_actor)):
    from backend.app.domain.common import audit, get
    with request.app.state.db.transaction() as session:
        record = get(session, Credential, credential_id)
        if not record.revoked_at:
            record.revoked_at = now()
            audit(session, actor, "credential.revoke", {"credential_id": record.id})
        return service.credential_view(record)
