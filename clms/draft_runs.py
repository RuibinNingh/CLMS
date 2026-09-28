"""草稿的后台执行：Agent 模式（agent.py 的 harness）与旧的一次性识图 / 整份修订；插话、停止、重试、重启恢复。

Agent 的事件变成对话里的块（对标 Pi 交互界面的消息流）：
  thinking（模型的思考，逐字）→ assistant（它说的话，逐字）→ tool（每次工具调用：参数逐字生成 → 执行中 → 结果）
  → … → run（这次执行的收尾：状态、轮数、工具次数、用时、改动芯片、回到修改前）。
子代理的块挂在 delegate 那次工具调用下面（parent = 工具块 id，task = 第几个子代理）。
块的开始和结束写进草稿文件并推一条 block 事件；中间逐字的内容只进 live.py（内存）并推 delta 事件。
每次 run 有一个令牌；「停止」或服务重启让令牌作废，之后这次 run 的任何写入都被丢弃。
"""

import threading
import time
import uuid

from . import agent as agent_mod
from . import ai_assist, live
from .common import load_config, now_iso
from .draft_schema import diff
from .drafts import BUSY, DraftError, _lock, add_revision, current_groups, image_path, load, msg, new_block, \
    publish_status, save, view
from .harness import Aborted

TRANSCRIPT_KEEP = 160
RESULT_CHARS = 6000
_sems = {}
_aborts = {}


def _sem(vault):
    """并发上限跟随配置：改了 ai_concurrency 后，新任务用新的信号量，正在跑的任务照旧释放旧的。"""
    limit = max(1, min(6, int(load_config(vault).get("ai_concurrency") or 2)))
    with _lock:
        if vault not in _sems or _sems[vault][0] != limit:
            _sems[vault] = (limit, threading.BoundedSemaphore(limit))
        return _sems[vault][1]


def agent_mode(vault):
    return bool(load_config(vault).get("ai_agent", True))


def _alive(draft, token) -> bool:
    return (draft.get("agent") or {}).get("token") == token


def start_job(vault, draft_id, job):
    with _lock:
        draft = load(vault, draft_id)
        draft["last_job"], draft["error"], draft["status"] = job, "", "queued"
        draft["activity"] = {"started_at": now_iso(), "finished_at": None, "steps": [
            {"id": "queue", "label": "等待处理位", "kind": "queue", "status": "running", "at": now_iso()}]}
        token = uuid.uuid4().hex[:10]
        draft["agent"]["token"] = token
        abort_event = _aborts[draft_id] = threading.Event()
        save(vault, draft)
        publish_status(draft)
    threading.Thread(target=_run, args=(vault, draft_id, job, token, abort_event), daemon=True).start()


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


def _run(vault, draft_id, job, token, abort_event):
    with _sem(vault):
        with _lock:
            draft = load(vault, draft_id)
            if not _alive(draft, token):
                return                          # 排队期间被停止了
            draft["status"] = "extracting" if job["type"] == "extract" else "thinking"
            save(vault, draft)
            publish_status(draft)
        if agent_mode(vault):
            _run_agent(vault, draft_id, job, token, abort_event)
        else:
            _run_legacy(vault, draft_id, job)


# ── 旧流程（关掉 Agent 模式时）──────────────────────────────

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


