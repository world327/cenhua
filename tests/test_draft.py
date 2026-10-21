#!/usr/bin/env python3
"""M4a draft 套件（主题创作闭环，任务 7-10 + 17）。

覆盖：parse_cli 六种形态、召回仅 primary、三闸顺序（dry-run → 网关 →
longjob 预算 → --force/--max-cost 放行）、LLM 主路径引文校验与落盘、
解析失败/调用异常转规则兜底（零 LLM 消费）、版本递增、rid 幂等短路、
辅助能力 --list/--verify/--diff/--restore、回流 tier=derived-doc、
CLI 注册（cenhua draft 端到端 rc）。纯离线零网关（LLM 一律 mock
cenhua_service.refine.call_llm）。

Run:  python3 tests/test_draft.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "bin", "cenhua")

_TEST_HOME = tempfile.mkdtemp(prefix="cenhua-dr-")
os.environ["CENHUA_HOME"] = _TEST_HOME
os.environ["CENHUA_CONFIG_DIR"] = os.path.join(_TEST_HOME, "config-dir")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import m_lib as L  # noqa: E402
from cenhua_service import draft as F  # noqa: E402

DOC = "pi-d1"
SNIP = "违约金为合同金额的 5%"
TEXT = ("=== PAGE 1 ===\n供应链融资的违约金为合同金额的 5%，逾期 30 天触发。\n"
        "=== PAGE 2 ===\n供应链融资的授信额度需每年复核一次。\n")


def _manifest(vault, entries):
    os.makedirs(vault.store, exist_ok=True)
    with open(os.path.join(vault.store, "ingest_manifest.json"),
              "w", encoding="utf-8") as f:
        json.dump(entries, f)


def _good_json(doc=DOC):
    return json.dumps({"sections": [
        {"title": "违约成本", "body": "逾期成本高企 [doc P1]。",
         "citations": [{"doc": doc, "page": "1", "snippet": SNIP}]},
        {"title": "授信管理", "body": "额度需年度复核 [doc P2]。",
         "citations": [{"doc": doc, "page": "2",
                        "snippet": "授信额度需每年复核一次"}]}]},
        ensure_ascii=False)


class ParseCliTest(unittest.TestCase):
    def test_01_new_defaults(self):
        kw = F.parse_cli(["供应链融资"])
        self.assertEqual((kw["mode"], kw["action"], kw["target"]),
                         ("new", "", "供应链融资"))
        self.assertFalse(kw["dry_run"])

    def test_02_extend_and_rewrite_modes(self):
        self.assertEqual(F.parse_cli(["主题", "--extend", "2"])["mode"],
                         "extend")
        kw = F.parse_cli(["主题", "--rewrite", "3"])
        self.assertEqual((kw["mode"], kw["section"]), ("rewrite", "3"))
        self.assertEqual(kw["action"], "")      # 段号不当位置参数

    def test_03_aux_actions(self):
        self.assertEqual(F.parse_cli(["--list"])["action"], "list")
        self.assertEqual(F.parse_cli(["--list", "主题"])["target"], "主题")
        self.assertEqual(F.parse_cli(["--verify"])["action"], "verify")
        kw = F.parse_cli(["--diff", "主题", "1", "2"])
        self.assertEqual((kw["action"], kw["target"], kw["diff"]),
                         ("diff", "主题", ("1", "2")))
        kw = F.parse_cli(["主题", "--restore", "1"])
        self.assertEqual((kw["action"], kw["target"], kw["version"]),
                         ("restore", "主题", "1"))

    def test_04_gates_and_numbers(self):
        kw = F.parse_cli(["主题", "--dry-run", "--force", "--max-cost",
                          "0.5", "--top", "5"])
        self.assertEqual((kw["dry_run"], kw["force"], kw["top"]),
                         (True, True, 5))
        self.assertAlmostEqual(kw["max_cost"], 0.5)
        self.assertEqual(F.parse_cli(["主题", "--top", "x"])["top"],
                         F.MAX_DOCS)          # 坏值降级不抛

    def test_05_needs_channel(self):
        self.assertTrue(F.needs_channel(["主题"]))
        self.assertTrue(F.needs_channel(["主题", "--extend", "1"]))
        for aux in (["--list"], ["--verify"], ["--diff", "t", "1", "2"]):
            self.assertFalse(F.needs_channel(aux))


class Base(unittest.TestCase):
    """共享 vault：1 篇 primary（有文本层）+ 1 篇 derived（不可作证据）。"""

    @classmethod
    def setUpClass(cls):
        r = subprocess.run([CLI, "init", "drv", "--yes"],
                           capture_output=True, text=True,
                           env=dict(os.environ, CENHUA_HOME=_TEST_HOME),
                           timeout=120)
        assert r.returncode == 0, r.stderr
        cls.vault = L.Vault("drv")

    def setUp(self):
        today = time.strftime("%Y-%m-%d %H:%M:%S")
        _manifest(self.vault, {
            DOC: {"name": "供应链融资办法.pdf", "tier": "primary",
                  "ts": today},
            "pi-dv": {"name": "洞察_weekly_V1.md", "tier": "derived-doc",
                      "ts": today, "derived_from": [DOC]}})
        os.makedirs(self.vault.textdir, exist_ok=True)
        for did in (DOC, "pi-dv"):
            with open(os.path.join(self.vault.textdir, did + ".txt"),
                      "w", encoding="utf-8") as f:
                f.write(TEXT)
        for k in ("PI_BASE", "PI_KEY", "CENHUA_LONGJOB_MAX_COST_CNY"):
            os.environ.pop(k, None)
        self.addCleanup(shutil.rmtree, F.drafts_dir(self.vault),
                        ignore_errors=True)
        self.addCleanup(lambda: os.remove(F._rid_path(self.vault))
                        if os.path.isfile(F._rid_path(self.vault)) else None)

    def gateway(self):
        os.environ["PI_BASE"] = "http://127.0.0.1:9/v1"
        os.environ["PI_KEY"] = "k"

    def run_cli(self, args):
        e = dict(os.environ, CENHUA_HOME=_TEST_HOME)
        e.pop("PI_BASE", None)
        e.pop("PI_KEY", None)
        return subprocess.run([CLI, *args], env=e, cwd=ROOT,
                              capture_output=True, text=True, timeout=120)


class RecallTest(Base):
    def test_10_recall_primary_only(self):
        got = F.recall(self.vault, "供应链融资违约金")
        self.assertIn(DOC, got)
        self.assertNotIn("pi-dv", got)        # derived 默认不召回

    def test_11_recall_empty_rc1(self):
        res = F.draft_flow(self.vault, topic="量子计算与冷藏榴莲")
        self.assertEqual(res.rc, 1)
        self.assertTrue(any("召回为空" in l for l in res.lines))

    def test_12_topic_required(self):
        self.assertEqual(F.draft_flow(self.vault).rc, 2)
        self.assertEqual(F.draft_flow(self.vault, mode="teleport").rc, 2)


class GateTest(Base):
    def test_20_dry_run_no_gateway(self):
        res = F.draft_flow(self.vault, topic="供应链融资", dry_run=True)
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.cost["calls"], 1)   # 估价按 1 次调用
        self.assertEqual(res.path, "")
        self.assertTrue(any("dry-run" in l for l in res.lines))

    def test_21_no_gateway_rc3(self):
        res = F.draft_flow(self.vault, topic="供应链融资")
        self.assertEqual(res.rc, 3)
        self.assertTrue(any("PI_BASE/PI_KEY" in l for l in res.lines))

    def test_22_budget_gate_rc4(self):
        self.gateway()
        os.environ["CENHUA_LONGJOB_MAX_COST_CNY"] = "0.000001"
        res = F.draft_flow(self.vault, topic="供应链融资", rid="r-budget")
        self.assertEqual(res.rc, 4)
        self.assertTrue(res.lines[0].startswith("[draft] REFUSED"))

    def test_23_force_overrides_budget(self):
        self.gateway()
        os.environ["CENHUA_LONGJOB_MAX_COST_CNY"] = "0.000001"
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 200, 90)):
            res = F.draft_flow(self.vault, topic="供应链融资", force=True,
                               rid="r-force")
        self.assertEqual(res.rc, 0)
        self.assertTrue(any("overrides" in l for l in res.lines))

    def test_24_max_cost_gate(self):
        self.gateway()
        res = F.draft_flow(self.vault, topic="供应链融资", max_cost=0.000001,
                           rid="r-maxcost")
        self.assertEqual(res.rc, 4)


class GenerateTest(Base):
    def test_30_llm_writes_versioned_draft(self):
        self.gateway()
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 300, 120)):
            res = F.draft_flow(self.vault, topic="供应链融资")
        self.assertEqual((res.rc, res.mode, res.version), (0, "llm", 1))
        self.assertEqual(res.derived_from, [DOC])
        self.assertEqual(sum(1 for c in res.citations if c["ok"]), 2)
        name = "%s_V1_%s.md" % (F.slug("供应链融资"),
                                time.strftime("%Y-%m-%d"))
        self.assertEqual(os.path.basename(res.path), name)
        art = F._read(res.path)
        self.assertIn("tier=derived-doc", art)
        self.assertIn("<!-- draft: topic=供应链融资", art)
        self.assertIn("derived_from: %s" % DOC, art)
        self.assertIn(SNIP, art)
        self.assertIn("· ✓", art)

    def test_31_version_increments(self):
        self.gateway()
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 300, 120)):
            first = F.draft_flow(self.vault, topic="供应链融资", rid="v1")
            second = F.draft_flow(self.vault, topic="供应链融资", rid="v2")
        self.assertEqual((first.version, second.version), (1, 2))

    def test_32_parse_fail_rules_fallback(self):
        self.gateway()
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm", return_value=("不像 JSON", 9, 9)):
            res = F.draft_flow(self.vault, topic="供应链融资", rid="r-parse")
        self.assertEqual((res.rc, res.mode), (0, "rules"))
        self.assertEqual(res.cost["calls"], 0)     # 兜底零 LLM 消费
        self.assertTrue(any("无法解析" in l for l in res.lines))
        art = F._read(res.path)
        self.assertIn("需 LLM", art)               # 明示，不伪造分析
        self.assertNotIn(SNIP + "  ·", art)

    def test_33_llm_exception_rules_fallback(self):
        self.gateway()
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm", side_effect=RuntimeError("x")):
            res = F.draft_flow(self.vault, topic="供应链融资", rid="r-exc")
        self.assertEqual((res.rc, res.mode), (0, "rules"))
        self.assertTrue(any("调用失败" in l for l in res.lines))

    def test_34_hallucinated_citation_marked_fail(self):
        self.gateway()
        from unittest import mock
        from cenhua_service import refine as R
        bad = json.dumps({"sections": [{"title": "编造", "body": "无据结论",
                                        "citations": [{"doc": DOC, "page": "1",
                                                       "snippet": "年化 0.5%"}]}]},
                         ensure_ascii=False)
        with mock.patch.object(R, "call_llm", return_value=(bad, 100, 40)):
            res = F.draft_flow(self.vault, topic="供应链融资", rid="r-bad")
        self.assertEqual(res.rc, 0)
        self.assertFalse(res.citations[0]["ok"])
        self.assertTrue(any("0/1 校验通过" in l for l in res.lines))

    def test_35_rid_idempotent_short_circuit(self):
        self.gateway()
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 300, 120)) as llm:
            first = F.draft_flow(self.vault, topic="供应链融资")
            second = F.draft_flow(self.vault, topic="供应链融资")
        self.assertEqual(llm.call_count, 1)        # 同 rid 不再花钱
        self.assertEqual((first.rc, second.rc, second.mode), (0, 0, "cached"))
        self.assertEqual(second.path, first.path)
        self.assertTrue(any("idempotent" in l for l in second.lines))

    def test_37_backflow_derived_doc(self):
        """draft_flow 自动回流（M3a 任务 10 同模式）：rc 不变 +
        台账 tier=derived-doc + derived_from。引擎 mock L.run_engine。"""
        self.gateway()
        from unittest import mock
        from cenhua_service import refine as R

        def _fake_added(name):
            def _run(*a, **k):
                led_path = os.path.join(self.vault.store,
                                        "ingest_manifest.json")
                led = L.read_json(led_path, {}) or {}
                led["pi-draft1"] = {"name": name, "sha1": "x",
                                    "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
                with open(led_path, "w", encoding="utf-8") as f:
                    json.dump(led, f, ensure_ascii=False)
                return (0, "+ %s -> pi-draft1 (0s, gw=gw1)\n" % name)
            return _run

        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 300, 120)), \
             mock.patch.object(L, "run_engine",
                               _fake_added("backflow_V1.md")):
            res = F.draft_flow(self.vault, topic="供应链融资回流",
                               rid="r-back")
        self.assertEqual(res.rc, 0)
        self.assertTrue(any("backflow" in l and "pi-draft1" in l
                            for l in res.lines))
        led = L.read_json(os.path.join(self.vault.store,
                                       "ingest_manifest.json"), {})
        rec = led.get("pi-draft1", {})
        self.assertEqual(rec.get("tier"), "derived-doc")
        self.assertEqual(rec.get("derived_from"), [DOC])
        self.addCleanup(lambda: led.pop("pi-draft1", None))

    def test_38_backflow_failure_keeps_rc(self):
        """回流失败（引擎报错）绝不允许拖垮 draft：rc 仍 0 + skipped 行。"""
        self.gateway()
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 300, 120)), \
             mock.patch.object(L, "run_engine",
                               return_value=(1, "engine down\n")):
            res = F.draft_flow(self.vault, topic="供应链融资回流败",
                               rid="r-backfail")
        self.assertEqual(res.rc, 0)
        self.assertTrue(any("backflow" in l and "skipped" in l
                            for l in res.lines))
        self.assertTrue(os.path.isfile(res.path))

    def test_36_ledger_and_cost(self):
        self.gateway()
        from unittest import mock
        from cenhua_service import cost as CC
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 300, 120)):
            F.draft_flow(self.vault, topic="供应链融资", rid="r-ledger")
        path = CC.ledger_path(self.vault)
        rows = [json.loads(x) for x in open(path, encoding="utf-8")
                if x.strip()] if os.path.isfile(path) else []
        hit = [r for r in rows if r.get("cmd") == "draft"
               and r.get("rid") == "r-ledger"]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["mode"], "new")
        self.assertTrue(hit[0]["tokens_in"])


class AuxTest(Base):
    def _make(self, topic="供应链融资"):
        self.gateway()
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 300, 120)):
            return F.draft_flow(self.vault, topic=topic, rid="aux-" + topic)

    def test_40_list(self):
        self.assertEqual(F.list_lines(self.vault)["rc"], 1)
        self._make()
        res = F.list_lines(self.vault)
        self.assertEqual(res["rc"], 0)
        self.assertTrue(any("V1" in l for l in res["lines"]))
        self.assertEqual(F.list_lines(self.vault, "不存在的主题")["rc"], 1)

    def test_41_verify_pass(self):
        r = self._make()
        res = F.verify_draft(self.vault, os.path.basename(r.path))
        self.assertEqual(res["rc"], 0)
        self.assertTrue(any("2 条引文，2 通过" in l for l in res["lines"]))

    def test_42_verify_fails_on_tampered_snippet(self):
        r = self._make()
        body = F._read(r.path).replace(SNIP, "违约金为合同金额的 50%")
        with open(r.path, "w", encoding="utf-8") as f:
            f.write(body)
        res = F.verify_draft(self.vault, "供应链融资")
        self.assertEqual(res["rc"], 1)
        self.assertTrue(any("✗" in l for l in res["lines"]))

    def test_42b_verify_resolves_doc_prefix(self):
        """E2E 防回潮：生成 ✓ 的引文重验必 ✓。

        引文行渲染只写 doc 前 8 位，verify_draft 必须与生成路径同口径
        先 resolve_ids 补全，否则前缀查不到文档 -> 全量假阴性。
        """
        r = self._make(topic="供应链融资前缀")
        self.assertIn("> 引文 [pi-d1 P", F._read(r.path))   # 渲染为前缀
        res = F.verify_draft(self.vault, "供应链融资前缀")
        self.assertEqual(res["rc"], 0)
        self.assertTrue(any("2/2 通过" in l for l in res["lines"]))

    def test_42c_rules_fallback_multiline_roundtrip(self):
        """E2E 防回潮：证据段含换行时引文行仍单行且重验通过。

        规则兜底 snippet 必须压掉内部换行（引文行协议前提是单行），
        verify 归一化去空白，往返一致。
        """
        LONG = "pi-multiline01"
        multiline = ("=== PAGE 1 ===\n上海某某贸易有\n"
                     "限公司与深圳某某科技有限公司签署融资协议。\n")
        self.addCleanup(lambda: os.remove(
            os.path.join(self.vault.textdir, LONG + ".txt"))
            if os.path.isdir(self.vault.textdir) else None)
        _manifest(self.vault, {
            LONG: {"name": "多方协议.pdf", "tier": "primary",
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")}})
        with open(os.path.join(self.vault.textdir, LONG + ".txt"),
                  "w", encoding="utf-8") as f:
            f.write(multiline)
        self.gateway()
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm", return_value=("不像 JSON", 9, 9)):
            res = F.draft_flow(self.vault, topic="某某贸易融资协议",
                               rid="r-multi")
        self.assertEqual((res.rc, res.mode), (0, "rules"))
        art = F._read(res.path)
        cites = [m.group(0) for m in F._CITE_RE.finditer(art)]
        self.assertTrue(cites)                       # 有真实引文行
        self.assertTrue(all("\n" not in c for c in cites))
        v = F.verify_draft(self.vault, "某某贸易融资协议")
        self.assertEqual(v["rc"], 0)
        self.assertTrue(any("通过" in l for l in v["lines"]))
        self.assertFalse(any("✗" in l for l in v["lines"]))

    def test_43_verify_unknown_target_rc2(self):
        self._make()
        self.assertEqual(F.verify_draft(self.vault, "根本没这篇")["rc"], 2)

    def test_44_extend_new_version(self):
        base = self._make()
        from unittest import mock
        from cenhua_service import refine as R
        good = _good_json()
        with mock.patch.object(R, "call_llm",
                               return_value=(good, 200, 80)) as llm:
            res = F.draft_flow(self.vault, topic="供应链融资", mode="extend",
                               section="1", rid="r-ext")
        self.assertEqual((res.rc, res.version), (0, 2))
        self.assertEqual(llm.call_count, 1)
        art = F._read(res.path)
        self.assertIn("违约成本", art)              # 段结构保留
        self.assertIn("2.", art)
        self.assertTrue(F._read(base.path))

    def test_45_rewrite_bad_section_rc2(self):
        self._make()
        res = F.draft_flow(self.vault, topic="供应链融资", mode="rewrite",
                           section="9", rid="r-rw")
        self.assertEqual(res.rc, 2)
        self.assertTrue(any("超出范围" in l for l in res.lines))
        self.assertEqual(F.draft_flow(self.vault, topic="供应链融资",
                                      mode="extend", section="",
                                      rid="r-rw2").rc, 2)

    def test_46_rewrite_no_draft_rc1(self):
        res = F.draft_flow(self.vault, topic="空白主题", mode="extend",
                           section="1", rid="r-none")
        self.assertEqual(res.rc, 1)

    def test_47_diff(self):
        a = self._make()
        self.gateway()
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 200, 80)):
            b = F.draft_flow(self.vault, topic="供应链融资", mode="extend",
                             section="1", rid="r-diff")
        res = F.diff_draft(self.vault, "供应链融资", a.version, b.version)
        self.assertEqual(res["rc"], 0)
        self.assertTrue(any(l.startswith("+") or l.startswith("@@")
                            for l in res["lines"]))
        self.assertEqual(F.diff_draft(self.vault, "供应链融资",
                                      a.version, 99)["rc"], 1)

    def test_48_restore_creates_new_version(self):
        a = self._make()
        res = F.restore_draft(self.vault, "供应链融资", a.version)
        self.assertEqual(res["rc"], 0)
        rows = F.list_lines(self.vault)["lines"]
        self.assertTrue(any("V2" in l for l in rows))
        self.assertEqual(F.restore_draft(self.vault, "供应链融资", 7)["rc"], 1)
        self.assertEqual(F.restore_draft(self.vault, "", "")["rc"], 2)

    def test_49_aux_flow_dispatch(self):
        self._make()
        out = F.flow(self.vault, ["--list"])
        self.assertEqual(out["rc"], 0)
        self.assertEqual(F.aux_flow(self.vault, {"action": ""})["rc"], 2)


class AssembleTest(Base):
    """assemble 渲染口径（E2E 实测两坑回归）。"""

    def _art(self, sections, cites):
        return "\n".join(F.assemble(self.vault, "口径", 1, sections, cites,
                                    "llm", [DOC], "r-asm"))

    def test_70_title_with_number_no_double_prefix(self):
        # LLM 把骨架 "1.《X》" 编号带回时不再叠加 "## %d. " 前缀
        art = self._art([{"title": "1.《本周进展》", "body": "b1",
                          "citations": []},
                         {"title": "无编号标题", "body": "b2",
                          "citations": []}], [])
        self.assertIn("## 1.《本周进展》", art)
        self.assertNotIn("## 1. 1.", art)
        self.assertIn("## 2. 无编号标题", art)

    def test_71_ok_map_prefix_and_full_id_match(self):
        # cites 经 resolve_ids 补全为完整 id，小节引文仍是 8 位前缀：
        # 两边必须都命中 ✓（E2E 实测曾全标 ✗ 而汇总 4/4 通过）
        long_id = "pi-d1aaaabbbbcccc"
        sects = [{"title": "T", "body": "b", "citations": [
            {"doc": long_id[:8], "page": "1", "snippet": SNIP},
            {"doc": long_id, "page": "1", "snippet": "改写的幻觉文本"}]}]
        cites = [{"doc": long_id, "page": "1", "snippet": SNIP,
                  "ok": True, "via": "direct", "note": ""},
                 {"doc": long_id, "page": "1", "snippet": "改写的幻觉文本",
                  "ok": False, "via": "none", "note": "x"}]
        art = self._art(sects, cites)
        self.assertIn(SNIP + "  · ✓", art)
        self.assertIn("改写的幻觉文本  · ✗", art)


class CliTest(Base):
    def test_50_dispatch_and_usage(self):
        r = self.run_cli(["draft"])
        self.assertEqual(r.returncode, 2)
        r2 = self.run_cli(["draft", "--list"])
        self.assertIn(r2.returncode, (0, 1))
        r3 = self.run_cli(["draft", "主题", "--extend", "abc"])
        self.assertEqual(r3.returncode, 2)      # 段号非数字 -> 参数错

    def test_51_usage_mentions_draft(self):
        r = subprocess.run([CLI, "--help"], capture_output=True, text=True,
                           env=dict(os.environ, CENHUA_HOME=_TEST_HOME))
        self.assertIn("TOPIC DRAFTING", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
