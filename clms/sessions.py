"""复习（对标 OMRS sessions.py + feedback.py）：按时间预算排一次复习 → 纸上或屏幕上做 → 逐题自评。

评分写 review.grade；撤销写 review.void（只追加，不改旧提交）。复习是否完成由评分数量推出，不单独存状态。
"""

import datetime

from . import ledger
from .common import load_config
from .projections import context, get_state
from .scheduling import DICTATION_GRADES, GRADES, NEVER, next_review_day, plan_session
from .taxonomy import GENRE_BY_CODE, GENRE_ORDER, MATERIAL_MINUTES, item_minutes


def plan(vault: str, minutes=None, genres=None, fill=True, qtypes=None, pinned=None, exclude=None) -> dict:
    """推荐一次复习（不写 Ledger）。pinned = 用户自选必排的题，exclude = 用户从推荐里移掉的题；
    已在未完成复习里的题不重复推荐。参数与规则见 AI/algorithm.md「排复习」。"""
    ctx = context(vault)
    state = get_state(vault)
    horizon = next_review_day(ctx["today"], ctx["weekdays"])
    minutes = minutes or load_config(vault).get("session_minutes") or 40
    items = state.all_items(ctx)
    result = plan_session(items, float(minutes), ctx["today"], horizon, genres=genres or None, fill=bool(fill),
                          qtypes=qtypes or None, pinned=pinned, exclude=exclude, busy=open_item_ids(state),
                          t=ctx["tuning"])
    index = {it["id"]: it for it in items}
    result["items"] = [dict(entry, item=brief(index[entry["id"]])) for entry in result["items"]]
    result["horizon"] = horizon.isoformat()
    return result


def open_item_ids(state) -> set:
    """还在未完成复习里、没评分的题（排复习时不重复推荐）。"""
    out = set()
    for sess in state.sessions.values():
        if sess["cancelled"]:
            continue
        out.update(e["id"] for e in sess["items"] if e["id"] not in sess["grades"])
    return out


def brief(item) -> dict:
    """排复习 / 挑题用的精简行：够显示、够估时。"""
    sched = item["sched"]
    return {"id": item["id"], "genre": item["genre"], "qtype": item.get("qtype", ""), "no": item.get("no", ""),
            "stem": item["stem"][:80], "material_id": item.get("material_id"), "source": item.get("source", ""),
            "material_title": item.get("material_title", ""), "status": sched["status"], "kind": sched["kind"],
            "mastery": sched["mastery"], "decayed": sched["decayed"], "due": sched["due"],
            "last_review": sched["last_review"] if sched["reviews"] else "", "last_grade": sched["last_grade"],
            "reviews": sched["reviews"], "leech": sched["leech"], "created_at": item.get("created_at", ""),
            "minutes": item_minutes(item["genre"], item.get("qtype", "")),
            "material_minutes": MATERIAL_MINUTES.get(item["genre"], 0.0) if item.get("material_id") else 0.0}


def create(vault: str, item_ids: list, minutes=0, title="") -> dict:
    state = get_state(vault)
    ids = [i for i in dict.fromkeys(item_ids or []) if i in state.items]
    if not ids:
        raise ValueError("没有选中任何题目")
    ctx = context(vault)
    planned = next_review_day(ctx["today"], ctx["weekdays"]).isoformat()

    def build(tx):
        session_id = tx.next_id("S", 4)
        tx.append("review", "session.create", f"安排复习 {len(ids)} 题", {
            "session_id": session_id, "items": [{"id": i} for i in ids], "minutes": minutes,
            "planned_for": planned, "title": title or ""})
        return session_id

    session_id, _ = ledger.transact(vault, build)
    return view(vault, session_id)


def _progress(sess) -> dict:
    total = len(sess["items"])
    done = sum(1 for entry in sess["items"] if entry["id"] in sess["grades"])
    return {"total": total, "done": done, "complete": total > 0 and done >= total}


def list_sessions(vault: str) -> list:
    state = get_state(vault)
    out = []
    for sess in state.sessions.values():
        if sess["cancelled"]:
            continue
        genres = [state.items[e["id"]]["genre"] for e in sess["items"] if e["id"] in state.items]
        out.append({"id": sess["id"], "created_at": sess["created_at"], "planned_for": sess["planned_for"],
                    "minutes": sess["minutes"], "title": sess["title"], "progress": _progress(sess),
                    "genres": sorted(set(genres), key=GENRE_ORDER.index)})
    out.sort(key=lambda s: s["created_at"], reverse=True)
    return out


