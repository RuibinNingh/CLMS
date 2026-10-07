"""Official SDK execution boundary: schemas, permissions, review and revocation."""
import asyncio
import importlib.util
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

from test_core import TempVault, _group_a, seed_types
from clms import ai_review, creation, ledger, runtime_history, sessions
from clms.harness import Tool
from clms.mcp import keys
from clms.mcp.server import build_server, _arguments

SDK = importlib.util.find_spec("mcp") is not None


@unittest.skipUnless(SDK, "optional MCP SDK not installed")
class MCPTests(TempVault):
    def setUp(self):
        super().setUp(); seed_types(self.vault)
        self.ids = creation.commit_draft(self.vault, {"id": "D-mcp", "images": []}, _group_a())["item_ids"]
        self.key = keys.create_key(self.vault, scopes=list(keys.SCOPES))
        self.server = build_server(self.vault)

    async def _authenticated(self, operation, secret=None):
        from mcp.server.auth.middleware.auth_context import auth_context_var
        from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
        from mcp.server.auth.provider import AccessToken
        context = auth_context_var.set(AuthenticatedUser(AccessToken(token=secret or self.key["secret"],
                                                   client_id=self.key["key_id"], scopes=list(keys.SCOPES))))
        try:
            return await operation()
        finally:
            auth_context_var.reset(context)

    def call(self, name, args):
        return asyncio.run(self._authenticated(lambda: self.server.call_tool(name, args)))

    def tools(self):
        return asyncio.run(self._authenticated(self.server.list_tools))

    def assert_error(self, result, code):
        self.assertTrue(result.isError)
        self.assertTrue(result.content[0].text.startswith(code + ":"), result.content[0].text)

    def test_discovery_and_direct_call_share_current_scopes(self):
        keys.update_scopes(self.vault, self.key["key_id"], ["clms:read"])
        names = {tool.name for tool in self.tools()}
        self.assertIn("get_item", names)
        self.assertNotIn("create_review_session", names)
        self.assertNotIn("get_essay_image", names)
        self.assert_error(self.call("create_review_session", {"item_ids": self.ids, "request_id": "scope"}), "forbidden")
        keys.update_scopes(self.vault, self.key["key_id"], ["session:create"])
        self.assertNotIn("create_review_session", {tool.name for tool in self.tools()})
        self.assert_error(self.call("get_item", {"item_id": self.ids[0]}), "forbidden")

    def test_strict_arguments_no_approval_or_arbitrary_file_tools(self):
        for args in ({"item_id": self.ids[0], "path": "/etc/passwd"}, {"item_id": 123}):
            self.assert_error(self.call("get_item", args), "invalid_arguments")
        self.assert_error(self.call("create_review_session", {"item_ids": self.ids}), "invalid_arguments")
        self.assert_error(self.call("create_review_session", {"item_ids": self.ids, "request_id": "../bad"}), "invalid_arguments")
        for name in ("approve_operation", "read_file", "http_request", "delete_item"):
            self.assert_error(self.call(name, {}), "unknown_tool")
        self.assertNotIn("approve_operation", {tool.name for tool in self.tools()})

    def test_session_pending_manual_approval_once_and_request_conflict(self):
        payload = {"item_ids": self.ids, "minutes": 30, "title": "现代文复习", "request_id": "plan-one"}
        pending = self.call("create_review_session", payload)
        self.assertEqual(pending["status"], "pending_confirmation")
        self.assertEqual(sessions.list_sessions(self.vault), [])
        again = self.call("create_review_session", payload)
        self.assertEqual(again["id"], pending["id"])
        self.assert_error(self.call("create_review_session", dict(payload, minutes=31)), "request_conflict")
        applied = ai_review.decide(self.vault, pending["id"], pending["revision"], "approve", {"kind": "human", "channel": "web"})
        repeated = ai_review.decide(self.vault, pending["id"], pending["revision"], "approve", {"kind": "human", "channel": "web"})
        self.assertEqual(applied["result"]["id"], repeated["result"]["id"])
        self.assertEqual(len(sessions.list_sessions(self.vault)), 1)
        queried = self.call("get_operation", {"operation_id": pending["id"]})
        self.assertEqual(queried["status"], "applied")

    def test_approval_rechecks_key_and_foreign_operation_not_disclosed(self):
        pending = self.call("propose_item_update", {"item_id": self.ids[0], "changes": {"blank_lines": 11}, "request_id": "question"})
        other = keys.create_key(self.vault, scopes=list(keys.SCOPES))
        result = asyncio.run(self._authenticated(lambda: self.server.call_tool("get_operation", {"operation_id": pending["id"]}), other["secret"]))
        self.assert_error(result, "not_found")
        keys.revoke_key(self.vault, self.key["key_id"])
        resolved = ai_review.decide(self.vault, pending["id"], pending["revision"], "approve", {"kind": "human", "channel": "web"})
        self.assertEqual(resolved["error_code"], "forbidden")
        self.assertEqual(sessions.create(self.vault, self.ids)["items"][0]["blank_lines"], 7)
        self.assert_error(self.call("get_item", {"item_id": self.ids[0]}), "forbidden")

    def test_revoke_during_read_hides_late_result(self):
        def execute(args, context):
            keys.revoke_key(self.vault, self.key["key_id"])
            return {"private": "late result"}
        tool = Tool("get_overview", "test", {"type": "object", "properties": {}}, execute)
        tool.permission, tool.scopes = "read", {"clms:read"}
        with patch("clms.mcp.server._catalog", return_value={tool.name: tool}):
            self.assert_error(self.call("get_overview", {}), "forbidden")

    def test_waiting_ledger_lock_rechecks_revocation(self):
        pending = self.call("create_review_session", {"item_ids": self.ids, "request_id": "locked"})
        result = []
        with ledger._write_lock:
            worker = threading.Thread(target=lambda: result.append(ai_review.decide(self.vault, pending["id"], 1, "approve", {"kind": "human"})))
            worker.start(); time.sleep(.08)
            keys.revoke_key(self.vault, self.key["key_id"])
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0]["error_code"], "forbidden")
        self.assertEqual(sessions.list_sessions(self.vault), [])

    def test_runtime_never_keeps_private_text_credential_or_image(self):
        result = self.call("get_item", {"item_id": self.ids[0]})
        self.assertEqual(result["id"], self.ids[0])
        rows = runtime_history.list_records(self.vault, {"source": "mcp"})["items"]
        raw = json.dumps(rows, ensure_ascii=False)
        self.assertNotIn(self.key["secret"], raw)
        self.assertNotIn("①线索②象征", raw)
        self.assertNotIn("分析“灯”的作用", raw)
        self.assertTrue(any(row["result"].get("id") == self.ids[0] for row in rows))


if __name__ == "__main__":
    unittest.main()