def _run_legacy(vault, draft_id, job):
    try:
        draft = load(vault, draft_id)
        report = lambda step_id, label, kind: _activity_step(vault, draft_id, step_id, label, kind)  # noqa: E731
        if job["type"] == "extract":
            pages = draft["pages"]
            notes = "；".join(f"第 {n} 页：{p['note']}" for n, p in enumerate(pages, 1) if p.get("note"))
            hint = "\n".join(x for x in (draft.get("hint", ""), notes) if x)
            result = ai_assist.extract(vault, [image_path(vault, p["image"]) for p in pages], hint, progress=report,
                                       rotations=[p.get("rotate", 0) for p in pages])
            report("save", "保存草稿", "local")
            with _lock:
                draft = load(vault, draft_id)
                n = add_revision(draft, result["groups"], "ai")
                msg(draft, "ai", _extract_summary(result["groups"]), notes=result["notes"], revision=n, changes=[],
                    kind="extract")
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
                n = add_revision(draft, result["groups"], "ai") if changes else draft["revisions"][-1]["n"]
                msg(draft, "ai", result["reply"], changes=changes, revision=n, base_revision=n - 1 if changes else None)
                draft["status"] = "ready"
                _finish_activity(draft, "done")
                save(vault, draft)
        else:
            raise DraftError("这类任务需要 Agent 模式：到「设置」打开")
    except Exception as exc:  # noqa: BLE001 - 任何失败都要落到草稿上，前端才能看到并重试
        with _lock:
            draft = load(vault, draft_id)
            draft["status"], draft["error"] = "error", str(exc)
            msg(draft, "ai", str(exc), error=True)
            _finish_activity(draft, "error")
            save(vault, draft)
    with _lock:
        publish_status(load(vault, draft_id))


# ── Agent：事件 → 块 ────────────────────────────────────────

