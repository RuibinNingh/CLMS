"""录入对话直连的 Agent（对标 Pi coding-agent 的「harness + 工具 + subagent」）。

一次任务 = 一次 run（harness.Agent.run）。三种任务：
- extract：刚上传的试卷。页数多或大题多时，主代理先看全卷，再用 delegate 把每个大题（一篇阅读材料 + 它的小题，
  或名句默写）交给子代理，只告诉子代理板块、标题和所在页码；子代理各自只看自己的页（原图全分辨率）、
  只能动自己的板块，并发执行。主代理最后用 draft_view 检查、补漏、总结。小卷子主代理直接自己录。
- chat：用户在对话里说的话。可以逐题改草稿、查改题库、增删改查复习记录、记复习反馈、入库。
- review：复习做完后的作答照片，逐题批改并写入评分与反馈。

drafts.py 提供 host（草稿的持久化、事件落盘、插话队列、停止信号），这里不直接读写草稿文件。
"""

import concurrent.futures
import threading

from . import ai_assist
from .agent_draft import Workspace, draft_tools
from .agent_ops import library_tools, record_tools, review_tools
from .common import load_config, today
from .harness import Agent, Aborted, Tool, ToolError, ToolResult, final_text
from .taxonomy import GENRE_BY_CODE, GENRES, normalize_genre, qtypes

SURVEY_WIDTH = 1024        # 主代理看全卷用的宽度（页数多时）；子代理和小卷子用 ai_assist.MAX_WIDTH
MAX_TASKS = 8


def qtype_table(vault) -> str:
    table = qtypes(vault)
    return "\n".join(f"- {g['name']}：" + "、".join(table[g["code"]]) for g in GENRES if g["code"] != "dictation")


RULES = """## 录入规则
- 板块只有四个：现代文阅读、文言文阅读、古代诗歌阅读、名句默写。每篇独立的阅读材料是一个板块；名句默写整份只用一个板块。
- 阅读材料：title 标题、author 作者、source 出处、text 原文。原文逐字转录，不改写、不省略；段落之间一个换行；古诗按原排版每句或每联换行；保留①②③；注释放在末尾另起一段以「注：」开头。
- 小题：no 题号原样；qtype 从题型表选最贴切的，实在没有才自拟以「题」结尾的名称；stem 题干原文（选择题把选项放进题干，每个选项一行）；answer 参考答案——图里有就照录（answer_origin=image），没有就按高考阅卷习惯分条补写（answer_origin=ai，每条一个采分点，条数与分值匹配）；analysis 图中有解析才录；score 分值；blank_lines 留白行数（选择 0，解释 / 断句 1–2，翻译每句 2–3，概括赏析 3–6，探究 6–10）；user_answer 学生作答看得清就录。
- 文言文精细到每道小题，不再往下拆。
- 名句默写：template 用 {书写区域1}、{书写区域2}… 标出要写的空（每条内从 1 编号），blanks 是编号到答案的表（只写诗文本身），source 出处，kind 直接默写 / 理解性默写。入库时每个空是一道题。

## 题型表
%s"""

MAIN_PROMPT = """你是 CLMS（高中语文错题本）的录入助手，运行在一个工具调用 harness 里：你只能通过调用工具来读写草稿、题库和复习记录；用户在界面右侧实时看到草稿的变化，左侧看到你的每一步工具调用。今天是 %s。

## 工作方式
- 用户能实时看到你的每一步。每次调用工具之前，先用一句话说明接下来要做什么、为什么（例如「先看全卷有几个大题」「第 7 题答案图里没有，我按 6 分补写」），不要默默连调一串工具。
- 先用工具查清现状再动手（draft_view、library_get、session_get）；只改用户要求改的地方，其余不动。
- 逐个板块、逐道题地写：材料用 material_set，小题用 items_add（一次加几道即可，别把整份卷子塞进一次调用），改题用 item_update / dictation_update。
- 删除类操作（删题、作废记录）只在用户明确要求时做；这些操作都能撤销。
- 草稿入库前用户会在界面上确认；只有用户明确说「入库」时才调用 draft_commit。
- 做完后用一两句话说明做了什么、哪些地方拿不准（看不清的字、图里没有答案由你补写的题）。不要把草稿内容整段复述。
%s
%s

## 当前草稿
%s
%s"""

