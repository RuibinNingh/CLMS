"""MCP credential security, separate Web access and process-safe lifecycle."""
import datetime
import hashlib
import json
import multiprocessing
import os
import stat
import subprocess
import sys
import unittest

from test_core import TempVault
from clms.mcp import keys


def _create_process(vault):
    for index in range(5):
        keys.create_key(vault, f"worker-{index}", ["clms:read"])


class KeyTests(TempVault):
    def test_one_time_secret_separate_safe_digest_and_mode(self):
        created = keys.create_key(self.vault, "ChatGPT", ["essay:read"])
        with open(keys.path(self.vault), encoding="utf-8") as stream:
            stored = stream.read()
        self.assertNotIn(created["secret"], stored)
        self.assertIn(hashlib.sha256(created["secret"].encode()).hexdigest(), stored)
        self.assertEqual(stat.S_IMODE(os.stat(keys.path(self.vault)).st_mode), 0o600)
        self.assertNotIn("secret", keys.list_keys(self.vault)[0])
        self.assertNotIn("secret_sha256", keys.list_keys(self.vault)[0])
        self.assertEqual(keys.verify_key(self.vault, created["secret"])["key_id"], created["key_id"])
        self.assertIsNone(keys.verify_key(self.vault, "<已脱敏>"))

    def test_revoke_and_scope_change_recheck_existing_credential(self):
        row = keys.create_key(self.vault)
        keys.update_scopes(self.vault, row["key_id"], ["essay:read"])
        self.assertEqual(keys.verify_key(self.vault, row["secret"])["scopes"], ["essay:read"])
        keys.revoke_key(self.vault, row["key_id"])
        self.assertIsNone(keys.verify_key(self.vault, row["secret"]))
        self.assertIsNone(keys.active_key(self.vault, row["key_id"]))
        with self.assertRaises(ValueError):
            keys.update_scopes(self.vault, row["key_id"], ["clms:read"])
        keys.revoke_key(self.vault, row["key_id"])  # idempotent lifecycle

    def test_expiry_is_realtime_and_invalid_input_is_rejected(self):
        expires = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).isoformat()
        row = keys.create_key(self.vault, expires_at=expires)
        with keys._key_lock(self.vault):
            data = keys._load(self.vault)
            data["keys"][0]["expires_at"] = "2000-01-01T00:00:00+00:00"
            keys._save(self.vault, data)
        self.assertIsNone(keys.verify_key(self.vault, row["secret"]))
        for scopes in ([], ["admin"], "clms:read", [True]):
            with self.subTest(scopes=scopes), self.assertRaises(ValueError):
                keys.create_key(self.vault, scopes=scopes)
        for expiry in ("bad", "2000-01-01", False):
            with self.subTest(expiry=expiry), self.assertRaises(ValueError):
                keys.create_key(self.vault, expires_at=expiry)

    def test_symlink_file_lock_and_directory_are_rejected(self):
        target = keys.path(self.vault)
        external = os.path.join(self.vault, "private.txt")
        with open(external, "w") as stream:
            stream.write("do not overwrite")
        os.symlink(external, target)
        with self.assertRaises(ValueError):
            keys.create_key(self.vault)
        self.assertIsNone(keys.verify_key(self.vault, "clms_mcp_unknown"))
        os.unlink(target)
        lock = target + ".lock"
        os.unlink(lock)
        os.symlink(external, lock)
        with self.assertRaises(ValueError):
            keys.list_keys(self.vault)
        with open(external) as stream:
            self.assertEqual(stream.read(), "do not overwrite")

    def test_corrupt_file_does_not_get_silently_overwritten(self):
        keys.create_key(self.vault)
        with open(keys.path(self.vault), "w") as stream:
            stream.write("{corrupt")
        with self.assertRaises(ValueError):
            keys.create_key(self.vault)
        with open(keys.path(self.vault)) as stream:
            self.assertEqual(stream.read(), "{corrupt")

    def test_process_writes_do_not_lose_credentials(self):
        context = multiprocessing.get_context("spawn")
        processes = [context.Process(target=_create_process, args=(self.vault,)) for _ in range(3)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=10); self.assertEqual(process.exitcode, 0)
        rows = keys.list_keys(self.vault)
        self.assertEqual(len(rows), 15)
        self.assertEqual(len({row["key_id"] for row in rows}), 15)

    def test_web_and_mcp_modules_import_without_optional_dependencies(self):
        source = """
import builtins
original = builtins.__import__
def without_optional(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name.split('.')[0] in {'mcp', 'uvicorn', 'jsonschema'}:
        raise ImportError('optional disabled for test')
    return original(name, globals, locals, fromlist, level)
builtins.__import__ = without_optional
from clms.server import make_server
from clms.mcp.server import build_server
try:
    build_server('/tmp/unused-clms-optional-test')
except ValueError as error:
    assert 'requirements-mcp.txt' in str(error)
else:
    raise AssertionError('SDK unexpectedly imported')
"""
        result = subprocess.run([sys.executable, "-c", source], cwd=os.path.dirname(os.path.dirname(__file__)),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