class Host:
    """agent.run() 的宿主。每个事件在锁内「读草稿 → 改块 → 存 → 推事件」；run 被停止后什么都不写。"""

    def __init__(self, vault, draft_id, job, token, abort_event):
        self.vault, self.draft_id, self.token, self.abort = vault, draft_id, token, abort_event
        self.image_path = image_path
        self.started = time.time()
        self.streams = {}
        with _lock:
            draft = load(vault, draft_id)
            if not _alive(draft, token):
                raise Aborted()                          # 刚要开始就被停止了：什么都不写
            state = draft["agent"]
            state["run"] = state.get("run", 0) + 1
            self.run_id, self.kind = f"r{state['run']}", job["type"]
            state["running"] = {"run": self.run_id, "kind": job["type"], "started_at": now_iso()}
            self.pages = [dict(p) for p in draft["pages"]]
            self.groups = current_groups(draft)
            self.base_revision = draft["revisions"][-1]["n"] if draft["revisions"] else 0
            self.committed = bool(draft.get("committed"))
            self.transcript = list(state.get("messages") or [])
            self.rev_n = None
            save(vault, draft)

    # 基础：在锁内改草稿并推送
    def _edit(self, fn):
        with _lock:
            draft = load(self.vault, self.draft_id)
            if not _alive(draft, self.token):
                return None
            touched = fn(draft) or []
            save(self.vault, draft)
            for block in live.overlay(self.draft_id, touched):
                live.publish(self.draft_id, {"type": "block", "block": block})
            return touched

    @staticmethod
    def _find(draft, bid):
        return next((m for m in draft["messages"] if m.get("id") == bid), None)

    def _stream(self, key):
        return self.streams.setdefault(key, {"thinking": None, "text": None, "calls": {}, "by_call": {}, "seen": set()})

    def _create(self, role, parent, task, **fields):
        extra = {"run": self.run_id, **({"parent": parent, "task": task} if parent else {})}
        holder = {}

        def fn(draft):
            holder["b"] = new_block(draft, role, **extra, **fields)
            return [holder["b"]]
        self._edit(fn)
        return holder.get("b", {}).get("id")

    def _close(self, st, which, final=None):
        bid = st[which]
        st[which] = None
        if not bid:
            return
        text = final if final is not None else live.live_text(self.draft_id, bid, "text")

        def fn(draft):
            block = self._find(draft, bid)
            if block is None:
                return []
            block.update(text=text, status="done", ended_at=now_iso())
            return [block]
        live.settle(self.draft_id, bid)
        self._edit(fn)

    def _update(self, bid, **fields):
        def fn(draft):
            block = self._find(draft, bid)
            if block is None:
                return []
            block.update(fields)
            return [block]
        if bid:
            self._edit(fn)

    def event(self, ev, key="main", parent=None, task=None):
        kind = ev["type"]
        if kind == "sub":
            parent_bid = self._stream(key)["by_call"].get(ev["parent"])
            return self.event(ev["event"], f"{ev['parent']}:{ev['task']}", parent_bid, ev["task"])
        st = self._stream(key)
        if kind == "message_start":
            st.update(thinking=None, text=None, calls={}, seen=set())
        elif kind == "delta" and ev["kind"] == "thinking":
            st["seen"].add("thinking")
            if not st["thinking"]:
                st["thinking"] = self._create("thinking", parent, task, text="", status="streaming")
            live.append(self.draft_id, st["thinking"], "text", ev["text"])
        elif kind == "delta":
            st["seen"].add("text")
            self._close(st, "thinking")
            if not st["text"]:
                st["text"] = self._create("assistant", parent, task, text="", status="streaming")
            live.append(self.draft_id, st["text"], "text", ev["text"])
        elif kind == "toolcall_delta":
            self._close(st, "thinking")
            self._close(st, "text")
            bid = st["calls"].get(ev["index"])
            if not bid:
                bid = st["calls"][ev["index"]] = self._create("tool", parent, task, name=ev["name"], label=ev["name"],
                                                              status="preparing", args_text="")
            live.append(self.draft_id, bid, "args_text", ev["delta"])
        elif kind == "message_end":
            self._end_message(st, ev["message"], parent, task)
            self._count(ev, sub=parent is not None)
        elif kind == "tool_start":
            self._update(st["by_call"].get(ev["id"]), status="running", label=ev.get("label", ""), args=ev.get("args"),
                         started_at=now_iso())
        elif kind == "tool_update":
            if (ev.get("details") or {}).get("tasks"):
                self._update(st["by_call"].get(ev["id"]), tasks=ev["details"]["tasks"])
        elif kind == "tool_end":
            fields = {"status": "error" if ev.get("error") else "done", "summary": (ev.get("summary") or "")[:200],
                      "result": (ev.get("content") or "")[:RESULT_CHARS], "ended_at": now_iso()}
            if (ev.get("details") or {}).get("tasks"):
                fields["tasks"] = ev["details"]["tasks"]
            self._update(st["by_call"].get(ev["id"]), **fields)
            self._count({}, tool=True)
        return None

    def _count(self, ev, sub=False, tool=False):
        """累计用量：主代理最近一次请求的输入 + 输出就是当前上下文；速度取最近一次有效的生成。"""
        usage, timing = ev.get("usage") or {}, ev.get("timing") or {}
        holder = {}

        def fn(draft):
            stats = draft["agent"].setdefault("stats", {})
            for key in ("turns", "sub_turns", "tool_calls", "input_total", "output_total", "context"):
                stats.setdefault(key, 0)
            if tool:
                stats["tool_calls"] += 1
            else:
                stats["sub_turns" if sub else "turns"] += 1
                stats["input_total"] += int(usage.get("input") or 0)
                stats["output_total"] += int(usage.get("output") or 0)
                if not sub:
                    stats["context"] = int(usage.get("input") or 0) + int(usage.get("output") or 0)
                if timing.get("tps"):
                    stats["tps"], stats["ttft"] = timing["tps"], timing.get("ttft", 0)
                stats["estimated"] = bool(usage.get("estimated"))
            holder["s"] = dict(stats)
            return []
        if self._edit(fn) is not None:
            live.publish(self.draft_id, {"type": "stats", "stats": with_window(self.vault, holder["s"])})

    def _end_message(self, st, message, parent, task):
        if st["thinking"]:
            self._close(st, "thinking", message.get("thinking") or None)
        elif message.get("thinking") and "thinking" not in st["seen"]:
            self._create("thinking", parent, task, text=message["thinking"], status="done")
        if st["text"]:
            self._close(st, "text", None)
        elif message.get("content") and "text" not in st["seen"]:
            self._create("assistant", parent, task, text=message["content"], status="done")
        for n, call in enumerate(message.get("tool_calls") or []):
            bid = st["calls"].get(n) or self._create("tool", parent, task, name=call["name"], label=call["name"],
                                                     status="pending", args_text="")
            live.settle(self.draft_id, bid)
            self._update(bid, call_id=call["id"], name=call["name"], args_text=call["arguments"], status="pending")
            st["by_call"][call["id"]] = bid

    # harness 需要的其它接口
    def flush(self, groups):
        with _lock:
            draft = load(self.vault, self.draft_id)
            if not _alive(draft, self.token):
                return
            last = draft["revisions"][-1] if draft["revisions"] else None
            if self.rev_n is None or not last or last["n"] != self.rev_n:
                self.rev_n = add_revision(draft, groups, "ai")
            else:
                last["groups"], last["at"] = groups, now_iso()
            save(self.vault, draft)
            publish_status(draft)

    def steering(self):
        out = []

        def fn(draft):
            inbox, draft["agent"]["inbox"] = draft["agent"].get("inbox") or [], []
            touched = []
            for entry in inbox:
                block = next((m for m in draft["messages"] if m.get("qid") == entry["qid"]), None)
                if block is not None:                    # 插话挪到当前位置
                    draft["messages"].remove(block)
                    block.pop("queued", None)
                    draft["messages"].append(block)
                    touched.append(block)
                out.append({"role": "user", "content": entry["text"] or "（见图）",
                            "images": [{"image": i} for i in entry.get("images") or []]})
            if touched:
                live.publish(self.draft_id, {"type": "reload"})
            return touched
        with _lock:
            draft = load(self.vault, self.draft_id)
            if not _alive(draft, self.token) or not draft["agent"].get("inbox"):
                return []
        self._edit(fn)
        return out

    def commit(self, groups):
        from . import creation
        holder = {}

        def fn(draft):
            result = creation.commit_draft(self.vault, draft, groups)
            draft["committed"], holder["r"] = result, result
            text = f"已入库 {result['created']} 题" + (f"，{result['reencountered']} 题库里已有、记为又错一次"
                                                    if result["reencountered"] else "")
            return [msg(draft, "system", text)]
        if self._edit(fn) is None:
            raise Aborted()
        self.committed = True
        return holder["r"]

    def finish(self, result=None, error=None):
        follow = []

        def fn(draft):
            touched = _close_open_blocks(draft, self.run_id, "error" if error else "done")
            changes = diff(self.groups, current_groups(draft)) if self.rev_n else []
            footer = {"run": self.run_id, "kind": self.kind, "status": "error" if error else "done",
                      "seconds": round(time.time() - self.started), "turns": (result or {}).get("turns", 0),
                      "tool_calls": (result or {}).get("tool_calls", 0)}
            if error:
                footer["text"] = str(error)
            if changes and self.base_revision:
                footer.update(changes=changes, revision=self.rev_n, base_revision=self.base_revision)
            touched.append(new_block(draft, "run", **footer))
            state = draft["agent"]
            if result is not None:
                kept = self.transcript[-TRANSCRIPT_KEEP:]
                while kept and not (kept[0]["role"] == "user" and not kept[0].get("synthetic")):
                    kept.pop(0)
                state["messages"] = kept
            state["token"], state["running"] = None, None
            if error:
                draft["status"], draft["error"] = "error", str(error)
            else:
                draft["status"] = "committed" if draft.get("committed") else "ready"
            _finish_activity(draft, "error" if error else "done")
            if not error:
                follow.extend(state.get("inbox") or [])
                state["inbox"] = []
                for entry in follow:
                    block = next((m for m in draft["messages"] if m.get("qid") == entry["qid"]), None)
                    if block is not None:
                        block.pop("queued", None)
            publish_status(draft)
            return touched
        self._edit(fn)
        if follow:                                     # run 刚好结束时到的插话：接着再跑一次
            texts = [e["text"] for e in follow if e["text"]]
            start_job(self.vault, self.draft_id, {"type": "revise", "text": "\n".join(texts) or "（见图）",
                                                  "images": [i for e in follow for i in e.get("images") or []]})


