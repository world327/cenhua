"""cenhua_service.query — `cenhua query` 四段编排核心（M2b）。

四段输出（roadmap §6.3）：
  ① 直接命中（find，精确 W_EXACT=1.0）
  ② 总结延展（ask，hint 两段式 prompt + 证据段，LLM）
  ③ 内容出处（citations + snippet 强制校验，F2）
  ④ 关联推荐（related，Top-2 文档的关联边）

三路融合（M2b-2）：find（精确）+ seek（语义 W_SEMANTIC=0.6）+ ask，fuse()
按置信度排序去重。

检索默认降级（M2b-3）：默认仅 primary 层；`--include-derived` 显式开启
derived-doc，命中显 ⚠derived；internal-artifact 永不参与检索。

引文穿透（M2b-4）：derived 引文沿 derived_from 链穿透到 primary 原件页码。

成本护栏（M2b-7）：dry-run 金额预估 + CENHUA_MAX_COST_CNY 预算闸（env >
vault.yaml max_cost > 2.0 保守默认）。

service 纪律：不 print/exit（test_70）；parse_args/_int_opt 下沉本模块
（test_71 白名单 M2b = query_cmd）。
"""

import os
import re
import time

import m_lib as L  # noqa: E402
from cenhua_service import prompt as P  # noqa: E402
from cenhua_service import tier as T  # noqa: E402

W_EXACT = 1.0
W_SEMANTIC = 0.6
MAX_DOCS = 3
MAX_PAGES_PER_DOC = 2
MAX_PAGE_CHARS = 1600

# 停用词（CJK 词项与拉丁词项共用）
STOP_TERMS = {
    "的", "了", "是", "在", "和", "与", "或", "及", "对于", "如何", "什么",
    "哪些", "多少", "请问", "告诉", "一下", "吗", "呢",
    "the", "and", "for", "with", "what", "how", "does", "what's",
}

_LATIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{1,}")


def terms_from_question(q):
    """问题 -> 检索词项。

    拉丁词：>=2 字符整串入项；CJK：<=4 字整串入项，>4 字滑窗 2-gram 去重；
    停用词过滤；空 -> [q.strip()]。
    """
    terms = []
    for m in _LATIN.findall(q):
        if len(m) >= 2 and m.lower() not in STOP_TERMS:
            terms.append(m)
    cjk = re.findall(r"[\u4e00-\u9fff]+", q)
    for seg in cjk:
        if len(seg) <= 4:
            if seg not in STOP_TERMS:
                terms.append(seg)
        else:
            for i in range(len(seg) - 1):
                g = seg[i:i + 2]
                if g not in STOP_TERMS:
                    terms.append(g)
    # 去重保序
    seen, out = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out or [q.strip()]


def find_hits(vault, terms, include_derived=False):
    """精确检索（find 层）。逐 .txt 扫，PAGE_RE 记页。

    返回 [{"doc","name","page","line","term","tier","derived_from"}]。
    internal-artifact 跳过；derived-doc 非 include_derived 跳过。
    """
    docs = L.store_docs(vault)
    hits = []
    for doc_id, meta in docs.items():
        t = T.doc_tier(vault, doc_id)
        if t == T.TIER_INTERNAL:
            continue
        if t == T.TIER_DERIVED and not include_derived:
            continue
        path = os.path.join(vault.textdir, f"{doc_id}.txt")
        if not os.path.isfile(path):
            continue
        page = "?"
        try:
            fh = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                m = L.PAGE_RE.match(line.strip())
                if m:
                    page = m.group(1) or m.group(2)
                    continue
                low = line.lower()
                for term in terms:
                    if term.lower() in low:
                        hits.append({
                            "doc": doc_id, "name": meta.get("name", doc_id),
                            "page": page, "line": line.strip()[:200],
                            "term": term, "tier": t,
                            "derived_from": T.derived_from(vault, doc_id)
                            if t == T.TIER_DERIVED else [],
                        })
                        break
    return hits


