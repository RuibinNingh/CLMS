"""Mandatory official SDK tests over a real TCP port; no direct tool invocation."""
import base64
import hashlib
import json
import secrets
import socket
import threading
import time
from contextlib import asynccontextmanager
from io import BytesIO

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image
from sqlalchemy import select

from backend.app.config import Settings
from backend.app.db.models import Credential, Evaluation, ReadReceipt

TOOLS = {"get_capabilities", "list_categories", "search_prompts", "get_prompt", "list_attempts",
         "get_attempt", "get_version", "get_evaluation", "get_asset", "read_asset_pages",
         "list_staged_assets", "upload_asset", "upload_attachment", "list_review_items", "get_review_item", "get_history",
         "propose_category_change", "propose_prompt_change", "propose_submission", "propose_revision",
         "propose_evaluation", "propose_reflection", "revise_proposal", "withdraw_proposal"}


@pytest.fixture
def protocol_server(tmp_path):
    from backend.app.main import create_app
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    settings = Settings(data_dir=tmp_path / "protocol-archive", public_origin=origin)
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "actual uvicorn server failed to start"
    with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=30) as web:
        token = settings.bootstrap_token_file.read_text().strip()
        response = web.post("/api/auth/bootstrap", json={"username": "protocol-admin",
            "password": secrets.token_urlsafe(24), "bootstrap_token": token})
        assert response.status_code == 200, response.text
        status = web.get("/api/auth/status").json()
        web.headers["X-CSRF-Token"] = status["csrf_token"]
        credential = web.post("/api/credentials", json={"name": "SDK protocol test",
                              "scopes": ["archive.read", "media.read", "proposals.write"]}).json()
        assert "secret" in credential, credential
        yield origin, web, credential, app
    server.should_exit = True
    thread.join(timeout=10)
    sock.close()
    assert not thread.is_alive(), "real uvicorn server did not stop"


def _png(color="red"):
    output = BytesIO()
    Image.new("RGB", (120, 180), color).save(output, "PNG")
    return output.getvalue()


def _pdf():
    output = BytesIO()
    pages = [Image.new("RGB", (160, 200), color) for color in ("red", "blue", "green")]
    pages[0].save(output, "PDF", save_all=True, append_images=pages[1:])
    return output.getvalue()


def _structured(result):
    assert not result.isError, result
    return result.structuredContent or json.loads(result.content[0].text)


