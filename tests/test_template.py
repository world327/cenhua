#!/usr/bin/env python3
"""test_template.py — M4c-12 模板系统离线单测（roadmap §7.5）。

覆盖：parse_cli 形态（--list/--add/--section 可重复/tid+topic）、内置四模板
齐全、自定义可加 + 同名覆盖内置 + 已存在需 --force、template_flow 三闸
（dry-run → 网关 → longjob 预算 → --force 放行）、mock LLM 成功落盘
（`<!-- template: id -->` 溯源 + rid 幂等短路）、解析失败转规则兜底
（零 LLM 消费）、CLI dispatch 与 USAGE。纯离线零网关（LLM mock
cenhua_service.refine.call_llm）。

Run:  python3 tests/test_template.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "bin", "cenhua")

_TEST_HOME = tempfile.mkdtemp(prefix="cenhua-tpl-")
os.environ["CENHUA_HOME"] = _TEST_HOME
os.environ["CENHUA_CONFIG_DIR"] = os.path.join(_TEST_HOME, "config-dir")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import m_lib as L  # noqa: E402
from cenhua_service import draft as D  # noqa: E402
from cenhua_service import templates as TP  # noqa: E402

DOC = "pi-t1"
SNIP = "违约金为合同金额的 5%"
TEXT = ("=== PAGE 1 ===\n供应链融资的违约金为合同金额的 5%，逾期 30 天触发。\n"
        "=== PAGE 2 ===\n供应链融资的授信额度需每年复核一次。\n")


def _good_json():
    return json.dumps({"sections": [
        {"title": "背景", "body": "逾期成本高企 [doc P1]。",
         "citations": [{"doc": DOC, "page": "1", "snippet": SNIP}]},
        {"title": "关键事实", "body": "额度需年度复核 [doc P2]。",
         "citations": [{"doc": DOC, "page": "2",
                        "snippet": "授信额度需每年复核一次"}]}]},
        ensure_ascii=False)


class ParseCliTest(unittest.TestCase):
    def test_01_generation_defaults(self):
        kw = TP.parse_cli(["memo", "供应链融资风险"])
        self.assertEqual((kw["action"], kw["tid"], kw["topic"]),
                         ("", "memo", "供应链融资风险"))
        self.assertFalse(kw["dry_run"])

    def test_02_aux_actions(self):
        self.assertEqual(TP.parse_cli(["--list"])["action"], "list")
        kw = TP.parse_cli(["--add", "board_brief", "--name", "董事会简报",
                           "--section", "要点", "--section", "风险"])
        self.assertEqual((kw["action"], kw["tid"], kw["name"], kw["sections"]),
                         ("add", "board_brief", "董事会简报", ["要点", "风险"]))
        kw = TP.parse_cli(["--add", "x1", "--sections", "a,b,c"])
        self.assertEqual(kw["sections"], ["a", "b", "c"])

    def test_03_gates_and_numbers(self):
        kw = TP.parse_cli(["memo", "主题", "--dry-run", "--force",
                           "--max-cost", "0.5", "--top", "5"])
        self.assertEqual((kw["dry_run"], kw["force"], kw["top"]),
                         (True, True, 5))
        self.assertAlmostEqual(kw["max_cost"], 0.5)
        self.assertIsNone(TP.parse_cli(["memo", "主题", "--top", "x"])["top"])

    def test_04_needs_channel(self):
        self.assertTrue(TP.needs_channel(["memo", "主题"]))
        self.assertFalse(TP.needs_channel(["--list"]))
        self.assertFalse(TP.needs_channel(["memo"]))          # show 离线
        self.assertFalse(TP.needs_channel(["--add", "x", "--section", "s"]))


class Base(unittest.TestCase):
    """共享 vault：1 篇 primary 语料，模板目录/草稿目录每例清理。"""

    @classmethod
    def setUpClass(cls):
        r = subprocess.run([CLI, "init", "tplv", "--yes"],
                           capture_output=True, text=True,
                           env=dict(os.environ, CENHUA_HOME=_TEST_HOME),
                           timeout=120)
        assert r.returncode == 0, r.stderr
        cls.vault = L.Vault("tplv")

    def setUp(self):
        _manifest = {DOC: {"name": "供应链融资办法.pdf", "tier": "primary",
                           "ts": time.strftime("%Y-%m-%d %H:%M:%S")}}
        os.makedirs(self.vault.store, exist_ok=True)
        with open(os.path.join(self.vault.store, "ingest_manifest.json"),
                  "w", encoding="utf-8") as f:
            json.dump(_manifest, f)
        os.makedirs(self.vault.textdir, exist_ok=True)
        with open(os.path.join(self.vault.textdir, DOC + ".txt"),
                  "w", encoding="utf-8") as f:
            f.write(TEXT)
        for k in ("PI_BASE", "PI_KEY", "CENHUA_LONGJOB_MAX_COST_CNY"):
            os.environ.pop(k, None)
        self.addCleanup(shutil.rmtree, D.drafts_dir(self.vault),
                        ignore_errors=True)
        self.addCleanup(shutil.rmtree, TP.tpl_dir(self.vault),
                        ignore_errors=True)
        self.addCleanup(lambda: os.remove(D._rid_path(self.vault))
                        if os.path.isfile(D._rid_path(self.vault)) else None)

    def gateway(self):
        os.environ["PI_BASE"] = "http://127.0.0.1:9/v1"
        os.environ["PI_KEY"] = "k"

    def run_cli(self, args):
        e = dict(os.environ, CENHUA_HOME=_TEST_HOME)
        e.pop("PI_BASE", None)
        e.pop("PI_KEY", None)
        return subprocess.run([CLI, *args], env=e, cwd=ROOT,
                              capture_output=True, text=True, timeout=120)


class CatalogTest(Base):
    def test_10_four_builtins(self):
        ids = {t["id"] for t in TP.list_templates(self.vault)}
        self.assertTrue({"report", "memo", "email", "weekly"} <= ids)
        for t in TP.list_templates(self.vault):
            if t["id"] in TP.BUILTIN:
                self.assertTrue(t["sections"])       # 内置都有骨架

    def test_11_custom_add_and_override(self):
        r = TP.add_template(self.vault, "board_brief", "董事会简报",
                            ["要点", "风险", "决议"])
        self.assertEqual(r["rc"], 0)
        t = TP.load(self.vault, "board_brief")
        self.assertEqual(t["name"], "董事会简报")
        self.assertEqual(t["sections"], ["要点", "风险", "决议"])
        self.assertTrue(t["custom"])
        # 已存在需 --force
        self.assertEqual(TP.add_template(self.vault, "board_brief")["rc"], 2)
        self.assertEqual(TP.add_template(self.vault, "board_brief",
                                         overwrite=True)["rc"], 0)
        # 非法 id
        self.assertEqual(TP.add_template(self.vault, "Bad ID!")["rc"], 2)

    def test_12_custom_overrides_builtin(self):
        TP.add_template(self.vault, "memo", "定制备忘", ["唯一小节"])
        t = TP.load(self.vault, "memo")
        self.assertEqual(t["sections"], ["唯一小节"])   # 覆盖内置骨架
        self.assertTrue(t["builtin"])                  # 仍是同名内置 id
        rows = {r["id"]: r for r in TP.list_templates(self.vault)}
        self.assertTrue(rows["memo"]["custom"])

    def test_13_unknown_template_none(self):
        self.assertIsNone(TP.load(self.vault, "nope9"))
        self.assertEqual(TP.aux_flow(self.vault, {"action": "",
                                                  "tid": "nope9"})["rc"], 2)

    def test_14_show_and_list_lines(self):
        res = TP.show(TP.load(self.vault, "report"))
        self.assertEqual(res["rc"], 0)
        self.assertTrue(any("背景" in l for l in res["lines"]))
        res = TP.aux_flow(self.vault, {"action": "list"})
        self.assertEqual(res["rc"], 0)
        self.assertTrue(any("memo" in l for l in res["lines"]))


class GateTest(Base):
    def test_20_missing_args_rc2(self):
        self.assertEqual(TP.template_flow(self.vault).rc, 2)
        self.assertEqual(TP.template_flow(self.vault, tid="memo").rc, 2)
        self.assertEqual(TP.template_flow(self.vault, tid="nope9",
                                          topic="x").rc, 2)

    def test_21_recall_empty_rc1(self):
        res = TP.template_flow(self.vault, tid="memo",
                               topic="量子计算与冷藏榴莲")
        self.assertEqual(res.rc, 1)
        self.assertTrue(any("召回为空" in l for l in res.lines))

    def test_22_dry_run_no_gateway(self):
        res = TP.template_flow(self.vault, tid="memo", topic="供应链融资",
                               dry_run=True)
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.cost["calls"], 1)
        self.assertEqual(res.path, "")
        self.assertTrue(any("dry-run" in l for l in res.lines))

    def test_23_no_gateway_rc3(self):
        res = TP.template_flow(self.vault, tid="memo", topic="供应链融资")
        self.assertEqual(res.rc, 3)
        self.assertTrue(any("PI_BASE/PI_KEY" in l for l in res.lines))

    def test_24_budget_gate_rc4_and_force(self):
        self.gateway()
        os.environ["CENHUA_LONGJOB_MAX_COST_CNY"] = "0.000001"
        res = TP.template_flow(self.vault, tid="memo", topic="供应链融资",
                               runtime=None)
        self.assertEqual(res.rc, 4)
        self.assertTrue(res.lines[0].startswith("[template] REFUSED"))
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 200, 90)):
            res = TP.template_flow(self.vault, tid="memo",
                                   topic="供应链融资", force=True)
        self.assertEqual(res.rc, 0)


class GenerateTest(Base):
    def test_30_llm_article_with_template_marker(self):
        self.gateway()
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 300, 120)):
            res = TP.template_flow(self.vault, tid="memo", topic="供应链融资")
        self.assertEqual((res.rc, res.mode, res.version), (0, "llm", 1))
        self.assertEqual(res.derived_from, [DOC])
        self.assertEqual(sum(1 for c in res.citations if c["ok"]), 2)
        name = "%s_V1_%s.md" % (D.slug("供应链融资"),
                                time.strftime("%Y-%m-%d"))
        self.assertEqual(os.path.basename(res.path), name)
        art = D._read(res.path)
        self.assertIn("tier=derived-doc", art)
        self.assertIn("<!-- template: memo -->", art)     # 模板溯源行
        self.assertIn("<!-- draft: topic=供应链融资", art)
        self.assertIn(SNIP, art)

    def test_31_parse_fail_rules_fallback(self):
        self.gateway()
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm", return_value=("不像 JSON", 9, 9)):
            res = TP.template_flow(self.vault, tid="weekly",
                                   topic="供应链融资")
        self.assertEqual((res.rc, res.mode), (0, "rules"))
        self.assertEqual(res.cost["calls"], 0)         # 兜底零 LLM 消费
        self.assertTrue(any("无法解析" in l for l in res.lines))
        art = D._read(res.path)
        self.assertIn("需 LLM", art)
        self.assertIn("本周进展", art)                  # 模板骨架明示

    def test_32_llm_exception_rules_fallback(self):
        self.gateway()
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm", side_effect=RuntimeError("x")):
            res = TP.template_flow(self.vault, tid="email",
                                   topic="供应链融资")
        self.assertEqual((res.rc, res.mode), (0, "rules"))
        self.assertTrue(any("调用失败" in l for l in res.lines))

    def test_33_rid_idempotent_short_circuit(self):
        self.gateway()
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 300, 120)) as llm:
            first = TP.template_flow(self.vault, tid="memo",
                                     topic="供应链融资")
            second = TP.template_flow(self.vault, tid="memo",
                                      topic="供应链融资")
        self.assertEqual(llm.call_count, 1)            # 同 rid 不再花钱
        self.assertEqual((first.rc, second.rc, second.mode), (0, 0, "cached"))
        self.assertEqual(second.path, first.path)
        self.assertTrue(any("idempotent" in l for l in second.lines))

    def test_34_ledger_cmd_template(self):
        self.gateway()
        from cenhua_service import cost as CC
        from cenhua_service import refine as R
        with mock.patch.object(R, "call_llm",
                               return_value=(_good_json(), 300, 120)):
            TP.template_flow(self.vault, tid="report", topic="供应链融资")
        path = CC.ledger_path(self.vault)
        rows = [json.loads(x) for x in open(path, encoding="utf-8")
                if x.strip()] if os.path.isfile(path) else []
        self.addCleanup(lambda: os.remove(path))
        hit = [r for r in rows if r.get("cmd") == "template"]
        self.assertTrue(hit)
        self.assertEqual(hit[-1]["template"], "report")
        self.assertTrue(hit[-1]["tokens_in"])


class CliTest(Base):
    def test_40_usage_mentions_template(self):
        r = subprocess.run([CLI, "--help"], capture_output=True, text=True,
                           env=dict(os.environ, CENHUA_HOME=_TEST_HOME))
        self.assertIn("TEMPLATES & EXPORT", r.stdout + r.stderr)

    def test_41_aux_offline_via_cli(self):
        r = self.run_cli(["template", "--list"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("memo", r.stdout)
        r2 = self.run_cli(["template", "weekly"])
        self.assertEqual(r2.returncode, 0)
        self.assertIn("本周进展", r2.stdout)
        r3 = self.run_cli(["template", "--add", "cli_tpl",
                           "--section", "要点"])
        self.assertEqual(r3.returncode, 0)
        r4 = self.run_cli(["template", "--add", "cli_tpl"])
        self.assertEqual(r4.returncode, 2)             # 已存在需 --force

    def test_42_generate_no_gateway_offline_rc3(self):
        r = self.run_cli(["template", "memo", "供应链融资"])
        self.assertEqual(r.returncode, 3)              # 三闸：网关未配置


if __name__ == "__main__":
    unittest.main(verbosity=2)
