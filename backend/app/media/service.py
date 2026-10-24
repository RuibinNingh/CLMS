"""Media APIs shared by Web and MCP; persistence is owned by the caller's transaction."""
import hashlib
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, event, exists, select

from backend.app.db.models import Asset, AssetPage, FileReference

from .render import decode_image, derived_image, render_pdf, sniff
from .storage import MediaError, private_root, read_bytes, safe_path, validate_name


def _id(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _can_read(session, asset, actor):
    if not actor or not actor.startswith("mcp:"):
        return
    # Single administrator's Web uploads are controlled shared staging. Private
    # MCP staging becomes shared only after a formal archive reference exists.
    if asset.created_by.startswith("mcp:") and asset.created_by != actor:
        formal = session.scalar(select(FileReference.owner_id).where(
            FileReference.asset_id == asset.id, FileReference.owner_type != "review").limit(1))
        if not formal:
            raise MediaError("permission_denied", "当前凭据不能访问该暂存文件。", 403)


def get_asset(session, asset_id, actor=None):
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise MediaError("not_found", "文件不存在。", 404)
    _can_read(session, asset, actor)
    return asset


def asset_view(session, asset_id, actor=None):
    asset = get_asset(session, asset_id, actor)
    pages = session.scalars(select(AssetPage).where(AssetPage.asset_id == asset.id)
                            .order_by(AssetPage.source_page)).all()
    return {"id": asset.id, "sha256": asset.sha256, "mime": asset.mime,
            "original_name": asset.original_name, "byte_size": asset.byte_size,
            "page_count": asset.page_count, "created_at": _iso(asset.created_at),
            "original_url": f"/api/assets/{asset.id}/original",
            "pages": [{"page_id": page.id, "asset_id": asset.id, "asset_sha256": asset.sha256,
                       "source_page": page.source_page, "order": index + 1, "rotation": 0,
                       "width": page.width, "height": page.height} for index, page in enumerate(pages)]}


def upload(session, settings, stream, filename, actor):
    filename = validate_name(filename)
    asset_id = _id("asset")
    directory = private_root(settings) / asset_id
    directory.mkdir(mode=0o700)
    original = directory / "original"
    digest, total = hashlib.sha256(), 0
    # Upper bound applies during streaming, before any parsing or full buffering.
    maximum = max(settings.image_max_bytes, settings.pdf_max_bytes)
    try:
        with original.open("xb") as output:
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > maximum:
                    raise MediaError("media_limit_exceeded", "文件大小超出上传限制。")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        with original.open("rb") as header_stream:
            header = header_stream.read(32)
        mime = sniff(header, filename)
        limit = settings.pdf_max_bytes if mime == "application/pdf" else settings.image_max_bytes
        if total > limit:
            raise MediaError("media_limit_exceeded", "文件大小超出对应格式限制。")
        if mime == "application/pdf":
            pages = render_pdf(settings, original, directory)
        else:
            image = decode_image(original.read_bytes(), settings.image_max_pixels)
            image.thumbnail((settings.media_high_edge, settings.media_high_edge))
            image.save(directory / "page-1.jpg", "JPEG", quality=92)
            pages = [{"source_page": 1, "width": image.width, "height": image.height, "file": "page-1.jpg"}]
            image.close()
        os.chmod(original, 0o400)
        for page in pages:
            path = directory / page["file"]
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
            os.chmod(path, 0o400)
        # File bytes are durable before rows may be referenced by a domain write.
        for durable_directory in (directory, directory.parent, directory.parent.parent):
            dir_fd = os.open(durable_directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        asset = Asset(id=asset_id, sha256=digest.hexdigest(), mime=mime, original_name=filename,
                      byte_size=total, page_count=len(pages), storage_key=f"{asset_id}/original",
                      created_by=actor, created_at=datetime.now(timezone.utc).isoformat())
        session.add(asset)
        session.flush()
        for page in pages:
            session.add(AssetPage(id=_id("page"), asset_id=asset_id, source_page=page["source_page"],
                                  width=page["width"], height=page["height"],
                                  preview_key=f"{asset_id}/{page['file']}"))
        session.flush()
        return asset_view(session, asset_id, actor)
    except Exception:
        shutil.rmtree(directory)
        raise


def page_image(session, settings, page_id, rotation=0, quality="normal", bbox=None, actor=None):
    page = session.get(AssetPage, page_id)
    if page is None:
        raise MediaError("not_found", "页面不存在。", 404)
    asset = get_asset(session, page.asset_id, actor)
    if quality not in ("normal", "high"):
        raise MediaError("validation_error", "清晰度必须为 normal 或 high。")
    edge = settings.media_normal_edge if quality == "normal" else settings.media_high_edge
    data, metadata = derived_image(read_bytes(settings, page.preview_key), rotation=rotation,
                                   edge=edge, max_pixels=settings.image_max_pixels, bbox=bbox)
    metadata.update({"page_id": page.id, "asset_id": asset.id, "asset_sha256": asset.sha256,
                     "source_page": page.source_page, "width": page.width, "height": page.height,
                     "quality": quality})
    return data, metadata


def original_path(session, settings, asset_id, actor=None):
    asset = get_asset(session, asset_id, actor)
    return safe_path(settings, asset.storage_key)


def staged_assets(session, actor, cursor=None, limit=30):
    settings = session.info.get("settings")
    maximum = min(100, settings.max_page_size) if settings else 100
    if not 1 <= limit <= maximum:
        raise MediaError("validation_error", f"分页数量必须为 1–{maximum}。")
    formal = exists(select(FileReference.owner_id).where(FileReference.asset_id == Asset.id,
                                                  FileReference.owner_type != "review"))
    query = select(Asset).where(~formal).order_by(Asset.id)
    if cursor:
        query = query.where(Asset.id > cursor)
    if actor and actor.startswith("mcp:"):
        query = query.where((~Asset.created_by.like("mcp:%")) | (Asset.created_by == actor))
    assets = session.scalars(query.limit(limit + 1)).all()
    return {"items": [asset_view(session, row.id, actor) for row in assets[:limit]],
            "next_cursor": assets[limit - 1].id if len(assets) > limit else None}


def cleanup(session, settings, now=None, dry_run=False):
    """Call within db.transaction (BEGIN IMMEDIATE). Delete physical bytes after commit.

    Pending and formal references both protect files. A transaction rollback never
    removes files. Orphan directories from failed DB commits are handled separately.
    """
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=settings.media_ttl_hours)
    referenced = exists(select(FileReference.owner_id).where(FileReference.asset_id == Asset.id))
    rows = session.scalars(select(Asset).where(~referenced, Asset.created_at < cutoff.isoformat())).all()
    result = {"asset_ids": [row.id for row in rows], "byte_size": sum(row.byte_size for row in rows),
              "dry_run": dry_run}
    if dry_run:
        return result
    directories = []
    for row in rows:
        path = safe_path(settings, row.storage_key, must_exist=False).parent
        directories.append(path)
        session.execute(delete(AssetPage).where(AssetPage.asset_id == row.id))
        session.delete(row)
    session.flush()
    if directories:
        session.info.setdefault("media_delete_after_commit", []).extend(directories)
        if not session.info.get("media_cleanup_listeners"):
            session.info["media_cleanup_listeners"] = True

            def remove_committed_files(current_session):
                # A SAVEPOINT commit is not the surrounding transaction's commit.
                if current_session.in_nested_transaction():
                    return
                for path in current_session.info.pop("media_delete_after_commit", []):
                    if path.exists() and not path.is_symlink():
                        try:
                            shutil.rmtree(path)
                        except OSError:
                            # The DB is already committed; orphan GC can retry files.
                            pass

            def forget_rolled_back_files(current_session):
                current_session.info.pop("media_delete_after_commit", None)

            event.listen(session, "after_commit", remove_committed_files)
            event.listen(session, "after_rollback", forget_rolled_back_files)
    return result


def cleanup_orphan_files(session, settings, now=None, dry_run=False):
    """Reclaim crash leftovers only when old, unreferenced, and named by this service."""
    cutoff = (now or datetime.now(timezone.utc)).timestamp() - settings.media_ttl_hours * 3600
    live_ids = set(session.scalars(select(Asset.id)))
    removed = []
    for directory in private_root(settings).iterdir():
        if (directory.name.startswith("asset_") and len(directory.name) == 38
                and all(c in "0123456789abcdef" for c in directory.name[6:])
                and directory.name not in live_ids and not directory.is_symlink()
                and directory.is_dir() and directory.stat().st_mtime < cutoff):
            removed.append(directory.name)
            if not dry_run:
                shutil.rmtree(directory)
    return {"orphan_asset_ids": removed, "dry_run": dry_run}
