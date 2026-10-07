"""题型体系：四大板块（genre）与每个板块下的题目类型（qtype）。

genre 的内部代码固定为 modern / poetry / classical / dictation；AI 与用户可以写中文名或别名，
由 normalize_genre() 统一。阅读题型只取自 config.json，首次使用时从现有题目迁移。
"""

import json
import threading
from functools import wraps

from .common import config_path, load_config, save_config

GENRES = [
    {"code": "modern", "name": "现代文阅读", "short": "现代文",
     "aliases": ["现代文", "现代文阅读", "记叙文", "散文", "小说", "论述类文本", "实用类文本", "非连续性文本", "议论文"]},
    {"code": "classical", "name": "文言文阅读", "short": "文言文",
     "aliases": ["文言文", "文言文阅读", "古文", "文言"]},
    {"code": "poetry", "name": "古代诗歌阅读", "short": "古诗",
     "aliases": ["古诗", "古代诗歌", "古代诗歌阅读", "诗歌鉴赏", "古诗词鉴赏", "诗词", "古诗词"]},
    {"code": "dictation", "name": "名句默写", "short": "默写",
     "aliases": ["默写", "名句默写", "名篇名句默写", "古诗文默写", "理解性默写"]},
]
GENRE_ORDER = [g["code"] for g in GENRES]      # 试卷顺序：现代文 → 文言 → 古诗 → 默写
GENRE_BY_CODE = {g["code"]: g for g in GENRES}

READING_GENRES = ("modern", "classical", "poetry")
DICTATION_TYPES = ["直接默写", "理解性默写"]
LEGACY_RECALL_QTYPES = {"实词解释题", "虚词题", "文化常识题"}
_lock = threading.RLock()


