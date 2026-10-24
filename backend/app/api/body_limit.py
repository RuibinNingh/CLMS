"""Bound multipart bytes before Starlette's spool, including chunked uploads."""
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class UploadTooLarge(HTTPException):
    def __init__(self):
        super().__init__(413, "文件上传超出服务限额")


class BodyLimitMiddleware:
    def __init__(self, app, maximum):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/assets":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        length = headers.get("content-length")
        if length:
            try:
                over_limit = int(length) > self.maximum
            except ValueError:
                over_limit = True
            if over_limit:
                response = JSONResponse({"error": {"code": "media_limit_exceeded", "message": "文件上传超出服务限额", "details": None}},
                                        status_code=413, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
                return await response(scope, receive, send)
        count = 0

        async def limited_receive():
            nonlocal count
            message = await receive()
            if message["type"] == "http.request":
                count += len(message.get("body", b""))
                if count > self.maximum:
                    raise UploadTooLarge()
            return message

        await self.app(scope, limited_receive, send)