def semantic_hits(vault, question, top=6):
    """语义检索（seek 层）。embedding 缺失/异常 -> []（降级不崩）。"""
    try:
        import m_vectors as V
        base, key, model = V.embed_config(vault)
        if not (base and model):
            return []
        chunks, mat = V.load_index(vault)
        if not chunks:
            return []
        import numpy as np
        qv = np.array(V.normalize(V.embed_texts([question], base, key, model)[0]),
                      dtype="float32")
        sims = mat @ qv
        order = sims.argsort()[::-1][:top]
        out = []
        for i in order:
            c = chunks[int(i)]
            out.append({"doc": c["doc"], "page": c["page"], "sim": float(sims[i]),
                        "text": c["text"][:200]})
        return out
    except Exception:
        return []


def fuse(find_hits_, seek_hits_):
    """三路融合：按 doc 聚合，精确 + 语义加权，置信度降序去重。

    返回 [{"doc","name","score","tier","derived_from","sim","terms"}]。
    """
    agg = {}
    for h in find_hits_:
        a = agg.setdefault(h["doc"], {"doc": h["doc"], "name": h["name"],
                                      "score": 0.0, "tier": h["tier"],
                                      "derived_from": h["derived_from"],
                                      "sim": None, "terms": []})
        a["score"] += W_EXACT * max(1, len(h["term"]))
        if h["term"] not in a["terms"]:
            a["terms"].append(h["term"])
    for s in seek_hits_:
        a = agg.setdefault(s["doc"], {"doc": s["doc"], "name": "",
                                      "score": 0.0, "tier": None,
                                      "derived_from": [], "sim": None,
                                      "terms": []})
        a["score"] += W_SEMANTIC * s["sim"] * 10
        a["sim"] = max(a["sim"] or 0, s["sim"])
    ranked = sorted(agg.values(), key=lambda a: -a["score"])
    return ranked


def evidence_for(vault, doc_ids):
    """证据段：每 doc 前 MAX_PAGES_PER_DOC 页，text[:MAX_PAGE_CHARS]。

    返回 [(doc_id, name, page, text)]。
    """
    docs = L.store_docs(vault)
    segs = []
    for did in doc_ids:
        pages = L.text_pages(vault, did)
        for pno, text in pages[:MAX_PAGES_PER_DOC]:
            segs.append((did, docs.get(did, {}).get("name", did),
                         pno, text[:MAX_PAGE_CHARS]))
    return segs


def estimate(vault, prompt_text, calls=1):
    """按 prompt 文本估价（委托 cost 层）。"""
    from cenhua_service import cost as C
    tin = C.estimate_tokens(prompt_text)
    tout = 1400
    model = os.environ.get("PI_MODEL", "openai/gpt-4o-mini")
    est, currency, priced, note = C.estimate_cost(model, tin, tout)
    return {"calls": calls, "tokens_in": tin, "tokens_out": tout,
            "est_cost": est, "currency": currency, "priced": priced,
            "note": note, "model": model}


def max_cost_cny(vault):
    """预算上限（CNY）。env > vault.yaml max_cost > 2.0 保守默认。"""
    from cenhua_service import cost as C
    return C.max_cost_cny(vault)


def cost_gate(vault, est, force=False):
    """预算闸（委托 cost 层）。返回 (ok, message)。"""
    from cenhua_service import cost as C
    return C.cost_gate(vault, est, force=force)