DELEGATE_GUIDE = """
## 大试卷：委派子代理
试卷有 3 页以上、或有 2 个以上的大题（板块）时，不要自己逐题转录：先通读全卷，然后调用 delegate，把每个大题交给一个子代理，只需告诉它板块（genre）、标题和所在页码（pages，从 1 开始；跨页就写多页）；instructions 里补充题号范围或特别说明即可。子代理会并行工作，各自只负责自己的板块。全部完成后调用 draft_view 检查：补上遗漏的题、修正明显的问题，再总结。
只有 1–2 页、单个大题的小卷子，直接自己用 group_add / material_set / items_add / dictation_add 录入。"""

SUB_PROMPT = """你是 CLMS 录入流程里的子代理，只负责一个大题：%s。板块已经建好，编号 %s；你只能改这个板块。附图是它所在的第 %s 页（整份卷子共 %d 页，别的页不归你管）。
%s
## 做法
1. 先转录材料（阅读题用 material_set；原文很长可以分几次，后几次 append=true）。
2. 再按题号顺序用 items_add 添加小题（名句默写用 dictation_add），一次几道即可。
3. 不确定的字照图转录并在最后说明；图里没有答案的题由你补写（answer_origin=ai）。
4. 全部录完后，用一两句话回复：录了几道题、哪些地方拿不准。回复时不要再调用工具。

%s"""


class ImageRenderer:
    """图片引用 → data URL，按 (图片, 宽度, 旋转) 缓存：同一次 run 里每轮都要重发图片，不能每轮都重新缩图编码。
    pages 是准备阶段确认过的页：[{image, rotate, note}]；引用 {"page": n} 取第 n 页（带旋转），{"image": id} 取附图。"""

    def __init__(self, vault, pages, image_path):
        self.vault, self.pages, self.image_path = vault, list(pages), image_path
        self._cache, self._lock = {}, threading.Lock()

    def urls(self, refs, width=ai_assist.MAX_WIDTH) -> list:
        out = []
        for ref in refs or []:
            page = self.pages[ref["page"] - 1] if 0 < ref.get("page", 0) <= len(self.pages) else None
            image_id = ref.get("image") or (page or {}).get("image") or ""
            if not image_id:
                continue
            key = (image_id, ref.get("width") or width, int((page or {}).get("rotate") or 0))
            with self._lock:
                cached = self._cache.get(key)
            if cached is None:
                cached = ai_assist.image_data_urls(self.image_path(self.vault, image_id), key[1], key[2])
                with self._lock:
                    self._cache[key] = cached
            out += cached
        return out


def pages_note(pages) -> str:
    notes = [f"第 {n} 页：{p['note']}" for n, p in enumerate(pages, 1) if (p.get("note") or "").strip()]
    return ("\n用户对各页的说明：" + "；".join(notes)) if notes else ""


def _pages_text(pages) -> str:
    pages = sorted(pages)
    if len(pages) > 1 and pages == list(range(pages[0], pages[-1] + 1)):
        return f"{pages[0]}–{pages[-1]}"
    return "、".join(map(str, pages))


