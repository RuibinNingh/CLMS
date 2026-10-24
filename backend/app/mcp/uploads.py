"""Stage client bytes or host-provided ChatGPT files without creating archive records."""
import base64
import binascii
import ipaddress
import logging
from contextlib import contextmanager
from io import BytesIO
from socket import SOCK_STREAM, getaddrinfo
from tempfile import SpooledTemporaryFile
from time import monotonic
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.app.media import service
from backend.app.media.render import sniff
from backend.app.media.storage import MediaError, validate_name

CHAT_FILE_HOST = "files.oaiusercontent.com"


class _PrivateDownloadLog(logging.Filter):
    def filter(self, record):
        # HTTPX otherwise emits the complete signed URL at INFO level.
        return CHAT_FILE_HOST not in record.getMessage()


logging.getLogger("httpx").addFilter(_PrivateDownloadLog())


class ChatFile(BaseModel):
    # All four properties are required in the descriptor, but only the first
    # two may be required values under openai/fileParams.
    model_config = ConfigDict(extra="forbid")
    download_url: str = Field(min_length=1, max_length=16384, repr=False)
    file_id: str = Field(min_length=1, max_length=512)
    mime_type: str = Field(default="", max_length=120)
    file_name: str = Field(default="", max_length=255)


def stage_base64(session, settings, actor, filename, content_base64):
    validate_name(filename)
    maximum = settings.mcp_upload_max_bytes
    if len(content_base64) > 4 * ((maximum + 2) // 3):
        raise MediaError("media_limit_exceeded", "MCP 附件超出字节上传限额。")
    try:
        data = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error) as error:
        raise MediaError("validation_error", "附件必须是完整、有效的标准 Base64 文件字节。") from error
    if not data:
        raise MediaError("validation_error", "不能上传空附件。")
    if len(data) > maximum:
        raise MediaError("media_limit_exceeded", "MCP 附件超出字节上传限额。")
    with BytesIO(data) as stream:
        return staged(service.upload(session, settings, stream, filename, actor))


def staged(asset):
    return {**asset, "status": "staged", "next_step": "propose_submission or propose_revision",
            "human_review_required_for_archive": True}


def validate_chat_url(url):
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname == CHAT_FILE_HOST
                 and parsed.port in (None, 443) and not parsed.username
                 and not parsed.password and not parsed.fragment and parsed.path.startswith("/"))
    except ValueError:
        valid = False
    if not valid:
        raise MediaError("validation_error", "只接受 ChatGPT 附件服务的 HTTPS 临时下载地址。")
    try:
        addresses = getaddrinfo(CHAT_FILE_HOST, 443, type=SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
            raise MediaError("permission_denied", "附件下载地址不能解析到内网或保留地址。", 403)
    except OSError as error:
        raise MediaError("media_unavailable", "附件服务暂时不可用，请稍后重试。", 502) from error


def attachment_name(header):
    for extension in (".png", ".jpg", ".webp", ".pdf"):
        name = "attachment" + extension
        try:
            sniff(header, name)
            return name
        except MediaError:
            pass
    raise MediaError("unsupported_media", "附件只支持 JPEG、PNG、WebP 和 PDF。")


@contextmanager
def chat_file_stream(settings, file):
    if file.file_name:
        validate_name(file.file_name)
    validate_chat_url(file.download_url)
    maximum = max(settings.image_max_bytes, settings.pdf_max_bytes)
    deadline = monotonic() + 30
    # Never forward the MCP Bearer, cookies or proxy credentials. Never follow
    # redirects, even to another OpenAI host. Signed URLs are not persisted.
    with SpooledTemporaryFile(max_size=1024**2, mode="w+b") as stream:
        try:
            with httpx.Client(timeout=httpx.Timeout(30, connect=10), follow_redirects=False,
                              trust_env=False) as client:
                with client.stream("GET", file.download_url, headers={"Accept-Encoding": "identity"}) as response:
                    if response.status_code != 200:
                        raise MediaError("media_unavailable", "附件链接不可用或已过期，请重新选择附件。", 502)
                    if response.headers.get("content-encoding", "identity").lower() not in ("", "identity"):
                        raise MediaError("unsupported_media", "附件下载不接受额外的传输压缩。")
                    length = response.headers.get("content-length")
                    if length and (not length.isdecimal() or int(length) > maximum):
                        raise MediaError("media_limit_exceeded", "附件大小超出上传限额。")
                    total, header, filename, mime = 0, b"", file.file_name, None
                    for chunk in response.iter_bytes(chunk_size=65536):
                        if monotonic() > deadline:
                            raise MediaError("media_unavailable", "附件下载超时，请重新选择附件后重试。", 502)
                        total += len(chunk)
                        header = (header + chunk)[:32]
                        if mime is None and len(header) >= 32:
                            filename = filename or attachment_name(header)
                            mime = sniff(header, filename)
                            maximum = settings.pdf_max_bytes if mime == "application/pdf" else settings.image_max_bytes
                        if total > maximum:
                            raise MediaError("media_limit_exceeded", "附件大小超出对应格式限额。")
                        stream.write(chunk)
            if not total:
                raise MediaError("validation_error", "不能上传空附件。")
            filename = filename or attachment_name(header)
            mime = sniff(header, filename)
            if file.mime_type and file.mime_type != mime:
                raise MediaError("unsupported_media", "附件声明格式与真实格式不符。")
        except httpx.HTTPError as error:
            # Do not return/log exception text: it may contain a signed URL.
            raise MediaError("media_unavailable", "附件下载失败，请重新选择附件后重试。", 502) from error
        stream.seek(0)
        yield stream, filename


def stage_chat_file(session, settings, actor, prepared):
    stream, filename = prepared
    return staged(service.upload(session, settings, stream, filename, actor))
