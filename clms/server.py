"""HTTP 服务（对标 OMRS server.py，吸取其两条技术债）：

1. ThreadingHTTPServer：AI 调用在后台线程，慢请求不再卡住整个界面；写入统一经 ledger 的写锁。
2. 路由表：每个端点一行登记（方法、路径、处理函数），不再是一长串 if 分支；AI/api.md 按这张表写。

默认只监听 127.0.0.1。写请求校验同源（Origin 与 Host 一致）。
"""

import base64
import email.utils
import http.server
import json
import mimetypes
import os
import re
import urllib.parse

from . import ai_assist, creation, drafts, library, printing, records, sessions
from .common import load_config, save_config
from .ledger import verify_ledger
from .taxonomy import taxonomy_payload
from .version import VERSION

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_BODY = 80 * 1024 * 1024
ROUTES = {}


class Raw:
    def __init__(self, body: bytes, content_type: str, headers=None):
        self.body, self.content_type, self.headers = body, content_type, headers or {}


def route(method, path):
    def deco(fn):
        ROUTES[(method, path)] = fn
        return fn
    return deco


def _ids(value):
    return [str(v) for v in value] if isinstance(value, list) else []


# ── 概览 / 配置 ─────────────────────────────────────────

@route("GET", "/api/summary")
def _summary(vault, q, b):
    data = sessions.summary(vault)
    data["ai_ready"] = ai_assist.ai_ready(vault)
    data["version"] = VERSION
    return data


@route("GET", "/api/taxonomy")
def _taxonomy(vault, q, b):
    return taxonomy_payload(vault)


@route("GET", "/api/config")
def _config_get(vault, q, b):
    cfg = load_config(vault)
    cfg["ai_api_key_set"] = bool(cfg.pop("ai_api_key", ""))
    return cfg


@route("POST", "/api/config")
def _config_post(vault, q, b):
    patch = dict(b or {})
    for key, lo, hi in (("agent_subagents", 1, 6), ("agent_max_turns", 4, 80)):
        if key in patch:
            patch[key] = max(lo, min(hi, int(patch[key] or lo)))
    if "ai_agent" in patch:
        patch["ai_agent"] = bool(patch["ai_agent"])
    if not patch.get("ai_api_key"):
        patch.pop("ai_api_key", None)          # 留空 = 保留旧密钥
    if patch.pop("clear_api_key", False):
        patch["ai_api_key"] = ""
    if "review_weekdays" in patch:
        patch["review_weekdays"] = sorted({int(d) for d in _ids(patch["review_weekdays"]) if d.isdigit() and int(d) < 7})
    save_config(vault, patch)
    return _config_get(vault, q, b)


@route("GET", "/api/activity")
def _activity(vault, q, b):
    return {"items": library.activity(vault, int(q.get("limit", 20)))}


@route("GET", "/api/ledger/verify")
def _verify(vault, q, b):
    return verify_ledger(vault)


@route("GET", "/api/source/export")
def _source_export(vault, q, b):
    """脱敏源码包（不依赖 Git），见 source_export.py。"""
    from .source_export import create_source_export
    data, filename, meta = create_source_export(vault)
    quoted = urllib.parse.quote(filename)
    return Raw(data, "application/zip", {"Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quoted}",
                                         "Cache-Control": "no-store", "X-Source-Files": str(meta["files"])})


# ── 录入草稿 ────────────────────────────────────────────

@route("GET", "/api/drafts")
def _drafts(vault, q, b):
    return {"drafts": drafts.list_drafts(vault), "ai_ready": ai_assist.ai_ready(vault)}


def _save_images(vault, images) -> list:
    ids = []
    for image in images or []:
        data = str(image.get("data") or "")
        data = data.split(",", 1)[1] if data.startswith("data:") else data
        try:
            ids.append(drafts.save_image(vault, base64.b64decode(data, validate=False)))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{image.get('name') or '图片'}：{exc}")
    return ids