def verify_citations(vault, citations):
    """校验 citations 的 snippet 是否在该页文本层（F2）。

    无 snippet -> fail"无 snippet（F2 计失败）"；
    verify_citation 原文验失败 -> T.penetration 穿透到 primary 重验；
    仍败 -> fail"snippet 未在该页文本层找到（幻觉或改写）"。
    返回 [{"doc","page","snippet","ok","via","note"}]。
    """
    from cenhua_service import verify as V
    out = []
    for c in citations:
        doc, page, snippet = c.get("doc", ""), c.get("page", ""), c.get("snippet", "")
        if not snippet:
            out.append({"doc": doc, "page": page, "snippet": "",
                        "ok": False, "via": "none",
                        "note": "无 snippet（F2 计失败）"})
            continue
        if V.verify_citation(vault, doc, page, snippet):
            out.append({"doc": doc, "page": page, "snippet": snippet,
                        "ok": True, "via": "direct", "note": ""})
            continue
        # 穿透到 primary 重验
        pen = T.penetration(vault, doc, page)
        via = "penetration"
        ok = False
        for pdoc, ppage in pen:
            if V.verify_citation(vault, pdoc, ppage or page, snippet):
                ok = True
                via = f"penetration->{pdoc[:8]}"
                break
        out.append({"doc": doc, "page": page, "snippet": snippet,
                    "ok": ok, "via": via,
                    "note": "" if ok else "snippet 未在该页文本层找到（幻觉或改写）"})
    return out


# ------------------------------------------------------------ CLI 解析 ----
_VALUE_OPTS = {"--top"}


def parse_args(rest):
    """解析 `cenhua query` 参数。返回 (question, kw)。

    kw = {"include_derived", "dry", "force", "top"}。
    skip 带值 flag 的值，收集位置参数为 question。
    """
    question_parts, kw = [], {"include_derived": False, "dry": False,
                              "force": False, "top": MAX_DOCS}
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("--include-derived",):
            kw["include_derived"] = True
        elif a in ("--dry-run", "--dry"):
            kw["dry"] = True
        elif a == "--force":
            kw["force"] = True
        elif a in _VALUE_OPTS and i + 1 < len(rest):
            kw["top"] = _int_opt(rest, i + 1, kw["top"])
            i += 1
        elif a.startswith("-") and len(a) > 1:
            pass
        else:
            question_parts.append(a)
        i += 1
    return " ".join(question_parts).strip(), kw


def _int_opt(args, idx, default):
    try:
        return int(args[idx])
    except (ValueError, IndexError):
        return default


