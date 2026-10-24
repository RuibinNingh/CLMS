import hmac

from fastapi import Request

from backend.app.auth.service import authenticate_web
from backend.app.errors import require


def web_actor(request: Request):
    require(not request.headers.get("authorization"), "permission_denied", "Web API仅接受网页登录会话", 403)
    with request.app.state.db.read() as session:
        record, user = authenticate_web(session, request.cookies.get("clms_session"))
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            require(hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), record.csrf_state),
                    "permission_denied", "CSRF校验失败，请刷新后重试", 403)
        return "web:" + user.id