@route("POST", "/api/drafts")
def _drafts_create(vault, q, b):
    """{images:[{name, data(dataURL)}], combine, hint} → 每张一份草稿，或合成一份；
    {manual: genre} 手动录入；{chat: true} 空白对话；{images, review_session} 复习作答照片交给 AI 批改。"""
    if b.get("manual"):
        return {"drafts": [drafts.view(vault, drafts.create(vault, [], manual_genre=b["manual"])["id"])]}
    if b.get("chat"):
        return {"drafts": [drafts.view(vault, drafts.create(vault, [], kind="chat")["id"])]}
    ids = _save_images(vault, b.get("images"))
    if not ids:
        raise ValueError("没有收到图片")
    if not ai_assist.ai_ready(vault):
        raise ValueError("还没有配置 AI：到「设置」填写 API 地址、Key 和模型；也可以先用「手动录入」")
    if b.get("review_session"):
        sessions.view(vault, str(b["review_session"]))          # 不存在就 404
        draft = drafts.create(vault, list(dict.fromkeys(ids)), hint=str(b.get("hint") or ""), kind="review",
                              session_id=str(b["review_session"]))
        return {"drafts": [drafts.view(vault, draft["id"])]}
    groups = [ids] if b.get("combine") else [[i] for i in dict.fromkeys(ids)]
    created = [drafts.create(vault, group, hint=str(b.get("hint") or "")) for group in groups]
    return {"drafts": [drafts.view(vault, d["id"]) for d in created]}


@route("GET", "/api/draft")
def _draft(vault, q, b):
    return drafts.view(vault, q.get("id", ""))


@route("POST", "/api/draft/message")
def _draft_message(vault, q, b):
    if b.get("images") and not ai_assist.ai_ready(vault):
        raise ValueError("还没有配置 AI")
    return drafts.post_message(vault, b.get("id", ""), b.get("text", ""), b.get("with_image", True),
                               _save_images(vault, b.get("images")))


@route("POST", "/api/draft/abort")
def _draft_abort(vault, q, b):
    return drafts.abort(vault, b.get("id", ""))


@route("POST", "/api/draft/edit")
def _draft_edit(vault, q, b):
    return drafts.manual_edit(vault, b.get("id", ""), b.get("groups"), b.get("revision", 0))


@route("POST", "/api/draft/restore")
def _draft_restore(vault, q, b):
    return drafts.restore(vault, b.get("id", ""), b.get("revision", 0))


@route("POST", "/api/draft/retry")
def _draft_retry(vault, q, b):
    return drafts.retry(vault, b.get("id", ""))


@route("POST", "/api/draft/commit")
def _draft_commit(vault, q, b):
    return drafts.commit(vault, b.get("id", ""))


@route("POST", "/api/draft/discard")
def _draft_discard(vault, q, b):
    return drafts.discard(vault, b.get("id", ""))


@route("GET", "/api/image")
def _image(vault, q, b):
    path = drafts.image_path(vault, q.get("id", ""))
    if not os.path.exists(path):
        raise KeyError("图片不存在")
    with open(path, "rb") as fh:
        return Raw(fh.read(), mimetypes.guess_type(path)[0] or "application/octet-stream",
                   {"Cache-Control": "private, max-age=604800, immutable"})


# ── 题库 ────────────────────────────────────────────────

@route("GET", "/api/items")
def _items(vault, q, b):
    return library.list_items(vault, q.get("genre", ""), q.get("qtype", ""), q.get("status", ""),
                              q.get("q", ""), q.get("sort", "priority"), q.get("suspended") == "1")


@route("GET", "/api/item")
def _item(vault, q, b):
    return library.item_detail(vault, q.get("id", ""))


@route("POST", "/api/item/update")
def _item_update(vault, q, b):
    creation.update_item(vault, b.get("id", ""), b.get("changes") or {})
    return library.item_detail(vault, b.get("id", ""))


@route("POST", "/api/item/suspend")
def _item_suspend(vault, q, b):
    library.set_suspended(vault, b.get("id", ""), b.get("suspended", True))
    return library.item_detail(vault, b.get("id", ""))


@route("POST", "/api/item/delete")
def _item_delete(vault, q, b):
    return library.delete(vault, b.get("id", ""))


@route("POST", "/api/item/restore")
def _item_restore(vault, q, b):
    library.restore(vault, b.get("id", ""))
    return library.item_detail(vault, b.get("id", ""))


