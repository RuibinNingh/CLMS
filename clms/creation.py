"""草稿 → 题库：去重标注与入库（一份草稿 = 一条 entry.commit，整体成功或整体失败）。

去重（全部「只比汉字」）：
- 阅读材料：原文汉字的哈希。同一篇文章再录一次，新小题挂到已有材料下，不重复建材料。
- 阅读小题：所属材料 + 题干汉字的哈希。
- 默写：每个空按 dictation.dedupe_key（答案汉字；过短时加题面汉字）。
已在库中的题不新建，而是记一次 reencounter（「又错了一次」），调度按一次「不会」处理；
同一份草稿里重复出现的只保留第一次。
"""

from . import dictation as dict_mod
from . import ledger
from .draft_schema import count_units, issues
from .projections import get_state, item_key, material_key

EDITABLE = {"qtype", "stem", "answer", "answer_origin", "analysis", "score", "blank_lines",
            "user_answer", "note", "no", "source"}
MATERIAL_EDITABLE = {"title", "author", "source", "text"}


def annotate(vault: str, groups: list) -> dict:
    state = get_state(vault)
    result = {"groups": {}, "units": count_units(groups), "new_units": 0, "dup_units": 0}
    seen = {}
    for group in groups:
        info = {"material_match": None, "items": {}, "dictation": {}}
        if group["genre"] != "dictation":
            mid = state.match_material(group["genre"], group["material"]["text"])
            if mid:
                mat = state.materials[mid]
                info["material_match"] = {"id": mid, "title": mat.get("title", ""), "items": len(mat["item_ids"])}
            for item in group["items"]:
                dup = state.match_item(mid, item["stem"]) if mid else None
                info["items"][item["iid"]] = {"dup_item_id": dup}
                result["dup_units" if dup else "new_units"] += 1
        else:
            for entry in group["dictation"]:
                rows = []
                for unit in dict_mod.split_entry(entry):
                    dup = state.keys.get(unit["key"])
                    dup = dup if dup in state.items else None
                    rows.append({"blank": unit["blank"], "key": unit["key"], "dup_item_id": dup,
                                 "dup_in_draft": seen.get(unit["key"])})
                    if dup or unit["key"] in seen:
                        result["dup_units"] += 1
                    else:
                        result["new_units"] += 1
                    seen.setdefault(unit["key"], f"{entry['iid']}·{unit['blank']}")
                info["dictation"][entry["iid"]] = rows
        result["groups"][group["gid"]] = info
    return result


def commit_draft(vault: str, draft: dict, groups: list) -> dict:
    problems = issues(groups)
    if problems:
        raise ValueError("草稿还有问题没解决：" + "；".join(p["message"] for p in problems[:3]))
    images = draft.get("images") or []

    def build(tx):
        state = get_state(vault)
        materials, items, again, keys = [], [], [], {}
        skipped = 0

        def lookup(key):
            if not key:
                return None
            if key in keys:
                return keys[key]
            found = state.keys.get(key)
            return found if (found in state.items or found in state.materials) else None

        def reencounter(item_id):
            nonlocal skipped
            if any(a["item_id"] == item_id for a in again) or item_id.startswith("new:"):
                skipped += 1
                return
            again.append({"item_id": item_id})

        for group in groups:
            if group["genre"] == "dictation":
                for entry in group["dictation"]:
                    for unit in dict_mod.split_entry(entry):
                        dup = lookup(unit["key"])
                        if dup:
                            reencounter(dup)
                            continue
                        item_id = tx.next_id("Q")
                        keys[unit["key"]] = "new:" + item_id
                        items.append({"id": item_id, "material_id": None, "genre": "dictation",
                                      "qtype": entry["kind"] or "直接默写", "stem": unit["prompt"],
                                      "answer": unit["answer"], "source": unit["source"], "no": "",
                                      "order": len(items), "blank_lines": 1, "key": unit["key"],
                                      "template": entry["template"], "image": images[0] if images else ""})
                continue
            mat = group["material"]
            mkey = material_key(mat["text"])
            mid = keys.get(mkey) if mkey else None
            mid = mid or state.match_material(group["genre"], mat["text"])
            if not mid:
                mid = tx.next_id("M")
                if mkey:
                    keys[mkey] = mid
                materials.append({"id": mid, "genre": group["genre"], "title": mat["title"],
                                  "author": mat["author"], "source": mat["source"], "text": mat["text"],
                                  "key": mkey, "image": images[0] if images else ""})
            for order, item in enumerate(group["items"]):
                ikey = item_key(mid, item["stem"])
                dup = keys.get(ikey) or (state.match_item(mid, item["stem"]) if mid in state.materials else None)
                if dup:
                    reencounter(dup)
                    continue
                item_id = tx.next_id("Q")
                keys[ikey] = "new:" + item_id
                record = {k: item[k] for k in ("no", "qtype", "stem", "answer", "answer_origin", "analysis",
                                                "score", "blank_lines", "user_answer", "note")}
                record.update({"id": item_id, "material_id": mid, "genre": group["genre"], "order": order,
                               "key": ikey, "image": images[0] if images else ""})
                items.append(record)
        if not items and not again:
            raise ValueError("没有可入库的内容")
        message = f"录入 {len(items)} 题" + (f"，{len(again)} 题再次出错" if again else "")
        commit = tx.append("entry", "entry.commit", message, {
            "draft_id": draft["id"], "images": images, "materials": materials,
            "items": items, "reencounters": again})
        return {"commit_id": commit["commit_id"], "created": len(items), "reencountered": len(again),
                "skipped": skipped, "item_ids": [it["id"] for it in items],
                "material_ids": [m["id"] for m in materials]}

    result, _ = ledger.transact(vault, build)
    return result


def update_item(vault: str, item_id: str, changes: dict) -> dict:
    state = get_state(vault)
    item = state.items.get(item_id)
    if not item:
        raise KeyError("找不到这道题：" + item_id)
    clean = {k: v for k, v in (changes or {}).items() if k in EDITABLE}
    if "blank_lines" in clean:
        clean["blank_lines"] = max(0, min(24, int(clean["blank_lines"] or 0)))
    if not clean:
        raise ValueError("没有可修改的字段")
    new_key = None
    if item["genre"] == "dictation" and ("answer" in clean or "stem" in clean):
        new_key = dict_mod.dedupe_key(clean.get("answer", item["answer"]), clean.get("stem", item["stem"]))
    elif item.get("material_id") and "stem" in clean:
        new_key = item_key(item["material_id"], clean["stem"])
    if new_key and new_key != item.get("key") and new_key in state.keys:
        raise ValueError("改完后和题库里的另一道题重复了：" + state.keys[new_key])
    payload = {"item_id": item_id, "changes": clean}
    if new_key:
        payload["key"] = new_key
    from .sessions import describe
    return ledger.append_commit(vault, "library", "item.update", f"修改 {describe(state, item_id)}", payload)


def update_material(vault: str, material_id: str, changes: dict) -> dict:
    state = get_state(vault)
    if material_id not in state.materials:
        raise KeyError("找不到这篇材料：" + material_id)
    clean = {k: str(v) for k, v in (changes or {}).items() if k in MATERIAL_EDITABLE}
    if not clean:
        raise ValueError("没有可修改的字段")
    return ledger.append_commit(vault, "library", "material.update", f"修改 {material_id}",
                                {"material_id": material_id, "changes": clean})
