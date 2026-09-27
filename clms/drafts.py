"""录入草稿（对标 OMRS 收件箱：暂存层，不进 Ledger，入库时才一次性写 entry.commit）。

存储：<vault>/语文/.clms/drafts/<id>.json，图片按内容哈希存 images/<sha>.<ext>（重复上传自动合并）。
状态：queued → extracting → ready ⇄ thinking；出错为 error（可重试）；终态 committed / discarded。
每次 AI 修订或手工编辑都追加一个 revision（保留最近 40 版），对话里的每条改动都能「回到修改前」。
AI 调用在后台线程里跑，并发数受 config.ai_concurrency 限制；前端轮询草稿状态。

Agent 模式（config.ai_agent，默认开）：对话直连 agent.py 的 harness。一次 run 只占一版 revision（工具每改一次就
原地更新这一版，前端能看到实时进度）；对话里一条 AI 消息 = run 的一段（segment），带 steps（模型说的话、每次工具调用、
子代理进度）。run 进行中用户再发话会进 agent.inbox，由 harness 在下一轮前读到（插话）；「停止」让 run 作废，
之后它的任何写入都被丢弃。模型的完整上下文（含工具调用）存在 agent.messages，图片只存引用。
草稿的 kind：extract（上传试卷）、manual（手动录入）、chat（空白对话，可查改题库、记复习反馈）、review（复习批改）。
"""

import datetime
import hashlib
import json
import os
import re
import threading
import uuid

from . import agent as agent_mod
from . import ai_assist, creation
from .common import load_config, now_iso, sub_dir
from .harness import Aborted
from .draft_schema import diff, issues, normalize_groups

BUSY = ("queued", "extracting", "thinking")
MAX_REVISIONS = 40
IMAGE_ID_RE = re.compile(r"^[0-9a-f]{24}\.(png|jpg|gif|webp)$")
_lock = threading.RLock()
_sems = {}
_aborts = {}              # draft_id → 当前 run 的停止信号
TRANSCRIPT_KEEP = 160     # agent.messages 最多保留几条（从一条用户消息处截断，不拆开工具调用）


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


# ── 存取 ────────────────────────────────────────────────

def _path(vault, draft_id):
    if not re.match(r"^D-[\w-]+$", draft_id or ""):
        raise DraftError("草稿编号无效")
    return os.path.join(sub_dir(vault, "drafts"), draft_id + ".json")


def load(vault: str, draft_id: str) -> dict:
    try:
        with _lock:
            with open(_path(vault, draft_id), "r", encoding="utf-8") as fh:
                return json.load(fh)
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


def _add_revision(draft, groups, source):
    n = (draft["revisions"][-1]["n"] + 1) if draft["revisions"] else 1
    draft["revisions"].append({"n": n, "at": now_iso(), "source": source, "groups": groups})
    draft["revisions"] = draft["revisions"][-MAX_REVISIONS:]
    return n


def _msg(draft, role, text, **extra):
    draft["messages"].append(dict({"role": role, "text": text, "at": now_iso()}, **extra))


def title_of(groups, draft=None) -> str:
    if draft is not None and not groups:
        if draft.get("kind") == "review":
            return f"批改 {draft.get('session_id') or ''}".strip()
        if draft.get("kind") == "chat":
            first = next((m.get("text") for m in draft.get("messages", []) if m["role"] == "user" and m.get("text")), "")
            return "对话" + (f" · {first[:12]}" if first else "")
    names = []
    for group in groups:
        title = group["material"].get("title")
        names.append(f"《{title}》" if title else {"dictation": "名句默写"}.get(group["genre"], "未命名材料"))
    return "、".join(names[:3]) + ("等" if len(names) > 3 else "")


def agent_mode(vault: str) -> bool:
    return bool(load_config(vault).get("ai_agent", True))