def with_window(vault, stats) -> dict:
    return dict(stats or {}, window=int(load_config(vault).get("ai_context_window") or 128000))


def _close_open_blocks(draft, run_id, status) -> list:
    """把这次 run 里还在进行的块收尾（停止 / 出错时）；进行中的逐字内容从内存写回文件。"""
    touched = []
    for block in draft["messages"]:
        if block.get("run") != run_id:
            continue
        if block.get("status") in ("streaming", "preparing", "pending", "running"):
            for field in ("text", "args_text"):
                text = live.live_text(draft["id"], block["id"], field)
                if text:
                    block[field] = text
            live.settle(draft["id"], block["id"])
            block["status"] = "done" if block["role"] in ("thinking", "assistant") else (
                "stopped" if status == "stopped" else "error")
            block["ended_at"] = now_iso()
            touched.append(block)
        for t in block.get("tasks") or []:
            if t.get("status") in ("queued", "running"):
                t["status"] = "stopped"
    return touched


def _edits_since_last_run(draft) -> str:
    labels = []
    for m in reversed(draft["messages"]):
        if m["role"] in ("run", "ai"):
            break
        if m["role"] == "edit" and m.get("changes"):
            labels += [c["label"] for c in m["changes"]]
    return "（我在草稿上手动改了：" + "、".join(labels[:8]) + "）\n" if labels else ""


