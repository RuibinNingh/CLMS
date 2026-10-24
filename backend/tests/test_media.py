import hashlib
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from PIL import Image

from backend.app.config import Settings
from backend.app.db.base import Base, Database
from backend.app.db.models import Asset, FileReference
from backend.app.media import (
    MediaError,
    asset_view,
    cleanup,
    original_path,
    page_image,
    staged_assets,
    upload,
)
from backend.app.media.storage import safe_path


@pytest.fixture
def media_env(tmp_path):
    settings = Settings(data_dir=tmp_path)
    db = Database(settings)
    Base.metadata.create_all(db.engine)
    return settings, db


def image_bytes(color="blue", size=(100, 60)):
    stream = BytesIO()
    Image.new("RGB", size, color).save(stream, "PNG")
    return stream.getvalue()


def pdf_bytes():
    stream = BytesIO()
    images = [Image.new("RGB", (120, 160), color) for color in ("red", "blue", "green")]
    images[0].save(stream, "PDF", save_all=True, append_images=images[1:])
    return stream.getvalue()


def test_original_hash_and_derivatives(media_env):
    settings, db = media_env
    data = image_bytes()
    with db.transaction() as session:
        asset = upload(session, settings, BytesIO(data), "sample.png", "web:admin")
    with db.read() as session:
        assert original_path(session, settings, asset["id"]).read_bytes() == data
        assert asset["sha256"] == hashlib.sha256(data).hexdigest()
        page = asset["pages"][0]
        encoded, metadata = page_image(session, settings, page["page_id"], rotation=90,
                                       bbox=[0.1, 0.1, 0.5, 0.5])
        image = Image.open(BytesIO(encoded))
        assert image.size == (30, 50)
        assert metadata["source_page"] == 1 and metadata["rotation"] == 90
        assert metadata["asset_sha256"] == asset["sha256"]
        assert metadata["region"] == [0.1, 0.1, 0.5, 0.5]


def test_pdf_pages_original_and_colors(media_env):
    settings, db = media_env
    data = pdf_bytes()
    with db.transaction() as session:
        asset = upload(session, settings, BytesIO(data), "sample.pdf", "web:admin")
    assert asset["mime"] == "application/pdf" and asset["page_count"] == 3
    assert [p["source_page"] for p in asset["pages"]] == [1, 2, 3]
    with db.read() as session:
        assert original_path(session, settings, asset["id"]).read_bytes() == data
        encoded, metadata = page_image(session, settings, asset["pages"][1]["page_id"])
        red, green, blue = Image.open(BytesIO(encoded)).getpixel((20, 20))
        assert blue > red + 100 and blue > green + 100
        assert metadata["source_page"] == 2


@pytest.mark.parametrize("filename,data,code", [
    ("../../escape.png", b"", "validation_error"),
    ("fake.jpg", image_bytes(), "unsupported_media"),
    ("corrupt.png", b"\x89PNG\r\n\x1a\nBAD", "unsupported_media"),
    ("corrupt.pdf", b"%PDF-1.7\nbad", "unsupported_media"),
    ("document.txt", b"hello", "unsupported_media")])
def test_rejected_uploads(media_env, filename, data, code):
    settings, db = media_env
    with pytest.raises(MediaError) as error, db.transaction() as session:
        upload(session, settings, BytesIO(data), filename, "web:admin")
    assert error.value.code == code
    assert list((settings.data_dir / "media").glob("asset_*")) == []


def test_limits_page_crop_and_symlink(media_env, tmp_path):
    settings, db = media_env
    settings.image_max_pixels = 50
    with pytest.raises(MediaError, match="像素"), db.transaction() as session:
        upload(session, settings, BytesIO(image_bytes()), "image.png", "web:admin")
    settings.image_max_pixels = 40_000_000
    settings.image_max_bytes = 10
    with pytest.raises(MediaError, match="大小"), db.transaction() as session:
        upload(session, settings, BytesIO(image_bytes()), "image.png", "web:admin")
    settings.image_max_bytes = 1024**2
    settings.pdf_max_pages = 2
    with pytest.raises(MediaError, match="页数"), db.transaction() as session:
        upload(session, settings, BytesIO(pdf_bytes()), "sample.pdf", "web:admin")
    with db.transaction() as session:
        asset = upload(session, settings, BytesIO(image_bytes()), "sample.png", "web:admin")
    with db.read() as session:
        for arguments in ({"bbox": [-0.1, 0, 1, 1]}, {"rotation": 45}, {"quality": "unlimited"}):
            with pytest.raises(MediaError):
                page_image(session, settings, asset["pages"][0]["page_id"], **arguments)
        with pytest.raises(MediaError):
            page_image(session, settings, "page_missing")
    original = settings.data_dir / "media" / asset["id"] / "original"
    original.unlink()
    original.symlink_to(tmp_path / "outside-secret")
    with db.read() as session, pytest.raises(MediaError):
        original_path(session, settings, asset["id"])
    with pytest.raises(MediaError):
        safe_path(settings, "../private")


