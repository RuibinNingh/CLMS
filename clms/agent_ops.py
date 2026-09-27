"""Agent 的题库 / 记录 / 复习反馈工具。全部是对现有后端函数的薄包装，写入一律经 Ledger 追加提交。

- 题库（查改删、停用、撤销删除）：library.py、creation.update_item / update_material。「增」走草稿入库（draft_commit）。
- 记录（复习记录的增删改查、恢复）：records.py。
- 复习反馈（看作答照片批改，一次写多题评分）：sessions.list_sessions / view / grade_many。
"""

import json

from . import creation, library, records, sessions
from .harness import Tool, ToolResult
from .taxonomy import GENRE_BY_CODE

GRADE_HELP = "阅读题 0=不会 1=部分 2=基本 3=完整；默写 0=不会 1=有错字 3=全对"
EDIT_PROPS = {
    "no": {"type": "string"}, "qtype": {"type": "string"}, "stem": {"type": "string"},
    "answer": {"type": "string"}, "analysis": {"type": "string"}, "score": {"type": "number"},
    "blank_lines": {"type": "integer"}, "user_answer": {"type": "string"}, "note": {"type": "string", "description": "错因"},
    "source": {"type": "string", "description": "默写出处"},
}


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _brief(row: dict) -> dict:
    sched = row.get("sched") or {}
    return {"id": row["id"], "genre": GENRE_BY_CODE.get(row["genre"], {}).get("short", row["genre"]),
            "qtype": row.get("qtype", ""), "no": row.get("no", ""), "material": row.get("material_title", ""),
            "source": row.get("source", ""), "stem": (row.get("stem") or "")[:60], "answer": (row.get("answer") or "")[:40],
            "status": "已删除" if row.get("deleted") else sched.get("status"), "leech": sched.get("leech"),
            "mastery": sched.get("decayed"), "due": sched.get("due"), "suspended": row.get("suspended")}


def _record_brief(r: dict) -> dict:
    return {k: r.get(k) for k in ("commit_id", "item_id", "item_name", "session_id", "grade", "grade_label", "note",
                                  "at", "voided", "restored_from", "replaces")}