def _run_agent(vault, draft_id, job, token, abort_event):
    host = None
    try:
        _activity_step(vault, draft_id, "agent", "Agent 执行", "model", token)
        if job["type"] == "revise":
            job = dict(job, text=_edits_since_last_run(load(vault, draft_id)) + job["text"])
        host = Host(vault, draft_id, job, token, abort_event)
        result = agent_mod.run(vault, host, job)
        if not abort_event.is_set():
            host.finish(result)
    except Aborted:
        return                                          # abort() 已经收尾
    except Exception as exc:  # noqa: BLE001 - 任何失败都要落到草稿上，前端才能看到并重试
        if abort_event.is_set():
            return
        if host is not None:
            host.finish(error=exc)
            return
        with _lock:
            draft = load(vault, draft_id)
            if _alive(draft, token):
                draft["status"], draft["error"] = "error", str(exc)
                new_block(draft, "run", run="", status="error", text=str(exc))
                _finish_activity(draft, "error")
                draft["agent"]["token"] = None
                save(vault, draft)
                publish_status(draft)
    finally:
        with _lock:
            if _aborts.get(draft_id) is abort_event:
                _aborts.pop(draft_id, None)


# ── 对外：发话 / 停止 / 重试 / 恢复 ─────────────────────────

def post_message(vault, draft_id, text, with_image=True, images=None) -> dict:
    """发一条话。Agent 模式下：AI 正在执行就进插话队列；已入库的草稿也能继续聊（查改题库、记复习反馈）。"""
    from .drafts import editable
    text = (text or "").strip()
    image_ids = list(dict.fromkeys(images or []))
    if not text and not image_ids:
        raise DraftError("说点什么再发送")
    agent_on = agent_mode(vault)
    with _lock:
        draft = load(vault, draft_id)
        if draft["status"] == "staged":
            raise DraftError("先确认页面、开始识别，再对话")
        if not agent_on:
            editable(draft)
            if not draft["revisions"]:
                raise DraftError("还没有识别结果，先重试识别")
            if image_ids:
                raise DraftError("附图发送需要 Agent 模式")
        elif draft["status"] == "discarded":
            raise DraftError("这份草稿在回收站里，先恢复")
        for image_id in image_ids:
            if image_id not in draft["images"]:
                draft["images"].append(image_id)
                draft["pages"].append({"image": image_id, "rotate": 0, "note": "对话附图"})
        if agent_on and draft["status"] in BUSY:
            qid = uuid.uuid4().hex[:8]
            draft["agent"].setdefault("inbox", []).append({"qid": qid, "text": text, "images": image_ids})
            block = msg(draft, "user", text, images=image_ids, queued=True, qid=qid)
            save(vault, draft)
            live.publish(draft_id, {"type": "block", "block": block})
            return view(vault, draft_id)
        block = msg(draft, "user", text, **({"images": image_ids} if image_ids else {}))
        save(vault, draft)
        live.publish(draft_id, {"type": "block", "block": block})
    start_job(vault, draft_id, {"type": "revise", "text": text or "（见图）", "images": image_ids,
                                "with_image": bool(with_image and draft["images"] and not image_ids)})
    return view(vault, draft_id)