@route("GET", "/api/records")
def _records(vault, q, b):
    return records.list_records(vault, q.get("item_id", ""), q.get("session_id", ""), q.get("voided", "1") == "1",
                                int(q.get("limit", 100)))


@route("POST", "/api/record/add")
def _record_add(vault, q, b):
    return records.add(vault, b.get("item_id", ""), b.get("grade"), b.get("note", ""), b.get("date", ""),
                       b.get("session_id", ""))


@route("POST", "/api/record/update")
def _record_update(vault, q, b):
    return records.update(vault, b.get("commit_id", ""), b.get("grade"), b.get("note"))


@route("POST", "/api/record/delete")
def _record_delete(vault, q, b):
    return records.delete(vault, b.get("commit_id", ""))


@route("POST", "/api/record/restore")
def _record_restore(vault, q, b):
    return records.restore(vault, b.get("commit_id", ""))


@route("GET", "/api/material")
def _material(vault, q, b):
    return library.material_detail(vault, q.get("id", ""))


@route("POST", "/api/material/update")
def _material_update(vault, q, b):
    creation.update_material(vault, b.get("id", ""), b.get("changes") or {})
    return library.material_detail(vault, b.get("id", ""))


# ── 复习 ────────────────────────────────────────────────

@route("POST", "/api/sessions/plan")
def _plan(vault, q, b):
    return sessions.plan(vault, b.get("minutes"), _ids(b.get("genres")), b.get("fill", True))


@route("GET", "/api/sessions")
def _sessions(vault, q, b):
    return {"sessions": sessions.list_sessions(vault)}


@route("POST", "/api/sessions")
def _sessions_create(vault, q, b):
    return sessions.create(vault, _ids(b.get("item_ids")), b.get("minutes", 0), b.get("title", ""))


@route("GET", "/api/session")
def _session(vault, q, b):
    return sessions.view(vault, q.get("id", ""))


@route("POST", "/api/session/grade")
def _grade(vault, q, b):
    return sessions.grade(vault, b.get("session_id", ""), b.get("item_id", ""), b.get("grade", 0), b.get("note", ""))


@route("POST", "/api/session/ungrade")
def _ungrade(vault, q, b):
    return sessions.void_grade(vault, b.get("session_id", ""), b.get("item_id", ""))


@route("POST", "/api/session/cancel")
def _cancel(vault, q, b):
    return sessions.cancel(vault, b.get("id", ""))


@route("GET", "/print/session")
def _print(vault, q, b):
    data = sessions.view(vault, q.get("id", ""))
    page = printing.render_session(data, with_answers=q.get("answers") == "1")
    return Raw(page.encode("utf-8"), "text/html; charset=utf-8")


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
            self.wfile.write(body)

    def _json(self, code, data):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8",
                   {"Cache-Control": "no-store"})

    def _dispatch(self, method):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        handler = ROUTES.get((method, path))
        if handler is None:
            if method == "GET":
                return self._static(path)
            return self._json(404, {"error": "not_found", "msg": "没有这个接口：" + path})
        body = {}
        if method == "POST":
            if not self._same_origin():
                return self._json(403, {"error": "origin", "msg": "拒绝跨站请求"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._json(413, {"error": "too_large", "msg": "请求太大（上限 80MB）"})
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
            except ValueError:
                return self._json(400, {"error": "bad_json", "msg": "请求体不是有效 JSON"})
        try:
            result = handler(self.vault, query, body if isinstance(body, dict) else {})
        except KeyError as exc:
            return self._json(404, {"error": "not_found", "msg": str(exc.args[0] if exc.args else exc)})
        except ValueError as exc:
            return self._json(400, {"error": "invalid", "msg": str(exc)})
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._json(500, {"error": "server", "msg": f"服务端出错：{exc}"})
        if isinstance(result, Raw):
            return self._send(200, result.body, result.content_type, result.headers)
        return self._json(200, result)

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


def make_server(vault: str, host: str = "127.0.0.1", port: int = 8472):
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("font/woff2", ".woff2")
    Handler.vault = vault
    server = http.server.ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
