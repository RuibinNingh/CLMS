"""Immutable, private storage. Keys are generated here, never from upload names."""
import os
import re
from pathlib import Path, PurePosixPath


class MediaError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details=None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details


def private_root(settings) -> Path:
    root = Path(settings.data_dir).absolute() / "media"
    # Reject a symlink in any component, including configured parents.
    for component in (root, *root.parents):
        if component.is_symlink():
            raise MediaError("media_unavailable", "文件存储目录不能使用符号链接。", 500)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def safe_path(settings, key: str, *, must_exist=True) -> Path:
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", key):
        raise MediaError("media_unavailable", "文件引用无效。", 404)
    parts = PurePosixPath(key).parts
    if not parts or key.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise MediaError("media_unavailable", "文件引用无效。", 404)
    root = private_root(settings)
    path = root.joinpath(*parts)
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            raise MediaError("media_unavailable", "文件引用不能使用符号链接。", 404)
    if not path.resolve().is_relative_to(root.resolve()):
        raise MediaError("media_unavailable", "文件引用超出存储范围。", 404)
    if must_exist and (not path.is_file() or path.is_symlink()):
        raise MediaError("media_unavailable", "文件不可用。", 404)
    return path


def read_bytes(settings, key: str) -> bytes:
    path = safe_path(settings, key)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            return stream.read()
    except OSError as exc:
        raise MediaError("media_unavailable", "文件不可用。", 404) from exc


def validate_name(filename: str) -> str:
    if not filename or len(filename) > 255 or "/" in filename or "\\" in filename:
        raise MediaError("validation_error", "请使用不含路径的文件名。")
    if filename in (".", "..") or any(ord(c) < 32 for c in filename):
        raise MediaError("validation_error", "文件名无效。")
    return filename
