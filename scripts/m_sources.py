#!/usr/bin/env python3
"""m_sources.py — 多源摄取 CLI（M5-4）。

USAGE
  cenhua pulls [--source NAME] [--force]    同步全部/指定源（cron 入口）
  cenhua pulls --list                        列出 sources.yaml 配置
  cenhua pulls --state                       打印每源状态
  cenhua pulls --dry-run                     只拉不取入

service 纪律：零 print / 零 exit。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import m_lib as L  # noqa: E402


def _have_yaml():
    try:
        import yaml  # noqa: F401
        return True
    except ImportError:
        return False


def _list_sources(vault):
    from cenhua_service.sources import parse_sources, list_source_types, \
        load_state
    sources = parse_sources(vault)
    state = load_state(vault)
    if not sources:
        L.say("无配置源（meta/sources.yaml 缺失或为空）")
        L.say("可用类型: " + ", ".join(list_source_types()))
        return 0
    L.say("共 %d 个配置源：" % len(sources))
    for i, s in enumerate(sources, 1):
        name = s.get("name", "?")
        st = state.get(name, {})
        last = st.get("last_success") or "-"
        last = time.strftime("%F %T", time.localtime(last)) \
            if isinstance(last, int) else last
        L.say("  %d. [%-7s] %s  url=%s  last=%s" % (
            i, s.get("type", "?"), name,
            (s.get("url") or s.get("path") or "-")[:50], last))
    return 0


def _state_sources(vault):
    from cenhua_service.sources import load_state
    state = load_state(vault)
    if not state:
        L.say("sources_state.json 空")
        return 0
    L.say("=== sources_state ===")
    for name, st in sorted(state.items()):
        last = st.get("last_success") or 0
        last = time.strftime("%F %T", time.localtime(last)) if last else "-"
        seen = len(st.get("last_seen") or [])
        err = st.get("last_error") or ""
        L.say("  %-24s seen=%-4d last=%s  %s" % (name, seen, last, err))
    return 0


def _sync_sources(vault, source_filter="", force=False):
    if not _have_yaml():
        L.err("! 需要 PyYAML：pip install pyyaml")
        return 1
    from cenhua_service.sources import parse_sources, get_source_type
    sources = parse_sources(vault)
    if not sources:
        L.say("无配置源（meta/sources.yaml）")
        return 0
    if source_filter:
        sources = [s for s in sources
                   if s.get("name") == source_filter
                   or s.get("path") == source_filter]
        if not sources:
            L.err("! 未找到源: %s" % source_filter); return 1

    total_added = total_dupe = total_failed = 0
    for s in sources:
        stype = s.get("type", "")
        name = s.get("name") or stype
        cls = get_source_type(stype)
        if cls is None:
            L.err("! %s: 未注册类型 %s" % (name, stype)); continue
        try:
            L.say("→ %s [%s]" % (name, stype))
            res = cls().fetch(vault, s)
            for ln in res.lines:
                L.say("  " + ln)
            if res.rc == 0:
                L.say("  ↳ added=%d dupe=%d failed=%d" %
                      (res.added, res.dupe, res.failed))
                total_added += res.added
                total_dupe += res.dupe
                total_failed += res.failed
            else:
                L.err("  ! 失败: %s" % res.error)
        except Exception as exc:
            vault.log("sources", ["%s %s" % (name, type(exc).__name__)])
            L.err("  ! 异常: %s" % type(exc).__name__)
            if force: continue
    L.say("总计: added=%d dupe=%d failed=%d" %
          (total_added, total_dupe, total_failed))
    return 0


def flow(vault, rest):
    ap = argparse.ArgumentParser(prog="cenhua pulls",
                                 description=__doc__.split("USAGE")[0].strip())
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--state", action="store_true")
    ap.add_argument("--source", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(rest)
    if args.list: return _list_sources(vault)
    if args.state: return _state_sources(vault)
    return _sync_sources(vault, source_filter=args.source,
                         force=args.force)
