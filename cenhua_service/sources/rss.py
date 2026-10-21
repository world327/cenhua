# -*- coding: utf-8 -*-
"""cenhua_service.sources.rss — RSS/Atom 订阅适配器（M5-4）。

feedparser 必需依赖（pip install feedparser）。增量策略：
- 用 guid / link / title 三字段 hash 作为条目唯一键
- sources_state.json 存每源 last_seen（已见条目 hash set），下次只拉增量
- 条目内容写 HTML 片段 → inbox（.html 扩展名），走 core.ingest 既 dedupe
  又 flatten 文本层

配置（meta/sources.yaml）：
  sources:
    - type: rss
      name: tech-blogs
      url: https://example.com/blog/feed.xml
      interval_s: 3600         # 建议轮询间隔（CLI cron 控制）
      user_agent: cenhua/0.7   # 可选
      timeout_s: 20            # 可选，默认 15
      max_items: 50            # 可选，单次最多处理条数（防爆）

service 纪律：零 print / 零 exit。
"""
from __future__ import annotations

import hashlib
import time
import urllib.request

from cenhua_service.sources import Source, SourceResult, register, _REGISTRY, \
    load_state, save_state


@register
class RssSource(Source):
    _type = "rss"

    def fetch(self, vault, cfg: dict) -> SourceResult:
        import feedparser  # 必需依赖，入口已确认
        url = (cfg.get("url") or "").strip()
        if not url:
            return SourceResult(rc=1, error="url 必需")
        name = cfg.get("name") or "rss-" + self._hash_url(url)[:6]
        timeout = int(cfg.get("timeout_s") or 15)
        ua = cfg.get("user_agent") or "cenhua/0.7"
        max_items = int(cfg.get("max_items") or 50)

        # 1) 拉 feed
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": ua,
                               "Accept": "application/rss+xml, application/atom+xml"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except Exception as exc:
            vault.log("sources", ["%s RSS 拉取失败: %s" % (name,
                                                            type(exc).__name__)])
            return SourceResult(source=name, source_type="rss", rc=1,
                                error=str(exc))

        feed = feedparser.parse(raw)
        if getattr(feed, "bozo", 1) and not feed.entries:
            vault.log("sources", ["%s RSS 解析失败: %s" % (name,
                                                           feed.bozo_exception)])
            return SourceResult(source=name, source_type="rss", rc=1,
                                error=str(feed.bozo_exception or "parse failed"))

        # 2) 增量：对比 sources_state.json 里 last_seen
        state = load_state(vault)
        st = state.setdefault(name, {"last_seen": [], "last_success": 0,
                                      "last_error": None})
        seen_keys = set(st.get("last_seen") or [])

        added = dupe = failed = 0
        lines = []
        new_keys = list(seen_keys)               # 保留旧 key，避免 state 膨胀
        new_keys_set = set(new_keys)

        for entry in feed.entries[:max_items]:
            key = self._entry_key(entry)
            if key in seen_keys:
                dupe += 1
                continue
            # 构造 HTML 片段 → inbox
            try:
                html = self._entry_to_html(entry, name)
                fname = self._entry_fname(entry, name) + ".html"
                dest = self._append_to_inbox(vault, fname, html.encode("utf-8"))
                # 直接触发 ingest（复用 dedupe + flatten）
                from cenhua_service import core
                res = core.ingest(vault, dest)
                if res.status == "added":
                    added += 1
                elif res.status == "dupe":
                    dupe += 1
                else:
                    failed += 1
                if key not in new_keys_set:
                    new_keys.append(key); new_keys_set.add(key)
                lines.append("+ %s %s" % (res.status, fname))
            except Exception as exc:
                failed += 1
                lines.append("! %s: %s" % (fname, type(exc).__name__))

        # 3) 更新 state（last_seen 保留最近 200 条 key）
        st["last_seen"] = new_keys[-200:]
        st["last_success"] = int(time.time())
        st["last_error"] = None
        state[name] = st
        save_state(vault, state)

        vault.log("sources", ["%s RSS: added=%d dupe=%d failed=%d"
                               % (name, added, dupe, failed)])
        return SourceResult(source=name, source_type="rss", rc=0,
                            added=added, dupe=dupe, failed=failed, lines=lines)

    # --- 内部工具 ---
    @staticmethod
    def _entry_key(entry) -> str:
        """条目唯一键：guid > link > title，hash 后存。"""
        raw = entry.get("id") or entry.get("link") or entry.get("title") or ""
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _entry_fname(entry, src_name: str) -> str:
        """条目文件名：标题安全化 + 截断，无日期间隔（source_state 已去重）。"""
        title = entry.get("title") or "untitled"
        safe = Source._sanitize_filename(title, max_len=80)
        return "%s-%s" % (src_name[:20], safe)

    @staticmethod
    def _entry_to_html(entry, src_name: str) -> str:
        """RSS 条目 → 受限 HTML 片段（消毒 script/on* 属性）。"""
        import re
        title = entry.get("title") or "(无标题)"
        link = entry.get("link") or ""
        pub = entry.get("published") or entry.get("updated") or ""
        content = (entry.get("content") or [{}])[0].get("value") or \
                  entry.get("summary") or entry.get("description") or ""
        # 消毒
        content = re.sub(r"(?is)<script.*?</script>", "", content)
        content = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)",
                         "", content)
        return ("<!DOCTYPE html>\n<html lang=\"zh\">\n<head>\n"
                "<meta charset=\"utf-8\">\n<title>%s</title>\n"
                "<style>body{font-family:system-ui,sans-serif;"
                "max-width:800px;margin:2em auto;padding:0 1em;line-height:1.6}"
                "blockquote{border-left:3px solid #bbb;padding-left:1em;color:#555}"
                "a{color:#2563eb}</style>\n</head>\n<body>\n"
                "<h1>%s</h1>\n"
                "<p class='muted'>来源：%s · %s</p>\n"
                "<p><a href='%s' target='_blank'>原文链接</a></p>\n"
                "%s\n</body>\n</html>\n"
                % (title, title, src_name, pub, link, content))

    @staticmethod
    def _hash_url(url: str) -> str:
        return hashlib.sha1(url.encode("utf-8")).hexdigest()


# 强制触发注册（_REGISTRY.register 装饰器在类体执行时注册）
assert RssSource._type in _REGISTRY, "RssSource failed to register"
