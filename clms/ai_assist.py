"""AI 录入（OpenAI 兼容协议，只用标准库；调用方式与 OMRS ai_assist.py 相同）。

三种调用：
- chat(messages, tools)：Agent harness 的多轮工具调用（见 harness.py / agent.py）。
- extract(images)：看图 → 草稿 groups（原文 / 小题 / 题型 / 答案 / 留白 / 默写模板）。
- revise(groups, history, instruction)：对话修订 → {reply, groups}。每次都把完整草稿发过去（无状态），
  模型返回完整草稿，由 draft_schema.diff() 算出改动，前端据此高亮。

消息只用 user 角色，指令与图片都在 user 的 content 里（兼容 Qwen-VL 等不建议设 system 的模型）。
配置：config.json 的 ai_base_url / ai_api_key / ai_model / ai_timeout / ai_max_tokens。
"""

import base64
import io
import json
import mimetypes
import re
import urllib.error
import urllib.request

from .common import load_config
from .draft_schema import normalize_groups
from .taxonomy import GENRES, qtypes

try:                                   # 可选：缩图 / 长图切片；没有 Pillow 就原图直发
    from PIL import Image
except ImportError:                    # pragma: no cover
    Image = None

MAX_WIDTH = 1600
STRIP_RATIO = 3.2      # 高 / 宽超过这个比例的长截图切成多张（带重叠）按顺序发送


def _endpoint(base: str) -> str:
    base = base.strip().rstrip("/")
    return base if base.endswith("/chat/completions") else base + "/chat/completions"


def ai_ready(vault: str) -> bool:
    cfg = load_config(vault)
    return all(str(cfg.get(k) or "").strip() for k in ("ai_base_url", "ai_api_key", "ai_model"))


def image_data_urls(path: str, max_width: int = MAX_WIDTH) -> list:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as fh:
        data = fh.read()
    if Image is None:
        return [f"data:{mime};base64," + base64.b64encode(data).decode()]
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
    except Exception:  # noqa: BLE001 - 不是 Pillow 能读的格式就原样发
        return [f"data:{mime};base64," + base64.b64encode(data).decode()]
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)))
    strips = [img]
    if img.height > img.width * STRIP_RATIO:
        step, overlap, strips, top = int(img.width * 2.2), int(img.width * 0.15), [], 0
        while top < img.height:
            bottom = min(img.height, top + step)
            if img.height - bottom < img.width * 0.5:
                bottom = img.height
            strips.append(img.crop((0, top, img.width, bottom)))
            if bottom >= img.height:
                break
            top = bottom - overlap
    out = []
    for strip in strips:
        buf = io.BytesIO()
        strip.save(buf, "JPEG", quality=88)
        out.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())
    return out


def _config(vault: str):
    cfg = load_config(vault)
    base, key, model = (str(cfg.get(k) or "").strip() for k in ("ai_base_url", "ai_api_key", "ai_model"))
    missing = [n for n, v in (("API 地址", base), ("API Key", key), ("模型", model)) if not v]
    if missing:
        raise ValueError("还没有配置 AI：到「设置」填写 " + "、".join(missing))
    return cfg, base, key, model


def _post(vault: str, payload: dict, tools_used: bool = False) -> dict:
    """POST /chat/completions，返回解析后的响应 JSON；网络 / HTTP / 超时 / 格式错误统一转成中文 ValueError。"""
    cfg, base, key, _ = _config(vault)
    request = urllib.request.Request(
        _endpoint(base), data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "Accept": "application/json"})
    timeout = int(cfg.get("ai_timeout") or 150)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400] if exc.fp else ""
        hint = ""
        if tools_used and exc.code in (400, 404, 422) and re.search(r"tool|function", detail, re.I):
            hint = "。这个模型可能不支持工具调用（function calling）：换一个支持的模型，或到「设置」关闭 Agent 模式"
        raise ValueError(f"模型服务返回 HTTP {exc.code}：{detail or exc.reason}{hint}")
    except urllib.error.URLError as exc:
        raise ValueError(f"连不上模型服务，检查 API 地址和网络：{getattr(exc, 'reason', exc)}")
    except TimeoutError:
        raise ValueError(f"模型超过 {timeout} 秒没有回复，可以重试或换一个更快的模型")
    try:
        response = json.loads(raw)
        response["choices"][0]["message"]
    except Exception:  # noqa: BLE001
        raise ValueError("模型接口的回复格式无法解析")
    return response


