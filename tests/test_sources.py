# -*- coding: utf-8 -*-
"""M5-4 多源摄取测试：RSS + Webhook + CLI pulls + /sources 状态端点。"""
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time as _time
import unittest
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="cenhua-test-sources-")
os.environ["CENHUA_HOME"] = os.path.join(_TMP, "home")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import m_lib as L  # noqa: E402
import uvicorn  # noqa: E402
from cenhua_service.sources import (parse_sources, list_source_types,
    load_state, save_state, get_source_type, Source)  # noqa: E402
from cenhua_service.sources.rss import RssSource  # noqa: E402
from cenhua_service.sources.webhook import (WebhookSource,  # noqa: E402
    verify_signature, mount_webhook_routes)
from cenhua_service.webui import app as W  # noqa: E402


CLI = os.path.join(ROOT, "bin", "cenhua")


def _serve(app):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(cfg)
    th = threading.Thread(target=server.run, daemon=True); th.start()
    for _ in range(400):
        try:
            with socket.create_connection(("127.0.0.1", port), 0.2):
                break
        except OSError:
            _time.sleep(0.05)
    import httpx
    return httpx.Client(base_url="http://127.0.0.1:%d" % port,
                        timeout=30, follow_redirects=False), (server, th)


class _Base(unittest.TestCase):
    def setUp(self):
        subprocess.run([CLI, "init", self.id().split(".")[-1], "--yes"],
                       check=True, capture_output=True)
        self.vault = L.Vault(self.id().split(".")[-1])

    def tearDown(self):
        shutil.rmtree(_TMP, ignore_errors=True)


# ------------------------------------------------ registry + parse_sources ---
class TestRegistry(_Base):
    def test_01_registry_has_rss_and_webhook(self):
        self.assertIn("rss", list_source_types())
        self.assertIn("webhook", list_source_types())
        self.assertIsNotNone(get_source_type("rss"))
        self.assertIsNotNone(get_source_type("webhook"))

    def test_02_missing_sources_yaml_returns_empty(self):
        self.assertEqual(parse_sources(self.vault), [])

    def test_03_sources_yaml_parsed(self):
        import yaml
        os.makedirs(os.path.join(self.vault.root, "meta"), exist_ok=True)
        cfg = {"sources": [
            {"type": "rss", "name": "test-rss",
             "url": "https://example.com/feed.xml"},
            {"type": "webhook", "name": "test-wh",
             "path": "test", "secret": "s3cret"},
            {"type": "unknown", "name": "skip-me"},     # 未注册，过滤
        ]}
        with open(os.path.join(self.vault.root, "meta", "sources.yaml"),
                  "w", encoding="utf-8") as fh:
            yaml.dump(cfg, fh, allow_unicode=True)
        sources = parse_sources(self.vault)
        types = [s["type"] for s in sources]
        self.assertEqual(types, ["rss", "webhook"])     # unknown 过滤掉

    def test_04_sources_yaml_bad_yaml_returns_empty(self):
        os.makedirs(os.path.join(self.vault.root, "meta"), exist_ok=True)
        open(os.path.join(self.vault.root, "meta", "sources.yaml"),
             "w").write("sources: [garbage:")
        self.assertEqual(parse_sources(self.vault), [])


# ------------------------------------------------ HMAC verify ---
class TestHMAC:
    """纯函数测试，不需要 vault。"""

    def test_01_good_signature(self):
        body = b'{"hello":"world"}'
        secret = "s3cret"
        sig = "sha256=" + hmac.new(secret.encode(), body,
                                  hashlib.sha256).hexdigest()
        assert verify_signature(secret, body, sig)

    def test_02_bad_signature(self):
        body = b'{"hello":"world"}'
        secret = "s3cret"
        sig = "sha256=" + hmac.new(b"wrong", body,
                                  hashlib.sha256).hexdigest()
        assert not verify_signature(secret, body, sig)

    def test_03_no_prefix(self):
        body = b'body'
        secret = "s3cret"
        hex_sig = hmac.new(secret.encode(), body,
                           hashlib.sha256).hexdigest()
        assert verify_signature(secret, body, hex_sig)  # 裸 hex 也认

    def test_04_empty_secret_rejects(self):
        body = b'body'
        sig = "sha256=abc"
        assert not verify_signature("", body, sig)

    def test_05_empty_sig_rejects(self):
        assert not verify_signature("s3cret", b"body", "")


# ------------------------------------------------ RSS fetch ---
def _fake_ingest(vault, path):
    """替换 core.ingest：无网关环境也能让 sources 链路跑通（同 test_webui）。"""
    import os
    from cenhua_service.core import IngestResult
    name = os.path.basename(path)
    sha = L.sha1(path) if os.path.isfile(path) else ""
    return IngestResult(status="added", doc_id="fake-" + sha[:8],
                        name=name, error="")