def create(vault: str, image_ids: list, hint: str = "", manual_genre: str = "", kind: str = "",
           session_id: str = "") -> dict:
    kind = kind or ("manual" if manual_genre else "extract")
    if kind in ("chat", "review") and not agent_mode(vault):
        raise DraftError("对话和 AI 批改需要 Agent 模式：到「设置」打开")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    idle = kind in ("manual", "chat")
    draft = {"id": f"D-{stamp}-{uuid.uuid4().hex[:4]}", "created_at": now_iso(), "updated_at": now_iso(),
             "status": "ready" if idle else "queued", "images": list(image_ids), "hint": hint, "kind": kind,
             "session_id": session_id, "messages": [], "revisions": [], "error": "", "committed": None,
             "last_job": None, "agent": {"messages": [], "run": 0, "inbox": [], "token": None}}
    if image_ids:
        _msg(draft, "user", hint, images=list(image_ids))
    if manual_genre:
        _add_revision(draft, normalize_groups([{"genre": manual_genre, "items": [{}], "dictation": [
            {"template": "", "blanks": {}}]}]), "manual")
        _msg(draft, "edit", "新建空白草稿，直接在右侧填写", changes=[])
    with _lock:
        save(vault, draft)
    if kind == "extract":
        _start(vault, draft["id"], {"type": "extract"})
    elif kind == "review":
        _start(vault, draft["id"], {"type": "review", "session_id": session_id, "hint": hint})
    return draft


def list_drafts(vault: str) -> list:
    out = []
    folder = sub_dir(vault, "drafts")
    with _lock:
        for name in os.listdir(folder):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, name), "r", encoding="utf-8") as fh:
                    draft = json.load(fh)
            except (OSError, ValueError):
                continue
            if draft.get("status") == "discarded":
                continue
            groups = current_groups(draft)
            out.append({"id": draft["id"], "status": draft["status"], "created_at": draft["created_at"],
                        "updated_at": draft["updated_at"], "images": draft["images"], "title": title_of(groups, draft),
                        "kind": draft.get("kind", "extract"),
                        "genres": [g["genre"] for g in groups], "error": draft.get("error", ""),
                        "committed": draft.get("committed")})
    out.sort(key=lambda d: d["created_at"], reverse=True)
    active = [d for d in out if d["status"] != "committed"]
    done = [d for d in out if d["status"] == "committed"][:12]
    return active + done


def view(vault: str, draft_id: str) -> dict:
    draft = load(vault, draft_id)
    groups = current_groups(draft)
    return {"id": draft["id"], "status": draft["status"], "created_at": draft["created_at"],
            "updated_at": draft["updated_at"], "images": draft["images"], "hint": draft.get("hint", ""),
            "messages": draft["messages"], "error": draft.get("error", ""), "committed": draft.get("committed"),
            "revision": draft["revisions"][-1]["n"] if draft["revisions"] else 0,
            "revisions": [{"n": r["n"], "at": r["at"], "source": r["source"]} for r in draft["revisions"]],
            "groups": groups, "title": title_of(groups, draft), "issues": issues(groups),
            "dedupe": creation.annotate(vault, groups) if groups else None,
            "activity": draft.get("activity"), "kind": draft.get("kind", "extract"),
            "session_id": draft.get("session_id", ""), "agent": agent_mode(vault),
            "queued": len((draft.get("agent") or {}).get("inbox") or []),
            "can_retry": draft["status"] == "error" and bool(draft.get("last_job"))}


# ── 后台任务 ────────────────────────────────────────────

def _sem(vault):
    """并发上限跟随配置：改了 ai_concurrency 后，新任务用新的信号量，正在跑的任务照旧释放旧的。"""
    limit = max(1, min(6, int(load_config(vault).get("ai_concurrency") or 2)))
    with _lock:
        if vault not in _sems or _sems[vault][0] != limit:
            _sems[vault] = (limit, threading.BoundedSemaphore(limit))
        return _sems[vault][1]


def _start(vault, draft_id, job):
    with _lock:
        draft = load(vault, draft_id)
        draft["last_job"], draft["error"] = job, ""
        draft["status"] = "queued"
        draft["activity"] = {"started_at": now_iso(), "finished_at": None, "steps": [
            {"id": "queue", "label": "等待处理位", "kind": "queue", "status": "running", "at": now_iso()}]}
        token = uuid.uuid4().hex[:10]
        state = draft.setdefault("agent", {"messages": [], "run": 0, "inbox": [], "token": None})
        state["token"] = token
        abort = _aborts[draft_id] = threading.Event()
        save(vault, draft)
    threading.Thread(target=_run, args=(vault, draft_id, job, token, abort), daemon=True).start()


