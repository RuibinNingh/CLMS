"""ASGI limits remain bounded for chunked requests and live credentials."""
import asyncio
import unittest
from unittest.mock import patch

from test_core import TempVault
from clms.mcp import keys
from clms.mcp.http import MCPRequestGuard


class MCPHttpTests(TempVault):
    def setUp(self):
        super().setUp()
        self.key = keys.create_key(self.vault)
        self.calls = []

        async def app(scope, receive, send):
            self.calls.append(scope)
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        self.guard = MCPRequestGuard(app, self.vault, maximum=8)

    def request(self, headers=None, messages=None, query=b""):
        result = []
        pending = list(messages or [{"type": "http.request", "body": b"{}"}])

        async def receive():
            return pending.pop(0) if pending else {"type": "http.disconnect"}

        async def send(message):
            result.append(message)
        scope = {"type": "http", "method": "POST", "path": "/mcp", "query_string": query,
                 "headers": headers if headers is not None else [(b"authorization", b"Bearer " + self.key["secret"].encode())]}
        asyncio.run(self.guard(scope, receive, send))
        return result[0]["status"]

    def test_no_credentials_duplicate_or_dual_headers_are_rejected(self):
        self.assertEqual(self.request([]), 401)
        auth = (b"authorization", b"Bearer " + self.key["secret"].encode())
        self.assertEqual(self.request([auth, auth]), 401)
        self.assertEqual(self.request([auth, (b"x-clms-mcp-key", self.key["secret"].encode())]), 401)
        self.assertEqual(self.request(query=b"key=anything"), 404)
        self.assertEqual(self.calls, [])

    def test_alternate_header_is_normalized_without_url_credentials(self):
        self.assertEqual(self.request([(b"x-clms-mcp-key", self.key["secret"].encode())]), 200)
        self.assertIn((b"authorization", b"Bearer " + self.key["secret"].encode()), self.calls[0]["headers"])

    def test_streaming_body_and_declared_length_are_bounded(self):
        self.assertEqual(self.request(messages=[{"type": "http.request", "body": b"12345", "more_body": True},
                                                {"type": "http.request", "body": b"6789"}]), 413)
        headers = [(b"authorization", b"Bearer " + self.key["secret"].encode()), (b"content-length", b"100")]
        self.assertEqual(self.request(headers), 413)
        headers[-1] = (b"content-length", b"-1")
        self.assertEqual(self.request(headers), 400)
        self.assertEqual(self.calls, [])

    def test_rate_limit_and_revocation_apply_to_each_request(self):
        with patch("clms.mcp.http.REQUESTS_PER_MINUTE", 1):
            self.assertEqual(self.request(), 200)
            self.assertEqual(self.request(), 429)
        keys.revoke_key(self.vault, self.key["key_id"])
        self.assertEqual(self.request(), 401)

    def test_concurrency_limit_is_key_scoped(self):
        self.guard.active[self.key["key_id"]] = 4
        self.assertEqual(self.request(), 429)
        other = keys.create_key(self.vault)
        self.assertEqual(self.request([(b"authorization", b"Bearer " + other["secret"].encode())]), 200)


if __name__ == "__main__":
    unittest.main()
