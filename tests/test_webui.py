# -*- coding: utf-8 -*-
"""M3b Web UI + 局域网 API 测试（任务 12）+ M4b 图谱/草稿端点与页面。

覆盖：鉴权 fail-closed / 限流 429 / graph+draft 真端点（M4b）/
docmeta 往返 / 任务通道 JSON 轮询 + SSE 增量重放 / 页面登录与页面集 /
multipart 摄取 / rid 全链路日志 / host:port 配置解析。
基座与 test_channel.py 同款：临时 CENHUA_HOME + `cenhua init`。
"""
import httpx
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
_TMP = tempfile.mkdtemp(prefix="cenhua-test-webui-")
os.environ["CENHUA_HOME"] = os.path.join(_TMP, "home")
os.environ.setdefault("CENHUA_CONFIG_DIR", os.path.join(_TMP, "conf"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import m_lib as L  # noqa: E402
import uvicorn  # noqa: E402
from cenhua_service import core  # noqa: E402
from cenhua_service import docmeta as DM  # noqa: E402
from cenhua_service import draft as DR  # noqa: E402
from cenhua_service import jobs as J  # noqa: E402
from cenhua_service.webui import app as W  # noqa: E402
from cenhua_service.webui import pages as P  # noqa: E402
from cenhua_service.webui import security  # noqa: E402

CLI = os.path.join(ROOT, "bin", "cenhua")
TOKEN = "test-token-1234567890"


def _serve(app):
    """后台线程跑 uvicorn + 真 HTTP 客户端。

    starlette 0.36 的 TestClient 与 httpx 0.28 不兼容（`app=` 参数被移除），
    真起服务反而更接近端到端验收。返回 (client, thread)。
    """
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(cfg)
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(400):                    # 等待端口就绪（最长 20s）
        try:
            with socket.create_connection(("127.0.0.1", port), 0.2):
                break
        except OSError:
            _time.sleep(0.05)
    return httpx.Client(base_url="http://127.0.0.1:%d" % port,
                        timeout=30, follow_redirects=False), (server, th)


class _ServerMixin:
    """起停管理：self._mk(vault, rate) 造客户端，tearDown 统一关停。"""

    def _mk(self, vault, rate=None):
        client, (server, th) = _serve(W.create_app(vault, rate=rate))
        self._servers = getattr(self, "_servers", [])
        self._servers.append((client, server, th))
        return client

    def _stop_all(self):
        for client, server, th in getattr(self, "_servers", []):
            client.close()
            server.should_exit = True
            th.join(timeout=5)
        self._servers = []


def _init_vault(name):
    """子进程 init（与 CLI 完全同路径），返回 Vault。"""
    subprocess.run([CLI, "init", name, "--yes"],
                   check=True, capture_output=True)
    return L.Vault(name)


def _seed_doc(vault, doc_id, name, pages):
    """无网关环境种文档：台账 + manifest + 文本层（同 _seed_text 思路）。"""
    os.makedirs(vault.textdir, exist_ok=True)
    with open(os.path.join(vault.textdir, doc_id + ".txt"), "w",
              encoding="utf-8") as fh:
        for i, p in enumerate(pages, 1):
            fh.write("=== PAGE %d ===\n%s\n" % (i, p))
    led_path = os.path.join(vault.store, "ingest_manifest.json")
    led = L.read_json(led_path, {}) or {}
    led[doc_id] = {"doc_id": doc_id, "name": name, "source": "seed",
                   "stored_as": "", "sha1": "", "ts": "0"}
    with open(led_path, "w", encoding="utf-8") as fh:
        json.dump(led, fh, ensure_ascii=False)
    man_path = os.path.join(vault.store, "manifest.json")
    man = L.read_json(man_path, {}) or {}
    man.setdefault("docs", {})[doc_id] = {"name": name}
    with open(man_path, "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False)


def _fake_ingest(res):
    """替换 core.ingest 的替身（真引擎需 PI_BASE/PI_KEY 网关）。"""
    def _fn(vault, path):
        return res
    return _fn


class _WebBase(_ServerMixin, unittest.TestCase):
    """公共基座：临时库 + token + 真 HTTP 客户端；jobs 每例重置。"""

    rate = None

    def setUp(self):
        J.reset()
        os.environ["CENHUA_API_TOKEN"] = TOKEN
        self.vault = _init_vault("webuibase-" + self.id().split(".")[-1])
        self.client = self._mk(self.vault, rate=self.rate)
        self.auth = {"X-Cenhua-Token": TOKEN}
        self._real_ingest = core.ingest
        core.ingest = _fake_ingest(core.IngestResult(
            status="added", doc_id="pi-webui1", name="seed-doc.txt"))

    def tearDown(self):
        core.ingest = self._real_ingest
        self._stop_all()
        os.environ.pop("CENHUA_API_TOKEN", None)

    def login(self):
        return self.client.post("/login", data={"token": TOKEN},
                                follow_redirects=False)


class TestAuthFailClosed(_ServerMixin, unittest.TestCase):
    """未配置 token = 拒绝一切（不依赖基座 env）。"""

    def setUp(self):
        J.reset()
        os.environ.pop("CENHUA_API_TOKEN", None)
        self.vault = _init_vault("webui-notoken")

    def tearDown(self):
        self._stop_all()
        os.environ.pop("CENHUA_API_TOKEN", None)

    def test_01_no_token_api_401(self):
        c = self._mk(self.vault)
        r = c.get("/api/v1/stats")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"]["error"],
                         "invalid or missing token")

    def test_02_no_token_page_redirect_login(self):
        c = self._mk(self.vault)
        r = c.get("/ingest")
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/login")

    def test_03_check_token_double_deny(self):
        # 服务端未配置：任何 provided 都拒（含非空）
        self.assertFalse(security.check_token(self.vault, "anything"))
        self.assertFalse(security.check_token(self.vault, ""))


class TestTokenApi(_WebBase):
    def test_01_missing_token_401(self):
        r = self.client.get("/api/v1/stats")
        self.assertEqual(r.status_code, 401)

    def test_02_header_ok(self):
        r = self.client.get("/api/v1/stats", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], self.vault.name)
        self.assertEqual(r.json()["schema_version"] if
                         "schema_version" in r.json() else 1, 1)

    def test_03_bearer_ok(self):
        r = self.client.get("/api/v1/stats",
                            headers={"Authorization": "Bearer " + TOKEN})
        self.assertEqual(r.status_code, 200)

    def test_04_wrong_token_401(self):
        r = self.client.get("/api/v1/stats",
                            headers={"X-Cenhua-Token": TOKEN + "x"})
        self.assertEqual(r.status_code, 401)

    def test_05_cookie_ok(self):
        # EventSource 同源回退：登录后 cookie 即可调 API
        self.login()
        r = self.client.get("/api/v1/stats")
        self.assertEqual(r.status_code, 200)


class TestRateLimit(_WebBase):
    rate = (2, 60)

    def test_01_third_call_429(self):
        codes = [self.client.get("/api/v1/stats",
                                 headers=self.auth).status_code
                 for _ in range(3)]
        self.assertEqual(codes[:2], [200, 200])
        self.assertEqual(codes[2], 429)

    def test_02_retry_after_header(self):
        for _ in range(2):
            self.client.get("/api/v1/stats", headers=self.auth)
        r = self.client.get("/api/v1/stats", headers=self.auth)
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r.headers)
        self.assertGreaterEqual(int(r.headers["Retry-After"]), 1)
        self.assertEqual(r.json()["detail"]["error"], "rate limit exceeded")