def view(vault: str, session_id: str) -> dict:
    state = get_state(vault)
    sess = state.sessions.get(session_id)
    if not sess or sess["cancelled"]:
        raise KeyError("找不到这次复习：" + session_id)
    ctx = context(vault)
    items, materials = [], {}
    for entry in sess["items"]:
        item = state.item_view(entry["id"], ctx)
        if not item:
            continue
        item["grade"] = sess["grades"].get(item["id"])
        items.append(item)
        mid = item.get("material_id")
        if mid and mid not in materials and mid in state.materials:
            mat = state.materials[mid]
            materials[mid] = {k: mat.get(k, "") for k in ("id", "genre", "title", "author", "source", "text")}
    return {"id": sess["id"], "created_at": sess["created_at"], "planned_for": sess["planned_for"],
            "minutes": sess["minutes"], "title": sess["title"], "progress": _progress(sess),
            "items": items, "materials": materials}


def describe(state, item_id: str) -> str:
    """提交说明里用的人话名称：《老街的灯》第 7 题 / 默写「疑是地上霜」。"""
    item = state.items.get(item_id)
    if not item:
        return item_id
    if item["genre"] == "dictation":
        return f"默写「{item['answer'][:12]}」"
    title = state.materials.get(item.get("material_id") or "", {}).get("title")
    head = f"《{title}》" if title else ""
    return head + (f"第 {item['no']} 题" if item.get("no") else (item.get("qtype") or item_id))


def grade_label(genre: str, value: int) -> str:
    return (DICTATION_GRADES if genre == "dictation" else GRADES).get(value, str(value))


def grade(vault: str, session_id: str, item_id: str, grade_value: int, note: str = "") -> dict:
    state = get_state(vault)
    sess = state.sessions.get(session_id)
    if not sess or sess["cancelled"]:
        raise KeyError("找不到这次复习")
    if item_id not in {e["id"] for e in sess["items"]}:
        raise ValueError("这道题不在本次复习里")
    grade_value = int(grade_value)
    if grade_value not in (0, 1, 2, 3):
        raise ValueError("评分只能是 0–3")
    previous = sess["grades"].get(item_id)
    name = describe(state, item_id)
    label = grade_label(state.items[item_id]["genre"], grade_value)

    def build(tx):
        if previous:        # 改评分 = 作废旧评分 + 新评分，两条都留在链上
            tx.append("review", "review.void", f"改评分 {name}", {"commit_id": previous["commit_id"]})
        return tx.append("review", "review.grade", f"{name} · {label}", {
            "session_id": session_id, "item_id": item_id, "grade": grade_value, "note": note or ""})

    commit, _ = ledger.transact(vault, build)
    return {"commit_id": commit["commit_id"], "session": view(vault, session_id)}


def grade_many(vault: str, session_id: str, grades: list) -> dict:
    """一次写入多道题的评分（AI 批改用）：同一个事务，要么全部成功，要么全部失败。
    grades = [{item_id, grade, note}]；已评过的题先 void 再评。"""
    from .records import check_grade
    state = get_state(vault)
    sess = state.sessions.get(session_id)
    if not sess or sess["cancelled"]:
        raise KeyError("找不到这次复习：" + str(session_id))
    members = {e["id"] for e in sess["items"]}
    rows, seen = [], set()
    for g in grades or []:
        item_id = str((g or {}).get("item_id") or "")
        if item_id not in members:
            raise ValueError(f"{item_id or '（空）'} 不在这次复习里")
        if item_id in seen:
            raise ValueError(f"{item_id} 重复出现")
        seen.add(item_id)
        value = check_grade(state.items[item_id]["genre"], g.get("grade"))
        rows.append((item_id, value, str(g.get("note") or "")))
    if not rows:
        raise ValueError("没有要写入的评分")

    def build(tx):
        for item_id, value, note in rows:
            previous = sess["grades"].get(item_id)
            name = describe(state, item_id)
            if previous:
                tx.append("review", "review.void", f"改评分 {name}", {"commit_id": previous["commit_id"]})
            tx.append("review", "review.grade", f"{name} · {grade_label(state.items[item_id]['genre'], value)}", {
                "session_id": session_id, "item_id": item_id, "grade": value, "note": note})
        return len(rows)

    count, _ = ledger.transact(vault, build)
    return {"graded": count, "session": view(vault, session_id)}


