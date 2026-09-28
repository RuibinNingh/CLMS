"""复习记录的增删改查（对标 OMRS 历史页的 review.replace / retract / restore，但全部落成 CLMS 已有的提交类型）。

一条「记录」就是一条 review.grade 提交。和 Ledger 的不变量一致，修正永远是追加：
- 增：review.grade（可以不属于任何复习，即「补记」；可指定当天以前的日期）。
- 删：review.void 作废它。
- 改：review.void 旧记录 + review.grade 新记录（同一复习、同一日期；payload.replaces 指回旧记录）。
- 恢复：给已作废的记录追加一条内容相同的 review.grade（payload.restored_from 指回它）；
  若它所在的复习里这道题已有别的有效评分，先把那条作废。
- 查：投影里的 state.reviews（含已作废），按题 / 复习 / 是否作废筛选。
"""

import datetime

from . import ledger
from .common import parse_date, today
from .projections import get_state
from .scheduling import DICTATION_GRADES, GRADES


def grade_label(genre: str, value: int) -> str:
    return (DICTATION_GRADES if genre == "dictation" else GRADES).get(value, str(value))


def check_grade(genre: str, value) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError("评分必须是整数")
    allowed = DICTATION_GRADES if genre == "dictation" else GRADES
    if value not in allowed:
        opts = "、".join(f"{k}={v}" for k, v in allowed.items())
        raise ValueError(f"{'默写' if genre == 'dictation' else '阅读题'}的评分只能是 {opts}")
    return value


def _item(state, item_id):
    item = state.items.get(item_id)
    if not item:
        raise KeyError("找不到这道题：" + str(item_id) + ("（已删除，先恢复）" if item_id in state.deleted else ""))
    return item


def _describe(state, item_id):
    from .sessions import describe
    return describe(state, item_id)


def view_record(state, record: dict) -> dict:
    item = state.items.get(record["item_id"]) or state.deleted.get(record["item_id"]) or {}
    genre = item.get("genre", "")
    title = state.materials.get(item.get("material_id") or "", {}).get("title", "")
    return dict(record, genre=genre, qtype=item.get("qtype", ""), material_title=title,
                item_name=_describe(state, record["item_id"]) if item else record["item_id"],
                grade_label=grade_label(genre, record["grade"]), voided=bool(record["voided_by"]),
                item_deleted=record["item_id"] in state.deleted)


def list_records(vault: str, item_id: str = "", session_id: str = "", include_voided: bool = True,
                 limit: int = 100, genre: str = "", grade: str = "", since: str = "", has_note: bool = False,
                 offset: int = 0) -> dict:
    """复习历史。grade：low（不会 / 部分 / 有错字）/ mid（基本）/ high（完整 / 全对）或具体分值；
    since：YYYY-MM-DD，只看这天及以后的；has_note：只看写了反馈的。按日期倒序，offset / limit 分页。"""
    state = get_state(vault)

    def genre_of(r):
        item = state.items.get(r["item_id"]) or state.deleted.get(r["item_id"]) or {}
        return item.get("genre", "")

    def grade_ok(value):
        if not grade:
            return True
        if grade in ("low", "mid", "high"):
            return {"low": value <= 1, "mid": value == 2, "high": value == 3}[grade]
        return str(value) == str(grade)

    rows = [r for r in state.reviews.values()
            if (not item_id or r["item_id"] == item_id) and (not session_id or r["session_id"] == session_id)
            and (include_voided or not r["voided_by"]) and grade_ok(r["grade"])
            and (not since or r["at"][:10] >= since) and (not has_note or (r.get("note") or "").strip())
            and (not genre or genre_of(r) == genre)]
    rows.sort(key=lambda r: (r["at"], r["created_at"], r["commit_id"]), reverse=True)
    limit = max(1, min(500, int(limit or 100)))
    offset = max(0, int(offset or 0))
    return {"records": [view_record(state, r) for r in rows[offset:offset + limit]], "total": len(rows),
            "offset": offset, "limit": limit}


def get_record(vault: str, commit_id: str) -> dict:
    state = get_state(vault)
    record = state.reviews.get(commit_id)
    if not record:
        raise KeyError("找不到这条复习记录：" + str(commit_id))
    return view_record(state, record)


def _at_from(date_text: str) -> str:
    if not date_text:
        return ""
    day = parse_date(date_text)
    if day is None:
        raise ValueError("日期格式应为 YYYY-MM-DD")
    if day > today():
        raise ValueError("不能补记未来的日期")
    return day.isoformat() + "T12:00:00"


