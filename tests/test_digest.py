#!/usr/bin/env python3
"""test_digest.py — M3a 任务 6：digest 命令骨架 + watch 提示（F10）。

覆盖：parse_window 三种触发与互斥/格式错、digest_flow rc 语义
（2 参数错 / 0 空窗 / 0 dry-run / 3 网关未配置）、docs_in_window 时间圈选、
docs_since_last_digest 计数、hint_threshold 配置优先级、watch 提示文案
（进程内测 watch 挂载的 _digest_hint：文案精确、阈值未达不打印、绝不自动执行）、
compose 四节生成（mock refine.call_llm：LLM 成功带引文校验、解析失败/
调用异常转规则兜底、版本递增落盘 works/digests/）、longjob 三闸顺序与豁免中途执法（任务 8）：dry-run 免闸/超预算拒启 rc=4/--force 与 --max-cost 放行、不被 CENHUA_MAX_COST_CNY 腰斩。纯离线零网关。
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_TEST_HOME = tempfile.mkdtemp(prefix="cenhua-dg-")
os.environ["CENHUA_HOME"] = _TEST_HOME
os.environ["CENHUA_CONFIG_DIR"] = os.path.join(_TEST_HOME, "config-dir")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import m_lib as L  # noqa: E402
from cenhua_service import digest as G  # noqa: E402


def _manifest(vault, entries):
    os.makedirs(vault.store, exist_ok=True)
    with open(os.path.join(vault.store, "ingest_manifest.json"),
              "w", encoding="utf-8") as f:
        json.dump(entries, f)


class ParseWindowTest(unittest.TestCase):
    def test_01_three_windows(self):
        for flag_name, days in (("weekly", 7), ("monthly", 30),
                                ("quarterly", 91)):
            kw = {flag_name: True}
            start, label = G.parse_window(**kw)
            self.assertEqual(label, flag_name)
            expect = time.strftime(
                "%Y-%m-%d", time.localtime(time.time() - days * 86400))
            self.assertEqual(start, expect)

    def test_02_since_ok_and_bad_format(self):
        start, label = G.parse_window(since="2026-09-01")
        self.assertEqual((start, label), ("2026-09-01", "since 2026-09-01"))
        start, msg = G.parse_window(since="0901")
        self.assertIsNone(start)
        self.assertIn("YYYY-MM-DD", msg)

    def test_03_mutex_and_missing(self):
        start, msg = G.parse_window(weekly=True, since="2026-09-01")
        self.assertIsNone(start)
        self.assertIn("互斥", msg)
        start, msg = G.parse_window()
        self.assertIsNone(start)
        self.assertIn("usage: cenhua digest", msg)


class FlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess as SP
        r = SP.run([os.path.join(ROOT, "bin", "cenhua"), "init", "dgv",
                    "--yes"], capture_output=True, text=True,
                   env=dict(os.environ, CENHUA_HOME=_TEST_HOME), timeout=120)
        assert r.returncode == 0, r.stderr
        cls.vault = L.Vault("dgv")

    def setUp(self):
        today = time.strftime("%Y-%m-%d %H:%M:%S")
        _manifest(self.vault, {
            "pi-new": {"name": "新文档.pdf", "tier": "primary", "ts": today},
            "pi-old": {"name": "旧文档.pdf", "tier": "primary",
                       "ts": "2020-01-01 10:00:00"}})
        os.makedirs(self.vault.textdir, exist_ok=True)
        with open(os.path.join(self.vault.textdir, "pi-new.txt"),
                  "w", encoding="utf-8") as f:
            f.write("=== PAGE 1 ===\n窗口内新合同，罚金条款 7.2。\n")
        for k in ("PI_BASE", "PI_KEY"):
            os.environ.pop(k, None)

    def test_04_bad_args_rc2(self):
        self.assertEqual(G.digest_flow(self.vault).rc, 2)

    def test_05_window_filters_docs(self):
        picked = G.docs_in_window(self.vault, "2026-01-01")
        self.assertEqual([d for d, _ in picked], ["pi-new"])

    def test_06_empty_window_note(self):
        res = G.digest_flow(self.vault, since="2030-01-01")
        self.assertEqual(res.rc, 0)
        self.assertTrue(any("窗口内无新摄取" in l for l in res.lines))

    def test_07_dry_run_estimate(self):
        res = G.digest_flow(self.vault, weekly=True, dry_run=True)
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.cost["calls"], 1)
        self.assertTrue(any(l.startswith("[digest] documents  : 1")
                            for l in res.lines))
        self.assertIn("(dry run \u2014 nothing was sent)", res.lines)

    def test_08_no_gateway_rc3(self):
        res = G.digest_flow(self.vault, weekly=True)
        self.assertEqual(res.rc, 3)
        self.assertTrue(any("PI_BASE" in l for l in res.lines))

    def test_09_since_last_digest_and_threshold(self):
        self.assertEqual(G.docs_since_last_digest(self.vault), 2)  # 无洞察=全库
        ddir = os.path.join(self.vault.works, "digests")
        os.makedirs(ddir, exist_ok=True)
        p = os.path.join(ddir, "d.md")
        open(p, "w").write("# x")
        old = time.time() - 86400 * 40
        os.utime(p, (old, old))
        # 洞察在旧文档之后、新文档之前 -> 只有新文档计入
        self.assertEqual(G.docs_since_last_digest(self.vault), 1)
        self.assertEqual(G.hint_threshold(self.vault), 20)
        os.environ["CENHUA_DIGEST_HINT_DOCS"] = "3"
        try:
            self.assertEqual(G.hint_threshold(self.vault), 3)
        finally:
            os.environ.pop("CENHUA_DIGEST_HINT_DOCS", None)


class WatchHintTest(unittest.TestCase):
    """watch 提示钩子：_digest_hint 文案精确 + 阈值未达不打印（F10）。

    端到端 watch 摄取需真 LLM 网关（见 test_cenhua test_20），故此处
    进程内直接调 watch 挂载的 _digest_hint，验证文案与触发条件；
    "无自动触发执行"由代码审查保证——钩子只 say 一行，绝不调 digest_flow。
    """

    @classmethod
    def setUpClass(cls):
        import subprocess as SP
        r = SP.run([os.path.join(ROOT, "bin", "cenhua"), "init", "wv",
                    "--yes"], capture_output=True, text=True,
                   env=dict(os.environ, CENHUA_HOME=_TEST_HOME), timeout=120)
        assert r.returncode == 0, r.stderr
        cls.vault = L.Vault("wv")

    def _capture_hint(self):
        import io
        import contextlib
        import m_ingest
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            m_ingest._digest_hint(self.vault)
        return buf.getvalue()

    def test_10_hint_line_exact(self):
        today = time.strftime("%Y-%m-%d %H:%M:%S")
        _manifest(self.vault, {"pi-h": {"name": "提示测试.pdf",
                                        "tier": "primary", "ts": today}})
        os.environ["CENHUA_DIGEST_HINT_DOCS"] = "1"
        try:
            out = self._capture_hint()
            self.assertIn("提示：自上次洞察以来已摄取 1 篇，"
                          "可运行 cenhua digest --dry-run 估价", out)
            # 只打印一行提示，绝不自动执行 digest
            self.assertNotIn("[digest] window", out)
            self.assertEqual(out.count("\n"), 1)
            os.environ["CENHUA_DIGEST_HINT_DOCS"] = "100"
            self.assertEqual(self._capture_hint(), "")   # 未达阈值闭嘴
        finally:
            os.environ.pop("CENHUA_DIGEST_HINT_DOCS", None)


class ComposeTest(unittest.TestCase):
    """compose 四节引擎（任务 7）：LLM 主路径 + 规则兜底 + 引文校验 + 落盘。

    LLM 一律 mock cenhua_service.refine.call_llm（test_query 模式），零网关。
    """

    @classmethod
    def setUpClass(cls):
        import subprocess as SP
        r = SP.run([os.path.join(ROOT, "bin", "cenhua"), "init", "cv",
                    "--yes"], capture_output=True, text=True,
                   env=dict(os.environ, CENHUA_HOME=_TEST_HOME), timeout=120)
        assert r.returncode == 0, r.stderr
        cls.vault = L.Vault("cv")
        today = time.strftime("%Y-%m-%d %H:%M:%S")
        _manifest(cls.vault, {"pi-c1": {"name": "合同A.pdf",
                                        "tier": "primary", "ts": today}})
        os.makedirs(cls.vault.textdir, exist_ok=True)
        with open(os.path.join(cls.vault.textdir, "pi-c1.txt"),
                  "w", encoding="utf-8") as f:
            f.write("=== PAGE 1 ===\n窗口内新合同，罚金条款 7.2。\n")
        cls.SNIP = "罚金条款 7.2"
        cls.GOOD = json.dumps({
            "graph": {"overview": "本期 1 篇合同类文档",
                      "entity_changes": [{"entity": "7.2", "note": "罚金"}]},
            "findings": {"patterns": [{"text": "合同含罚金条款",
                                       "citations": [{"doc": "pi-c1",
                                                      "page": "1",
                                                      "snippet": cls.SNIP}]}],
                         "trends": [], "contradictions": []},
            "open_questions": []}, ensure_ascii=False)

    def setUp(self):
        for k in ("PI_BASE", "PI_KEY"):
            os.environ.pop(k, None)

    def _article(self, res):
        self.assertTrue(res.path and os.path.isfile(res.path))
        return open(res.path, encoding="utf-8").read()

    def _four_sections(self, art):
        for h in ("# CENHUA 知识洞察", "## 一、", "## 二、", "## 三、",
                  "## 四、"):
            self.assertIn(h, art)

    def test_11_llm_path_citations_verified(self):
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(self.GOOD, 100, 50)):
            res, lines = G.compose(self.vault, ["pi-c1"], label="weekly",
                                   start="2026-10-01")
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.mode, "llm")
        self.assertEqual(res.derived_from, ["pi-c1"])
        self.assertEqual(len(res.citations), 1)
        self.assertTrue(res.citations[0]["ok"])       # snippet 逐字命中
        art = self._article(res)
        self._four_sections(art)
        self.assertIn(self.SNIP, art)                  # 全程带引文（含 snippet）
        self.assertIn("\u2713", art)
        self.assertIn("derived_from: pi-c1", art)
        self.assertIn("1/1 校验通过", "\n".join(lines))

    def test_12_parse_fail_rules_fallback(self):
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm", return_value=("不是JSON", 9, 9)):
            res, lines = G.compose(self.vault, ["pi-c1"], label="weekly")
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.mode, "rules")
        self.assertEqual(res.cost["calls"], 0)         # 兜底零 LLM 消费
        self.assertTrue(any("无法解析" in l for l in lines))
        art = self._article(res)
        self._four_sections(art)
        self.assertIn("需 LLM 网关", art)              # 二/三节明示，零编造
        self.assertNotIn(self.SNIP, art)

    def test_13_llm_exception_rules_fallback(self):
        from unittest import mock
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               side_effect=RuntimeError("boom")):
            res, lines = G.compose(self.vault, ["pi-c1"], label="weekly")
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.mode, "rules")
        self.assertTrue(any("调用失败" in l for l in lines))
        self._four_sections(self._article(res))

    def test_14_version_increments(self):
        ddir = os.path.join(self.vault.works, "digests")
        before = sorted(os.listdir(ddir)) if os.path.isdir(ddir) else []
        res, _ = G.compose(self.vault, ["pi-c1"], label="weekly")
        after = sorted(os.listdir(ddir))
        self.assertEqual(len(after), len(before) + 1)
        self.assertIn("_V", os.path.basename(res.path))
        vs = sorted(int(f.split("_V")[1].split("_")[0]) for f in after
                    if f.startswith("洞察_weekly_"))
        self.assertEqual(vs, list(range(1, len(vs) + 1)))   # V1..VN 连续

    def test_15_flow_wired(self):
        from unittest import mock
        from cenhua_service import refine as R
        os.environ["PI_BASE"] = "http://127.0.0.1:9/v1"
        os.environ["PI_KEY"] = "k"
        try:
            with mock.patch.object(R, "call_llm",
                                   return_value=(self.GOOD, 100, 50)):
                res = G.digest_flow(self.vault, weekly=True)
        finally:
            os.environ.pop("PI_BASE", None)
            os.environ.pop("PI_KEY", None)
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.mode, "llm")
        self.assertTrue(any("[digest] engine" in l for l in res.lines))
        self.assertTrue(any("[digest] article" in l for l in res.lines))
        self.assertTrue(res.path and os.path.isfile(res.path))


class BudgetGateTest(unittest.TestCase):
    """三闸（任务 8）：① dry-run 估价 → ② longjob 预算拒启 → ③ force/--max-cost。

    同时验证豁免中途执法：digest 不查 CENHUA_MAX_COST_CNY，
    超限只认 longjob 限额（防跑到单命令上限被腰斩成断头洞察）。
    LLM 一律 mock，零网关。
    """

    @classmethod
    def setUpClass(cls):
        import subprocess as SP
        r = SP.run([os.path.join(ROOT, "bin", "cenhua"), "init", "bg",
                    "--yes"], capture_output=True, text=True,
                   env=dict(os.environ, CENHUA_HOME=_TEST_HOME), timeout=120)
        assert r.returncode == 0, r.stderr
        cls.vault = L.Vault("bg")
        today = time.strftime("%Y-%m-%d %H:%M:%S")
        _manifest(cls.vault, {"pi-b1": {"name": "预算.pdf",
                                        "tier": "primary", "ts": today}})
        os.makedirs(cls.vault.textdir, exist_ok=True)
        with open(os.path.join(cls.vault.textdir, "pi-b1.txt"),
                  "w", encoding="utf-8") as f:
            f.write("=== PAGE 1 ===\n长任务预算闸测试文本。\n")

    def setUp(self):
        for k in ("PI_BASE", "PI_KEY", "CENHUA_LONGJOB_MAX_COST_CNY",
                  "CENHUA_MAX_COST_CNY"):
            os.environ.pop(k, None)

    def test_16_budget_check_units(self):
        est = {"est_cost": 2.5, "currency": "CNY"}
        ok, msg = G.budget_check(self.vault, est)
        self.assertTrue(ok)                       # 默认限额 5.0
        self.assertIn("within longjob budget", msg)
        os.environ["CENHUA_LONGJOB_MAX_COST_CNY"] = "1.0"
        ok, msg = G.budget_check(self.vault, est)
        self.assertFalse(ok)
        self.assertIn("CENHUA_LONGJOB_MAX_COST_CNY", msg)
        ok, msg = G.budget_check(self.vault, est, force=True)
        self.assertTrue(ok)
        self.assertIn("--force", msg)
        ok, _ = G.budget_check(self.vault, est, max_cost=9.9)
        self.assertTrue(ok)                       # --max-cost 覆盖限额
        # USD 报价按保守汇率折 CNY 再比（闸只收紧不放松）
        ok, _ = G.budget_check(self.vault,
                               {"est_cost": 1.0, "currency": "USD"})
        self.assertFalse(ok)                      # ¥7.4 > ¥1

    def test_17_longjob_limit_precedence(self):
        from cenhua_service import cost as CC
        self.assertEqual(CC.longjob_max_cost_cny(self.vault), 5.0)
        os.environ["CENHUA_LONGJOB_MAX_COST_CNY"] = "3.5"
        self.assertEqual(CC.longjob_max_cost_cny(self.vault), 3.5)
        os.environ["CENHUA_LONGJOB_MAX_COST_CNY"] = "bad"
        self.assertEqual(CC.longjob_max_cost_cny(self.vault), 5.0)

    def test_18_dry_run_exempt_from_gate(self):
        os.environ["CENHUA_LONGJOB_MAX_COST_CNY"] = "0.000001"
        res = G.digest_flow(self.vault, weekly=True, dry_run=True)
        self.assertEqual(res.rc, 0)     # ① dry-run 只估价，不触②③
        self.assertFalse(any("refused" in l for l in res.lines))

    def test_19_over_budget_refuse_rc4(self):
        os.environ["PI_BASE"] = "http://127.0.0.1:9/v1"
        os.environ["PI_KEY"] = "k"
        os.environ["CENHUA_LONGJOB_MAX_COST_CNY"] = "0.000001"
        res = G.digest_flow(self.vault, weekly=True)
        self.assertEqual(res.rc, 4)     # ② 超预算拒启（all-or-nothing）
        self.assertTrue(any("exceeds longjob budget" in l
                            for l in res.lines))

    def test_20_force_and_max_cost_pass(self):
        from unittest import mock
        from cenhua_service import refine as R
        os.environ["PI_BASE"] = "http://127.0.0.1:9/v1"
        os.environ["PI_KEY"] = "k"
        os.environ["CENHUA_LONGJOB_MAX_COST_CNY"] = "0.000001"
        for kw in ({"force": True}, {"max_cost": 99}):
            with mock.patch.object(R, "call_llm",
                                   return_value=("不是JSON", 1, 1)):
                res = G.digest_flow(self.vault, weekly=True, **kw)
            self.assertEqual(res.rc, 0)     # ③ 放行 -> 走到引擎（规则兜底）
            self.assertEqual(res.mode, "rules")
            self.assertFalse(any("refused" in l for l in res.lines))

    def test_21_exempt_from_max_cost_slash(self):
        from unittest import mock
        from cenhua_service import refine as R
        os.environ["PI_BASE"] = "http://127.0.0.1:9/v1"
        os.environ["PI_KEY"] = "k"
        os.environ["CENHUA_MAX_COST_CNY"] = "0.000001"   # 单命令上限压到极低
        with mock.patch.object(R, "call_llm", return_value=("不是JSON", 1, 1)):
            res = G.digest_flow(self.vault, weekly=True)
        self.assertEqual(res.rc, 0)     # 豁免：不被 MAX_COST 腰斩
        self.assertTrue(any(l.startswith("[digest] budget")
                            and "longjob" in l for l in res.lines))

    def test_22_parse_cli(self):
        kw = G.parse_cli(["--weekly", "--dry-run", "--force",
                          "--max-cost", "9.9", "--since", "2026-01-01"])
        self.assertTrue(kw["weekly"] and kw["force"] and kw["dry_run"])
        self.assertEqual(kw["since"], "2026-01-01")
        self.assertEqual(kw["max_cost"], 9.9)
        self.assertIsNone(G.parse_cli(["--weekly"])["max_cost"])


class BackflowTest(unittest.TestCase):
    """M3a 任务 10：回流闭环——works/digests 文章 -> inbox 摄取 ->
    台账 tier=derived-doc + derived_from；best-effort 永不拖垮 digest。

    引擎一律 mock L.run_engine（ADDED_RE 可解析行），零网关零引擎依赖。
    """

    @classmethod
    def setUpClass(cls):
        import subprocess as SP
        from cenhua_service import refine as R
        cls.R = R
        r = SP.run([os.path.join(ROOT, "bin", "cenhua"), "init", "bfv",
                    "--yes"], capture_output=True, text=True,
                   env=dict(os.environ, CENHUA_HOME=_TEST_HOME), timeout=120)
        assert r.returncode == 0, r.stderr
        cls.vault = L.Vault("bfv")
        today = time.strftime("%Y-%m-%d %H:%M:%S")
        _manifest(cls.vault, {"pi-b1": {"name": "合同A.pdf",
                                        "tier": "primary", "ts": today}})
        os.makedirs(cls.vault.textdir, exist_ok=True)
        with open(os.path.join(cls.vault.textdir, "pi-b1.txt"),
                  "w", encoding="utf-8") as f:
            f.write("=== PAGE 1 ===\n窗口内新合同，罚金条款 7.2。\n")
        cls.SNIP = "罚金条款 7.2"
        cls.GOOD = json.dumps({
            "graph": {"overview": "本期 1 篇合同类文档", "entity_changes": []},
            "findings": {"patterns": [{"text": "合同含罚金条款",
                                       "citations": [{"doc": "pi-b1",
                                                      "page": "1",
                                                      "snippet": cls.SNIP}]}],
                         "trends": [], "contradictions": []},
            "open_questions": []}, ensure_ascii=False)

    def setUp(self):
        for k in ("PI_BASE", "PI_KEY", "CENHUA_LONGJOB_MAX_COST_CNY",
                  "CENHUA_MAX_COST_CNY", "CENHUA_MAX_LLM_CALLS"):
            os.environ.pop(k, None)

    def _fake_added(self, name):
        """假引擎：ADDED_RE 可解析行 + 台账写行（模拟 pi_ingest.py 副作用）。"""
        def _run(*a, **k):
            led_path = os.path.join(self.vault.store, "ingest_manifest.json")
            led = L.read_json(led_path, {}) or {}
            led["pi-digest1"] = {"name": name,
                                 "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
            with open(led_path, "w", encoding="utf-8") as f:
                json.dump(led, f, ensure_ascii=False)
            return (0, "+ %s -> pi-digest1 (0s, gw=gw1)\n" % name)
        return _run

    def _reset_backflow(self):
        """清掉回流 doc 的 dedupe/台账痕迹，让下一次回流是全新 added。"""
        dp = os.path.join(self.vault.meta, "dedupe.json")
        dd = L.read_json(dp, {}) or {}
        for k in [k for k, v in dd.items()
                  if v.get("doc_id") == "pi-digest1"]:
            del dd[k]
        with open(dp, "w", encoding="utf-8") as f:
            json.dump(dd, f)
        led_path = os.path.join(self.vault.store, "ingest_manifest.json")
        led = L.read_json(led_path, {}) or {}
        led.pop("pi-digest1", None)
        with open(led_path, "w", encoding="utf-8") as f:
            json.dump(led, f, ensure_ascii=False)

    def test_23_ingest_back_tier_and_chain(self):
        from unittest import mock
        from cenhua_service import refine as R
        # ingest_one 现在 gateway 检查在 dedupe/is_supported 之后；
        # 要测引擎路径（mock run_engine）必须让 chat_ready 通过。
        os.environ["PI_BASE"] = "http://127.0.0.1:9/v1"
        os.environ["PI_KEY"] = "k"
        try:
            with mock.patch.object(R, "call_llm", return_value=(self.GOOD, 9, 9)):
                res, _ = G.compose(self.vault, ["pi-b1"], label="weekly")
            self.assertEqual(res.rc, 0)
            with mock.patch.object(L, "run_engine",
                                   self._fake_added(os.path.basename(res.path))):
                doc_id = G.ingest_back(self.vault, res)
        finally:
            os.environ.pop("PI_BASE", None)
            os.environ.pop("PI_KEY", None)
        self.assertEqual(doc_id, "pi-digest1")
        led = L.read_json(os.path.join(self.vault.store,
                                       "ingest_manifest.json"), {})
        rec = led["pi-digest1"]
        self.assertEqual(rec["tier"], "derived-doc")   # 显式覆盖（名称不命中 DERIVED_RE）
        self.assertEqual(rec["derived_from"], ["pi-b1"])
        from cenhua_service import tier as TG
        self.assertEqual(TG.doc_tier(self.vault, "pi-digest1"), "derived-doc")
        self.assertFalse(TG.evidence_eligible(self.vault, "pi-digest1"))
        self.assertEqual(TG.derived_from(self.vault, "pi-digest1"), ["pi-b1"])
        # inbox 闭环：复制件已被 stage 到 .processed
        # inbox 常驻 .processed/.failed 隐藏 stage 目录，只看待处理项
        self.assertEqual([f for f in os.listdir(self.vault.inbox)
                          if not f.startswith('.')], [])
        self.assertTrue(any(f.startswith("洞察_weekly_")
                            for f in os.listdir(self.vault.processed)))
        # works/ 原件保留
        self.assertTrue(os.path.isfile(res.path))

    def test_24_flow_backflow_line(self):
        from unittest import mock
        from cenhua_service import refine as R
        os.environ["PI_BASE"] = "http://127.0.0.1:9/v1"
        os.environ["PI_KEY"] = "k"
        try:
            with mock.patch.object(R, "call_llm",
                                   return_value=(self.GOOD, 9, 9)), \
                 mock.patch.object(L, "run_engine",
                                   self._fake_added("x.md")):
                res = G.digest_flow(self.vault, weekly=True)
        finally:
            os.environ.pop("PI_BASE", None)
            os.environ.pop("PI_KEY", None)
        self.assertEqual(res.rc, 0)
        hit = [l for l in res.lines if "[digest] backflow" in l]
        self.assertEqual(len(hit), 1)
        self.assertIn("pi-digest1", hit[0])
        led = L.read_json(os.path.join(self.vault.store,
                                       "ingest_manifest.json"), {})
        self.assertEqual(led["pi-digest1"]["tier"], "derived-doc")

    def test_25_backflow_never_breaks_rc(self):
        from unittest import mock
        from cenhua_service import refine as R
        self._reset_backflow()          # 避免同名内容 sha1 dupe 直接短路
        os.environ["PI_BASE"] = "http://127.0.0.1:9/v1"
        os.environ["PI_KEY"] = "k"
        try:
            with mock.patch.object(R, "call_llm",
                                   return_value=(self.GOOD, 9, 9)), \
                 mock.patch.object(L, "run_engine",
                                   return_value=(1, "engine down\n")):
                res = G.digest_flow(self.vault, weekly=True)
        finally:
            os.environ.pop("PI_BASE", None)
            os.environ.pop("PI_KEY", None)
        self.assertEqual(res.rc, 0)               # 回流失败不改变 digest rc
        self.assertTrue(any("skipped" in l for l in res.lines
                            if "[digest] backflow" in l))

    def test_26_missing_path_returns_empty(self):
        res = G.DigestResult(path="")
        self.assertEqual(G.ingest_back(self.vault, res), "")
        res2 = G.DigestResult(path="/nonexistent/洞察_weekly_V9_x.md")
        self.assertEqual(G.ingest_back(self.vault, res2), "")

    def test_27_digest_via_channel(self):
        """任务 9 验收：digest_flow 经 core.channel_job 任务通道执行并逐行 emit。"""
        from unittest import mock
        from cenhua_service import core as CO
        from cenhua_service import jobs as J
        from cenhua_service import refine as R
        os.environ["PI_BASE"] = "http://127.0.0.1:9/v1"
        os.environ["PI_KEY"] = "k"
        try:
            with mock.patch.object(R, "call_llm",
                                   return_value=(self.GOOD, 9, 9)), \
                 mock.patch.object(L, "run_engine",
                                   self._fake_added("x.md")):
                h = J.submit(CO.channel_job("digest", G.digest_flow,
                                            self.vault, weekly=True))
                printed = []
                st = J.run_cli(h, printed.append, poll=0.01, timeout=15)
                res = J.job_result(h)          # 直接是 DigestResult
        finally:
            os.environ.pop("PI_BASE", None)
            os.environ.pop("PI_KEY", None)
        self.assertEqual(st.state, J.DONE)
        self.assertEqual(res.rc, 0)
        # run_cli 打印的行 = result.lines 逐行 emit（含 rc 摘要行）
        for line in res.lines:
            self.assertIn(line, printed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
