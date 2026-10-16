#!/usr/bin/env python3
"""m_web.py — CENHUA 网页收录（M2a，独立支线）。

把网页 URL 发给 CENHUA → Playwright 渲染 → 双产物（PDF + HTML 快照）→
走标准摄取闭环。**不含 §4.4**（F5 唯一归属 M1b）。

关键设计：
  * Playwright 渲染 JS 重页面；chromium 缺失/渲染失败时**自动降级静态 HTML
    抓取**（R3-T9 行为闭环）。
  * robots.txt 遵循爬虫礼仪（禁爬则拒绝）。
  * 同域名滑动窗口速率限制（避免压垮目标站）。
  * URL 规范化去重（去 fragment、统一 query 排序）。
  * 单页大小上限（防内存爆）。
  * 网页摄取失败独立进 inbox/.failed/，不阻塞本地文档摄取。

离线可测部分（robots/速率/URL 规范化/readability/大小上限）为纯函数；
渲染部分用 Playwright，chromium 缺失时优雅降级。
"""

import os
import re
import sys
import time
import urllib.parse
import urllib.robotparser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_lib as L  # noqa: E402

# 渲染超时硬上限（秒）
RENDER_TIMEOUT = 60
# 单页大小上限（字节），超过则截断；可用 CENHUA_MAX_PAGE_BYTES 覆盖
MAX_PAGE_BYTES = int(os.environ.get("CENHUA_MAX_PAGE_BYTES",
                                    5 * 1024 * 1024))  # 5 MB
# 同域名速率限制：每域名最小间隔（秒）
RATE_LIMIT_INTERVAL = 1.0

# 正文守卫：可提取文本少于该字符数视为失败（JS 空壳页 / 反爬验证页），
# 不产出垃圾 PDF。可用 CENHUA_MIN_CONTENT_CHARS 覆盖。
MIN_CONTENT_CHARS = int(os.environ.get("CENHUA_MIN_CONTENT_CHARS", "100"))

# 浏览器 UA：部分站点（如微信公众平台）对非浏览器 UA 直接返回"环境异常"
# 验证页而非正文，默认 bot UA 会拿到空内容。
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
# 速率限制滑动窗口（秒）
RATE_WINDOW = 10.0

# 注入 CJK 字体，防中文乱码
CJK_FONT_CSS = """
@font-face {
  font-family: 'CJK-Fallback';
  src: local('Noto Sans CJK SC'), local('WenQuanYi Micro Hei'),
       local('PingFang SC'), local('Microsoft YaHei');
  unicode-range: U+4E00-9FFF, U+3000-303F, U+FF00-FFEF;
}
body, p, div, span, h1, h2, h3, li, td, th {
  font-family: 'CJK-Fallback', sans-serif;
}
"""


# ------------------------------------------------------------ URL 规范化 ----
def normalize_url(url):
    """URL 规范化：去 fragment、统一 query 排序、小写 scheme/host。

    返回规范化 URL 字符串。用于去重。
    """
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip()
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    # 去 fragment
    path = parts.path or "/"
    # 统一 query 排序（去重时顺序无关）
    query = parts.query
    if query:
        pairs = sorted(query.split("&"))
        query = "&".join(pairs)
    return urllib.parse.urlunsplit((scheme, host, path, query, ""))


def same_url(a, b):
    """两个 URL 规范化后是否相同（用于去重）。"""
    return normalize_url(a) == normalize_url(b)


# ------------------------------------------------------------ robots.txt ----
def robots_allowed(url, user_agent=None):
    """检查 robots.txt 是否允许抓取该 URL。

    返回 (allowed, reason)。robots.txt 不可达时默认允许（fail-open 抓取，
    但速率限制仍生效）；明确 Disallow 则拒绝。
    """
    user_agent = user_agent or f"cenhua/{L.VERSION}"
    try:
        parts = urllib.parse.urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        rp.read()
        if not rp.can_fetch(user_agent, url):
            return False, f"robots.txt disallows {url}"
        return True, ""
    except Exception as e:
        # robots.txt 不可达：默认允许（不因 robots 故障阻塞抓取）
        return True, f"robots.txt unreachable ({type(e).__name__}) — allowed"


