"""复习助手的只读工具（v0.6）：题目、原文、以前的复习都由模型按需调用，不再每次整篇塞进上下文。

- 只读：不写 Ledger、不改题库。评分 / 反馈仍然只是建议（review_ai.py），学生点「采用」后才写入。
- 编号与评分页一致：卷上题序 n 从 1 开始；原文按非空行分段，段号从 1 开始（评分页原文左边的小号数字）。
- 范围限定在这次复习：只能看这次复习里的题和它们的材料。
- 每次调用都重新取状态：学生可能刚改过评分。
"""

import re

from .common import parse_date
from .harness import Tool, ToolError, ToolResult
from .projections import context, get_state
from .records import grade_label
from .taxonomy import GENRE_BY_CODE

MAX_READ = 6000          # material_read 一次最多返回多少字
_RANGE = re.compile(r"(\d+)\s*[-–—~～至到]\s*(\d+)")


def paragraphs(text: str) -> list:
    """与前端 domain/paper.js passage() 同一套分段：按换行切、去空白、丢空行。"""
    return [p.strip() for p in str(text or "").split("\n") if p.strip()]


def parse_range(spec, total: int) -> list:
    """「2」「2-4」「1,3,5」「2–4、6」→ 段号列表（1 起，去重保序，越界的忽略）。"""
    out = []
    for part in re.split(r"[,，、;；\s]+", str(spec or "").strip()):
        if not part:
            continue
        m = _RANGE.fullmatch(part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out += range(min(a, b), max(a, b) + 1)
        elif part.isdigit():
            out.append(int(part))
        else:
            raise ToolError(f"段号「{part}」看不懂：写成 2、2-4 或 1,3")
    return [n for n in dict.fromkeys(out) if 1 <= n <= total]


def _short(genre: str) -> str:
    return GENRE_BY_CODE.get(genre, {}).get("short", genre)


def _stem(item: dict) -> str:
    return item["stem"].replace("{书写区域}", "____") if item["genre"] == "dictation" else item["stem"]


class Desk:
    """一次助手请求能看到的复习。job 来自 review_ai.prepare：session_id、item_id（学生正在看的题）、revealed_ids。"""

    def __init__(self, vault: str, job: dict):
        self.vault, self.job = vault, job

    def session(self):
        state = get_state(self.vault)
        sess = state.sessions.get(self.job["session_id"])
        if not sess or sess["cancelled"]:
            raise ToolError("这次复习已经删除了")
        return state, sess

    def resolve(self, args: dict):
        """n（卷上题序）或 item_id → (state, sess, item_id, n)；都没给就是学生正在看的那道。"""
        state, sess = self.session()
        ids = [e["id"] for e in sess["items"]]
        item_id, n = str(args.get("item_id") or "").strip(), args.get("n")
        if item_id:
            if item_id not in ids:
                raise ToolError(f"{item_id} 不在这次复习里；卷上共 {len(ids)} 题，可以用 n 按题序指定")
        elif n not in (None, ""):
            if not 1 <= int(n) <= len(ids):
                raise ToolError(f"卷上只有 {len(ids)} 题")
            item_id = ids[int(n) - 1]
        else:
            item_id = self.job["item_id"]
        return state, sess, item_id, ids.index(item_id) + 1

    def materials(self, state, sess) -> dict:
        out = {}
        for entry in sess["items"]:
            mid = (state.items.get(entry["id"]) or {}).get("material_id")
            if mid and mid in state.materials:
                out.setdefault(mid, state.materials[mid])
        return out

    def revealed(self, sess, item_id: str) -> bool:
        return item_id in self.job.get("revealed_ids", ()) or item_id in sess["grades"]


def tools(vault: str, job: dict) -> list:
    desk = Desk(vault, job)

    def outline(args, ctx):
        state, sess = desk.session()
        current = [e["id"] for e in sess["items"]].index(job["item_id"]) + 1
        lines = [f"复习 {sess['id']}，卷上共 {len(sess['items'])} 题；学生正在看第 {current} 题。"]
        for n, entry in enumerate(sess["items"], 1):
            item = state.items.get(entry["id"])
            if not item:
                continue
            mat = state.materials.get(item.get("material_id") or "")
            where = f"《{mat['title'] or '无题'}》" if mat else (item.get("source") or "名句默写")
            graded = sess["grades"].get(item["id"])
            score = f" · {item['score']:g} 分" if isinstance(item.get("score"), (int, float)) and item["score"] else ""
            lines.append(f"- 第 {n} 题 {item['id']} · {_short(item['genre'])} · {item.get('qtype') or '—'}{score} · {where} · "
                         + (f"已自评「{grade_label(item['genre'], graded['grade'])}」" if graded else "未评"))
        mats = desk.materials(state, sess)
        if mats:
            lines.append("材料：")
            for mid, mat in mats.items():
                paras = paragraphs(mat.get("text"))
                byline = " ".join(x for x in (mat.get("author"), mat.get("source")) if x)
                lines.append(f"- {mid}《{mat.get('title') or '无题'}》{(' ' + byline) if byline else ''}，"
                             f"共 {len(paras)} 段、{sum(len(p) for p in paras)} 字")
        return ToolResult("\n".join(lines), {"summary": f"{len(sess['items'])} 题 · {len(mats)} 篇材料"})

    def question(args, ctx):
        state, sess, item_id, n = desk.resolve(args)
        item = state.item_view(item_id, context(vault))
        head = f"第 {n} 题（{item_id}" + (f"，原卷第 {item['no']} 题" if item.get("no") else "") + "）" \
            + f" · {GENRE_BY_CODE.get(item['genre'], {}).get('name', item['genre'])} · {item.get('qtype') or '—'}"
        if isinstance(item.get("score"), (int, float)) and item["score"]:
            head += f" · {item['score']:g} 分"
        parts = [head]
        mat = state.materials.get(item.get("material_id") or "")
        if mat:
            parts.append(f"材料：《{mat.get('title') or '无题'}》（{mat['id']}，共 {len(paragraphs(mat.get('text')))} 段；"
                         "要看原文用 material_read）")
        elif item.get("source"):
            parts.append(f"出处：{item['source']}")
        parts += ["## 题干", _stem(item), "## 参考答案（阅卷标准）", (item.get("answer") or "").strip() or "（没有参考答案）"]
        for key, title in (("analysis", "解析"), ("user_answer", "录入这道错题时的作答"), ("note", "录入时记下的错因")):
            if (item.get(key) or "").strip():
                parts += [f"## {title}", item[key].strip()]
        graded = sess["grades"].get(item_id)
        status = f"已自评「{grade_label(item['genre'], graded['grade'])}」" + (f"，反馈：{graded['note']}" if graded.get("note") else "") \
            if graded else "还没评分"
        if not desk.revealed(sess, item_id):
            status += "；学生还没对这道题的答案：除非他明确要看，或者这次是打分任务，否则不要直接说出参考答案，可以先提示思路"
        parts += ["## 本次复习", status]
        return ToolResult("\n".join(parts), {"summary": " · ".join(x for x in (
            item.get("qtype"), f"{item['score']:g} 分" if isinstance(item.get("score"), (int, float)) and item["score"] else "") if x)})

    def read(args, ctx):
        state, sess = desk.session()
        mats = desk.materials(state, sess)
        mid = str(args.get("material_id") or "").strip()
        if not mid:
            mid = (state.items.get(job["item_id"]) or {}).get("material_id") or ""
        if mid not in mats:
            names = "、".join(f"{k}《{v.get('title') or '无题'}》" for k, v in mats.items()) or "（这次复习没有阅读材料）"
            raise ToolError(f"这次复习里没有材料 {mid or '（未指定）'}；可以读的：{names}")
        mat = mats[mid]
        paras = paragraphs(mat.get("text"))
        picked = parse_range(args["paragraphs"], len(paras)) if str(args.get("paragraphs") or "").strip() \
            else list(range(1, len(paras) + 1))
        query = str(args.get("query") or "").strip()
        if query:
            picked = [n for n in picked if query in paras[n - 1]]
        shown, used = [], 0
        for n in picked:
            text = paras[n - 1]
            if shown and used + len(text) > MAX_READ:
                break
            shown.append(n)
            used += len(text)
        byline = " ".join(x for x in (mat.get("author"), mat.get("source")) if x)
        head = f"《{mat.get('title') or '无题'}》{(' ' + byline) if byline else ''}（{mid}）共 {len(paras)} 段"
        if not shown:
            return ToolResult(head + (f"；没有找到含「{query}」的段落" if query else "；指定的段号不在范围内"),
                              {"summary": "没有找到" if query else "段号越界"})
        lines = [head + ("，下面是全文：" if len(shown) == len(paras) else f"，下面是其中 {len(shown)} 段：")]
        lines += [f"[{n}] {paras[n - 1]}" for n in shown]
        if len(shown) < len(picked):
            lines.append(f"（太长了，只返回到第 {shown[-1]} 段；其余用 paragraphs 指定段号再读）")
        return ToolResult("\n".join(lines), {"summary": f"{len(shown)} 段 · {used} 字"})

    def history(args, ctx):
        state, sess, item_id, n = desk.resolve(args)
        item = state.item_view(item_id, context(vault))
        past = sorted((r for r in state.reviews.values()
                       if r["item_id"] == item_id and not r["voided_by"] and r["session_id"] != sess["id"]),
                      key=lambda r: r["at"])
        sched = item.get("sched") or {}
        lines = [f"第 {n} 题（{item_id}）：录入 {item.get('encounters', 1)} 次；状态 {sched.get('status', '—')}"
                 + ("，顽固题" if sched.get("leech") else "")]
        if past:
            lines.append("以前的复习（旧 → 新）：")
            lines += [f"- {parse_date(r['at']) or r['at']} {grade_label(item['genre'], r['grade'])}"
                      + (f"：{r['note']}" if r.get("note") else "") for r in past[-8:]]
        else:
            lines.append("以前没有复习过这道题。")
        return ToolResult("\n".join(lines), {"summary": f"{len(past)} 次复习" if past else "没有复习过"})

    def title_of(mid: str) -> str:
        state = get_state(vault)
        mid = mid or (state.items.get(job["item_id"]) or {}).get("material_id") or ""
        return (state.materials.get(mid) or {}).get("title") or "原文"

    def read_label(a):
        text = f"读《{title_of(str(a.get('material_id') or ''))}》"
        if str(a.get("paragraphs") or "").strip():
            text += f"第 {a['paragraphs']} 段"
        if str(a.get("query") or "").strip():
            text += f"，找「{a['query']}」"
        return text

    ref = {"n": {"type": "integer", "description": "卷上题序（1 起）；不填就是学生正在看的那道"},
           "item_id": {"type": "string", "description": "题库编号，如 Q-000012（和 n 二选一）"}}
    return [
        Tool("review_outline", "看这次复习卷的题目清单（题序、题型、分值、所属材料、是否已评）和材料列表（段数、字数）。",
             {"type": "object", "properties": {}}, outline, lambda a: "看这次复习的题目清单"),
        Tool("question_get", "看一道题：题干、参考答案（阅卷标准）、解析、录入时的作答与错因、本次评分。",
             {"type": "object", "properties": ref}, question,
             lambda a: f"看第 {a['n']} 题" if a.get("n") else (f"看 {a['item_id']}" if a.get("item_id") else "看这道题")),
        Tool("material_read", "读阅读材料原文，返回带段号的段落。长文章只读需要的段（paragraphs），"
             "或用 query 找含某个词句的段落；不填 material_id 就是当前这道题的材料。",
             {"type": "object", "properties": {
                 "material_id": {"type": "string", "description": "材料编号，如 M-000003"},
                 "paragraphs": {"type": "string", "description": "段号：2、2-4 或 1,3"},
                 "query": {"type": "string", "description": "只要含这个词句的段落"}}}, read, read_label),
        Tool("item_history", "查一道题以前的复习（日期、评分、反馈）和录入次数、记忆状态。",
             {"type": "object", "properties": ref}, history,
             lambda a: "查以前的复习" + (f"（第 {a['n']} 题）" if a.get("n") else "")),
    ]
