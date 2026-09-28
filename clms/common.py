"""路径、配置、日期与中文归一化。核心运行路径只依赖标准库。"""

import datetime
import hashlib
import json
import os
import re
import threading
import unicodedata

DATA_ROOT = "语文"          # <vault>/语文/.clms/，对标 OMRS 的 错题/.omrs/
DATA_DIRNAME = ".clms"

DEFAULT_CONFIG = {
    "ai_base_url": "",
    "ai_api_key": "",
    "ai_model": "",
    "ai_timeout": 150,
    "ai_max_tokens": 16000,
    "ai_concurrency": 2,
    "ai_context_window": 128000,   # 模型上下文窗口（token），输入框的圆环按它算占用
    # Agent harness：录入对话直连工具调用的 Agent；模型不支持 function calling 时关掉，回到一次性识图 / 整份修订
    "ai_agent": True,
    "agent_subagents": 3,     # 大试卷委派子代理时同时跑几个
    "agent_max_turns": 30,    # 主代理单次 run 最多几轮（一轮 = 一次模型请求 + 执行它要的工具）
    "agent_sub_turns": 16,
    # 复习日：0=周一 … 6=周日。默认周二、周五、周日（一周三次，间隔 3/2/2 天）
    "review_weekdays": [1, 4, 6],
    "session_minutes": 40,
    "theme": "light",
    "tuning": {},
    "qtypes": {},            # 覆盖默认题型表：{genre_code: [题型, …]}
}

_config_lock = threading.RLock()


def data_dir(vault: str) -> str:
    path = os.path.join(vault, DATA_ROOT, DATA_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def sub_dir(vault: str, name: str) -> str:
    path = os.path.join(data_dir(vault), name)
    os.makedirs(path, exist_ok=True)
    return path


def config_path(vault: str) -> str:
    return os.path.join(data_dir(vault), "config.json")


def load_config(vault: str) -> dict:
    with _config_lock:
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        try:
            with open(config_path(vault), "r", encoding="utf-8") as fh:
                user = json.load(fh)
            if isinstance(user, dict):
                merged.update(user)
        except (OSError, ValueError):
            pass
        return merged


def save_config(vault: str, patch: dict) -> dict:
    """浅合并写入；只接受 DEFAULT_CONFIG 里登记过的键。"""
    with _config_lock:
        current = load_config(vault)
        for key, value in (patch or {}).items():
            if key in DEFAULT_CONFIG:
                current[key] = value
        tmp = config_path(vault) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(current, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, config_path(vault))
        return current


# ── 日期 ────────────────────────────────────────────────

def today() -> datetime.date:
    override = os.environ.get("CLMS_TODAY")      # 测试用：固定「今天」
    if override:
        return datetime.date.fromisoformat(override)
    return datetime.date.today()


def now_iso() -> str:
    override = os.environ.get("CLMS_TODAY")
    if override:
        return override + "T12:00:00"
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def parse_date(value):
    if isinstance(value, datetime.date):
        return value
    text = str(value or "").strip()[:10]
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


# ── 中文归一化（去重的核心） ─────────────────────────────

_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ebef\U00030000-\U0003134f]"
)


def chinese_only(text: str) -> str:
    """只保留汉字：标点（全角 / 半角）、空白、数字、字母、注音全部丢弃。"""
    return "".join(_HAN_RE.findall(str(text or "")))


_ALNUM_RE = re.compile(r"[0-9a-z]")


def content_chars(text: str) -> str:
    """题干比对用：NFKC 归一（③ → 3、全角数字 → 半角）后保留汉字、数字、字母，丢掉标点和空白。
    与 chinese_only 的区别是保留编号——「第③段」和「第⑤段」必须是两道题。"""
    norm = unicodedata.normalize("NFKC", str(text or "")).lower()
    return "".join(ch for ch in norm if _HAN_RE.match(ch) or _ALNUM_RE.match(ch))


def short_hash(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def clamp_int(value, lo, hi, default):
    try:
        num = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, num))


def as_float_or_none(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num >= 0 else None