def _activity_step(vault, draft_id, step_id, label, kind, token=None):
    with _lock:
        draft = load(vault, draft_id)
        if token and not _alive(draft, token):
            raise Aborted()
        steps = draft["activity"]["steps"]
        if steps[-1]["status"] == "running":
            steps[-1]["status"], steps[-1]["ended_at"] = "done", now_iso()
        steps.append({"id": step_id, "label": label, "kind": kind, "status": "running", "at": now_iso()})
        save(vault, draft)


def _finish_activity(draft, status):
    activity = draft.get("activity")
    if not activity:
        return
    steps = activity["steps"]
    if steps and steps[-1]["status"] == "running":
        steps[-1]["status"], steps[-1]["ended_at"] = status, now_iso()
    activity["finished_at"] = now_iso()


def _alive(draft, token) -> bool:
    return (draft.get("agent") or {}).get("token") == token


def _run(vault, draft_id, job, token=None, abort=None):
    with _sem(vault):
        with _lock:
            draft = load(vault, draft_id)
            if token and not _alive(draft, token):
                return                          # 排队期间被停止了
            draft["status"] = "extracting" if job["type"] == "extract" else "thinking"
            save(vault, draft)
        if agent_mode(vault):
            _run_agent(vault, draft_id, job, token, abort)
        else:
            _run_legacy(vault, draft_id, job)


def _run_legacy(vault, draft_id, job):
    try:
        draft = load(vault, draft_id)
        report = lambda step_id, label, kind: _activity_step(vault, draft_id, step_id, label, kind)  # noqa: E731
        if job["type"] == "extract":
            paths = [image_path(vault, i) for i in draft["images"]]
            result = ai_assist.extract(vault, paths, draft.get("hint", ""), progress=report)
            report("save", "保存草稿", "local")
            with _lock:
                draft = load(vault, draft_id)
                n = _add_revision(draft, result["groups"], "ai")
                summary = _extract_summary(result["groups"])
                _msg(draft, "ai", summary, notes=result["notes"], revision=n, changes=[], kind="extract")
                draft["status"] = "ready"
                _finish_activity(draft, "done")
                save(vault, draft)
        elif job["type"] == "revise":
            report("context", "整理修改要求", "local")
            before = current_groups(draft)
            paths = [image_path(vault, i) for i in draft["images"]] if job.get("with_image") else []
            history = []
            for m in draft["messages"][:-1]:
                if m["role"] in ("user", "ai") and not m.get("error"):
                    history.append(m)
                elif m["role"] == "edit" and m.get("changes"):
                    labels = "、".join(c["label"] for c in m["changes"][:6])
                    history.append({"role": "user", "text": f"（我手动改了：{labels}）"})
            result = ai_assist.revise(vault, before, history, job["text"], paths, progress=report)
            report("save", "保存修订", "local")
            with _lock:
                draft = load(vault, draft_id)
                changes = diff(current_groups(draft), result["groups"])
                n = _add_revision(draft, result["groups"], "ai") if changes else draft["revisions"][-1]["n"]
                _msg(draft, "ai", result["reply"], changes=changes, revision=n,
                     base_revision=n - 1 if changes else None)
                draft["status"] = "ready"
                _finish_activity(draft, "done")
                save(vault, draft)
        else:
            raise DraftError("这类任务需要 Agent 模式：到「设置」打开")
    except Exception as exc:  # noqa: BLE001 - 任何失败都要落到草稿上，前端才能看到并重试
        with _lock:
            draft = load(vault, draft_id)
            draft["status"], draft["error"] = "error", str(exc)
            _msg(draft, "ai", str(exc), error=True)
            _finish_activity(draft, "error")
            save(vault, draft)


