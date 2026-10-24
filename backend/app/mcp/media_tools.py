import base64
import json

from mcp.types import CallToolResult, ImageContent, TextContent

from backend.app.auth.service import recheck_actor
from backend.app.db.models import ReadReceipt, uid
from backend.app.domain import query
from backend.app.errors import require
from backend.app.media import asset_view, page_image


def read_pages(session, settings, actor, *, version_id=None, asset_id=None, page_ids=None,
               quality="normal", region=None, rotation=0):
    require(bool(version_id) != bool(asset_id), "validation_error", "稿件ID和受控文件ID必须二选一")
    manifest_hash, snapshot_hash = None, None
    if version_id:
        require(rotation == 0, "validation_error", "稿件读取使用已冻结旋转，不允许覆盖")
        recheck_actor(session, actor, "archive.read")
        version = query.get_version(session, version_id)
        manifest, manifest_hash = version["manifest"], version["manifest_hash"]
        snapshot_hash = version["prompt_snapshot_hash"]
    else:
        require(rotation in (0, 90, 180, 270), "validation_error", "旋转角度无效")
        manifest = asset_view(session, asset_id, actor)["pages"]
        manifest = [{**page, "rotation": rotation,
                     "width": page["height"] if rotation in (90, 270) else page["width"],
                     "height": page["width"] if rotation in (90, 270) else page["height"]}
                    for page in manifest]
    selected = page_ids or [manifest[0]["page_id"]]
    require(len(selected) <= settings.mcp_max_pages and len(selected) >= 1,
            "media_limit_exceeded", f"一次最多读取 {settings.mcp_max_pages} 页")
    require(len(selected) == len(set(selected)), "validation_error", "页面ID不能重复")
    available = {page["page_id"] for page in manifest}
    require(set(selected) <= available, "validation_error", "页面不属于指定稿件或文件")
    images, mappings = [], []
    for page in manifest:
        if page["page_id"] not in selected:
            continue
        data, metadata = page_image(session, settings, page["page_id"], rotation=page["rotation"],
                                    quality=quality, bbox=region, actor=actor)
        encoded = base64.b64encode(data).decode("ascii")
        metadata.update({"order": page["order"], "width": page["width"], "height": page["height"],
                         "version_id": version_id,
                         "manifest_hash": manifest_hash, "prompt_snapshot_hash": snapshot_hash})
        mappings.append(metadata)
        images.append(ImageContent(type="image", data=encoded, mimeType="image/jpeg"))
    metadata = {"pages": mappings, "next_page_ids": [page["page_id"] for page in manifest
                if page["page_id"] not in selected], "total_pages": len(manifest),
                "response_budget_bytes": settings.mcp_image_budget,
                "read_receipt_notice": "仅证明服务端交付了这些页面，不证明模型理解。"}
    receipt_id = uid("read")
    metadata["read_receipt_id"] = receipt_id
    result = CallToolResult(content=[TextContent(type="text", text=json.dumps(metadata,
                            ensure_ascii=False)), *images], structuredContent=metadata)
    # Includes Base64, both text/structured mappings and the eventual receipt ID.
    # Default serialization also counts nullable fields, conservatively bounding
    # the SDK's wire representation (which omits nulls).
    require(len(result.model_dump_json(by_alias=True).encode("utf-8")) <= settings.mcp_image_budget,
            "media_limit_exceeded", "图像响应超出预算，请降低清晰度或缩小区域")
    session.add(ReadReceipt(id=receipt_id, credential_id=actor[4:], version_id=version_id,
                           page_ids=[page["page_id"] for page in mappings]))
    session.flush()
    return result
