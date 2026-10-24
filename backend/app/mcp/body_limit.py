"""Bound authenticated MCP JSON before SDK parsing, also for chunked bodies."""
from starlette.datastructures import Headers
from starlette.responses import JSONResponse


class MCPBodyLimitMiddleware:
    def __init__(self, app, maximum):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)

        async def reject():
            response = JSONResponse({"error": {"code": "media_limit_exceeded",
                "message": "MCP 请求超出附件上传限额", "details": None}}, status_code=413)
            await response(scope, receive, send)

        length = Headers(scope=scope).get("content-length")
        if length and (not length.isdecimal() or int(length) > self.maximum):
            return await reject()
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.maximum:
                return await reject()
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
