"""测试 / 演示用的假模型服务（OpenAI 兼容 /chat/completions）。不联网，不看图。

- 识别请求（提示词含「## 板块 genre」）：按调用次序轮流返回三套样例 A / B / C。
  A：现代文（自拟短文）3 题 + 名句默写 2 道；B：古诗《山居秋暝》2 题 + 一道与 A 标点不同的重复默写；
  C：文言文《世说新语·咏雪》3 题。
- 修订请求（提示词含「## 用户这次说」）：按指令里的「第 N 题」+「答案 / 题型 / 留白」做确定性修改。

- 带 tools 的请求（Agent 模式）：扮演一个确定性的工具调用 Agent（见 agent_reply）：
  识图时两个板块以上就 delegate 给子代理（每个子代理 material_set + items_add 或 dictation_add），单个板块自己
  group_add + items_add；对话里「第 N 题 + 答案 / 题型 / 留白」→ item_update，「入库」→ draft_commit，
  「停用 Q-…」→ library_suspend；复习批改 → session_get + review_grade。

用法：python3 tests/fake_ai.py 18999   然后在设置里填 API 地址 http://127.0.0.1:18999/v1、任意 Key、任意模型名。
环境变量 FAKE_AI_DELAY=秒 可模拟慢模型。
"""

import copy
import http.server
import itertools
import json
import os
import re
import sys
import threading
import time

MODERN_TEXT = """①老街在城的东头，街不长，两旁是青砖的铺面。我小时候最喜欢傍晚，那时各家的灯一盏一盏亮起来，像是有人沿着街慢慢走过去，顺手把它们点着了。
②修鞋的周伯的灯最暗。一只蒙着油污的灯泡吊在棚子下，光只够照亮他手里的那只鞋。他说灯亮了费电，照得见针脚就行。可每到下雨，他总把灯往外挪一挪，好让赶路的人看清门口那块松动的石板。
③后来老街要拆了。搬走的前一晚，我又去看周伯。他坐在棚子里，灯没开。“开着也没人来了。”他说。我替他拉了一下灯绳，那点昏黄的光落在他脸上，也落在满地的碎砖上，一时竟不知是灯照着街，还是街托着灯。
④如今城东是一片新楼，夜里的灯比从前亮得多。只是我偶尔路过，总觉得少了点什么——少的大约不是那盏灯，而是灯下那个替别人挪一挪灯的人。"""

SET_A = {"groups": [
    {"genre": "现代文阅读", "material": {"title": "老街的灯", "author": "", "source": "练习卷", "text": MODERN_TEXT},
     "items": [
         {"no": "6", "qtype": "选择题", "stem": "下列对文本相关内容的理解，不正确的一项是\nA. 第①段把灯次第亮起比作有人沿街点灯，写出了老街傍晚的温暖与生气。\nB. 周伯嫌灯亮费电，说明他为人吝啬，与下雨时挪灯的举动形成对比。\nC. 第③段“灯没开”与“我”替他拉灯，暗示老街即将消失时人的落寞。\nD. 结尾点明作者怀念的是灯下那份替人着想的善意。",
          "answer": "B", "answer_origin": "image", "analysis": "“费电”是周伯的自谦与节俭，并非吝啬。", "score": 3, "blank_lines": 0, "user_answer": "C"},
         {"no": "7", "qtype": "意象作用题", "stem": "文中多次写到“灯”，请分析“灯”在文中的作用。",
          "answer": "①线索：以灯贯穿全文，串起老街傍晚、周伯修鞋、拆迁前夜与如今城东的新楼。\n②象征：周伯的灯象征朴素的善意与人情温暖。\n③抒情：借灯的有无明暗，寄寓作者对老街人情的怀念与失落。",
          "answer_origin": "image", "score": 6, "blank_lines": 7, "user_answer": "灯是线索，贯穿全文。"},
         {"no": "8", "qtype": "句子赏析题", "stem": "赏析第③段画线句：“一时竟不知是灯照着街，还是街托着灯。”",
          "answer": "", "answer_origin": "", "score": 4, "blank_lines": 5, "user_answer": ""},
     ]},
    {"genre": "名句默写", "dictation": [
        {"template": "床前明月光，{书写区域1}。", "blanks": {"1": "疑是地上霜"}, "source": "李白《静夜思》", "kind": "直接默写"},
        {"template": "杜甫《春望》中，以花鸟寄寓感时恨别之情的两句是：“{书写区域1}，{书写区域2}。”",
         "blanks": {"1": "感时花溅泪", "2": "恨别鸟惊心"}, "source": "杜甫《春望》", "kind": "理解性默写"},
    ]},
], "notes": "第 8 题图中没有答案，已按采分点补写。"}

