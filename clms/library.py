"""题库查询与维护：列表筛选、详情、停用 / 恢复、删除与撤销删除（都是追加提交，Ledger 里仍可审计）。

「增」走录入草稿（草稿 → entry.commit，见 drafts.py / creation.py），题库这里只查、改、停用、删、恢复。
"""

from . import ledger
from .common import chinese_only
from .projections import context, get_state
from .taxonomy import GENRE_ORDER

SORTS = {
    "priority": lambda it: -it["sched"]["priority"],
    "due": lambda it: it["sched"]["due"],
    "mastery": lambda it: it["sched"]["decayed"],
}


def list_items(vault: str, genre="", qtype="", status="", q="", sort="priority", include_suspended=False) -> dict:
    ctx = context(vault)
    state = get_state(vault)
    needle = chinese_only(q) or (q or "").strip()
    out = []
    source = ([state.item_view(i, ctx) for i in state.deleted] if status == "deleted" else state.all_items(ctx))
    if status == "deleted":
        status, include_suspended = "", True
    for item in source:
        if item.get("suspended") and not include_suspended:
            continue
        if genre and item["genre"] != genre:
            continue
        if qtype and item.get("qtype") != qtype:
            continue
        if status == "leech" and not item["sched"]["leech"]:
            continue
        if status and status != "leech" and item["sched"]["status"] != status:
            continue
        if needle:
            mat = state.materials.get(item.get("material_id") or "", {})
            hay = " ".join([item["stem"], item["answer"], item.get("source", ""), mat.get("title", ""),
                            mat.get("author", ""), item.get("qtype", "")])
            if needle not in hay and needle not in chinese_only(hay):
                continue
        out.append(_row(item))
    if sort == "created":
        out.sort(key=lambda it: it.get("created_at") or "", reverse=True)
    else:
        out.sort(key=SORTS.get(sort, SORTS["priority"]))
    counts = {code: 0 for code in GENRE_ORDER}
    for item in state.items.values():
        if not item.get("suspended"):
            counts[item["genre"]] = counts.get(item["genre"], 0) + 1
    return {"items": out, "total": len(out), "counts": counts, "deleted": len(state.deleted)}


def _row(item) -> dict:
    keep = ("id", "genre", "qtype", "no", "stem", "answer", "material_id", "material_title", "source",
            "suspended", "created_at", "sched", "encounters", "blank_lines", "score", "deleted", "deleted_at")
    return {k: item.get(k) for k in keep}


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
