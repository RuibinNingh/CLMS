"""v0.5：两种记忆类型、复习推荐（自选 / 移除 / 未完成复习）、题库分面筛选与分组、复习历史筛选；
v0.6：复习助手改为只读 Agent（按需调工具看题和原文、引用、照片跨轮、关掉 Agent 模式时的旧做法）。"""

import datetime
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from clms import creation, library, records, review_ai, scheduling, sessions  # noqa: E402
from clms.common import save_config  # noqa: E402
from test_core import TempVault, _group_a  # noqa: E402

WD = [1, 4, 6]


def ev(grade, at):
    return {"kind": "review", "grade": grade, "at": at}


class MemoryKindTests(unittest.TestCase):
    def test_kinds(self):
        from clms.taxonomy import memory_kind
        self.assertEqual(memory_kind("dictation", "直接默写"), "recall")
        self.assertEqual(memory_kind("classical", "实词解释题"), "recall")
        self.assertEqual(memory_kind("classical", "翻译题"), "skill")
        self.assertEqual(memory_kind("modern", "意象作用题"), "skill")

    def test_skill_one_full_mark_masters_and_revives_late(self):
        d = scheduling.derive("2026-09-28", [ev(3, "2026-10-01")], WD, datetime.date(2026, 10, 2), kind="skill")
        self.assertEqual(d["status"], "已掌握")
        self.assertGreaterEqual(d["interval"], 120)
        r = scheduling.derive("2026-09-28", [ev(3, "2026-10-01")], WD, datetime.date(2026, 10, 2), kind="recall")
        self.assertNotEqual(r["status"], "已掌握")          # 记忆型仍要连续两次
        self.assertLess(r["interval"], 10)

    def test_skill_two_basic_marks_master(self):
        one = scheduling.derive("2026-09-28", [ev(2, "2026-10-01")], WD, datetime.date(2026, 10, 2), kind="skill")
        self.assertEqual(one["status"], "巩固中")
        self.assertGreaterEqual(one["interval"], 7)          # 「基本」之后至少隔 7 天
        two = scheduling.derive("2026-09-28", [ev(2, "2026-10-01"), ev(2, "2026-10-09")], WD,
                                datetime.date(2026, 10, 10), kind="skill")
        self.assertEqual(two["status"], "已掌握")

    def test_skill_revive_zero_means_never(self):
        t = dict(scheduling.DEFAULT_TUNING, skill_revive_days=0)
        d = scheduling.derive("2026-09-28", [ev(3, "2026-10-01")], WD, datetime.date(2026, 10, 2), t, kind="skill")
        self.assertEqual(d["due"], scheduling.NEVER)
        self.assertEqual(d["overdue_days"], 0)

    def test_skill_decays_slower(self):
        evs = [ev(2, "2026-10-01")]
        skill = scheduling.derive("2026-09-28", evs, WD, datetime.date(2026, 11, 1), kind="skill")
        recall = scheduling.derive("2026-09-28", evs, WD, datetime.date(2026, 11, 1), kind="recall")
        self.assertGreater(skill["decayed"], recall["decayed"])

    def test_new_items_rise_with_age(self):
        fresh = scheduling.derive("2026-09-28", [], WD, datetime.date(2026, 9, 29))
        old = scheduling.derive("2026-09-01", [], WD, datetime.date(2026, 9, 29))
        self.assertGreater(old["priority"], fresh["priority"])
        self.assertEqual(old["age_days"], 28)


def fake_item(i, mid, genre, due, prio, status="待攻克", reviews=1, qtype="", decayed=0.1, last="2026-09-20"):
    return {"id": i, "material_id": mid, "genre": genre, "qtype": qtype, "order": 0,
            "sched": {"due": due, "status": status, "priority": prio, "decayed": decayed, "leech": False,
                      "reviews": reviews, "overdue_days": 0, "kind": "skill", "last_grade": 1 if reviews else None,
                      "age_days": 5, "wrong_streak": 0, "last_review": last}}