# ------------------------------------------------------------ 速率限制 ----
class RateLimiter:
    """同域名滑动窗口速率限制。"""

    def __init__(self, interval=RATE_LIMIT_INTERVAL, window=RATE_WINDOW):
        self.interval = interval
        self.window = window
        self._hits = {}  # domain -> [timestamps]

    def _domain(self, url):
        try:
            return urllib.parse.urlsplit(url).netloc
        except ValueError:
            return url

    def allow(self, url, now=None):
        """是否允许抓取该 URL。允许则记录本次访问。"""
        now = now if now is not None else time.time()
        domain = self._domain(url)
        ts = self._hits.setdefault(domain, [])
        # 清理窗口外的记录
        ts[:] = [t for t in ts if now - t < self.window]
        if ts and now - ts[-1] < self.interval:
            return False
        ts.append(now)
        return True

    def wait_seconds(self, url, now=None):
        """距下次允许还需等待的秒数（0 = 立即可抓）。"""
        now = now if now is not None else time.time()
        domain = self._domain(url)
        ts = self._hits.get(domain, [])
        if not ts:
            return 0.0
        return max(0.0, self.interval - (now - ts[-1]))


# ------------------------------------------------------------ 大小上限 ----
def enforce_size_limit(html, max_bytes=MAX_PAGE_BYTES):
    """单页大小上限：超过则只取前 N 字节（截断到标签边界）。

    返回 (truncated_html, truncated: bool)。
    """
    if len(html) <= max_bytes:
        return html, False
    # 截断到最近的闭合标签，避免半截标签
    cut = html[:max_bytes]
    last_close = cut.rfind(">")
    if last_close > 0:
        cut = cut[:last_close + 1]
    return cut, True


# ------------------------------------------------------------ readability ----
def extract_readable(html):
    """用 readability 库提正文（去广告/导航/页脚）。

    返回 (title, main_text)。readability 不可用时降级为 <article>/<main>/
    <body> 文本提取。
    """
    title = _extract_title(html)
    try:
        from readability import Document
        doc = Document(html)
        main = doc.summary(html_partial=True)
        text = _html_to_text(main)
        if text.strip():
            return title, text
    except Exception:
        pass
    # 降级：取 <article>/<main>/<body> 文本
    text = _fallback_text(html)
    return title, text


def _extract_title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def _html_to_text(html):
    """粗略 HTML -> 文本（去标签、去脚本/样式、折叠空白）。"""
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html,
                  flags=re.I | re.S)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _fallback_text(html):
    """降级正文提取：优先 <article>/<main>，否则 <body>。"""
    for tag in ("article", "main"):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.I | re.S)
        if m:
            text = _html_to_text(m.group(1))
            if text.strip():
                return text
    m = re.search(r"<body[^>]*>(.*?)</body>", html, re.I | re.S)
    if m:
        return _html_to_text(m.group(1))
    return _html_to_text(html)


# ------------------------------------------------------------ 渲染 ----
def build_clean_html(title, text, url):
    """把提取出的正文重排成极简 HTML（供 PDF 排版）。

    为什么不用整页 PDF：信息流站点（头条 m 站等）整页渲染会把导航、
    推荐流、评论、播放列表全部排进 PDF——实测正文被淹没、页首是
    "首页 反馈 下载 扫码下载"。正文进 PDF（干净、检索质量高），
    整页留在 HTML 快照里溯源（roadmap §4.3）。
    """
    import html as _html
    body = _html.escape(text or "")
    head = _html.escape(title or "")
    src = _html.escape(url or "")
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "body{font-family:'Noto Sans CJK SC','WenQuanYi Zen Hei',"
        "'Microsoft YaHei',sans-serif;max-width:46em;margin:0 auto;"
        "padding:1.2em;line-height:1.7;font-size:11pt;color:#111}"
        "h1{font-size:16pt;line-height:1.4;margin:0 0 .4em}"
        ".src{color:#666;font-size:9pt;word-break:break-all;margin:0 0 1.2em;"
        "padding-bottom:.8em;border-bottom:1px solid #ddd}"
        "pre{white-space:pre-wrap;word-break:break-word;font:inherit;"
        "margin:0}</style></head><body>"
        f"<h1>{head}</h1><p class='src'>来源：{src}</p>"
        f"<pre>{body}</pre></body></html>")


