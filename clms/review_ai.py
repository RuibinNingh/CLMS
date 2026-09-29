"""复习助手：复习评分页右侧的 AI（v0.5 起；v0.6 改为只读 Agent，按需调用工具看题和原文）。

默认（设置里开着 Agent 模式）它是一个只读的小 Agent：上下文里只有一份很小的索引（这次复习、学生正在看哪道题），
题干、参考答案、原文、以前的复习都由模型调用 review_tools 里的工具按需获取——长文章可以只读几段，前几轮查过的
内容不再重发。学生在卷面上选中文字「引用」的内容直接附在他的话里。关掉 Agent 模式时退回旧做法：把这道题的全部上下文
并进第一条消息（context_text），不带工具。

三种模式：ask 随时提问；grade 对照采分点打分，最后一行 【建议】{"grade": n, "note": "…"}；
feedback 按当前评分写一条反馈，最后一行 【建议】{"note": "…"}。服务端把【建议】解析成 suggestion 交给前端；
评分和反馈由学生点「采用」后经 /api/session/grade、/api/record/update 写入——助手不写 Ledger（不变量 9）。

流式事件（两种做法一样）：start → block（开一个思考 / 正文 / 工具块）→ delta（逐字）→ end（思考 / 正文收尾）
→ tool（工具块状态、摘要、结果）→ … → done 或 error。学生发来的作答照片按内容哈希存进 images/，对话里只传编号。
"""

import base64
import json
import queue
import threading
import time
import uuid

from . import ai_assist, harness, review_tools
from .common import load_config, parse_date
from .drafts import image_path, save_image
from .projections import context, get_state
from .records import check_grade, grade_label
from .taxonomy import GENRE_BY_CODE

MODES = ("ask", "grade", "feedback")
MARK = "【建议】"
MAX_TEXT = 6000          # 旧做法：原文最多带多少字
MAX_TURNS = 16           # 最多带最近几轮对话
MAX_IMAGES = 4           # 最多带最近几张作答照片（全分辨率 1280 宽）
MAX_REFS = 6             # 一句话最多带几段引用
AGENT_TURNS = 8          # 只读 Agent 单次最多几轮（一轮 = 一次模型请求 + 执行它要的工具）

GRADES_HELP = "评分档：阅读题 0 不会（没思路 / 答偏）、1 部分（只答到少量要点）、2 基本（主要要点都有）、3 完整（要点齐全、表述到位）；" \
    "默写 0 不会、1 有错字、3 全对。"
RULES = """## 复习助手
你是学生的语文复习助手。学生刚在纸上做完一份复习卷，正在对答案、自评。你帮他对照参考答案分析作答、讲清楚这道题。
- 用中文，简洁，先结论后理由；讲阅读题时按采分点说。参考答案就是阅卷标准，不要另立标准。
- 学生的作答可能是打字，也可能是照片；看不清的地方直接说看不清，不要猜。
- """ + GRADES_HELP
TOOLS_HELP = """- 你看不到题目和原文，要用工具查：question_get 看题干、参考答案、解析和本次评分（不填就是学生正在看的这道）；material_read 读原文（长文章只读需要的段，或用 query 找含某个词句的段落）；item_history 查这道题以前的复习；review_outline 看整份卷子的题目清单。
- 只查回答需要的内容。前几轮查过的内容不会重发，需要时再查一次。学生引用的原文已经附在他的话里，可以直接用。"""

