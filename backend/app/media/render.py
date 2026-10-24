"""Validated image decoding and bounded rendering in isolated PDF worker processes."""
import json
import os
import subprocess
import sys
import threading
import warnings
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .storage import MediaError

_pdf_slots = {}
_pdf_slots_lock = threading.Lock()
_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_EXTENSIONS = {"image/jpeg": {".jpg", ".jpeg"}, "image/png": {".png"},
               "image/webp": {".webp"}, "application/pdf": {".pdf"}}


def sniff(data: bytes, filename: str) -> str:
    if data.startswith(b"%PDF-"):
        mime = "application/pdf"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise MediaError("unsupported_media", "只支持有效的 JPEG、PNG、WebP 和 PDF 文件。")
    if Path(filename).suffix.lower() not in _EXTENSIONS[mime]:
        raise MediaError("unsupported_media", "文件扩展名与真实格式不符。")
    return mime


def decode_image(data: bytes, max_pixels: int) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source = Image.open(BytesIO(data))
            if source.format not in _FORMATS or getattr(source, "n_frames", 1) != 1:
                raise MediaError("unsupported_media", "不支持动态或多帧图片。")
            if source.width * source.height > max_pixels:
                raise MediaError("media_limit_exceeded", "图片像素超出限制。")
            source.verify()
            source = Image.open(BytesIO(data))
            source.load()
            oriented = ImageOps.exif_transpose(source)
            if oriented.mode in ("RGBA", "LA") or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                image = Image.alpha_composite(background, rgba).convert("RGB")
                rgba.close()
                background.close()
            else:
                image = oriented.convert("RGB")
            oriented.close()
            source.close()
            return image
    except MediaError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise MediaError("media_limit_exceeded", "图片像素超出限制。") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise MediaError("unsupported_media", "图片损坏或无法解码。") from exc


def render_pdf(settings, source: Path, output: Path) -> list[dict]:
    timeout = getattr(settings, "pdf_render_timeout", 20)
    concurrency = getattr(settings, "pdf_render_concurrency", 2)
    with _pdf_slots_lock:
        slots = _pdf_slots.setdefault(concurrency, threading.BoundedSemaphore(concurrency))
    if not slots.acquire(timeout=timeout):
        raise MediaError("media_limit_exceeded", "PDF 渲染繁忙，请稍后重试。", 429)
    try:
        command = [sys.executable, "-m", "backend.app.media.pdf_worker", str(source), str(output),
                   str(settings.pdf_max_pages), str(settings.image_max_pixels),
                   str(getattr(settings, "media_high_edge", 4096)),
                   str(getattr(settings, "pdf_render_memory_mb", 512)), str(max(1, int(timeout)))]
        # Credentials and session secrets are not inherited by the parser process.
        environment = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(Path(__file__).parents[3]),
                       "LANG": "C.UTF-8"}
        try:
            result = subprocess.run(command, capture_output=True, timeout=timeout, env=environment,
                                    cwd=Path(__file__).parents[3], check=False)
        except subprocess.TimeoutExpired as exc:
            raise MediaError("media_limit_exceeded", "PDF 渲染超时。") from exc
        try:
            response = json.loads(result.stdout)
        except (ValueError, UnicodeDecodeError) as exc:
            raise MediaError("media_limit_exceeded", "PDF 渲染进程超出资源限制或异常退出。") from exc
        if result.returncode or "error" in response:
            code = response.get("error", "invalid_pdf")
            if "limit" in code:
                raise MediaError("media_limit_exceeded", "PDF 页数或页面像素超出限制。")
            raise MediaError("unsupported_media", "PDF 已加密、损坏或无法渲染。")
        return response["pages"]
    finally:
        slots.release()


def derived_image(data: bytes, *, rotation: int, edge: int, max_pixels: int, bbox=None):
    if rotation not in (0, 90, 180, 270):
        raise MediaError("validation_error", "旋转角度必须为 0、90、180 或 270。")
    image = decode_image(data, max_pixels)
    original_size = (image.width, image.height)
    if rotation:
        image = image.rotate(-rotation, expand=True)
    rotated_size = (image.width, image.height)
    crop = None
    if bbox is not None:
        if len(bbox) != 4 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in bbox):
            raise MediaError("validation_error", "区域须为 [x,y,width,height] 归一化坐标。")
        x, y, width, height = bbox
        if not (0 <= x < 1 and 0 <= y < 1 and width > 0 and height > 0
                and x + width <= 1 and y + height <= 1):
            raise MediaError("validation_error", "区域坐标超出页面范围。")
        crop = [x, y, width, height]
        left, top = int(x * image.width), int(y * image.height)
        right, bottom = round((x + width) * image.width), round((y + height) * image.height)
        if right <= left or bottom <= top:
            raise MediaError("validation_error", "区域过小。")
        image = image.crop((left, top, right, bottom))
    image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, "JPEG", quality=88)
    return output.getvalue(), {"image_width": image.width, "image_height": image.height,
                              "source_width": original_size[0], "source_height": original_size[1],
                              "rotated_width": rotated_size[0], "rotated_height": rotated_size[1],
                              "region": crop, "rotation": rotation, "mime": "image/jpeg"}
