"""既有领域 HTTP 适配：仅解析参数，调用共享业务函数。"""
import mimetypes
import json
import os
import time
import urllib.parse

from . import ai_assist, creation, draft_runs, drafts, library, live, printing, records, review_ai, sessions, taxonomy
from . import domain_ops
from .common import load_config, save_config
from .ledger import verify_ledger
from .taxonomy import taxonomy_payload
from .version import VERSION
from .http_registry import Raw, Stream, route

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


@route("POST", "/api/taxonomy/add")
def _taxonomy_add(vault, q, b):
    return taxonomy.add(vault, b.get("genre"), b.get("name"))


@route("POST", "/api/taxonomy/rename")
def _taxonomy_rename(vault, q, b):
    return taxonomy.rename(vault, b.get("genre"), b.get("old_name"), b.get("new_name"))


@route("POST", "/api/taxonomy/delete")
def _taxonomy_delete(vault, q, b):
    return taxonomy.delete(vault, b.get("genre"), b.get("name"), b.get("replace_with"))


@route("POST", "/api/taxonomy/reorder")
def _taxonomy_reorder(vault, q, b):
    return taxonomy.reorder(vault, b.get("genre"), b.get("names"))


@route("POST", "/api/taxonomy/kind")
def _taxonomy_kind(vault, q, b):
    return taxonomy.set_kind(vault, b.get("genre"), b.get("name"), b.get("kind"))


@route("GET", "/api/config")
def _config_get(vault, q, b):
    cfg = load_config(vault)
    cfg["ai_api_key_set"] = bool(cfg.pop("ai_api_key", ""))
    cfg["assistant_api_key_set"] = bool(cfg.pop("assistant_api_key", ""))
    return cfg


@route("POST", "/api/config")
def _config_post(vault, q, b):
    taxonomy.qtypes(vault)  # 写其它设置前先完成旧题型迁移
    patch = dict(b or {})
    patch.pop("qtypes", None)
    patch.pop("qtype_kinds", None)
    patch.pop("qtype_initialized", None)
    patch.pop("qtype_migration", None)
    for key, lo, hi in (("agent_subagents", 1, 6), ("agent_max_turns", 4, 80)):
        if key in patch:
            patch[key] = max(lo, min(hi, int(patch[key] or lo)))
    if "ai_agent" in patch:
        patch["ai_agent"] = bool(patch["ai_agent"])
    if not patch.get("ai_api_key"):
        patch.pop("ai_api_key", None)          # 留空 = 保留旧密钥
    if patch.pop("clear_api_key", False):
        patch["ai_api_key"] = ""
    if not patch.get("assistant_api_key"):
        patch.pop("assistant_api_key", None)
    if patch.pop("clear_assistant_api_key", False):
        patch["assistant_api_key"] = ""
    if "assistant_enabled" in patch:
        patch["assistant_enabled"] = bool(patch["assistant_enabled"])
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
    domain_ops.update_item(vault, b.get("id", ""), b.get("changes") or {})
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
    domain_ops.update_material(vault, b.get("id", ""), b.get("changes") or {})
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
    return domain_ops.create_session(vault, _ids(b.get("item_ids")), b.get("minutes", 0), b.get("title", ""))


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