class _Host:
    """agent.run() 需要的宿主：把 harness 的事件、草稿改动、插话、入库落到草稿文件上；run 被停止后一律不写。"""

    def __init__(self, vault, draft_id, job, token, abort):
        self.vault, self.draft_id, self.token, self.abort = vault, draft_id, token, abort
        self.image_path = image_path
        with _lock:
            draft = load(vault, draft_id)
            if not _alive(draft, token):
                raise Aborted()                          # 刚要开始就被停止了：什么都不写
            state = draft["agent"]
            state["run"] = state.get("run", 0) + 1
            self.run_id = f"r{state['run']}"
            self.pages = list(draft["images"])
            self.groups = current_groups(draft)
            self.base_revision = draft["revisions"][-1]["n"] if draft["revisions"] else 0
            self.committed = bool(draft.get("committed"))
            self.transcript = list(state.get("messages") or [])
            self.rev_n = None
            self._segment(draft, job["type"])
            save(vault, draft)

    def _live(self):
        draft = load(self.vault, self.draft_id)
        return draft if _alive(draft, self.token) else None

    def _segment(self, draft, kind=None):
        seg = {"role": "ai", "text": "", "at": now_iso(), "run": self.run_id, "kind": kind or "chat",
               "status": "running", "steps": [], "changes": []}
        draft["messages"].append(seg)
        return seg

    @staticmethod
    def _current(draft, run_id):
        return next((m for m in reversed(draft["messages"]) if m["role"] == "ai" and m.get("run") == run_id), None)

    def flush(self, groups):
        with _lock:
            draft = self._live()
            if draft is None:
                return
            last = draft["revisions"][-1] if draft["revisions"] else None
            if self.rev_n is None or not last or last["n"] != self.rev_n:
                self.rev_n = _add_revision(draft, groups, "ai")
            else:
                last["groups"], last["at"] = groups, now_iso()
            save(self.vault, draft)

    def event(self, ev):
        with _lock:
            draft = self._live()
            if draft is None:
                return
            seg = self._current(draft, self.run_id)
            if seg is None:
                return
            kind = ev["type"]
            if ev.get("agent", "main") != "main":
                return
            if kind == "turn_start":
                seg["turn"] = ev["turn"]
            elif kind == "message_end":
                text = (ev["message"].get("content") or "").strip()
                if text and ev["message"].get("tool_calls"):
                    seg["steps"].append({"type": "say", "text": text[:600]})
                elif text:
                    seg["text"] = text
            elif kind == "tool_start":
                seg["steps"].append({"type": "tool", "id": ev["id"], "name": ev["name"], "label": ev.get("label", ""),
                                     "status": "running", "at": now_iso()})
            elif kind in ("tool_update", "tool_end"):
                step = next((x for x in seg["steps"] if x.get("id") == ev["id"]), None)
                if step is None:
                    return
                details = ev.get("details") or {}
                if details.get("tasks"):
                    step["tasks"] = details["tasks"]
                if kind == "tool_end":
                    step["status"] = "error" if ev.get("error") else "done"
                    step["summary"] = (ev.get("summary") or "")[:200]
                    step["ended_at"] = now_iso()
            else:
                return
            save(self.vault, draft)

    def steering(self):
        with _lock:
            draft = self._live()
            if draft is None or not draft["agent"].get("inbox"):
                return []
            inbox, draft["agent"]["inbox"] = draft["agent"]["inbox"], []
            seg = self._current(draft, self.run_id)
            if seg is not None:
                seg["status"] = "done"
            out = []
            for entry in inbox:
                msg = next((m for m in draft["messages"] if m.get("qid") == entry["qid"]), None)
                if msg is not None:                     # 插话挪到当前位置，后面接一段新的 AI 回复
                    draft["messages"].remove(msg)
                    msg.pop("queued", None)
                    draft["messages"].append(msg)
                out.append({"role": "user", "content": entry["text"] or "（见图）",
                            "images": [{"image": i} for i in entry.get("images") or []]})
            self._segment(draft)
            save(self.vault, draft)
            return out

    def commit(self, groups):
        with _lock:
            draft = self._live()
            if draft is None:
                raise Aborted()
            result = creation.commit_draft(self.vault, draft, groups)
            draft["committed"] = result
            text = f"已入库 {result['created']} 题" + (f"，{result['reencountered']} 题库里已有、记为又错一次"
                                                    if result["reencountered"] else "")
            _msg(draft, "system", text)
            self._segment(draft)
            save(self.vault, draft)
            self.committed = True
            return result

    def finish(self, result=None, error=None, stopped=False):
        with _lock:
            draft = self._live() if not stopped else load(self.vault, self.draft_id)
            if draft is None:
                return
            seg = self._current(draft, self.run_id)
            changes = diff(self.groups, current_groups(draft)) if self.rev_n else []
            if seg is not None:
                seg["status"] = "error" if error else ("stopped" if stopped else "done")
                for step in seg["steps"]:
                    if step.get("status") == "running":
                        step["status"] = "stopped" if stopped else "error"
                if error:
                    seg["text"], seg["error"] = str(error), True
                elif stopped:
                    seg["text"] = (seg["text"] + "\n" if seg["text"] else "") + "（已停止）"
                else:
                    seg["text"] = result["text"]
                    seg["turns"], seg["tool_calls"] = result["turns"], result["tool_calls"]
                if changes and self.base_revision:      # 第一次识别全是「新增」，不列芯片（与旧流程一致）
                    seg["changes"], seg["revision"], seg["base_revision"] = changes, self.rev_n, self.base_revision
            if result is not None:
                state = draft["agent"]
                kept = self.transcript[-TRANSCRIPT_KEEP:]
                while kept and not (kept[0]["role"] == "user" and not kept[0].get("synthetic")):
                    kept.pop(0)
                state["messages"] = kept
            draft["agent"]["token"] = None
            if error:
                draft["status"], draft["error"] = "error", str(error)
            elif draft.get("committed"):
                draft["status"] = "committed"
            elif stopped and not draft["revisions"] and draft.get("kind") == "extract":
                draft["status"], draft["error"] = "error", "已停止"
            else:
                draft["status"] = "ready"
            _finish_activity(draft, "error" if error else "done")
            follow = draft["agent"].get("inbox") if not (error or stopped) else None
            if follow:
                draft["agent"]["inbox"] = []
            save(self.vault, draft)
        if follow:                                     # run 刚好结束时到的插话：接着再跑一次
            with _lock:
                draft = load(self.vault, self.draft_id)
                for entry in follow:
                    msg = next((m for m in draft["messages"] if m.get("qid") == entry["qid"]), None)
                    if msg is not None:
                        msg.pop("queued", None)
                save(self.vault, draft)
            texts = [e["text"] for e in follow if e["text"]]
            _start(self.vault, self.draft_id, {"type": "revise", "text": "\n".join(texts) or "（见图）",
                                               "images": [i for e in follow for i in e.get("images") or []]})