def test_cleanup_reference_and_rollback(media_env):
    settings, db = media_env
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    with db.transaction() as session:
        assets = [upload(session, settings, BytesIO(image_bytes()), f"{index}.png", "web:admin")
                  for index in range(3)]
        for asset in assets:
            session.get(Asset, asset["id"]).created_at = old
        session.add(FileReference(owner_type="review", owner_id="pending", asset_id=assets[0]["id"]))
        session.add(FileReference(owner_type="version", owner_id="formal", asset_id=assets[1]["id"]))
    with pytest.raises(RuntimeError), db.transaction() as session:
        result = cleanup(session, settings)
        assert result["asset_ids"] == [assets[2]["id"]]
        raise RuntimeError("rollback")
    with db.read() as session:
        assert original_path(session, settings, assets[2]["id"]).is_file()
    with db.transaction() as session:
        result = cleanup(session, settings)
    assert result["asset_ids"] == [assets[2]["id"]]
    assert not (settings.data_dir / "media" / assets[2]["id"]).exists()
    with db.read() as session:
        for asset in assets[:2]:
            assert original_path(session, settings, asset["id"]).is_file()


def test_mcp_private_staging_and_formal_share(media_env):
    settings, db = media_env
    with db.transaction() as session:
        asset = upload(session, settings, BytesIO(image_bytes()), "private.png", "mcp:first")
        shared = upload(session, settings, BytesIO(image_bytes()), "shared.png", "web:admin")
        session.add(FileReference(owner_type="review", owner_id="pending", asset_id=asset["id"]))
    with db.read() as session:
        assert asset_view(session, shared["id"], "mcp:second")["id"] == shared["id"]
        with pytest.raises(MediaError):
            asset_view(session, asset["id"], "mcp:second")
    with db.transaction() as session:
        session.add(FileReference(owner_type="version", owner_id="formal", asset_id=asset["id"]))
    with db.read() as session:
        assert asset_view(session, asset["id"], "mcp:second")["id"] == asset["id"]


@pytest.mark.parametrize("format_name,filename", [("JPEG", "photo.jpg"), ("WEBP", "photo.webp")])
def test_supported_image_formats(media_env, format_name, filename):
    settings, db = media_env
    source = BytesIO()
    Image.new("RGB", (25, 40), "yellow").save(source, format_name)
    with db.transaction() as session:
        asset = upload(session, settings, BytesIO(source.getvalue()), filename, "web:admin")
    with db.read() as session:
        assert original_path(session, settings, asset["id"]).read_bytes() == source.getvalue()
        assert page_image(session, settings, asset["pages"][0]["page_id"])[0].startswith(b"\xff\xd8\xff")


def test_actual_pdf_worker_timeout(media_env):
    settings, db = media_env
    settings.pdf_render_timeout = 0.001
    with pytest.raises(MediaError, match="超时"), db.transaction() as session:
        upload(session, settings, BytesIO(pdf_bytes()), "timeout.pdf", "web:admin")
    assert list((settings.data_dir / "media").glob("asset_*")) == []


def test_orphan_cleanup_is_bounded(media_env):
    import os

    from backend.app.media import cleanup_orphan_files
    settings, db = media_env
    with db.transaction() as session:
        asset = upload(session, settings, BytesIO(image_bytes()), "keep.png", "web:admin")
    root = settings.data_dir / "media"
    orphan = root / ("asset_" + "0" * 32)
    orphan.mkdir()
    (orphan / "original").write_bytes(b"orphan")
    unknown = root / "unrelated"
    unknown.mkdir()
    link = root / ("asset_" + "1" * 32)
    link.symlink_to(unknown, target_is_directory=True)
    old = (datetime.now(timezone.utc) - timedelta(days=5)).timestamp()
    for path in (orphan, unknown, root / asset["id"]):
        os.utime(path, (old, old))
    with db.transaction() as session:
        preview = cleanup_orphan_files(session, settings, dry_run=True)
        assert preview["orphan_asset_ids"] == [orphan.name] and orphan.exists()
        assert cleanup_orphan_files(session, settings)["orphan_asset_ids"] == [orphan.name]
    assert not orphan.exists() and unknown.exists() and link.is_symlink()
    assert (root / asset["id"] / "original").is_file()


def test_cleanup_reused_session_and_savepoint_never_delete_on_rollback(media_env):
    settings, db = media_env
    with db.transaction() as session:
        asset = upload(session, settings, BytesIO(image_bytes()), "rollback.png", "web:admin")
        session.get(Asset, asset["id"]).created_at = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    original = settings.data_dir / "media" / asset["id"] / "original"
    with db.session_factory() as session:
        with pytest.raises(RuntimeError), session.begin():
            cleanup(session, settings)
            with session.begin_nested():
                pass
            assert original.exists(), "SAVEPOINT commit cannot delete bytes"
            raise RuntimeError("rollback outer")
        assert original.exists()
        # Same Session commits unrelated work after rollback: old callback must be gone.
        with session.begin():
            assert session.get(Asset, asset["id"]) is not None
        assert original.exists()


