"""把 Ledger 重放成内存状态（对标 OMRS projections.py）。

与 OMRS 的区别：投影常驻内存并按 seq 增量应用新提交（OMRS 技术债「每次全量重放」在这里不存在）；
记忆状态不落表，每次读取时由 scheduling.derive() 按「今天」和复习日现算——题量是个人级别，
几千题现算也在毫秒级，换来的是改了复习日 / tuning 立刻生效、撤销评分后无需迁移。
"""

import threading

from . import ledger
from .common import chinese_only, content_chars, short_hash, today as today_fn
from .scheduling import derive, load_tuning, review_weekdays


def material_key(text: str):
    han = chinese_only(text)
    return "mat:" + short_hash(han) if len(han) >= 8 else None


def grams(text: str, keep_numbers: bool = False) -> frozenset:
    chars = content_chars(text) if keep_numbers else chinese_only(text)
    return frozenset(chars[i:i + 2] for i in range(len(chars) - 1))


def overlap(a: frozenset, b: frozenset) -> float:
    """重合系数 |A∩B| / min(|A|,|B|)：对「多一行标题」「几个字识别不同」都不敏感。"""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def item_key(material_id: str, stem: str):
    chars = content_chars(stem)
    return f"item:{material_id}:{short_hash(chars)}" if (material_id and chars) else None