def _edits_since_last_ai(draft) -> str:
    labels = []
    for m in reversed(draft["messages"]):
        if m["role"] == "ai":
            break
        if m["role"] == "edit" and m.get("changes"):
            labels += [c["label"] for c in m["changes"]]
    return "（我在草稿上手动改了：" + "、".join(labels[:8]) + "）\n" if labels else ""


def _run_agent(vault, draft_id, job, token, abort):
    host = None
    try:
        _activity_step(vault, draft_id, "agent", "Agent 执行", "model", token)
        if job["type"] == "revise":             # 先取手改说明：建 host 会追加这次 run 的 AI 消息
            job = dict(job, text=_edits_since_last_ai(load(vault, draft_id)) + job["text"])
        host = _Host(vault, draft_id, job, token, abort)
        result = agent_mod.run(vault, host, job)
        if abort is not None and abort.is_set():
            return
        host.finish(result)
    except Aborted:
        return                                          # abort() 已经把草稿收尾了
    except Exception as exc:  # noqa: BLE001 - 任何失败都要落到草稿上，前端才能看到并重试
        if abort is not None and abort.is_set():
            return
        if host is not None:
            host.finish(error=exc)
            return
        with _lock:
            draft = load(vault, draft_id)
            if _alive(draft, token):
                draft["status"], draft["error"] = "error", str(exc)
                _msg(draft, "ai", str(exc), error=True)
                _finish_activity(draft, "error")
                draft["agent"]["token"] = None
                save(vault, draft)
    finally:
        with _lock:
            if _aborts.get(draft_id) is abort:
                _aborts.pop(draft_id, None)