TASKS = {
    "grade": """## 这次的任务：打分
对照参考答案，逐个采分点判断学生的作答答到了哪些、漏了哪些（作答在对话里，文字或照片）。先简短说明，最后单独一行写：
{mark}{{"grade": 分值, "note": "反馈"}}
grade 只能取 {allowed}；note 用一两句话写错在哪、漏了哪个采分点、下次注意什么（40 字以内）。
如果对话里找不到学生的作答，就请他把作答发过来（打字或拍照），不要编造，也不要写{mark}。""",
    "feedback": """## 这次的任务：写复习反馈
学生这次的评分：{current}。根据对话里的作答和参考答案，写一条复习反馈：错在哪、漏了哪个采分点、下次注意什么（40 字以内）。
没有作答时，就按评分和这道题的难点写一条提醒。可以先简短说明，最后单独一行写：
{mark}{{"note": "反馈"}}""",
}
DEFAULT_TEXT = {"grade": "请对照参考答案给我的作答打分。", "feedback": "帮我写一条这次的复习反馈。"}
QUOTE_TEXT = "解释一下我引用的这段。"


class Stopped(Exception):
    """前端断开（点了停止或离开页面）：流式读取中立即抛出，连接随之关闭。"""


# ── 请求 ────────────────────────────────────────────────

def _refs(raw) -> list:
    out = []
    for ref in (raw or [])[:MAX_REFS]:
        ref = ref if isinstance(ref, dict) else {}
        text = " ".join(str(ref.get("text") or "").split())[:400]
        if not text:
            continue
        where = ref.get("where") if isinstance(ref.get("where"), dict) else {}
        out.append({"text": text, "label": str(ref.get("label") or "")[:60],
                    "where": {k: str(where[k])[:40] for k in ("material_id", "para", "n", "part") if where.get(k) not in (None, "")}})
    return out


def prepare(vault: str, body: dict) -> dict:
    """校验请求、存下新的作答照片，返回交给 run() 的任务。出错时抛 ValueError / KeyError（路由转成 400 / 404）。"""
    if not ai_assist.ai_ready(vault):
        raise ValueError("还没有配置 AI：到「设置」填写 API 地址、Key 和模型")
    state = get_state(vault)
    session_id, item_id = str(body.get("session_id") or ""), str(body.get("item_id") or "")
    sess = state.sessions.get(session_id)
    if not sess or sess["cancelled"]:
        raise KeyError("找不到这次复习：" + session_id)
    if item_id not in {e["id"] for e in sess["items"]}:
        raise ValueError("这道题不在这次复习里")
    mode = str(body.get("mode") or "ask")
    if mode not in MODES:
        raise ValueError("mode 只能是 ask / grade / feedback")
    text = str(body.get("text") or "").strip()[:4000]
    refs = _refs(body.get("refs"))
    new_images = []
    for image in (body.get("images") or [])[:6]:
        data = str((image or {}).get("data") or "")
        data = data.split(",", 1)[1] if data.startswith("data:") else data
        try:
            new_images.append(save_image(vault, base64.b64decode(data, validate=False)))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{(image or {}).get('name') or '图片'}：{exc}")
    if mode == "ask" and not text and not new_images and not refs:
        raise ValueError("先写下要问的问题")
    history = []
    for turn in (body.get("history") or [])[-MAX_TURNS:]:
        turn = turn if isinstance(turn, dict) else {}
        role = "assistant" if turn.get("role") == "assistant" else "user"
        images = [str(i) for i in (turn.get("images") or []) if isinstance(i, str)]
        for image_id in images:
            image_path(vault, image_id)                   # 编号不合法就拒绝
        history.append({"role": role, "text": str(turn.get("text") or "")[:4000], "images": images,
                        "refs": _refs(turn.get("refs")) if role == "user" else [],
                        "tools": [str(t)[:60] for t in (turn.get("tools") or [])[:10]] if role == "assistant" else []})
    revealed = body.get("revealed")
    revealed_ids = {str(x) for x in revealed} if isinstance(revealed, list) else ({item_id} if revealed else set())
    default = DEFAULT_TEXT.get(mode, "") or (QUOTE_TEXT if refs else "")
    return {"session_id": session_id, "item_id": item_id, "mode": mode, "text": text or default, "refs": refs,
            "images": new_images, "history": history, "revealed": item_id in revealed_ids, "revealed_ids": revealed_ids}


