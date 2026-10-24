"""Each tool authenticates its current HTTP request again inside its transaction."""
import json
from contextlib import ExitStack

import anyio
from mcp.types import CallToolResult, TextContent
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from backend.app.auth.service import authenticate_mcp
from backend.app.errors import DomainError
from backend.app.media import MediaError


def bearer(headers):
    value = headers.get("authorization", "")
    if not value.startswith("Bearer ") or not value[7:].strip():
        raise DomainError("permission_denied", "需要独立 MCP Bearer 凭据", 401)
    return value[7:].strip()


def error_result(error):
    payload = {"error": {"code": error.code, "message": error.message, "details": error.details}}
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
                          structuredContent=payload, isError=True)


class Runtime:
    def __init__(self, settings, db):
        self.settings, self.db = settings, db

    async def call(self, context, scope, function, *, prepare=None):
        try:
            request = context.request_context.request
            if request is None:
                raise DomainError("permission_denied", "MCP 工具必须通过已认证 HTTP 请求调用", 401)
            secret = bearer(request.headers)
            def execute():
                with ExitStack() as resources:
                    args = ()
                    if prepare is not None:
                        with self.db.transaction() as session:
                            authenticate_mcp(session, secret, scope)
                        # Slow attachment downloads must not hold SQLite's write
                        # lock. Recheck scope/expiry/revocation after downloading.
                        args = (resources.enter_context(prepare()),)
                    with self.db.transaction() as session:
                        actor = authenticate_mcp(session, secret, scope)
                        result = function(session, actor, *args)
                        if isinstance(result, CallToolResult):
                            return result
                        return CallToolResult(content=[TextContent(type="text", text=json.dumps(result,
                                              ensure_ascii=False, allow_nan=False))], structuredContent=result)
            return await anyio.to_thread.run_sync(execute)
        except (DomainError, MediaError) as error:
            return error_result(error)


class BearerMiddleware:
    """Transport sessions confer no permissions; every HTTP method rechecks the DB."""
    def __init__(self, app, db):
        self.app, self.db = app, db

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        try:
            secret = bearer(Headers(scope=scope))
            def authenticate():
                with self.db.transaction() as session:
                    authenticate_mcp(session, secret)
            await anyio.to_thread.run_sync(authenticate)
        except DomainError as error:
            response = JSONResponse(error.payload(), status_code=error.status,
                                    headers={"WWW-Authenticate": "Bearer"})
            return await response(scope, receive, send)
        await self.app(scope, receive, send)
