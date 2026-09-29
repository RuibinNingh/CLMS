"""录入草稿（对标 OMRS 收件箱：暂存层，不进 Ledger，入库时才一次性写 entry.commit）。

存储：<vault>/语文/.clms/drafts/<id>.json，图片按内容哈希存 images/<sha>.<ext>（重复上传自动合并）。

流程（v0.3 起上传后不再直接执行）：
  staged（准备：排页序、旋转、删页、加页、写每页说明和补充说明）→「开始识别」→ queued → extracting → ready ⇄ thinking
  出错为 error（可重试）；终态 committed；discarded 是回收站（可恢复、可彻底删除）。
kind：extract（上传试卷）、manual（手动录入）、chat（空白对话）、review（复习作答照片，准备好后「开始批改」）。

对话 messages 是一串「块」（每块有 id）：user / thinking / assistant / tool / run（一次执行的收尾：改动、用时、状态）/
edit（手改）/ system（入库）/ ai（旧的一次性流程）。Agent 执行时块由 draft_runs.Host 写入，逐字的内容走 live.py，
读草稿时 live.overlay() 盖上进行中的文字。每次 AI 修订或手工编辑追加一个 revision（最近 40 版）。
后台执行（Agent / 旧流程）、插话、停止在 draft_runs.py。
"""

import base64
import datetime
import hashlib
import json
import os
import re
import threading
import uuid

from . import creation, live
from .common import load_config, now_iso, sub_dir
from .draft_schema import count_units, diff, issues, normalize_groups

BUSY = ("queued", "extracting", "thinking")
MAX_REVISIONS = 40
ROTATIONS = (0, 90, 180, 270)
IMAGE_ID_RE = re.compile(r"^[0-9a-f]{24}\.(png|jpg|gif|webp)$")
VIEWS = ("all", "active", "ready", "committed", "trash")
_lock = threading.RLock()


class DraftError(ValueError):
    pass


# ── 图片 ────────────────────────────────────────────────

def _sniff(data: bytes):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save_image(vault: str, data: bytes) -> str:
    ext = _sniff(data or b"")
    if not ext:
        raise DraftError("只支持 PNG / JPEG / GIF / WebP 图片")
    if len(data) > 25 * 1024 * 1024:
        raise DraftError("图片超过 25MB")
    image_id = hashlib.sha256(data).hexdigest()[:24] + "." + ext
    path = os.path.join(sub_dir(vault, "images"), image_id)
    if not os.path.exists(path):
        with open(path + ".tmp", "wb") as fh:
            fh.write(data)
        os.replace(path + ".tmp", path)
    return image_id


def image_path(vault: str, image_id: str) -> str:
    if not IMAGE_ID_RE.match(image_id or ""):
        raise DraftError("图片编号无效")
    return os.path.join(sub_dir(vault, "images"), image_id)


def receive_image(vault: str, image: dict) -> str:
    """接收图片字节或已经逐页上传的图片引用；引用必须确实存在。"""
    if not isinstance(image, dict):
        raise DraftError("图片参数无效")
    if image.get("image"):
        image_id = str(image["image"])
        if not os.path.isfile(image_path(vault, image_id)):
            raise DraftError("图片不存在，请重新上传")
        return image_id
    data = str(image.get("data") or "")
    data = data.split(",", 1)[1] if data.startswith("data:") else data
    return save_image(vault, base64.b64decode(data, validate=False))


# ── 存取 ────────────────────────────────────────────────

def _path(vault, draft_id):
    if not re.match(r"^D-[\w-]+$", draft_id or ""):
        raise DraftError("草稿编号无效")
    return os.path.join(sub_dir(vault, "drafts"), draft_id + ".json")


def _upgrade(draft: dict) -> dict:
    """旧草稿补字段：pages、消息 id。"""
    if "pages" not in draft:
        draft["pages"] = [{"image": i, "rotate": 0, "note": ""} for i in draft.get("images") or []]
    for index, page in enumerate(draft["pages"]):
        page.setdefault("id", f"legacy-{index}")
    for msg in draft.get("messages") or []:
        msg.setdefault("id", "m" + uuid.uuid4().hex[:10])
    draft.setdefault("agent", {"messages": [], "run": 0, "inbox": [], "token": None})
    return draft


