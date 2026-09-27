"""录入草稿的结构：归一化（AI 输出 / 手工编辑都过这里）、入库前检查、两版之间的差异。

group = {gid, genre, material: {title, author, source, text}, items: [...], dictation: [...]}
item  = {iid, no, qtype, stem, answer, answer_origin, analysis, score, blank_lines, user_answer, note}
dictation entry = {iid, template, blanks: {"1": "…"}, source, kind}

gid / iid 是草稿内的稳定编号：AI 修订时被要求原样保留，前端据此对齐卡片、标出「刚改过」。
"""

import re

from . import dictation as dict_mod
from .common import as_float_or_none, clamp_int
from .taxonomy import GENRE_BY_CODE, normalize_genre

ITEM_FIELDS = ("no", "qtype", "stem", "answer", "answer_origin", "analysis", "user_answer", "note")
MATERIAL_FIELDS = ("title", "author", "source", "text")
FIELD_LABELS = {"no": "题号", "qtype": "题型", "stem": "题干", "answer": "答案", "analysis": "解析",
                "score": "分值", "blank_lines": "留白", "user_answer": "我的作答", "note": "错因",
                "answer_origin": "答案来源", "title": "标题", "author": "作者", "source": "出处",
                "text": "原文", "template": "题面", "blanks": "答案表", "kind": "类型"}


def _text(value) -> str:
    text = str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u3000]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def default_blank_lines(qtype: str, score) -> int:
    if "选择" in (qtype or ""):
        return 0
    if score:
        return max(2, min(12, round(score * 1.2)))
    return 4


def _item(raw: dict, fallback_iid: str) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    item = {field: _text(raw.get(field)) for field in ITEM_FIELDS}
    item["iid"] = str(raw.get("iid") or fallback_iid)
    item["score"] = as_float_or_none(raw.get("score"))
    if item["score"] is not None and item["score"] == int(item["score"]):
        item["score"] = int(item["score"])
    if raw.get("blank_lines") in (None, ""):
        item["blank_lines"] = default_blank_lines(item["qtype"], item["score"])
    else:
        item["blank_lines"] = clamp_int(raw.get("blank_lines"), 0, 24, 4)
    if item["answer_origin"] not in ("image", "ai", "user"):
        item["answer_origin"] = "image" if item["answer"] else ""
    return item


def _dictation(raw: dict, fallback_iid: str) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    template = _text(raw.get("template"))
    template = dict_mod.PLACEHOLDER_RE.sub(lambda m: "{书写区域%s}" % m.group(1), template)
    blanks = dict_mod.normalize_blanks(raw.get("blanks"))
    kind = _text(raw.get("kind")) or ("理解性默写" if len(template) > 30 else "直接默写")
    return {"iid": str(raw.get("iid") or fallback_iid), "template": template, "blanks": blanks,
            "source": _text(raw.get("source")), "kind": kind}


def normalize_groups(raw_groups) -> list:
    groups = []
    used_gids, used_iids = set(), set()
    for gi, raw in enumerate(raw_groups if isinstance(raw_groups, list) else []):
        if not isinstance(raw, dict):
            continue
        genre = normalize_genre(raw.get("genre"))
        gid = str(raw.get("gid") or "")
        if not gid or gid in used_gids:
            gid = next(f"g{n}" for n in range(1, 999) if f"g{n}" not in used_gids)
        used_gids.add(gid)
        material = raw.get("material") if isinstance(raw.get("material"), dict) else {}
        group = {"gid": gid, "genre": genre,
                 "material": {field: _text(material.get(field)) for field in MATERIAL_FIELDS},
                 "items": [], "dictation": []}

        def fresh(prefix, wanted):
            iid = str(wanted or "")
            if not iid or iid in used_iids:
                iid = next(f"{prefix}{n}" for n in range(1, 9999) if f"{prefix}{n}" not in used_iids)
            used_iids.add(iid)
            return iid

        if genre == "dictation":
            entries = raw.get("dictation") or raw.get("items") or []
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, dict):
                    group["dictation"].append(_dictation(entry, fresh("d", entry.get("iid"))))
            group["material"] = {field: "" for field in MATERIAL_FIELDS}
        else:
            entries = raw.get("items")
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, dict):
                    group["items"].append(_item(entry, fresh("i", entry.get("iid"))))
        groups.append(group)
    return groups