def said(vault: str, turn: dict) -> str:
    """学生一句话的正文：引用（带位置，材料段落写上编号方便模型再查）+ 他写的字。"""
    state = get_state(vault)
    parts = []
    for n, ref in enumerate(turn.get("refs") or [], 1):
        where, label = ref.get("where") or {}, ref.get("label") or "卷面"
        mat = state.materials.get(where.get("material_id") or "")
        if mat and where.get("para"):
            label = f"《{mat.get('title') or '无题'}》第 {where['para']} 段（{mat['id']}）"
        elif where.get("n"):
            label = f"第 {where['n']} 题" + {"stem": "的题干", "answer": "的参考答案"}.get(where.get("part"), "")
        parts.append(f"（引用 {n}：{label}）\n> {ref['text']}")
    if turn.get("text"):
        parts.append(turn["text"])
    return "\n".join(parts)


def _task_text(vault: str, job: dict) -> str:
    if job["mode"] == "ask":
        return ""
    state = get_state(vault)
    item = state.items[job["item_id"]]
    allowed = "0（不会）、1（有错字）、3（全对）" if item["genre"] == "dictation" else "0、1、2、3"
    current = state.sessions[job["session_id"]]["grades"].get(job["item_id"])
    label = f"「{grade_label(item['genre'], current['grade'])}」" if current else "还没评分"
    return TASKS[job["mode"]].format(mark=MARK, allowed=allowed, current=label)


def _keep_images(job: dict) -> set:
    """这次要发原图的照片：本轮新拍的优先，再按新到旧补到 MAX_IMAGES 张。"""
    budget, keep = MAX_IMAGES, set()
    for turn in reversed(job["history"] + [{"role": "user", "images": job["images"]}]):
        for image_id in reversed(turn.get("images") or []):
            if budget > 0:
                keep.add(image_id)
                budget -= 1
    return keep


def _photo_note(images: list, keep: set) -> str:
    if not images:
        return ""
    dropped = sum(1 for i in images if i not in keep)
    return f"（附 {len(images)} 张作答照片{f'，其中 {dropped} 张较早的已省略' if dropped else ''}）\n"


# ── 只读 Agent（默认）────────────────────────────────────

def index_text(vault: str, job: dict) -> str:
    """索引：规则 + 学生正在看哪道题（只有题型、分值、所属材料这类元信息，不含题干、答案、原文）。"""
    state = get_state(vault)
    sess = state.sessions[job["session_id"]]
    item = state.items[job["item_id"]]
    ids = [e["id"] for e in sess["items"]]
    head = f"- 学生正在看：第 {ids.index(item['id']) + 1} 题（{item['id']}）· " \
        f"{GENRE_BY_CODE.get(item['genre'], {}).get('name', item['genre'])} · {item.get('qtype') or '—'}"
    if isinstance(item.get("score"), (int, float)) and item["score"]:
        head += f" · {item['score']:g} 分"
    mat = state.materials.get(item.get("material_id") or "")
    if mat:
        head += f" · 材料《{mat.get('title') or '无题'}》（{mat['id']}，{len(review_tools.paragraphs(mat.get('text')))} 段）"
    current = sess["grades"].get(item["id"])
    now = "还没评分" if not current else f"已自评「{grade_label(item['genre'], current['grade'])}」" \
        + (f"，反馈：{current['note']}" if current.get("note") else "")
    lines = [RULES, TOOLS_HELP, "## 现在", f"- 这次复习：{sess['id']}，卷上共 {len(ids)} 题", head, f"- 本次复习：{now}"]
    if not job["revealed"] and not current:
        lines.append("- 学生还没对这道题的答案：除非他明确要看，或者这次是打分任务，否则不要直接说出参考答案，可以先提示思路。")
    return "\n".join(lines)


