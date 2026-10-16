#!/usr/bin/env python3
"""M2a 网页收录测试套件（离线，无需真实网络/chromium）。

覆盖：
  * URL 规范化去重
  * robots.txt 检查
  * 速率限制
  * 大小上限
  * readability 正文提取（降级路径）
  * 双产物生成
  * 静态 HTML 抓取降级（本地 HTTP server）
  * `cenhua add --url` 端到端（本地 server）
  * doctor chromium 自检

Run:  python3 tests/test_web.py
"""

import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "bin", "cenhua")

# 必须在导入 m_web（间接 import m_lib）之前设置 CENHUA_HOME，
# 因为 m_lib.HOME 在 import 时即计算（模块级常量）。
_TEST_HOME = tempfile.mkdtemp(prefix="cenhua-web-")
os.environ["CENHUA_HOME"] = _TEST_HOME
os.environ["CENHUA_CONFIG_DIR"] = os.path.join(_TEST_HOME, "config-dir")
# 测试页正文较短，守卫阈值调小（生产默认 100）
os.environ["CENHUA_MIN_CONTENT_CHARS"] = "20"

sys.path.insert(0, os.path.join(ROOT, "scripts"))

import m_web as W  # noqa: E402


def run(args, home, env=None):
    e = dict(os.environ)
    e["CENHUA_HOME"] = home
    e["CENHUA_CONFIG_DIR"] = os.path.join(home, "config-dir")
    e.update(env or {})
    e.pop("PI_BASE", None)
    e.pop("PI_KEY", None)
    return subprocess.run([CLI, *args], env=e, cwd=ROOT,
                          capture_output=True, text=True)