def issues(groups) -> list:
    """入库前的阻断问题：[{gid, iid, message}]。题型为空只是提醒，不阻断。"""
    out = []
    if not groups:
        out.append({"gid": "", "iid": "", "message": "草稿里还没有任何题目"})
    for group in groups:
        if group["genre"] == "dictation":
            if not group["dictation"]:
                out.append({"gid": group["gid"], "iid": "", "message": "默写板块没有题目"})
            for entry in group["dictation"]:
                for problem in dict_mod.check_entry(entry):
                    out.append({"gid": group["gid"], "iid": entry["iid"], "message": problem})
            continue
        if not group["material"]["text"]:
            out.append({"gid": group["gid"], "iid": "", "message": "缺少阅读材料原文"})
        if not group["items"]:
            out.append({"gid": group["gid"], "iid": "", "message": "这篇材料下没有小题"})
        for item in group["items"]:
            if not item["stem"]:
                out.append({"gid": group["gid"], "iid": item["iid"], "message": "题干为空"})
            if not item["answer"]:
                out.append({"gid": group["gid"], "iid": item["iid"], "message": "没有答案"})
    return out


def _label(group, entry=None, field=""):
    name = GENRE_BY_CODE[group["genre"]]["short"]
    title = group["material"].get("title")
    head = f"《{title}》" if title else name
    if entry is None:
        return f"{head} · {FIELD_LABELS.get(field, field)}" if field else head
    if group["genre"] == "dictation":
        tag = "默写 " + (entry.get("source") or entry["iid"])
    else:
        tag = f"第 {entry.get('no') or '?'} 题"
    return f"{tag} · {FIELD_LABELS.get(field, field)}" if field else tag


def diff(old_groups, new_groups) -> list:
    """两版草稿的差异：[{gid, iid, field, label}]，供对话气泡列出「改了哪里」、卡片标出高亮。"""
    changes = []
    old_by_gid = {g["gid"]: g for g in old_groups or []}
    for group in new_groups or []:
        before = old_by_gid.pop(group["gid"], None)
        if before is None:
            changes.append({"gid": group["gid"], "iid": "", "field": "*", "label": _label(group) + " · 新增"})
            continue
        if before["genre"] != group["genre"]:
            changes.append({"gid": group["gid"], "iid": "", "field": "genre", "label": _label(group) + " · 板块"})
        for field in MATERIAL_FIELDS:
            if before["material"].get(field) != group["material"].get(field):
                changes.append({"gid": group["gid"], "iid": "", "field": field, "label": _label(group, None, field)})
        key = "dictation" if group["genre"] == "dictation" else "items"
        old_entries = {e["iid"]: e for e in before.get(key, [])}
        for entry in group.get(key, []):
            prev = old_entries.pop(entry["iid"], None)
            if prev is None:
                changes.append({"gid": group["gid"], "iid": entry["iid"], "field": "*",
                                "label": _label(group, entry) + " · 新增"})
                continue
            for field, value in entry.items():
                if field not in ("iid", "answer_origin") and prev.get(field) != value:
                    changes.append({"gid": group["gid"], "iid": entry["iid"], "field": field,
                                    "label": _label(group, entry, field)})
        for entry in old_entries.values():
            changes.append({"gid": group["gid"], "iid": entry["iid"], "field": "-",
                            "label": _label(before, entry) + " · 删除"})
    for group in old_by_gid.values():
        changes.append({"gid": group["gid"], "iid": "", "field": "-", "label": _label(group) + " · 删除"})
    return changes


def count_units(groups) -> int:
    """入库后会变成几道小题（默写按空计）。"""
    total = 0
    for group in groups or []:
        if group["genre"] == "dictation":
            total += sum(len(dict_mod.blank_numbers(e["template"])) for e in group["dictation"])
        else:
            total += len(group["items"])
    return total


def normalize_item(raw: dict, iid: str) -> dict:
    """单道阅读小题的归一化（Agent 工具逐题增改时用，规则同 normalize_groups）。"""
    return _item(raw, iid)


def normalize_dictation(raw: dict, iid: str) -> dict:
    """单条默写的归一化（Agent 工具用）。"""
    return _dictation(raw, iid)


def clean_text(value) -> str:
    """统一换行、去行尾空白（与草稿字段同一规则）。"""
    return _text(value)