SET_A["groups"][0]["items"][2]["answer"] = "①运用设问（反问式的疑问）与对称句式，形成回环之美。\n②“照”“托”二字写出灯与街相互依存，人与老街融为一体。\n③含蓄表达“我”对老街人情的眷恋与即将失去的怅惘。"
SET_A["groups"][0]["items"][2]["answer_origin"] = "ai"

POEM = "空山新雨后，天气晚来秋。\n明月松间照，清泉石上流。\n竹喧归浣女，莲动下渔舟。\n随意春芳歇，王孙自可留。"
SET_B = {"groups": [
    {"genre": "古代诗歌阅读", "material": {"title": "山居秋暝", "author": "王维", "source": "", "text": POEM},
     "items": [
         {"no": "15", "qtype": "意象作用题", "stem": "颔联选取了“明月”“清泉”等意象，请分析其作用。",
          "answer": "①营造清幽明净的山间秋夜意境。\n②以动衬静，泉声更显山居之静。\n③寄托诗人高洁的情怀。", "score": 4, "blank_lines": 4},
         {"no": "16", "qtype": "思想情感题", "stem": "尾联表达了诗人怎样的思想感情？",
          "answer": "①反用《楚辞》“王孙兮归来”之意，表明山中可留。\n②表达对山居生活的喜爱与归隐之志。", "score": 5, "blank_lines": 5},
     ]},
    {"genre": "名句默写", "dictation": [
        {"template": "床前明月光,{书写区域1}.", "blanks": {"1": "疑是地上霜"}, "source": "李白《静夜思》"},
    ]},
], "notes": ""}

CLASSIC = "谢太傅寒雪日内集，与儿女讲论文义。俄而雪骤，公欣然曰：“白雪纷纷何所似？”兄子胡儿曰：“撒盐空中差可拟。”兄女曰：“未若柳絮因风起。”公大笑乐。即公大兄无奕女，左将军王凝之妻也。"
SET_C = {"groups": [
    {"genre": "文言文阅读", "material": {"title": "咏雪", "author": "刘义庆", "source": "《世说新语》", "text": CLASSIC},
     "items": [
         {"no": "10", "qtype": "实词解释题", "stem": "解释加点词：①俄而 ②骤", "answer": "①不久，一会儿 ②急（指雪下得大而急）", "score": 2, "blank_lines": 1},
         {"no": "11", "qtype": "翻译题", "stem": "把“未若柳絮因风起”翻译成现代汉语。", "answer": "不如比作柳絮乘风飞舞。", "score": 3, "blank_lines": 2},
         {"no": "12", "qtype": "观点态度题", "stem": "谢太傅对两个比喻的态度是怎样的？从哪里可以看出？", "answer": "更欣赏“柳絮因风起”；从“公大笑乐”以及文末特意交代谢道韫身份可以看出。", "score": 3, "blank_lines": 3},
     ]},
], "notes": ""}

_cycle = itertools.cycle([SET_A, SET_B, SET_C])
_keys = itertools.cycle(["A", "B", "C"])
_lock = threading.Lock()
QTYPES = ["意象作用题", "句子赏析题", "表达技巧题", "情感主旨题", "人物形象题", "环境描写作用题", "内容概括题", "翻译题"]