@asynccontextmanager
async def _sdk(origin, credential):
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {credential['secret']}"},
                                timeout=30, trust_env=False) as http:
        async with streamable_http_client(origin + "/mcp/", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                yield client


@pytest.mark.asyncio
async def test_mcp_upload_originals_private_staging_and_submission_approval(protocol_server):
    from backend.app.db.models import Asset, Attempt, Version

    origin, web, credential, app = protocol_server
    other = web.post("/api/credentials", json={"name": "Other uploader",
        "scopes": ["archive.read", "media.read", "proposals.write"]}).json()
    async with _sdk(origin, credential) as client:
        assets = []
        for name, data in [("作文.png", _png()), ("multi-page.pdf", _pdf())]:
            asset = _structured(await client.call_tool("upload_asset", {
                "filename": name, "content_base64": base64.b64encode(data).decode()}))
            assert asset["status"] == "staged" and asset["human_review_required_for_archive"]
            assert asset["sha256"] == hashlib.sha256(data).hexdigest()
            assert web.get(asset["original_url"]).content == data
            assets.append(asset)
        assert [a["page_count"] for a in assets] == [1, 3]
        with app.state.db.read() as session:
            assert session.scalar(select(Attempt)) is None
            assert session.scalar(select(Version)) is None
            assert all(a.created_by == "mcp:" + credential["id"] for a in session.scalars(select(Asset)))
        pages = [{"page_id": page["page_id"]} for asset in assets for page in asset["pages"]]
        proposal = _structured(await client.call_tool("propose_submission", {"request_id": "upload-new-attempt",
            "payload": {"prompt": {"language": "zh", "title": "MCP upload test", "instructions": "写一篇作文"},
                        "pages": pages, "duration_minutes": 35}}))
        assert proposal["status"] == "pending" and proposal["result"] is None
        async with _sdk(origin, other) as reader:
            assert _structured(await reader.call_tool("list_staged_assets", {}))["items"] == []
            for asset in assets:
                denied = await reader.call_tool("get_asset", {"asset_id": asset["id"]})
                assert denied.isError and denied.structuredContent["error"]["code"] == "permission_denied"
            stolen = await reader.call_tool("propose_submission", {"request_id": "stolen-pages",
                "payload": {"prompt": {"language": "en", "instructions": "Cannot steal"}, "pages": pages}})
            assert stolen.isError and stolen.structuredContent["error"]["code"] == "permission_denied"
        approved = web.post(f"/api/reviews/{proposal['id']}/decide", json={"decision": "approve",
            "expected_revision": proposal["revision"], "expected_digest": proposal["effective_digest"]})
        assert approved.status_code == 200, approved.text
        receipt = _structured(await client.call_tool("get_review_item", {"operation_id": proposal["id"]}))
        assert receipt["status"] == "applied"
        version = _structured(await client.call_tool("get_version", {"version_id": receipt["result"]["version_id"]}))
        assert len(version["manifest"]) == 4
        async with _sdk(origin, other) as reader:
            assert not (await reader.call_tool("get_asset", {"asset_id": assets[0]["id"]})).isError


@pytest.mark.asyncio
async def test_mcp_upload_invalid_bytes_limits_and_scope(protocol_server):
    from backend.app.db.models import Asset

    origin, web, credential, app = protocol_server
    async with _sdk(origin, credential) as client:
        app.state.settings.mcp_upload_max_bytes = len(_png()) - 1
        cases = [
            ({"filename": "../secret.png", "content_base64": "AAAA"}, "validation_error"),
            ({"filename": "empty.png", "content_base64": ""}, "validation_error"),
            ({"filename": "bad.png", "content_base64": "secret-not-base64"}, "validation_error"),
            ({"filename": "bad.png", "content_base64": "data:image/png;base64,AAAA"}, "validation_error"),
            ({"filename": "fake.png", "content_base64": "aGVsbG8="}, "unsupported_media"),
            ({"filename": "large.png", "content_base64": base64.b64encode(_png()).decode()}, "media_limit_exceeded"),
        ]
        for arguments, code in cases:
            result = await client.call_tool("upload_asset", arguments)
            assert result.isError and result.structuredContent["error"]["code"] == code
            assert "secret-not-base64" not in result.model_dump_json()
        # Schema failures must not echo sensitive file inputs either.
        result = await client.call_tool("upload_attachment", {"file": {"download_url": "secret-signed-url"}})
        assert result.isError and "secret-signed-url" not in result.model_dump_json()
    readonly = web.post("/api/credentials", json={"name": "Read only", "scopes": ["media.read"]}).json()
    async with _sdk(origin, readonly) as client:
        result = await client.call_tool("upload_asset", {"filename": "test.png", "content_base64": "AAAA"})
        assert result.isError and result.structuredContent["error"]["code"] == "permission_denied"
    with app.state.db.read() as session:
        assert session.scalar(select(Asset)) is None


@pytest.mark.asyncio
async def test_chat_file_descriptor_and_bounded_download(protocol_server, monkeypatch, caplog):
    from backend.app.db.models import Asset
    from backend.app.mcp import uploads

    origin, web, credential, app = protocol_server
    caplog.set_level("INFO", logger="httpx")
    real_client, requests = httpx.Client, []
    file = {"download_url": "https://files.oaiusercontent.com/file-test?sig=private-test-signature",
            "file_id": "file_test", "file_name": "作文.png", "mime_type": "image/png"}
    def handler(request):
        requests.append(request)
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, content=_png())
    monkeypatch.setattr(uploads, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("104.18.1.1", 443))])
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    async with _sdk(origin, credential) as client:
        tool = next(t for t in (await client.list_tools()).tools if t.name == "upload_attachment")
        assert tool.meta["openai/fileParams"] == ["file"]
        schema = tool.inputSchema["$defs"]["ChatFile"]
        assert set(schema["properties"]) == {"download_url", "file_id", "mime_type", "file_name"}
        assert set(schema["required"]) == {"download_url", "file_id"}
        asset = _structured(await client.call_tool("upload_attachment", {"file": file}))
        assert web.get(asset["original_url"]).content == _png()
        assert len(requests) == 1
        for url in ["file:///etc/passwd", "http://files.oaiusercontent.com/file", "https://127.0.0.1/file",
                    "https://files.oaiusercontent.com.evil.test/file", "https://files.oaiusercontent.com:8443/file",
                    "https://user:password@files.oaiusercontent.com/file"]:
            rejected = await client.call_tool("upload_attachment", {"file": {**file, "download_url": url}})
            assert rejected.isError
        assert len(requests) == 1
        monkeypatch.setattr(uploads, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
        assert (await client.call_tool("upload_attachment", {"file": file})).isError
        assert len(requests) == 1
        monkeypatch.setattr(uploads, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("104.18.1.1", 443))])
        def redirect(request):
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(redirect), **kw))
        rejected = await client.call_tool("upload_attachment", {"file": file})
        assert rejected.isError and "private-test-signature" not in rejected.model_dump_json()
        def too_large(request):
            return httpx.Response(200, headers={"content-length": str(app.state.settings.pdf_max_bytes + 1)})
        monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(too_large), **kw))
        rejected = await client.call_tool("upload_attachment", {"file": file})
        assert rejected.isError and rejected.structuredContent["error"]["code"] == "media_limit_exceeded"
        # Revocation during the unlocked download must prevent any persistence.
        def revoke_during_download(request):
            with app.state.db.transaction() as session:
                session.get(Credential, credential["id"]).revoked_at = "2000-01-01"
            return httpx.Response(200, content=_png())
        monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(revoke_during_download), **kw))
        rejected = await client.call_tool("upload_attachment", {"file": file})
        assert rejected.isError and rejected.structuredContent["error"]["code"] == "credential_revoked"
    with app.state.db.read() as session:
        assert len(session.scalars(select(Asset)).all()) == 1
    assert "private-test-signature" not in caplog.text


