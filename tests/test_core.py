"""后端单测 + 集成测试（unittest，无第三方依赖）。python3 -m unittest discover -s tests -q"""

import datetime
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from clms import ai_assist, creation, dictation, draft_schema, ledger, projections, scheduling, sessions  # noqa: E402
from clms.common import chinese_only, save_config  # noqa: E402


class TempVault(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp(prefix="clms-test-")
        projections.reset_state(self.vault)

    def tearDown(self):
        projections.reset_state(self.vault)
        shutil.rmtree(self.vault, ignore_errors=True)


class DictationTests(unittest.TestCase):
    def test_chinese_only_ignores_punctuation(self):
        self.assertEqual(chinese_only("床前明月光,疑是地上霜."), chinese_only("床前明月光，疑是地上霜。"))

    def test_split_each_blank_into_item(self):
        units = dictation.split_entry({"template": "《春望》：“{书写区域1}，{书写区域2}。”",
                                       "blanks": {"1": "感时花溅泪", "2": "恨别鸟惊心"}})
        self.assertEqual(len(units), 2)
        self.assertEqual(units[0]["prompt"], "《春望》：“{书写区域}，恨别鸟惊心。”")
        self.assertEqual(units[1]["prompt"], "《春望》：“感时花溅泪，{书写区域}。”")

    def test_dedupe_key_same_across_punctuation_and_context(self):
        a = dictation.split_entry({"template": "床前明月光，{书写区域1}。", "blanks": {"1": "疑是地上霜"}})[0]
        b = dictation.split_entry({"template": "床前明月光,{书写区域1}.", "blanks": ["疑是地上霜"]})[0]
        c = dictation.split_entry({"template": "《静夜思》写月光如霜的句子：{书写区域1}", "blanks": {"1": "疑是地上霜。"}})[0]
        self.assertEqual(a["key"], b["key"])
        self.assertEqual(a["key"], c["key"])

    def test_short_answer_key_includes_context(self):
        a = dictation.dedupe_key("之", "学而时习{书写区域}")
        b = dictation.dedupe_key("之", "三人行必有我师焉，择其善者而从{书写区域}")
        self.assertNotEqual(a, b)

    def test_full_width_braces_and_problems(self):
        self.assertEqual(dictation.blank_numbers("甲｛书写区域1｝乙{ 书写区域 2 }"), ["1", "2"])
        problems = dictation.check_entry({"template": "{书写区域1}，{书写区域2}", "blanks": {"1": "某句"}})
        self.assertTrue(any("书写区域2" in p for p in problems))


class LedgerTests(TempVault):
    def test_verify_cli_runs_with_gbk_console(self):
        env = {**os.environ, "PYTHONIOENCODING": "gbk"}
        command = [sys.executable, os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                                "clms_engine.py"), "--vault", self.vault, "verify"]
        result = subprocess.run(command, env=env, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("gbk", errors="replace"))
        self.assertIn("[OK] 提交链完整", result.stdout.decode("gbk"))

    def test_chain_verifies_and_detects_tamper(self):
        ledger.append_commit(self.vault, "t", "x.test", "a", {"n": 1})
        ledger.append_commit(self.vault, "t", "x.test", "b", {"n": 2})
        self.assertTrue(ledger.verify_ledger(self.vault)["ok"])
        db = sqlite3.connect(ledger.ledger_path(self.vault))
        db.execute("UPDATE commits SET payload='{\"n\":9}' WHERE seq=1")
        db.commit()
        db.close()
        self.assertFalse(ledger.verify_ledger(self.vault)["ok"])

    def test_transaction_rolls_back_ids(self):
        with self.assertRaises(RuntimeError):
            ledger.transact(self.vault, lambda tx: (tx.next_id("Q"), (_ for _ in ()).throw(RuntimeError("x"))))
        item_id, _ = ledger.transact(self.vault, lambda tx: tx.next_id("Q"))
        self.assertEqual(item_id, "Q-000001")