def load(vault: str, draft_id: str) -> dict:
    try:
        with _lock:
            with open(_path(vault, draft_id), "r", encoding="utf-8") as fh:
                return _upgrade(json.load(fh))
    except FileNotFoundError:
        raise DraftError("草稿不存在：" + draft_id)


def save(vault: str, draft: dict):
    with _lock:
        draft["updated_at"] = now_iso()
        path = _path(vault, draft["id"])
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(draft, fh, ensure_ascii=False)
        os.replace(path + ".tmp", path)


def current_groups(draft: dict) -> list:
    return draft["revisions"][-1]["groups"] if draft.get("revisions") else []


def add_revision(draft, groups, source):
    n = (draft["revisions"][-1]["n"] + 1) if draft["revisions"] else 1
    draft["revisions"].append({"n": n, "at": now_iso(), "source": source, "groups": groups})
    draft["revisions"] = draft["revisions"][-MAX_REVISIONS:]
    return n


def new_block(draft, role, **fields) -> dict:
    block = dict({"id": "m" + uuid.uuid4().hex[:10], "role": role, "at": now_iso()}, **fields)
    draft["messages"].append(block)
    return block


def msg(draft, role, text, **extra) -> dict:
    return new_block(draft, role, text=text, **extra)


def publish_status(draft):
    live.publish(draft["id"], {"type": "status", "status": draft["status"],
                               "revision": draft["revisions"][-1]["n"] if draft["revisions"] else 0})


def title_of(groups, draft=None) -> str:
    if draft is not None and draft.get("name"):
        return draft["name"]
    if draft is not None and not groups:
        if draft.get("kind") == "review":
            return f"批改 {draft.get('session_id') or ''}".strip()
        if draft.get("kind") == "chat":
            first = next((m.get("text") for m in draft.get("messages", []) if m["role"] == "user" and m.get("text")), "")
            return "对话" + (f" · {first[:12]}" if first else "")
        if draft.get("status") == "staged":
            return f"待识别 · {len(draft.get('pages') or [])} 页"
    names = []
    for group in groups:
        title = group["material"].get("title")
        names.append(f"《{title}》" if title else {"dictation": "名句默写"}.get(group["genre"], "未命名材料"))
    return "、".join(names[:3]) + ("等" if len(names) > 3 else "")


def agent_mode(vault: str) -> bool:
    return bool(load_config(vault).get("ai_agent", True))


def _pages(image_ids, sources=None):
    """普通图片按内容合并；PDF 页面有独立身份，相同内容也保留页数。"""
    pages, seen = [], set()
    for index, image in enumerate(image_ids):
        source = (sources[index].get("source") or {}) if sources and index < len(sources) else {}
        if source:
            if not isinstance(source, dict):
                raise DraftError("PDF 页面来源无效")
            token = str(source.get("import_id") or "")
            number = int(source.get("page") or 0)
            if not re.fullmatch(r"[0-9a-f]{32}", token) or not 1 <= number <= 60:
                raise DraftError("PDF 页面来源无效")
            page = {"id": f"pdf-{token}-{number}", "image": image, "rotate": 0, "note": "",
                    "source": {"name": str(source.get("name") or "PDF")[:240], "page": number, "import_id": token}}
        else:
            if image in seen:
                continue
            page = {"id": uuid.uuid4().hex, "image": image, "rotate": 0, "note": ""}
        seen.add(image)
        pages.append(page)
    if len({p["id"] for p in pages}) != len(pages):
        raise DraftError("PDF 页面来源重复")
    return pages


