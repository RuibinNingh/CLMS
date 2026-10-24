from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response

from backend.app.media import service

from .dependencies import web_actor

router = APIRouter()


@router.post("/assets")
def upload(request: Request, file: UploadFile = File(...), actor=Depends(web_actor)):
    with request.app.state.db.transaction() as session:
        return service.upload(session, request.app.state.settings, file.file, file.filename, actor)


@router.get("/assets/staged")
def staged(request: Request, cursor: str | None = None, limit: int = Query(30, ge=1, le=100), actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return service.staged_assets(session, actor, cursor, limit)


@router.get("/assets/{asset_id}")
def asset(asset_id: str, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        return service.asset_view(session, asset_id, actor)


@router.get("/assets/{asset_id}/original")
def original(asset_id: str, request: Request, actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        item = service.get_asset(session, asset_id, actor)
        path = service.original_path(session, request.app.state.settings, asset_id, actor)
        return FileResponse(path, media_type=item.mime, filename=item.original_name, content_disposition_type="attachment")


@router.get("/pages/{page_id}")
def page(page_id: str, request: Request, rotation: int = 0, quality: str = "normal", actor=Depends(web_actor)):
    with request.app.state.db.read() as session:
        data, metadata = service.page_image(session, request.app.state.settings, page_id, rotation, quality, actor=actor)
        return Response(data, media_type="image/jpeg")
