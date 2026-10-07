"""作文真实领域门禁：版本、OCR、校对、不可变评价、自由分类与旧库兼容。"""

import base64
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from clms import essays, essays_ocr, ledger, projections

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=")


class EssayTests(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp(prefix="clms-essays-")
        self.prompt = essays.create_prompt(self.vault, "成长", "请以成长为题写一篇完整作文。", "不少于 800 字")
        self.attempt = essays.create_attempt(self.vault, self.prompt["id"], "周日练习")

    def tearDown(self):
        projections.reset_state(self.vault)
        shutil.rmtree(self.vault)

    def upload(self, pages=1):
        return essays.create_version(self.vault, self.attempt["id"],
                                     [{"name": f"第{i}页.png", "data": base64.b64encode(PNG + bytes([i])).decode()}
                                      for i in range(pages)])

    def confirm(self, version, text="我的成长\n那天，母亲陪我走过长街。"):
        corrected = essays.correct_version(self.vault, version["id"], text, version["revision"])
        return essays.confirm_version(self.vault, version["id"], revision=corrected["revision"])

    def test_multiple_pages_are_one_version_and_independent_attempts(self):
        version = self.upload(3)
        attempt = essays.attempt_detail(self.vault, self.attempt["id"])
        self.assertEqual(len(version["images"]), 3)
        self.assertEqual(attempt["version_count"], 1)
        self.assertEqual(attempt["modification_count"], 0)
        next_attempt = essays.create_attempt(self.vault, self.prompt["id"])
        self.assertEqual(next_attempt["version_count"], 0)
        self.assertEqual(essays.prompt_detail(self.vault, self.prompt["id"])["attempt_count"], 2)

    def test_ocr_failed_retry_raw_text_preserved_and_correction_is_not_new_version(self):
        version = self.upload(2)
        def failure(vault, v):
            raise ValueError("网络失败")
        failed = essays_ocr.start_ocr(self.vault, version["id"], runner=failure, background=False)
        self.assertEqual(failed["status"], "ocr_failed")
        self.assertTrue(failed["can_retry"])
        raw_text = "我长大了，走在【存疑：街/衔】上，错字保留。"
        retried = essays_ocr.start_ocr(self.vault, version["id"], runner=lambda *_: {
            "text": raw_text, "raw_response": '{"text":"原始模型完整回复"}',
            "uncertainties": [{"page": 2, "text": "街/衔"}], "model": "vision"}, background=False)
        self.assertEqual(retried["ocr_attempts"], 2)
        self.assertEqual(retried["status"], "proofreading")
        self.assertEqual(retried["text"], "")
        corrected_text = raw_text.replace("【存疑：街/衔】", "街")
        corrected = essays.correct_version(self.vault, version["id"], corrected_text, retried["revision"])
        confirmed = essays.confirm_version(self.vault, version["id"], revision=corrected["revision"])
        self.assertEqual(confirmed["raw_ocr_text"], raw_text)
        self.assertEqual(confirmed["raw_ocr_response"], '{"text":"原始模型完整回复"}')
        self.assertEqual(confirmed["text"], corrected_text)
        self.assertEqual(confirmed["corrected_text"], corrected_text)
        self.assertEqual(essays.attempt_detail(self.vault, self.attempt["id"])["modification_count"], 0)

    def test_confirmed_text_never_overwritten_and_duplicate_confirm_is_idempotent(self):
        confirmed = self.confirm(self.upload())
        before = len(ledger.read_commits(self.vault))
        essays.confirm_version(self.vault, confirmed["id"], confirmed["text"])
        self.assertEqual(len(ledger.read_commits(self.vault)), before)
        with self.assertRaisesRegex(ValueError, "正式正文"):
            essays.correct_version(self.vault, confirmed["id"], "偷偷覆盖")
        with self.assertRaisesRegex(ValueError, "不可覆盖"):
            essays.confirm_version(self.vault, confirmed["id"], "偷偷覆盖")
        with self.assertRaisesRegex(ValueError, "自动覆盖"):
            essays_ocr.start_ocr(self.vault, confirmed["id"], runner=lambda *_: {"text": "偷偷覆盖"})
        self.assertEqual(essays.version_detail(self.vault, confirmed["id"])["text"], confirmed["text"])

    def test_revision_conflict_and_empty_confirmation(self):
        version = self.upload()
        corrected = essays.correct_version(self.vault, version["id"], "第一份校对", version["revision"])
        with self.assertRaisesRegex(ValueError, "刷新"):
            essays.correct_version(self.vault, version["id"], "旧页面内容", version["revision"])
        with self.assertRaisesRegex(ValueError, "刷新"):
            essays.confirm_version(self.vault, version["id"], revision=version["revision"])
        with self.assertRaisesRegex(ValueError, "不能为空"):
            essays.confirm_version(self.vault, version["id"], " ", corrected["revision"])

    def test_multiple_evaluations_stay_with_original_version(self):
        first = self.confirm(self.upload(), "第一稿正文")
        second = self.confirm(self.upload(), "第二稿增加细节")
        a = essays.add_evaluation(self.vault, first["id"], 47, "结构基本完整", strengths=["有细节"],
                                  issues=["第二段突兀"], suggestions=["重写过渡"], dimensions={"自由项": "成长主题"},
                                  evaluator="ChatGPT", source="mcp", model="external", metadata={"request_id": "a"})
        b = essays.add_evaluation(self.vault, first["id"], 49, "第二位评价者的看法", source="assistant")
        essays.add_evaluation(self.vault, second["id"], 53, "过渡改善")
        adopted = essays.adopt_evaluation(self.vault, first["id"], a["id"])
        self.assertEqual(adopted["adopted_evaluation_id"], a["id"])
        self.assertEqual([e["id"] for e in adopted["evaluations"]], [a["id"], b["id"]])
        self.assertEqual(adopted["text"], "第一稿正文")
        attempt = essays.attempt_detail(self.vault, self.attempt["id"])
        self.assertEqual(attempt["version_count"], 2)
        self.assertEqual(attempt["modification_count"], 1)
        self.assertEqual(len(attempt["versions"][1]["evaluations"]), 1)
        self.assertEqual(a["source"], "mcp")
        self.assertEqual(a["version_id"], first["id"])
        self.assertEqual(a["max_score"], 60)
        with self.assertRaisesRegex(ValueError, "不属于"):
            essays.adopt_evaluation(self.vault, second["id"], a["id"])

    def test_total_score_boundaries_and_unconfirmed_evaluation(self):
        version = self.upload()
        with self.assertRaisesRegex(ValueError, "正式转写"):
            essays.add_evaluation(self.vault, version["id"], 47)
        self.confirm(version)
        for score in (-1, 61, True, "47", float("nan"), float("inf"), None):
            with self.subTest(score=score), self.assertRaises(ValueError):
                essays.add_evaluation(self.vault, version["id"], score)
        for score in (0, 60, 47.5):
            self.assertEqual(essays.add_evaluation(self.vault, version["id"], score)["total_score"], score)

    def test_notes_append_only_bind_to_exact_attempt_and_optional_version(self):
        first = self.confirm(self.upload())
        note = essays.add_note(self.vault, self.attempt["id"], "下一稿重点处理第二段和结尾。", first["id"], source="mcp")
        essays.add_note(self.vault, self.attempt["id"], "整次练习的观察。", source="assistant")
        attempt = essays.attempt_detail(self.vault, self.attempt["id"])
        self.assertEqual(len(attempt["notes"]), 2)
        self.assertEqual(len(essays.version_detail(self.vault, first["id"])["notes"]), 1)
        self.assertEqual(note["text"], "下一稿重点处理第二段和结尾。")
        other = essays.create_attempt(self.vault, self.prompt["id"])
        with self.assertRaisesRegex(ValueError, "不属于"):
            essays.add_note(self.vault, other["id"], "错误归属", first["id"])

    def test_free_classification_no_predefined_group_and_atomic_validation(self):
        custom = essays.create_classification(self.vault, "第二段的转折", source="mcp")
        self.assertEqual(custom["group"], "")
        self.assertEqual(essays.create_classification(self.vault, "第二段的转折")["id"], custom["id"])
        tagged = essays.classify(self.vault, "prompt", self.prompt["id"], [custom["id"]],
                                 ["成长", {"name": "记叙文", "group": "我自己的分组"}], source="assistant")
        self.assertEqual({c["name"] for c in tagged["classifications"]}, {"第二段的转折", "成长", "记叙文"})
        self.assertEqual(essays.list_prompts(self.vault, "成长")["total"], 1)
        self.assertEqual(essays.list_prompts(self.vault, classification_id=custom["id"])["total"], 1)
        before = len(ledger.read_commits(self.vault))
        with self.assertRaises(ValueError):
            essays.classify(self.vault, "prompt", self.prompt["id"], names=["应整体回滚", " "])
        self.assertEqual(len(ledger.read_commits(self.vault)), before)
        self.assertNotIn("应整体回滚", [c["name"] for c in essays.list_classifications(self.vault)])

    def test_old_ledger_replays_and_all_new_events_replay_without_scheduling(self):
        old = tempfile.mkdtemp(prefix="clms-old-essay-")
        try:
            ledger.append_commit(old, "old", "entry.commit", "旧题", {"materials": [], "items": []})
            state = projections.get_state(old)
            for attribute in ("essay_prompts", "essay_attempts", "essay_versions", "essay_evaluations", "essay_notes"):
                self.assertEqual(getattr(state, attribute), {})
        finally:
            projections.reset_state(old)
            shutil.rmtree(old)
        version = self.confirm(self.upload(3))
        essays.add_evaluation(self.vault, version["id"], 47)
        essays.add_note(self.vault, self.attempt["id"], "讨论笔记", version["id"])
        essays.classify(self.vault, "version", version["id"], names=["细节描写"])
        original = essays.attempt_detail(self.vault, self.attempt["id"])
        projections.reset_state(self.vault)
        self.assertEqual(essays.attempt_detail(self.vault, self.attempt["id"]), original)
        state = projections.get_state(self.vault)
        self.assertEqual(state.items, {})
        self.assertEqual(state.sessions, {})
        for commit in ledger.read_commits(self.vault):
            self.assertNotIn("sched", repr(commit["payload"]))
            self.assertTrue(hasattr(state, "_on_" + commit["commit_type"].replace(".", "_")))
        self.assertTrue(ledger.verify_ledger(self.vault)["ok"])

    def test_ocr_network_wait_does_not_hold_write_lock(self):
        version = self.upload()
        entered, release = threading.Event(), threading.Event()
        def slow(vault, current):
            entered.set()
            release.wait(3)
            return {"text": "请求后得到的原样转写"}
        essays_ocr.start_ocr(self.vault, version["id"], runner=slow)
        self.assertTrue(entered.wait(2))
        try:
            # 模型仍在等网络时，另一个正式 append 操作必须能完成。
            note = essays.add_note(self.vault, self.attempt["id"], "OCR 期间仍能操作")
            self.assertTrue(note["id"])
            with self.assertRaises(ValueError):
                essays.correct_version(self.vault, version["id"], "处理中不能抢写")
        finally:
            release.set()
        done = threading.Event()
        def observe():
            for _ in range(200):
                if essays.version_detail(self.vault, version["id"])["status"] != "ocr_running":
                    done.set()
                    return
                done.wait(0.01)
        watcher = threading.Thread(target=observe)
        watcher.start()
        watcher.join(3)
        self.assertTrue(done.is_set())

    def test_stale_ocr_result_cannot_overwrite_retry_and_restart_recovers(self):
        version = self.upload()
        old_token = essays_ocr._start(self.vault, version["id"])
        self.assertEqual(essays_ocr.recover(self.vault), 1)
        self.assertEqual(essays_ocr.recover(self.vault), 0)
        token = essays_ocr._start(self.vault, version["id"])
        essays_ocr._complete(self.vault, version["id"], old_token, {"text": "旧结果"})
        self.assertEqual(essays.version_detail(self.vault, version["id"])["status"], "ocr_running")
        essays_ocr._complete(self.vault, version["id"], token, {"text": "新结果"})
        self.assertEqual(essays.version_detail(self.vault, version["id"])["raw_ocr_text"], "新结果")

    def test_original_image_access_checks_version_membership(self):
        first, second = self.upload(1), self.upload(2)
        path = essays.version_image_path(self.vault, first["id"], first["images"][0])
        self.assertTrue(os.path.isfile(path))
        with self.assertRaisesRegex(ValueError, "不属于"):
            essays.version_image_path(self.vault, first["id"], second["images"][1])
        with self.assertRaises(ValueError):
            essays.version_image_path(self.vault, first["id"], "../../config.json")

    def test_ocr_prompt_only_transcribes_and_preserves_raw_model_response(self):
        version = self.upload(2)
        raw = '{"text":"错字：成涨。\\n【存疑：街】", "uncertainties":[]}'
        with patch.object(essays_ocr.ai_assist, "image_data_urls", return_value=["data:image/png;base64,x"]), \
                patch.object(essays_ocr.ai_assist, "call_model", return_value=raw) as call:
            result = essays_ocr.transcribe(self.vault, version)
        self.assertEqual(len(call.call_args.args[2]), 2)
        self.assertIn("禁止根据文意偷偷纠正", call.call_args.args[1])
        self.assertIn("不负责评价、润色或改写", call.call_args.args[1])
        self.assertEqual(result["text"], "错字：成涨。\n【存疑：街】")
        self.assertEqual(result["raw_response"], raw)

    def test_compare_versions_reports_insert_delete_and_rejects_other_attempt(self):
        first = self.confirm(self.upload(), "母亲陪我走过长街。")
        second = self.confirm(self.upload(), "母亲牵着我的手，陪我走过长街。")
        diff = essays.compare_versions(self.vault, first["id"], second["id"])
        self.assertEqual("".join(c["before"] for c in diff["changes"]), first["text"])
        self.assertEqual("".join(c["after"] for c in diff["changes"]), second["text"])
        self.assertTrue(any(c["kind"] != "equal" for c in diff["changes"]))
        other = essays.create_attempt(self.vault, self.prompt["id"])
        version = essays.create_version(self.vault, other["id"], [{"data": base64.b64encode(PNG).decode()}])
        self.confirm(version)
        with self.assertRaisesRegex(ValueError, "同一次练习"):
            essays.compare_versions(self.vault, first["id"], version["id"])


if __name__ == "__main__":
    unittest.main()
