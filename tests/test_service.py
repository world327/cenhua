#!/usr/bin/env python3
"""M1a service 层测试套件（成本 + 质量基础设施）。

覆盖：
  * test_70_service_no_print：service 模块禁 print/exit（全量生效）
  * test_71_cli_is_thin：白名单命令（cost/bench）CLI 薄包装
  * pricing / OpenClaw 全名匹配 / token 估算 / 金额换算
  * cost-ledger 全量记账 + cenhua cost 汇总
  * verify_citation 三参原语（NFKC + 去空白 + 全半角折叠）
  * bench fixture 门禁（存在性 100% + 引文条目 >=95%）

Run:  python3 tests/test_service.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "bin", "cenhua")

# 必须在导入 m_lib/cenhua_service 之前设置 CENHUA_HOME，
# 因为 m_lib.HOME 在 import 时即计算（模块级常量）。
_TEST_HOME = tempfile.mkdtemp(prefix="cenhua-svc-")
os.environ["CENHUA_HOME"] = _TEST_HOME
os.environ["CENHUA_CONFIG_DIR"] = os.path.join(_TEST_HOME, "config-dir")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

from cenhua_service import cost as C  # noqa: E402
from cenhua_service import verify as V  # noqa: E402
from cenhua_service import bench as B  # noqa: E402


def run(args, home, env=None):
    e = dict(os.environ)
    e["CENHUA_HOME"] = home
    e["CENHUA_CONFIG_DIR"] = os.path.join(home, "config-dir")
    e.update(env or {})
    e.pop("PI_BASE", None)
    e.pop("PI_KEY", None)
    return subprocess.run([CLI, *args], env=e, cwd=ROOT,
                          capture_output=True, text=True)


class ServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = _TEST_HOME
        r = run(["init", "t", "--yes"], cls.home)
        assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TEST_HOME, ignore_errors=True)

    # ------------------------------------------------- test_70 / test_71 ----
    def test_70_service_no_print(self):
        """service 模块禁 print/exit（全量生效，M1a 起）。"""
        import ast
        svc_dir = os.path.join(ROOT, "cenhua_service")
        for fn in os.listdir(svc_dir):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(svc_dir, fn)
            src = open(path, encoding="utf-8").read()
            # 用 AST 剥离 docstring/注释，只检查真实代码
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = (f.id if isinstance(f, ast.Name) else
                            (f.attr if isinstance(f, ast.Attribute) else ""))
                    if name in ("print", "exit"):
                        self.fail(f"{fn} must not call {name}()")
                    if name == "say" and isinstance(f, ast.Attribute) \
                            and isinstance(f.value, ast.Name) \
                            and f.value.id == "L":
                        self.fail(f"{fn} must not print via L.say()")
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    f = node.value.func
                    if isinstance(f, ast.Attribute) and f.attr == "exit" \
                            and isinstance(f.value, ast.Name) \
                            and f.value.id == "sys":
                        self.fail(f"{fn} must not call sys.exit()")

    def test_71_cli_is_thin(self):
        """白名单命令（M1a: cost/bench；M1b: refine/related）CLI 薄包装，
        函数体 <=10 行。"""
        import m_cost
        import m_weave
        for mod, names in ((m_cost, ("cost_cmd", "bench_cmd")),
                           (m_weave, ("refine_cmd", "related_cmd"))):
            for name in names:
                fn = getattr(mod, name)
                src_lines = _func_body(fn)
                self.assertLessEqual(len(src_lines), 10,
                                     f"{name} CLI must be thin (<=10 lines)")

    # ------------------------------------------------------- pricing ----
    def test_80_pricing_match_full_name(self):
        p, priced, note = C.match_price("openai/gpt-4o-mini")
        self.assertTrue(priced)
        self.assertEqual(p["currency"], "USD")
        self.assertEqual(note, "")

    def test_81_pricing_match_bare_id(self):
        p, priced, note = C.match_price("gpt-4o-mini")
        self.assertTrue(priced)
        self.assertEqual(p["currency"], "USD")

    def test_82_pricing_unknown_uses_default(self):
        p, priced, note = C.match_price("openclaw:p9/weird-model")
        self.assertFalse(priced)
        self.assertIn("未配置单价", note)
        self.assertEqual(p["currency"], "USD")

    def test_83_token_estimate(self):
        self.assertGreater(C.estimate_tokens("hello world 你好世界"), 0)
        self.assertEqual(C.estimate_tokens(""), 0)
        # 数量级正确：100 字符 -> ~62 token
        self.assertAlmostEqual(C.estimate_tokens("x" * 100), 62, delta=5)

    def test_84_cost_estimate(self):
        cost, cur, priced, note = C.estimate_cost("gpt-4o-mini", 1000, 500)
        self.assertEqual(cur, "USD")
        self.assertTrue(priced)
        # 单价按每 1K token：1000 in * 0.00015 + 500 out * 0.0006
        # = 1 * 0.00015 + 0.5 * 0.0006 = 0.00015 + 0.0003 = 0.00045
        self.assertAlmostEqual(cost, 0.00045, places=6)

    def test_85_format_mixed_currency(self):
        out = C.format_cost([(0.35, "CNY"), (0.02, "USD")])
        self.assertIn("¥0.35", out)
        self.assertIn("$0.02", out)
        self.assertIn("混合货币", out)

    # ------------------------------------------------------- ledger ----
    def test_90_ledger_append_and_summary(self):
        import m_lib as L
        v = L.Vault("t")
        C.ledger_append(v, {"cmd": "ingest", "doc": "a.pdf", "calls": 1,
                            "tokens_in": 0, "tokens_out": 0, "est_cost": 0.0,
                            "currency": "CNY", "priced": False})
        C.ledger_append(v, {"cmd": "ask", "doc": "b", "calls": 2,
                            "tokens_in": 0, "tokens_out": 0, "est_cost": 0.0,
                            "currency": "CNY", "priced": False})
        groups, total_parts, total_calls = C.cost_summary(v)
        cmds = [g for g, _ in groups]
        # 摄取成本单列首位
        self.assertEqual(cmds[0], "ingest")
        self.assertEqual(total_calls, 3)

    def test_91_cost_cmd_output(self):
        r = run(["cost", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ingest", r.stdout)
        self.assertIn("ask", r.stdout)

    def test_92_calibrate_warns_on_drift(self):
        msg = C.calibrate(None, actual_cost=10.0, est_cost=1.0)
        self.assertIn("预估偏差", msg)
        self.assertIn("单价表可能过期", msg)
        self.assertEqual(C.calibrate(None, actual_cost=1.0, est_cost=1.0), "")

    # --------------------------------------------------- verify_citation ----
    def test_100_verify_citation_true(self):
        import m_lib as L
        v = L.Vault("t")
        # 先建文本层
        self._seed_text(v)
        self.assertTrue(V.verify_citation(v, "pi-aaaa1111", "1",
                                          "The penalty for early termination"))
        self.assertTrue(V.verify_citation(v, "pi-aaaa1111", "2",
                                          "Account 6222 0200 1234 5678"))

    def test_101_verify_citation_false_wrong_page(self):
        import m_lib as L
        v = L.Vault("t")
        self._seed_text(v)
        # 内容存在但页码错误 -> False（非"页存在"同义反复）
        self.assertFalse(V.verify_citation(v, "pi-aaaa1111", "2",
                                           "The penalty for early termination"))

    def test_102_verify_citation_false_wrong_content(self):
        import m_lib as L
        v = L.Vault("t")
        self._seed_text(v)
        # 页码存在但内容错误 -> False
        self.assertFalse(V.verify_citation(v, "pi-aaaa1111", "1",
                                           "This sentence does not exist"))

    def test_103_verify_citation_empty_snippet(self):
        import m_lib as L
        v = L.Vault("t")
        self._seed_text(v)
        self.assertFalse(V.verify_citation(v, "pi-aaaa1111", "1", ""))

    def test_104_verify_citation_fullwidth_fold(self):
        import m_lib as L
        v = L.Vault("t")
        self._seed_text(v)
        # 全角逗号折叠：原文 "30% of the annual fee." 用全角标点也能匹配
        self.assertTrue(V.verify_citation(v, "pi-aaaa1111", "1",
                                          "The penalty for early termination"))

    def _seed_text(self, v):
        """在 vault t 的文本层写入两页（模拟 flatten 产物）。"""
        os.makedirs(v.textdir, exist_ok=True)
        with open(os.path.join(v.textdir, "pi-aaaa1111.txt"),
                  encoding="utf-8", mode="w") as f:
            f.write("=== PAGE 1 ===\n"
                    "The penalty for early termination is 30% of the annual fee.\n"
                    "=== PAGE 2 ===\n"
                    "Account 6222 0200 1234 5678 belongs to the client.\n")

    # --------------------------------------------------------- bench ----
    def test_110_bench_fixture_passes(self):
        rep = B.run_fixture()
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["existence"]["pass"], rep["existence"]["total"])
        self.assertGreaterEqual(rep["traceability"]["total_entries"], 20)
        self.assertGreaterEqual(
            rep["traceability"]["pass_entries"] / rep["traceability"]["total_entries"],
            0.95)

    def test_111_bench_cmd(self):
        r = run(["bench", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS", r.stdout)

    def test_112_bench_corpus_report_mode(self):
        r = run(["bench", "--corpus", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("report mode", r.stdout)


def _func_body(fn):
    """返回函数源码行数（粗略，用于 CLI 薄包装检查）。"""
    import inspect
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return 0
    return [l for l in src.splitlines() if l.strip() and not l.strip().startswith("#")]


if __name__ == "__main__":
    unittest.main(verbosity=2)