def create(vault: str, image_ids: list, hint: str = "", manual_genre: str = "", kind: str = "",
           session_id: str = "", sources=None, upload_id: str = "") -> dict:
    """新建草稿。上传的图片只进入「准备」（staged），用户确认页序后才开始执行。"""
    kind = kind or ("manual" if manual_genre else "extract")
    if kind in ("chat", "review") and not agent_mode(vault):
        raise DraftError("对话和 AI 批改需要 Agent 模式：到「设置」打开")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if upload_id and not re.fullmatch(r"[0-9a-f]{32}", upload_id):
        raise DraftError("上传编号无效")
    pages = _pages(image_ids, sources)
    draft_id = f"D-upload-{upload_id}" if upload_id else f"D-{stamp}-{uuid.uuid4().hex[:4]}"
    draft = {"id": draft_id, "created_at": now_iso(), "updated_at": now_iso(),
             "status": "staged" if pages else "ready", "images": [p["image"] for p in pages], "pages": pages,
             "hint": hint, "kind": kind, "name": "", "session_id": session_id, "messages": [], "revisions": [],
             "error": "", "committed": None, "last_job": None,
             "agent": {"messages": [], "run": 0, "inbox": [], "token": None}}
    if manual_genre:
        add_revision(draft, normalize_groups([{"genre": manual_genre, "items": [{}], "dictation": [
            {"template": "", "blanks": {}}]}]), "manual")
        msg(draft, "edit", "新建空白草稿，直接在右侧填写", changes=[])
    with _lock:
        if upload_id and os.path.isfile(_path(vault, draft_id)):
            return load(vault, draft_id)
        save(vault, draft)
    return draft


# ── 准备阶段：页序、旋转、每页说明、加页 → 开始 ────────────────

def update_pages(vault: str, draft_id: str, pages=None, hint=None, add=None, sources=None) -> dict:
    with _lock:
        draft = load(vault, draft_id)
        if draft["status"] != "staged":
            raise DraftError("已经开始执行了，不能再调整页面")
        known = set(draft["images"]) | set(add or [])
        if pages is not None:
            clean = []
            originals = {p["id"]: p for p in draft["pages"]}
            for page in pages if isinstance(pages, list) else []:
                image = str((page or {}).get("image") or "")
                if image not in known:
                    raise DraftError("页面里有不属于这份草稿的图片")
                original = originals.get(page.get("id")) if page.get("id") else next(
                    (p for p in draft["pages"] if p["image"] == image and p["id"] not in {x["id"] for x in clean}), None)
                if page.get("id") and (not original or original["image"] != image):
                    raise DraftError("页面编号无效")
                rotate = int((page or {}).get("rotate") or 0) % 360
                clean.append({**(original or {"id": uuid.uuid4().hex}), "image": image,
                              "rotate": rotate if rotate in ROTATIONS else 0,
                              "note": str((page or {}).get("note") or "").strip()[:60]})
            if len({p["id"] for p in clean}) != len(clean):
                raise DraftError("页面编号重复")
            draft["pages"] = clean
        for page in _pages(add or [], sources):
            duplicate = page["id"] in {p["id"] for p in draft["pages"]} if page.get("source") else page["image"] in {p["image"] for p in draft["pages"]}
            if not duplicate:
                draft["pages"].append(page)
        draft["images"] = [p["image"] for p in draft["pages"]]
        if hint is not None:
            draft["hint"] = str(hint)[:500]
        save(vault, draft)
    return view(vault, draft_id)


def start(vault: str, draft_id: str, split: bool = False) -> list:
    """确认页面后开始执行。split=True 时每页一份草稿（各自识别）。返回开始执行的草稿编号。"""
    from . import draft_runs
    with _lock:
        draft = load(vault, draft_id)
        if draft["status"] != "staged":
            raise DraftError("这份草稿不在准备阶段")
        if not draft["pages"]:
            raise DraftError("至少要有一页")
        ids = [draft_id]
        if split and len(draft["pages"]) > 1 and draft.get("kind") == "extract":
            for page in draft["pages"][1:]:
                copy = create(vault, [], hint=draft.get("hint", ""), kind="extract")
                copy["pages"], copy["images"], copy["status"] = [page], [page["image"]], "staged"
                save(vault, copy)
                ids.append(copy["id"])
            draft["pages"], draft["images"] = draft["pages"][:1], draft["images"][:1]
            save(vault, draft)
    for one in ids:
        with _lock:
            d = load(vault, one)
            notes = "；".join(f"第 {n} 页：{p['note']}" for n, p in enumerate(d["pages"], 1) if p["note"])
            text = "\n".join(x for x in (d.get("hint", ""), notes) if x)
            msg(d, "user", text, images=list(d["images"]))
            d["status"] = "queued"
            save(vault, d)
        job = {"type": "review", "session_id": d.get("session_id"), "hint": d.get("hint", "")} \
            if d.get("kind") == "review" else {"type": "extract", "hint": d.get("hint", "")}
        draft_runs.start_job(vault, one, job)
    return ids


