"""HTTP 传输外壳；领域适配通过唯一注册表装配，默认仅监听本机。"""
import email.utils
import http.server
import json
import mimetypes
import os
import re
import time
import urllib.parse

from .version import VERSION
from .http_registry import ROUTES, Raw, Stream, AfterResponse
from .service import ServiceServer
from . import http_legacy
from . import essay_http, http_upgrade, mcp_http, http_assistant
from .http_registry import register_routes

register_routes(essay_http.ROUTES)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_BODY = 80 * 1024 * 1024

# ── HTTP 外壳 ───────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    vault = "."
    server_version = "CLMS/" + VERSION

    def log_message(self, fmt, *args):   # 安静：只在出错时打印
        pass

    def _send(self, code, body: bytes, content_type, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # 页面卸载会取消长轮询；结果已生成，无需重发或报服务故障。

    def _json(self, code, data):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8",
                   {"Cache-Control": "no-store"})

    def _dispatch(self, method):
        if self.headers.get("Authorization") or self.headers.get("X-CLMS-MCP-Key"):
            return self._json(403, {"error": "forbidden", "msg": "MCP 凭据只能用于独立 MCP 端口"})
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        handler = ROUTES.get((method, path))
        if handler is None:
            if method == "GET":
                return self._static(path)
            return self._json(404, {"error": "not_found", "msg": "没有这个接口：" + path})
        if self.headers.get("Last-Event-ID"):
            query["_last_event_id"] = self.headers.get("Last-Event-ID")
        body = {}
        if method == "POST":
            if not self._same_origin():
                return self._json(403, {"error": "origin", "msg": "拒绝跨站请求"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length < 0 or len(self.headers.get_all("Content-Length") or []) > 1:
                    raise ValueError()
            except ValueError:
                return self._json(400, {"error": "bad_length", "msg": "请求长度无效"})
            if length > MAX_BODY:
                return self._json(413, {"error": "too_large", "msg": "请求太大（上限 80MB）"})
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
            except ValueError:
                return self._json(400, {"error": "bad_json", "msg": "请求体不是有效 JSON"})
        try:
            context = self.server if getattr(handler, "needs_server", False) else self.vault
            result = handler(context, query, body if isinstance(body, dict) else {})
        except KeyError as exc:
            return self._json(404, {"error": "not_found", "msg": str(exc.args[0] if exc.args else exc)})
        except ValueError as exc:
            code = getattr(exc, "code", "invalid")
            status = 409 if code.endswith("conflict") else 403 if code == "forbidden" else 400
            return self._json(status, {"error": code, "msg": str(exc)})
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._json(500, {"error": "server", "msg": f"服务端出错：{exc}"})
        if isinstance(result, Raw):
            return self._send(200, result.body, result.content_type, result.headers)
        if isinstance(result, Stream):
            return self._stream(result)
        if isinstance(result, AfterResponse):
            try:
                self._json(200, result.data)
                self.wfile.flush()
            finally:
                result.callback()
            return None
        return self._json(200, result)

    def _stream(self, result):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for chunk in result.chunks:
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            close = getattr(result.chunks, "close", None)
            if close:
                close()                  # 让生成器的 finally 立即执行（复习助手据此停止模型）
        self.close_connection = True

    def _same_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urllib.parse.urlsplit(origin).netloc == self.headers.get("Host")

    def _static(self, path):
        if path in ("/", "/index.html"):
            path = "/clms.html"
        rel = os.path.normpath(urllib.parse.unquote(path).lstrip("/"))
        if rel != "clms.html" and not re.match(r"^assets[\\/]", rel):
            return self._json(404, {"error": "not_found", "msg": "没有这个页面"})
        full = os.path.join(ROOT, rel)
        if not full.startswith(ROOT + os.sep) or not os.path.isfile(full):
            return self._json(404, {"error": "not_found", "msg": "文件不存在"})
        stat = os.stat(full)
        etag = f'W/"{int(stat.st_mtime)}-{stat.st_size}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return None
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            body = fh.read()
        return self._send(200, body, ctype, {"ETag": etag, "Cache-Control": "no-cache",
                                             "Last-Modified": email.utils.formatdate(stat.st_mtime, usegmt=True)})

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


def make_server(vault: str, host: str = "127.0.0.1", port: int = 8472, *, restart_enabled=False):
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("application/javascript", ".mjs")
    mimetypes.add_type("application/wasm", ".wasm")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("font/woff2", ".woff2")
    handler = type("VaultHandler", (Handler,), {"vault": vault})
    return ServiceServer((host, port), handler, vault, restart_enabled)