def guard_qtype_writes(fn):
    """题目提交与题型迁移用同一锁，避免旧题型在迁移完成后才落入 Ledger。"""
    @wraps(fn)
    def guarded(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return guarded

# 估时（分钟）：用于按时间预算排复习。阅读材料按篇只算一次。
ITEM_MINUTES = {"modern": 5.0, "classical": 2.5, "poetry": 4.0, "dictation": 0.5}
MATERIAL_MINUTES = {"modern": 5.0, "classical": 3.0, "poetry": 1.5, "dictation": 0.0}

# 记忆类型：决定用哪条记忆曲线（见 AI/algorithm.md「两种记忆类型」）。
# 默写固定记忆型；阅读题从用户配置取 kind，未分类或配置缺失安全回退理解型。
MEMORY_KINDS = {"recall": "记忆型", "skill": "理解型"}


def _raw_config(vault):
    try:
        with open(config_path(vault), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _ensure(vault):
    """迁移标记单独保存；旧版或新代码提前写出的空 qtypes 仍需扫描实际题目。"""
    with _lock:
        raw = _raw_config(vault)
        if raw.get("qtype_initialized") is True and isinstance(raw.get("qtype_kinds"), dict) and isinstance(raw.get("qtypes"), dict):
            return load_config(vault)
        from .projections import get_state
        table = {g: [] for g in READING_GENRES}
        existing = raw.get("qtypes") if isinstance(raw.get("qtypes"), dict) else {}
        for genre in READING_GENRES:
            for name in existing.get(genre, []) if isinstance(existing.get(genre), list) else []:
                name = str(name).strip()
                if name and name not in table[genre]:
                    table[genre].append(name)
        state = get_state(vault)
        for item in list(state.items.values()) + list(state.deleted.values()):
            genre, name = item.get("genre"), str(item.get("qtype") or "").strip()
            if genre in table and name and name not in table[genre]:
                table[genre].append(name)
        kinds = {g: {name: ("recall" if g == "classical" and name in LEGACY_RECALL_QTYPES else "skill")
                     for name in table[g]} for g in READING_GENRES}
        save_config(vault, {"qtypes": table, "qtype_kinds": kinds, "qtype_initialized": True})
        return load_config(vault)


def _tables(vault):
    cfg = _ensure(vault)
    table = {g: list(cfg["qtypes"].get(g, [])) for g in READING_GENRES}
    kinds = {g: {name: cfg["qtype_kinds"].get(g, {}).get(name, "skill")
                 if cfg["qtype_kinds"].get(g, {}).get(name, "skill") in MEMORY_KINDS else "skill"
                 for name in table[g]} for g in READING_GENRES}
    return table, kinds


def memory_kind(genre: str, qtype: str = "", vault: str = "", kinds=None) -> str:
    if genre == "dictation":
        return "recall"
    if not qtype or genre not in READING_GENRES:
        return "skill"
    if kinds is None:
        if not vault:
            return "skill"
        table, kinds = _tables(vault)
        return kinds[genre].get(qtype, "skill") if qtype in table[genre] else "skill"
    return kinds.get(genre, {}).get(qtype, "skill")


def qtype_kinds(vault):
    return _tables(vault)[1]


def normalize_genre(value, default="modern") -> str:
    text = str(value or "").strip()
    if text in GENRE_BY_CODE:
        return text
    for genre in GENRES:
        if text == genre["name"] or text in genre["aliases"]:
            return genre["code"]
    for genre in GENRES:                       # 模糊：包含别名
        if any(alias in text for alias in genre["aliases"] if len(alias) >= 2):
            return genre["code"]
    return default


def qtypes(vault: str) -> dict:
    table, _ = _tables(vault)
    return {**table, "dictation": list(DICTATION_TYPES)}


def valid_qtype(vault, genre, name):
    name = str(name or "").strip()
    return name if genre in READING_GENRES and name in qtypes(vault)[genre] else ""


def _genre(genre):
    if genre not in READING_GENRES:
        raise ValueError("只能管理现代文、文言文、古代诗歌的题型")
    return genre


def _name(name):
    name = str(name or "").strip()
    if not name:
        raise ValueError("题型名称不能为空")
    return name


def _save(vault, table, kinds):
    save_config(vault, {"qtypes": table, "qtype_kinds": kinds})
    return taxonomy_payload(vault)


def add(vault, genre, name):
    genre, name = _genre(genre), _name(name)
    with _lock:
        table, kinds = _tables(vault)
        if name in table[genre]:
            raise ValueError("这个板块已有同名题型")
        table[genre].append(name)
        kinds[genre][name] = "skill"
        return _save(vault, table, kinds)


def reorder(vault, genre, names):
    genre = _genre(genre)
    with _lock:
        table, kinds = _tables(vault)
        if not isinstance(names, list) or len(names) != len(table[genre]) or set(names) != set(table[genre]):
            raise ValueError("排序必须包含该板块的全部题型且不能重复")
        table[genre] = names[:]
        return _save(vault, table, kinds)


def set_kind(vault, genre, name, kind):
    genre, name = _genre(genre), _name(name)
    if kind not in MEMORY_KINDS:
        raise ValueError("记忆类型只能是 skill 或 recall")
    with _lock:
        table, kinds = _tables(vault)
        if name not in table[genre]:
            raise ValueError("题型不存在")
        kinds[genre][name] = kind
        return _save(vault, table, kinds)


def _used(vault, genre, name):
    from .projections import get_state
    state = get_state(vault)
    return [i["id"] for i in list(state.items.values()) + list(state.deleted.values())
            if i.get("genre") == genre and i.get("qtype") == name]


def rename(vault, genre, old_name, new_name):
    genre, old_name, new_name = _genre(genre), _name(old_name), _name(new_name)
    with _lock:
        table, kinds = _tables(vault)
        if old_name not in table[genre]:
            if new_name in table[genre] and not _used(vault, genre, old_name):
                return taxonomy_payload(vault)  # 中断后重试
            raise ValueError("原题型不存在")
        if old_name == new_name:
            return taxonomy_payload(vault)
        marker = load_config(vault).get("qtype_migration") or {}
        resumed = marker == {"genre": genre, "old_name": old_name, "new_name": new_name}
        if new_name in table[genre] and not resumed:
            raise ValueError("新名称已存在")
        if new_name not in table[genre]:
            table[genre].insert(table[genre].index(old_name), new_name)
            kinds[genre][new_name] = kinds[genre].get(old_name, "skill")
            save_config(vault, {"qtypes": table, "qtype_kinds": kinds,
                                "qtype_migration": {"genre": genre, "old_name": old_name, "new_name": new_name}})
        from .creation import update_item
        for item_id in _used(vault, genre, old_name):
            update_item(vault, item_id, {"qtype": new_name})
        table, kinds = _tables(vault)
        table[genre].remove(old_name)
        kinds[genre].pop(old_name, None)
        save_config(vault, {"qtypes": table, "qtype_kinds": kinds, "qtype_migration": {}})
        return taxonomy_payload(vault)


def delete(vault, genre, name, replace_with=None):
    genre, name = _genre(genre), _name(name)
    with _lock:
        table, kinds = _tables(vault)
        if name not in table[genre]:
            raise ValueError("题型不存在")
        used = _used(vault, genre, name)
        if used and replace_with is None:
            raise ValueError(f"还有 {len(used)} 道题使用「{name}」，请先选择迁移目标。")
        if replace_with is not None and replace_with != "" and (replace_with == name or replace_with not in table[genre]):
            raise ValueError("迁移目标必须是同板块的其它已有题型")
        from .creation import update_item
        for item_id in used:
            update_item(vault, item_id, {"qtype": replace_with})
        table[genre].remove(name)
        kinds[genre].pop(name, None)
        return _save(vault, table, kinds)


def taxonomy_payload(vault: str) -> dict:
    table, kinds = _tables(vault)
    from .projections import get_state
    uncategorized = {g: 0 for g in READING_GENRES}
    usage = {g: {name: 0 for name in table[g]} for g in READING_GENRES}
    for item in get_state(vault).items.values():
        genre, name = item.get("genre"), item.get("qtype")
        if genre in uncategorized:
            if not name:
                uncategorized[genre] += 1
            elif name in usage[genre]:
                usage[genre][name] += 1
    for item in get_state(vault).deleted.values():
        genre, name = item.get("genre"), item.get("qtype")
        if genre in usage and name in usage[genre]:
            usage[genre][name] += 1
    return {
        "genres": [{"code": g["code"], "name": g["name"], "short": g["short"]} for g in GENRES],
        "qtypes": {**table, "dictation": list(DICTATION_TYPES)}, "qtype_kinds": kinds,
        "uncategorized": uncategorized, "usage": usage,
    }


def item_minutes(genre: str, qtype: str) -> float:
    return ITEM_MINUTES.get(genre, 3.0)