# ── 历史记录：列表 / 搜索 / 重命名 / 回收站 ─────────────────

def _bucket(draft) -> str:
    status = draft.get("status")
    if status == "discarded":
        return "trash"
    if status == "committed":
        return "committed"
    if status in BUSY or status in ("staged", "error"):
        return "active"
    return "ready"


def _row(draft) -> dict:
    groups = current_groups(draft)
    last = next((m for m in reversed(draft.get("messages") or [])
                 if m["role"] in ("user", "assistant", "ai", "system") and m.get("text")), None)
    return {"id": draft["id"], "status": draft["status"], "created_at": draft["created_at"],
            "updated_at": draft["updated_at"], "images": draft["images"][:1], "pages": len(draft.get("pages") or []),
            "title": title_of(groups, draft), "name": draft.get("name", ""), "kind": draft.get("kind", "extract"),
            "genres": [g["genre"] for g in groups], "units": count_units(groups), "error": draft.get("error", ""),
            "committed": draft.get("committed"), "bucket": _bucket(draft),
            "snippet": (last.get("text") or "")[:60] if last else ""}


def list_drafts(vault: str, view_name: str = "all", q: str = "", offset: int = 0, limit: int = 60) -> dict:
    rows = []
    folder = sub_dir(vault, "drafts")
    with _lock:
        for name in os.listdir(folder):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, name), "r", encoding="utf-8") as fh:
                    rows.append(_row(_upgrade(json.load(fh))))
            except (OSError, ValueError, KeyError):
                continue
    counts = {v: 0 for v in VIEWS}
    for row in rows:
        counts[row["bucket"]] += 1
        if row["bucket"] != "trash":
            counts["all"] += 1
    view_name = view_name if view_name in VIEWS else "all"
    needle = (q or "").strip().lower()
    picked = [r for r in rows if (r["bucket"] == view_name if view_name != "all" else r["bucket"] != "trash")
              and (not needle or needle in (r["title"] + " " + r["snippet"] + " " + r["id"]).lower())]
    picked.sort(key=lambda r: r["updated_at"], reverse=True)
    offset, limit = max(0, int(offset or 0)), max(1, min(200, int(limit or 60)))
    return {"drafts": picked[offset:offset + limit], "total": len(picked), "counts": counts}


def rename(vault: str, draft_id: str, name: str) -> dict:
    with _lock:
        draft = load(vault, draft_id)
        draft["name"] = str(name or "").strip()[:40]
        save(vault, draft)
    return view(vault, draft_id)


def discard(vault: str, draft_id: str) -> dict:
    """放进回收站（题库里已入库的题不受影响）。"""
    with _lock:
        draft = load(vault, draft_id)
        if draft["status"] in BUSY:
            raise DraftError("AI 还在执行，先停止再丢弃")
        if draft["status"] != "discarded":
            draft["discarded_from"], draft["status"] = draft["status"], "discarded"
            save(vault, draft)
    return {"id": draft_id, "status": "discarded"}


def undiscard(vault: str, draft_id: str) -> dict:
    with _lock:
        draft = load(vault, draft_id)
        if draft["status"] != "discarded":
            raise DraftError("这份草稿不在回收站里")
        draft["status"] = draft.pop("discarded_from", "") or ("ready" if draft["revisions"] else "staged")
        save(vault, draft)
    return view(vault, draft_id)


def delete_forever(vault: str, draft_id: str) -> dict:
    """彻底删除回收站里的草稿文件（原图按内容哈希共用，留在 images/ 里）。"""
    with _lock:
        draft = load(vault, draft_id)
        if draft["status"] != "discarded":
            raise DraftError("只能彻底删除回收站里的草稿")
        os.remove(_path(vault, draft_id))
    return {"id": draft_id, "deleted": True}


# ── 视图与编辑 ──────────────────────────────────────────