def agent_messages(vault: str, job: dict, run_id: str):
    """history → harness 消息 + 这次的 prompt。只有要发原图的照片带 images，并标成本次 run（harness 只渲染本次 run 的图）。"""
    keep = _keep_images(job)
    messages = []
    for turn in job["history"]:
        if turn["role"] == "assistant":
            text = turn["text"] or "（空）"
            if turn.get("tools"):
                text += "\n（这一轮查过：" + "；".join(turn["tools"]) + "。内容没有再附上，需要时重新查。）"
            messages.append({"role": "assistant", "content": text})
            continue
        shown = [i for i in turn["images"] if i in keep]
        msg = {"role": "user", "content": _photo_note(turn["images"], keep) + said(vault, turn), "images": shown}
        if shown:
            msg["run"] = run_id
        messages.append(msg)
    task = _task_text(vault, job)
    text = _photo_note(job["images"], keep) + said(vault, job)
    prompt = {"role": "user", "content": f"{text}\n\n{task}" if task else text, "images": list(job["images"])}
    return messages, [prompt]


# ── 旧做法（关掉 Agent 模式时）：整道题的上下文并进第一条消息 ─────────

def _clip(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + "……（后略）"


def context_text(vault: str, job: dict) -> str:
    """这道题的全部上下文，并进第一条用户消息（不用 system 角色，与录入对话一致）。"""
    ctx = context(vault)
    state = get_state(vault)
    item = state.item_view(job["item_id"], ctx)
    sess = state.sessions[job["session_id"]]
    genre = GENRE_BY_CODE.get(item["genre"], {}).get("name", item["genre"])
    position = [e["id"] for e in sess["items"]].index(item["id"]) + 1
    head = [f"- 板块：{genre}", f"- 卷上第 {position} 题" + (f"（原卷第 {item['no']} 题）" if item.get("no") else "")]
    if item.get("qtype"):
        head.append(f"- 题型：{item['qtype']}")
    if isinstance(item.get("score"), (int, float)) and item["score"]:
        head.append(f"- 分值：{item['score']:g} 分")
    parts = [RULES, "## 这道题\n" + "\n".join(head)]
    mat = state.materials.get(item.get("material_id") or "")
    if mat:
        byline = " ".join(x for x in (mat.get("author"), mat.get("source")) if x)
        parts.append(f"## 材料《{mat.get('title') or '无题'}》{(' ' + byline) if byline else ''}\n{_clip(mat.get('text'), MAX_TEXT)}")
    stem = item["stem"].replace("{书写区域}", "____") if item["genre"] == "dictation" else item["stem"]
    parts.append("## 题干\n" + stem)
    parts.append("## 参考答案（阅卷标准）\n" + (item.get("answer") or "（没有参考答案）"))
    for key, title in (("analysis", "解析"), ("user_answer", "录入这道错题时的作答"), ("note", "录入时记下的错因")):
        if (item.get(key) or "").strip():
            parts.append(f"## {title}\n{item[key].strip()}")
    past = [r for r in state.reviews.values()
            if r["item_id"] == item["id"] and not r["voided_by"] and r["session_id"] != job["session_id"]]
    past.sort(key=lambda r: r["at"])
    if past:
        lines = [f"- {(parse_date(r['at']) or r['at'])} {grade_label(item['genre'], r['grade'])}"
                 + (f"：{r['note']}" if r.get("note") else "") for r in past[-6:]]
        parts.append("## 这道题以前的复习\n" + "\n".join(lines))
    current = sess["grades"].get(item["id"])
    now = "还没评分" if not current else f"已自评「{grade_label(item['genre'], current['grade'])}」" \
        + (f"，反馈：{current['note']}" if current.get("note") else "")
    note = "" if job["revealed"] or current else \
        "\n学生还没对答案：除非他明确要看，或者这次是打分任务，否则不要直接说出参考答案，可以先提示思路。"
    parts.append(f"## 本次复习\n{now}{note}")
    return "\n\n".join(parts)


def build_messages(vault: str, job: dict) -> list:
    """旧做法的 OpenAI 消息：第一条用户消息带上下文；只有最近 MAX_IMAGES 张照片发原图，更早的换成一句占位。"""
    keep = _keep_images(job)
    turns = job["history"] + [dict(job, role="user", current=True)]
    messages, first = [], True
    for turn in turns:
        if turn["role"] == "assistant":
            messages.append({"role": "assistant", "content": turn["text"] or "（空）"})
            continue
        content = []
        for image_id in turn["images"]:
            if image_id in keep:
                for url in ai_assist.image_data_urls(image_path(vault, image_id), 1280):
                    content.append({"type": "image_url", "image_url": {"url": url}})
        text = _photo_note(turn["images"], keep) + said(vault, turn)
        if turn.get("current"):
            task = _task_text(vault, job)
            text = f"{text}\n\n{task}" if task else text
        if first:
            text = context_text(vault, job) + "\n\n## 学生说\n" + text
            first = False
        content.append({"type": "text", "text": text})
        messages.append({"role": "user", "content": content})
    return messages


# ── 解析与执行 ──────────────────────────────────────────

def parse_suggestion(content: str, genre: str, mode: str):
    """拆出回答正文与建议：(reply, suggestion | None)。建议不合法时丢掉，只保留正文。"""
    at = content.rfind(MARK)
    if at < 0 or mode == "ask":
        return content.strip(), None
    reply, tail = content[:at].strip(), content[at + len(MARK):]
    try:
        data = ai_assist.extract_json(tail)
    except ValueError:
        return reply, None
    out = {}
    note = str(data.get("note") or "").strip()
    if note:
        out["note"] = note[:200]
    if mode == "grade" and data.get("grade") is not None:
        try:
            value = check_grade(genre, data["grade"])
            out["grade"], out["grade_label"] = value, grade_label(genre, value)
        except ValueError:
            pass
    return reply, (out or None)


class Relay:
    """模型的逐字回调 / harness 事件 → 前端的块事件。块：thinking / text（逐字）、tool（状态 + 摘要 + 结果）。"""

    def __init__(self, put):
        self.put, self.n, self.turn = put, 0, 0
        self.live = {"thinking": None, "text": None}
        self.slots, self.calls = {}, {}           # (轮, 下标) → 块；工具调用 id → 块
        self.tools = 0
        self.usage = {"input": 0, "output": 0, "estimated": False}

    def _open(self, kind, **extra) -> str:
        self.n += 1
        block = f"b{self.n}"
        self.put(dict({"type": "block", "id": block, "kind": kind}, **extra))
        return block

    def close(self, *kinds):
        for kind in kinds or ("thinking", "text"):
            if self.live[kind]:
                self.put({"type": "end", "id": self.live[kind]})
                self.live[kind] = None

    def delta(self, kind, text):
        if kind not in self.live or not text:
            return
        self.close("text" if kind == "thinking" else "thinking")
        if not self.live[kind]:
            self.live[kind] = self._open(kind)
        self.put({"type": "delta", "id": self.live[kind], "kind": kind, "text": text})

    def count(self, usage: dict):
        self.usage["input"] += int(usage.get("input") or 0)
        self.usage["output"] += int(usage.get("output") or 0)
        self.usage["estimated"] = self.usage["estimated"] or bool(usage.get("estimated"))

    def event(self, ev: dict):
        kind = ev["type"]
        if kind == "message_start":
            self.turn = ev.get("turn", self.turn + 1)
            self.close()
        elif kind == "delta":
            self.delta(ev["kind"], ev["text"])
        elif kind == "toolcall_delta":
            self.close()
            key = (self.turn, ev.get("index", 0))
            if key not in self.slots:
                self.slots[key] = self._open("tool", name=ev.get("name") or "", status="preparing")
        elif kind == "message_end":
            self.close()
            self.count(ev.get("usage") or {})
        elif kind == "tool_start":
            key = (self.turn, ev.get("index", 0))
            block = self.slots.get(key) or self._open("tool", name=ev["name"], status="preparing")
            self.slots[key] = self.calls[ev["id"]] = block
            self.put({"type": "tool", "id": block, "status": "running", "name": ev["name"], "label": ev.get("label") or ev["name"]})
        elif kind == "tool_end":
            self.tools += 1
            block = self.calls.get(ev["id"])
            if block:
                self.put({"type": "tool", "id": block, "status": "error" if ev.get("error") else "done",
                          "summary": str(ev.get("summary") or "")[:120], "result": str(ev.get("content") or "")[:2400]})


def _agent_on(vault: str) -> bool:
    return bool(load_config(vault).get("ai_agent", True))


def run(vault: str, job: dict, relay: Relay, stop=None) -> dict:
    """跑一次（Agent 或旧做法），逐字 / 工具事件经 relay 推出；返回 done 事件的内容。"""
    started = time.time()
    genre = get_state(vault).items[job["item_id"]]["genre"]
    if _agent_on(vault):
        run_id = uuid.uuid4().hex[:10]
        messages, prompts = agent_messages(vault, job, run_id)
        agent = harness.Agent(
            llm=lambda msgs, schemas, on_delta: ai_assist.chat(vault, msgs, schemas, on_delta),
            tools=review_tools.tools(vault, job), system_prompt=index_text(vault, job),
            render_images=lambda refs: [url for ref in refs for url in ai_assist.image_data_urls(image_path(vault, ref), 1280)],
            run_id=run_id, max_turns=AGENT_TURNS, on_event=relay.event, abort=stop, name="review")
        new = agent.run(messages, prompts)
        content = harness.final_text(new)
        last = next((m for m in reversed(new) if m["role"] == "assistant"), {})
        if not content and not last.get("tool_calls"):
            raise ValueError("模型输出达到上限还没开始回答：到「设置」提高输出 token 上限后重试")
        if not content:
            content = "查了几次还没理出结论，可以换个问法再问一次。"
    else:
        def relay_delta(kind, data):
            if stop is not None and stop.is_set():
                raise Stopped()
            if kind in ("text", "thinking"):
                relay.delta(kind, data)
        result = ai_assist.chat(vault, build_messages(vault, job), on_delta=relay_delta)
        relay.close()
        relay.count(result.get("usage") or {})
        if result.get("finish_reason") == "length" and not result.get("content"):
            raise ValueError("模型输出达到上限还没开始回答：到「设置」提高输出 token 上限后重试")
        content = result.get("content") or ""
    reply, suggestion = parse_suggestion(content, genre, job["mode"])
    return {"reply": reply, "suggestion": suggestion, "usage": relay.usage, "tools": relay.tools,
            "timing": {"seconds": round(time.time() - started, 1)}}


def stream(vault: str, job: dict):
    """SSE 片段生成器（事件见模块说明）。模型调用在后台线程里跑，经队列转成事件；
    客户端断开时生成器被关闭，设停止信号让模型连接立即断开。"""
    events, stop = queue.Queue(), threading.Event()

    def work():
        relay = Relay(events.put)
        try:
            events.put({"type": "done", **run(vault, job, relay, stop)})
        except (Stopped, harness.Aborted):
            pass
        except (ValueError, KeyError) as exc:
            relay.close()
            events.put({"type": "error", "msg": str(exc.args[0] if exc.args else exc)})
        except Exception as exc:  # noqa: BLE001
            relay.close()
            events.put({"type": "error", "msg": f"服务端出错：{exc}"})
        finally:
            events.put(None)

    def chunks():
        try:
            yield _event({"type": "start", "images": job["images"], "mode": job["mode"], "agent": _agent_on(vault)})
            threading.Thread(target=work, daemon=True).start()
            while True:
                try:
                    event = events.get(timeout=15)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                if event is None:
                    break
                yield _event(event)
        finally:
            stop.set()

    return chunks()


def _event(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
