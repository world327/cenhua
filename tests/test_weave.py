#!/usr/bin/env python3
"""test_weave.py — M1b 编织层离线单测（summaries/refine/relations/related）。

纯离线：规则先行层零 LLM 直接断言；需要网关的环节按"失败隔离/降级"
设计断言（同 test_web/test_mail 的纪律）。
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_TEST_HOME = tempfile.mkdtemp(prefix="cenhua-weave-")
os.environ["CENHUA_HOME"] = _TEST_HOME
os.environ["CENHUA_CONFIG_DIR"] = os.path.join(_TEST_HOME, "config-dir")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import m_lib as L  # noqa: E402
from cenhua_service import summaries as S  # noqa: E402

DOC = """=== PAGE 1 ===
2025 年度采购合同评审纪要
为落实集团降本要求，采购部与供应商华兴科技于 2025年3月15日 完成合同评审。
合同金额为 128.5万元，付款条件为验收后 30 日内电汇。法务提出知识产权条款
需要补充，编号 HT-2025-0331，联系人张伟（zhangwei@huaxing.com.cn）。
=== PAGE 2 ===
预算与风险
本年度预算 420000 元，超预算需 CFO 审批。身份证号 110101199003077758 的
经办人已离职，交接给新员工。Budget review 由 Finance Dept 复核。
第2页
发票税率调整为 6%，其余条款维持不变，双方同意在 2025/06/01 前完成签署。
"""


class SummariesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        r = subprocess.run([os.path.join(ROOT, "bin", "cenhua"), "init",
                            "wv", "--yes"], capture_output=True, text=True,
                           env=dict(os.environ, CENHUA_HOME=_TEST_HOME),
                           timeout=120)
        assert r.returncode == 0, r.stderr
        cls.vault = L.Vault("wv")

    # ------------------------------------------------------------ 纯函数 ----
    def test_01_plain_text_strips_page_marks(self):
        t = S.plain_text(DOC)
        self.assertNotIn("=== PAGE 1 ===", t)
        self.assertNotIn("第2页", t.split("\n")[0])
        self.assertIn("128.5万元", t)

    def test_02_first_paragraph_skips_title(self):
        fp = S.first_paragraph(S.plain_text(DOC))
        # 短标题行（无句读）被跳过，首段从正文开始
        self.assertTrue(fp.startswith("为落实集团降本要求"), fp[:40])
        self.assertIn("华兴科技", fp)
        self.assertNotIn("预算与风险", fp)     # 下一节标题处收束

    def test_03_entities(self):
        ents = S.extract_entities(S.plain_text(DOC))
        self.assertTrue(any("128.5万元" in v for v in ents.get("money", [])),
                        ents.get("money"))
        self.assertTrue(any("420000" in v for v in ents.get("money", [])))
        self.assertTrue(any("2025年3月15日" in v for v in ents.get("date", [])))
        self.assertIn("zhangwei@huaxing.com.cn", ents.get("email", []))
        self.assertIn("110101199003077758", ents.get("id_number", []))
        self.assertTrue(any("Finance" in v for v in
                            ents.get("capitalized", [])) or
                        any("Budget" in v for v in ents.get("capitalized", [])))

    def test_04_keywords(self):
        kws = [k["term"] for k in S.keywords(S.plain_text(DOC))]
        self.assertTrue(kws)
        joined = "".join(kws)
        self.assertIn("合同", joined)          # 高频中文词胜出
        self.assertNotIn("可以", kws)          # 停用词排除
        # tf 降序
        tf = [k["tf"] for k in S.keywords(S.plain_text(DOC))]
        self.assertEqual(tf, sorted(tf, reverse=True))

    def test_05_headings(self):
        hs = S.headings(S.plain_text(DOC))
        self.assertIn("2025 年度采购合同评审纪要", hs)
        self.assertIn("预算与风险", hs)

    def test_06_rule_summarize_shape(self):
        doc = S.rule_summarize("d1", "纪要.pdf", DOC)
        self.assertEqual(doc["status"], "rule-only")
        self.assertEqual(doc["tier"], "internal-artifact")
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(doc["name"], "纪要.pdf")
        self.assertTrue(doc["first_paragraph"])
        self.assertTrue(doc["entities"])
        self.assertTrue(doc["keywords"])
        self.assertGreater(doc["tokens_estimate"], 0)
        self.assertIsNone(doc["refined"])

    # ------------------------------------------------------------ 持久化 ----
    def test_07_refresh_and_load(self):
        S.refresh(self.vault, "docA", "a.pdf", DOC)
        got = S.load_summary(self.vault, "docA")
        self.assertEqual(got["status"], "rule-only")
        self.assertEqual(got["doc_id"], "docA")
        # refined 不被幂等刷新降级
        got["status"] = "refined"
        got["refined"] = {"summary": "ok"}
        S.save_summary(self.vault, got)
        again = S.refresh(self.vault, "docA", "a.pdf", DOC)
        self.assertEqual(again["status"], "refined")

    def test_08_load_missing_returns_none(self):
        self.assertIsNone(S.load_summary(self.vault, "nope"))

    def test_09_ensure_all_offline(self):
        docs = {"docX": {"name": "x.pdf"}, "docY": {"name": "y.pdf"}}
        read = lambda i: None if i == "docY" else DOC  # noqa: E731
        r = S.ensure_all(self.vault, docs, read)
        self.assertEqual(r["rule-only"], 1)
        self.assertEqual(r["skipped"], 1)
        self.assertIsNotNone(S.load_summary(self.vault, "docX"))
        self.assertIsNone(S.load_summary(self.vault, "docY"))


class _FakeVault:
    """refine 单测用最小 vault（只用到 meta/textdir/logs）。"""

    def __init__(self, home):
        self.meta = os.path.join(home, "meta")
        self.textdir = os.path.join(home, "text")
        self.logs = os.path.join(home, "logs")
        os.makedirs(self.meta, exist_ok=True)
        os.makedirs(self.textdir, exist_ok=True)
        os.makedirs(self.logs, exist_ok=True)

    def log(self, *a, **k):
        pass


class RefineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="cenhua-refine-")
        cls.vault = _FakeVault(cls.home)
        with open(os.path.join(cls.vault.textdir, "d1.txt"), "w",
                  encoding="utf-8") as f:
            f.write(DOC)
        with open(os.path.join(cls.vault.textdir, "d2.txt"), "w",
                  encoding="utf-8") as f:
            f.write(DOC)
        S.refresh(cls.vault, "d1", "d1.pdf", DOC)
        S.refresh(cls.vault, "d2", "d2.pdf", DOC)

    def setUp(self):
        from cenhua_service import refine as R
        self.R = R
        q = R.queue_path(self.vault)
        if os.path.exists(q):
            os.remove(q)
        os.environ.pop(R.BUDGET_ENV, None)
        # 恢复 rule-only（上个测试可能改 refined）
        for d in ("d1", "d2"):
            s = S.load_summary(self.vault, d)
            s["status"] = S.STATUS_RULE_ONLY
            S.save_summary(self.vault, s)

    # ------------------------------------------------------------ 队列 ----
    def test_10_enqueue_idempotent(self):
        self.assertTrue(self.R.enqueue(self.vault, "d1", reason="ask"))
        self.assertFalse(self.R.enqueue(self.vault, "d1", reason="ask"))   # 幂等
        self.assertTrue(self.R.enqueue(self.vault, "d2"))
        q = self.R.pending(self.vault)
        self.assertEqual({i["doc_id"] for i in q}, {"d1", "d2"})

    def test_11_refined_leaves_queue(self):
        self.R.enqueue(self.vault, "d1")
        s = S.load_summary(self.vault, "d1")
        s["status"] = S.STATUS_REFINED
        S.save_summary(self.vault, s)
        self.assertEqual(self.R.pending(self.vault), [])   # 已精化=已消费

    # ------------------------------------------------------------ 三闸 ----
    def test_12_budget_defaults_to_zero_refuse(self):
        est = self.R.estimate(self.vault, ["d1", "d2"])
        self.assertGreater(est["est_cost"], 0)
        self.assertGreater(est["tokens_in"], 0)
        ok, msg = self.R.budget_check(est)
        self.assertFalse(ok)                        # 默认 0 = fail-closed
        self.assertIn("CENHUA_REFINE_BUDGET_CNY", msg)
        ok2, _ = self.R.budget_check(est, force=True)
        self.assertTrue(ok2)                        # ③ --force 放行

    def test_13_budget_env_limit(self):
        os.environ[self.R.BUDGET_ENV] = "999999"
        est = self.R.estimate(self.vault, ["d1"])
        ok, _ = self.R.budget_check(est)
        self.assertTrue(ok)                         # 预算内直接过
        os.environ[self.R.BUDGET_ENV] = "abc"       # 非法值 = 0（fail-closed）
        self.assertEqual(self.R.budget_limit(), 0.0)

    def test_14_dry_run_never_costs(self):
        self.R.enqueue(self.vault, "d1")
        rc, lines = self.R.refine_flow(self.vault, do_all=True, dry=True)
        self.assertEqual(rc, 0)                     # dry-run 不受预算闸阻断
        text = "\n".join(lines)
        self.assertIn("dry run", text)
        self.assertIn("estimate", text)

    # ------------------------------------------------------------ ROI 账 ----
    def test_19_roi_lines_visible(self):
        """M3a 任务 13：hint 二段验证成本计入 refine ROI 账（可见）。"""
        from cenhua_service import cost as C
        C.ledger_append(self.vault, {
            "cmd": "refine", "doc": "d1.pdf", "calls": 1,
            "tokens_in": 500, "tokens_out": 80,
            "est_cost": 0.02, "currency": "CNY", "priced": True})
        C.ledger_append(self.vault, {
            "cmd": "query", "doc": "违约金怎么算", "calls": 2,
            "tokens_in": 3000, "tokens_out": 600,
            "est_cost": 0.05, "currency": "CNY", "priced": True,
            "hint_docs": 2, "hint_dropped": 1})
        lines = self.R.roi_lines(self.vault)
        text = "\n".join(lines)
        self.assertIn("[ROI]", text)
        self.assertIn("refine 生产", text)
        self.assertIn("query 验证", text)
        self.assertIn("1 rounds", text)
        self.assertIn("2 doc-round(s)", text)
        self.assertIn("1 祈使句已剔除", text)

    def test_20_status_lines_include_roi(self):
        """无参 `cenhua refine` 状态视图带 ROI 账（任务 13 验收：可见）。"""
        text = "\n".join(self.R.status_lines(self.vault))
        self.assertIn("[ROI]", text)
        self.assertIn("usage", text)

    # ------------------------------------------------------------ drain ----
    def test_15_drain_llm_stubbed(self):
        import unittest.mock as mock
        self.R.enqueue(self.vault, "d1")
        good = '{"summary": "合同评审通过，金额128.5万元。", "entities": ["华兴科技"]}'
        with mock.patch.object(self.R, "_call_llm",
                               return_value=(good, 500, 80)):
            rc, lines = self.R.refine_flow(self.vault, do_drain=True, force=True)
        self.assertEqual(rc, 0)
        s = S.load_summary(self.vault, "d1")
        self.assertEqual(s["status"], "refined")
        self.assertIn("128.5万元", s["refined"]["summary"])
        self.assertEqual(self.R.pending(self.vault), [])    # 出队
        # ledger 记账（T5）
        led = os.path.join(self.vault.meta, "cost-ledger.jsonl")
        rows = [json.loads(l) for l in open(led, encoding="utf-8")]
        self.assertTrue(any(r["cmd"] == "refine" and r["calls"] == 1
                            for r in rows))

    def test_16_drain_fallback_on_bad_json(self):
        import unittest.mock as mock
        self.R.enqueue(self.vault, "d1")
        with mock.patch.object(self.R, "_call_llm",
                               return_value=("对不起我无法输出JSON", 500, 20)):
            rc, _ = self.R.refine_flow(self.vault, do_drain=True, force=True)
        self.assertEqual(rc, 0)
        s = S.load_summary(self.vault, "d1")
        self.assertEqual(s["status"], "refined")            # fallback 也算消费
        self.assertIn("为落实集团降本要求", s["refined"]["summary"])  # 规则首段兜底

    def test_17_drain_failure_stays_queued(self):
        import unittest.mock as mock
        self.R.enqueue(self.vault, "d1")
        with mock.patch.object(self.R, "_call_llm",
                               side_effect=RuntimeError("no gateway")):
            rc, lines = self.R.refine_flow(self.vault, do_drain=True, force=True)
        self.assertEqual(rc, 1)
        s = S.load_summary(self.vault, "d1")
        self.assertEqual(s["status"], S.STATUS_RULE_ONLY)   # 不降级不损坏
        self.assertEqual([i["doc_id"] for i in self.R.pending(self.vault)],
                         ["d1"])                            # 留在队列可重试

    def test_18_drain_refused_without_budget(self):
        self.R.enqueue(self.vault, "d1")
        rc, lines = self.R.refine_flow(self.vault, do_drain=True)
        self.assertEqual(rc, 4)                             # 预算闸拒启
        self.assertIn("REFUSED", lines[0])


class _RelVault:
    """relations 单测用最小 vault（meta/store/textdir）。"""

    def __init__(self, home):
        self.meta = os.path.join(home, "meta")
        self.store = os.path.join(home, "store")
        self.textdir = os.path.join(home, "text")
        for d in (self.meta, self.store, self.textdir):
            os.makedirs(d, exist_ok=True)

    def put(self, doc_id, name, text):
        with open(os.path.join(self.textdir, doc_id + ".txt"), "w",
                  encoding="utf-8") as f:
            f.write(text)
        led_path = os.path.join(self.store, "ingest_manifest.json")
        led = json.load(open(led_path)) if os.path.exists(led_path) else {}
        led[doc_id] = {"name": name}
        with open(led_path, "w", encoding="utf-8") as f:
            json.dump(led, f)
        S.refresh(self, doc_id, name, text)


class RelationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cenhua_service import relations as REL
        cls.REL = REL
        cls.home = tempfile.mkdtemp(prefix="cenhua-rel-")
        v = cls.vault = _RelVault(cls.home)
        # 合成语料：doc1/doc2 共享 AlphaCorp+BetaLabs+128万元（日期差 1 天）
        v.put("doc1", "合同A.pdf",
              "=== PAGE 1 ===\nAlphaCorp 与 BetaLabs 签订合同，金额 128万元。\n"
              "=== PAGE 2 ===\nCommonEntity 例行条款，日期 2026-01-05，履行中。\n")
        v.put("doc2", "付款B.pdf",
              "=== PAGE 1 ===\nAlphaCorp 向 BetaLabs 付款 128万元，"
              "日期 2026-01-06，CommonEntity 条款不变。\n")
        v.put("doc3", "立项C.pdf",
              "=== PAGE 1 ===\nGammaCo 独立立项 77万元，CommonEntity 适用，"
              "日期 2026-02-01。\n")
        v.put("doc4", "纪要D.pdf",
              "=== PAGE 1 ===\nGammaCo 第二次会议复核 77万元预算，"
              "CommonEntity 适用，日期 2026-03-01。\n")

    def _edges(self):
        return self.REL.load_relations(self.vault)

    # ------------------------------------------------------------ 纯函数 ----
    def test_19_npmi_values(self):
        self.assertAlmostEqual(self.REL.npmi(4, 2, 2, 2), 0.5)     # 完全相关
        self.assertLess(self.REL.npmi(4, 3, 3, 1), 0)              # 低于随机
        self.assertEqual(self.REL.npmi(1, 1, 1, 1), 0.0)           # N<=1 无定义
        self.assertEqual(self.REL.npmi(10, 2, 2, 0), 0.0)          # 不共现

    def test_20_profile_tiers(self):
        os.environ.pop("CENHUA_SMALL_CORPUS_N", None)
        p = self.REL.profile(4)
        self.assertEqual(p["tier"], "small")            # N=4 < 200
        self.assertEqual((p["floor"], p["hub_df_ratio"], p["laplace"]),
                         (1, 0.50, True))
        os.environ["CENHUA_SMALL_CORPUS_N"] = "3"
        p2 = self.REL.profile(4)
        self.assertEqual(p2["tier"], "standard")        # N>=3 -> 标准档
        self.assertEqual((p2["floor"], p2["hub_df_ratio"], p2["laplace"]),
                         (2, 0.30, False))
        os.environ.pop("CENHUA_SMALL_CORPUS_N")

    # ------------------------------------------------------------ 建边 ----
    def test_21_build_edges_with_evidence(self):
        r = self.REL.build(self.vault)
        self.assertEqual(r["tier"], "small")
        self.assertEqual(r["docs"], 4)
        pairs = {(e["from"], e["to"]) for e in self._edges()}
        self.assertIn(("doc1", "doc2"), pairs)          # 强共现
        self.assertIn(("doc3", "doc4"), pairs)          # GammaCo 共现
        for e in self._edges():
            self.assertLessEqual(e["weight"], 0.6)      # 自动边上限
            self.assertEqual(e["tier"], "internal-artifact")
            self.assertIn("nPMI=", e["evidence"])       # 证据带 nPMI
            self.assertIn("P", e["evidence"])           # 证据带页码

    def test_22_hub_entity_no_edge(self):
        self.REL.build(self.vault)
        # CommonEntity 出现在全部 4 篇（df=4 > 4*0.5）判枢纽
        ent_docs, _, _, n = self.REL.entity_index(self.vault)
        df = {e: len(d) for e, d in ent_docs.items()}
        hubs = self.REL.hub_entities(df, n, 0.50)
        self.assertIn("commonentity", hubs)
        for e in self._edges():
            self.assertNotIn("commonentity", e["evidence"])   # 不产生共现边

    def test_23_floor_standard_vs_small(self):
        # doc1/doc3 只共现 1 篇（commonentity 是枢纽除外）：
        # 小库档 floor=1 允许候选，标准档 floor=2 拦住
        os.environ["CENHUA_SMALL_CORPUS_N"] = "3"      # 标准档
        self.REL.build(self.vault)
        std = {(e["from"], e["to"]) for e in self._edges()}
        os.environ.pop("CENHUA_SMALL_CORPUS_N")        # 小库档
        self.REL.build(self.vault)
        small = {(e["from"], e["to"]) for e in self._edges()}
        self.assertTrue(small - std or len(small) >= len(std))   # 降档边只多不少

    def test_24_time_series_type(self):
        self.REL.build(self.vault)
        e = [x for x in self._edges()
             if {x["from"], x["to"]} == {"doc1", "doc2"}]
        self.assertTrue(e)
        # 双方日期差 1 天（2026-01-05 / 06）-> time_series
        self.assertEqual(e[0]["type"], "time_series")

    def test_25_manual_link_and_ban(self):
        self.REL.build(self.vault)
        self.REL.manual_link(self.vault, "doc1", "doc3", etype="cite")
        man = [e for e in self._edges()
               if e["source"] == "manual" and {e["from"], e["to"]} ==
               {"doc1", "doc3"}]
        self.assertEqual(len(man), 1)
        self.assertEqual(man[0]["weight"], 0.8)        # 人工权重专属
        # ban 压制：alphacorp/betalabs 是 doc1-doc2 边的证据实体
        self.REL.build(self.vault)                     # 先重建（含 doc1-doc2）
        self.assertTrue(self.REL.add_ban(self.vault, "AlphaCorp", "BetaLabs"))
        self.assertFalse(self.REL.add_ban(self.vault, "AlphaCorp", "BetaLabs"))
        # ban 后重建：doc1-doc2 不再有该对证据的边
        self.REL.build(self.vault)
        for e in self._edges():
            if e["source"] == "auto":
                ev = e["evidence"]
                self.assertFalse("alphacorp" in ev and "betalabs" in ev, ev)
        # 人工边在重建中保留
        man2 = [e for e in self._edges() if e["source"] == "manual"]
        self.assertEqual(len(man2), 1)

    def test_26_top8_truncation(self):
        home2 = tempfile.mkdtemp(prefix="cenhua-rel2-")
        v2 = _RelVault(home2)
        names = ["core"] + [f"partner{i}" for i in range(10)]
        for i, nm in enumerate(names):
            # core 含所有 UniXi+UniYi；partner_i 只含第 i 对
            body = " ".join(f"Uni{j}X 与 Uni{j}Y 合作 金额 {j}万元。"
                            for j in range(10)) if i == 0 else \
                   f"Uni{i}X 与 Uni{i}Y 合作 金额 {i}万元。"
            v2.put(f"doc{i}", f"{nm}.pdf", f"=== PAGE 1 ===\n{body}\n")
        self.REL.build(v2)
        out = [e for e in self.REL.load_relations(v2)
               if "doc0" in (e["from"], e["to"])]
        self.assertLessEqual(len(out), 8)              # Top-8 截断
        self.assertGreaterEqual(len(out), 5)           # 但不至于全砍

    def test_27_related_query(self):
        self.REL.build(self.vault)
        rel = self.REL.related(self.vault, "doc1")
        self.assertTrue(rel)
        w = [r["weight"] for r in rel]
        self.assertEqual(w, sorted(w, reverse=True))   # 权重降序
        self.assertEqual(self.REL.related(self.vault, "ghost"), [])

    def test_28_related_hit_enqueues(self):
        # 命中入队闭环：related 输出后，本文档与对端都进精化队列
        from cenhua_service import refine as R
        q = R.queue_path(self.vault)
        if os.path.exists(q):
            os.remove(q)
        self.REL.build(self.vault)
        self.REL.related_lines(self.vault, "doc1", "合同A.pdf")
        queued = {i["doc_id"] for i in R.pending(self.vault)}
        self.assertIn("doc1", queued)
        self.assertTrue(queued & {"doc2", "doc3"})     # 对端也入队


class GraphIsolationTest(unittest.TestCase):
    """M3a 任务 12：图谱隔离——derived-doc / internal-artifact 不建边。

    两层排除：台账显式 tier 字段（回流文章名称"洞察_weekly_…"不命中
    DERIVED_RE，只能靠 tier 挡）+ 名称 DERIVED_RE 兜底（tier 未回填的
    手动衍生文件，如"周报_…"）。
    """

    @classmethod
    def setUpClass(cls):
        from cenhua_service import relations as REL
        cls.REL = REL

    def _vault(self, tier_overrides=None):
        v = _RelVault(tempfile.mkdtemp(prefix="cenhua-iso-"))
        v.put("doc1", "合同A.pdf",
              "=== PAGE 1 ===\nAlphaCorp 与 BetaLabs 签订合同，金额 128万元。\n"
              "日期 2026-01-05。\n")
        v.put("doc2", "付款B.pdf",
              "=== PAGE 1 ===\nAlphaCorp 向 BetaLabs 付款 128万元，"
              "日期 2026-01-06。\n")
        v.put("doc3", "洞察_weekly_V1_2026-10-12.md",
              "=== PAGE 1 ===\nAlphaCorp 与 BetaLabs 签订合同，金额 128万元。\n")
        v.put("doc4", "周报_2026W41.md",
              "=== PAGE 1 ===\nAlphaCorp 向 BetaLabs 付款 128万元。\n")
        for doc_id, t in (tier_overrides or {}).items():
            led_path = os.path.join(v.store, "ingest_manifest.json")
            led = json.load(open(led_path))
            led[doc_id]["tier"] = t
            with open(led_path, "w", encoding="utf-8") as f:
                json.dump(led, f)
        return v

    def test_29_tier_field_excluded(self):
        v = self._vault({"doc3": "derived-doc"})
        ids = [d for d, _ in self.REL.primary_docs(v)]
        self.assertNotIn("doc3", ids)             # 台账 tier 排除
        self.assertNotIn("doc4", ids)             # 周报_ 名称兜底排除
        self.assertEqual(sorted(ids), ["doc1", "doc2"])

    def test_30_name_fallback_without_tier(self):
        v = self._vault()                         # 无 tier 字段
        ids = [d for d, _ in self.REL.primary_docs(v)]
        self.assertIn("doc3", ids)                # 名称不命中 -> 保守视作 primary
        self.assertNotIn("doc4", ids)             # 名称兜底
        r = self.REL.build(v)
        self.assertEqual(r["docs"], 3)
        for e in self.REL.load_relations(v):
            self.assertNotIn("doc4", (e["from"], e["to"]))

    def test_31_build_shrinks_on_tier(self):
        v = self._vault()
        self.assertEqual(self.REL.build(v)["docs"], 3)
        self._vault_patch_tier(v, "doc3", "internal-artifact")
        r = self.REL.build(v)
        self.assertEqual(r["docs"], 2)            # doc3 也被 tier 挡掉
        for e in self.REL.load_relations(v):
            self.assertNotIn("doc3", (e["from"], e["to"]))

    def _vault_patch_tier(self, v, doc_id, t):
        led_path = os.path.join(v.store, "ingest_manifest.json")
        led = json.load(open(led_path))
        led[doc_id]["tier"] = t
        with open(led_path, "w", encoding="utf-8") as f:
            json.dump(led, f)


if __name__ == "__main__":
    unittest.main(verbosity=2)