def void_grade(vault: str, session_id: str, item_id: str) -> dict:
    state = get_state(vault)
    sess = state.sessions.get(session_id)
    previous = (sess or {}).get("grades", {}).get(item_id)
    if not previous:
        raise ValueError("这道题还没有评分")
    ledger.append_commit(vault, "review", "review.void", f"撤销评分 {describe(state, item_id)}",
                         {"commit_id": previous["commit_id"]})
    return view(vault, session_id)


def cancel(vault: str, session_id: str) -> dict:
    state = get_state(vault)
    sess = state.sessions.get(session_id)
    if not sess or sess["cancelled"]:
        raise KeyError("找不到这次复习")
    for item_id, g in list(sess["grades"].items()):
        ledger.append_commit(vault, "review", "review.void", f"随复习删除撤销 {item_id}", {"commit_id": g["commit_id"]})
    ledger.append_commit(vault, "review", "session.cancel", f"删除复习 {session_id}", {"session_id": session_id})
    return {"id": session_id, "cancelled": True}


def summary(vault: str) -> dict:
    """仪表盘：下次复习日、到期量、板块 / 题型掌握度、最近活动。"""
    ctx = context(vault)
    state = get_state(vault)
    items = [it for it in state.all_items(ctx) if not it.get("suspended")]
    horizon = next_review_day(ctx["today"], ctx["weekdays"])
    due = [it for it in items if it["sched"]["due"] <= horizon.isoformat()]
    by_genre, by_qtype = {}, {}
    for it in items:
        g = by_genre.setdefault(it["genre"], {"total": 0, "due": 0, "mastered": 0, "mastery_sum": 0.0, "leech": 0})
        g["total"] += 1
        g["mastery_sum"] += it["sched"]["decayed"]
        g["due"] += it["sched"]["due"] <= horizon.isoformat()
        g["mastered"] += it["sched"]["status"] == "已掌握"
        g["leech"] += bool(it["sched"]["leech"])
        if it["genre"] != "dictation" and it.get("qtype"):
            q = by_qtype.setdefault((it["genre"], it["qtype"]), {"total": 0, "mastery_sum": 0.0, "wrong": 0})
            q["total"] += 1
            q["mastery_sum"] += it["sched"]["decayed"]
            q["wrong"] += it["encounters"] - 1 + sum(1 for x in it["sched"]["grades"] if x <= 1)
    genres = []
    for code in GENRE_ORDER:
        g = by_genre.get(code)
        if g:
            genres.append({"code": code, "name": GENRE_BY_CODE[code]["name"], "total": g["total"], "due": g["due"],
                           "mastered": g["mastered"], "leech": g["leech"],
                           "mastery": round(g["mastery_sum"] / g["total"], 3)})
    qtypes = sorted(({"genre": k[0], "qtype": k[1], "total": v["total"], "wrong": v["wrong"],
                      "mastery": round(v["mastery_sum"] / v["total"], 3)} for k, v in by_qtype.items()),
                    key=lambda q: (q["mastery"], -q["total"]))
    mats = {(it["genre"], it["material_id"]) for it in due if it.get("material_id")}
    minutes = sum(item_minutes(it["genre"], it.get("qtype", "")) for it in due) \
        + sum(MATERIAL_MINUTES.get(genre, 0) for genre, _ in mats)
    upcoming = None
    scheduled = [it for it in items if it["sched"]["due"] != NEVER]
    if not due and scheduled:
        first = min(it["sched"]["due"] for it in scheduled)
        upcoming = {"date": first, "count": sum(1 for it in scheduled if it["sched"]["due"] <= first)}
    week_ago = (ctx["today"] - datetime.timedelta(days=6)).isoformat()
    reviewed_week = sum(1 for it in state.items.values() for e in it["events"]
                        if e["kind"] == "review" and (e["at"] or "")[:10] >= week_ago)
    return {
        "today": ctx["today"].isoformat(), "next_review": horizon.isoformat(),
        "is_review_day": horizon == ctx["today"], "weekdays": ctx["weekdays"],
        "total": len(items), "due": len(due), "due_minutes": round(minutes), "upcoming": upcoming,
        "leech": sum(1 for it in items if it["sched"]["leech"]),
        "new": sum(1 for it in items if it["sched"]["status"] == "新录入"),
        "genres": genres, "qtypes": qtypes[:12], "reviewed_week": reviewed_week,
        "open_sessions": [s for s in list_sessions(vault) if not s["progress"]["complete"]][:3],
        "materials": len(state.materials),
    }