def library_tools(vault: str) -> list:
    def search(args, ctx):
        data = library.list_items(vault, args.get("genre") or "", args.get("qtype") or "", args.get("status") or "",
                                  args.get("query") or "", args.get("sort") or "priority", include_suspended=True)
        limit = max(1, min(50, int(args.get("limit") or 20)))
        rows = [_brief(r) for r in data["items"][:limit]]
        return ToolResult(_dump({"total": data["total"], "items": rows}), {"summary": f"找到 {data['total']} 题"})

    def get(args, ctx):
        d = library.item_detail(vault, args["item_id"])
        mat = d.get("material") or {}
        out = {k: d.get(k) for k in ("id", "genre", "qtype", "no", "stem", "answer", "answer_origin", "analysis", "score",
                                     "blank_lines", "user_answer", "note", "source", "suspended", "deleted", "encounters")}
        out["sched"] = {k: d["sched"].get(k) for k in ("status", "decayed", "due", "reviews", "leech")}
        if mat:
            out["material"] = {"id": mat["id"], "title": mat["title"], "author": mat["author"],
                               "text": mat["text"][:800] + ("…" if len(mat["text"]) > 800 else "")}
        out["records"] = [_record_brief(r) for r in d.get("records", [])[:20]]
        return ToolResult(_dump(out), {"summary": f"{d['id']} {d.get('qtype') or ''}"})

    def update(args, ctx):
        changes = {k: args[k] for k in EDIT_PROPS if k in args}
        creation.update_item(vault, args["item_id"], changes)
        return ToolResult(f"已修改 {args['item_id']}：" + "、".join(changes), {"summary": f"{args['item_id']} 已修改"})

    def mat_update(args, ctx):
        changes = {k: args[k] for k in ("title", "author", "source", "text") if k in args}
        creation.update_material(vault, args["material_id"], changes)
        return ToolResult(f"已修改材料 {args['material_id']}", {"summary": f"{args['material_id']} 已修改"})

    def suspend(args, ctx):
        library.set_suspended(vault, args["item_id"], bool(args.get("suspended", True)))
        word = "停用" if args.get("suspended", True) else "恢复复习"
        return ToolResult(f"{args['item_id']} 已{word}", {"summary": f"{args['item_id']} 已{word}"})

    def delete(args, ctx):
        library.delete(vault, args["item_id"])
        return ToolResult(f"{args['item_id']} 已删除（可以用 library_restore 撤销）", {"summary": f"{args['item_id']} 已删除"})

    def restore(args, ctx):
        library.restore(vault, args["item_id"])
        return ToolResult(f"{args['item_id']} 已恢复", {"summary": f"{args['item_id']} 已恢复"})

    item = {"item_id": {"type": "string", "description": "题库编号，如 Q-000012"}}
    return [
        Tool("library_search", "在题库里查题：关键词搜题干 / 答案 / 篇名 / 出处，可按板块、题型、状态筛选。",
             {"type": "object", "properties": {
                 "query": {"type": "string"}, "genre": {"type": "string", "enum": list(GENRE_BY_CODE)},
                 "qtype": {"type": "string"},
                 "status": {"type": "string", "enum": ["新录入", "巩固中", "待攻克", "已掌握", "leech", "deleted"]},
                 "sort": {"type": "string", "enum": ["priority", "due", "mastery", "created"]},
                 "limit": {"type": "integer"}}}, search, lambda a: f"查题库{' · ' + a['query'] if a.get('query') else ''}"),
        Tool("library_get", "看一道题的完整内容、记忆状态、所属材料和复习记录。",
             {"type": "object", "properties": item, "required": ["item_id"]}, get, lambda a: f"查看 {a.get('item_id')}"),
        Tool("library_update", "修改题库里的一道题（只传要改的字段）。改题干或默写答案后若和别的题重复会被拒绝。",
             {"type": "object", "properties": dict(item, **EDIT_PROPS), "required": ["item_id"]}, update,
             lambda a: f"改 {a.get('item_id')}"),
        Tool("material_update", "修改题库里的一篇阅读材料（标题 / 作者 / 出处 / 原文）。",
             {"type": "object", "properties": {"material_id": {"type": "string"}, "title": {"type": "string"},
                                               "author": {"type": "string"}, "source": {"type": "string"},
                                               "text": {"type": "string"}}, "required": ["material_id"]},
             mat_update, lambda a: f"改材料 {a.get('material_id')}"),
        Tool("library_suspend", "停用（不再安排复习）或恢复一道题。",
             {"type": "object", "properties": dict(item, suspended={"type": "boolean"}), "required": ["item_id"]},
             suspend, lambda a: f"{'停用' if a.get('suspended', True) else '恢复'} {a.get('item_id')}"),
        Tool("library_delete", "删除一道题（追加提交，可撤销）。只在用户明确要求时使用。",
             {"type": "object", "properties": item, "required": ["item_id"]}, delete, lambda a: f"删除 {a.get('item_id')}"),
        Tool("library_restore", "撤销删除，把已删除的题恢复到题库。",
             {"type": "object", "properties": item, "required": ["item_id"]}, restore, lambda a: f"恢复 {a.get('item_id')}"),
    ]


