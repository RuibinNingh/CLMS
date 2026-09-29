"""HTTP 服务（对标 OMRS server.py，吸取其两条技术债）：

1. ThreadingHTTPServer：AI 调用在后台线程，慢请求不再卡住整个界面；写入统一经 ledger 的写锁。
2. 路由表：每个端点一行登记（方法、路径、处理函数），不再是一长串 if 分支；AI/api.md 按这张表写。

默认只监听 127.0.0.1。写请求校验同源（Origin 与 Host 一致）。
"""

import email.utils
import http.server
import json
import mimetypes
import os
import re
import time
import urllib.parse

from . import ai_assist, creation, draft_runs, drafts, library, live, printing, records, review_ai, sessions
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


class Stream:
    """SSE：处理函数返回 Stream(生成器)，外壳逐段写出并 flush，客户端断开就停。"""

    def __init__(self, chunks):
        self.chunks = chunks


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
    """录入记录：view = all / active / ready / committed / trash，q 搜标题和最近一句话，分页 offset / limit。"""
    data = drafts.list_drafts(vault, q.get("view", "all"), q.get("q", ""), int(q.get("offset", 0)), int(q.get("limit", 60)))
    data["ai_ready"] = ai_assist.ai_ready(vault)
    return data


def _save_images(vault, images) -> list:
    ids = []
    for image in images or []:
        try:
            ids.append(drafts.receive_image(vault, image))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{image.get('name') if isinstance(image, dict) else '图片'}：{exc}")
    return ids


@route("POST", "/api/image")
def _image_upload(vault, q, b):
    """逐页保存图片，整份 PDF 拆完后再把引用一次性加入草稿。"""
    return {"image": _save_images(vault, [b])[0]}


@route("POST", "/api/drafts")
def _drafts_create(vault, q, b):
    """{images, hint} → 一份「准备中」的草稿（先确认页序再开始）；{manual: genre} 手动录入；{chat: true} 空白对话；
    {images, review_session} 复习作答照片，准备好后开始批改。"""
    if b.get("manual"):
        return {"drafts": [drafts.view(vault, drafts.create(vault, [], manual_genre=b["manual"])["id"])]}
    if b.get("chat"):
        return {"drafts": [drafts.view(vault, drafts.create(vault, [], kind="chat")["id"])]}
    ids = _save_images(vault, b.get("images"))
    if not ids:
        raise ValueError("没有收到图片")
    if b.get("review_session"):
        sessions.view(vault, str(b["review_session"]))          # 不存在就 404
        draft = drafts.create(vault, ids, hint=str(b.get("hint") or ""), kind="review",
                              session_id=str(b["review_session"]), sources=b.get("images"), upload_id=str(b.get("upload_id") or ""))
    else:
        draft = drafts.create(vault, ids, hint=str(b.get("hint") or ""), sources=b.get("images"), upload_id=str(b.get("upload_id") or ""))
    return {"drafts": [drafts.view(vault, draft["id"])]}


@route("POST", "/api/draft/pages")
def _draft_pages(vault, q, b):
    """准备阶段：{id, pages:[{image, rotate, note}], hint, add:[{name, data}]}。"""
    return drafts.update_pages(vault, b.get("id", ""), b.get("pages"), b.get("hint"), _save_images(vault, b.get("add")), b.get("add"))


@route("POST", "/api/draft/start")
def _draft_start(vault, q, b):
    if not ai_assist.ai_ready(vault):
        raise ValueError("还没有配置 AI：到「设置」填写 API 地址、Key 和模型；也可以先用「手动录入」")
    ids = drafts.start(vault, b.get("id", ""), bool(b.get("split")))
    return {"ids": ids, "draft": drafts.view(vault, ids[0])}


@route("POST", "/api/draft/rename")
def _draft_rename(vault, q, b):
    return drafts.rename(vault, b.get("id", ""), b.get("name", ""))