def test_mcp_large_and_chunked_requests_rejected_before_json(protocol_server):
    from backend.app.db.models import Asset

    origin, web, credential, app = protocol_server
    headers = {"Authorization": "Bearer " + credential["secret"], "Content-Type": "application/json"}
    maximum = 4 * ((app.state.settings.mcp_upload_max_bytes + 2) // 3) + 65536
    for body in [b"x" * (maximum + 1), (b"x" * 65536 for _ in range(maximum // 65536 + 2))]:
        response = web.post("/mcp/", headers=headers, content=body)
        assert response.status_code == 413, response.text
        assert response.json()["error"]["code"] == "media_limit_exceeded"
    with app.state.db.read() as session:
        assert session.scalar(select(Asset)) is None


@pytest.mark.asyncio
async def test_real_protocol_image_pdf_pending_and_web_approval(protocol_server):
    origin, web, credential, app = protocol_server
    image = web.post("/api/assets", files={"file": ("sample.png", _png(), "image/png")}).json()
    pdf = web.post("/api/assets", files={"file": ("sample.pdf", _pdf(), "application/pdf")}).json()
    result = web.post("/api/submissions", json={"prompt": {"language": "en", "title": "TCP test",
        "instructions": "Describe your observation."}, "pages": [
            {"page_id": pdf["pages"][1]["page_id"], "rotation": 0},
            {"page_id": image["pages"][0]["page_id"], "rotation": 90}]})
    assert result.status_code == 200, result.text
    submitted = result.json()
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {credential['secret']}"}, timeout=30) as http:
        async with streamable_http_client(origin + "/mcp/", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as client:
                initialized = await client.initialize()
                assert initialized.serverInfo.name == "CLMS 作文档案馆"
                discovered = await client.list_tools()
                assert {tool.name for tool in discovered.tools} == TOOLS
                assert all(tool.inputSchema.get("additionalProperties") is False for tool in discovered.tools)
                assert not any("approve" in tool.name or "credential" in tool.name for tool in discovered.tools)
                capabilities = _structured(await client.call_tool("get_capabilities", {}))
                assert capabilities["limits"]["mcp_max_pages"] == 2
                assert initialized.protocolVersion in capabilities["supported_protocol_versions"]
                assert capabilities["request_protocol_version"] == initialized.protocolVersion
                version = _structured(await client.call_tool("get_version", {"version_id": submitted["version_id"]}))
                pages = version["manifest"]
                result = await client.call_tool("read_asset_pages", {"version_id": submitted["version_id"],
                      "page_ids": [p["page_id"] for p in pages]})
                mapping = _structured(result)
                images = [block for block in result.content if block.type == "image"]
                assert len(images) == 2
                assert len(result.model_dump_json(by_alias=True).encode("utf-8")) <= app.state.settings.mcp_image_budget
                decoded = Image.open(BytesIO(base64.b64decode(images[0].data, validate=True)))
                red, green, blue = decoded.getpixel((20, 20))
                assert blue > red + 100 and blue > green + 100
                assert mapping["pages"][0]["source_page"] == 2 and mapping["pages"][0]["order"] == 1
                assert mapping["pages"][1]["rotation"] == 90
                assert mapping["pages"][1]["width"] == pages[1]["width"]
                assert mapping["pages"][1]["height"] == pages[1]["height"]
                assert mapping["pages"][1]["source_width"] == image["pages"][0]["width"]
                assert mapping["pages"][0]["manifest_hash"] == version["manifest_hash"]
                assert mapping["pages"][0]["version_id"] == submitted["version_id"]
                assert "storage_key" not in json.dumps(mapping)
                # Read a bounded rotated area and verify the returned coordinate mapping.
                region_result = await client.call_tool("read_asset_pages", {"version_id": submitted["version_id"],
                      "page_ids": [pages[1]["page_id"]], "quality": "high", "region": [0.1, 0.1, 0.5, 0.5]})
                assert _structured(region_result)["pages"][0]["region"] == [0.1, 0.1, 0.5, 0.5]
                with app.state.db.read() as session:
                    delivered_before = len(session.scalars(select(ReadReceipt)).all())
                previous_budget = app.state.settings.mcp_image_budget
                # A budget that covers only Base64 + one metadata copy must fail:
                # the actual tool JSON includes both metadata copies and receipt ID.
                legacy_budget = sum(len(block.data) for block in images) + len(json.dumps(mapping, ensure_ascii=False).encode()) + 20
                assert legacy_budget < len(result.model_dump_json(by_alias=True).encode("utf-8"))
                app.state.settings.mcp_image_budget = legacy_budget
                exceeded_metadata = await client.call_tool("read_asset_pages", {"version_id": submitted["version_id"],
                    "page_ids": [p["page_id"] for p in pages]})
                assert exceeded_metadata.isError and exceeded_metadata.structuredContent["error"]["code"] == "media_limit_exceeded"
                app.state.settings.mcp_image_budget = 10
                exceeded = await client.call_tool("read_asset_pages", {"version_id": submitted["version_id"]})
                assert exceeded.isError and exceeded.structuredContent["error"]["code"] == "media_limit_exceeded"
                app.state.settings.mcp_image_budget = previous_budget
                with app.state.db.read() as session:
                    assert len(session.scalars(select(ReadReceipt)).all()) == delivered_before
                override = await client.call_tool("read_asset_pages", {"version_id": submitted["version_id"], "rotation": 90})
                assert override.isError and override.structuredContent["error"]["code"] == "validation_error"
                payload = {"version_id": version["id"], "expected_manifest_hash": version["manifest_hash"],
                    "expected_prompt_snapshot_hash": version["prompt_snapshot_hash"],
                    "coverage": {"scope": "full", "reviewed_page_ids": [p["page_id"] for p in pages]},
                    "summary": "Protocol test feedback", "score": None, "strengths": ["Clear organization"],
                    "issues": [], "next_actions": ["Add a specific detail"]}
                proposed = _structured(await client.call_tool("propose_evaluation", {"payload": payload,
                                              "request_id": "official-sdk-evaluation"}))
                operation_id = proposed.get("operation_id", proposed.get("id"))
                assert proposed["status"] == "pending" and proposed["requires_human_review"] is True
                with app.state.db.read() as session:
                    assert session.scalar(select(Evaluation)) is None
                review = _structured(await client.call_tool("get_review_item", {"operation_id": operation_id}))
                response = web.post(f"/api/reviews/{operation_id}/decide", json={"decision": "approve",
                          "expected_revision": review["revision"], "expected_digest": review["effective_digest"]})
                assert response.status_code == 200, response.text
                approved = _structured(await client.call_tool("get_review_item", {"operation_id": operation_id}))
                assert approved["status"] == "applied"
                with app.state.db.read() as session:
                    evaluation = session.scalar(select(Evaluation))
                    assert evaluation is not None and evaluation.version_id == version["id"]
                evaluation_result = _structured(await client.call_tool("get_evaluation", {"evaluation_id": evaluation.id}))
                assert evaluation_result["version_id"] == version["id"]
                # Unknown admin tool and actor injection cannot grant permissions.
                forbidden = await client.call_tool("approve_review", {"operation_id": operation_id})
                assert forbidden.isError
                injection = await client.call_tool("propose_category_change", {"payload": {
                    "action": "create", "name": "Protocol category"}, "request_id": "actor-injection",
                    "source_actor": "web:admin"})
                assert injection.isError and injection.structuredContent["error"]["code"] == "validation_error"
                bad_payload = await client.call_tool("propose_category_change", {"payload": {
                    "action": "create", "name": "Bad category", "admin": True}, "request_id": "unknown-field"})
                assert bad_payload.isError and bad_payload.structuredContent["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_current_request_scopes_and_revocation(protocol_server):
    origin, web, credential, app = protocol_server
    image = web.post("/api/assets", files={"file": ("sample.png", _png(), "image/png")}).json()
    try:
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {credential['secret']}"}, timeout=30) as http:
            async with streamable_http_client(origin + "/mcp/", http_client=http) as (read, write, _):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    assert not (await client.call_tool("get_asset", {"asset_id": image["id"]})).isError
                    # Change the scope while the official SDK client remains initialized.
                    with app.state.db.transaction() as session:
                        session.get(Credential, credential["id"]).scopes = ["archive.read"]
                    denied = await client.call_tool("get_asset", {"asset_id": image["id"]})
                    assert denied.isError and denied.structuredContent["error"]["code"] == "permission_denied"
                    assert not (await client.call_tool("list_categories", {})).isError
                    response = web.post(f"/api/credentials/{credential['id']}/revoke", json={})
                    assert response.status_code == 200
                    # The same client cannot retain its previous permission after revocation.
                    with pytest.raises(Exception) as revoked:
                        await client.call_tool("get_capabilities", {})
                    assert "401" in str(revoked.value) or "terminated" in str(revoked.value).lower()
    except ExceptionGroup as group:
        def leaves(error):
            if isinstance(error, BaseExceptionGroup):
                return [leaf for item in error.exceptions for leaf in leaves(item)]
            return [error]
        assert all(isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 401
                   for error in leaves(group)), repr(group)
    async with httpx.AsyncClient() as http:
        unauthenticated = await http.post(origin + "/mcp/", json={"jsonrpc": "2.0", "id": 1,
                                                       "method": "tools/list"})
        assert unauthenticated.status_code == 401
        revoked = await http.post(origin + "/mcp/", headers={"Authorization": f"Bearer {credential['secret']}"},
                                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert revoked.status_code == 401 and revoked.json()["error"]["code"] == "credential_revoked"


@pytest.mark.asyncio
async def test_entire_catalog_and_private_proposals(protocol_server):
    origin, web, credential, app = protocol_server
    asset = web.post("/api/assets", files={"file": ("sample.png", _png(), "image/png")}).json()
    response = web.post("/api/submissions", json={"prompt": {"language": "zh", "instructions": "描述一次经历"},
                       "pages": [{"page_id": asset["pages"][0]["page_id"]}]})
    assert response.status_code == 200, response.text
    formal = response.json()
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {credential['secret']}"}, timeout=30) as http:
        async with streamable_http_client(origin + "/mcp/", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                for tool_name, arguments in [
                    ("list_categories", {}), ("search_prompts", {"q": "经历"}),
                    ("get_prompt", {"prompt_id": formal["prompt_id"]}),
                    ("list_attempts", {"prompt_id": formal["prompt_id"]}),
                    ("get_attempt", {"attempt_id": formal["attempt_id"]}),
                    ("get_asset", {"asset_id": asset["id"]}), ("list_staged_assets", {}),
                    ("list_review_items", {}), ("get_history", {"version_id": formal["version_id"]})]:
                    _structured(await client.call_tool(tool_name, arguments))
                category = _structured(await client.call_tool("propose_category_change", {"request_id": "category",
                    "payload": {"action": "create", "name": "叙述练习", "language_scope": "zh"}}))
                edited = _structured(await client.call_tool("revise_proposal", {"operation_id": category["operation_id"],
                    "expected_revision": category["revision"], "changes": {"name": "自己的分类"}}))
                assert edited["revision"] == 2 and edited["payload"]["name"] == "自己的分类"
                retry = _structured(await client.call_tool("propose_category_change", {"request_id": "category",
                    "payload": {"action": "create", "name": "叙述练习", "language_scope": "zh"}}))
                assert retry["revision"] == 2 and retry["payload"]["name"] == "自己的分类"
                assert _structured(await client.call_tool("list_categories", {}))["items"] == []
                withdrawn = _structured(await client.call_tool("withdraw_proposal", {"operation_id": category["operation_id"],
                    "expected_revision": 2}))
                assert withdrawn["status"] == "withdrawn"
                for name, payload in [
                    ("propose_prompt_change", {"action": "update", "prompt_id": formal["prompt_id"],
                      "expected_revision": 1, "title": "人工审核后修改题目"}),
                    ("propose_submission", {"prompt_id": formal["prompt_id"],
                      "pages": [{"page_id": asset["pages"][0]["page_id"]}]}),
                    ("propose_revision", {"attempt_id": formal["attempt_id"], "parent_version_id": formal["version_id"],
                      "pages": [{"page_id": asset["pages"][0]["page_id"], "rotation": 90}]}),
                    ("propose_reflection", {"attempt_id": formal["attempt_id"], "expected_revision": 1,
                      "reflection": "下次增加具体细节"})]:
                    proposal = _structured(await client.call_tool(name, {"payload": payload, "request_id": name}))
                    assert proposal["status"] == "pending" and proposal["requires_human_review"]
                own_pending = _structured(await client.call_tool("list_review_items", {}))
                assert len(own_pending["items"]) == 4
                other = web.post("/api/credentials", json={"name": "other client",
                                 "scopes": ["archive.read", "media.read", "proposals.write"]}).json()
                # A new bearer on the same initialized client must select its own source actor.
                http.headers["Authorization"] = f"Bearer {other['secret']}"
                denied = await client.call_tool("get_review_item", {"operation_id": proposal["operation_id"]})
                assert denied.isError and denied.structuredContent["error"]["code"] == "permission_denied"
                assert _structured(await client.call_tool("list_review_items", {}))["items"] == []


def test_simulation_cli_real_sdk_no_ai_no_approval(protocol_server):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from backend.app.db.models import ReviewOperation
    origin, web, credential, app = protocol_server
    pdf = web.post("/api/assets", files={"file": ("sample.pdf", _pdf(), "application/pdf")}).json()
    image = web.post("/api/assets", files={"file": ("material.png", _png(), "image/png")}).json()
    response = web.post("/api/submissions", json={"prompt": {"language": "zh", "instructions": "", "materials": [
                      {"page_id": image["pages"][0]["page_id"], "rotation": 90}]},
                      "pages": [{"page_id": p["page_id"]} for p in pdf["pages"]]})
    assert response.status_code == 200, response.text
    formal = response.json()
    environment = dict(os.environ)
    environment["CLMS_MCP_TOKEN"] = credential["secret"]
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / "scripts/simulate_client.py"),
        "--endpoint", origin + "/mcp/", "--version-id", formal["version_id"],
        "--request-id", "simulation-cli-test", "--category", "模拟专用分类"],
        env=environment, capture_output=True, text=True, timeout=30, cwd=root, check=False)
    assert result.returncode == 0, result.stderr
    assert credential["secret"] not in result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["simulation"] and receipt["ai_model_used"] is False and receipt["approval_performed"] is False
    assert receipt["evaluation_receipt"]["status"] == "pending" and receipt["category_receipt"]["status"] == "pending"
    assert len(receipt["manuscript_delivery"]) == 3 and len(receipt["material_delivery"]) == 1
    assert receipt["material_delivery"][0]["rotation"] == 90
    assert receipt["review_url"] == origin + receipt["evaluation_receipt"]["review_path"]
    assert receipt["evaluation_receipt"]["payload"]["score"] is None
    assert "脚本模拟" in receipt["evaluation_receipt"]["payload"]["summary"]
    with app.state.db.read() as session:
        assert session.scalar(select(Evaluation)) is None
        assert len(session.scalars(select(ReviewOperation).where(ReviewOperation.status == "pending")).all()) == 2


@pytest.mark.asyncio
async def test_single_manuscript_limit_keeps_material_union_protected(protocol_server):
    from datetime import datetime, timedelta, timezone

    from backend.app.db.models import FileReference, ReviewOperation
    from backend.app.media import cleanup

    origin, web, credential, app = protocol_server
    app.state.settings.version_max_pages = 1
    material = web.post("/api/assets", files={"file": ("material.png", _png("blue"), "image/png")}).json()
    manuscript = web.post("/api/assets", files={"file": ("manuscript.png", _png("red"), "image/png")}).json()
    payload = {"prompt": {"language": "zh", "instructions": "", "materials": [
        {"page_id": material["pages"][0]["page_id"]}]},
        "pages": [{"page_id": manuscript["pages"][0]["page_id"]}]}
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {credential['secret']}"}, timeout=30) as http:
        async with streamable_http_client(origin + "/mcp/", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                proposal = _structured(await client.call_tool("propose_submission", {
                    "payload": payload, "request_id": "separate-material-manuscript-limit"}))
                assert proposal["status"] == "pending"
                operation_id = proposal["operation_id"]
                with app.state.db.transaction() as session:
                    protected = set(session.scalars(select(FileReference.asset_id).where(
                        FileReference.owner_type == "review", FileReference.owner_id == operation_id)))
                    assert protected == {material["id"], manuscript["id"]}
                    future = datetime.now(timezone.utc) + timedelta(days=5)
                    assert cleanup(session, app.state.settings, now=future)["asset_ids"] == []
                oversized = await client.call_tool("propose_submission", {"request_id": "too-many-manuscript-pages",
                    "payload": {**payload, "pages": [
                        {"page_id": manuscript["pages"][0]["page_id"]},
                        {"page_id": material["pages"][0]["page_id"]}]}})
                assert oversized.isError
                assert oversized.structuredContent["error"]["code"] == "media_limit_exceeded"
                with app.state.db.read() as session:
                    assert len(session.scalars(select(ReviewOperation)).all()) == 1
                    assert set(session.scalars(select(FileReference.asset_id))) == protected


@pytest.mark.asyncio
async def test_upload_rejects_unauthenticated_and_csrf_before_receive(web, app, settings):
    from urllib.parse import urlsplit

    async def forbidden_receive():
        raise AssertionError("Rejected upload must not consume or spool any multipart body")

    async def invoke(cookie=None):
        messages = []
        async def capture(message):
            messages.append(message)
        origin = urlsplit(settings.public_origin)
        headers = [(b"host", origin.netloc.encode()), (b"origin", settings.public_origin.encode()),
                   (b"content-type", b"multipart/form-data; boundary=early-auth-test")]
        if cookie:
            headers.append((b"cookie", ("clms_session=" + cookie).encode()))
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/api/assets", "raw_path": b"/api/assets",
                 "query_string": b"", "root_path": "", "headers": headers,
                 "client": ("127.0.0.1", 12345), "server": ("testserver", 80)}
        await app(scope, forbidden_receive, capture)
        response = next(message for message in messages if message["type"] == "http.response.start")
        return response["status"]

    assert await invoke() == 401
    assert await invoke(web.cookies.get("clms_session")) == 403