def chromium_available():
    """chromium 是否已安装（可执行文件存在）。"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return os.path.exists(p.chromium.executable_path)
    except Exception:
        return False


def render_page(url, timeout=RENDER_TIMEOUT):
    """Playwright 无头渲染页面。

    返回 (html, pdf_bytes, ok, note)：
      * html: 渲染后的完整 HTML（含 JS 执行结果，进快照溯源）
      * pdf_bytes: **正文重排 PDF**（readability 提取正文后重新排版，
        导航/推荐流/评论不进 PDF；提取失败降级整页 PDF）
      * ok: 是否成功
      * note: 失败原因 / 降级说明

    chromium 缺失或渲染失败时 ok=False（调用方降级静态抓取）。
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                # 浏览器语境（UA/语言/视口）：部分站点按 UA 判定 bot 返回验证页
                ctx = browser.new_context(user_agent=BROWSER_UA,
                                          locale="zh-CN",
                                          viewport={"width": 1280,
                                                    "height": 900})
                page = ctx.new_page()
                # domcontentloaded 而非 networkidle：信息流站点埋点/长连接
                # 让网络永不空闲，networkidle 必然拖到超时（实测头条 60s 超时）
                page.goto(url, wait_until="domcontentloaded",
                          timeout=timeout * 1000)
                # DOM 就绪后等 JS 动态渲染 + 注入 CJK 字体防乱码
                # （样式必须在 goto 之后注入，否则导航会丢弃）
                page.wait_for_timeout(2000)
                page.add_style_tag(content=CJK_FONT_CSS)
                page.wait_for_timeout(300)
                html = page.content()
                # 正文重排 PDF：提取正文成功 -> 干净排版；失败 -> 整页兜底
                title, text = extract_readable(html)
                if text and len(text) >= MIN_CONTENT_CHARS:
                    page2 = ctx.new_page()
                    page2.set_content(build_clean_html(title, text, url),
                                      wait_until="load")
                    pdf = page2.pdf(format="A4")
                    page2.close()
                else:
                    pdf = page.pdf(format="A4", print_background=True)
                return html, pdf, True, ""
            finally:
                browser.close()
    except Exception as e:
        note = f"{type(e).__name__}: {str(e)[:120]}".replace("\n", " ")
        return None, None, False, note


def fetch_static(url, timeout=30):
    """静态 HTML 抓取（降级路径，R3-T9）。

    返回 (html, ok, note)。不执行 JS。
    """
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read(MAX_PAGE_BYTES + 1024).decode("utf-8", "replace")
        return html, True, ""
    except Exception as e:
        return None, False, f"{type(e).__name__}: {str(e)[:120]}"


def _content_chars(html):
    """可提取正文字符数（守卫用）。解析失败按 0 计。"""
    try:
        _, text = extract_readable(html)
        return len(text or "")
    except Exception:
        return 0