@route("POST", "/api/draft/undiscard")
def _draft_undiscard(vault, q, b):
    return drafts.undiscard(vault, b.get("id", ""))


@route("POST", "/api/draft/delete")
def _draft_delete(vault, q, b):
    return drafts.delete_forever(vault, b.get("id", ""))


@route("GET", "/api/draft/events")
def _draft_events(vault, q, b):
    """SSE：Agent 执行时的块与逐字内容。since 之后的事件；缓冲区不够时推 reload。每 15 秒一次心跳，5 分钟后让浏览器重连。"""
    draft_id = q.get("id", "")
    drafts.load(vault, draft_id)
    since = int(q.get("_last_event_id") or q.get("since") or 0)

    def chunks():
        nonlocal since
        yield "retry: 1500\n\n"
        deadline = time.time() + 300
        while time.time() < deadline:
            events = live.wait(draft_id, since, 15)
            if not events:
                yield ": ping\n\n"
                continue
            for event in events:
                since = max(since, event.get("seq", since))
                yield f"id: {since}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
    return Stream(chunks())


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
    return draft_runs.abort(vault, b.get("id", ""))


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
    """题库查询：筛选维度、分面计数、分页、按材料分组，见 library.list_items。"""
    return library.list_items(vault, q.get("genre", ""), q.get("qtype", ""), q.get("status", ""),
                              q.get("q", ""), q.get("sort", "priority"), q.get("suspended") == "1",
                              kind=q.get("kind", ""), added=q.get("added", ""), last=q.get("last", ""),
                              grade=q.get("grade", ""), material=q.get("material", ""),
                              offset=int(q.get("offset", 0) or 0), limit=int(q["limit"]) if q.get("limit") else None,
                              group=q.get("group", "item"))


@route("POST", "/api/items/batch")
def _items_batch(vault, q, b):
    """批量停用 / 恢复 / 删除：{ids, action: suspend|resume|delete}。逐题追加提交，返回成功数与失败原因。"""
    action = b.get("action")
    if action not in ("suspend", "resume", "delete"):
        raise ValueError("action 只能是 suspend / resume / delete")
    done, failed = 0, []
    for item_id in _ids(b.get("ids"))[:500]:
        try:
            if action == "delete":
                library.delete(vault, item_id)
            else:
                library.set_suspended(vault, item_id, action == "suspend")
            done += 1
        except (KeyError, ValueError) as exc:
            failed.append({"id": item_id, "msg": str(exc.args[0] if exc.args else exc)})
    return {"done": done, "failed": failed}


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
                                int(q.get("limit", 100)), genre=q.get("genre", ""), grade=q.get("grade", ""),
                                since=q.get("since", ""), has_note=q.get("has_note") == "1",
                                offset=int(q.get("offset", 0) or 0))


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
    return sessions.plan(vault, b.get("minutes"), _ids(b.get("genres")), b.get("fill", True),
                         qtypes=_ids(b.get("qtypes")), pinned=_ids(b.get("pinned")), exclude=_ids(b.get("exclude")))


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


@route("POST", "/api/review/ai")
def _review_ai(vault, q, b):
    """复习助手（流式）：{session_id, item_id, mode: ask|grade|feedback, text, images:[{name,data}],
    history:[{role, text, images:[编号]}], revealed}。校验在开始流式之前做完，错误照常回 400 / 404。"""
    return Stream(review_ai.stream(vault, review_ai.prepare(vault, b)))


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
        if self.headers.get("Last-Event-ID"):
            query["_last_event_id"] = self.headers.get("Last-Event-ID")
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
        if isinstance(result, Stream):
            return self._stream(result)
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


def make_server(vault: str, host: str = "127.0.0.1", port: int = 8472):
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("application/javascript", ".mjs")
    mimetypes.add_type("application/wasm", ".wasm")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("font/woff2", ".woff2")
    Handler.vault = vault
    server = http.server.ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