def _text_of(message) -> str:
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def call_model(vault: str, text: str, images: list) -> str:
    cfg, _, _, model = _config(vault)
    content = [{"type": "image_url", "image_url": {"url": url}} for url in images]
    content.append({"type": "text", "text": text})
    payload = {"model": model, "messages": [{"role": "user", "content": content}],
               "temperature": 0.1, "max_tokens": int(cfg.get("ai_max_tokens") or 6000)}
    response = _post(vault, payload)
    choice = response["choices"][0]
    if choice.get("finish_reason") == "length":
        usage = response.get("usage") or {}
        reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        detail = f"（其中思考用了 {reasoning} token）" if isinstance(reasoning, int) else ""
        raise ValueError(f"模型输出达到 {payload['max_tokens']} token 上限{detail}，草稿没有生成完整。"
                         "请到「设置」提高输出上限后重试，或拆成每张一份草稿")
    return _text_of(choice["message"])


def chat(vault: str, messages: list, tools=None) -> dict:
    """带工具的多轮调用（Agent harness 用）。messages 已是 OpenAI 格式。
    返回 {content, tool_calls:[{id, name, arguments(原始字符串)}], finish_reason, usage}；
    finish_reason=length 不在这里报错，由 harness 决定怎么处理被截断的工具调用。"""
    cfg, _, _, model = _config(vault)
    payload = {"model": model, "messages": messages, "temperature": 0.1,
               "max_tokens": int(cfg.get("ai_max_tokens") or 6000)}
    if tools:
        payload["tools"] = tools
    response = _post(vault, payload, tools_used=bool(tools))
    choice = response["choices"][0]
    message = choice["message"]
    calls = []
    for n, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments")
        calls.append({"id": str(call.get("id") or f"call_{n}"), "name": str(fn.get("name") or ""),
                      "arguments": args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)})
    return {"content": _text_of(message), "tool_calls": calls, "finish_reason": choice.get("finish_reason") or "",
            "usage": response.get("usage") or {}}