def fetch_page(url, use_render=True):
    """抓取网页，返回 (html, pdf_bytes, source, note)。

    source: 'render'（Playwright 渲染）| 'static'（静态降级）| None（失败）

    正文守卫：两条路径都要过 `MIN_CONTENT_CHARS` 门槛，否则视为失败。
    否则 JS 空壳页/反爬验证页会"抓取成功"，再在 PDF 转换时以
    "layout integrity check failed: PDF has 0 chars" 崩掉，用户拿不到
    可读提示（实测头条 m 站静态 HTML 可见文本为 0）。
    """
    def usable(html):
        return html is not None and _content_chars(html) >= MIN_CONTENT_CHARS

    if use_render and chromium_available():
        html, pdf, ok, note = render_page(url)
        if ok and usable(html):
            return html, pdf, "render", ""
        rnote = note or (f"rendered page has almost no text "
                         f"(<{MIN_CONTENT_CHARS} chars; JS wall or anti-bot page)")
        # 渲染失败/空壳 -> 降级静态
        shtml, sok, snote = fetch_static(url)
        if sok and usable(shtml):
            return shtml, None, "static", f"render failed ({rnote}); used static"
        return None, None, None, (
            f"render failed ({rnote}); static unusable too "
            f"({snote or 'almost no text: page needs JS or blocked us'})")
    # 无 chromium 或禁用渲染 -> 静态
    shtml, sok, snote = fetch_static(url)
    if sok and usable(shtml):
        return shtml, None, "static", ""
    if sok:
        return None, None, None, (
            f"page has almost no static text (<{MIN_CONTENT_CHARS} chars) "
            "and no chromium to render it — install: cenhua setup")
    return None, None, None, snote


# ------------------------------------------------------------ 双产物 ----
def build_artifacts(url, html, pdf_bytes, vault, name):
    """生成双产物。返回 (ingest_paths, snapshot_path, note)。

    * PDF（若有）写入 vault 根 inbox —— 走标准摄取闭环（成功进
      .processed/、失败进 .failed/ 的暂存语义生效），是**进索引的产物**；
    * HTML 快照归档到 <vault>/works/snapshots/<name>.html —— **溯源用，
      不进索引**（roadmap §4.3：快照与 PDF 内容重复，索引它只会污染检索），
      同时写同名 .meta.json 记录 URL/时间，便于溯源回链；
    * 无 PDF 时（静态降级）HTML 直接进 inbox 参与索引，保证内容不丢。

    失败返回 ([], None, reason)。
    """
    inbox = os.path.abspath(vault.inbox)
    os.makedirs(inbox, exist_ok=True)
    try:
        if pdf_bytes:
            pdf_path = os.path.join(inbox, f"url-{name}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
            snapshot = _write_snapshot(vault, url, name, html)
            return [pdf_path], snapshot, ""
        # 无 PDF（静态降级）：HTML 进 inbox 参与索引，同时留快照
        html_path = os.path.join(inbox, f"url-{name}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        snapshot = _write_snapshot(vault, url, name, html)
        return [html_path], snapshot, ""
    except OSError as e:
        return [], None, f"cannot write artifacts: {e}"


def _write_snapshot(vault, url, name, html):
    """HTML 快照归档 + 溯源元信息。返回快照路径。"""
    snap_dir = os.path.join(vault.works, "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    snap = os.path.join(snap_dir, f"url-{name}.html")
    with open(snap, "w", encoding="utf-8") as f:
        f.write(html)
    import json as _json
    meta = {"url": url, "ts": time.strftime("%F %T"), "snapshot": snap}
    with open(os.path.join(snap_dir, f"url-{name}.meta.json"), "w",
              encoding="utf-8") as f:
        _json.dump(meta, f, ensure_ascii=False, indent=1)
    return snap


def slugify_url(url, max_len=60):
    """从 URL 生成文件名 slug（去 scheme/query，保留路径关键词）。"""
    try:
        parts = urllib.parse.urlsplit(url)
        path = parts.path.strip("/")
        if not path:
            path = parts.netloc
        # 取路径最后一段，去扩展名
        seg = path.split("/")[-1]
        seg = re.sub(r"\.[a-z0-9]+$", "", seg, flags=re.I)
        seg = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "_", seg)
        seg = seg.strip("_") or "page"
        return seg[:max_len]
    except Exception:
        return "page"