def revise(prompt: str) -> dict:
    draft = json.loads(prompt.split("## 当前草稿\n", 1)[1].split("\n\n## 最近的对话", 1)[0])
    instruction = prompt.split("## 用户这次说\n", 1)[1].split("\n\n修改要求", 1)[0]
    match = re.search(r"第\s*(\d+)\s*题", instruction)
    target = None
    for group in draft["groups"]:
        for item in group.get("items", []):
            if match and str(item.get("no")) == match.group(1):
                target = item
    if target is None:
        return {"reply": "我没找到你说的是哪一题，可以说“第 7 题……”。", "draft": draft}
    notes = []
    if "答案" in instruction:
        target["answer"] = "①点明手法：……（1 分）\n②结合文本分析：……（2 分）\n③指出效果与情感：……（1 分）"
        target["answer_origin"] = "ai"
        notes.append("按采分点重写了答案")
    for name in QTYPES:
        if name in instruction and "题型" in instruction:
            target["qtype"] = name
            notes.append(f"题型改成{name}")
    lines = re.search(r"留白\D*(\d+)", instruction)
    if lines:
        target["blank_lines"] = int(lines.group(1))
        notes.append(f"留白改为 {lines.group(1)} 行")
    reply = f"第 {target.get('no')} 题：" + ("，".join(notes) if notes else "这题我看了，暂时不需要改") + "。"
    return {"reply": reply, "draft": draft}


SETS = {"A": SET_A, "B": SET_B, "C": SET_C}