def record_tools(vault: str) -> list:
    def listing(args, ctx):
        data = records.list_records(vault, args.get("item_id") or "", args.get("session_id") or "",
                                    args.get("include_voided", True), args.get("limit") or 30)
        return ToolResult(_dump({"total": data["total"], "records": [_record_brief(r) for r in data["records"]]}),
                          {"summary": f"{data['total']} 条记录"})

    def add(args, ctx):
        r = records.add(vault, args["item_id"], args["grade"], args.get("note") or "", args.get("date") or "",
                        args.get("session_id") or "")
        return ToolResult(_dump(_record_brief(r)), {"summary": f"{r['item_name']} · {r['grade_label']}"})

    def update(args, ctx):
        r = records.update(vault, args["commit_id"], args.get("grade"), args.get("note"))
        return ToolResult(_dump(_record_brief(r)), {"summary": f"{r['item_name']} · {r['grade_label']}"})

    def delete(args, ctx):
        r = records.delete(vault, args["commit_id"])
        return ToolResult(f"已作废 {args['commit_id']}（{r['item_name']}）；可用 record_restore 恢复",
                          {"summary": f"作废 {r['item_name']} 的记录"})

    def restore(args, ctx):
        r = records.restore(vault, args["commit_id"])
        return ToolResult(_dump(_record_brief(r)), {"summary": f"恢复 {r['item_name']} 的记录"})

    cid = {"commit_id": {"type": "string", "description": "记录编号（提交号），如 C-000031"}}
    grade = {"type": "integer", "description": GRADE_HELP}
    return [
        Tool("records_list", "查复习记录（每条是一次评分）：可按题或按复习筛选，默认含已作废的。",
             {"type": "object", "properties": {"item_id": {"type": "string"}, "session_id": {"type": "string"},
                                               "include_voided": {"type": "boolean"}, "limit": {"type": "integer"}}},
             listing, lambda a: "查复习记录"),
        Tool("record_add", "补记一条复习记录（不在某次复习里做的，也可以记）。date 形如 2026-09-20，默认今天。",
             {"type": "object", "properties": {"item_id": {"type": "string"}, "grade": grade, "note": {"type": "string"},
                                               "date": {"type": "string"}, "session_id": {"type": "string"}},
              "required": ["item_id", "grade"]}, add, lambda a: f"补记 {a.get('item_id')}"),
        Tool("record_update", "修改一条复习记录的评分或反馈（旧记录作废、写一条新的）。",
             {"type": "object", "properties": dict(cid, grade=grade, note={"type": "string"}), "required": ["commit_id"]},
             update, lambda a: f"改记录 {a.get('commit_id')}"),
        Tool("record_delete", "作废一条复习记录（可恢复）。",
             {"type": "object", "properties": cid, "required": ["commit_id"]}, delete,
             lambda a: f"作废记录 {a.get('commit_id')}"),
        Tool("record_restore", "恢复一条已作废的复习记录。",
             {"type": "object", "properties": cid, "required": ["commit_id"]}, restore,
             lambda a: f"恢复记录 {a.get('commit_id')}"),
    ]


def review_tools(vault: str) -> list:
    def listing(args, ctx):
        rows = [{k: s[k] for k in ("id", "planned_for", "title", "progress")} for s in sessions.list_sessions(vault)[:20]]
        return ToolResult(_dump(rows), {"summary": f"{len(rows)} 次复习"})

    def get(args, ctx):
        data = sessions.view(vault, args["session_id"])
        items = []
        for n, it in enumerate(data["items"], 1):
            items.append({"n": n, "item_id": it["id"], "genre": it["genre"], "no": it.get("no", ""),
                          "qtype": it.get("qtype", ""), "material": it.get("material_title", ""),
                          "stem": it["stem"], "answer": it["answer"], "score": it.get("score"),
                          "grade": (it.get("grade") or {}).get("grade"), "note": (it.get("grade") or {}).get("note", "")})
        out = {"id": data["id"], "planned_for": data["planned_for"], "progress": data["progress"], "items": items,
               "grades": GRADE_HELP}
        return ToolResult(_dump(out), {"summary": f"{data['id']} 共 {len(items)} 题"})

    def grade(args, ctx):
        result = sessions.grade_many(vault, args["session_id"], args.get("grades") or [])
        p = result["session"]["progress"]
        return ToolResult(f"已写入 {result['graded']} 题评分；这次复习评了 {p['done']}/{p['total']}",
                          {"summary": f"评分 {result['graded']} 题（{p['done']}/{p['total']}）"})

    sid = {"session_id": {"type": "string", "description": "复习编号，如 S-0003"}}
    return [
        Tool("sessions_list", "列出最近的复习（编号、日期、评分进度）。", {"type": "object", "properties": {}},
             listing, lambda a: "查复习列表"),
        Tool("session_get", "看一次复习的全部题目：题干、参考答案、当前评分（n 是卷面上的题序）。",
             {"type": "object", "properties": sid, "required": ["session_id"]}, get,
             lambda a: f"查看复习 {a.get('session_id')}"),
        Tool("review_grade", "记录复习反馈：一次写入多道题的评分和简短反馈（note：错在哪、漏了哪个采分点）。"
             "已评过的题会被改评。评分标准：" + GRADE_HELP,
             {"type": "object", "properties": dict(sid, grades={"type": "array", "items": {
                 "type": "object", "properties": {"item_id": {"type": "string"}, "grade": {"type": "integer"},
                                                  "note": {"type": "string"}}, "required": ["item_id", "grade"]}}),
              "required": ["session_id", "grades"]}, grade,
             lambda a: f"批改 {a.get('session_id')} · {len(a.get('grades') or [])} 题"),
    ]