class State:
    def __init__(self):
        self.materials = {}
        self.items = {}
        self.sessions = {}
        self.keys = {}            # 去重键 → item_id / material_id
        self.review_index = {}    # commit_id → (item_id, session_id)，只含有效评分
        self.reviews = {}         # commit_id → 复习记录（含已作废的，供「记录」增删改查）
        self.deleted = {}         # 已删除的小题（item.delete 后移到这里，item.restore 可移回）
        self.last_seq = 0
        self._grams = {}          # 模糊匹配用的汉字二元组缓存：id → frozenset

    # ── 模糊匹配（同一篇文章 / 同一道题，两次拍照转录略有出入）──
    def _cached(self, key, text, keep_numbers=False):
        cached = self._grams.get(key)
        if cached is None or cached[0] != text:
            cached = self._grams[key] = (text, grams(text, keep_numbers))
        return cached[1]

    def match_material(self, genre: str, text: str):
        key = material_key(text)
        if key and self.keys.get(key) in self.materials:
            return self.keys[key]
        mine = grams(text)
        if len(mine) < 15:
            return None
        best, score = None, 0.0
        for mid, mat in self.materials.items():
            if mat.get("genre") != genre:
                continue
            theirs = self._cached(mid, mat.get("text", ""))
            if not theirs or min(len(mine), len(theirs)) / max(len(mine), len(theirs)) < 0.6:
                continue
            value = overlap(mine, theirs)
            if value >= 0.85 and value > score:
                best, score = mid, value
        return best

    def match_item(self, material_id: str, stem: str):
        key = item_key(material_id, stem)
        if key and self.keys.get(key) in self.items:
            return self.keys[key]
        mat = self.materials.get(material_id or "")
        mine = grams(stem, keep_numbers=True)
        if not mat or len(mine) < 4:
            return None
        for item_id in mat["item_ids"]:
            item = self.items.get(item_id)
            theirs = self._cached(item_id, item["stem"], keep_numbers=True) if item else None
            if theirs and min(len(mine), len(theirs)) / max(len(mine), len(theirs)) >= 0.7 and overlap(mine, theirs) >= 0.9:
                return item_id
        return None

    # ── 应用单条提交 ────────────────────────────────────
    def apply(self, c):
        handler = getattr(self, "_on_" + c["commit_type"].replace(".", "_"), None)
        if handler:
            handler(c["payload"], c)
        self.last_seq = c["seq"]

    def _on_entry_commit(self, p, c):
        for mat in p.get("materials", []):
            record = dict(mat, created_at=c["created_at"], item_ids=[], commit_id=c["commit_id"])
            self.materials[mat["id"]] = record
            if mat.get("key"):
                self.keys[mat["key"]] = mat["id"]
        for item in p.get("items", []):
            record = dict(item, created_at=c["created_at"], events=[], suspended=False,
                          commit_id=c["commit_id"], draft_id=p.get("draft_id", ""))
            self.items[item["id"]] = record
            if item.get("key"):
                self.keys[item["key"]] = item["id"]
            mat = self.materials.get(item.get("material_id") or "")
            if mat is not None:
                mat["item_ids"].append(item["id"])
        for again in p.get("reencounters", []):
            item = self.items.get(again.get("item_id"))
            if item:
                item["events"].append({"kind": "reencounter", "at": c["created_at"], "commit_id": c["commit_id"],
                                       "draft_id": p.get("draft_id", "")})

    def _on_item_update(self, p, c):
        item = self.items.get(p.get("item_id"))
        if not item:
            return
        old_key = item.get("key")
        item.update(p.get("changes") or {})
        new_key = p.get("key")
        if new_key and new_key != old_key:
            if old_key and self.keys.get(old_key) == item["id"]:
                self.keys.pop(old_key, None)
            item["key"] = new_key
            self.keys[new_key] = item["id"]

    def _on_material_update(self, p, c):
        mat = self.materials.get(p.get("material_id"))
        if mat:
            mat.update(p.get("changes") or {})

    def _on_item_suspend(self, p, c):
        item = self.items.get(p.get("item_id"))
        if item:
            item["suspended"] = bool(p.get("suspended"))

    def _on_item_delete(self, p, c):
        item = self.items.pop(p.get("item_id"), None)
        if not item:
            return
        if item.get("key") and self.keys.get(item["key"]) == item["id"]:
            self.keys.pop(item["key"], None)
        mat = self.materials.get(item.get("material_id") or "")
        if mat and item["id"] in mat["item_ids"]:
            mat["item_ids"].remove(item["id"])
        item["deleted_at"] = c["created_at"]
        self.deleted[item["id"]] = item

    def _on_item_restore(self, p, c):
        item = self.deleted.pop(p.get("item_id"), None)
        if not item:
            return
        item.pop("deleted_at", None)
        self.items[item["id"]] = item
        if item.get("key") and item["key"] not in self.keys:
            self.keys[item["key"]] = item["id"]
        mat = self.materials.get(item.get("material_id") or "")
        if mat is not None and item["id"] not in mat["item_ids"]:
            mat["item_ids"].append(item["id"])

    def _on_session_create(self, p, c):
        self.sessions[p["session_id"]] = {
            "id": p["session_id"], "created_at": c["created_at"], "planned_for": p.get("planned_for", ""),
            "minutes": p.get("minutes", 0), "items": p.get("items", []), "grades": {}, "cancelled": False,
            "title": p.get("title", ""),
        }

    def _on_session_cancel(self, p, c):
        sess = self.sessions.get(p.get("session_id"))
        if sess:
            sess["cancelled"] = True

    def _on_review_grade(self, p, c):
        item = self.items.get(p.get("item_id")) or self.deleted.get(p.get("item_id"))
        if not item:
            return
        at = p.get("at") or c["created_at"]
        item["events"].append({"kind": "review", "grade": p.get("grade", 0), "at": at,
                               "commit_id": c["commit_id"], "session_id": p.get("session_id", ""),
                               "note": p.get("note", "")})
        sess = self.sessions.get(p.get("session_id") or "")
        if sess is not None:
            sess["grades"][item["id"]] = {"grade": p.get("grade", 0), "commit_id": c["commit_id"], "at": at,
                                          "note": p.get("note", "")}
        self.review_index[c["commit_id"]] = (item["id"], p.get("session_id") or "")
        self.reviews[c["commit_id"]] = {
            "commit_id": c["commit_id"], "item_id": item["id"], "session_id": p.get("session_id") or "",
            "grade": p.get("grade", 0), "note": p.get("note", ""), "at": at, "created_at": c["created_at"],
            "voided_by": None, "restored_by": None, "restored_from": p.get("restored_from"),
            "replaces": p.get("replaces")}
        origin = self.reviews.get(p.get("restored_from") or "")
        if origin:
            origin["restored_by"] = c["commit_id"]

    def _on_review_void(self, p, c):
        target = p.get("commit_id")
        item_id, session_id = self.review_index.pop(target, (None, None))
        record = self.reviews.get(target or "")
        if record and not record["voided_by"]:
            record["voided_by"] = c["commit_id"]
        item = self.items.get(item_id or "") or self.deleted.get(item_id or "")
        if item:
            item["events"] = [e for e in item["events"] if e.get("commit_id") != target]
        sess = self.sessions.get(session_id or "")
        if sess and sess["grades"].get(item_id, {}).get("commit_id") == target:
            sess["grades"].pop(item_id, None)

    # ── 读视图 ─────────────────────────────────────────
    def item_view(self, item_id, ctx):
        item = self.items.get(item_id) or self.deleted.get(item_id)
        if not item:
            return None
        events = [e for e in item["events"]]
        sched = derive(item["created_at"], events, ctx["weekdays"], ctx["today"], ctx["tuning"])
        mat = self.materials.get(item.get("material_id") or "")
        view = {k: v for k, v in item.items() if k != "events"}
        view["sched"] = sched
        view["material_title"] = (mat or {}).get("title", "")
        view["encounters"] = 1 + sum(1 for e in events if e["kind"] == "reencounter")
        view["deleted"] = item_id in self.deleted
        return view

    def all_items(self, ctx):
        return [self.item_view(item_id, ctx) for item_id in self.items]


_states = {}
_states_lock = threading.Lock()


def get_state(vault: str) -> State:
    with _states_lock:
        state = _states.get(vault)
        if state is None:
            state = _states[vault] = State()
        for commit in ledger.read_commits(vault, state.last_seq):
            state.apply(commit)
        return state


def reset_state(vault: str):
    with _states_lock:
        _states.pop(vault, None)


def context(vault: str) -> dict:
    return {"weekdays": review_weekdays(vault), "today": today_fn(), "tuning": load_tuning(vault)}
