"""服务重启：同源门禁、实例隔离、真实 CLI 进程重载和持久数据恢复。"""
import json
import importlib.util
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from clms import creation, draft_schema, drafts, ledger  # noqa: E402
from clms.common import save_config  # noqa: E402
from clms.server import make_server  # noqa: E402


def call(base, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data,
                                     headers={"Content-Type": "application/json", **(headers or {})})
    try:
        response = urllib.request.urlopen(request, timeout=2)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.code, json.loads(response.read())


class CLIService:
    """独立 CLI 进程测试夹具；从数据目录启动，避免依赖当前工作目录。"""
    def __init__(self, vault, extra=None):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.log = tempfile.TemporaryFile(mode="w+")
        self.process = subprocess.Popen([sys.executable, os.path.join(ROOT, "clms_engine.py"),
                                         "--vault", vault, "serve", "--port", str(self.port), *(extra or [])],
                                        cwd=vault, stdout=self.log, stderr=self.log)
        try:
            self.initial = self.wait_status()
        except BaseException:
            self.close()
            raise

    def wait_status(self, previous=None):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.log.seek(0)
                raise AssertionError("CLI 提前退出：" + self.log.read())
            try:
                code, status = call(self.base, "/api/status")
                if code == 200 and status["instance_id"] != previous:
                    return status
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(.05)
        raise AssertionError("等待 CLI 实例超时")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)
        self.log.close()


class ServiceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.TemporaryDirectory(prefix="clms-service-")
        self.addCleanup(self.vault.cleanup)
        self.server = make_server(self.vault.name, port=0, restart_enabled=True)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def test_status_belongs_to_requested_server(self):
        other = make_server(self.vault.name, port=0)
        self.addCleanup(other.server_close)
        code, status = call(self.base, "/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(status["port"], self.server.server_address[1])
        self.assertEqual(status["instance_id"], self.server.instance_id)
        self.assertNotEqual(status["instance_id"], other.instance_id)

    def test_cross_origin_and_mcp_credentials_cannot_restart(self):
        body = {"instance_id": self.server.instance_id}
        for headers in ({"Origin": "http://evil.invalid"}, {"Authorization": "Bearer test"},
                        {"X-CLMS-MCP-Key": "test"}):
            code, _ = call(self.base, "/api/service/restart", body, headers)
            self.assertEqual(code, 403)
            self.assertFalse(self.server.restart_requested)

    def test_stale_or_missing_instance_cannot_restart(self):
        for body in ({}, {"instance_id": "old-instance"}):
            code, result = call(self.base, "/api/service/restart", body)
            self.assertEqual(code, 409)
            self.assertEqual(result["error"], "restart_conflict")
            self.assertFalse(self.server.restart_requested)

    def test_embedded_server_rejects_restart(self):
        self.server.restart_enabled = False
        code, _ = call(self.base, "/api/service/restart", {"instance_id": self.server.instance_id})
        self.assertEqual(code, 400)
        self.assertFalse(self.server.restart_requested)

    def test_reply_is_delivered_and_duplicate_requests_shutdown_once(self):
        # 拦住真正关闭来发两次请求；HTTP 客户端必须能读完两份 JSON。
        with patch.object(self.server, "shutdown") as shutdown:
            for _ in range(2):
                code, result = call(self.base, "/api/service/restart", {"instance_id": self.server.instance_id})
                self.assertEqual(code, 200)
                self.assertTrue(result["restarting"])
            deadline = time.monotonic() + 1
            while not shutdown.called and time.monotonic() < deadline:
                time.sleep(.01)
            shutdown.assert_called_once()


class CLIRestartTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("mcp") is not None, "可选 MCP SDK 未安装")
    def test_real_restart_restores_mcp_listener(self):
        with tempfile.TemporaryDirectory(prefix="clms-restart-mcp-") as vault:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                mcp_port = sock.getsockname()[1]
            service = CLIService(vault, ["--mcp-port", str(mcp_port)])
            try:
                old = service.initial
                self.assertTrue(old["mcp"]["running"])
                self.assertEqual(call(service.base, "/api/service/restart", {"instance_id": old["instance_id"]})[0], 200)
                new = service.wait_status(old["instance_id"])
                self.assertTrue(new["mcp"]["running"])
                self.assertEqual(new["mcp"]["url"], old["mcp"]["url"])
                with socket.create_connection(("127.0.0.1", mcp_port), timeout=2):
                    pass
            finally:
                service.close()

    def test_real_restart_keeps_data_port_and_pid_and_recovers_busy_draft(self):
        with tempfile.TemporaryDirectory(prefix="clms-restart-") as vault:
            save_config(vault, {"session_minutes": 53})
            creation.commit_draft(vault, {"id": "restart-seed"}, draft_schema.normalize_groups([
                {"genre": "dictation", "dictation": [
                    {"template": "床前明月光，{书写区域1}。", "blanks": {"1": "疑是地上霜"}}]}]))
            before = ledger.read_commits(vault)
            draft = drafts.create(vault, [], manual_genre="dictation")
            service = CLIService(vault)
            try:
                draft["status"] = "extracting"
                drafts.save(vault, draft)
                old = service.initial
                self.assertTrue(old["restart_supported"])
                code, result = call(service.base, "/api/service/restart", {"instance_id": old["instance_id"]})
                self.assertEqual(code, 200)
                self.assertEqual(result["instance_id"], old["instance_id"])
                new = service.wait_status(old["instance_id"])
                self.assertEqual(new["pid"], old["pid"])
                self.assertEqual(new["port"], old["port"])
                self.assertFalse(new["restarting"])
                self.assertEqual(call(service.base, "/api/config")[1]["session_minutes"], 53)
                self.assertEqual(ledger.read_commits(vault), before)
                self.assertTrue(ledger.verify_ledger(vault)["ok"])
                self.assertEqual(drafts.load(vault, draft["id"])["status"], "error")
                code, _ = call(service.base, "/api/service/restart", {"instance_id": old["instance_id"]})
                self.assertEqual(code, 409)
                self.assertEqual(service.wait_status()["instance_id"], new["instance_id"])
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