def abort(vault: str, draft_id: str) -> dict:
    """停止正在跑的 Agent：之后它的写入一律作废；已经做了的改动保留，可以「回到修改前」。"""
    with _lock:
        draft = load(vault, draft_id)
        if draft["status"] not in BUSY:
            raise DraftError("没有正在执行的任务")
        event = _aborts.get(draft_id)
        if event is not None:
            event.set()
        state = draft.setdefault("agent", {})
        for m in draft["messages"]:
            if m.get("queued"):
                m.pop("queued", None)
                m["dropped"] = True
        state["inbox"] = []
        seg = next((m for m in reversed(draft["messages"]) if m["role"] == "ai" and m.get("status") == "running"), None)
        if seg is not None:
            seg["status"] = "stopped"
            seg["text"] = (seg.get("text") + "\n" if seg.get("text") else "") + "（已停止）"
            for step in seg.get("steps", []):
                if step.get("status") == "running":
                    step["status"] = "stopped"
            if draft["revisions"] and seg.get("run"):
                n = draft["revisions"][-1]["n"]
                base = next((r for r in reversed(draft["revisions"]) if r["n"] < n), None)
                if draft["revisions"][-1]["source"] == "ai" and base is not None:
                    changes = diff(base["groups"], draft["revisions"][-1]["groups"])
                    if changes:
                        seg["changes"], seg["revision"], seg["base_revision"] = changes, n, base["n"]
        state["token"] = None
        if draft.get("committed"):
            draft["status"] = "committed"
        elif not draft["revisions"] and draft.get("kind", "extract") == "extract":
            draft["status"], draft["error"] = "error", "已停止，可以重试"
        else:
            draft["status"] = "ready"
        _finish_activity(draft, "error")
        save(vault, draft)
    return view(vault, draft_id)


def _extract_summary(groups) -> str:
    parts = []
    for group in groups:
        if group["genre"] == "dictation":
            blanks = sum(len(e["blanks"]) for e in group["dictation"])
            parts.append(f"名句默写 {len(group['dictation'])} 道（{blanks} 个空）")
        else:
            name = {"modern": "现代文", "classical": "文言文", "poetry": "古诗"}[group["genre"]]
            title = group["material"]["title"]
            parts.append(f"{name}{'《' + title + '》' if title else ''} {len(group['items'])} 道小题")
    return "识别到 " + "；".join(parts) + "。核对一下草稿，有要改的直接告诉我。"


def _editable(draft):
    if draft["status"] in BUSY:
        raise DraftError("AI 还在处理上一步，稍等一下")
    if draft["status"] in ("committed", "discarded"):
        raise DraftError("这份草稿已经入库或丢弃，不能再改")


def post_message(vault: str, draft_id: str, text: str, with_image: bool = True, images=None) -> dict:
    """发一条话。Agent 模式下：AI 正在执行就进插话队列；已入库的草稿也能继续聊（查改题库、记复习反馈）。"""
    text = (text or "").strip()
    image_ids = list(dict.fromkeys(images or []))
    if not text and not image_ids:
        raise DraftError("说点什么再发送")
    agent_on = agent_mode(vault)
    with _lock:
        draft = load(vault, draft_id)
        if not agent_on:
            _editable(draft)
            if not draft["revisions"]:
                raise DraftError("还没有识别结果，先重试识别")
            if image_ids:
                raise DraftError("附图发送需要 Agent 模式")
        elif draft["status"] == "discarded":
            raise DraftError("这份草稿已经丢弃")
        for image_id in image_ids:
            if image_id not in draft["images"]:
                draft["images"].append(image_id)
        if agent_on and draft["status"] in BUSY:
            qid = uuid.uuid4().hex[:8]
            draft.setdefault("agent", {}).setdefault("inbox", []).append({"qid": qid, "text": text, "images": image_ids})
            _msg(draft, "user", text, images=image_ids, queued=True, qid=qid)
            save(vault, draft)
            return view(vault, draft_id)
        _msg(draft, "user", text, **({"images": image_ids} if image_ids else {}))
        save(vault, draft)
    _start(vault, draft_id, {"type": "revise", "text": text or "（见图）", "images": image_ids,
                             "with_image": bool(with_image and draft["images"] and not image_ids)})
    return view(vault, draft_id)