def extract_json(text: str) -> dict:
    cleaned = (text or "").strip()
    fence = re.match(r"^```[a-zA-Z0-9]*\s*\n?(.*?)\n?```$", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    for candidate in (cleaned, cleaned[cleaned.find("{"):cleaned.rfind("}") + 1]):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    raise ValueError("模型回复不是有效的 JSON；请重试，或换用更稳定的模型")


def _qtype_table(vault: str) -> str:
    table = qtypes(vault)
    return "\n".join(f"- {g['name']}：" + "、".join(table[g["code"]])
                     for g in GENRES if g["code"] != "dictation")


EXTRACT_PROMPT = """你是高中语文错题录入助手。图片是语文试卷或练习的照片 / 截图（可能分成几张，按顺序拼接），通常同时包含题目和答案（参考答案、解析或批改）。请整理成结构化 JSON，供错题本入库。

## 板块 genre
只用四个值：现代文阅读、文言文阅读、古代诗歌阅读、名句默写。一张图可能有多个板块；每篇独立的阅读材料单独成一个 group，名句默写整体成一个 group。

## group 的字段
- material：阅读材料。现代文、文言文、古诗必须填 title（标题）、author（作者，可空）、source（出处，可空）、text（原文全文）。
  - 原文逐字转录，不改写、不省略；段落之间用一个换行分隔；古诗按原排版每句或每联换行；保留①②③段落序号；注释放在 text 末尾，另起一段以「注：」开头。
- items：该材料下的每道小题（名句默写 group 里为空数组）：
  - no：题号原样（如 "7"、"8(1)"）
  - qtype：题目类型，从下方题型表选最贴切的一个；确实没有合适的才自拟一个以「题」结尾的简短名称
  - stem：题干原文；选择题把选项放进题干，每个选项单独一行（A. ……）
  - answer：参考答案。图片里有就照录，answer_origin 写 "image"；图片里没有时由你按高考阅卷习惯写（分条，每条一个采分点），answer_origin 写 "ai"
  - analysis：解析，图片里有就录，没有留空
  - score：分值（数字），看不到写 null
  - blank_lines：答题留白行数（整数，每行约 20 个汉字），按答案要点多少、分值和题型判断。参考：选择题 0；词语解释、断句 1–2；翻译每句 2–3；概括、赏析 3–6；探究、论述 6–10
  - user_answer：学生自己的作答（手写或填写），看得清就转录，没有留空
- dictation：只在名句默写 group 里用。每道默写题一条：
  - template：题面，每个要书写的空替换成 {书写区域1}、{书写区域2}……（编号在本条内从 1 递增）
  - blanks：编号到答案的表，如 {"1": "疑是地上霜"}；答案只写诗文本身
  - source：出处（如 李白《静夜思》），看得出就写
  - kind：直接默写 或 理解性默写
  - 例：{"template": "床前明月光，{书写区域1}。", "blanks": {"1": "疑是地上霜"}, "source": "李白《静夜思》", "kind": "直接默写"}

## 题型表
%s

%s## 输出
只输出一个 JSON 对象，不要 Markdown 围栏，不要解释：
{"groups": [{"genre": "…", "material": {…}, "items": […], "dictation": […]}], "notes": "看不清或拿不准的地方，一两句话；没有就写空字符串"}"""


REVISE_PROMPT = """你是高中语文错题录入助手，正在和用户一起校对一份错题草稿。字段含义：material 阅读材料；items 小题（qtype 题型、stem 题干、answer 参考答案、answer_origin 答案来源 image/ai/user、score 分值、blank_lines 留白行数、user_answer 学生作答、note 错因）；dictation 默写（template 用 {书写区域n} 标出要写的空，blanks 是编号到答案的表）。gid / iid 是内部编号，已有的原样保留、不要重排；新增的题不写 iid。

## 可选题型
%s

## 当前草稿
%s

## 最近的对话
%s

## 用户这次说
%s

修改要求：
- 只改用户要求改的地方，其余字段逐字保持原样。
- 改答案时按高考阅卷习惯：分条、每条一个采分点、语言简洁；分值已知时采分点数与分值匹配；由你改写的答案把 answer_origin 设为 "ai"。
- 用户只是提问、不要求修改时，草稿原样返回，在 reply 里回答。
- 需要核对原文或题目时，看附带的原图。

只输出一个 JSON 对象，不要 Markdown 围栏：
{"reply": "一两句话说明改了什么（或回答问题）", "draft": {"groups": [ …完整草稿… ]}}"""


def extract(vault: str, image_paths: list, hint: str = "", progress=None) -> dict:
    if progress:
        progress("images", "处理原图", "local")
    images = [url for path in image_paths for url in image_data_urls(path)]
    hint_text = f"## 用户补充说明\n{hint.strip()}\n\n" if hint and hint.strip() else ""
    if progress:
        progress("model", "调用识图模型", "model")
    reply = call_model(vault, EXTRACT_PROMPT % (_qtype_table(vault), hint_text), images)
    if progress:
        progress("parse", "解析模型回复", "local")
    obj = extract_json(reply)
    groups = normalize_groups(obj.get("groups"))
    if not groups:
        raise ValueError("模型没有从图片里识别出题目。可以换一张更清晰的图，或在对话里说明这是哪一类题")
    return {"groups": groups, "notes": str(obj.get("notes") or "").strip()}


def _strip_for_prompt(groups: list) -> list:
    return [{k: v for k, v in g.items()} for g in groups]


def revise(vault: str, groups: list, history: list, instruction: str, image_paths: list, progress=None) -> dict:
    lines = []
    for msg in history[-8:]:
        who = "用户" if msg.get("role") == "user" else "助手"
        text = str(msg.get("text") or "").strip().replace("\n", " ")
        if text:
            lines.append(f"{who}：{text[:300]}")
    prompt = REVISE_PROMPT % (_qtype_table(vault),
                              json.dumps({"groups": _strip_for_prompt(groups)}, ensure_ascii=False),
                              "\n".join(lines) or "（无）", instruction.strip())
    images = [url for path in image_paths for url in image_data_urls(path)]
    if progress:
        progress("model", "调用对话模型", "model")
    obj = extract_json(call_model(vault, prompt, images))
    if progress:
        progress("parse", "比对并解析改动", "local")
    draft = obj.get("draft") if isinstance(obj.get("draft"), dict) else obj
    new_groups = normalize_groups(draft.get("groups")) if isinstance(draft, dict) and "groups" in draft else groups
    return {"reply": str(obj.get("reply") or "").strip() or "已按你的要求修改。", "groups": new_groups}
