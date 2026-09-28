"""题库查询与维护：列表筛选、详情、停用 / 恢复、删除与撤销删除（都是追加提交，Ledger 里仍可审计）。

「增」走录入草稿（草稿 → entry.commit，见 drafts.py / creation.py），题库这里只查、改、停用、删、恢复。
"""

from . import ledger
from .common import chinese_only, parse_date
from .projections import context, get_state
from .taxonomy import GENRE_ORDER

SORTS = {
    "priority": lambda it: -it["sched"]["priority"],
    "due": lambda it: it["sched"]["due"],
    "mastery": lambda it: it["sched"]["decayed"],
    "wrong": lambda it: (-_wrong(it), -it["sched"]["priority"]),
}
STATUSES = ("新录入", "待攻克", "巩固中", "已掌握")
ADDED_BUCKETS = (7, 30, 90)            # 添加时间：近 7 / 30 / 90 天，更早 = old
LAST_BUCKETS = (7, 30)                 # 最近练习：近 7 / 30 天，更早 = old，从没做过 = never
FACETS = ("genre", "status", "qtype", "kind", "added", "last", "grade")


def _wrong(it) -> int:
    """出错次数：又录入的次数 + 最近 8 次评分里「不会 / 部分 / 有错字」的次数。"""
    return it.get("encounters", 1) - 1 + sum(1 for g in it["sched"]["grades"] if g <= 1)


def _days(today, iso) -> int:
    day = parse_date(iso)
    return (today - day).days if day else 0


def _facet_values(it, today) -> dict:
    """每道题在各个筛选维度上落在哪些桶里（桶可以叠加：7 天内的题也在 30 天内）。"""
    sched = it["sched"]
    age = _days(today, it.get("created_at"))
    added = [str(n) for n in ADDED_BUCKETS if age <= n] or ["old"]
    if not sched["reviews"]:
        last = ["never"]
    else:
        ago = _days(today, sched["last_review"])
        last = [str(n) for n in LAST_BUCKETS if ago <= n] or ["old"]
    grade = sched.get("last_grade")
    status = ([sched["status"]] + (["leech"] if sched["leech"] else [])) if not it.get("suspended") else []
    if it.get("suspended"):
        status.append("suspended")
    return {"genre": [it["genre"]], "status": status, "qtype": [it.get("qtype") or ""], "kind": [sched["kind"]],
            "added": added, "last": last,
            "grade": ["none"] if grade is None else ["low"] if grade <= 1 else ["mid"] if grade == 2 else ["high"]}


def _haystack(state, item) -> str:
    mat = state.materials.get(item.get("material_id") or "", {})
    return " ".join([item["id"], item["stem"], item["answer"], item.get("source", ""), mat.get("title", ""),
                     mat.get("author", ""), mat.get("source", ""), item.get("qtype", ""), item.get("note", "")])


def list_items(vault: str, genre="", qtype="", status="", q="", sort="priority", include_suspended=False,
               kind="", added="", last="", grade="", material="", offset=0, limit=None, group="item") -> dict:
    """题库查询。筛选维度（都可叠加）：板块、题型、状态（含 leech / suspended / deleted）、记忆类型、
    添加时间（7/30/90/old）、最近练习（never/7/30/old）、上次评分（none/low/mid/high）、材料、关键词。

    facets：每个维度各桶的题数，按「除这个维度以外的其它筛选」计算（经典分面计数），前端据此显示数字。
    group = material 时按材料（默写按出处）分组，分页按组计；否则按题分页。limit 为空表示不分页。
    """
    ctx = context(vault)
    state = get_state(vault)
    today = ctx["today"]
    needle = chinese_only(q) or (q or "").strip()
    deleted = status == "deleted"
    source = [state.item_view(i, ctx) for i in state.deleted] if deleted else state.all_items(ctx)
    wanted = {"genre": genre, "qtype": qtype, "kind": kind, "added": added, "last": last, "grade": grade,
              "status": "" if deleted else status}
    show_suspended = include_suspended or deleted or status == "suspended"
    rows, facets = [], {name: {} for name in FACETS}
    for item in source:
        if item.get("suspended") and not show_suspended:
            continue
        if material and item.get("material_id") != material:
            continue
        if needle:
            hay = _haystack(state, item)
            if needle not in hay and needle not in chinese_only(hay) and needle.upper() not in hay:
                continue
        values = _facet_values(item, today)
        if deleted:
            values["status"] = []
        misses = [name for name, want in wanted.items() if want and want not in values[name]]
        for name in FACETS:
            if not misses or misses == [name]:
                for value in values[name]:
                    facets[name][value] = facets[name].get(value, 0) + 1
        if not misses:
            rows.append(item)
    if sort == "created":
        rows.sort(key=lambda it: it.get("created_at") or "", reverse=True)
    elif sort == "oldest":
        rows.sort(key=lambda it: it.get("created_at") or "")
    elif sort == "last":
        rows.sort(key=lambda it: it["sched"]["last_review"] if it["sched"]["reviews"] else "", reverse=True)
    else:
        rows.sort(key=SORTS.get(sort, SORTS["priority"]))
    offset = max(0, int(offset or 0))
    size = max(1, min(500, int(limit))) if limit else None
    out = {"total": len(rows), "offset": offset, "limit": size, "facets": facets,
           "counts": {code: facets["genre"].get(code, 0) for code in GENRE_ORDER},
           "deleted": len(state.deleted),
           "library_total": sum(1 for it in state.items.values() if not it.get("suspended"))}
    if group == "material":
        groups = _group(state, rows)
        out["total_groups"] = len(groups)
        out["groups"] = groups[offset:offset + size] if size else groups[offset:]
        out["items"] = []
    else:
        page = rows[offset:offset + size] if size else rows[offset:]
        out["items"] = [_row(it) for it in page]
    return out