def manual_edit(vault: str, draft_id: str, groups, base_revision: int) -> dict:
    with _lock:
        draft = load(vault, draft_id)
        _editable(draft)
        current = draft["revisions"][-1]["n"] if draft["revisions"] else 0
        if int(base_revision or 0) != current:
            raise DraftError("草稿已被 AI 更新，刷新后再改")
        new_groups = normalize_groups(groups)
        changes = diff(current_groups(draft), new_groups)
        if changes:
            n = _add_revision(draft, new_groups, "manual")
            last = draft["messages"][-1] if draft["messages"] else None
            if last and last["role"] == "edit" and last.get("changes") is not None and last.get("merge"):
                seen = {(c["gid"], c["iid"], c["field"]) for c in last["changes"]}
                last["changes"] += [c for c in changes if (c["gid"], c["iid"], c["field"]) not in seen]
                last["revision"], last["at"] = n, now_iso()
            else:
                _msg(draft, "edit", "手动修改", changes=changes, revision=n, base_revision=current, merge=True)
        save(vault, draft)
    return view(vault, draft_id)


def restore(vault: str, draft_id: str, revision: int) -> dict:
    with _lock:
        draft = load(vault, draft_id)
        _editable(draft)
        target = next((r for r in draft["revisions"] if r["n"] == int(revision)), None)
        if target is None:
            raise DraftError("这一版已经太旧，无法恢复")
        changes = diff(current_groups(draft), target["groups"])
        n = _add_revision(draft, target["groups"], "restore")
        _msg(draft, "edit", f"回到第 {target['n']} 版", changes=changes, revision=n, base_revision=n - 1)
        save(vault, draft)
    return view(vault, draft_id)


def retry(vault: str, draft_id: str) -> dict:
    draft = load(vault, draft_id)
    if draft["status"] != "error" or not draft.get("last_job"):
        raise DraftError("没有需要重试的任务")
    _start(vault, draft_id, draft["last_job"])
    return view(vault, draft_id)


def commit(vault: str, draft_id: str) -> dict:
    with _lock:
        draft = load(vault, draft_id)
        _editable(draft)
        result = creation.commit_draft(vault, draft, current_groups(draft))
        draft["status"], draft["committed"] = "committed", result
        text = f"已入库 {result['created']} 题"
        if result["reencountered"]:
            text += f"，{result['reencountered']} 题库里已有、记为又错一次"
        _msg(draft, "system", text)
        save(vault, draft)
    return view(vault, draft_id)


def discard(vault: str, draft_id: str) -> dict:
    with _lock:
        draft = load(vault, draft_id)
        if draft["status"] == "committed":
            raise DraftError("已入库的草稿不能丢弃")
        draft["status"] = "discarded"
        save(vault, draft)
    return {"id": draft_id, "status": "discarded"}


def recover(vault: str) -> int:
    """服务重启时把卡在处理中的草稿标成可重试的错误（Agent 的 run 一并作废）。"""
    count = 0
    folder = sub_dir(vault, "drafts")
    for name in os.listdir(folder):
        if name.endswith(".json"):
            with _lock:
                draft = load(vault, name[:-5])
                if draft["status"] in BUSY:
                    draft["status"], draft["error"] = "error", "服务重启，这一步中断了，点重试继续"
                    _finish_activity(draft, "error")
                    state = draft.setdefault("agent", {})
                    state["token"], state["inbox"] = None, []
                    for m in draft["messages"]:
                        if m.get("status") == "running":
                            m["status"] = "error"
                        if m.get("queued"):
                            m.pop("queued", None)
                            m["dropped"] = True
                    save(vault, draft)
                    count += 1
    return count
