"""Agent 的草稿工具：模型逐个板块 / 逐道题地建、查、改、删草稿，而不是一次吐出整份 JSON。

Workspace 是一次 run 里的草稿工作副本（主代理和子代理共用，带锁）；每次改动后调用 on_change(groups)，
drafts.py 把它写进本次 run 的那一版 revision（整次 run 只占一版，前端轮询能看到实时进度）。
所有输入都经 draft_schema 的归一化，和手工编辑、旧的整份识图走同一套规则。

scope：子代理只负责一个板块（gid），越界的调用直接报错；它不能新建 / 删除板块。
"""

import copy
import json
import threading

from . import creation
from .draft_schema import FIELD_LABELS, MATERIAL_FIELDS, clean_text, issues, normalize_dictation, normalize_groups, \
    normalize_item
from .harness import Tool, ToolError, ToolResult
from .taxonomy import GENRE_BY_CODE, normalize_genre

ITEM_PROPS = {
    "no": {"type": "string", "description": "题号原样，如 7、8(1)"},
    "qtype": {"type": "string", "description": "题型，从题型表里选"},
    "stem": {"type": "string", "description": "题干原文；选择题把选项放进题干，每个选项一行"},
    "answer": {"type": "string", "description": "参考答案，分条写，每条一个采分点"},
    "answer_origin": {"type": "string", "enum": ["image", "ai", "user"],
                      "description": "image=图中照录；ai=你补写或改写的"},
    "analysis": {"type": "string", "description": "解析（图中有才录）"},
    "score": {"type": "number", "description": "分值"},
    "blank_lines": {"type": "integer", "description": "答题留白行数 0–24（每行约 20 字）"},
    "user_answer": {"type": "string", "description": "学生自己的作答"},
    "note": {"type": "string", "description": "错因"},
}
DICT_PROPS = {
    "template": {"type": "string", "description": "题面，每个要写的空写成 {书写区域1}、{书写区域2}…"},
    "blanks": {"type": "object", "description": "编号到答案的表，如 {\"1\": \"疑是地上霜\"}"},
    "source": {"type": "string", "description": "出处，如 李白《静夜思》"},
    "kind": {"type": "string", "enum": ["直接默写", "理解性默写"]},
}
MAT_PROPS = {k: {"type": "string"} for k in MATERIAL_FIELDS}
MAT_PROPS["text"]["description"] = "原文全文，逐字转录；段落之间一个换行；保留①②③；注释放末尾以「注：」开头"


class Workspace:
    def __init__(self, vault, groups, pages, on_change=None, readonly=False):
        self.vault, self.pages, self.on_change, self.readonly = vault, list(pages or []), on_change, readonly
        self.groups = normalize_groups(copy.deepcopy(groups or []))
        self.lock = threading.RLock()

    def snapshot(self) -> list:
        with self.lock:
            return copy.deepcopy(self.groups)

    def changed(self):
        """在锁内取快照并落盘：子代理并发改草稿时，落盘顺序和改动顺序一致，不会用旧快照盖掉新的。"""
        if self.on_change:
            with self.lock:
                self.on_change(self.snapshot())

    def _used(self):
        gids = {g["gid"] for g in self.groups}
        iids = {e["iid"] for g in self.groups for e in g["items"] + g["dictation"]}
        return gids, iids

    def new_gid(self) -> str:
        gids, _ = self._used()
        return next(f"g{n}" for n in range(1, 9999) if f"g{n}" not in gids)

    def new_iid(self, prefix) -> str:
        _, iids = self._used()
        return next(f"{prefix}{n}" for n in range(1, 99999) if f"{prefix}{n}" not in iids)

    def group(self, gid) -> dict:
        found = next((g for g in self.groups if g["gid"] == gid), None)
        if not found:
            raise ToolError(f"草稿里没有板块 {gid}。现有：" + ("、".join(g["gid"] for g in self.groups) or "（空）"))
        return found

    def dictation_group(self, create=True):
        found = next((g for g in self.groups if g["genre"] == "dictation"), None)
        if found or not create:
            return found
        found = normalize_groups([{"gid": self.new_gid(), "genre": "dictation"}])[0]
        self.groups.append(found)
        return found

    def add_group(self, genre, material=None) -> dict:
        group = normalize_groups([{"gid": self.new_gid(), "genre": genre, "material": material or {}}])[0]
        self.groups.append(group)
        return group

    def find(self, ref, gid=None):
        """ref 可以是 iid（i3 / d2），也可以是题号（7、第7题）。返回 (group, key, entry)。"""
        ref = str(ref or "").strip()
        pool = [g for g in self.groups if not gid or g["gid"] == gid]
        for group in pool:
            for key in ("items", "dictation"):
                for entry in group[key]:
                    if entry["iid"] == ref:
                        return group, key, entry
        no = ref.replace("第", "").replace("题", "").strip()
        hits = [(g, "items", e) for g in pool for e in g["items"] if no and e.get("no") == no]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ToolError(f"第 {no} 题有 {len(hits)} 处：" + "、".join(f"{g['gid']}/{e['iid']}" for g, _, e in hits)
                            + "。请用 iid 指定")
        raise ToolError(f"找不到 {ref}。先用 draft_view 看一下 iid")

    # ── 给模型看的视图 ──────────────────────────────────
    def outline(self) -> str:
        if not self.groups:
            return "（草稿是空的）"
        lines = []
        for g in self.groups:
            name = GENRE_BY_CODE[g["genre"]]["name"]
            if g["genre"] == "dictation":
                parts = [f"{e['iid']} {e.get('source') or '未注出处'}（{len(e['blanks'])} 空）" for e in g["dictation"]]
                lines.append(f"{g['gid']} {name}：" + ("；".join(parts) or "（没有题）"))
                continue
            title = g["material"]["title"]
            head = f"{g['gid']} {name}" + (f"《{title}》" if title else "") + f"（原文 {len(g['material']['text'])} 字）"
            parts = [f"{e['iid']} 第{e['no'] or '?'}题 {e['qtype'] or '未分类'}"
                     + (f" {e['score']}分" if e["score"] is not None else "") + ("" if e["answer"] else " 无答案")
                     for e in g["items"]]
            lines.append(head + "：" + ("；".join(parts) or "（没有小题）"))
        return "\n".join(lines)

    def view(self, gid=None) -> dict:
        with self.lock:
            if gid:
                return {"group": copy.deepcopy(self.group(gid))}
            out = {"outline": self.outline(), "issues": issues(self.groups)}
            if self.groups:
                dd = creation.annotate(self.vault, self.groups)
                out["dedupe"] = {"new_units": dd["new_units"], "dup_units": dd["dup_units"],
                                 "material_matches": {k: v["material_match"]["title"] for k, v in dd["groups"].items()
                                                      if v["material_match"]}}
            return out