class PlanTests(unittest.TestCase):
    today = datetime.date(2026, 10, 1)

    def plan(self, items, **kw):
        return scheduling.plan_session(items, kw.pop("budget", 60), self.today, self.today, **kw)

    def test_pinned_first_and_excluded_replaced(self):
        items = [fake_item("Q1", None, "dictation", "2026-10-01", 0.9), fake_item("Q2", None, "dictation", "2026-10-01", 0.8),
                 fake_item("Q3", None, "dictation", "2026-11-01", 0.1)]
        plan = self.plan(items, pinned=["Q3"], exclude=["Q1"], fill=False)
        ids = {c["id"]: c["tag"] for c in plan["items"]}
        self.assertEqual(ids, {"Q3": "manual", "Q2": "due"})
        self.assertEqual(plan["pinned"], 1)

    def test_busy_items_skipped_and_counted(self):
        items = [fake_item("Q1", None, "dictation", "2026-10-01", 0.9), fake_item("Q2", None, "dictation", "2026-10-01", 0.8)]
        plan = self.plan(items, busy={"Q1"}, fill=False)
        self.assertEqual([c["id"] for c in plan["items"]], ["Q2"])
        self.assertEqual(plan["busy_skipped"], 1)

    def test_reason_mentions_last_grade(self):
        items = [fake_item("Q1", None, "modern", "2026-09-29", 0.9, qtype="意象作用题")]
        items[0]["sched"]["overdue_days"] = 2
        plan = self.plan(items, fill=False)
        self.assertEqual(plan["items"][0]["tag"], "overdue")
        self.assertIn("上次「部分」", plan["items"][0]["reason"])

    def test_weak_qtype_preferred_when_filling(self):
        reviewed = [fake_item(f"W{i}", None, "modern", "2026-12-01", 0.2, qtype="意象作用题", decayed=0.2) for i in range(2)]
        strong = [fake_item(f"S{i}", None, "modern", "2026-12-01", 0.2, qtype="选择题", decayed=0.9) for i in range(2)]
        fresh = [fake_item("NW", None, "modern", "2026-12-01", 0.3, qtype="意象作用题", reviews=0, status="新录入", decayed=0),
                 fake_item("NS", None, "modern", "2026-12-01", 0.3, qtype="选择题", reviews=0, status="新录入", decayed=0)]
        plan = self.plan(reviewed + strong + fresh, budget=5, fill=True)
        self.assertEqual(plan["weak"], [{"genre": "modern", "qtype": "意象作用题"}])
        self.assertIn("NW", [c["id"] for c in plan["items"]])
        self.assertNotIn("NS", [c["id"] for c in plan["items"]])

    def test_recent_items_not_pulled_forward(self):
        items = [fake_item("Q1", None, "dictation", "2026-12-01", 0.5, last="2026-09-30")]
        self.assertEqual(self.plan(items, fill=True)["items"], [])


