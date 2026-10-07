"""审核权威、乐观锁与跨辅助库/领域库崩溃恢复的专项验证。"""

import concurrent.futures
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing

from clms import ai_review, creation, domain_ops, draft_schema, drafts, ledger, projections, runtime_history


class ReviewFoundationTests(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp(prefix="clms-review-")
        self.auth = dict(ai_review._AUTHORIZERS)
        ai_review.register_authorizer("mcp", lambda vault, tool, actor: None)
        result = creation.commit_draft(self.vault, {"id": "D-test", "images": []}, draft_schema.normalize_groups([{
            "genre": "modern", "material": {"title": "街灯", "text": "旧街的灯光照亮放学回家的孩子们。"},
            "items": [{"stem": "灯光的作用是什么？", "answer": "照亮道路，也象征温情。", "blank_lines": 4}]}]))
        self.item_id = result["item_ids"][0]
        self.material_id = result["material_ids"][0]

    def tearDown(self):
        ai_review._AUTHORIZERS.clear()
        ai_review._AUTHORIZERS.update(self.auth)
        projections.reset_state(self.vault)
        shutil.rmtree(self.vault)

    def proposal(self, request_id="req1", source="assistant"):
        return ai_review.propose(self.vault, source, "session.create", request_id,
                                 {"item_ids": [self.item_id], "minutes": 30, "title": "现代文复习"},
                                 actor={"key_id": "key1"} if source == "mcp" else {})

    def decide(self, row, choice="approve"):
        return ai_review.decide(self.vault, row["id"], row["revision"], choice, {"kind": "human", "channel": "web"})

    def test_formal_session_waits_and_duplicate_approve_only_creates_once(self):
        row = self.proposal()
        self.assertEqual(row["status"], "pending_confirmation")
        self.assertFalse(projections.get_state(self.vault).sessions)
        self.assertEqual(row["preview"]["count"], 1)
        first, second = self.decide(row), self.decide(row)
        self.assertEqual(first["status"], "applied")
        self.assertEqual(first["result"]["id"], second["result"]["id"])
        self.assertEqual(len(projections.get_state(self.vault).sessions), 1)
        self.assertEqual(len(second["decisions"]), 1)
        self.assertTrue(ledger.verify_ledger(self.vault)["ok"])

    def test_confirmation_card_and_center_race_for_same_authority(self):
        row = self.proposal()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.decide(row), range(2)))
        self.assertTrue(all(r["status"] in {"applying", "applied"} for r in results))
        self.assertEqual(len(projections.get_state(self.vault).sessions), 1)

    def test_reject_never_creates_session(self):
        row = self.decide(self.proposal(), "reject")
        self.assertEqual(row["status"], "rejected")
        self.assertFalse(projections.get_state(self.vault).sessions)
        self.assertEqual(self.decide(row)["status"], "rejected")

    def test_expired_operation_cannot_be_approved(self):
        row = self.proposal()
        with closing(sqlite3.connect(ai_review.path(self.vault))) as db:
            db.execute("UPDATE operations SET expires_at=0 WHERE operation_id=?", (row["id"],))
            db.commit()
        self.assertEqual(ai_review.get(self.vault, row["id"])["status"], "expired")
        self.assertEqual(self.decide(row)["status"], "expired")
        self.assertFalse(projections.get_state(self.vault).sessions)
        self.assertEqual(ai_review.counts(self.vault)["pending"], 0)

    def test_human_revision_is_bounded_and_retried_original_does_not_overwrite(self):
        payload = {"item_id": self.item_id, "changes": {"answer": "原提案"}}
        row = ai_review.propose(self.vault, "assistant", "item.update", "edit1", payload)
        revised = ai_review.update(self.vault, row["id"], 1, {"answer": "人工修订"})
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["revisions"][0]["payload"], payload)
        self.assertEqual(revised["original_payload"], payload)
        retried = ai_review.propose(self.vault, "assistant", "item.update", "edit1", payload)
        self.assertEqual(retried["payload"]["changes"]["answer"], "人工修订")
        with self.assertRaises(ai_review.ReviewError) as error:
            ai_review.update(self.vault, row["id"], 2, {"stem": "扩大原修改字段"})
        self.assertEqual(error.exception.code, "forbidden")
        with self.assertRaises(ai_review.ReviewError) as error:
            self.decide(row)
        self.assertEqual(error.exception.code, "revision_conflict")
        self.decide(revised)
        self.assertEqual(projections.get_state(self.vault).items[self.item_id]["answer"], "人工修订")

    def test_item_content_conflict_prevents_stale_write(self):
        row = ai_review.propose(self.vault, "assistant", "item.update", "edit",
                                {"item_id": self.item_id, "changes": {"answer": "过时提案"}})
        creation.update_item(self.vault, self.item_id, {"answer": "网页新答案"})
        outcome = self.decide(row)
        self.assertEqual(outcome["status"], "conflict")
        self.assertEqual(outcome["error_code"], "content_conflict")
        self.assertEqual(projections.get_state(self.vault).items[self.item_id]["answer"], "网页新答案")

    def test_material_content_and_session_item_snapshot_conflicts(self):
        material = ai_review.propose(self.vault, "assistant", "material.update", "material",
                                     {"material_id": self.material_id, "changes": {"title": "新标题"}})
        session = self.proposal()
        creation.update_material(self.vault, self.material_id, {"text": "原文已经更正，不接受旧提案。"})
        self.assertEqual(self.decide(material)["status"], "conflict")
        self.assertEqual(self.decide(session)["status"], "conflict")

    def test_mcp_cannot_self_approve_and_cannot_read_another_keys_operation(self):
        row = self.proposal(source="mcp")
        with self.assertRaises(ai_review.ReviewError) as error:
            ai_review.decide(self.vault, row["id"], 1, "approve", {"kind": "mcp", "key_id": "key1"})
        self.assertEqual(error.exception.code, "forbidden")
        self.assertEqual(ai_review.get(self.vault, row["id"], key_id="key1")["id"], row["id"])
        with self.assertRaises(ai_review.ReviewError):
            ai_review.get(self.vault, row["id"], key_id="key2")

    def test_live_key_revocation_prevents_approved_write(self):
        row = self.proposal(source="mcp")
        def forbidden(vault, tool, actor):
            raise ai_review.ReviewError("forbidden", "密钥已吊销", 403)
        ai_review.register_authorizer("mcp", forbidden)
        outcome = self.decide(row)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["error_code"], "forbidden")
        self.assertFalse(projections.get_state(self.vault).sessions)

    def test_same_request_content_conflicts_instead_of_overwrite(self):
        self.proposal()
        with self.assertRaises(ai_review.ReviewError) as error:
            ai_review.propose(self.vault, "assistant", "session.create", "req1",
                              {"item_ids": [self.item_id], "minutes": 40})
        self.assertEqual(error.exception.code, "request_conflict")

    def test_auxiliary_result_failure_recovers_native_receipt_without_reexecution(self):
        row = self.proposal()
        original_state = ai_review._state
        def state(vault, op, status, **kwargs):
            if status == "applied":
                raise sqlite3.OperationalError("simulated audit disk failure")
            return original_state(vault, op, status, **kwargs)
        with patch.object(ai_review, "_state", state):
            result = self.decide(row)
        self.assertEqual(result["status"], "applied")
        self.assertTrue(result["recovery_pending"])
        self.assertEqual(ai_review.get(self.vault, row["id"])["status"], "applying")
        with patch.object(domain_ops, "execute", side_effect=AssertionError("recovery must not execute")):
            self.assertEqual(ai_review.recover(self.vault)["reconciled"], 1)
        self.assertEqual(ai_review.get(self.vault, row["id"])["status"], "applied")
        self.assertEqual(len(projections.get_state(self.vault).sessions), 1)

    def test_abandoned_apply_without_receipt_is_interrupted_and_not_replayed(self):
        row = self.proposal()
        ai_review._state(self.vault, row["id"], "applying")
        with patch.object(domain_ops, "execute", side_effect=AssertionError("must not execute")):
            self.assertEqual(ai_review.recover(self.vault)["interrupted"], 1)
        self.assertEqual(self.decide(row)["status"], "interrupted")
        self.assertFalse(projections.get_state(self.vault).sessions)

    def test_low_risk_draft_write_has_native_receipt_and_audit(self):
        payload = {"genre": "modern", "name": "助手草稿", "groups": [{"genre": "modern", "items": [
            {"stem": "新问题", "answer": "新答案"}]}]}
        row = ai_review.propose(self.vault, "assistant", "draft.create", "draft1", payload)
        self.assertEqual(row["status"], "applied")
        self.assertFalse(row["decisions"])
        draft_id = row["result"]["id"]
        native = domain_ops.receipt(self.vault, row["id"], "draft.create")
        self.assertEqual(native["digest"], row["effective_digest"])
        self.assertEqual(drafts.load(self.vault, draft_id)["name"], "助手草稿")
        self.assertEqual(ai_review.propose(self.vault, "assistant", "draft.create", "draft1", payload)["result"]["id"], draft_id)
        ai_review._state(self.vault, row["id"], "running", result={})
        ai_review.recover(self.vault)
        self.assertEqual(ai_review.get(self.vault, row["id"])["result"]["id"], draft_id)

    def test_native_transaction_receipt_rolls_back_with_learning_write(self):
        def build(tx):
            tx.append("test", "item.update", "not committed", {"item_id": self.item_id, "changes": {"note": "x"}})
            raise ValueError("abort")
        count = len(ledger.read_commits(self.vault))
        with self.assertRaises(ValueError), ledger.operation(self.vault, "op_failed", "digest"):
            ledger.transact(self.vault, build)
        self.assertEqual(len(ledger.read_commits(self.vault)), count)
        self.assertIsNone(ledger.operation_receipt(self.vault, "op_failed"))

    def test_domain_operation_native_idempotency_including_after_projection_restart(self):
        payload = {"item_ids": [self.item_id], "minutes": 30, "title": "repeat"}
        args = {"operation_id": "op_exact", "digest": "same"}
        first = domain_ops.execute(self.vault, "session.create", payload, **args)
        projections.reset_state(self.vault)
        second = domain_ops.execute(self.vault, "session.create", payload, **args)
        self.assertEqual(first["id"], second["id"])
        with self.assertRaises(domain_ops.DomainError):
            domain_ops.execute(self.vault, "session.create", payload, operation_id="op_exact", digest="different")
        self.assertEqual(len(projections.get_state(self.vault).sessions), 1)


class RuntimeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp(prefix="clms-runtime-")

    def tearDown(self):
        shutil.rmtree(self.vault)

    def test_empty_queries_do_not_create_auxiliary_database(self):
        self.assertEqual(runtime_history.list_records(self.vault)["items"], [])
        self.assertEqual(ai_review.items(self.vault)["items"], [])
        self.assertFalse(os.path.exists(os.path.join(self.vault, "语文")))

    def test_redaction_uses_positive_allowlist_and_records_stable_links(self):
        call = runtime_history.begin(self.vault, "mcp", "essay.evaluation.add", {
            "version_id": "EV-000001", "api_key": "clms_mcp_secret", "text": "私人完整作文",
            "summary": "私人评价", "request_id": "私人请求", "images": ["data:image/png;base64,SECRET"],
            "item_id": "https://private?key=secret", "status": "Bearer SECRET"}, {"key_id": "K-0001", "secret": "PRIVATE"})
        row = runtime_history.finish(self.vault, call, {"id": "EE-000001", "version_id": "EV-000001",
                                                       "summary": "私人评价", "source": "mcp"})
        self.assertEqual(row["arguments"], {"version_id": "EV-000001", "images_count": 1})
        self.assertEqual(row["result"]["version_id"], "EV-000001")
        with closing(sqlite3.connect(runtime_history.path(self.vault))) as db:
            raw = str(db.execute("SELECT * FROM records").fetchone())
        for secret in ("私人", "SECRET", "clms_mcp_secret", "https://private", "data:image"):
            self.assertNotIn(secret, raw)
        self.assertEqual(os.stat(runtime_history.path(self.vault)).st_mode & 0o777, 0o600)
        self.assertFalse(os.path.exists(ledger.ledger_path(self.vault)))

    def test_finish_is_terminal_and_recovery_does_not_infer_success(self):
        first = runtime_history.begin(self.vault, "assistant", "assistant.run")
        second = runtime_history.begin(self.vault, "ocr", "essay.ocr")
        runtime_history.finish(self.vault, first, {"status": "done"})
        runtime_history.finish(self.vault, first, {"status": "overwritten"}, "failure")
        self.assertEqual(runtime_history.detail(self.vault, first)["status"], "success")
        self.assertEqual(runtime_history.recover(self.vault), 1)
        self.assertEqual(runtime_history.detail(self.vault, second)["status"], "interrupted")
        self.assertEqual(runtime_history.list_records(self.vault, {"source": "ocr", "q": "转写"})["total"], 1)

    def test_telemetry_failure_does_not_propagate_and_symlink_is_rejected(self):
        with patch.object(runtime_history, "begin", side_effect=RuntimeError("disk broken")):
            self.assertIsNone(runtime_history.safely(runtime_history.begin, self.vault, "mcp", "read"))
        os.makedirs(os.path.dirname(runtime_history.path(self.vault)))
        os.symlink(os.path.join(self.vault, "elsewhere.db"), runtime_history.path(self.vault))
        with self.assertRaises(ValueError):
            runtime_history.begin(self.vault, "mcp", "read")


if __name__ == "__main__":
    unittest.main()
