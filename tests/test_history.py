"""学习/运行分轨历史、域对象定位、旧库与源码隐私边界。"""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clms import essays, history, ledger, runtime_history, source_export
from clms.common import save_config
from clms.server import make_server


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.vault = self.temp.name
        self.addCleanup(self.temp.cleanup)

    def test_old_ledger_and_filter_before_pagination(self):
        old = ledger.append_commit(self.vault, "legacy", "unknown.legacy", "旧库提交", {"item_id": "Q-unchanged"})
        for n in range(5):
            essays.create_prompt(self.vault, f"作文{n}", "谈谈你对成长的理解")
        result = history.list_learning(self.vault, {"source": "legacy", "limit": 1})
        self.assertEqual((result["total"], result["items"][0]["id"]), (1, old["commit_id"]))
        self.assertEqual(result["items"][0]["links"][0]["id"], "Q-unchanged")
        self.assertEqual(history.list_learning(self.vault, {"q": "作文3"})["total"], 1)
        self.assertEqual(history.list_learning(self.vault, {"to": "1900-01-01"})["total"], 0)
        self.assertTrue(ledger.verify_ledger(self.vault)["ok"])

    def test_essay_evaluation_links_to_original_version(self):
        prompt = essays.create_prompt(self.vault, "成长", "写一次成长经历")
        attempt = essays.create_attempt(self.vault, prompt["id"])
        # History reads the persisted relation, irrespective of the current version.
        commit = ledger.append_commit(self.vault, "mcp", "essay.evaluation.add", "追加作文评价", {
            "evaluation": {"id": "EE-old", "version_id": "EV-old", "attempt_id": attempt["id"], "prompt_id": prompt["id"], "total_score": 47}})
        links = history.detail(self.vault, commit["commit_id"])["links"]
        self.assertIn({"page": "essays", "field": "version", "id": "EV-old", "label": "打开作文版本"}, links)
        listing = history.list_learning(self.vault, {"type": "essay.prompt"})
        self.assertEqual(listing["items"][0]["links"][0]["id"], prompt["id"])

    def test_runtime_is_separate_redacted_and_points_to_operation(self):
        call = runtime_history.begin(self.vault, "mcp", "session.create", {
            "request_id": "private-request", "text": "全文不能进入运行库", "api_key": "secret", "images": ["data:private"], "minutes": 30})
        runtime_history.finish(self.vault, call, {"operation_id": "op_test", "status": "pending_confirmation", "answer": "不能保存"})
        item = runtime_history.detail(self.vault, call)
        encoded = json.dumps(item, ensure_ascii=False)
        for secret in ["private-request", "全文", "secret", "data:private", "不能保存"]:
            self.assertNotIn(secret, encoded)
        self.assertIn("op_test", encoded)
        self.assertEqual(history.list_learning(self.vault)["total"], 0)
        self.assertEqual(runtime_history.list_records(self.vault, {"source": "mcp"})["total"], 1)

    def test_formal_operation_origin_and_classification_target(self):
        commit = ledger.append_commit(self.vault, "review", "session.create", "批准复习提案", {
            "id": "S-unchanged", "_operation": {"id": "op_mcp", "source": "mcp"}})
        result = history.list_learning(self.vault, {"source": "mcp"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["domain_source"], "review")
        self.assertIn("mcp", result["sources"])
        links = history.detail(self.vault, commit["commit_id"])["links"]
        self.assertEqual({link["id"] for link in links}, {"op_mcp", "S-unchanged"})
        self.assertEqual(history.references({"commit_type": "essay.classification.assign", "payload": {
            "target_type": "version", "target_id": "EV-original"}})[0]["field"], "version")

    def test_runtime_operation_keeps_formal_session_identity(self):
        value = runtime_history.summary({"id": "op_mcp", "operation_id": "op_mcp", "status": "applied",
                                         "result": {"id": "S-0001", "items": [{"id": "Q-000001"}]}})
        self.assertEqual(value["id"], "op_mcp")
        self.assertEqual(value["operation_id"], "op_mcp")
        self.assertEqual(value["session_id"], "S-0001")
        self.assertEqual(value["items_count"], 1)

    def test_http_registration_and_web_rejects_mcp_credentials(self):
        server = make_server(self.vault, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        for path in ["/api/history", "/api/runtime/records", "/api/essays", "/api/status", "/api/assistant/status"]:
            with urllib.request.urlopen(base + path) as response:
                self.assertEqual(response.status, 200)
        req = urllib.request.Request(base + "/api/history", headers={"Authorization": "Bearer arbitrary"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req)
        self.assertEqual(caught.exception.code, 403)

    def test_export_covers_new_modules_and_excludes_new_private_stores(self):
        root = Path(self.vault, "source")
        (root / "clms" / "mcp").mkdir(parents=True)
        (root / "clms" / "essay_images").mkdir()
        (root / "clms" / "mcp" / "server.py").write_text("# MCP implementation")
        model_secret = "model-" + "private-1234567890"
        mcp_secret = "clms_" + "mcp_" + "secret-0123456789abcdef"
        (root / "clms" / "assistant.py").write_text(model_secret + "\n" + mcp_secret)
        (root / "requirements-mcp.txt").write_text("mcp==1.28.1")
        (root / "clms" / "essay_images" / "private.py").write_text("private-original")
        for name in ["assistant.db", "runtime.db", "ai_review.db", "mcp_keys.json"]:
            (root / "clms" / name).write_text("private-store")
        save_config(self.vault, {"assistant_api_key": model_secret})
        data, _, _ = source_export.create_source_export(self.vault, str(root))
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            self.assertIn("CLMS/clms/mcp/server.py", names)
            self.assertIn("CLMS/requirements-mcp.txt", names)
            content = archive.read("CLMS/clms/assistant.py").decode()
            self.assertNotIn(model_secret, content)
            self.assertNotIn(mcp_secret, content)
            self.assertFalse(any("essay_images" in x or x.endswith((".db", "mcp_keys.json")) for x in names))


if __name__ == "__main__":
    unittest.main()