def view(vault: str, draft_id: str) -> dict:
    draft = load(vault, draft_id)
    groups = current_groups(draft)
    state = draft.get("agent") or {}
    return {"id": draft["id"], "status": draft["status"], "created_at": draft["created_at"],
            "updated_at": draft["updated_at"], "images": draft["images"], "pages": draft.get("pages", []),
            "hint": draft.get("hint", ""), "name": draft.get("name", ""),
            "messages": live.overlay(draft["id"], draft["messages"]), "live_seq": live.current(draft["id"]),
            "error": draft.get("error", ""), "committed": draft.get("committed"),
            "revision": draft["revisions"][-1]["n"] if draft["revisions"] else 0,
            "revisions": [{"n": r["n"], "at": r["at"], "source": r["source"]} for r in draft["revisions"]],
            "groups": groups, "title": title_of(groups, draft), "issues": issues(groups),
            "dedupe": creation.annotate(vault, groups) if groups else None,
            "activity": draft.get("activity"), "kind": draft.get("kind", "extract"),
            "session_id": draft.get("session_id", ""), "agent": agent_mode(vault),
            "running": state.get("running") if draft["status"] in BUSY else None,
            "stats": dict(state.get("stats") or {}, window=int(load_config(vault).get("ai_context_window") or 128000)),
            "queued": len(state.get("inbox") or []),
            "can_retry": draft["status"] == "error" and bool(draft.get("last_job"))}


def editable(draft):
    if draft["status"] in BUSY:
        raise DraftError("AI 还在处理上一步，稍等一下")
    if draft["status"] == "staged":
        raise DraftError("还在准备阶段，先开始识别")
    if draft["status"] in ("committed", "discarded"):
        raise DraftError("这份草稿已经入库或丢弃，不能再改")


def manual_edit(vault: str, draft_id: str, groups, base_revision: int) -> dict:
    with _lock:
        draft = load(vault, draft_id)
        editable(draft)
        current = draft["revisions"][-1]["n"] if draft["revisions"] else 0
        if int(base_revision or 0) != current:
            raise DraftError("草稿已被 AI 更新，刷新后再改")
        new_groups = normalize_groups(groups)
        changes = diff(current_groups(draft), new_groups)
        if changes:
            n = add_revision(draft, new_groups, "manual")
            last = draft["messages"][-1] if draft["messages"] else None
            if last and last["role"] == "edit" and last.get("changes") is not None and last.get("merge"):
                seen = {(c["gid"], c["iid"], c["field"]) for c in last["changes"]}
                last["changes"] += [c for c in changes if (c["gid"], c["iid"], c["field"]) not in seen]
                last["revision"], last["at"] = n, now_iso()
            else:
                msg(draft, "edit", "手动修改", changes=changes, revision=n, base_revision=current, merge=True)
        save(vault, draft)
    return view(vault, draft_id)


def restore(vault: str, draft_id: str, revision: int) -> dict:
    with _lock:
        draft = load(vault, draft_id)
        editable(draft)
        target = next((r for r in draft["revisions"] if r["n"] == int(revision)), None)
        if target is None:
            raise DraftError("这一版已经太旧，无法恢复")
        changes = diff(current_groups(draft), target["groups"])
        n = add_revision(draft, target["groups"], "restore")
        msg(draft, "edit", f"回到第 {target['n']} 版", changes=changes, revision=n, base_revision=n - 1)
        save(vault, draft)
    return view(vault, draft_id)


def commit(vault: str, draft_id: str) -> dict:
    with _lock:
        draft = load(vault, draft_id)
        editable(draft)
        result = creation.commit_draft(vault, draft, current_groups(draft))
        draft["status"], draft["committed"] = "committed", result
        text = f"已入库 {result['created']} 题"
        if result["reencountered"]:
            text += f"，{result['reencountered']} 题库里已有、记为又错一次"
        msg(draft, "system", text)
        save(vault, draft)
    return view(vault, draft_id)


# 执行相关的入口在 draft_runs；这里转一下，保持旧的调用方式可用
def post_message(vault, draft_id, text, with_image=True, images=None):
    from . import draft_runs
    return draft_runs.post_message(vault, draft_id, text, with_image, images)


def retry(vault, draft_id):
    from . import draft_runs
    return draft_runs.retry(vault, draft_id)


def abort(vault, draft_id):
    from . import draft_runs
    return draft_runs.abort(vault, draft_id)


def recover(vault):
    from . import draft_runs
    return draft_runs.recover(vault)