def _group(state, rows) -> list:
    """按材料分组（默写按出处，其余单独成组）；组的顺序跟随组里排得最靠前的题。"""
    groups, index = [], {}
    for it in rows:
        mid = it.get("material_id")
        key = mid or ("src:" + it["source"] if it.get("source") else "item:" + it["id"])
        if key not in index:
            mat = state.materials.get(mid or "", {})
            index[key] = len(groups)
            groups.append({"key": key, "material_id": mid, "genre": it["genre"],
                           "title": mat.get("title") or (it.get("source") if not mid else "") or "",
                           "author": mat.get("author", ""), "source": mat.get("source", ""),
                           "created_at": mat.get("created_at") or it.get("created_at"),
                           "size": len([i for i in mat.get("item_ids", []) if i in state.items]) if mid else 0,
                           "items": []})
        groups[index[key]]["items"].append(_row(it))
    for g in groups:
        scheds = [r["sched"] for r in g["items"]]
        g["size"] = g["size"] or len(scheds)
        g["stats"] = {"total": len(scheds), "mastered": sum(1 for x in scheds if x["status"] == "已掌握"),
                      "new": sum(1 for x in scheds if x["status"] == "新录入"),
                      "leech": sum(1 for x in scheds if x["leech"]),
                      "mastery": round(sum(x["decayed"] for x in scheds) / len(scheds), 3)}
    return groups


def _row(item) -> dict:
    keep = ("id", "genre", "qtype", "no", "stem", "answer", "material_id", "material_title", "source",
            "suspended", "created_at", "sched", "encounters", "blank_lines", "score", "deleted", "deleted_at")
    row = {k: item.get(k) for k in keep}
    row["wrong"] = _wrong(item)
    return row


def item_detail(vault: str, item_id: str) -> dict:
    ctx = context(vault)
    state = get_state(vault)
    item = state.item_view(item_id, ctx)
    if not item:
        raise KeyError("找不到这道题：" + item_id)
    raw = state.items.get(item_id) or state.deleted[item_id]
    item["events"] = [{k: e.get(k) for k in ("kind", "grade", "at", "session_id", "commit_id", "note")}
                      for e in raw["events"]]
    from .records import list_records
    item["records"] = list_records(vault, item_id=item_id, limit=200)["records"]
    mat = state.materials.get(item.get("material_id") or "")
    item["material"] = None
    if mat:
        item["material"] = {k: mat.get(k) for k in ("id", "genre", "title", "author", "source", "text", "created_at")}
        item["siblings"] = [{"id": sid, "no": state.items[sid].get("no", ""), "qtype": state.items[sid].get("qtype", "")}
                            for sid in mat["item_ids"] if sid in state.items]
    return item


def material_detail(vault: str, material_id: str) -> dict:
    ctx = context(vault)
    state = get_state(vault)
    mat = state.materials.get(material_id)
    if not mat:
        raise KeyError("找不到这篇材料：" + material_id)
    out = {k: mat.get(k) for k in ("id", "genre", "title", "author", "source", "text", "created_at", "image")}
    out["items"] = [_row(state.item_view(i, ctx)) for i in mat["item_ids"] if i in state.items]
    return out


def set_suspended(vault: str, item_id: str, suspended: bool) -> dict:
    if item_id not in get_state(vault).items:
        raise KeyError("找不到这道题：" + item_id)
    from .sessions import describe
    name = describe(get_state(vault), item_id)
    return ledger.append_commit(vault, "library", "item.suspend", ("停用 " if suspended else "恢复 ") + name,
                                {"item_id": item_id, "suspended": bool(suspended)})


def delete(vault: str, item_id: str) -> dict:
    if item_id not in get_state(vault).items:
        raise KeyError("找不到这道题：" + item_id)
    from .sessions import describe
    return ledger.append_commit(vault, "library", "item.delete", "删除 " + describe(get_state(vault), item_id),
                                {"item_id": item_id})


def restore(vault: str, item_id: str) -> dict:
    """撤销删除：追加 item.restore。删除后又录入了同一道题（去重键被占）时拒绝。"""
    state = get_state(vault)
    item = state.deleted.get(item_id)
    if not item:
        raise KeyError("没有这道已删除的题：" + item_id)
    holder = state.keys.get(item.get("key") or "")
    if holder and holder != item_id and holder in state.items:
        raise ValueError(f"删除后又录入了同一道题（{holder}），不能恢复；可以直接用 {holder}")
    from .sessions import describe
    return ledger.append_commit(vault, "library", "item.restore", "恢复 " + describe(state, item_id), {"item_id": item_id})


def activity(vault: str, limit: int = 20) -> list:
    return [{"commit_id": c["commit_id"], "created_at": c["created_at"], "type": c["commit_type"],
             "message": c["message"]} for c in ledger.recent_commits(vault, limit)]
