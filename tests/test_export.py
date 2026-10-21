#!/usr/bin/env python3
"""test_export.py — M4c-13 导出离线单测（Markdown/HTML/PDF，roadmap §7.5）。

覆盖：parse_cli 三格式 flag、md 逐字节复制、html 骨架 + 表格渲染 +
script/on* 消毒、pdf 用 pymupdf 读回字符完整性（引擎 html_to_pdf 内置
>=85% 校验，读回比对是 dev-plan §8.3 #13 的"读回验收"口径）、源文件非法
（穿越/非 .md/不存在）rc2、格式非法 rc2、CLI dispatch 与 USAGE。
纯离线零 LLM（草稿直接手写作产物源）。

Run:  python3 tests/test_export.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "bin", "cenhua")

_TEST_HOME = tempfile.mkdtemp(prefix="cenhua-exp-")
os.environ["CENHUA_HOME"] = _TEST_HOME
os.environ["CENHUA_CONFIG_DIR"] = os.path.join(_TEST_HOME, "config-dir")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import m_lib as L  # noqa: E402
from cenhua_service import draft as D  # noqa: E402
from cenhua_service import exporter as X  # noqa: E402

SRC = "供应链融资办法_V1_2026-01-01.md"
MD_TEXT = """<!-- draft: topic=供应链融资办法 version=1 -->
<!-- template: memo -->
# 供应链融资办法

## 违约成本

逾期成本高企 [pi-d1 P1]。

> 引文 [pi-d1 P1] 违约金为合同金额的 5%  · ✓

| 项目 | 数值 |
| --- | --- |
| 违约金比例 | 5% |
| 逾期触发 | 30 天 |

<script>alert(1)</script>
<img src=x onerror="alert(2)">
"""


def _write_draft(vault, name=SRC, text=MD_TEXT):
    os.makedirs(D.drafts_dir(vault), exist_ok=True)
    path = os.path.join(D.drafts_dir(vault), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class ParseCliTest(unittest.TestCase):
    def test_01_default_md(self):
        self.assertEqual(X.parse_cli(["a.md"]), ("a.md", "md"))

    def test_02_format_flags(self):
        self.assertEqual(X.parse_cli(["a.md", "--html"]), ("a.md", "html"))
        self.assertEqual(X.parse_cli(["--pdf", "a.md"]), ("a.md", "pdf"))

    def test_03_no_file(self):
        self.assertEqual(X.parse_cli(["--html"]), ("", "html"))

    def test_04_flow_no_file_rc2(self):
        self.assertEqual(X.flow(None, [])["rc"], 2)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([CLI, "init", "expv", "--yes"],
                           capture_output=True, text=True,
                           env=dict(os.environ, CENHUA_HOME=_TEST_HOME),
                           timeout=120)
        assert r.returncode == 0, r.stderr
        cls.vault = L.Vault("expv")

    def setUp(self):
        for k in ("PI_BASE", "PI_KEY"):
            os.environ.pop(k, None)
        self.addCleanup(shutil.rmtree, D.drafts_dir(self.vault),
                        ignore_errors=True)
        self.addCleanup(shutil.rmtree, X.exports_dir(self.vault),
                        ignore_errors=True)

    def run_cli(self, args):
        e = dict(os.environ, CENHUA_HOME=_TEST_HOME)
        return subprocess.run([CLI, *args], env=e, cwd=ROOT,
                              capture_output=True, text=True, timeout=120)


class ExportTest(Base):
    def test_10_md_byte_copy(self):
        src = _write_draft(self.vault)
        res = X.export(self.vault, SRC, "md")
        self.assertEqual(res["rc"], 0)
        self.assertTrue(res["path"].endswith(".md"))
        with open(src, "rb") as f, open(res["path"], "rb") as g:
            self.assertEqual(f.read(), g.read())

    def test_11_html_skeleton_and_table(self):
        _write_draft(self.vault)
        res = X.export(self.vault, SRC, "html")
        self.assertEqual(res["rc"], 0)
        with open(res["path"], encoding="utf-8") as f:
            html = f.read()
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("<title>", html)
        self.assertIn("<table>", html)          # markdown tables 扩展生效
        self.assertIn("违约金比例", html)
        # 消毒口径与 pages._md_to_html 单一来源
        self.assertNotIn("<script", html)
        self.assertNotIn("onerror", html)

    def test_12_pdf_readback_integrity(self):
        """PDF 读回比对（#13 验收：不只看生成成功，要校验产物内容）。"""
        _write_draft(self.vault)
        res = X.export(self.vault, SRC, "pdf")
        self.assertEqual(res["rc"], 0, res["lines"])
        import pymupdf
        doc = pymupdf.open(res["path"])
        text = "".join(p.get_text() for p in doc)
        doc.close()
        for probe in ("供应链融资办法", "违约成本", "5%", "30"):
            self.assertIn(probe, text)

    def test_13_bad_source_rc2(self):
        _write_draft(self.vault)
        for bad in ("../etc/passwd.md", "notmd.txt", "不存在_V1_x.md",
                    "sub/嵌套.md", ".hidden.md"):
            self.assertEqual(X.export(self.vault, bad, "md")["rc"], 2, bad)

    def test_14_bad_fmt_rc2(self):
        _write_draft(self.vault)
        self.assertEqual(X.export(self.vault, SRC, "docx")["rc"], 2)

    def test_15_pdf_failure_no_leftover(self):
        """渲染异常 -> rc1 且不留半成品文件（导出失败不污染 exports/）。"""
        from unittest import mock
        _write_draft(self.vault)
        with mock.patch.object(X, "_html_to_pdf",
                               side_effect=RuntimeError("blank pdf")):
            res = X.export(self.vault, SRC, "pdf")
        self.assertEqual(res["rc"], 1)
        self.assertFalse(os.path.exists(
            os.path.join(X.exports_dir(self.vault),
                         os.path.splitext(SRC)[0] + ".pdf")))

    def test_16_fmt_case_insensitive(self):
        _write_draft(self.vault)
        self.assertEqual(X.export(self.vault, SRC, "MD")["rc"], 0)


class CliTest(Base):
    def test_20_usage_mentions_export(self):
        r = subprocess.run([CLI, "--help"], capture_output=True, text=True,
                           env=dict(os.environ, CENHUA_HOME=_TEST_HOME))
        self.assertIn("MULTI-TURN & RERANK", r.stdout + r.stderr)

    def test_21_missing_args_rc2(self):
        self.assertEqual(self.run_cli(["export"]).returncode, 2)

    def test_22_export_md_via_cli(self):
        _write_draft(self.vault)
        r = self.run_cli(["export", SRC, "--md"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("exported MD", r.stdout)
        out = os.path.join(X.exports_dir(self.vault),
                           os.path.splitext(SRC)[0] + ".md")
        self.assertTrue(os.path.isfile(out))

    def test_23_bad_source_via_cli_rc2(self):
        self.assertEqual(self.run_cli(["export", "无.md", "--html"]
                                      ).returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