class AIAssistTests(TempVault):
    def test_output_limit_reports_truncated_draft(self):
        save_config(self.vault, {"ai_base_url": "http://localhost/v1", "ai_api_key": "test",
                                 "ai_model": "test", "ai_max_tokens": 6000})
        reply = {"choices": [{"finish_reason": "length", "message": {"content": '{"groups": ['}}],
                 "usage": {"completion_tokens_details": {"reasoning_tokens": 5052}}}
        with patch("clms.ai_assist.urllib.request.urlopen",
                   return_value=io.BytesIO(json.dumps(reply).encode("utf-8"))):
            with self.assertRaisesRegex(ValueError, "6000 token 上限.*5052 token.*草稿没有生成完整"):
                ai_assist.call_model(self.vault, "测试", [])


class SchedulingTests(unittest.TestCase):
    wd = [1, 4, 6]

    def test_due_aligned_to_review_day(self):
        created = "2026-09-28"                       # 周一
        d = scheduling.derive(created, [], self.wd, datetime.date(2026, 9, 28))
        self.assertEqual(d["status"], "新录入")
        self.assertEqual(datetime.date.fromisoformat(d["due"]).weekday() in self.wd, True)
        self.assertGreaterEqual(d["due"], "2026-09-30")

    def test_two_full_marks_master_then_revive(self):
        ev = [{"kind": "review", "grade": 3, "at": "2026-10-01"}, {"kind": "review", "grade": 3, "at": "2026-10-06"}]
        d = scheduling.derive("2026-09-28", ev, self.wd, datetime.date(2026, 10, 6))
        self.assertEqual(d["status"], "已掌握")
        self.assertGreater(d["interval"], 40)

    def test_reencounter_counts_as_miss_and_leech(self):
        ev = [{"kind": "review", "grade": 0, "at": "2026-10-01"}, {"kind": "reencounter", "at": "2026-10-03"},
              {"kind": "review", "grade": 1, "at": "2026-10-06"}]
        d = scheduling.derive("2026-09-28", ev, self.wd, datetime.date(2026, 10, 6))
        self.assertTrue(d["leech"])
        self.assertEqual(d["reviews"], 2)

    def test_plan_bundles_material_and_respects_budget(self):
        def item(i, mid, genre, due, prio):
            return {"id": i, "material_id": mid, "genre": genre, "qtype": "", "order": 0,
                    "sched": {"due": due, "status": "待攻克", "priority": prio, "decayed": 0.1, "leech": False,
                              "reviews": 1, "overdue_days": 0}}
        items = [item("Q1", "M1", "modern", "2026-10-01", 0.9), item("Q2", "M2", "modern", "2026-10-01", 0.8),
                 item("Q3", "M1", "modern", "2026-10-01", 0.1), item("Q4", None, "dictation", "2026-10-01", 0.5)]
        plan = scheduling.plan_session(items, 16, datetime.date(2026, 10, 1), datetime.date(2026, 10, 1), fill=False)
        ids = [c["id"] for c in plan["items"]]
        self.assertIn("Q3", ids)                     # 与 Q1 同篇，顺带一起做
        self.assertNotIn("Q2", ids)                  # 预算不够再读一篇
        self.assertLessEqual(plan["minutes"], 16)


def _group_a():
    return draft_schema.normalize_groups([
        {"genre": "现代文阅读", "material": {"title": "老街的灯", "text": "老街在城的东头，街不长，两旁是青砖的铺面。"},
         "items": [{"no": "7", "qtype": "意象作用题", "stem": "分析“灯”的作用。", "answer": "①线索②象征", "score": 6}]},
        {"genre": "默写", "dictation": [
            {"template": "床前明月光，{书写区域1}。", "blanks": {"1": "疑是地上霜"}},
            {"template": "床前明月光,{书写区域1}.", "blanks": {"1": "疑是地上霜"}}]},
    ])