def delegate_tool(vault, ws: Workspace, renderer: ImageRenderer, llm, parent_run: str, page_info=None) -> Tool:
    cfg = load_config(vault)
    workers = max(1, min(6, int(cfg.get("agent_subagents") or 3)))
    sub_turns = max(4, int(cfg.get("agent_sub_turns") or 16))

    def execute(args, ctx):
        raw = args.get("tasks") or []
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_TASKS:
            raise ToolError(f"tasks 要有 1–{MAX_TASKS} 个")
        tasks = []
        with ws.lock:
            for n, t in enumerate(raw, 1):
                t = t if isinstance(t, dict) else {}
                genre = normalize_genre(t.get("genre"), default="")
                pages = sorted({int(p) for p in t.get("pages") or [] if str(p).lstrip("-").isdigit()})
                if not genre:
                    raise ToolError(f"第 {n} 个任务的 genre 无效")
                if not pages or any(not 1 <= p <= len(ws.pages) for p in pages):
                    raise ToolError(f"第 {n} 个任务的 pages 要在 1–{len(ws.pages)} 之间")
                if t.get("gid"):
                    group = ws.group(t["gid"])
                elif genre == "dictation":
                    group = ws.dictation_group()
                else:
                    group = ws.add_group(genre, {"title": str(t.get("title") or "")})
                tasks.append({"n": n, "gid": group["gid"], "genre": genre, "title": str(t.get("title") or ""),
                              "pages": pages, "instructions": str(t.get("instructions") or ""),
                              "status": "queued", "tools": 0, "turns": 0, "last": "", "summary": "", "error": ""})
        ws.changed()
        lock = threading.Lock()

        def push():
            with lock:
                ctx.update({"tasks": [{k: v for k, v in t.items() if k != "instructions"} for t in tasks]})

        def on_event(task, forward, event):
            forward(event)
            if event["type"] == "tool_start":
                task["last"] = event.get("label", "")
            elif event["type"] == "tool_end":
                task["tools"] += 1
            elif event["type"] == "turn_start":
                task["turns"] = event["turn"]
            else:
                return
            push()

        def work(task):
            if ctx.aborted:
                task["status"] = "stopped"
                return
            task["status"] = "running"
            push()
            name = GENRE_BY_CODE[task["genre"]]["name"] + (f"《{task['title']}》" if task["title"] else "")
            notes = pages_note([p if n + 1 in task["pages"] else {} for n, p in enumerate(page_info or [])])
            prompt = SUB_PROMPT % (name, task["gid"], _pages_text(task["pages"]), len(ws.pages),
                                   ("\n## 主代理的说明\n" + task["instructions"] + "\n") if task["instructions"] else "",
                                   RULES % qtype_table(vault) + notes)
            forward = ctx.sub_events(task["n"])
            sub = Agent(llm=llm, tools=draft_tools(ws, scope=task["gid"], structure=False), system_prompt=prompt,
                        render_images=lambda refs: renderer.urls(refs), run_id=f"{parent_run}.{task['n']}",
                        max_turns=sub_turns, on_event=lambda ev: on_event(task, forward, ev),
                        abort=ctx.agent.abort_event, name=f"sub{task['n']}")
            try:
                new = sub.run([], [{"role": "user", "content": f"请录入{name}（第 {_pages_text(task['pages'])} 页）。",
                                    "images": [{"page": p} for p in task["pages"]]}])
                task["summary"] = final_text(new)[:400] or "（子代理没有总结）"
                task["status"] = "done"
            except Aborted:
                task["status"] = "stopped"
            except Exception as exc:  # noqa: BLE001 - 一个子代理失败不影响其它的；主代理会看到原因
                task["status"], task["error"] = "error", str(exc)[:300]
            push()

        push()
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
            list(pool.map(work, tasks))
        if ctx.aborted:
            raise Aborted()
        lines = []
        for t in tasks:
            head = f"{t['gid']} {GENRE_BY_CODE[t['genre']]['short']}{'《' + t['title'] + '》' if t['title'] else ''}（第 {_pages_text(t['pages'])} 页）"
            lines.append(f"- {head}：" + (t["summary"] if t["status"] == "done" else f"失败：{t['error'] or t['status']}"))
        done = sum(1 for t in tasks if t["status"] == "done")
        text = f"{done}/{len(tasks)} 个子代理完成。\n" + "\n".join(lines) + "\n请用 draft_view 检查整份草稿，补漏、修正后再总结。"
        return ToolResult(text, {"summary": f"{done}/{len(tasks)} 个子代理完成",
                                 "tasks": [{k: v for k, v in t.items() if k != "instructions"} for t in tasks]})

    return Tool(
        "delegate",
        "把大题分派给子代理并行录入（每个任务一个大题）。只需给出板块、标题和所在页码；子代理只看这些页、只改自己的板块。"
        "gid 可选：给已有板块时，子代理在它上面补录 / 修正。",
        {"type": "object", "properties": {"tasks": {"type": "array", "items": {"type": "object", "properties": {
            "genre": {"type": "string", "enum": ["现代文阅读", "文言文阅读", "古代诗歌阅读", "名句默写"]},
            "title": {"type": "string", "description": "材料标题（默写可空）"},
            "pages": {"type": "array", "items": {"type": "integer"}, "description": "所在页码，从 1 开始"},
            "instructions": {"type": "string", "description": "补充说明，如题号范围 6–9"},
            "gid": {"type": "string"}}, "required": ["genre", "pages"]}}}, "required": ["tasks"]},
        execute, lambda a: f"委派 {len(a.get('tasks') or [])} 个子代理")