def abort(vault, draft_id) -> dict:
    """停止正在跑的 Agent：之后它的写入一律作废；已经做了的改动保留，可以「回到修改前」。"""
    with _lock:
        draft = load(vault, draft_id)
        if draft["status"] not in BUSY:
            raise DraftError("没有正在执行的任务")
        event = _aborts.get(draft_id)
        if event is not None:
            event.set()
        state = draft["agent"]
        run = (state.get("running") or {}).get("run")
        for m in draft["messages"]:
            if m.get("queued"):
                m.pop("queued", None)
                m["dropped"] = True
        state["inbox"] = []
        if run:
            _close_open_blocks(draft, run, "stopped")
            footer = {"run": run, "status": "stopped", "kind": (state.get("running") or {}).get("kind", "")}
            last = draft["revisions"][-1] if draft["revisions"] else None
            base = next((r for r in reversed(draft["revisions"]) if last and r["n"] < last["n"]), None)
            if last and last["source"] == "ai" and base is not None and last["at"] >= state["running"]["started_at"]:
                changes = diff(base["groups"], last["groups"])
                if changes:
                    footer.update(changes=changes, revision=last["n"], base_revision=base["n"])
            new_block(draft, "run", **footer)
        state["token"], state["running"] = None, None
        if draft.get("committed"):
            draft["status"] = "committed"
        elif not draft["revisions"] and draft.get("kind", "extract") == "extract":
            draft["status"], draft["error"] = "error", "已停止，可以重试"
        else:
            draft["status"] = "ready"
        _finish_activity(draft, "error")
        save(vault, draft)
        live.publish(draft_id, {"type": "reload"})
        publish_status(draft)
    return view(vault, draft_id)


def retry(vault, draft_id) -> dict:
    draft = load(vault, draft_id)
    if draft["status"] != "error" or not draft.get("last_job"):
        raise DraftError("没有需要重试的任务")
    start_job(vault, draft_id, draft["last_job"])
    return view(vault, draft_id)


def recover(vault) -> int:
    """服务重启时把卡在处理中的草稿标成可重试的错误（Agent 的 run 一并作废）。"""
    import os
    from .common import sub_dir
    count = 0
    for name in os.listdir(sub_dir(vault, "drafts")):
        if not name.endswith(".json"):
            continue
        with _lock:
            draft = load(vault, name[:-5])
            if draft["status"] not in BUSY:
                continue
            draft["status"], draft["error"] = "error", "服务重启，这一步中断了，点重试继续"
            _finish_activity(draft, "error")
            state = draft["agent"]
            run = (state.get("running") or {}).get("run")
            if run:
                _close_open_blocks(draft, run, "error")
            state["token"], state["inbox"], state["running"] = None, [], None
            for m in draft["messages"]:
                if m.get("queued"):
                    m.pop("queued", None)
                    m["dropped"] = True
            save(vault, draft)
            count += 1
    return count