def _text(msg) -> str:
    content = msg.get("content")
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def _call(name, **args):
    return {"id": f"call_{name}_{abs(hash(json.dumps(args, ensure_ascii=False, sort_keys=True))) % 10**8}",
            "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


def _key_of(calls) -> str:
    blob = json.dumps(calls, ensure_ascii=False)
    match = re.search(r"\[fake:([ABC]):(\d+)\]", blob)
    if match:
        return match.group(1)
    for key, data in SETS.items():
        if any(g.get("material", {}).get("title") and g["material"]["title"] in blob for g in data["groups"]):
            return key
    return "A"


def _material(group):
    return {k: group["material"].get(k, "") for k in ("title", "author", "source", "text")}


def agent_reply(messages: list, tools: list) -> dict:
    """确定性的工具调用 Agent：只看本次 run 的消息（最后一条真实用户消息之后）决定下一步。"""
    names = {t["function"]["name"] for t in tools}
    first = _text(messages[0])
    start = max(i for i, m in enumerate(messages) if m["role"] == "user" and not _text(m).startswith("（这是 view_pages"))
    prompt = _text(messages[start])
    turn = messages[start + 1:]
    done = [m for m in turn if m["role"] == "assistant"]
    results = [m for m in turn if m["role"] == "tool"]
    last_calls = [c["function"]["name"] for c in (done[-1].get("tool_calls") or [])] if done else []

    if "你是 CLMS 录入流程里的子代理" in first:                     # 子代理
        match = re.search(r"\[fake:([ABC]):(\d+)\]", first)
        group = SETS[match.group(1)]["groups"][int(match.group(2))] if match else SET_C["groups"][0]
        if not done:
            if normalize(group) == "dictation":
                return {"tool_calls": [_call("dictation_add", entries=group["dictation"])]}
            return {"tool_calls": [_call("material_set", **_material(group)),
                                   _call("items_add", items=group["items"])]}
        count = len(group.get("dictation") or group.get("items") or [])
        return {"content": f"已录入 {count} 题，没有拿不准的地方。"}

    if "请识别并录入草稿" in prompt:                                  # 主代理识图
        if not done:
            with _lock:
                key = next(_keys)
            data = SETS[key]
            pages = int(re.search(r"共 (\d+) 页", prompt).group(1))
            if len(data["groups"]) >= 2 and "delegate" in names:
                tasks = [{"genre": g["genre"], "title": g.get("material", {}).get("title", ""),
                          "pages": [min(n + 1, pages)], "instructions": f"[fake:{key}:{n}]"}
                         for n, g in enumerate(data["groups"])]
                return {"tool_calls": [_call("delegate", tasks=tasks)]}
            group = data["groups"][0]
            return {"tool_calls": [_call("group_add", genre=group["genre"], **_material(group))]}
        key = _key_of([c for m in done for c in m.get("tool_calls") or []])
        if last_calls == ["group_add"]:
            gid = re.search(r"板块 (g\d+)", results[-1]["content"]).group(1)
            return {"tool_calls": [_call("items_add", gid=gid, items=SETS[key]["groups"][0]["items"])]}
        if last_calls == ["delegate"]:
            return {"tool_calls": [_call("draft_view")]}
        notes = SETS[key].get("notes")
        return {"content": "录好了，核对一下右边的草稿。" + (f"拿不准：{notes}" if notes else "")}

    if "作答照片" in prompt:                                          # 复习批改
        sid = re.search(r"复习 (S-\d+)", prompt).group(1)
        if not done:
            return {"tool_calls": [_call("session_get", session_id=sid)]}
        if last_calls == ["session_get"]:
            data = json.loads(results[-1]["content"])
            grades = [{"item_id": it["item_id"], "grade": 3 if it["genre"] == "dictation" else 2,
                       "note": "要点基本齐全" if it["genre"] != "dictation" else "全对"} for it in data["items"]]
            return {"tool_calls": [_call("review_grade", session_id=sid, grades=grades)]}
        return {"content": "批改完了：" + (results[-1]["content"] if results else "")}

    # 对话（只看用户这次说的最后一行；前面可能是「我手动改了：…」的说明）
    prompt = prompt.strip().split("\n")[-1]
    if done:
        return {"content": "；".join(r["content"].split("\n")[0] for r in results) or "好的。"}
    match = re.search(r"第\s*(\d+)\s*题", prompt)
    if "入库" in prompt and "draft_commit" in names:
        return {"tool_calls": [_call("draft_commit")]}
    stop = re.search(r"停用\s*(Q-\d+)", prompt)
    if stop:
        return {"tool_calls": [_call("library_suspend", item_id=stop.group(1), suspended=True)]}
    if match and "item_update" in names:
        fields = {}
        if "答案" in prompt:
            fields["answer"] = "①点明手法：……（1 分）\n②结合文本分析：……（2 分）\n③指出效果与情感：……（1 分）"
        for name in QTYPES:
            if name in prompt and "题型" in prompt:
                fields["qtype"] = name
        lines = re.search(r"留白\D*(\d+)", prompt)
        if lines:
            fields["blank_lines"] = int(lines.group(1))
        if fields:
            return {"tool_calls": [_call("item_update", ref=match.group(1), **fields)]}
    return {"content": "我看了一下，暂时不需要改。"}


def normalize(group) -> str:
    return "dictation" if group["genre"] == "名句默写" else "reading"


class FakeAI(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        time.sleep(float(os.environ.get("FAKE_AI_DELAY", "0")))
        if body.get("tools"):
            message = agent_reply(body["messages"], body["tools"])
            message.setdefault("content", "")
            payload = json.dumps({"choices": [{"message": dict(message, role="assistant"),
                                               "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}]},
                                 ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        text = next((p["text"] for p in body["messages"][0]["content"] if p.get("type") == "text"), "")
        if "## 用户这次说" in text:
            out = revise(text)
        elif "## 板块 genre" in text:
            with _lock:
                out = copy.deepcopy(next(_cycle))
        else:
            out = {"reply": "?"}
        content = json.dumps(out, ensure_ascii=False)
        payload = json.dumps({"choices": [{"message": {"content": "```json\n" + content + "\n```"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start(port: int):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), FakeAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    start(int(sys.argv[1]) if len(sys.argv) > 1 else 18999)
    print("fake AI ready")
    threading.Event().wait()