def commit_tool(host, ws: Workspace) -> Tool:
    def execute(args, ctx):
        result = host.commit(ws.snapshot())
        ws.readonly = True
        text = f"已入库 {result['created']} 题" + (f"，{result['reencountered']} 题库里已有、记为又错一次" if result["reencountered"] else "")
        return ToolResult(text + "。草稿现在只读。", {"summary": text})
    return Tool("draft_commit", "把整份草稿入库（写进题库）。只在用户明确要求入库时调用；有待补问题时会失败。",
                {"type": "object", "properties": {}}, execute, lambda a: "入库")


def run(vault: str, host, job: dict) -> dict:
    """跑一次任务。host 需要提供：pages、groups、committed、transcript、run_id、flush(groups)、event(ev)、
    steering()、abort（threading.Event）、commit(groups)、image_path(vault, id)。"""
    kind = {"revise": "chat"}.get(job["type"], job["type"])      # 对话任务沿用旧名 revise（重试兼容）
    llm = lambda messages, tools, on_delta: ai_assist.chat(vault, messages, tools, on_delta)  # noqa: E731
    ws = Workspace(vault, host.groups, host.pages, on_change=host.flush, readonly=host.committed)
    renderer = ImageRenderer(vault, host.pages, host.image_path)
    width = ai_assist.MAX_WIDTH if len(host.pages) <= 2 else SURVEY_WIDTH
    pages = [{"page": n, "width": width} for n in range(1, len(host.pages) + 1)]
    tools, delegate = [], False
    if kind == "review":
        tools = review_tools(vault) + record_tools(vault) + library_tools(vault)[:2]
        tools += [t for t in draft_tools(ws) if t.name == "view_pages"]
    else:
        if host.committed:
            tools += [t for t in draft_tools(ws) if t.name in ("draft_view", "view_pages")]
        else:
            tools += draft_tools(ws)
            if host.pages:
                tools.append(delegate_tool(vault, ws, renderer, llm, host.run_id, host.pages))
                delegate = True
        if kind == "chat":
            if not host.committed:
                tools.append(commit_tool(host, ws))
            tools += library_tools(vault) + record_tools(vault) + review_tools(vault)
    if kind == "extract":
        hint = (job.get("hint") or "").strip()
        text = (f"这是一份语文试卷 / 练习的照片，共 {len(host.pages)} 页（用户已确认顺序，第 1–{len(host.pages)} 页）。请识别并录入草稿。"
                + (f"\n用户补充说明：{hint}" if hint else "") + pages_note(host.pages)
                + ("\n草稿里已经有上次录了一半的内容，先 draft_view 检查，补全缺的，不要重复添加。" if ws.groups else ""))
        prompts = [{"role": "user", "content": text, "images": pages}]
    elif kind == "review":
        text = (f"这是复习 {job['session_id']} 做完后的作答照片，共 {len(host.pages)} 页。请先 session_get 看题目和参考答案，"
                "再对照照片逐题批改：给出评分和一句具体的反馈（错在哪、漏了哪个采分点），用 review_grade 一次写入。"
                "看不清或没作答的题不要评，最后告诉我。" + (f"\n用户补充说明：{job['hint']}" if job.get("hint") else ""))
        prompts = [{"role": "user", "content": text, "images": pages}]
    else:
        refs = [{"image": i} for i in job.get("images") or []]
        if job.get("with_image"):
            refs = pages + refs
        prompts = [{"role": "user", "content": job["text"], "images": refs}]
    system = MAIN_PROMPT % (today().isoformat(), DELEGATE_GUIDE if delegate else "",
                            RULES % qtype_table(vault) if kind != "review" else "",
                            ws.outline() if kind != "review" else "（批改任务不涉及草稿）",
                            f"\n## 图片\n这段对话共有 {len(host.pages)} 页图片（view_pages 可再看）。" if host.pages else "")
    agent = Agent(llm=llm, tools=tools, system_prompt=system, render_images=lambda refs: renderer.urls(refs),
                  run_id=host.run_id, max_turns=max(4, int(load_config(vault).get("agent_max_turns") or 30)),
                  on_event=host.event, steering=host.steering, abort=host.abort)
    new = agent.run(host.transcript, prompts)
    reason = next((m for m in reversed(new) if m["role"] == "assistant"), None)
    text = final_text(new)
    if agent.turns >= agent.max_turns and reason and reason.get("tool_calls"):
        text = (text + "\n" if text else "") + f"（已达到单次最多 {agent.max_turns} 轮的上限，先停在这里；可以让我继续。）"
    return {"text": text or "完成。", "turns": agent.turns, "tool_calls": agent.tool_calls, "groups": ws.snapshot()}
