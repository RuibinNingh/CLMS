"""复习助手：复习评分页右侧的 AI（v0.5，取代评分页顶部的「拍照交给 AI 批改」入口）。

它不是 Agent：不调用工具、不写 Ledger。每次请求带上这道题的上下文（材料、题干、参考答案、以前的复习、
本次评分）和前端保存的这段对话，流式返回模型的回答。三种模式：

- ask       随时提问（这题怎么想、我的答案哪里不够……）；
- grade     对照采分点打分，最后一行给出 【建议】{"grade": n, "note": "…"}；
- feedback  按当前评分写一条复习反馈，最后一行给出 【建议】{"note": "…"}。

服务端把【建议】解析成 suggestion 交给前端；评分和反馈由学生点「采用」后经 /api/session/grade、
/api/record/update 写入——模型不会悄悄改掉记录（Ledger 不变量同样成立）。
学生发来的作答照片按内容哈希存进 images/（与录入原图同一目录），对话里只传图片编号。
"""

import base64
import json
import queue
import threading

from . import ai_assist
from .common import parse_date
from .drafts import image_path, save_image
from .projections import context, get_state
from .records import check_grade, grade_label
from .taxonomy import GENRE_BY_CODE

MODES = ("ask", "grade", "feedback")
MARK = "【建议】"
MAX_TEXT = 6000          # 原文最多带多少字
MAX_TURNS = 16           # 最多带最近几轮对话
MAX_IMAGES = 4           # 最多带最近几张作答照片（全分辨率 1280 宽）

RULES = """## 复习助手
你是学生的语文复习助手。学生刚在纸上做完一份复习卷，正在对答案、自评。你帮他对照参考答案分析作答、讲清楚这道题。
- 用中文，简洁，先结论后理由；讲阅读题时按采分点说。参考答案就是阅卷标准，不要另立标准。
- 学生的作答可能是打字，也可能是照片；看不清的地方直接说看不清，不要猜。
- 评分档：阅读题 0 不会（没思路 / 答偏）、1 部分（只答到少量要点）、2 基本（主要要点都有）、3 完整（要点齐全、表述到位）；默写 0 不会、1 有错字、3 全对。"""

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


class Stopped(Exception):
    """前端断开（点了停止或离开页面）：流式读取中立即抛出，连接随之关闭。"""


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
    new_images = []
    for image in (body.get("images") or [])[:6]:
        data = str((image or {}).get("data") or "")
        data = data.split(",", 1)[1] if data.startswith("data:") else data
        try:
            new_images.append(save_image(vault, base64.b64decode(data, validate=False)))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{(image or {}).get('name') or '图片'}：{exc}")
    if mode == "ask" and not text and not new_images:
        raise ValueError("先写下要问的问题")
    history = []
    for turn in (body.get("history") or [])[-MAX_TURNS:]:
        role = "assistant" if (turn or {}).get("role") == "assistant" else "user"
        images = [str(i) for i in (turn.get("images") or []) if isinstance(i, str)]
        for image_id in images:
            image_path(vault, image_id)                   # 编号不合法就拒绝
        history.append({"role": role, "text": str(turn.get("text") or "")[:4000], "images": images})
    return {"session_id": session_id, "item_id": item_id, "mode": mode, "text": text or DEFAULT_TEXT.get(mode, ""),
            "images": new_images, "history": history, "revealed": bool(body.get("revealed"))}


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


def _task_text(vault: str, job: dict) -> str:
    if job["mode"] == "ask":
        return ""
    state = get_state(vault)
    item = state.items[job["item_id"]]
    allowed = "0（不会）、1（有错字）、3（全对）" if item["genre"] == "dictation" else "0、1、2、3"
    current = state.sessions[job["session_id"]]["grades"].get(job["item_id"])
    label = f"「{grade_label(item['genre'], current['grade'])}」" if current else "还没评分"
    return TASKS[job["mode"]].format(mark=MARK, allowed=allowed, current=label)


def build_messages(vault: str, job: dict) -> list:
    """OpenAI 形状的消息：第一条用户消息带上下文；只有最近 MAX_IMAGES 张照片发原图，更早的换成一句占位。"""
    turns = job["history"] + [{"role": "user", "text": job["text"], "images": job["images"], "current": True}]
    budget, keep = MAX_IMAGES, set()
    for turn in reversed(turns):
        for image_id in reversed(turn["images"]):
            if budget > 0:
                keep.add(image_id)
                budget -= 1
    messages, first = [], True
    for turn in turns:
        if turn["role"] == "assistant":
            messages.append({"role": "assistant", "content": turn["text"] or "（空）"})
            continue
        content, dropped = [], 0
        for image_id in turn["images"]:
            if image_id not in keep:
                dropped += 1
                continue
            for url in ai_assist.image_data_urls(image_path(vault, image_id), 1280):
                content.append({"type": "image_url", "image_url": {"url": url}})
        text = turn["text"]
        if turn["images"]:
            text = f"（附 {len(turn['images'])} 张作答照片{f'，其中 {dropped} 张较早的已省略' if dropped else ''}）\n{text}"
        if turn.get("current"):
            task = _task_text(vault, job)
            text = f"{text}\n\n{task}" if task else text
        if first:
            text = context_text(vault, job) + "\n\n## 学生说\n" + text
            first = False
        content.append({"type": "text", "text": text})
        messages.append({"role": "user", "content": content})
    return messages


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


def run(vault: str, job: dict, on_delta=None, stop=None) -> dict:
    messages = build_messages(vault, job)

    def relay(kind, data):
        if stop is not None and stop.is_set():
            raise Stopped()
        if kind in ("text", "thinking") and on_delta:
            on_delta(kind, data)

    result = ai_assist.chat(vault, messages, on_delta=relay)
    if result.get("finish_reason") == "length" and not result.get("content"):
        raise ValueError("模型输出达到上限还没开始回答：到「设置」提高输出 token 上限后重试")
    genre = get_state(vault).items[job["item_id"]]["genre"]
    reply, suggestion = parse_suggestion(result.get("content") or "", genre, job["mode"])
    return {"reply": reply, "suggestion": suggestion, "usage": result.get("usage"), "timing": result.get("timing")}


def stream(vault: str, job: dict):
    """SSE 片段生成器：start（新照片的编号）→ delta（思考 / 正文逐字）→ done 或 error。
    模型调用在后台线程里跑，经队列转成事件；客户端断开时生成器被关闭，设停止信号让模型连接立即断开。"""
    events, stop = queue.Queue(), threading.Event()

    def work():
        try:
            events.put({"type": "done", **run(vault, job, lambda kind, text: events.put(
                {"type": "delta", "kind": kind, "text": text}), stop)})
        except Stopped:
            pass
        except (ValueError, KeyError) as exc:
            events.put({"type": "error", "msg": str(exc.args[0] if exc.args else exc)})
        except Exception as exc:  # noqa: BLE001
            events.put({"type": "error", "msg": f"服务端出错：{exc}"})
        finally:
            events.put(None)

    def chunks():
        try:
            yield _event({"type": "start", "images": job["images"], "mode": job["mode"]})
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