class LibraryAndRecordsTests(TempVault):
    def setUp(self):
        super().setUp()
        self.ids = creation.commit_draft(self.vault, {"id": "D-x", "images": []}, _group_a())["item_ids"]

    def test_facets_group_and_paging(self):
        data = library.list_items(self.vault, limit=1)            # _group_a：1 道现代文 + 1 道默写（另一道本稿重复）
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["facets"]["status"]["新录入"], 2)
        self.assertEqual(data["facets"]["kind"], {"skill": 1, "recall": 1})
        self.assertEqual(data["facets"]["added"]["7"], 2)
        self.assertEqual(data["facets"]["last"]["never"], 2)
        only = library.list_items(self.vault, genre="dictation")
        self.assertEqual(only["total"], 1)
        self.assertEqual(only["facets"]["genre"]["modern"], 1)      # 分面计数不受本维度筛选影响
        grouped = library.list_items(self.vault, group="material")
        self.assertEqual(grouped["total_groups"], 2)
        self.assertEqual(sum(g["stats"]["total"] for g in grouped["groups"]), 2)
        found = library.list_items(self.vault, q=self.ids[0])
        self.assertEqual([r["id"] for r in found["items"]], [self.ids[0]])

    def test_filters_by_last_grade_and_history(self):
        from clms import projections
        sess = sessions.create(self.vault, self.ids)
        self.assertEqual(sessions.open_item_ids(projections.get_state(self.vault)), set(self.ids))
        sessions.grade(self.vault, sess["id"], self.ids[0], 1, "漏了象征")
        self.assertEqual(sessions.open_item_ids(projections.get_state(self.vault)), {self.ids[1]})
        records.add(self.vault, self.ids[1], 3)                     # 补记（不属于复习）
        low = library.list_items(self.vault, grade="low")
        self.assertEqual([r["id"] for r in low["items"]], [self.ids[0]])
        self.assertEqual(library.list_items(self.vault, last="7")["total"], 2)
        self.assertEqual(records.list_records(self.vault, has_note=True)["total"], 1)
        self.assertEqual(records.list_records(self.vault, grade="high")["total"], 1)
        self.assertEqual(records.list_records(self.vault, genre="dictation")["total"], 1)
        rec = records.list_records(self.vault, grade="low")["records"][0]
        self.assertEqual(rec["material_title"], "老街的灯")
        page = records.list_records(self.vault, limit=1, offset=1)
        self.assertEqual((page["total"], len(page["records"])), (2, 1))


LONG_TEXT = "①老街在城的东头，街不长。\n②修鞋的周伯的灯最暗，光只够照亮手里的鞋。\n③后来老街要拆了，一时竟不知是灯照着街，还是街托着灯。\n④如今城东是一片新楼。"


def _group_long():
    from clms import draft_schema
    return draft_schema.normalize_groups([
        {"genre": "现代文阅读", "material": {"title": "老街的灯", "author": "佚名", "text": LONG_TEXT},
         "items": [{"no": "7", "qtype": "意象作用题", "stem": "分析“灯”的作用。", "answer": "①线索②象征", "score": 6},
                   {"no": "8", "qtype": "句子赏析题", "stem": "赏析第③段画线句。", "answer": "①设问②照托", "score": 4}]},
        {"genre": "默写", "dictation": [{"template": "床前明月光，{书写区域1}。", "blanks": {"1": "疑是地上霜"}}]},
    ])