# ------------------------------------------------------------ 主编排 ----
def query_flow(vault, question, include_derived=False, dry=False, force=False,
               top=MAX_DOCS):
    """`cenhua query` 主编排。返回 (rc, lines)。零 print。

    四段：命中列表 -> 证据段+hint -> LLM 延展 -> 引文校验 -> 关联推荐。
    """
    from cenhua_service import refine as R
    from cenhua_service import cost as C

    if not question:
        return 2, ["usage: cenhua query \"问题\" "
                   "[--include-derived --dry-run --force --top N]"]

    terms = terms_from_question(question)
    fh = find_hits(vault, terms, include_derived=include_derived)
    sh = semantic_hits(vault, question, top=top)
    fused = fuse(fh, sh)

    if not fused:
        lines = ["= 无命中（find+seek 均空）——拒答=正确"]
        lines.append("  提示：换措辞重试，或 `cenhua add` 补充语料")
        return 1, lines

    # ---- 第一段：命中列表 ----
    lines = [f"= 命中 {len(fused)} 个文档（按置信度降序）："]
    for a in fused[:top]:
        tag = ""
        if a["tier"] == T.TIER_DERIVED:
            tag = " ⚠derived"
            if a["derived_from"]:
                tag += " derived_from->" + ",".join(d[:8] for d in a["derived_from"])
        sim = f" sim={a['sim']:.2f}" if a["sim"] is not None else ""
        lines.append(f"  {a['score']:.2f} [{a['tier']}{tag}] "
                     f"{a['name'] or a['doc']}{sim}")

    # 候选入精化队列（M1b §5.3）
    cand = [a["doc"] for a in fused[:top]]
    for did in cand:
        R.enqueue(vault, did, reason="query")

    # ---- 第二段：证据段 + hint ----
    segs = evidence_for(vault, [d for d in cand
                                if T.evidence_eligible(vault, d)])
    hint_lines, hint_meta = P.hint_block(vault, cand)

    if dry:
        full = P.build_prompt(question, hint_lines,
                              [f"--- [{d[:8]} P?] ---" for d in cand])
        est = estimate(vault, full, calls=1)
        lines.extend(C.dry_run_cost_lines(vault, est))
        lines.append(f"[hint] {hint_meta['docs']} refined doc(s) ready"
                     + (f", {hint_meta['dropped_imperative']} 祈使句已剔除"
                        if hint_meta["dropped_imperative"] else ""))
        lines.append("(dry run — nothing was sent)")
        return 0, lines

    if not segs:
        lines.append(f"{P.UNVERIFIED} 跳过延展：无 primary 证据段"
                     "（命中均为 derived/internal，需 --include-derived 或精化）")
        return 0, lines

    if not L.chat_ready(L.build_env(vault)):
        lines.append(f"{P.UNVERIFIED} 跳过延展：LLM 网关未配置"
                     "（export PI_BASE/PI_KEY；find/read 仍可用）")
        return 0, lines

    # ---- 成本闸 ----
    full = P.build_prompt(question, hint_lines,
                          [f"--- [{d[:8]} P{p}] {n} ---\n{t}"
                           for d, n, p, t in segs])
    est = estimate(vault, full, calls=1)
    ok, msg = cost_gate(vault, est, force=force)
    if not ok:
        return 4, [f"! REFUSED: {msg}"]

    # ---- LLM 延展（失败隔离）----
    try:
        raw, tin, tout = R.call_llm(full, max_tokens=1400)
    except Exception as e:
        lines.append(f"{P.UNVERIFIED} 延展失败：{type(e).__name__}: {str(e)[:120]}")
        return 0, lines
    parsed = P.parse_answer(raw)
    C.ledger_append(vault, {"cmd": "query", "doc": question[:200], "calls": 1,
                            "tokens_in": tin, "tokens_out": tout,
                            "est_cost": est["est_cost"],
                            "currency": est["currency"],
                            "priced": est["priced"]})
    vault.log("query", [f"question={question}", f"calls=1 "
                       f"parse_ok={bool(parsed)}"])

    # ---- 第三段：内容出处 ----
    if parsed:
        lines.append(f"\n> 延展：{parsed['answer']}")
        cites = parsed["citations"]
        if not cites:
            lines.append("  LLM 未给出 citations——结论仅供参考")
        else:
            vc = verify_citations(vault, cites)
            bad = 0
            for r in vc:
                mark = "✓" if r["ok"] else "✗"
                if not r["ok"]:
                    bad += 1
                via = f" ({r['via']})" if r["via"] not in ("direct", "none") else ""
                lines.append(f"  [{mark}] [{r['doc'][:8]} P{r['page']}] "
                             f"{r['snippet'][:60]}{via}")
            if bad:
                lines.append(f"  ! {bad} 条引文未通过原文校验——按 "
                             f"{P.UNVERIFIED} 处理，勿直接采信")
    else:
        lines.append(f"{P.UNVERIFIED} LLM 输出无法解析——结论仅供参考")

    # ---- 第四段：关联推荐 ----
    from cenhua_service import relations as REL
    lines.append("\n> 关联推荐：")
    shown = 0
    for did in cand[:2]:
        for e in REL.related(vault, did)[:4]:
            other = e["to"] if e["from"] == did else e["from"]
            if other in cand:
                continue
            tag = "人工" if e.get("source") == "manual" else "自动"
            lines.append(f"  ↔ {other[:8]} ({e['type']}/{tag} w={e['weight']:.2f}) "
                         f"evidence={e.get('evidence', '')[:40]}")
            shown += 1
    if not shown:
        lines.append("  （无显著关联——正常）")

    # 未精化提示
    from cenhua_service import summaries as S
    unrefined = [d for d in cand
                 if not ((S.load_summary(vault, d) or {}).get("status")
                         == S.STATUS_REFINED)]
    if unrefined:
        lines.append("\n~ 命中文档尚未精化——`cenhua refine --drain` 生产 hint")
    return 0, lines