class CreationTests(TempVault):
    def test_normalize_and_diff(self):
        groups = _group_a()
        self.assertEqual(groups[0]["genre"], "modern")
        self.assertEqual(groups[1]["genre"], "dictation")
        self.assertEqual(groups[0]["items"][0]["blank_lines"], 7)      # 缺省按分值估
        changed = json.loads(json.dumps(groups))
        changed[0]["items"][0]["answer"] = "新答案"
        labels = [c["label"] for c in draft_schema.diff(groups, changed)]
        self.assertEqual(labels, ["第 7 题 · 答案"])

    def test_commit_dedupes_within_draft_and_against_library(self):
        draft = {"id": "D-test-1", "images": []}
        first = creation.commit_draft(self.vault, draft, _group_a())
        self.assertEqual(first["created"], 2)                  # 1 阅读 + 1 默写（同草稿重复被跳过）
        self.assertEqual(first["skipped"], 1)
        note = creation.annotate(self.vault, _group_a())
        self.assertEqual(note["dup_units"], 3)
        second = creation.commit_draft(self.vault, {"id": "D-test-2", "images": []}, _group_a())
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["reencountered"], 2)
        state = projections.get_state(self.vault)
        self.assertEqual(len(state.materials), 1)
        item = state.item_view(first["item_ids"][1], projections.context(self.vault))
        self.assertEqual(item["encounters"], 2)

    def test_fuzzy_material_and_item_match(self):
        text = "①老街在城的东头，街不长，两旁是青砖的铺面。我小时候最喜欢傍晚，那时各家的灯一盏一盏亮起来。"
        first = draft_schema.normalize_groups([{"genre": "现代文", "material": {"title": "老街的灯", "text": "老街的灯\n" + text},
                                                "items": [{"no": "7", "stem": "文中多次写到“灯”，请分析其作用。", "answer": "略"}]}])
        creation.commit_draft(self.vault, {"id": "D-f1", "images": []}, first)
        # 第二次拍照：没有标题行，且有两个字识别不同（灯→镫、街→衔），题干标点也不同
        again = draft_schema.normalize_groups([{"genre": "现代文", "material": {"title": "老街的灯", "text": text.replace("盏", "蓋", 1).replace("铺", "捕")},
                                                "items": [{"no": "7", "stem": "文中多次写到灯,请分析其作用", "answer": "略"},
                                                          {"no": "8", "stem": "赏析第③段画线句。", "answer": "略"}]}])
        note = creation.annotate(self.vault, again)
        self.assertIsNotNone(note["groups"]["g1"]["material_match"])
        self.assertEqual(note["new_units"], 1)
        result = creation.commit_draft(self.vault, {"id": "D-f2", "images": []}, again)
        self.assertEqual((result["created"], result["reencountered"]), (1, 1))
        self.assertEqual(len(projections.get_state(self.vault).materials), 1)

    def test_item_stems_keep_paragraph_numbers(self):
        from clms.projections import item_key
        self.assertNotEqual(item_key("M-1", "赏析第③段画线句。"), item_key("M-1", "赏析第⑤段画线句。"))
        self.assertEqual(item_key("M-1", "赏析第③段画线句。"), item_key("M-1", "赏析第3段画线句"))

    def test_short_poem_not_merged_into_long_text(self):
        poem = "空山新雨后，天气晚来秋。明月松间照，清泉石上流。竹喧归浣女，莲动下渔舟。随意春芳歇，王孙自可留。"
        essay = "我读王维，最爱这几句：" + poem + "后来到了山里，才知道诗里写的不是风景，而是一种心境。" * 3
        creation.commit_draft(self.vault, {"id": "D-p1", "images": []}, draft_schema.normalize_groups(
            [{"genre": "现代文", "material": {"text": essay}, "items": [{"stem": "概括作者的感受", "answer": "略"}]}]))
        state = projections.get_state(self.vault)
        self.assertIsNone(state.match_material("modern", poem))

    def test_session_grade_regrade_and_void(self):
        result = creation.commit_draft(self.vault, {"id": "D-x", "images": []}, _group_a())
        sess = sessions.create(self.vault, result["item_ids"])
        sid, qid = sess["id"], result["item_ids"][0]
        sessions.grade(self.vault, sid, qid, 1)
        sessions.grade(self.vault, sid, qid, 3)                 # 改评分：旧的被作废
        view = sessions.view(self.vault, sid)
        self.assertEqual(view["progress"]["done"], 1)
        item = projections.get_state(self.vault).item_view(qid, projections.context(self.vault))
        self.assertEqual(item["sched"]["reviews"], 1)
        sessions.void_grade(self.vault, sid, qid)
        self.assertEqual(sessions.view(self.vault, sid)["progress"]["done"], 0)
        self.assertTrue(ledger.verify_ledger(self.vault)["ok"])


