#!/usr/bin/env python3
"""M5-1 运维硬化测试套件（日志脱敏/轮转、backup/restore、/health）。

Run:  python3 tests/test_ops.py
"""

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time as _time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "bin", "cenhua")

_TEST_HOME = tempfile.mkdtemp(prefix="cenhua-ops-")
os.environ["CENHUA_HOME"] = _TEST_HOME
os.environ["CENHUA_CONFIG_DIR"] = os.path.join(_TEST_HOME, "config-dir")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import m_lib as L  # noqa: E402
import m_vault  # noqa: E402


def run(args, home, env=None):
    e = dict(os.environ)
    e["CENHUA_HOME"] = home
    e["CENHUA_CONFIG_DIR"] = os.path.join(home, "config-dir")
    e.update(env or {})
    e.pop("PI_BASE", None)
    e.pop("PI_KEY", None)
    return subprocess.run([CLI, *args], env=e, cwd=ROOT,
                          capture_output=True, text=True)


class LogRedactTest(unittest.TestCase):
    def test_redact_token_and_key(self):
        self.assertNotIn("sk-abc123", L._redact("PI_KEY=sk-abc123"))
        self.assertIn("***", L._redact("PI_KEY=sk-abc123"))
        self.assertNotIn("secret-token", L._redact("token=secret-token"))
        self.assertNotIn("abc.def", L._redact("Authorization: Bearer abc.def"))

    def test_redact_path(self):
        self.assertNotIn("/home/user/secret", L._redact("path /home/user/secret x"))
        self.assertIn("<path>", L._redact("path /home/user/secret x"))

    def test_redact_plain_text_unchanged(self):
        self.assertEqual(L._redact("正常日志内容 123"), "正常日志内容 123")


class LogRotateTest(unittest.TestCase):
    def setUp(self):
        self.v = L.Vault("t", must_exist=False)
        self.v.create_dirs()

    def test_rotate_on_size(self):
        os.environ["CENHUA_LOG_MAX_BYTES"] = "50"
        os.environ["CENHUA_LOG_BACKUPS"] = "2"
        try:
            for _ in range(20):
                self.v.log("test", "x" * 20)
            base = os.path.join(self.v.logs, "test-%s.log"
                                % _time.strftime("%Y%m"))
            self.assertTrue(os.path.isfile(base))
            self.assertTrue(os.path.isfile(base + ".1") or
                            os.path.isfile(base + ".2"))
        finally:
            os.environ.pop("CENHUA_LOG_MAX_BYTES", None)
            os.environ.pop("CENHUA_LOG_BACKUPS", None)

    def test_log_writes_redacted(self):
        self.v.log("test", "PI_KEY=sk-secret123 路径 /home/user/x")
        base = os.path.join(self.v.logs, "test-%s.log"
                            % _time.strftime("%Y%m"))
        content = open(base, encoding="utf-8").read()
        self.assertNotIn("sk-secret123", content)
        self.assertNotIn("/home/user/x", content)
        self.assertIn("***", content)


class BackupRestoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = run(["init", "t", "--yes"], _TEST_HOME)
        assert r.returncode == 0, r.stderr
        cls.v = L.Vault("t")
        os.makedirs(cls.v.textdir, exist_ok=True)
        with open(os.path.join(cls.v.textdir, "pi-d1.txt"), "w",
                  encoding="utf-8") as f:
            f.write("=== PAGE 1 ===\n测试内容\n")
        os.makedirs(cls.v.works, exist_ok=True)
        with open(os.path.join(cls.v.works, "draft.md"), "w",
                  encoding="utf-8") as f:
            f.write("# 草稿\n")

    def test_backup_creates_tar(self):
        dest = os.path.join(_TEST_HOME, "bk1.tar.gz")
        out = m_vault.backup(self.v, dest=dest, yes=True)
        self.assertTrue(os.path.isfile(dest))
        self.assertEqual(out, dest)

    def test_restore_to_new_name(self):
        dest = os.path.join(_TEST_HOME, "bk2.tar.gz")
        m_vault.backup(self.v, dest=dest, yes=True)
        root = m_vault.restore(dest, name="t-restored", yes=True)
        self.assertTrue(os.path.isfile(os.path.join(root, "vault.yaml")))
        self.assertTrue(os.path.isfile(
            os.path.join(root, "engine", "text", "pi-d1.txt")))
        self.assertTrue(os.path.isfile(os.path.join(root, "works", "draft.md")))

    def test_restore_refuses_nonempty(self):
        dest = os.path.join(_TEST_HOME, "bk3.tar.gz")
        m_vault.backup(self.v, dest=dest, yes=True)
        with self.assertRaises(SystemExit):
            m_vault.restore(dest, name="t", yes=False)


class HealthEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = L.Vault("t")
        from cenhua_service.webui import app as W
        cls.app = W.create_app(cls.v)

    def _serve(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        import uvicorn
        cfg = uvicorn.Config(self.app, host="127.0.0.1", port=port,
                             log_level="error")
        server = uvicorn.Server(cfg)
        th = threading.Thread(target=server.run, daemon=True)
        th.start()
        for _ in range(400):
            try:
                with socket.create_connection(("127.0.0.1", port), 0.2):
                    break
            except OSError:
                _time.sleep(0.05)
        import httpx
        return httpx.Client(base_url="http://127.0.0.1:%d" % port,
                            timeout=30), (server, th)

    def test_health_no_token_200(self):
        client, (server, th) = self._serve()
        try:
            r = client.get("/health")
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["vault"], "t")
            self.assertIn("version", data)
            self.assertIn("docs", data)
        finally:
            client.close()
            server.should_exit = True
            th.join(timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