class TestRss(_Base):
    """RSS fetch 端到端：构造 feed → fetch → inbox → ingest → state。"""

    def _write_feed(self, path, entries):
        """写最小合法 RSS XML。"""
        items = ""
        for t, l in entries:
            items += ("<item><title>%s</title><link>%s</link>"
                      "<guid>%s</guid></item>\n" % (t, l, l))
        xml = ("<?xml version='1.0' encoding='UTF-8'?>"
               "<rss><channel>" + items + "</channel></rss>")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(xml)

    def setUp(self):
        super().setUp()
        self._real_ingest = __import__("cenhua_service.core",
                                       fromlist=["ingest"]).ingest
        import cenhua_service.core as core
        core.ingest = _fake_ingest

    def tearDown(self):
        import cenhua_service.core as core
        core.ingest = self._real_ingest
        super().tearDown()

    def test_01_fetch_inbox_and_state(self):
        """RSS fetch → 条目进 inbox → state 更新 last_seen。"""
        feed_path = os.path.join(self.vault.inbox, "test.xml")
        self._write_feed(feed_path, [("RSS 标题 A", "http://a"),
                                      ("RSS 标题 B", "http://b")])
        cfg = {"url": "file://" + feed_path}
        res = RssSource().fetch(self.vault, cfg)
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.added, 2)
        self.assertEqual(res.dupe, 0)
        # inbox 有新文件
        inbox_fnames = os.listdir(self.vault.inbox)
        html_files = [f for f in inbox_fnames if f.endswith(".html")]
        self.assertGreaterEqual(len(html_files), 2)
        # state 有 last_seen
        state = load_state(self.vault)
        self.assertIn("rss-" + RssSource._hash_url(cfg["url"])[:6], state)

    def test_02_fetch_incremental_no_dupe(self):
        """第二次 fetch 相同 feed → dupe 全部命中。"""
        feed_path = os.path.join(self.vault.inbox, "test2.xml")
        self._write_feed(feed_path, [("RSS A", "http://a"),
                                      ("RSS B", "http://b")])
        cfg = {"url": "file://" + feed_path}
        RssSource().fetch(self.vault, cfg)
        # 第二次：条目 hash 已在 state.last_seen
        res2 = RssSource().fetch(self.vault, cfg)
        self.assertEqual(res2.added, 0)
        self.assertEqual(res2.dupe, 2)


# ------------------------------------------------ Webhook 路由端到端 ---
class TestWebhookE2E(_Base):
    def setUp(self):
        super().setUp()
        self._real_ingest = __import__("cenhua_service.core",
                                       fromlist=["ingest"]).ingest
        import cenhua_service.core as core
        core.ingest = _fake_ingest
        os.environ["CENHUA_API_TOKEN"] = "test-token-wh"
        import yaml
        os.makedirs(os.path.join(self.vault.root, "meta"), exist_ok=True)
        cfg = {"sources": [
            {"type": "webhook", "name": "test-wh",
             "path": "test", "secret": "wh-s3cret",
             "format": "auto"},
        ]}
        with open(os.path.join(self.vault.root, "meta", "sources.yaml"),
                  "w", encoding="utf-8") as fh:
            yaml.dump(cfg, fh, allow_unicode=True)
        self.client, (self.server, self.th) = _serve(W.create_app(self.vault))
        self.secret = "wh-s3cret"

    def tearDown(self):
        import cenhua_service.core as core
        core.ingest = self._real_ingest
        self.client.close()
        self.server.should_exit = True
        self.th.join(timeout=5)
        os.environ.pop("CENHUA_API_TOKEN", None)

    def _sign(self, body: bytes) -> str:
        return "sha256=" + hmac.new(self.secret.encode(), body,
                                    hashlib.sha256).hexdigest()

    def test_01_webhook_rejects_no_sig(self):
        r = self.client.post("/webhook/test",
                             content=b'{"text":"hello"}')
        self.assertEqual(r.status_code, 401)

    def test_02_webhook_rejects_bad_sig(self):
        r = self.client.post("/webhook/test",
                             content=b'{"text":"hello"}',
                             headers={"x-cenhua-signature":
                                      "sha256=deadbeef" * 8})
        self.assertEqual(r.status_code, 401)

    def test_03_webhook_accepts_and_ingests(self):
        body = b'{"text":"webhook test content"}'
        r = self.client.post("/webhook/test", content=body,
                             headers={"x-cenhua-signature": self._sign(body)})
        self.assertEqual(r.status_code, 200)
        self.assertIn("added", r.text)
        # inbox 有新文件
        inbox = os.listdir(self.vault.inbox)
        txt_files = [f for f in inbox if f.endswith(".txt")]
        self.assertGreaterEqual(len(txt_files), 1)
        # state 有记录
        state = load_state(self.vault)
        self.assertIn("test-wh", state)

    def test_04_webhook_auto_json_extract(self):
        """auto 模式：JSON body 取 text 字段 → 纯 .txt。"""
        body = json.dumps({"text": "extracted from JSON"}).encode()
        r = self.client.post("/webhook/test", content=body,
                             headers={"x-cenhua-signature": self._sign(body)})
        self.assertEqual(r.status_code, 200)
        inbox = os.listdir(self.vault.inbox)
        txt_files = [f for f in inbox if f.endswith(".txt")]
        self.assertTrue(any("test-wh" in f for f in txt_files))

    def test_05_webhook_body_too_large_413(self):
        big = b"x" * (256 * 1024 + 1)     # 超过 max_body_kb * 1024
        r = self.client.post("/webhook/test", content=big,
                             headers={"x-cenhua-signature": self._sign(big)})
        self.assertEqual(r.status_code, 413)


# ------------------------------------------------ /sources 端点 ---
class TestSourcesEndpoint(_Base):
    def setUp(self):
        super().setUp()
        self.client, (self.server, self.th) = _serve(W.create_app(self.vault))

    def tearDown(self):
        self.client.close()
        self.server.should_exit = True
        self.th.join(timeout=5)

    def test_01_sources_free_auth(self):
        """和 /health 同口径：免 token。"""
        r = self.client.get("/sources")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["schema_version"], 1)
        self.assertIn("registered", body)
        self.assertIn("sources", body)
        self.assertEqual(sorted(body["registered"]), ["rss", "webhook"])

    def test_02_sources_no_yaml(self):
        """无 sources.yaml → yaml_available=True 但 sources=[]。"""
        r = self.client.get("/sources")
        body = r.json()
        self.assertEqual(body["sources"], [])
        self.assertTrue(body["yaml_available"])


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    ret = unittest.TextTestRunner(verbosity=2).run(suite)
    shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(0 if ret.wasSuccessful() else 1)