def test_transparent_original_keeps_visible_ink_on_white_paper(media_env):
    from PIL import ImageDraw
    settings, db = media_env
    source = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(source).rectangle((20, 20, 80, 80), fill=(0, 0, 0, 255))
    stream = BytesIO()
    source.save(stream, "PNG")
    data = stream.getvalue()
    with db.transaction() as session:
        asset = upload(session, settings, BytesIO(data), "transparent.png", "web:admin")
    with db.read() as session:
        preview = Image.open(BytesIO(page_image(session, settings, asset["pages"][0]["page_id"])[0]))
        assert min(preview.getpixel((5, 5))) > 245
        assert max(preview.getpixel((50, 50))) < 10
        assert original_path(session, settings, asset["id"]).read_bytes() == data


def encrypted_pdf_bytes(password):
    """Minimal valid Standard Security R2 PDF; fixture encryption uses only stdlib."""
    import struct
    padding = bytes.fromhex("28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a")
    def pad(value):
        return (value.encode("ascii") + padding)[:32]
    def rc4(key, source):
        table, j = list(range(256)), 0
        for i in range(256):
            j = (j + table[i] + key[i % len(key)]) % 256
            table[i], table[j] = table[j], table[i]
        i, j, output = 0, 0, bytearray()
        for byte in source:
            i = (i + 1) % 256
            j = (j + table[i]) % 256
            table[i], table[j] = table[j], table[i]
            output.append(byte ^ table[(table[i] + table[j]) % 256])
        return bytes(output)
    document_id = bytes.fromhex("00112233445566778899aabbccddeeff")
    owner_key = hashlib.md5(pad("owner-test-password"), usedforsecurity=False).digest()[:5]
    owner = rc4(owner_key, pad(password))
    key = hashlib.md5(pad(password) + owner + struct.pack("<i", -4) + document_id,
                      usedforsecurity=False).digest()[:5]
    user = rc4(key, padding)
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 4 0 R >>",
               b"<< /Length 0 >>\nstream\n\nendstream",
               f"<< /Filter /Standard /V 1 /R 2 /Length 40 /O <{owner.hex()}> /U <{user.hex()}> /P -4 >>".encode()]
    output, offsets = bytearray(b"%PDF-1.4\n"), [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(output)
    output.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size 6 /Root 1 0 R /Encrypt 5 0 R /ID [<{document_id.hex()}> <{document_id.hex()}>] >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


@pytest.mark.parametrize("password", ["private-test-password", ""])
def test_valid_encrypted_pdf_rejected_even_empty_password(media_env, password):
    import pypdfium2
    settings, db = media_env
    data = encrypted_pdf_bytes(password)
    # Prove this is a decryptable encrypted document, not a corrupt fixture.
    document = pypdfium2.PdfDocument(data, password=password)
    assert len(document) == 1
    assert pypdfium2.raw.FPDF_GetSecurityHandlerRevision(document) == 2
    document.close()
    with pytest.raises(MediaError) as error, db.transaction() as session:
        upload(session, settings, BytesIO(data), "encrypted.pdf", "web:admin")
    assert error.value.code == "unsupported_media"
    assert list((settings.data_dir / "media").glob("asset_*")) == []


def test_actual_pdf_memory_limit(media_env):
    settings, db = media_env
    settings.pdf_render_memory_mb = 1
    with pytest.raises(MediaError) as error, db.transaction() as session:
        upload(session, settings, BytesIO(pdf_bytes()), "memory.pdf", "web:admin")
    assert error.value.code == "media_limit_exceeded"
    assert list((settings.data_dir / "media").glob("asset_*")) == []



def test_staged_assets_obey_configured_pagination_limit(media_env):
    settings, db = media_env
    settings.max_page_size = 1
    with db.transaction() as session:
        assets = [upload(session, settings, BytesIO(image_bytes()), f"page-{index}.png", "web:admin")
                  for index in range(2)]
    with db.read() as session:
        for actor in ("web:admin", "mcp:reader"):
            with pytest.raises(MediaError) as error:
                staged_assets(session, actor, limit=2)
            assert error.value.code == "validation_error"
            assert "1–1" in error.value.message
            first = staged_assets(session, actor, limit=1)
            assert len(first["items"]) == 1 and first["next_cursor"] is not None
            second = staged_assets(session, actor, cursor=first["next_cursor"], limit=1)
            assert len(second["items"]) == 1 and second["next_cursor"] is None
            assert {item["id"] for item in first["items"] + second["items"]} == {asset["id"] for asset in assets}
