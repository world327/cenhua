#!/usr/bin/env python3
"""test_core.py — M3a 六核心函数 service 化单测（契约 §3.5 core）。

手搭 vault（test_query 同款，零引擎依赖）：ingest 失败路径 + find/stats/
query/ask/related 结构化返回断言。纯离线：无网关环节按 rc 语义断言。
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_TEST_HOME = tempfile.mkdtemp(prefix="cenhua-core-")
os.environ["CENHUA_HOME"] = _TEST_HOME
os.environ["CENHUA_CONFIG_DIR"] = os.path.join(_TEST_HOME, "config-dir")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import m_lib as L  # noqa: E402
from cenhua_service import core  # noqa: E402

DOC_A = ("=== PAGE 1 ===\n华兴科技采购合同，金额 128.5万元。\n"
         "=== PAGE 2 ===\n违约罚金按日 0.05% 计，penalty clause 见第 7.2 条。\n")


class CoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        for k in ("PI_BASE", "PI_KEY"):
            os.environ.pop(k, None)
        r = subprocess.run([os.path.join(ROOT, "bin", "cenhua"), "init",
                            "ct", "--yes"], capture_output=True, text=True,
                           env=dict(os.environ, CENHUA_HOME=_TEST_HOME),
                           timeout=120)
        assert r.returncode == 0, r.stderr
        cls.vault = L.Vault("ct")
        os.makedirs(cls.vault.textdir, exist_ok=True)
        os.makedirs(cls.vault.store, exist_ok=True)
        with open(os.path.join(cls.vault.textdir, "pi-x1.txt"),
                  "w", encoding="utf-8") as f:
            f.write(DOC_A)
        with open(os.path.join(cls.vault.store, "ingest_manifest.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"pi-x1": {"name": "合同A.pdf", "tier": "primary",
                                 "ts": "2026-10-16 10:00:00"}}, f)

    # ------------------------------------------------------------ find ----
    def test_01_find_hit_fields(self):
        hits = core.find(self.vault, ["penalty"])
        self.assertEqual(len(hits), 1)
        h = hits[0]
        self.assertEqual(h.doc, "pi-x1")
        self.assertEqual(h.name, "合同A.pdf")
        self.assertEqual(h.page, "2")
        self.assertIn("penalty", h.line)

    def test_02_find_empty_and_miss(self):
        self.assertEqual(core.find(self.vault, []), [])
        self.assertEqual(core.find(self.vault, ["绝不存在的词XYZQ"]), [])

    def test_03_find_selector_and_regex(self):
        self.assertEqual(core.find(self.vault, ["penalty"],
                                   docs_selector="不匹配的选择器"), [])
        hits = core.find(self.vault, [r"128\.\d+万元"], regex=True)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].page, "1")

    def test_04_find_max_per_doc(self):
        with open(os.path.join(self.vault.textdir, "pi-x2.txt"),
                  "w", encoding="utf-8") as f:
            f.write("=== PAGE 1 ===\n" + "penalty here\n" * 30)
        # find/stats 以台账(store/ingest_manifest.json)为准，需同步登记
        with open(os.path.join(self.vault.store, "ingest_manifest.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"pi-x1": {"name": "合同A.pdf", "tier": "primary",
                                 "ts": "2026-10-16 10:00:00"},
                       "pi-x2": {"name": "合同B.pdf", "tier": "primary",
                                 "ts": "2026-10-16 10:01:00"}}, f)
        hits = core.find(self.vault, ["penalty"], docs_selector="pi-x2",
                         max_per_doc=5)
        self.assertEqual(len([h for h in hits if h.doc == "pi-x2"]), 5)

    # ------------------------------------------------------------ stats ----
    def test_10_stats(self):
        st = core.stats(self.vault)
        self.assertEqual(st.name, "ct")
        self.assertGreaterEqual(st.docs, 2)
        self.assertFalse(st.gateway_ready)     # 测试环境无 PI_BASE
        lines = core.stats_lines(self.vault, st)
        self.assertTrue(any("documents" in l for l in lines))

    # ------------------------------------------------------------ ask ----
    def test_20_ask_scope_errors(self):
        self.assertEqual(core.ask(self.vault, "").rc, 2)
        self.assertEqual(core.ask(self.vault, "问题").rc, 2)   # 无 scope
        ar = core.ask(self.vault, "问题", doc="不存在的选择器ZZZ")
        self.assertEqual(ar.rc, 2)

    def test_21_ask_dry_run_priced(self):
        ar = core.ask(self.vault, "金额多少", doc="合同A", dry_run=True)
        self.assertEqual(ar.rc, 0)
        self.assertIsNotNone(ar.cost)
        self.assertIn("est_cost", ar.cost)
        self.assertTrue(any("dry run" in l for l in ar.lines))

    def test_22_ask_no_gateway_rc3(self):
        ar = core.ask(self.vault, "金额多少", doc="合同A")
        self.assertEqual(ar.rc, 3)
        self.assertIn("gateway", ar.error.lower())

    def test_23_ask_ceiling_rc4(self):
        ar = core.ask(self.vault, "金额多少", all_docs=True, limit=1000)
        # 无网关时 ceiling 先于网关检查？顺序：cost_gate→ceiling→gateway
        # 无 PI_MODEL 定价走保守默认价，1 篇不会超 2.0 预算；limit=1000
        # 目标数=库内文档数(2)，低于 cap(默认10)，所以到这里应是 rc=3
        self.assertIn(ar.rc, (3, 4))

    # ------------------------------------------------------------ query ----
    def test_30_query_structured(self):
        qr = core.query(self.vault, "penalty clause")
        self.assertEqual(qr.rc, 0)
        self.assertIsInstance(qr.lines, list)
        self.assertIn("合同A.pdf", qr.answer)   # 无网关时仅命中列表段

    def test_31_query_miss_refused(self):
        qr = core.query(self.vault, "火星殖民地开采配额")
        self.assertEqual(qr.rc, 1)

    # ------------------------------------------------------------ related ----
    def test_40_related_empty_ok(self):
        self.assertEqual(core.related(self.vault, "pi-x1"), [])

    # ------------------------------------------------------------ ingest ----
    def test_50_ingest_unsupported_failed(self):
        bad = os.path.join(_TEST_HOME, "bad.zip")
        with open(bad, "w") as f:
            f.write("x")
        ir = core.ingest(self.vault, bad)
        self.assertEqual(ir.status, "failed")
        self.assertEqual(ir.doc_id, "")

    def test_51_result_schema_versions(self):
        self.assertEqual(core.IngestResult().schema_version, 1)
        self.assertEqual(core.FindHit().schema_version, 1)
        self.assertEqual(core.QueryResult().schema_version, 2)
        self.assertEqual(core.AskResult().schema_version, 2)
        self.assertEqual(core.VaultStats().schema_version, 1)
        self.assertEqual(core.Relation().schema_version, 1)

    def test_52_ingest_added_triggers_flatten(self):
        """防回潮：core.ingest 成功必须自动 rebuild 文本层。

        Web/API 上传曾走 core.ingest 而缺 flatten，新文档 find 静默
        不可见（"上传后搜不到"），与 CLI add() 语义不一致。
        """
        import m_ingest
        calls = []
        orig_one, orig_re = m_ingest.ingest_one, L.run_engine
        orig_sha1 = L.sha1
        try:
            m_ingest.ingest_one = lambda v, p, quiet=False: "added"
            L.sha1 = lambda p: "sha1-fake"
            m_ingest.dedupe_index = lambda v: {}

            def fake_re(script, args, vault, capture=False, **kw):
                calls.append(script)
                return 0, "rebuilt 1"

            L.run_engine = fake_re
            ir = core.ingest(self.vault, os.path.join(_TEST_HOME, "bad.zip"))
            self.assertEqual(ir.status, "added")
            self.assertIn("pi_flatten.py", calls)
        finally:
            m_ingest.ingest_one = orig_one
            L.run_engine = orig_re
            L.sha1 = orig_sha1


if __name__ == "__main__":
    unittest.main(verbosity=2)