def _changes_text(args, keys) -> str:
    return "、".join(FIELD_LABELS.get(k, k) for k in keys if k in args) or "字段"


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def draft_tools(ws: Workspace, scope: str = "", structure: bool = True) -> list:
    """草稿工具集。scope 非空时是子代理：只能动这个板块。structure=False 时不给建 / 删板块。"""

    def guard(gid):
        if ws.readonly:
            raise ToolError("草稿已经入库，只读；要改题请用题库工具（library_*）")
        if scope and gid != scope:
            raise ToolError(f"你只负责板块 {scope}，不能改 {gid}")

    def title_of(gid):
        g = next((x for x in ws.groups if x["gid"] == gid), None)
        if not g:
            return gid
        return f"《{g['material']['title']}》" if g["material"]["title"] else GENRE_BY_CODE[g["genre"]]["short"]

    def ok(text, summary=None, gid=None):
        extra = ""
        if gid:
            probs = [p["message"] for p in issues([ws.group(gid)])]
            extra = ("\n这个板块还缺：" + "；".join(probs[:6])) if probs else "\n这个板块检查通过。"
        return ToolResult(text + extra, {"summary": summary or text})

    # ── 查 ──
    def draft_view(args, ctx):
        gid = args.get("gid") or ""
        if scope and not gid:
            gid = scope
        return ToolResult(_dump(ws.view(gid or None)), {"summary": f"查看 {gid or '整份草稿'}"})

    # ── 板块 ──
    def group_add(args, ctx):
        guard("")
        genre = normalize_genre(args["genre"], default="")
        if not genre:
            raise ToolError("genre 只能是：现代文阅读、文言文阅读、古代诗歌阅读、名句默写")
        with ws.lock:
            if genre == "dictation":
                existing = ws.dictation_group(create=False)
                if existing:
                    return ok(f"名句默写只用一个板块，已有 {existing['gid']}，直接用 dictation_add 往里加")
                group = ws.dictation_group()
            else:
                group = ws.add_group(genre, {k: args.get(k, "") for k in MATERIAL_FIELDS})
        ws.changed()
        return ok(f"已新建板块 {group['gid']}（{GENRE_BY_CODE[genre]['name']}）", gid=group["gid"])

    def group_delete(args, ctx):
        guard("")
        with ws.lock:
            group = ws.group(args["gid"])
            ws.groups.remove(group)
        ws.changed()
        return ok(f"已删除板块 {args['gid']}")

    def material_set(args, ctx):
        gid = args.get("gid") or scope
        guard(gid)
        with ws.lock:
            group = ws.group(gid)
            if group["genre"] == "dictation":
                raise ToolError("名句默写没有阅读材料")
            if args.get("genre"):
                group["genre"] = normalize_genre(args["genre"], default=group["genre"])
            for key in MATERIAL_FIELDS:
                if key in args and args[key] is not None:
                    value = str(args[key])
                    if key == "text" and args.get("append") and group["material"]["text"]:
                        value = group["material"]["text"] + "\n" + value
                    group["material"][key] = clean_text(value)
            size = len(group["material"]["text"])
        ws.changed()
        return ok(f"{gid} 的材料已更新（原文 {size} 字）", f"{title_of(gid)} · {_changes_text(args, MATERIAL_FIELDS)}")

    # ── 阅读小题 ──
    def items_add(args, ctx):
        gid = args.get("gid") or scope
        guard(gid)
        raw = args.get("items") or []
        if not isinstance(raw, list) or not raw:
            raise ToolError("items 至少要有一道题")
        with ws.lock:
            group = ws.group(gid)
            if group["genre"] == "dictation":
                raise ToolError("名句默写请用 dictation_add")
            added = []
            for entry in raw:
                entry = dict(entry) if isinstance(entry, dict) else {}
                if entry.get("answer") and not entry.get("answer_origin"):
                    entry["answer_origin"] = "image"
                item = normalize_item(entry, ws.new_iid("i"))
                group["items"].append(item)
                added.append(item)
        ws.changed()
        names = "、".join(f"{i['iid']}=第{i['no'] or '?'}题" for i in added)
        return ok(f"已在 {gid} 添加 {len(added)} 题：{names}", f"{title_of(gid)} 添加 {len(added)} 题", gid=gid)

    def item_update(args, ctx):
        with ws.lock:
            group, key, entry = ws.find(args["ref"], args.get("gid") or (scope or None))
            guard(group["gid"])
            if key != "items":
                raise ToolError(f"{entry['iid']} 是默写，请用 dictation_update")
            changed = [k for k in ITEM_PROPS if k in args]
            if not changed:
                raise ToolError("没有要改的字段")
            merged = dict(entry, **{k: args[k] for k in changed})
            if "answer" in changed and "answer_origin" not in changed:
                merged["answer_origin"] = "ai"
            group["items"][group["items"].index(entry)] = normalize_item(merged, entry["iid"])
            no = entry["no"]
        ws.changed()
        return ok(f"已改 {entry['iid']}（第{no or '?'}题）：{_changes_text(args, changed)}",
                  f"第 {no or '?'} 题 · {_changes_text(args, changed)}")

    def item_delete(args, ctx):
        with ws.lock:
            group, key, entry = ws.find(args["ref"], args.get("gid") or (scope or None))
            guard(group["gid"])
            group[key].remove(entry)
        ws.changed()
        return ok(f"已删除 {entry['iid']}")

    # ── 默写 ──
    def dictation_add(args, ctx):
        raw = args.get("entries") or []
        if not isinstance(raw, list) or not raw:
            raise ToolError("entries 至少要有一条")
        with ws.lock:
            group = ws.group(args["gid"]) if args.get("gid") else (
                ws.group(scope) if scope else ws.dictation_group())
            guard(group["gid"])
            if group["genre"] != "dictation":
                raise ToolError(f"{group['gid']} 不是名句默写板块")
            added = []
            for entry in raw:                       # 逐条追加：new_iid 要看到前一条，编号才不重复
                added.append(normalize_dictation(entry if isinstance(entry, dict) else {}, ws.new_iid("d")))
                group["dictation"].append(added[-1])
            gid = group["gid"]
        ws.changed()
        return ok(f"已在 {gid} 添加 {len(added)} 条默写：" + "、".join(e["iid"] for e in added),
                  f"添加 {len(added)} 条默写", gid=gid)

    def dictation_update(args, ctx):
        with ws.lock:
            group, key, entry = ws.find(args["ref"], args.get("gid") or (scope or None))
            guard(group["gid"])
            if key != "dictation":
                raise ToolError(f"{entry['iid']} 是阅读小题，请用 item_update")
            changed = [k for k in DICT_PROPS if k in args]
            if not changed:
                raise ToolError("没有要改的字段")
            merged = dict(entry, **{k: args[k] for k in changed})
            group["dictation"][group["dictation"].index(entry)] = normalize_dictation(merged, entry["iid"])
        ws.changed()
        return ok(f"已改默写 {entry['iid']}：{_changes_text(args, changed)}",
                  f"默写 {entry.get('source') or entry['iid']} · {_changes_text(args, changed)}", gid=group["gid"])

    def view_pages(args, ctx):
        pages = sorted({int(p) for p in args.get("pages") or [] if str(p).lstrip("-").isdigit()})
        bad = [p for p in pages if not 1 <= p <= len(ws.pages)]
        if not pages or bad:
            raise ToolError(f"页码要在 1–{len(ws.pages)} 之间" if ws.pages else "这段对话没有图片")
        return ToolResult(f"第 {'、'.join(map(str, pages))} 页已附在下一条消息里。",
                          {"summary": f"查看第 {'、'.join(map(str, pages))} 页"}, images=[{"page": p} for p in pages])

    gid_prop = {"gid": {"type": "string", "description": "板块编号，如 g1" + ("（可省略，默认你负责的板块）" if scope else "")}}
    ref_prop = {"ref": {"type": "string", "description": "题目：iid（i3、d2）或题号（7）"}}
    need = [] if scope else ["gid"]
    tools = [
        Tool("draft_view", "查看草稿。不给 gid 时返回大纲、待补问题和去重情况；给 gid 返回这个板块的完整内容。",
             {"type": "object", "properties": dict(gid_prop)}, draft_view,
             lambda a: f"查看{' ' + a['gid'] if a.get('gid') else '草稿'}"),
        Tool("material_set", "设置阅读材料（标题 / 作者 / 出处 / 原文），只传要改的字段。原文很长时可以分几次，"
             "后几次设 append=true 接在后面。",
             {"type": "object", "properties": dict(gid_prop, **MAT_PROPS, append={"type": "boolean"}),
              "required": need}, material_set,
             lambda a: f"{title_of(a.get('gid') or scope)} · {_changes_text(a, MATERIAL_FIELDS)}"),
        Tool("items_add", "往阅读板块里添加小题（可一次多道，按试卷顺序）。",
             {"type": "object", "properties": dict(gid_prop, items={"type": "array", "items": {
                 "type": "object", "properties": ITEM_PROPS, "required": ["no", "stem"]}}),
              "required": need + ["items"]}, items_add,
             lambda a: f"{title_of(a.get('gid') or scope)} 添加 {len(a.get('items') or [])} 题"),
        Tool("item_update", "修改一道阅读小题的任意字段，只传要改的字段；改答案时默认记为 AI 改写。",
             {"type": "object", "properties": dict(ref_prop, **gid_prop, **ITEM_PROPS), "required": ["ref"]},
             item_update, lambda a: f"{a.get('ref')} · {_changes_text(a, ITEM_PROPS)}"),
        Tool("item_delete", "删除一道小题或一条默写。",
             {"type": "object", "properties": dict(ref_prop, **gid_prop), "required": ["ref"]},
             item_delete, lambda a: f"删除 {a.get('ref')}"),
        Tool("dictation_add", "添加名句默写（每条一个模板 + 答案表；入库时每个空是一道题）。不给 gid 时放进名句默写板块，没有就新建。",
             {"type": "object", "properties": dict(gid_prop, entries={"type": "array", "items": {
                 "type": "object", "properties": DICT_PROPS, "required": ["template", "blanks"]}}),
              "required": ["entries"]}, dictation_add, lambda a: f"添加 {len(a.get('entries') or [])} 条默写"),
        Tool("dictation_update", "修改一条默写（模板 / 答案表 / 出处 / 类型），只传要改的字段。",
             {"type": "object", "properties": dict(ref_prop, **gid_prop, **DICT_PROPS), "required": ["ref"]},
             dictation_update, lambda a: f"默写 {a.get('ref')} · {_changes_text(a, DICT_PROPS)}"),
    ]
    if ws.pages:
        tools.append(Tool("view_pages", f"重新查看原图（共 {len(ws.pages)} 页，页码从 1 开始）。",
                          {"type": "object", "properties": {"pages": {"type": "array", "items": {"type": "integer"}}},
                           "required": ["pages"]}, view_pages,
                          lambda a: f"查看第 {'、'.join(map(str, a.get('pages') or []))} 页"))
    if structure and not scope:
        tools[1:1] = [
            Tool("group_add", "新建一个板块：一篇阅读材料一个板块；名句默写整份只要一个板块。",
                 {"type": "object", "properties": dict(genre={"type": "string", "enum": [
                     "现代文阅读", "文言文阅读", "古代诗歌阅读", "名句默写"]}, **MAT_PROPS), "required": ["genre"]},
                 group_add, lambda a: f"新建板块 {a.get('genre', '')}{'《' + a['title'] + '》' if a.get('title') else ''}"),
            Tool("group_delete", "删除整个板块。",
                 {"type": "object", "properties": dict(gid_prop), "required": ["gid"]}, group_delete,
                 lambda a: f"删除板块 {a.get('gid')}"),
        ]
    return tools
