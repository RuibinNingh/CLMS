"""v0.5：两种记忆类型、复习推荐（自选 / 移除 / 未完成复习）、题库分面筛选与分组、复习历史筛选、复习助手。"""

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


class ReviewAssistantTests(TempVault):
    def setUp(self):
        super().setUp()
        import fake_ai
        from clms.server import make_server
        self.ai = fake_ai.start(0)
        save_config(self.vault, {"ai_base_url": f"http://127.0.0.1:{self.ai.server_address[1]}/v1",
                                 "ai_api_key": "k", "ai_model": "fake"})
        self.ids = creation.commit_draft(self.vault, {"id": "D-x", "images": []}, _group_a())["item_ids"]
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
        with urllib.request.urlopen(req, timeout=20) as res:
            text = res.read().decode()
        return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]

    def test_context_hides_answer_until_revealed(self):
        job = review_ai.prepare(self.vault, {"session_id": self.sid, "item_id": self.ids[0], "text": "怎么想"})
        text = review_ai.context_text(self.vault, job)
        self.assertIn("## 参考答案", text)
        self.assertIn("老街的灯", text)
        self.assertIn("还没对答案", text)
        job["revealed"] = True
        self.assertNotIn("还没对答案", review_ai.context_text(self.vault, job))

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
        self.assertTrue(any(e["type"] == "delta" and e["kind"] == "text" for e in events))
        self.assertIn("作用", events[-1]["reply"])
        self.assertIsNone(events[-1]["suggestion"])
        nothing = self.ask({"session_id": self.sid, "item_id": self.ids[0], "mode": "grade"})
        self.assertIsNone(nothing[-1]["suggestion"])                   # 没有作答：不编分
        history = [{"role": "user", "text": "我的作答：灯是线索"}, {"role": "assistant", "text": "收到"}]
        graded = self.ask({"session_id": self.sid, "item_id": self.ids[0], "mode": "grade", "history": history})
        self.assertEqual(graded[-1]["suggestion"]["grade"], 2)
        self.assertNotIn("【建议】", graded[-1]["reply"])
        fb = self.ask({"session_id": self.sid, "item_id": self.ids[0], "mode": "feedback"})
        self.assertIn("note", fb[-1]["suggestion"])
        state_reviews = records.list_records(self.vault)["total"]
        self.assertEqual(state_reviews, 0)                             # 助手本身不写记录

    def test_rejects_item_outside_session(self):
        req = urllib.request.Request(self.base + "/api/review/ai", method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"session_id": self.sid, "item_id": "Q-999999", "text": "?"}).encode())
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

    def test_photo_saved_and_sent(self):
        png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        events = self.ask({"session_id": self.sid, "item_id": self.ids[0], "mode": "grade",
                           "images": [{"name": "a.png", "data": png}]})
        self.assertEqual(len(events[0]["images"]), 1)
        self.assertEqual(events[-1]["suggestion"]["grade"], 2)         # 假模型看到照片就当有作答


if __name__ == "__main__":
    unittest.main()