def add(vault: str, item_id: str, grade, note: str = "", date: str = "", session_id: str = "") -> dict:
    state = get_state(vault)
    item = _item(state, item_id)
    value = check_grade(item["genre"], grade)
    payload = {"session_id": session_id or "", "item_id": item_id, "grade": value, "note": str(note or "")}
    if session_id:
        sess = state.sessions.get(session_id)
        if not sess or sess["cancelled"]:
            raise KeyError("找不到这次复习：" + session_id)
        if item_id not in {e["id"] for e in sess["items"]}:
            raise ValueError("这道题不在这次复习里")
        if item_id in sess["grades"]:
            raise ValueError("这道题在这次复习里已经有评分，要改请用「改」（record_update）")
    at = _at_from(date)
    if at:
        payload["at"] = at
    label = grade_label(item["genre"], value)
    commit = ledger.append_commit(vault, "review", "review.grade",
                                  f"{'补记 ' if not session_id else ''}{_describe(state, item_id)} · {label}", payload)
    return get_record(vault, commit["commit_id"])


def _active(state, commit_id):
    record = state.reviews.get(commit_id)
    if not record:
        raise KeyError("找不到这条复习记录：" + str(commit_id))
    if record["voided_by"]:
        raise ValueError("这条记录已经作废了")
    return record


def update(vault: str, commit_id: str, grade=None, note=None) -> dict:
    state = get_state(vault)
    old = _active(state, commit_id)
    item = _item(state, old["item_id"])
    value = check_grade(item["genre"], old["grade"] if grade is None else grade)
    new_note = old["note"] if note is None else str(note)
    if value == old["grade"] and new_note == old["note"]:
        return view_record(state, old)
    name = _describe(state, old["item_id"])

    def build(tx):
        tx.append("review", "review.void", f"改记录 {name}", {"commit_id": commit_id})
        return tx.append("review", "review.grade", f"{name} · {grade_label(item['genre'], value)}", {
            "session_id": old["session_id"], "item_id": old["item_id"], "grade": value, "note": new_note,
            "at": old["at"], "replaces": commit_id})

    commit, _ = ledger.transact(vault, build)
    return get_record(vault, commit["commit_id"])


def delete(vault: str, commit_id: str) -> dict:
    state = get_state(vault)
    old = _active(state, commit_id)
    ledger.append_commit(vault, "review", "review.void", f"撤销记录 {_describe(state, old['item_id'])}",
                         {"commit_id": commit_id})
    return get_record(vault, commit_id)


def restore(vault: str, commit_id: str) -> dict:
    state = get_state(vault)
    old = state.reviews.get(commit_id)
    if not old:
        raise KeyError("找不到这条复习记录：" + str(commit_id))
    if not old["voided_by"]:
        raise ValueError("这条记录没有作废，不需要恢复")
    if old["restored_by"] and not state.reviews.get(old["restored_by"], {}).get("voided_by"):
        raise ValueError("这条记录已经恢复过了：" + old["restored_by"])
    item = _item(state, old["item_id"])
    sess = state.sessions.get(old["session_id"]) if old["session_id"] else None
    if old["session_id"] and (not sess or sess["cancelled"]):
        raise ValueError("它所在的复习已经删除，不能恢复；可以「补记」一条")
    current = sess["grades"].get(old["item_id"]) if sess else None
    name = _describe(state, old["item_id"])

    def build(tx):
        if current:
            tx.append("review", "review.void", f"恢复旧记录前作废 {name}", {"commit_id": current["commit_id"]})
        return tx.append("review", "review.grade", f"恢复记录 {name} · {grade_label(item['genre'], old['grade'])}", {
            "session_id": old["session_id"], "item_id": old["item_id"], "grade": old["grade"], "note": old["note"],
            "at": old["at"], "restored_from": commit_id})

    commit, _ = ledger.transact(vault, build)
    return get_record(vault, commit["commit_id"])


def recent_days(vault: str, days: int = 7) -> int:
    """最近 N 天的有效复习记录条数（给 Agent 概览用）。"""
    since = (today() - datetime.timedelta(days=days - 1)).isoformat()
    state = get_state(vault)
    return sum(1 for r in state.reviews.values() if not r["voided_by"] and r["at"][:10] >= since)
