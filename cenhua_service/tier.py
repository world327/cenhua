"""cenhua_service.tier — 三层 artifact 判定与引文穿透（M2b §7.3）。

防"引文洗白"：LLM 回答只能引用 primary 证据源；derived-doc（digest/draft/
周报/日报）默认不参与检索，显式 `--include-derived` 才开启，且引文沿
`derived_from` 链穿透到 primary 原件页码；internal-artifact（summaries/
relations 等派生产物）正文永不进引文，只可作 hint。

判定优先级（doc_tier）：
  1. 台账 ingest_manifest.json 显式 `tier` 字段（在三常量内）-> 直接用
  2. 名称特征 DERIVED_RE（digest/draft/周报/日报）-> derived-doc
  3. 无行/无特征 -> 保守 primary

service 纪律：不 print/exit（test_70）。
"""

import json
import os
import re

import m_lib as L  # noqa: E402
from cenhua_service import relations as REL  # noqa: E402

TIER_PRIMARY = "primary"
TIER_DERIVED = "derived-doc"
TIER_INTERNAL = "internal-artifact"

# 名称特征：digest/draft/周报/日报（文件名或路径段）
DERIVED_RE = re.compile(r"(?:^|[/_.-])(?:digest|draft|周报|日报)[_.\-]", re.I)

_TIERS = {TIER_PRIMARY, TIER_DERIVED, TIER_INTERNAL}


def classify(name, stored_as=""):
    """按名称特征判定 tier（无特征 -> primary，保守）。"""
    if DERIVED_RE.search(name or "") or DERIVED_RE.search(stored_as or ""):
        return TIER_DERIVED
    return TIER_PRIMARY


def ledger(vault):
    """台账 ingest_manifest.json（doc_id -> rec）。"""
    return L.read_json(os.path.join(vault.store, "ingest_manifest.json"), {}) or {}


def doc_tier(vault, doc_id, rec=None):
    """某文档的 tier。台账显式 tier 字段优先，其次名称判定，无行 -> primary。"""
    if rec is None:
        rec = ledger(vault).get(doc_id) or {}
    t = rec.get("tier")
    if t in _TIERS:
        return t
    return classify(rec.get("name", ""), rec.get("stored_as", ""))


def tier_of(vault, doc_id, rec=None):
    """带台账行复用的便捷封装。"""
    return doc_tier(vault, doc_id, rec)


def derived_from(vault, doc_id, _seen=None):
    """derived-doc 的 primary 来源链（list[doc_id]）。

    优先台账 `derived_from` 字段；退到 REL.related 边（type=cite 人工声明）。
    只收 primary 层；防环（_seen 去重）。
    """
    if _seen is None:
        _seen = set()
    if doc_id in _seen:
        return []
    _seen.add(doc_id)
    rec = ledger(vault).get(doc_id) or {}
    srcs = rec.get("derived_from") or []
    if isinstance(srcs, str):
        srcs = [srcs]
    out = []
    for s in srcs:
        if s in _seen:
            continue
        if doc_tier(vault, s) == TIER_PRIMARY:
            out.append(s)
        else:
            out.extend(derived_from(vault, s, _seen))
    if not out:
        # 退到人工关联边（type=cite）
        for e in REL.related(vault, doc_id):
            other = e["to"] if e["from"] == doc_id else e["from"]
            if e.get("type") == REL.TYPE_CITE and other not in _seen \
                    and doc_tier(vault, other) == TIER_PRIMARY:
                out.append(other)
    return out


def penetration(vault, doc_id, page):
    """引文穿透：把某文档某页的引文映射到可引用的 primary 证据。

    primary        -> 原样一条 [(doc_id, page)]
    internal       -> []（正文永不进引文）
    derived-doc    -> derived_from 链上每个 primary 各一条（page=None，由
                      LLM 在证据段里定位页码）
    无链           -> []
    """
    t = doc_tier(vault, doc_id)
    if t == TIER_PRIMARY:
        return [(doc_id, page)]
    if t == TIER_INTERNAL:
        return []
    srcs = derived_from(vault, doc_id)
    return [(s, None) for s in srcs]


def evidence_eligible(vault, doc_id):
    """是否可作为证据段（仅 primary）。"""
    return doc_tier(vault, doc_id) == TIER_PRIMARY


def sources_lines(vault, kw=""):
    """`cenhua sources` 三层分组渲染（M3a 任务 11）：来源可核查 + tier 归属。

    分组顺序 primary -> derived-doc -> internal-artifact；
    derived-doc 组每篇追加 derived_from 链（台账字段口径，不递归）。
    字段口径与 m_vault.sources 对齐（uploaded/from/archived/text layer）。
    """
    import m_lib as _L  # 延迟导入：与 CLI 层共用 resolve_docs 口径
    docs = _L.store_docs(vault)
    targets = _L.resolve_docs(vault, kw) or [
        (d, x.get("name", d)) for d, x in docs.items()]
    if not targets:
        return ["(no documents yet)"]
    led = ledger(vault)
    groups = {TIER_PRIMARY: [], TIER_DERIVED: [], TIER_INTERNAL: []}
    for doc_id, name in targets:
        groups[doc_tier(vault, doc_id, led.get(doc_id) or {})].append(
            (doc_id, name))
    lines = []
    for tier in (TIER_PRIMARY, TIER_DERIVED, TIER_INTERNAL):
        items = groups[tier]
        if not items:
            continue
        lines.append("")
        lines.append("--- %s (%d) ---" % (tier, len(items)))
        for doc_id, name in items:
            rec = led.get(doc_id) or {}
            stored = rec.get("stored_as", "")
            lines.append("%s  (%s)" % (name, doc_id))
            lines.append("  uploaded  : %s  sha1 %s" % (
                rec.get("ts", "?"), (rec.get("sha1", "?") or "?")[:16]))
            lines.append("  from      : %s" % rec.get("source", "?"))
            lines.append("  archived  : %s" % (
                stored if stored and os.path.exists(stored)
                else "MISSING — verify from the text layer"))
            lines.append("  text layer: %s" % os.path.join(
                vault.textdir, doc_id + ".txt"))
            if tier == TIER_DERIVED:
                srcs = rec.get("derived_from") or []
                lines.append("  derived   : %s" % (", ".join(srcs)
                                                   if srcs else "(无台账链)"))
    return lines


def record_tier(vault, doc_id):
    """摄取后补写台账 tier 字段（引擎字节级不动，test_61）。

    读台账 -> rec["tier"]=t -> tmp + os.replace 原子写回。永不抛。
    """
    try:
        path = os.path.join(vault.store, "ingest_manifest.json")
        man = L.read_json(path, {}) or {}
        rec = man.get(doc_id)
        if not rec:
            return
        t = doc_tier(vault, doc_id, rec)
        if rec.get("tier") == t:
            return
        rec["tier"] = t
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError:
        pass
