"""导出脱敏源码包（对标 OMRS source_export.py）：给 AI 助手或别人看代码时用。

- 不依赖 Git：按源码目录和文件类型直接从当前工作区收集，包括未提交的改动。
- 只扫描项目根目录的几个文件和 AI/、assets/、clms/、deploy/、tests/；数据目录（<vault>/语文/.clms：
  Ledger、草稿、原图、config.json）即使放在项目目录里也不会被扫描到。
- 排除缓存、构建产物、隐藏文件、符号链接、日志、备份和之前导出的包。
- 脱敏：文本文件里出现的当前 API Key（config.json 的 ai_api_key）和形如 sk-… 的密钥串替换成 <已脱敏>，
  清单里记下哪些文件被替换过。
"""

import datetime
import io
import os
import re
import zipfile

from .common import load_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_FILES = {"AGENTS.md", "README.md", "clms.html", "clms_engine.py", "run.bat", "run.sh", ".gitignore"}
SOURCE_DIRS = {"AI", "assets", "clms", "deploy", "tests"}
SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".css", ".html", ".md", ".bat", ".sh", ".service", ".svg", ".woff2", ".txt"}
BINARY_SUFFIXES = {".woff2"}
EXCLUDED_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", "dist",
                 "语文", ".clms", "logs"}
EXCLUDED_NAMES = {"config.json", "ledger.db"}
SECRET_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")
REDACTED = "<已脱敏>"


def _is_source(relative: str) -> bool:
    parts = relative.split("/")
    name = parts[-1]
    if name in EXCLUDED_NAMES or name.startswith(("CLMS-source-", ".")) and name != ".gitignore":
        return False
    if name.endswith((".bak", ".log", ".tmp", ".pyc", ".db", ".zip")):
        return False
    if len(parts) == 1:
        return name in ROOT_FILES
    if parts[0] not in SOURCE_DIRS:
        return False
    suffix = os.path.splitext(name)[1].lower()
    if suffix == ".txt":                  # 只收字体许可证
        return relative.startswith("assets/vendor/fonts/") and name.endswith("-OFL.txt")
    return suffix in SOURCE_SUFFIXES


def source_files(root: str = ROOT):
    included, excluded = [], 0
    for name in sorted(ROOT_FILES):
        path = os.path.join(root, name)
        if os.path.isfile(path) and not os.path.islink(path):
            included.append(name)
    for top in sorted(SOURCE_DIRS):
        base = os.path.join(root, top)
        if not os.path.isdir(base) or os.path.islink(base):
            continue
        for current, dirs, files in os.walk(base, followlinks=False):
            keep = []
            for name in sorted(dirs):
                if name in EXCLUDED_DIRS or name.startswith(".") or os.path.islink(os.path.join(current, name)):
                    excluded += 1
                else:
                    keep.append(name)
            dirs[:] = keep
            for name in sorted(files):
                path = os.path.join(current, name)
                relative = os.path.relpath(path, root).replace(os.sep, "/")
                if not os.path.islink(path) and _is_source(relative):
                    included.append(relative)
                else:
                    excluded += 1
    return sorted(included), excluded


def _redact(text: str, secrets: list):
    count = 0
    for secret in secrets:
        if secret in text:
            count += text.count(secret)
            text = text.replace(secret, REDACTED)
    text, n = SECRET_RE.subn(REDACTED, text)
    return text, count + n


def create_source_export(vault: str, root: str = ROOT):
    """返回 (zip 字节, 文件名, 元信息)。"""
    included, excluded = source_files(root)
    if not included:
        raise ValueError("没有可导出的源码文件")
    key = str(load_config(vault).get("ai_api_key") or "").strip() if vault else ""
    secrets = [key] if len(key) >= 8 else []
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"CLMS-source-sanitized-{stamp}.zip"
    redacted = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in included:
            path = os.path.join(root, relative)
            if os.path.splitext(relative)[1].lower() in BINARY_SUFFIXES:
                archive.write(path, f"CLMS/{relative}")
                continue
            with open(path, "rb") as fh:
                data = fh.read()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                archive.writestr(f"CLMS/{relative}", data)
                continue
            text, hits = _redact(text, secrets)
            if hits:
                redacted.append(f"{relative}（{hits} 处）")
            archive.writestr(f"CLMS/{relative}", text)
        manifest = [
            "CLMS 脱敏源码包", "",
            "按源码目录和文件类型从当前工作区收集文件，包括未提交的改动；不依赖 Git。",
            "只扫描根目录项目文件及 AI/、assets/、clms/、deploy/、tests/；",
            "不含数据目录（语文/.clms：Ledger、草稿、原图、config.json）、缓存、隐藏文件、符号链接、日志和导出包。",
            "当前 API Key 与形如 sk-… 的密钥串已替换为 " + REDACTED + "。分享前仍请自行检查。", "",
            f"导出时间（UTC）：{stamp}", f"文件数量：{len(included)}", f"跳过的文件 / 目录：{excluded}",
            "脱敏替换：" + ("；".join(redacted) if redacted else "无"), "", "包含文件：", *included]
        archive.writestr("CLMS/SOURCE_EXPORT_MANIFEST.txt", "\n".join(manifest) + "\n")
    return buffer.getvalue(), filename, {"files": len(included), "excluded": excluded, "redacted": redacted}
