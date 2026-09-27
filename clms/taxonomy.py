"""题型体系：四大板块（genre）与每个板块下的题目类型（qtype）。

genre 的内部代码固定为 modern / poetry / classical / dictation；AI 与用户可以写中文名或别名，
由 normalize_genre() 统一。题型表可在 config.json 的 qtypes 覆盖，AI 提示词只给当前表。
"""

from .common import load_config

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

DEFAULT_QTYPES = {
    "modern": [
        "信息筛选题", "内容概括题", "词语理解题", "句子含意题", "句子赏析题",
        "修辞手法题", "表达技巧题", "段落作用题", "标题含义题", "线索题",
        "人物形象题", "环境描写作用题", "细节描写作用题", "意象作用题", "叙述视角题",
        "情感主旨题", "论证分析题", "探究拓展题", "选择题",
    ],
    "classical": [
        "实词解释题", "虚词题", "断句题", "文化常识题", "翻译题",
        "内容概括题", "人物形象题", "观点态度题", "选择题",
    ],
    "poetry": [
        "意象作用题", "意境画面题", "炼字题", "诗眼题", "表达技巧题",
        "修辞手法题", "抒情方式题", "思想情感题", "句子赏析题", "结构作用题",
        "比较阅读题", "选择题",
    ],
    "dictation": ["直接默写", "理解性默写"],
}

# 估时（分钟）：用于按时间预算排复习。阅读材料按篇只算一次。
ITEM_MINUTES = {"modern": 5.0, "classical": 2.5, "poetry": 4.0, "dictation": 0.5}
QTYPE_MINUTES = {"选择题": 1.5, "翻译题": 3.0, "断句题": 1.5, "实词解释题": 1.0,
                 "虚词题": 1.0, "文化常识题": 1.0, "词语理解题": 2.0}
MATERIAL_MINUTES = {"modern": 5.0, "classical": 3.0, "poetry": 1.5, "dictation": 0.0}


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
    cfg = load_config(vault)
    user = cfg.get("qtypes") if isinstance(cfg.get("qtypes"), dict) else {}
    out = {}
    for code in GENRE_ORDER:
        custom = user.get(code)
        base = list(DEFAULT_QTYPES[code])
        if isinstance(custom, list):
            base = [str(x).strip() for x in custom if str(x).strip()] or base
        out[code] = base
    return out


def taxonomy_payload(vault: str) -> dict:
    table = qtypes(vault)
    return {
        "genres": [{"code": g["code"], "name": g["name"], "short": g["short"]} for g in GENRES],
        "qtypes": table,
    }


def item_minutes(genre: str, qtype: str) -> float:
    if qtype in QTYPE_MINUTES:
        return QTYPE_MINUTES[qtype]
    return ITEM_MINUTES.get(genre, 3.0)