class TestM4bGraphApi(_WebBase):
    """M4b 任务 6/16：GET /api/v1/graph 真端点（guard 鉴权 + view 形态）。"""

    def setUp(self):
        super().setUp()
        _seed_doc(self.vault, "pi-graph1", "graph-src.txt",
                  ["分布式 共识 Raft 选主 协议", "第二页 日志 复制 机制"])

    def test_01_graph_requires_auth(self):
        r = self.client.get("/api/v1/graph")
        self.assertEqual(r.status_code, 401)

    def test_02_graph_shape(self):
        r = self.client.get("/api/v1/graph", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()                          # 空图也会自动 rebuild
        for key in ("ts", "tier", "n_docs", "center", "nodes", "edges",
                    "total_nodes", "total_edges", "truncated"):
            self.assertIn(key, body)
        self.assertEqual(body["schema_version"], 1)
        self.assertIsInstance(body["nodes"], list)
        self.assertIsInstance(body["edges"], list)

    def test_03_graph_entity_param(self):
        r = self.client.get("/api/v1/graph?entity=不存在的实体",
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["center"], "")   # 解析不到 -> 无中心

    def test_04_graph_max_nodes_bound(self):
        r = self.client.get("/api/v1/graph?max_nodes=9999",
                            headers=self.auth)
        self.assertEqual(r.status_code, 422)       # Query le=500


class TestM4bDraftApi(_WebBase):
    """M4b 任务 16/11：POST /api/v1/draft + /drafts 系列端点。"""

    def setUp(self):
        super().setUp()
        _seed_doc(self.vault, "pi-cite1", "cite-src.txt",
                  ["分布式 共识 算法 Raft 选主", "第二页 日志 复制"])
        self.dfile = "共识_V1_2026-01-01.md"
        self.dtext = ("<!-- draft: topic=共识 rid=r1 -->\n"
                      "<!-- derived_from: pi-cite1 -->\n"
                      "<!-- mode: new -->\n"
                      "# 共识\n\n## 1. 概述\n\n正文一段。\n\n"
                      "> 引文 [pi-cite1 P1] 分布式 共识 算法 Raft 选主 · ✓\n")
        DR._atomic_write(os.path.join(DR.drafts_dir(self.vault),
                                      self.dfile), self.dtext)

    # ---- POST /api/v1/draft（任务通道提交面） ----

    def test_01_draft_no_topic_422(self):
        r = self.client.post("/api/v1/draft", json={}, headers=self.auth)
        self.assertEqual(r.status_code, 422)

    def test_02_draft_bad_mode_422(self):
        r = self.client.post("/api/v1/draft",
                             json={"topic": "共识", "mode": "xx"},
                             headers=self.auth)
        self.assertEqual(r.status_code, 422)

    def test_03_draft_requires_auth(self):
        r = self.client.post("/api/v1/draft", json={"topic": "x"})
        self.assertEqual(r.status_code, 401)

    def test_04_draft_dry_run_submits_job(self):
        r = self.client.post("/api/v1/draft",
                             json={"topic": "共识", "dry_run": True},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("job_id", body["job"])
        self.assertTrue(body["events_url"].startswith("/api/v1/jobs/"))
        st = J.wait(J.JobHandle.from_dict(body["job"]), poll=0.01,
                    timeout=30)
        self.assertIn(st.state, (J.DONE, J.FAILED))   # dry_run 不打网关

    # ---- GET /drafts 列表 + detail ----

    def test_05_list_drafts(self):
        r = self.client.get("/api/v1/drafts", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["drafts"][0]["file"], self.dfile)
        self.assertEqual(body["drafts"][0]["topic"], "共识")
        self.assertEqual(body["drafts"][0]["version"], 1)

    def test_06_detail_citations_ok(self):
        r = self.client.get("/api/v1/drafts/"
                            + quote(self.dfile),
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["rc"], 0)
        self.assertEqual(body["topic"], "共识")
        self.assertIn("正文一段", body["text"])
        self.assertEqual(len(body["citations"]), 1)
        c = body["citations"][0]
        self.assertTrue(c["ok"])                     # primary 文本层直验
        self.assertEqual(c["via"], "direct")
        self.assertEqual(c["doc"], "pi-cite1")       # resolve_ids 补全
        self.assertEqual(c["line"], 9)
        self.assertEqual(len(body["versions"]), 1)

    def test_07_detail_missing_404(self):
        r = self.client.get("/api/v1/drafts/nope_V1_2026-01-01.md",
                            headers=self.auth)
        self.assertEqual(r.status_code, 404)

    def test_08_detail_traversal_404(self):
        r = self.client.get("/api/v1/drafts/%2e%2e%2Fvault.yaml",
                            headers=self.auth)
        self.assertIn(r.status_code, (404, 422))     # 穿越不进文件系统

    # ---- PUT 保存 + 重验 ----

    def test_09_put_save_reverify_fail(self):
        bad = self.dtext.replace("Raft 选主", "ZooKeeper 选主")
        r = self.client.put("/api/v1/drafts/" + quote(self.dfile),
                            json={"text": bad}, headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["rc"], 1)              # 引文重验有失败
        self.assertFalse(body["citations"][0]["ok"])
        with open(os.path.join(DR.drafts_dir(self.vault), self.dfile),
                  encoding="utf-8") as fh:           # 读回比对：已落盘
            self.assertIn("ZooKeeper", fh.read())

    def test_10_put_save_ok(self):
        r = self.client.put("/api/v1/drafts/" + quote(self.dfile),
                            json={"text": self.dtext}, headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["rc"], 0)

    def test_11_put_missing_404(self):
        r = self.client.put("/api/v1/drafts/nope_V1_2026-01-01.md",
                            json={"text": "x"}, headers=self.auth)
        self.assertEqual(r.status_code, 404)

    def test_12_put_text_required_422(self):
        r = self.client.put("/api/v1/drafts/" + quote(self.dfile),
                            json={}, headers=self.auth)
        self.assertEqual(r.status_code, 422)

    # ---- 引文穿透 excerpt ----

    def test_13_excerpt_direct(self):
        r = self.client.get("/api/v1/drafts/"
                            + quote(self.dfile) + "/excerpt",
                            params={"doc": "pi-cite1", "page": "1",
                                    "snippet": "Raft 选主"},
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertIn("Raft", body["excerpt"])
        self.assertEqual(body["doc"], "pi-cite1")

    def test_14_excerpt_miss_falls_back(self):
        r = self.client.get("/api/v1/drafts/"
                            + quote(self.dfile) + "/excerpt",
                            params={"doc": "pi-cite1", "page": "1",
                                    "snippet": "绝无此句"},
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertIn("excerpt", body)               # 页首预览兜底

    # ---- 版本对比 diff ----

    def test_15_diff(self):
        f2 = "共识_V2_2026-01-02.md"
        DR._atomic_write(os.path.join(DR.drafts_dir(self.vault), f2),
                         self.dtext.replace("正文一段", "正文两段扩写"))
        r = self.client.get("/api/v1/drafts/-/diff",
                            params={"a": self.dfile, "b": f2},
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["rc"], 0)
        self.assertTrue(any("扩写" in ln for ln in body["diff"]))
        r2 = self.client.get("/api/v1/drafts/-/diff",
                             params={"a": self.dfile, "b": self.dfile},
                             headers=self.auth)
        self.assertEqual(r2.json()["rc"], 1)         # 一致
        r3 = self.client.get("/api/v1/drafts/-/diff",
                             params={"a": "nope_V1_2026-01-01.md",
                                     "b": self.dfile}, headers=self.auth)
        self.assertEqual(r3.status_code, 404)


class TestApiEndpoints(_WebBase):
    def setUp(self):
        super().setUp()
        _seed_doc(self.vault, "pi-alpha", "alpha.txt",
                  ["量子计算 入门 笔记", "第二段 纠缠"])
        self.doc_id = "pi-alpha"

    def test_01_documents(self):
        r = self.client.get("/api/v1/documents", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["total"], 1)
        d = body["documents"][0]
        self.assertTrue(d["text_layer"])
        self.assertIn("tier", d)

    def test_02_find_grouped(self):
        r = self.client.post("/api/v1/find", json={"terms": ["纠缠"]},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json()["total"], 1)

    def test_03_find_empty_terms_422(self):
        r = self.client.post("/api/v1/find", json={}, headers=self.auth)
        self.assertEqual(r.status_code, 422)

    def test_04_relations_shape(self):
        r = self.client.get("/api/v1/relations?doc=" + self.doc_id,
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["doc"], self.doc_id)
        self.assertIsInstance(r.json()["relations"], list)

    def test_05_ingest_multipart(self):
        r = self.client.post("/api/v1/ingest", headers=self.auth,
                             files={"file": ("beta.txt", "新增 文档 内容",
                                             "text/plain")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "added")
        # 落 inbox 且 fsync 后可见（fake ingest 不动 store，验的是文件面）
        self.assertTrue(os.path.isfile(os.path.join(self.vault.inbox,
                                                    "beta.txt")))

    def test_06_ingest_duplicate_name_no_clobber(self):
        for _ in range(2):
            r = self.client.post(
                "/api/v1/ingest", headers=self.auth,
                files={"file": ("g0.txt", "网关 测试 语料 唯一", "text/plain")})
            self.assertEqual(r.status_code, 200)
        # inbox 同名避让：原件未被覆盖
        with open(os.path.join(self.vault.inbox, "g0.txt"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "网关 测试 语料 唯一")
        names = os.listdir(self.vault.inbox)
        self.assertEqual(len([n for n in names if n.startswith("g0")]), 2)


class TestDocMeta(_WebBase):
    """编织页标签/笔记：API 往返 + 原子落盘（读回比对）。"""

    def setUp(self):
        super().setUp()
        _seed_doc(self.vault, "pi-meta", "meta-doc.txt", ["标签 笔记 测试"])
        self.doc_id = "pi-meta"

    def test_01_post_then_get(self):
        r = self.client.post("/api/v1/docmeta",
                             json={"doc": self.doc_id,
                                   "tags": ["读", "读", "重点"],
                                   "note": "第一版"},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["tags"], ["读", "重点"])   # 去空去重保序
        r2 = self.client.get("/api/v1/docmeta?doc=" + self.doc_id,
                             headers=self.auth)
        self.assertEqual(r2.json()["tags"], ["读", "重点"])
        self.assertEqual(r2.json()["note"], "第一版")

    def test_02_partial_update(self):
        DM.update(self.vault, self.doc_id, tags=["a"], note="n1")
        r = self.client.post("/api/v1/docmeta",
                             json={"doc": self.doc_id, "note": "n2"},
                             headers=self.auth)
        self.assertEqual(r.json()["tags"], ["a"])     # tags=None 不触碰
        self.assertEqual(r.json()["note"], "n2")

    def test_03_disk_readback(self):
        self.client.post("/api/v1/docmeta",
                         json={"doc": self.doc_id, "tags": ["盘"]},
                         headers=self.auth)
        fresh = DM.load(self.vault)                    # 读回比对
        self.assertEqual(fresh[self.doc_id]["tags"], ["盘"])

    def test_04_missing_doc_422(self):
        r = self.client.post("/api/v1/docmeta", json={}, headers=self.auth)
        self.assertEqual(r.status_code, 422)


# ------------------------------------------------ 任务通道 + SSE 适配 --
from dataclasses import dataclass, field                    # noqa: E402
from typing import List                                    # noqa: E402


@dataclass
class _FakeResult:
    lines: List[str] = field(default_factory=list)
    cost: dict = field(default_factory=dict)


def _fake_ok(rt=None):
    return _FakeResult(lines=["第一行", "第二行"])


def _fake_fail():
    raise RuntimeError("boom-fake")


class TestJobsApi(_WebBase):
    def _submit(self, fn, kind="query"):
        spec = core.channel_job(kind, fn)
        return J.submit(spec)

    def test_01_query_requires_question(self):
        r = self.client.post("/api/v1/query", json={}, headers=self.auth)
        self.assertEqual(r.status_code, 422)

    def test_02_status_incremental_cursor(self):
        h = self._submit(_fake_ok)
        J.wait(h, poll=0.01, timeout=10)
        r = self.client.get("/api/v1/jobs/%s/status" % h.job_id,
                            headers=self.auth)
        st = r.json()
        self.assertEqual(st["state"], J.DONE)
        self.assertEqual(st["cursor"], 2)              # 两行 chunks
        r2 = self.client.get("/api/v1/jobs/%s/status?cursor=2" % h.job_id,
                             headers=self.auth)
        self.assertEqual(r2.json()["chunks"], [])      # 增量协议：已消费
        self.assertEqual(r2.json()["cursor"], 2)

    def test_03_result_ok_and_failed(self):
        h = self._submit(_fake_ok)
        J.wait(h, poll=0.01, timeout=10)
        r = self.client.get("/api/v1/jobs/%s/result" % h.job_id,
                            headers=self.auth)
        self.assertEqual(r.json()["lines"], ["第一行", "第二行"])
        hf = self._submit(_fake_fail)
        st = J.wait(hf, poll=0.01, timeout=10)
        self.assertEqual(st.state, J.FAILED)          # wait 到终态不抛错
        with self.assertRaises(J.JobFailed):
            J.job_result(hf)                          # 抛错的是 job_result
        rf = self.client.get("/api/v1/jobs/%s/result" % hf.job_id,
                             headers=self.auth)
        self.assertEqual(rf.status_code, 500)

    def test_04_unknown_job_stale_not_404(self):
        # ADR-001：未知 handle 恒定 aborted/stale，不抛错
        r = self.client.get("/api/v1/jobs/nope123/status",
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["state"], J.ABORTED)
        self.assertEqual(r.json()["reason"], "stale")

    def test_05_sse_stream(self):
        h = self._submit(_fake_ok)
        with self.client.stream("GET", "/api/v1/jobs/" + h.job_id,
                                headers=self.auth) as resp:
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.headers["content-type"]
                            .startswith("text/event-stream"))
            text = resp.read().decode("utf-8")
        self.assertIn("event: chunk", text)
        self.assertIn("第一行", text)
        self.assertIn("event: done", text)

    def test_06_sse_reconnect_replay(self):
        # 断线重连：?cursor=1 只重放未消费部分
        h = self._submit(_fake_ok)
        J.wait(h, poll=0.01, timeout=10)
        with self.client.stream("GET",
                                "/api/v1/jobs/%s?cursor=1" % h.job_id,
                                headers=self.auth) as resp:
            text = resp.read().decode("utf-8")
        self.assertNotIn("第一行", text)
        self.assertIn("第二行", text)
        self.assertIn("event: done", text)

    def test_07_sse_failed_event(self):
        h = self._submit(_fake_fail)
        with self.client.stream("GET", "/api/v1/jobs/" + h.job_id,
                                headers=self.auth) as resp:
            text = resp.read().decode("utf-8")
        self.assertIn("event: failed", text)
        self.assertIn("boom-fake", text)

    def test_08_ask_digest_endpoints_submit(self):
        r = self.client.post("/api/v1/ask", json={"question": "问题"},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertIn("job_id", r.json()["job"])
        self.assertTrue(r.json()["events_url"].startswith("/api/v1/jobs/"))


class TestPages(_WebBase):
    def setUp(self):
        super().setUp()
        _seed_doc(self.vault, "pi-page", "page-doc.txt", ["页面 测试 语料"])

    def test_01_login_bad_token(self):
        r = self.client.post("/login", data={"token": "wrong"},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/login?bad=1")
        self.assertNotIn("cenhua_token", r.cookies)

    def test_02_login_good_sets_httponly_cookie(self):
        r = self.login()
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/ingest")
        sc = r.headers.get("set-cookie", "")
        self.assertIn("cenhua_token=", sc)
        self.assertIn("HttpOnly", sc)

    def test_03_pages_require_login(self):
        for path in ("/ingest", "/search", "/weave", "/insights"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 303, path)
            self.assertEqual(r.headers["location"], "/login", path)
        # 首页 = 303 /ingest（再由其守卫转登录）
        self.assertEqual(self.client.get("/").headers["location"], "/ingest")
        # 未登录时 API 仍拒绝（cookie 通道独立：新客户端无 cookie）
        c2 = self._mk(self.vault)
        self.assertEqual(c2.get("/api/v1/stats").status_code, 401)

    def test_04_four_pages_after_login(self):
        self.login()
        for path in ("/ingest", "/search", "/weave", "/insights"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)

    def test_05_search_find_groups(self):
        self.login()
        r = self.client.get("/search?q=语料")
        self.assertEqual(r.status_code, 200)
        self.assertIn("page-doc", r.text)

    def test_06_doc_page_fulltext(self):
        self.login()
        r = self.client.get("/doc/pi-page")
        self.assertEqual(r.status_code, 200)
        self.assertIn("页面 测试 语料", r.text)

    def test_07_weave_meta_form_then_relations_part(self):
        self.login()
        doc_id = "pi-page"
        r = self.client.post("/weave/meta",
                             data={"doc": doc_id, "tags": "甲，乙 c"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("saved", r.text)
        self.assertEqual(DM.get(self.vault, doc_id).tags, ["甲", "乙", "c"])
        r2 = self.client.get("/relations.part?doc=" + doc_id)
        self.assertEqual(r2.status_code, 200)
        # 无边 -> no relations 提示；有边 -> mermaid 图部件
        self.assertTrue("mermaid" in r2.text.lower()
                        or "no relations" in r2.text)

    def test_08_ingest_file_form(self):
        self.login()
        r = self.client.post("/ingest/file",
                             files={"file": ("web-up.txt", "网页 上传 内容",
                                             "text/plain")})
        self.assertEqual(r.status_code, 200)
        self.assertIn("added", r.text)
        # fake ingest 不动 store：验落盘文件面
        self.assertTrue(os.path.isfile(os.path.join(self.vault.inbox,
                                                    "web-up.txt")))

    def test_09_ingest_url_job_sse_hookup(self):
        # 不真联网：只验任务通道接线（job 会失败，但 handle/订阅面就绪）
        self.login()
        r = self.client.post("/ingest/url",
                             data={"url": "http://127.0.0.1:9/nope"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("data-job=", r.text)

    def test_10_insights_readonly_and_traversal(self):
        self.login()
        ddir = os.path.join(self.vault.works, "digests")
        os.makedirs(ddir, exist_ok=True)
        with open(os.path.join(ddir, "digest-2026w01.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("# 周记\n\n<script>alert(1)</script>\n正文 onerror=x\n")
        r = self.client.get("/insights")
        self.assertIn("digest-2026w01.md", r.text)
        r2 = self.client.get("/insights/digest-2026w01.md")
        self.assertEqual(r2.status_code, 200)
        self.assertNotIn("<script>", r2.text)          # 消毒
        self.assertNotIn("onerror=", r2.text)
        self.assertIn("正文", r2.text)
        r3 = self.client.get("/insights/..%2Fvault.yaml")
        self.assertIn(r3.status_code, (400, 404))      # 路径穿越防护

    def test_11_rid_log(self):
        # rid 中间件：透传 + 响应头回写 + logs/web-YYYYMM.log 落盘
        r = self.client.get("/api/v1/stats",
                            headers={"X-Cenhua-Rid": "rid-test",
                                     **self.auth})
        self.assertEqual(r.headers.get("X-Cenhua-Rid"), "rid-test")
        logf = os.path.join(self.vault.logs,
                            "web-%s.log" % __import__("time").strftime(
                                "%Y%m"))
        self.assertTrue(os.path.isfile(logf))
        with open(logf, encoding="utf-8") as fh:
            self.assertIn("rid-test GET /api/v1/stats 200", fh.read())

    # ------------------------- M4b 页面（任务 6/11 页面面） -------------
    def test_12_graph_page(self):
        for path in ("/graph",):
            self.assertEqual(self.client.get(path).status_code, 303)
        self.login()
        r = self.client.get("/graph")
        self.assertEqual(r.status_code, 200)
        self.assertIn("force.js", r.text)            # 力导向脚本挂载
        self.assertIn("CENHUA_GRAPH", r.text)        # 参数注入

    def test_13_drafts_pages(self):
        dfile = "页面_V1_2026-01-01.md"
        text = ("<!-- draft: topic=页面 -->\n<!-- mode: new -->\n"
                "# 页面\n\n## 1. 段\n\n正文。\n\n"
                "> 引文 [pi-page P1] 页面 测试 语料 · ✓\n")
        DR._atomic_write(os.path.join(DR.drafts_dir(self.vault),
                                      dfile), text)
        self.login()
        r = self.client.get("/drafts")
        self.assertEqual(r.status_code, 200)
        self.assertIn(quote(dfile), r.text)          # 链接为 URL 编码
        r2 = self.client.get("/drafts/" + quote(dfile))
        self.assertEqual(r2.status_code, 200)
        self.assertIn("CENHUA_DRAFT", r2.text)
        self.assertIn("页面 测试 语料", r2.text)      # 引文表带 snippet
        self.assertIn("V1", r.text)                  # 列表页含版本
        r3 = self.client.get("/drafts/nope_V1_2026-01-01.md")
        self.assertEqual(r3.status_code, 404)

    def test_14_drafts_generate_requires_topic(self):
        self.login()
        r = self.client.post("/drafts/generate", data={})
        self.assertEqual(r.status_code, 422)
        r2 = self.client.post("/drafts/generate",
                              data={"topic": "共识", "dry_run": "on"})
        self.assertEqual(r2.status_code, 200)
        self.assertIn("data-job=", r2.text)          # joblog 接线


class TestConfig(_WebBase):
    """host/port 解析：默认 / env / vault.yaml / 坏值回落。"""

    def test_01_defaults(self):
        os.environ.pop("CENHUA_WEB_HOST", None)
        os.environ.pop("CENHUA_WEB_PORT", None)
        self.assertEqual(W.resolve_host(self.vault), "127.0.0.1")
        self.assertEqual(W.resolve_port(self.vault), 8765)

    def test_02_yaml_then_env(self):
        cfg = os.path.join(self.vault.root, "vault.yaml")
        with open(cfg, "a", encoding="utf-8") as fh:
            fh.write("web_host: 0.0.0.0\nweb_port: 9000\n")
        v2 = L.Vault(self.vault.name)                    # cfg() 每次读文件
        self.assertEqual(W.resolve_host(v2), "0.0.0.0")
        self.assertEqual(W.resolve_port(v2), 9000)
        os.environ["CENHUA_WEB_PORT"] = "9999"
        try:
            self.assertEqual(W.resolve_port(v2), 9999)   # env 优先
        finally:
            os.environ.pop("CENHUA_WEB_PORT", None)

    def test_03_bad_value_fallback(self):
        os.environ["CENHUA_WEB_PORT"] = "not-a-port"
        try:
            self.assertEqual(W.resolve_port(self.vault), 8765)
        finally:
            os.environ.pop("CENHUA_WEB_PORT", None)

    def test_04_ingest_url_job_lines(self):
        # service 面包装：CLI print 被捕获成 lines（不真联网走失败分支）
        res = P.ingest_url_job(self.vault, "http://127.0.0.1:9/nope")
        self.assertIsInstance(res, P.UrlIngestResult)
        self.assertEqual(res.status, "failed")
        self.assertEqual(res.rc, 1)
        self.assertIsInstance(res.lines, list)


# --------------------------------------- M5-3：多库 / 导出 / 交互补齐 --
try:
    import fitz as _fitz  # noqa: F401
    _HAS_PYMUPDF = True
except Exception:
    try:
        import pymupdf as _pymupdf  # noqa: F401
        _HAS_PYMUPDF = True
    except Exception:
        _HAS_PYMUPDF = False


class TestVaultSwitch(_WebBase):
    """M5-3 多库：/vaults 发现面 + ?vault= 数据面切换 + 页面 cookie 切换。"""

    def setUp(self):
        super().setUp()
        self.vault2 = _init_vault("webui-second-" + self.id().split(".")[-1])
        _seed_doc(self.vault2, "pi-v2", "v2-doc.txt", ["第二库 语料"])

    def test_01_vaults_requires_auth(self):
        r = self.client.get("/api/v1/vaults")
        self.assertEqual(r.status_code, 401)

    def test_02_vaults_list(self):
        r = self.client.get("/api/v1/vaults", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn(self.vault.name, body["vaults"])
        self.assertIn(self.vault2.name, body["vaults"])
        self.assertEqual(body["current"], self.vault.name)

    def test_03_query_param_switch_documents(self):
        r = self.client.get("/api/v1/documents",
                            params={"vault": self.vault2.name},
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        docs = r.json()["documents"]
        self.assertEqual([d["doc_id"] for d in docs], ["pi-v2"])

    def test_04_stats_follows_vault(self):
        r = self.client.get("/api/v1/stats",
                            params={"vault": self.vault2.name},
                            headers=self.auth)
        self.assertEqual(r.json()["name"], self.vault2.name)

    def test_05_unknown_vault_400(self):
        r = self.client.get("/api/v1/stats", params={"vault": "nope"},
                            headers=self.auth)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"]["error"], "unknown vault")

    def test_06_page_cookie_switch(self):
        self.login()
        r = self.client.post("/vault/switch",
                             data={"vault": self.vault2.name,
                                   "next": "/ingest"})
        self.assertEqual(r.status_code, 303)
        self.assertIn("cenhua_vault=", r.headers.get("set-cookie", ""))
        r2 = self.client.get("/ingest")          # cookie 自动带上
        self.assertEqual(r2.status_code, 200)
        self.assertIn(self.vault2.name, r2.text)  # 下拉选中当前库

    def test_07_switch_bad_vault_no_cookie(self):
        self.login()
        r = self.client.post("/vault/switch",
                             data={"vault": "nope", "next": "/ingest"})
        self.assertEqual(r.status_code, 303)
        self.assertNotIn("cenhua_vault=", r.headers.get("set-cookie", ""))

    def test_08_page_fallback_unknown_cookie(self):
        self.login()
        self.client.cookies.set("cenhua_vault", "ghost-vault")
        r = self.client.get("/ingest")           # 非法 cookie 安全回落启动库
        self.assertEqual(r.status_code, 200)


class TestDraftExport(_WebBase):
    """M5-3 导出下载：/drafts/{fname}/export?fmt=（复用 exporter）。"""

    def setUp(self):
        super().setUp()
        _seed_doc(self.vault, "pi-exp1", "exp-src.txt",
                  ["导出 测试 语料 Raft"])
        self.dfile = "导出_V1_2026-01-01.md"
        self.dtext = ("<!-- draft: topic=导出 rid=r1 -->\n"
                      "<!-- derived_from: pi-exp1 -->\n"
                      "<!-- mode: new -->\n"
                      "# 导出\n\n## 1. 概述\n\n正文内容。\n\n"
                      "> 引文 [pi-exp1 P1] 导出 测试 语料 Raft · ✓\n")
        DR._atomic_write(os.path.join(DR.drafts_dir(self.vault),
                                      self.dfile), self.dtext)

    def test_01_export_md(self):
        r = self.client.get("/api/v1/drafts/" + quote(self.dfile) + "/export",
                            params={"fmt": "md"}, headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/markdown"))
        self.assertIn("attachment", r.headers.get("content-disposition", ""))
        self.assertEqual(r.content.decode("utf-8"), self.dtext)  # 读回比对
        # 产物同径落 works/exports/（与 CLI export 一致）
        self.assertTrue(os.path.isfile(os.path.join(
            self.vault.works, "exports",
            os.path.splitext(self.dfile)[0] + ".md")))

    def test_02_export_html(self):
        r = self.client.get("/api/v1/drafts/" + quote(self.dfile) + "/export",
                            params={"fmt": "html"}, headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/html"))
        self.assertIn("<html", r.content.decode("utf-8"))

    @unittest.skipUnless(_HAS_PYMUPDF, "pymupdf not installed")
    def test_03_export_pdf(self):
        r = self.client.get("/api/v1/drafts/" + quote(self.dfile) + "/export",
                            params={"fmt": "pdf"}, headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"]
                        .startswith("application/pdf"))
        self.assertEqual(r.content[:4], b"%PDF")

    def test_04_bad_fmt_422(self):
        r = self.client.get("/api/v1/drafts/" + quote(self.dfile) + "/export",
                            params={"fmt": "exe"}, headers=self.auth)
        self.assertEqual(r.status_code, 422)

    def test_05_missing_draft_404(self):
        r = self.client.get("/api/v1/drafts/nope_V1_2026-01-01.md/export",
                            params={"fmt": "md"}, headers=self.auth)
        self.assertEqual(r.status_code, 404)

    def test_06_edit_page_has_buttons(self):
        self.login()
        r = self.client.get("/drafts/" + quote(self.dfile))
        self.assertEqual(r.status_code, 200)
        self.assertIn("export?fmt=md", r.text)


class TestSearchInsightsInterop(_WebBase):
    """M5-3 检索/洞察页交互补齐：find 高级参数 + digest 生成任务接线。"""

    def setUp(self):
        super().setUp()
        _seed_doc(self.vault, "pi-inter", "inter-doc.txt",
                  ["交互 测试 语料 Raft", "第二页 分散 语料"])

    def test_01_find_regex_and_ic(self):
        self.login()
        r = self.client.get("/search", params={
            "q": "R.ft", "mode": "find", "regex": "on"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("inter-doc", r.text)               # 正则命中
        r2 = self.client.get("/search", params={
            "q": "RAFT", "mode": "find"})                # 默认忽略大小写
        self.assertIn("inter-doc", r2.text)
        r3 = self.client.get("/search", params={
            "q": "RAFT", "mode": "find", "ic": ""})      # 区分大小写
        self.assertIn("没有命中", r3.text)

    def test_02_find_docs_selector_param(self):
        self.login()
        r = self.client.get("/search", params={
            "q": "语料", "mode": "find", "docs": "pi-inter"})
        self.assertEqual(r.status_code, 200)

    def test_03_query_dry_submit(self):
        self.login()
        r = self.client.get("/search", params={
            "q": "语料", "mode": "query", "dry": "on", "derived": "on"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("data-job=", r.text)

    def test_04_ask_all_docs_limit(self):
        self.login()
        r = self.client.get("/search", params={
            "q": "语料", "mode": "ask", "alldocs": "on", "limit": "5"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("data-job=", r.text)

    def test_05_insights_generate_dry(self):
        self.login()
        r = self.client.post("/insights/generate",
                             data={"kind": "weekly", "dry_run": "on"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("data-job=", r.text)

    def test_06_insights_generate_bad_kind_422(self):
        self.login()
        r = self.client.post("/insights/generate", data={"kind": "xx"})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromModule(
        sys.modules[__name__])
    ret = unittest.TextTestRunner(verbosity=2).run(suite)
    shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(0 if ret.wasSuccessful() else 1)
