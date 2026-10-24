from collections import defaultdict
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from backend.app.api import archive, auth, media, reviews
from backend.app.api.body_limit import BodyLimitMiddleware, UploadTooLarge
from backend.app.api.dependencies import web_actor
from backend.app.auth.service import ensure_bootstrap
from backend.app.config import SCOPES, VERSION, Settings
from backend.app.db.base import Database
from backend.app.errors import DomainError
from backend.app.mcp.server import create_mcp
from backend.app.media.storage import MediaError


def create_app(settings=None):
    settings = settings or Settings()
    db = Database(settings)
    mcp, mcp_app = create_mcp(settings, db)

    @asynccontextmanager
    async def lifespan(app):
        db.migrate()
        ensure_bootstrap(settings)
        async with mcp.session_manager.run():
            yield
        db.engine.dispose()

    app = FastAPI(title="CLMS 作文档案馆", version=VERSION, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db, app.state.settings = db, settings
    app.state.login_attempts = defaultdict(list)
    app.state.login_rate_lock = Lock()
    app.add_middleware(BodyLimitMiddleware, maximum=max(settings.pdf_max_bytes, settings.image_max_bytes) + 1024**2)

    @app.exception_handler(UploadTooLarge)
    async def upload_limit(request, error):
        return JSONResponse({"error": {"code": "media_limit_exceeded", "message": error.detail, "details": None}}, status_code=413)

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse(error.payload(), status_code=error.status)

    @app.exception_handler(MediaError)
    async def media_error(request, error):
        return JSONResponse({"error": {"code": error.code, "message": error.message, "details": None}}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        details = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in error.errors()]
        return JSONResponse({"error": {"code": "validation_error", "message": "字段校验失败", "details": details}}, status_code=422)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, error):
        return JSONResponse({"error": {"code": "state_conflict", "message": "数据约束冲突，变更已回滚", "details": None}}, status_code=409)

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("origin") != settings.public_origin:
                return JSONResponse({"error": {"code": "permission_denied", "message": "同源校验失败", "details": None}}, status_code=403)
            content_type = request.headers.get("content-type", "").split(";")[0]
            expected = "multipart/form-data" if request.url.path == "/api/assets" else "application/json"
            if request.method == "POST" and content_type != expected:
                return JSONResponse({"error": {"code": "validation_error", "message": "请求内容类型无效", "details": None}}, status_code=415)
            if request.url.path not in ("/api/auth/bootstrap", "/api/auth/login"):
                # Authenticate before FastAPI receives/parses multipart or JSON;
                # route dependencies recheck after parsing as well.
                try:
                    await run_in_threadpool(web_actor, request)
                except DomainError as error:
                    return JSONResponse(error.payload(), status_code=error.status,
                                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        if request.url.path.startswith(("/api/", "/mcp")):
            response.headers["Cache-Control"] = "no-store"
        return response

    for router in (auth.router, archive.router, media.router, reviews.router):
        app.include_router(router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": VERSION}

    @app.get("/api/settings")
    def preferences(actor=Depends(web_actor)):
        return {"version": VERSION, "limits": settings.limits, "mcp_endpoint": settings.public_origin + "/mcp/",
                "scopes": list(SCOPES), "data_storage": "SQLite 数据库与受控不可变原件", "theme_options": ["light", "dark", "system"]}

    app.mount("/mcp", mcp_app)
    if settings.frontend_dir.is_dir():
        for name in ("assets", "icons"):
            directory = settings.frontend_dir / name
            if directory.is_dir():
                app.mount("/" + name, StaticFiles(directory=directory), name="frontend_" + name)
        @app.get("/")
        def index():
            return FileResponse(settings.frontend_dir / "index.html")
    return app


app = create_app()
