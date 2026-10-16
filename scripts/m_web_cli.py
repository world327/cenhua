#!/usr/bin/env python3
"""m_web_cli.py — CENHUA 网页收录 CLI（M2a）。

用户命令（可 print）：
  * `cenhua add --url <url> [--url ...]`：抓取并摄取网页
  * `cenhua add --url-file <path>`：从文件读 URL 列表
  * `cenhua watch` 监听 `inbox/urls/*.url` 文件

流程：robots 检查 → 速率限制 → 渲染/静态抓取 → 双产物 → 走标准摄取闭环。
失败独立进 inbox/.failed/，不阻塞本地文档摄取。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_lib as L  # noqa: E402
import m_web  # noqa: E402
import m_ingest  # noqa: E402


def _read_url_file(path):
    """从文件读 URL 列表（每行一个，忽略空行/注释）。"""
    urls = []
    if not os.path.isfile(path):
        L.err(f"! url-file not found: {path}")
        return urls
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def _ingest_artifacts(vault, paths):
    """把进索引的产物交给标准摄取闭环。返回 'added' | 'failed' | 'dupe'。"""
    added = failed = 0
    for p in paths:
        # 走既有 ingest_one()：sha1 去重、成功进 .processed/、失败进 .failed/
        result = m_ingest.ingest_one(vault, p, quiet=True)
        if result == "added":
            added += 1
        elif result == "failed":
            failed += 1
    if added:
        try:
            rc, _ = L.run_engine("pi_flatten.py", [], vault, capture=True)
            if rc != 0:
                L.err("! flatten reported a problem — run: cenhua flatten")
        except SystemExit:
            L.err("! flatten failed (engine unavailable?) — run: cenhua flatten")
        return "added"
    return "failed" if failed else "dupe"


def ingest_url(vault, url, use_render=True, limiter=None, force=False):
    """抓取并摄取单个 URL。返回 'added' | 'dupe' | 'failed'。

    force=True 跳过 robots.txt 检查（用户显式覆盖，打印一次告警）。
    """
    # robots.txt 检查
    allowed, reason = m_web.robots_allowed(url)
    if not allowed:
        if not force:
            L.err(f"! {url}: {reason}")
            L.err("  (if you own/independently verified this source: add --force)")
            return "failed"
        L.say(f"~ {url}: robots.txt disallows crawling, "
              f"proceeding because of --force")
    # 速率限制
    if limiter is not None:
        wait = limiter.wait_seconds(url)
        if wait > 0:
            time.sleep(wait)
        if not limiter.allow(url):
            L.err(f"! {url}: rate limited (same domain)")
            return "failed"

    # 抓取
    html, pdf, source, note = m_web.fetch_page(url, use_render=use_render)
    if html is None:
        L.err(f"! {url}: fetch failed ({note})")
        return "failed"
    if note:
        L.say(f"~ {url}: {note}")

    # 大小上限
    html, truncated = m_web.enforce_size_limit(html)
    if truncated:
        L.say(f"~ {url}: page exceeded size limit, truncated")

    # 双产物：PDF 进索引，HTML 快照归档 works/snapshots/
    name = m_web.slugify_url(url)
    paths, snapshot, err = m_web.build_artifacts(url, html, pdf, vault, name)
    if not paths:
        L.err(f"! {url}: {err}")
        return "failed"
    if snapshot:
        L.say(f"  snapshot -> {snapshot}")

    # 走标准摄取闭环
    result = _ingest_artifacts(vault, paths)
    if result == "added":
        L.say(f"+ {url} -> ingested ({source})")
    elif result == "dupe":
        L.say(f"= {url}: already in vault")
    else:
        L.err(f"x {url}: ingest failed (artifact kept in inbox/.failed/)")
    return result


def add_urls(vault, urls, use_render=True, force=False):
    """批量摄取 URL 列表。返回 rc（有失败=1，同 m_ingest.add 语义）。"""
    if not urls:
        L.say("= no URLs to ingest")
        return 0
    limiter = m_web.RateLimiter()
    counts = {"added": 0, "dupe": 0, "failed": 0}
    for url in urls:
        counts[ingest_url(vault, url, use_render=use_render, limiter=limiter,
                          force=force)] += 1
    L.say(f"\ndone: +{counts['added']} new, = {counts['dupe']} dupes, "
          f"x{counts['failed']} failed")
    if counts["added"]:
        L.say("next: cenhua find <keyword>")
    return 1 if counts["failed"] else 0


def add_url_cmd(vault, urls, url_file=None, use_render=True, force=False):
    """cenhua add --url <url>... [--url-file <path>] [--force]。返回 rc。"""
    all_urls = list(urls)
    if url_file:
        all_urls += _read_url_file(url_file)
    # URL 规范化去重
    seen, deduped = set(), []
    for u in all_urls:
        norm = m_web.normalize_url(u)
        if norm not in seen:
            seen.add(norm)
            deduped.append(u)
    if len(deduped) < len(all_urls):
        L.say(f"~ {len(all_urls) - len(deduped)} duplicate URL(s) removed")
    return add_urls(vault, deduped, use_render=use_render, force=force)


def watch_urls(vault, interval=5.0, once=False, force=False):
    """监听 inbox/urls/*.url 文件，抓取并摄取。"""
    urls_dir = os.path.join(vault.inbox, "urls")
    os.makedirs(urls_dir, exist_ok=True)
    L.say(f"watching {urls_dir}/*.url every {interval:.0f}s (Ctrl-C to stop)")
    seen = set()
    while True:
        found = []
        for fn in os.listdir(urls_dir):
            if not fn.endswith(".url"):
                continue
            path = os.path.join(urls_dir, fn)
            if path in seen:
                continue
            seen.add(path)
            with open(path, encoding="utf-8") as f:
                url = f.read().strip()
            if url:
                found.append(url)
            # 处理完删除 .url 文件
            try:
                os.remove(path)
            except OSError:
                pass
        if found:
            add_urls(vault, found, force=force)
        if once:
            break
        time.sleep(interval)
    return 0