class _Handler(http.server.BaseHTTPRequestHandler):
    # 略超 5MB 上限的页面（验证截断）；刻意只超一点，避免客户端读满上限后
    # 服务端仍阻塞在 write 上（配合 ThreadingHTTPServer 双保险）。
    BIG = (b"<html><body>"
           + b"<p>filler text for the size limit padding test.</p>" * 100000
           + b"</body></html>")   # ≈5.3 MB，刚过 5 MB 上限

    def _send(self, body, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass    # 客户端按大小上限提前收手，属预期

    def do_GET(self):
        if self.path == "/robots.txt":
            body = b"User-agent: *\nDisallow: /private/\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/private/"):
            if self.path == "/private/ok":
                self._send(b"<html><body><article>"
                           b"<p>private page body text long enough to pass "
                           b"the content guard used by the fetch layer.</p>"
                           b"</article></body></html>")
                return
            self.send_response(403)
            self.end_headers()
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/page")
            self.end_headers()
            return
        if self.path == "/js":
            # JS 渲染页（模拟头条 m 站）：静态壳几乎无文本，
            # 渲染执行 JS 后才是 JS-RAN-OK + 足量正文
            # （拼接写法防止静态 HTML 源码里字面出现 JS-RAN-OK）
            self._send(b'<html><head><title>JS Page</title></head><body>'
                       b'<div id="x">INITIAL</div>'
                       b"<script>document.getElementById('x').textContent"
                       b"=('JS'+'-RAN-OK '+'headline body sentence. ')"
                       b".repeat(10);</script></body></html>")
            return
        if self.path == "/zh":
            self._send(("<html><head><title>年度报告</title></head><body>"
                        "<article><h1>2025 年度报告</h1>"
                        "<p>本年度营收增长百分之十五，现金流稳定。</p>"
                        "</article></body></html>").encode("utf-8"))
            return
        if self.path == "/big":
            self._send(self.BIG)
            return
        if self.path == "/stub":
            # 模拟 JS 空壳/反爬验证页：几乎无可提取文本
            self._send(b"<html><head><title>t</title></head>"
                       b"<body><div id=app></div></body></html>")
            return
        body = ("<html><head><title>Test Page</title></head>"
                "<body><nav>nav links</nav>"
                "<article><h1>Hello CENHUA</h1>"
                "<p>This is the main content of the test page.</p>"
                "</article><footer>footer</footer></body></html>"
                ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = _TEST_HOME
        r = run(["init", "t", "--yes"], cls.home)
        assert r.returncode == 0, r.stderr
        # 本地 HTTP server（多线程：大页客户端提前收手时 handler 阻塞不拖累他人）
        cls.httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.httpd.server_address[1]
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever,
                                             daemon=True)
        cls.server_thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        shutil.rmtree(cls.home, ignore_errors=True)

    # ------------------------------------------------- URL 规范化 ----
    def test_01_normalize_url(self):
        self.assertEqual(
            W.normalize_url("HTTPS://Example.com/path?b=2&a=1#frag"),
            "https://example.com/path?a=1&b=2")
        self.assertTrue(W.same_url("https://a.com/x?b=2&a=1",
                                   "https://a.com/x?a=1&b=2"))
        self.assertFalse(W.same_url("https://a.com/x", "https://a.com/y"))

    # ------------------------------------------------- robots.txt ----
    def test_02_robots_allowed(self):
        allowed, _ = W.robots_allowed(f"{self.base}/public")
        self.assertTrue(allowed)
        allowed, reason = W.robots_allowed(f"{self.base}/private/secret")
        self.assertFalse(allowed)
        self.assertIn("robots.txt", reason)

    # ------------------------------------------------- 速率限制 ----
    def test_03_rate_limiter(self):
        rl = W.RateLimiter(interval=1.0)
        self.assertTrue(rl.allow("https://a.com/p1", now=0))
        self.assertFalse(rl.allow("https://a.com/p2", now=0.5))
        self.assertTrue(rl.allow("https://a.com/p3", now=1.5))
        # 不同域名互不影响
        self.assertTrue(rl.allow("https://b.com/p1", now=0.5))

    # ------------------------------------------------- 大小上限 ----
    def test_04_size_limit(self):
        big = "x" * (W.MAX_PAGE_BYTES + 100)
        trunc, t = W.enforce_size_limit(big)
        self.assertTrue(t)
        self.assertLessEqual(len(trunc), W.MAX_PAGE_BYTES)
        small, t2 = W.enforce_size_limit("small")
        self.assertFalse(t2)

    # ------------------------------------------------- readability ----
    def test_05_readability_extract(self):
        html = ("<html><head><title>My Title</title></head><body>"
                "<nav>nav</nav><article><h1>Head</h1><p>Body text</p>"
                "</article><footer>foot</footer></body></html>")
        title, text = W.extract_readable(html)
        self.assertEqual(title, "My Title")
        self.assertIn("Body text", text)
        self.assertNotIn("nav", text)  # 导航被剥离

    def test_06_slugify(self):
        self.assertEqual(W.slugify_url("https://example.com/blog/my-article-123"),
                         "my-article-123")
        self.assertNotEqual(W.slugify_url("https://example.com/"), "")

    # ------------------------------------------------- 静态抓取降级 ----
    def test_07_fetch_static(self):
        html, ok, note = W.fetch_static(f"{self.base}/page")
        self.assertTrue(ok)
        self.assertIn("Hello CENHUA", html)

    def test_08_fetch_page_paths(self):
        # 显式禁用渲染 -> 必定静态、无 PDF
        html, pdf, source, note = W.fetch_page(f"{self.base}/page",
                                               use_render=False)
        self.assertIsNotNone(html)
        self.assertIsNone(pdf)
        self.assertEqual(source, "static")
        # 允许渲染 -> 环境相关：有 chromium 走 render（带 PDF），否则降级 static
        html2, pdf2, source2, _ = W.fetch_page(f"{self.base}/page",
                                              use_render=True)
        self.assertIsNotNone(html2)
        self.assertIn(source2, ("render", "static"))
        if W.chromium_available():
            self.assertEqual(source2, "render")
            self.assertTrue(pdf2 and pdf2.startswith(b"%PDF-"))
        else:
            self.assertEqual(source2, "static")

    # ------------------------------------------------- 双产物 ----
    def test_09_build_artifacts(self):
        import m_lib as L
        v = L.Vault("t")
        # 有 PDF：PDF 进 inbox（进索引），HTML 归档 snapshots（溯源）
        paths, snap, err = W.build_artifacts(
            f"{self.base}/page", "<html>hi</html>", b"%PDF-1.4 fake", v, "apage")
        self.assertEqual(err, "")
        self.assertEqual(len(paths), 1)              # 只有 PDF 进 inbox
        self.assertTrue(paths[0].endswith("url-apage.pdf"))
        self.assertTrue(os.path.isfile(paths[0]))
        self.assertTrue(snap.endswith("url-apage.html"))
        self.assertTrue(os.path.isfile(snap))
        self.assertIn(os.path.join("works", "snapshots"), snap)
        # 无 PDF（静态降级）：HTML 进 inbox 参与索引
        paths2, snap2, err2 = W.build_artifacts(
            f"{self.base}/page2", "<html>x</html>", None, v, "bpage")
        self.assertEqual(err2, "")
        self.assertEqual(len(paths2), 1)
        self.assertTrue(paths2[0].endswith("url-bpage.html"))
        self.assertTrue(os.path.isfile(snap2))

    # ------------------------------------------------- add --url 端到端 ----
    def test_10_add_url_static(self):
        # 无 PI_BASE/PI_KEY（引擎需 LLM 网关）-> 抓取成功、产物落 inbox、
        # 摄取失败被隔离进 .failed/（任务 13 验收点），不静默丢弃。
        r = run(["add", "--url", f"{self.base}/page", "--no-render",
                 "--vault", "t"], self.home)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 1, out)      # 有失败 -> rc=1
        self.assertIn("ingest failed", out)
        vault = os.path.join(self.home, "vaults", "t")
        failed_dir = os.path.join(vault, "inbox", ".failed")
        failed = os.listdir(failed_dir) if os.path.isdir(failed_dir) else []
        self.assertTrue(any(f.startswith("url-page") for f in failed),
                        f"artifact not staged to .failed/: {failed}")
        # HTML 快照归档在 works/snapshots/（溯源用，不进索引）
        snap = os.path.join(vault, "works", "snapshots", "url-page.html")
        self.assertTrue(os.path.isfile(snap))
        meta = snap[:-5] + ".meta.json"
        self.assertTrue(os.path.isfile(meta))
        with open(meta, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["url"], f"{self.base}/page")

    def test_11_add_url_robots_blocked(self):
        r = run(["add", "--url", f"{self.base}/private/secret", "--no-render",
                 "--vault", "t"], self.home)
        self.assertIn("robots.txt", r.stdout + r.stderr)
        # --force 显式覆盖：告警一次并继续抓取（/private/ok 可抓但 robots 禁）
        r = run(["add", "--url", f"{self.base}/private/ok", "--no-render",
                 "--force", "--vault", "t"], self.home)
        out = r.stdout + r.stderr
        self.assertIn("proceeding because of --force", out)
        self.assertNotIn("fetch failed", out)  # robots 不再拦，抓取成功
        self.assertIn("ingest failed", out)    # 无网关摄取失败（失败隔离）

    def test_12_add_url_file(self):
        urlfile = os.path.join(self.home, "urls.txt")
        with open(urlfile, "w", encoding="utf-8") as f:
            f.write(f"# comment\n{self.base}/about\n")
        r = run(["add", "--url-file", urlfile, "--no-render", "--vault", "t"],
                self.home)
        out = r.stdout + r.stderr
        # url-file 解析正确（about 被处理），且失败隔离
        self.assertIn("http://127.0.0.1", out)
        self.assertIn("ingest failed", out)
        self.assertIn("1 failed", out)

    def test_13_add_url_dedup(self):
        # 同一 URL 规范化后去重
        r = run(["add", "--url", f"{self.base}/page", "--url",
                 f"{self.base}/page#frag", "--no-render", "--vault", "t"],
                self.home)
        self.assertIn("duplicate", r.stdout)

    # ------------------------------------------------- doctor ----
    def test_14_doctor_web_section(self):
        r = run(["doctor", "--vault", "t"], self.home)
        self.assertIn("web ingestion", r.stdout)

    # ------------------------------------------------- 渲染判别 / 增强 ----
    def _require_chromium(self):
        if not W.chromium_available():
            self.skipTest("chromium not installed")

    def test_15_js_requires_render(self):
        # JS 页面：静态只见 INITIAL；渲染路径必须看到 JS 执行结果
        html, ok, _ = W.fetch_static(f"{self.base}/js")
        self.assertTrue(ok)
        self.assertIn("INITIAL", html)
        self.assertNotIn("JS-RAN-OK", html)
        self._require_chromium()
        rhtml, rpdf, source, _ = W.fetch_page(f"{self.base}/js")
        self.assertEqual(source, "render")
        self.assertIn("JS-RAN-OK", rhtml)
        self.assertTrue(rpdf and rpdf.startswith(b"%PDF-"))

    def test_16_render_cjk_pdf_text(self):
        # 中文页面走渲染双产物：PDF 落 inbox，且 PDF 文本可回读中文
        self._require_chromium()
        html, pdf, source, _ = W.fetch_page(f"{self.base}/zh")
        self.assertEqual(source, "render")
        import m_lib as L
        v = L.Vault("t")
        paths, snap, err = W.build_artifacts(f"{self.base}/zh", html, pdf,
                                             v, "zhreport")
        self.assertEqual(err, "")
        self.assertTrue(paths[0].endswith(".pdf"))
        import fitz
        with fitz.open(paths[0]) as doc:
            text = "".join(p.get_text() for p in doc)
        self.assertIn("年度报告", text)
        # 快照归档含原文且不进 inbox（不进索引）
        self.assertTrue(os.path.isfile(snap))
        self.assertNotIn("url-zhreport.html", os.listdir(v.inbox))

    def test_17_render_timeout_returns_note(self):
        # 不可达主机：渲染必须失败并返回可读 note（调用方降级静态）
        self._require_chromium()
        html, pdf, ok, note = W.render_page("http://127.0.0.1:1/x", timeout=5)
        self.assertFalse(ok)
        self.assertIsNone(html)
        self.assertTrue(note)

    def test_18_redirect_followed(self):
        html, ok, _ = W.fetch_static(f"{self.base}/redirect")
        self.assertTrue(ok)
        self.assertIn("Hello CENHUA", html)

    def test_19_fetch_unreachable(self):
        html, ok, note = W.fetch_static("http://127.0.0.1:1/nope")
        self.assertFalse(ok)
        self.assertIsNone(html)
        self.assertTrue(note)
        h, p, src, n2 = W.fetch_page("http://127.0.0.1:1/nope")
        self.assertIsNone(h)
        self.assertIsNone(src)
        self.assertTrue(n2)

    def test_20_robots_unreachable_fail_open(self):
        # 目标无 robots.txt/不可达 -> fail-open 允许（只 warn）
        allowed, reason = W.robots_allowed("http://127.0.0.1:1/x")
        self.assertTrue(allowed)
        self.assertIn("unreachable", reason)

    # ------------------------------------------------- CLI 边界 ----
    def test_21_add_url_eq_and_size_limit(self):
        # --url= 形式 + 5.3MB 页面 -> 截断提示 + 失败隔离。
        # 上限调小到 16KB：截断行为与 5MB 一致，但避免离线测试环境
        # 真的去转换 5MB HTML（引擎 insert_htmlbox 分钟级）。
        r = run(["add", f"--url={self.base}/big", "--no-render",
                 "--vault", "t"], self.home,
                env={"CENHUA_MAX_PAGE_BYTES": "16384"})
        out = r.stdout + r.stderr
        self.assertIn("truncated", out)
        self.assertIn("ingest failed", out)
        self.assertEqual(r.returncode, 1)

    def test_23_content_guard_rejects_empty_page(self):
        # JS 空壳页：静态无正文 -> 必须失败，绝不能"成功"后在 PDF 转换崩
        h, p, src, n = W.fetch_page(f"{self.base}/stub", use_render=False)
        self.assertIsNone(h)
        self.assertIsNone(src)
        self.assertIn("almost no static text", n)
        if W.chromium_available():
            h2, p2, src2, n2 = W.fetch_page(f"{self.base}/stub")
            self.assertIsNone(h2)
            self.assertIsNone(src2)
            self.assertTrue(n2)

    def test_24_toutiao_like_js_page_needs_render(self):
        # JS 壳页在允许渲染时必须走 render 并拿到足量正文（头条 m 站模式）
        self._require_chromium()
        html, pdf, source, note = W.fetch_page(f"{self.base}/js")
        self.assertEqual(source, "render", note)
        self.assertTrue(pdf and pdf.startswith(b"%PDF-"))
        _, text = W.extract_readable(html)
        self.assertGreaterEqual(len(text), W.MIN_CONTENT_CHARS)

    def test_22_cli_edge_cases(self):
        # 不可达 URL -> fetch failed, rc=1
        r = run(["add", "--url", "http://127.0.0.1:1/x", "--no-render",
                 "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 1)
        self.assertIn("fetch failed", r.stdout + r.stderr)
        # url-file 缺失 -> 明确报错，不崩
        r = run(["add", "--url-file", "/nonexistent/urls.txt", "--vault", "t"],
                self.home)
        self.assertIn("url-file not found", r.stdout + r.stderr)
        # watch --urls --once 空目录 -> 优雅退出 0
        r = run(["watch", "--urls", "--once", "--vault", "t"], self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # 文件 + 命令行同 URL（仅 fragment 不同）-> 规范化去重
        urlfile = os.path.join(self.home, "dupe.txt")
        with open(urlfile, "w", encoding="utf-8") as f:
            f.write(f"{self.base}/page\n")
        r = run(["add", "--url", f"{self.base}/page#frag", "--url-file", urlfile,
                 "--no-render", "--vault", "t"], self.home)
        self.assertIn("duplicate URL(s) removed", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
