"""默写题：模板 + 书写区域占位符 + 答案表 → 每个空一道小题，并按「只比汉字」去重。

AI 按如下格式填写一道默写题（一道题可以有多个空）：

    {"template": "床前明月光，{书写区域1}。", "blanks": {"1": "疑是地上霜"},
     "source": "李白《静夜思》", "kind": "直接默写"}

拆分规则：每个 {书写区域n} 变成一道独立小题。它的题面把自己的占位符换成统一的 {书写区域}，
同一模板里的其它空直接填入答案作上下文（例：上下两句各考一次时，考上句时下句可见）。

去重键：答案的汉字（去掉全部标点、空白、数字、字母）。同一名句无论出现在哪套卷子、
标点是全角还是半角、前后语境怎么写，都是同一道题。答案不足 4 个汉字时（如「之」「乎」），
单凭答案容易误并，改为「答案汉字 | 题面汉字前 24 字」。
"""

import re

from .common import chinese_only

PLACEHOLDER_RE = re.compile(r"[{｛]\s*书写区域\s*(\d+)\s*[}｝]")
TARGET = "{书写区域}"
SHORT_ANSWER = 4


def blank_numbers(template: str) -> list:
    """模板里出现的空的编号，按出现顺序去重。"""
    seen, out = set(), []
    for match in PLACEHOLDER_RE.finditer(template or ""):
        num = match.group(1)
        if num not in seen:
            seen.add(num)
            out.append(num)
    return out


def normalize_blanks(blanks) -> dict:
    """接受 {"1": "…"}、[{"n":1,"answer":"…"}]、["…", "…"] 三种写法，统一成 {"1": "…"}。"""
    out = {}
    if isinstance(blanks, dict):
        for key, value in blanks.items():
            num = re.sub(r"\D", "", str(key))
            if num:
                out[num] = str(value or "").strip()
    elif isinstance(blanks, list):
        for index, value in enumerate(blanks, 1):
            if isinstance(value, dict):
                num = re.sub(r"\D", "", str(value.get("n") or value.get("no") or index))
                out[num or str(index)] = str(value.get("answer") or value.get("text") or "").strip()
            else:
                out[str(index)] = str(value or "").strip()
    return out


def check_entry(entry: dict) -> list:
    """返回问题清单（空列表 = 可入库）。"""
    template = str(entry.get("template") or "")
    blanks = normalize_blanks(entry.get("blanks"))
    nums = blank_numbers(template)
    problems = []
    if not nums:
        problems.append("模板里没有 {书写区域n} 占位符")
    for num in nums:
        if not chinese_only(blanks.get(num, "")):
            problems.append(f"书写区域{num} 缺少答案")
    # 答案表里多出的编号（模板里已经删掉的空）不算问题：拆分时只按模板里的空取答案，多余的自然忽略。
    return problems


def prompt_for(template: str, blanks: dict, target: str) -> str:
    def repl(match):
        num = match.group(1)
        return TARGET if num == target else blanks.get(num, "")
    return PLACEHOLDER_RE.sub(repl, template or "")


def dedupe_key(answer: str, prompt: str = "") -> str:
    han = chinese_only(answer)
    if len(han) >= SHORT_ANSWER:
        return "dict:" + han
    context = chinese_only(prompt.replace(TARGET, ""))[:24]
    return "dict:" + han + "|" + context


def split_entry(entry: dict) -> list:
    """一道默写题 → 每个空一条：{no, prompt, answer, source, kind, key}。"""
    template = str(entry.get("template") or "")
    blanks = normalize_blanks(entry.get("blanks"))
    out = []
    for num in blank_numbers(template):
        answer = blanks.get(num, "")
        if not chinese_only(answer):
            continue
        prompt = prompt_for(template, blanks, num)
        out.append({
            "blank": num,
            "prompt": prompt,
            "answer": answer,
            "source": str(entry.get("source") or "").strip(),
            "kind": str(entry.get("kind") or "").strip(),
            "key": dedupe_key(answer, prompt),
        })
    return out
