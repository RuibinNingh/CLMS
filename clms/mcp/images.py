"""Version-bound original images, never arbitrary paths or outbound HTTP."""
import base64
import hashlib
import io
import os
import re
import stat

from ..common import DATA_DIRNAME, DATA_ROOT

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _mime(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("作文原图格式不支持")


def read_essay_image(vault, version_id, image_index=0):
    from .. import essays
    from ..ai_review import ReviewError
    version = essays.version_detail(vault, version_id)
    if type(image_index) is not int or not 0 <= image_index < len(version["images"]):
        raise ReviewError("not_found", "对应页的作文原图不存在", 404)
    image_id = version["images"][image_index]
    if not isinstance(image_id, str) or not re.fullmatch(r"[a-f0-9]{24}\.(?:jpg|jpeg|png|gif|webp)", image_id):
        raise ValueError("作文原图身份不合法")
    # Open directories and leaf by descriptor so a replaced or linked file cannot
    # redirect the read after validation. No absolute client path is accepted.
    directory = os.path.abspath(vault)
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        for part in (DATA_ROOT, DATA_DIRNAME, "images"):
            child = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=descriptor)
            os.close(descriptor); descriptor = child
        file_descriptor = os.open(image_id, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=descriptor)
        with os.fdopen(file_descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_IMAGE_BYTES:
                raise ValueError("作文原图超过限制或文件类型不合法")
            data = stream.read(MAX_IMAGE_BYTES + 1)
            after = os.fstat(stream.fileno())
            current = os.stat(image_id, dir_fd=descriptor, follow_symlinks=False)
            identities = lambda entry: (entry.st_dev, entry.st_ino, entry.st_size, entry.st_mtime_ns)
            if len(data) > MAX_IMAGE_BYTES or identities(before) != identities(after) or identities(after) != identities(current):
                raise ValueError("作文原图读取期间已经改变")
    except OSError:
        raise ReviewError("not_found", "作文原图不存在或无法安全读取", 404) from None
    finally:
        os.close(descriptor)
    mime = _mime(data)
    if hashlib.sha256(data).hexdigest()[:24] != image_id.split(".")[0]:
        raise ValueError("作文原图内容与图片身份不一致")
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image is not None:
        try:
            with Image.open(io.BytesIO(data)) as image:
                frames = getattr(image, "n_frames", 1)
                if frames > 100:
                    raise ValueError("作文原图像素或帧数超过限制")
                total_pixels = 0
                for frame in range(frames):
                    image.seek(frame); total_pixels += image.width * image.height
                    if total_pixels > 40_000_000:
                        raise ValueError("作文原图像素或帧数超过限制")
                    image.load()
        except (OSError, SyntaxError):
            raise ValueError("作文原图内容损坏") from None
    return {"version_id": version_id, "image_id": image_id, "image_index": image_index,
            "mime_type": mime, "data": base64.b64encode(data).decode("ascii")}