class ReviewAssistantTests(TempVault):
    PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    def setUp(self):
        super().setUp()
        import fake_ai
        from clms.server import make_server
        self.fake = fake_ai
        self.ai = fake_ai.start(0)
        save_config(self.vault, {"ai_base_url": f"http://127.0.0.1:{self.ai.server_address[1]}/v1",
                                 "ai_api_key": "k", "ai_model": "fake"})
        self.ids = creation.commit_draft(self.vault, {"id": "D-x", "images": []}, _group_long())["item_ids"]
        self.sid = sessions.create(self.vault, self.ids)["id"]
        self.server = make_server(self.vault, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.ai.shutdown()
        self.ai.server_close()
        super().tearDown()

    def ask(self, body):
        req = urllib.request.Request(self.base + "/api/review/ai", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        self.fake.REQUESTS.clear()
        with urllib.request.urlopen(req, timeout=20) as res:
            text = res.read().decode()
        return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]

    def sent(self):
        """这次助手请求发给模型的每一轮请求体的全部文字（按轮）。"""
        out = []
        for body in self.fake.REQUESTS:
            parts = []
            for m in body["messages"]:
                content = m.get("content")
                parts += [c.get("text", "") for c in content] if isinstance(content, list) else [content or ""]
            out.append("\n".join(parts))
        return out

    def test_context_hides_answer_until_revealed(self):
        job = review_ai.prepare(self.vault, {"session_id": self.sid, "item_id": self.ids[0], "text": "怎么想"})
        text = review_ai.context_text(self.vault, job)                    # 旧做法：整道题并进上下文
        self.assertIn("## 参考答案", text)
        self.assertIn("老街的灯", text)
        self.assertIn("还没对答案", text)
        self.assertIn("还没对这道题的答案", review_ai.index_text(self.vault, job))
        job["revealed"] = True
        self.assertNotIn("还没对答案", review_ai.context_text(self.vault, job))
        self.assertNotIn("还没对这道题的答案", review_ai.index_text(self.vault, job))

    def test_parse_suggestion(self):
        reply, sug = review_ai.parse_suggestion('分析……\n【建议】{"grade": 2, "note": "漏了象征"}', "modern", "grade")
        self.assertEqual(reply, "分析……")
        self.assertEqual(sug, {"grade": 2, "grade_label": "基本", "note": "漏了象征"})
        _, bad = review_ai.parse_suggestion('【建议】{"grade": 2}', "dictation", "grade")   # 默写没有 2 分
        self.assertIsNone(bad)
        _, none = review_ai.parse_suggestion("只是回答", "modern", "grade")
        self.assertIsNone(none)

    def test_stream_ask_grade_feedback(self):
        events = self.ask({"session_id": self.sid, "item_id": self.ids[0], "mode": "ask", "text": "这题怎么想"})
        self.assertEqual(events[0]["type"], "start")
        self.assertTrue(events[0]["agent"])
        self.assertTrue(any(e["type"] == "delta" and e["kind"] == "text" for e in events))
        self.assertTrue(any(e["type"] == "block" and e["kind"] == "thinking" for e in events))   # 思考逐字推给前端
        self.assertIn("作用", events[-1]["reply"])
        self.assertIsNone(events[-1]["suggestion"])
        nothing = self.ask({"session_id": self.sid, "item_id": self.ids[0], "mode": "grade"})
        self.assertIsNone(nothing[-1]["suggestion"])                   # 没有作答：不编分
        history = [{"role": "user", "text": "我的作答：灯是线索"}, {"role": "assistant", "text": "收到", "tools": ["看第 1 题"]}]
        graded = self.ask({"session_id": self.sid, "item_id": self.ids[0], "mode": "grade", "history": history})
        self.assertEqual(graded[-1]["suggestion"]["grade"], 2)
        self.assertNotIn("【建议】", graded[-1]["reply"])
        self.assertIn("这一轮查过：看第 1 题", self.sent()[0])        # 上一轮查过什么只留一句，内容不重发
        fb = self.ask({"session_id": self.sid, "item_id": self.ids[0], "mode": "feedback"})
        self.assertIn("note", fb[-1]["suggestion"])
        self.assertEqual(records.list_records(self.vault)["total"], 0)  # 助手本身不写记录

    def test_agent_reads_by_tools_not_injection(self):
        events = self.ask({"session_id": self.sid, "item_id": self.ids[0], "mode": "ask", "text": "这题怎么想"})
        tools = {e["id"]: e for e in events if e["type"] == "tool"}
        names = [e["name"] for e in events if e["type"] == "tool" and e["status"] == "running"]
        self.assertEqual(names, ["question_get", "material_read"])
        self.assertTrue(all(tools[k]["status"] == "done" for k in tools))
        self.assertEqual(events[-1]["tools"], 2)
        done = [e for e in events if e["type"] == "tool" and e["status"] == "done"]
        self.assertIn("①线索②象征", done[0]["result"])                 # 结果也推给前端（可展开看）
        self.assertIn("[2] ②修鞋", done[1]["result"])
        self.assertNotIn("[3]", done[1]["result"])                      # 只读了 1–2 段
        first, last = self.sent()[0], self.sent()[-1]
        self.assertNotIn("修鞋的周伯", first)                            # 第一轮：原文不在上下文里
        self.assertNotIn("①线索②象征", first)                          # 参考答案也要查
        self.assertIn("学生正在看：第 1 题", first)
        self.assertIn("修鞋的周伯", last)                                # 查过之后才有
        self.assertNotIn("如今城东", last)                               # 没读的段落始终不发

    def test_tools_ranges_and_scope(self):
        from clms import review_tools
        from clms.harness import ToolError
        job = review_ai.prepare(self.vault, {"session_id": self.sid, "item_id": self.ids[1], "text": "?"})
        tools = {t.name: t for t in review_tools.tools(self.vault, job)}
        mid = self.ids and sessions.view(self.vault, self.sid)["items"][0]["material_id"]
        run = lambda name, **a: tools[name].execute(a, None).content          # noqa: E731
        self.assertEqual(review_tools.parse_range("2-3、1", 4), [2, 3, 1])
        self.assertEqual(review_tools.parse_range("3–9", 4), [3, 4])
        self.assertIn("[3] ③后来", run("material_read", paragraphs="3"))
        found = run("material_read", material_id=mid, query="新楼")
        self.assertIn("[4]", found)
        self.assertNotIn("[1]", found)
        self.assertIn("没有找到", run("material_read", query="不存在的句子"))
        self.assertIn("第 2 题", run("question_get"))                    # 默认是学生正在看的那道
        self.assertIn("还没对这道题的答案", run("question_get"))
        self.assertIn("疑是地上霜", run("question_get", n=3))
        self.assertIn("M-", run("review_outline"))
        self.assertIn("以前没有复习过", run("item_history", n=1))
        with self.assertRaises(ToolError):
            run("question_get", n=9)
        with self.assertRaises(ToolError):
            run("material_read", material_id="M-999999")
        with self.assertRaises(ToolError):
            run("material_read", paragraphs="第二段")
        self.assertEqual(tools["material_read"].label({"paragraphs": "2-3"}), "读《老街的灯》第 2-3 段")

    def test_quote_refs_sent_with_location(self):
        mid = sessions.view(self.vault, self.sid)["items"][0]["material_id"]
        refs = [{"text": "一时竟不知是灯照着街，还是街托着灯。", "where": {"material_id": mid, "para": "3"}},
                {"text": "赏析第③段画线句。", "where": {"n": "2", "part": "stem"}}]
        events = self.ask({"session_id": self.sid, "item_id": self.ids[1], "mode": "ask", "refs": refs})
        self.assertEqual(events[-1]["type"], "done")
        first = self.sent()[0]
        self.assertIn(f"（引用 1：《老街的灯》第 3 段（{mid}））", first)
        self.assertIn("> 一时竟不知是灯照着街", first)
        self.assertIn("（引用 2：第 2 题的题干）", first)
        self.assertIn(review_ai.QUOTE_TEXT, first)                       # 只引用不写字：默认一句

    def test_photo_saved_sent_and_kept_for_next_turn(self):
        events = self.ask({"session_id": self.sid, "item_id": self.ids[0], "mode": "grade",
                           "images": [{"name": "a.png", "data": self.PNG}]})
        self.assertEqual(len(events[0]["images"]), 1)
        self.assertEqual(events[-1]["suggestion"]["grade"], 2)         # 假模型看到照片就当有作答
        history = [{"role": "user", "text": "", "images": events[0]["images"]}, {"role": "assistant", "text": "收到"}]
        again = self.ask({"session_id": self.sid, "item_id": self.ids[0], "mode": "grade", "history": history})
        self.assertEqual(again[-1]["suggestion"]["grade"], 2)          # 上一轮的照片仍按原图发

    def test_legacy_injection_when_agent_mode_off(self):
        save_config(self.vault, {"ai_agent": False})
        events = self.ask({"session_id": self.sid, "item_id": self.ids[0], "mode": "ask", "text": "这题怎么想"})
        self.assertFalse(events[0]["agent"])
        self.assertFalse(any(e["type"] == "tool" for e in events))
        self.assertIn("修鞋的周伯", self.sent()[0])                     # 旧做法：原文整篇并进第一条消息
        self.assertNotIn("tools", self.fake.REQUESTS[0])
        self.assertIn("作用", events[-1]["reply"])

    def test_rejects_item_outside_session(self):
        req = urllib.request.Request(self.base + "/api/review/ai", method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"session_id": self.sid, "item_id": "Q-999999", "text": "?"}).encode())
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