class ServerFlowTests(TempVault):
    """真起服务 + 假模型（旧的一次性识图 / 整份修订，ai_agent=False）：上传 → 识别 → 对话修订 → 入库 → 排复习 → 评分 → 打印。"""

    AGENT = False

    def setUp(self):
        super().setUp()
        import itertools
        import fake_ai
        from clms.server import make_server
        fake_ai._cycle = itertools.cycle([fake_ai.SET_A, fake_ai.SET_B, fake_ai.SET_C])
        self.ai = fake_ai.start(0)
        save_config(self.vault, {"ai_base_url": f"http://127.0.0.1:{self.ai.server_address[1]}/v1",
                                 "ai_api_key": "k", "ai_model": "fake", "ai_agent": self.AGENT})
        self.server = make_server(self.vault, "127.0.0.1", 0)
        import threading
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.ai.shutdown()
        self.ai.server_close()
        super().tearDown()

    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def wait_ready(self, draft_id):
        for _ in range(100):
            _, d = self.call(f"/api/draft?id={draft_id}")
            if d["status"] not in ("queued", "extracting", "thinking"):
                return d
            time.sleep(0.05)
        self.fail("草稿一直在处理中")

    def test_full_flow(self):
        png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        code, res = self.call("/api/drafts", {"images": [{"name": "a.png", "data": png}]})
        self.assertEqual(code, 200)
        self.assertEqual(res["drafts"][0]["status"], "staged")          # 上传后先准备，不直接执行
        self.call("/api/draft/start", {"id": res["drafts"][0]["id"]})
        draft = self.wait_ready(res["drafts"][0]["id"])
        self.assertEqual(draft["status"], "ready")
        self.assertEqual([step["id"] for step in draft["activity"]["steps"]],
                         ["queue", "images", "model", "parse", "save"])
        self.assertTrue(all(step["status"] == "done" for step in draft["activity"]["steps"]))
        self.assertTrue(draft["activity"]["finished_at"])
        self.assertEqual([g["genre"] for g in draft["groups"]], ["modern", "dictation"])
        self.assertEqual(draft["dedupe"]["new_units"], 6)
        code, _ = self.call("/api/draft/message", {"id": draft["id"], "text": "第7题答案按采分点重写，留白 8 行"})
        draft = self.wait_ready(draft["id"])
        self.assertEqual([step["id"] for step in draft["activity"]["steps"]],
                         ["queue", "context", "model", "parse", "save"])
        last = draft["messages"][-1]
        self.assertEqual({c["field"] for c in last["changes"]}, {"answer", "blank_lines"})
        item = next(i for i in draft["groups"][0]["items"] if i["no"] == "7")
        self.assertEqual(item["blank_lines"], 8)
        code, _ = self.call("/api/draft/restore", {"id": draft["id"], "revision": last["base_revision"]})
        self.assertEqual(code, 200)
        code, res = self.call("/api/draft/commit", {"id": draft["id"]})
        self.assertEqual(code, 200, res)
        self.assertEqual(res["committed"]["created"], 6)
        code, plan = self.call("/api/sessions/plan", {"minutes": 60})
        self.assertGreater(len(plan["items"]), 0)
        code, sess = self.call("/api/sessions", {"item_ids": [p["id"] for p in plan["items"]], "minutes": 60})
        self.assertEqual(code, 200)
        code, graded = self.call("/api/session/grade", {"session_id": sess["id"], "item_id": sess["items"][0]["id"], "grade": 2})
        self.assertEqual(graded["session"]["progress"]["done"], 1)
        with urllib.request.urlopen(self.base + f"/print/session?id={sess['id']}&answers=1") as res:
            page = res.read().decode()
        self.assertIn("参考答案", page)
        self.assertIn('class="blank"', page)
        code, summary = self.call("/api/summary")
        self.assertEqual(summary["total"], 6)
        code, err = self.call("/api/draft/commit", {"id": draft["id"]})
        self.assertEqual(code, 400)

    def test_cross_origin_post_rejected(self):
        req = urllib.request.Request(self.base + "/api/config", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
