"""cenhua_service.graph — 知识图谱：实体节点 + 关系边 + 查询（M4 §5.5）。

图谱是 **relations.jsonl 的实体视角投影**，不是第二套建边逻辑：
  * 实体节点与倒排来自 `relations.entity_index`（规则层 summaries +
    refined.entities_llm，只认 primary_docs，§7.3 图谱隔离）；
  * 实体-实体边**继承** relations 的四层降噪结果（IDF 枢纽压制 / nPMI>0 /
    共现地板 / 人工 ban），再把"共现文档对"穿透成"该文档提及的实体对"
    —— 文档级降噪与实体级边共用同一份证据，绝不另起炉灶；
  * 文档-文档边直接读 `load_relations()`（人工 link 0.8 原样保留）；
  * LLM 三元组（SPO）走 `refine.call_llm` 按需抽取，落
    `meta/triples.jsonl`，重建时原样并入（**不默认全库跑**，成本闸同 refine）。

权重语义与 relations 一致：人工 0.8，自动 ≤0.6。图谱整体
tier=internal-artifact（正文不进引文，只能作导航 hint）。

service 纪律：不 print/exit（test_70）；LLM 只在 `extract_triples` 内发生，
rebuild / 查询路径零网络。
"""

import json
import os
import re
import time
from collections import deque

from cenhua_service import refine as R
from cenhua_service import relations as REL
from cenhua_service import summaries as S

GRAPH_FILE = "graph.json"
TRIPLE_FILE = "triples.jsonl"
SCHEMA_VERSION = 1
TIER = "internal-artifact"

KIND_DOC = "doc"
KIND_ENTITY = "entity"

TYPE_MENTIONS = "mentions"          # doc -> entity
TYPE_COOCCUR = "cooccurrence"       # entity <-> entity（继承降噪）
TIME_GAP = 90                       # 时序边窗口（天），同 relations

# 谓词白名单（LLM 三元组只留可解释的关系；其余丢弃防噪音）
PREDICATES = {"属于", "负责", "参与", "签署", "位于", "购买", "出售",
              "投资", "合作", "竞争", "优于", "导致", "依赖", "包含",
              "属于组织", "任职于", "负责人", "截止时间"}
PRED_MAX = 12
W_TRIPLE = 0.5                      # LLM 三元组边权（介于自动与人工之间偏下）

TRIPLE_PROMPT = (
    "你是知识图谱抽取助手。从下面文本中抽取实体间的关系三元组。\n"
    "只输出一个 JSON 对象，不要其他文字：\n"
    '{{"triples": [{{"s": "主体", "p": "谓词", "o": "客体"}}]}}\n'
    f"谓词只能从这些里选：{', '.join(sorted(PREDICATES))}；"
    "无法归类的关系直接丢弃，最多输出 12 条。\n"
    "主体/客体必须保留原文写法，不得改写。\n\n"
    "文档名：{name}\n正文（截断）：\n{text}\n"
)


# ---------------------------------------------------------------- 路径 ----
def graph_path(vault):
    return os.path.join(vault.meta, GRAPH_FILE)


def triple_path(vault):
    return os.path.join(vault.meta, TRIPLE_FILE)


# ------------------------------------------------------------ LLM 三元组 ----
def _parse_triples(text):
    """LLM 输出 -> [(s,p,o)]。

    返回 None = 输出整体不可解析（调用方走 `_rule_triples` 兜底）；
    返回 [] = JSON 合法但确实没抽到关系（这是结论，不该兜底）。
    """
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None                              # 连 JSON 对象都没有 -> 不可解析
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None                            # 合法 JSON 解析失败 -> None
    if not isinstance(data, dict):
        return None
    out = []
    for t in data.get("triples") or []:
        if not isinstance(t, dict):
            continue
        s = str(t.get("s") or "").strip()[:80]
        p = str(t.get("p") or "").strip()
        o = str(t.get("o") or "").strip()[:80]
        if s and o and p in PREDICATES:
            out.append((s, p, o))
    return out[:PRED_MAX]


def extract_triples(vault, doc_id, read_text=None):
    """单文档 LLM 三元组抽取（唯一 LLM 入口，走 refine.call_llm）。

    返回 {"status": "ok"|"skip"|"failed", "triples": n, "cost": ...}，永不抛。
    失败隔离：网关失败只记账不污染已有三元组（AGENTS.md 降级铁律）。
    """
    from cenhua_service import cost as C
    summ = S.load_summary(vault, doc_id)
    if not summ:
        return {"status": "skip", "triples": 0}
    read_text = read_text or (lambda d: REL.read_text(vault, d))
    text = read_text(doc_id) or ""
    if not text.strip():
        return {"status": "skip", "triples": 0}
    prompt = TRIPLE_PROMPT.format(name=summ.get("name", ""),
                                 text=text[:6000])
    try:
        raw, tin, tout = R.call_llm(prompt, max_tokens=700, temperature=0.1)
    except Exception:
        return {"status": "failed", "triples": 0}
    parsed = _parse_triples(raw)
    parse_ok = parsed is not None
    if not parse_ok:                              # 输出不可解析 -> 规则层兜底
        parsed = _rule_triples(vault, doc_id)
    wrote = _save_triples(vault, doc_id, parsed)
    est, currency, priced, _ = C.estimate_cost(
        os.environ.get("PI_MODEL", "openai/gpt-4o-mini"), tin, tout)
    C.ledger_append(vault, {"cmd": "graph", "doc": summ.get("name", "")[:200],
                            "calls": 1, "tokens_in": tin, "tokens_out": tout,
                            "est_cost": est, "currency": currency,
                            "priced": priced})
    vault.log("graph", [f"doc={doc_id} triples={wrote} "
                        f"parse_ok={parse_ok} fallback={not parse_ok}"])
    return {"status": "ok", "triples": wrote, "fallback": not parse_ok}


def _rule_triples(vault, doc_id):
    """非 LLM fallback：从规则实体造 (doc, 提及, 实体) 三元组。"""
    summ = S.load_summary(vault, doc_id) or {}
    name = summ.get("name", doc_id)
    out = []
    for vals in (summ.get("entities") or {}).values():
        for v in vals:
            v = REL._norm_entity(v)
            if v:
                out.append((name, "提及", v))
    return out[:PRED_MAX]


def _save_triples(vault, doc_id, triples):
    """按 doc_id 整篇替换三元组（幂等：重跑不重复累积）。返回写入条数。"""
    rows = [r for r in _load_triples_raw(vault) if r.get("doc") != doc_id]
    for s, p, o in triples or []:
        rows.append({"doc": doc_id, "s": s, "p": p, "o": o,
                     "source": "llm", "ts": time.strftime("%F %T")})
    os.makedirs(vault.meta, exist_ok=True)
    tmp = triple_path(vault) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, triple_path(vault))
    return len(triples or [])


def _load_triples_raw(vault):
    try:
        with open(triple_path(vault), encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except (OSError, ValueError):
        return []


def extract_all(vault, doc_ids=None, limit=None, progress=None):
    """按需批量抽取三元组（**绝不默认全库跑**，§5.5 成本约定）。

    `doc_ids` 为已圈选清单（估价与执行**必须同一份**，否则 dry-run 价与
    实际花费脱钩）；缺省取全部 primary（调用方自己负责显式传 --all）。
    逐文档调 `extract_triples`（内部已 try/except + 记账），单篇失败不影响
    其余；`progress(i, total, res)` 只用于 CLI 心跳，本模块不打印。
    """
    if doc_ids is None:
        doc_ids = [d for d, _ in REL.primary_docs(vault)]
    if limit:
        doc_ids = doc_ids[:limit]
    done = fail = wrote = 0
    for i, doc_id in enumerate(doc_ids, 1):
        res = extract_triples(vault, doc_id)
        if res.get("status") == "ok":
            done += 1
            wrote += res.get("triples", 0)
        elif res.get("status") == "failed":
            fail += 1
        if progress:
            progress(i, len(doc_ids), res)
    return {"docs": done, "failed": fail, "triples": wrote}


# ---------------------------------------------------------------- 重建 ----
def entity_edges(cooc_pairs):
    """实体-实体边：继承 relations 的四层降噪结果与边权口径。

    cooc_pairs: {(a,b): (inter_docs, npmi_score)} —— 由 `_cooc_pairs` 产出，
    判据与 relations.build 逐条对齐（hub 压制 / 地板 / ban / nPMI>0），
    故边权直接走 `relations._auto_weight`（自动边硬上限 0.6）。
    """
    edges = {}
    for (a, b), (docs, score) in sorted(cooc_pairs.items()):
        edges[(a, b)] = {
            "from": a, "to": b, "type": TYPE_COOCCUR,
            "weight": REL._auto_weight(score), "source": "auto",
            "docs": sorted(docs),
            "evidence": (f"共现 [{a}, {b}] 于 "
                         f"{', '.join(sorted(x[:8] for x in docs))}, "
                         f"{len(docs)} doc(s), nPMI={score:.2f}")}
    return edges


def _cooc_pairs(vault, ent_docs, hubs, prof, n):
    """与 relations.build 同源的四层降噪（同判据、同 ban）。

    返回 {(a,b): (共现文档集合, nPMI)}。刻意不复用 `relations.build` 的返回值：
    它落盘的是文档对，本模块需要实体对侧的中间结果。
    """
    bans = REL.load_bans(vault)
    lap = 1 if prof["laplace"] else 0
    pairs = {}
    for doc_id, _ in REL.primary_docs(vault):
        summ = S.load_summary(vault, doc_id)
        if not summ:
            continue
        ents = {REL._norm_entity(v) for vals in
                (summ.get("entities") or {}).values() for v in vals}
        ents |= {REL._norm_entity(v) for v in
                 (summ.get("refined") or {}).get("entities_llm") or []}
        ents = sorted(e for e in ents if e and e not in hubs)
        for i, a in enumerate(ents):
            for b in ents[i + 1:]:
                pairs.setdefault((a, b), set()).add(doc_id)
    out = {}
    for (a, b), inter_docs in pairs.items():
        inter = len(inter_docs)
        if inter < prof["floor"]:                        # ③ 地板
            continue
        if (a, b) in bans or (b, a) in bans:             # ④ 人工阀门
            continue
        if lap:                             # ② nPMI（小库档 Laplace 平滑）
            score = REL.npmi(n + 1, len(ent_docs[a]) + 1,
                             len(ent_docs[b]) + 1, inter + 1)
        else:
            score = REL.npmi(n, len(ent_docs[a]), len(ent_docs[b]), inter)
        if score <= 0:
            continue
        out[(a, b)] = (inter_docs, score)
    return out


def rebuild(vault):
    """全量重建 graph.json（零 LLM、个人库规模秒级）。

    返回 {"docs","entities","edges","triples","hubs","tier"}。
    """
    REL.ensure_summaries(vault)
    ent_docs, ent_pages, doc_dates, n = REL.entity_index(vault)
    prof = REL.profile(n)
    df = {e: len(d) for e, d in ent_docs.items()}
    hubs = set(REL.hub_entities(df, n, prof["hub_df_ratio"]))

    names = dict(REL.primary_docs(vault))
    nodes = [{"id": d, "kind": KIND_DOC, "name": nm,
              "df": 0, "tier": "primary"} for d, nm in sorted(names.items())]
    nodes += [{"id": e, "kind": KIND_ENTITY, "name": e, "df": df[e],
               "hub": e in hubs, "tier": TIER} for e in sorted(df)]

    edges = []
    # ① doc -> entity（mentions，导航用，不参与权重竞争）
    for e in sorted(ent_docs):
        for d in sorted(ent_docs[e]):
            edges.append({"from": d, "to": e, "type": TYPE_MENTIONS,
                          "weight": 1.0, "source": "auto",
                          "pages": ent_pages.get(e, {}).get(d, [])})
    # ② entity <-> entity（继承四层降噪）
    edges += sorted(entity_edges(
        _cooc_pairs(vault, ent_docs, hubs, prof, n)).values(),
        key=lambda x: (x["from"], x["to"]))
    # ③ doc <-> doc（relations 原样，人工边保留）
    for r in REL.load_relations(vault):
        edges.append({"from": r["from"], "to": r["to"],
                      "type": r.get("type", REL.TYPE_COOCCUR),
                      "weight": r.get("weight", 0.0),
                      "evidence": r.get("evidence", ""),
                      "source": r.get("source", "auto")})
    # ④ LLM 三元组（SPO 视作实体边；端点缺节点则补，图必须自洽）
    triples = _load_triples_raw(vault)
    known = {nd["id"] for nd in nodes}
    for t in triples:
        s, o = t.get("s", ""), t.get("o", "")
        for side in (s, o):
            if side and side not in known:
                known.add(side)
                nodes.append({"id": side, "kind": KIND_ENTITY, "name": side,
                              "df": 0, "hub": False, "tier": TIER})
        edges.append({"from": s, "to": o,
                      "type": t.get("p", ""), "weight": W_TRIPLE,
                      "doc": t.get("doc", ""), "source": t.get("source", "llm"),
                      "evidence": f"三元组 [{s}]-{t.get('p')}->[{o}]"})

    doc = {"schema_version": SCHEMA_VERSION, "ts": time.strftime("%F %T"),
           "tier": TIER, "tier_profile": prof["tier"], "n_docs": n,
           "hubs": sorted(hubs), "nodes": nodes, "edges": edges}
    _write_json(graph_path(vault), doc)
    return {"docs": n, "entities": len(df), "edges": len(edges),
            "triples": len(triples), "hubs": len(hubs), "tier": prof["tier"]}


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_graph(vault, rebuild_if_missing=True):
    """读 graph.json；缺失且允许时自动 rebuild（离线、秒级）。"""
    if rebuild_if_missing and not os.path.isfile(graph_path(vault)):
        rebuild(vault)
    try:
        with open(graph_path(vault), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("nodes"), list):
            data.setdefault("tier", TIER)
            return data
    except (OSError, ValueError):
        pass
    return {"schema_version": SCHEMA_VERSION, "ts": "", "tier": TIER,
            "n_docs": 0, "hubs": [], "nodes": [], "edges": []}


# ---------------------------------------------------------------- 查询 ----
def _index(g):
    nodes = {nd["id"]: nd for nd in g["nodes"]}
    adj = {}
    for e in g["edges"]:
        if not e.get("from") or not e.get("to"):
            continue
        adj.setdefault(e["from"], []).append(e)
        adj.setdefault(e["to"], []).append(e)
    return nodes, adj


def _resolve(g, kw, kind=None):
    """关键词 -> 节点 id（精确 > 前缀 > 包含；大小写不敏感）。"""
    kw = (kw or "").strip().lower()
    if not kw:
        return None
    cands = [nd for nd in g["nodes"] if kind is None or nd["kind"] == kind]
    for pred in (lambda n: n["id"].lower() == kw,
                 lambda n: n["id"].lower().startswith(kw),
                 lambda n: n["name"].lower() == kw,
                 lambda n: kw in n["id"].lower(),
                 lambda n: kw in n["name"].lower()):
        hit = [n for n in cands if pred(n)]
        if hit:
            return sorted(hit, key=lambda n: (-n.get("df", 0), n["id"]))[0]["id"]
    return None


def entity(vault, kw, limit=10):
    """`graph entity <实体>`：df、提及文档、邻居实体（按权重）。"""
    g = load_graph(vault)
    nid = _resolve(g, kw)
    if not nid:
        return {"ok": False, "kw": kw,
                "lines": [f"entity({kw}): 图谱中无此实体"
                          f"（重建: cenhua weave rebuild）"]}
    nodes, adj = _index(g)
    names = {i: nd.get("name", i) for i, nd in nodes.items()}
    docs = sorted({other for e in adj.get(nid, []) if e["type"] == TYPE_MENTIONS
                   for other in (e["to"] if e["from"] == nid else e["from"],)
                   if nodes.get(other, {}).get("kind") == KIND_DOC})
    neigh = {}
    for e in adj.get(nid, []):
        if e["type"] == TYPE_MENTIONS:
            continue
        other = e["to"] if e["from"] == nid else e["from"]
        if other not in nodes:
            continue
        cur = neigh.get(other)
        if not cur or e.get("weight", 0) > cur["weight"]:
            neigh[other] = e
    ranked = sorted(neigh.values(), key=lambda e: -e.get("weight", 0))[:limit]
    lines = [f"entity({names[nid]}) — df={nodes[nid].get('df', 0)}"
             f"{' [hub 已压制建边]' if nodes[nid].get('hub') else ''}, "
             f"{len(docs)} doc(s) 提及:"]
    for d in docs[:limit]:
        lines.append(f"  {names.get(d, d)}")
    if len(docs) > limit:
        lines.append(f"  ... {len(docs) - limit} more")
    if not ranked:
        lines.append("邻居实体: (none) — 无显著共现（正常，空即信息）")
    else:
        lines.append(f"邻居实体（top {len(ranked)}，按权重）:")
        for e in ranked:
            other = e["to"] if e["from"] == nid else e["from"]
            lines.append(f"  {e.get('weight', 0):.2f} [{e['type']}] "
                         f"{names.get(other, other)}")
            if e.get("evidence"):
                lines.append(f"        evidence: {e['evidence']}")
    return {"ok": True, "id": nid, "df": nodes[nid].get("df", 0),
            "docs": docs, "neighbors": ranked, "lines": lines}


def path(vault, kw_a, kw_b, max_hops=3):
    """`graph path <A> <B>`：实体间最短路径（BFS，跳数含端点）。

    不经由 mentions 边（那是"谁提到我"，不是关系），只走关系边。
    """
    g = load_graph(vault)
    a = _resolve(g, kw_a, KIND_ENTITY) or _resolve(g, kw_a)
    b = _resolve(g, kw_b, KIND_ENTITY) or _resolve(g, kw_b)
    if not a or not b:
        miss = kw_a if not a else kw_b
        return {"ok": False, "lines": [f"path: 找不到实体 '{miss}'"]}
    if a == b:
        return {"ok": True, "hops": 0, "lines": [f"path: {a} 与自身同节点"]}
    nodes, adj = _index(g)
    prev, seen = {a: None}, {a}
    q = deque([a])
    found = False
    while q:
        cur = q.popleft()
        for e in adj.get(cur, []):
            if e["type"] == TYPE_MENTIONS:
                continue
            nxt = e["to"] if e["from"] == cur else e["from"]
            if nxt in seen or nxt not in nodes:
                continue
            prev[nxt] = (cur, e)
            if nxt == b:
                found = True
                q.clear()
                break
            seen.add(nxt)
            q.append(nxt)
        if found:
            break
    if not found:
        return {"ok": False, "lines": [
            f"path({kw_a} <-> {kw_b}): {max_hops} 跳内无关系路径"
            f"（未相连也是结论）"]}
    chain, cur = [], b
    while prev[cur] is not None:
        src, e = prev[cur]
        chain.append((src, cur, e))
        cur = src
    chain.reverse()
    names = {i: nd.get("name", i) for i, nd in nodes.items()}
    lines = [f"path({names[a]} -> {names[b]}): {len(chain)} edge(s)"]
    for src, dst, e in chain:
        lines.append(f"  {names.get(src, src)} -[{e['type']}"
                     f"/{e.get('weight', 0):.2f}]-> {names.get(dst, dst)}")
        if e.get("evidence"):
            lines.append(f"        evidence: {e['evidence']}")
    return {"ok": True, "hops": len(chain),
            "chain": [(s, d, e["type"]) for s, d, e in chain], "lines": lines}


def clusters(vault, top=10):
    """`graph cluster`：实体层连通分量 = 主题簇（含孤立实体计数）。"""
    g = load_graph(vault)
    nodes, adj = _index(g)
    ents = [n["id"] for n in g["nodes"] if n["kind"] == KIND_ENTITY]
    seen, comps = set(), []
    for e in sorted(ents):
        if e in seen:
            continue
        comp, q = set(), deque([e])
        seen.add(e)
        while q:
            cur = q.popleft()
            comp.add(cur)
            for ed in adj.get(cur, []):
                if ed["type"] == TYPE_MENTIONS:
                    continue
                nxt = ed["to"] if ed["from"] == cur else ed["from"]
                if nxt in seen or nxt not in nodes \
                        or nodes[nxt]["kind"] != KIND_ENTITY:
                    continue
                seen.add(nxt)
                q.append(nxt)
        comps.append(comp)
    linked = sorted([c for c in comps if len(c) > 1], key=len, reverse=True)
    isolated = sum(len(c) for c in comps if len(c) == 1)
    lines = [f"clusters: {len(linked)} connected cluster(s), "
             f"{isolated} isolated entity(ies) "
             f"[graph ts={g.get('ts', '') or 'n/a'}]"]
    if not linked:
        lines.append("  (none) — 尚无跨实体关系（库太小或文档无共现）")
    for i, c in enumerate(linked[:top], 1):
        members = sorted(c, key=lambda x: -nodes[x].get("df", 0))
        lines.append(f"  #{i}  n={len(members)}  "
                     + ", ".join(members[:8])
                     + (f" ... +{len(members) - 8}" if len(members) > 8 else ""))
    if len(linked) > top:
        lines.append(f"  ... {len(linked) - top} more cluster(s)")
    return {"ok": True, "clusters": [sorted(c) for c in linked],
            "isolated": isolated, "lines": lines}


# ------------------------------------------------------------ Mermaid ----
def mermaid(vault, entity_kw=None, max_nodes=24):
    """渲染 Mermaid graph（复用 M1a 范式；CLI 与 Web 共用一处实现）。

    mentions 边（doc->entity）不入图，否则一挂文档就糊成星形不可读；
    实体图谱只画关系边。节点用散列 id + 显示名，中文名/特殊字符都安全。
    """
    g = load_graph(vault)
    nodes, adj = _index(g)
    rel = [e for e in g["edges"] if e["type"] != TYPE_MENTIONS
           and e.get("from") and e.get("to")]
    if entity_kw:
        center = _resolve(g, entity_kw)
        keep = set()
        if center:
            keep.add(center)
            for e in adj.get(center, []):
                if e["type"] != TYPE_MENTIONS:
                    keep |= {e["from"], e["to"]}
    else:
        score = {}
        for e in rel:
            for side in (e["from"], e["to"]):
                score[side] = score.get(side, 0.0) + e.get("weight", 0.0)
        keep = {k for k, _ in sorted(score.items(),
                                     key=lambda kv: (-kv[1], kv[0]))[:max_nodes]}
    if not keep:
        return ("```mermaid\ngraph LR\n"
                "  empty[图谱为空: 先 cenhua weave rebuild]\n```")
    shown = [e for e in rel if e["from"] in keep and e["to"] in keep]
    lines = ["```mermaid", "graph LR"]
    for nid in sorted(keep):
        lines.append(f"  {_mid(nid)}[{_label(nodes.get(nid, {}).get('name', nid))}]")
    for e in shown:
        lines.append(f"  {_mid(e['from'])} -->|{_label(e['type'])}| "
                     f"{_mid(e['to'])}")
    lines.append("```")
    return "\n".join(lines)


def _label(text):
    """Mermaid 标签：方括号/引号/竖线一律替空（否则整图语法错）。"""
    return re.sub(r"[\[\]\"'|<>{}]", " ", str(text or "")).strip()[:40] or "节点"


def _mid(nid):
    """Mermaid 节点 id：一律 sha1 短码（中文名、同名清洗后都能唯一化）。"""
    import hashlib
    return "n" + hashlib.sha1(str(nid).encode("utf-8")).hexdigest()[:10]


# -------------------------------------------------- 力导向视图（M4b 任务 6）----


def view(vault, entity_kw=None, max_nodes=80):
    """graph.json -> 前端力导向图 JSON（GET /api/v1/graph 的数据面）。

    口径与 mermaid 一致：mentions 边（doc->entity）默认不入图，
    否则一挂文档就糊成星形不可读。entity_kw 给定时以该节点为中心
    展开一跳到邻居（邻居文档的 mentions 边保留，方便看"谁提到它"）；
    否则按边权（实体）+ 提及文档数（文档）取热度 top-N。
    返回 {"ts","tier","n_docs","nodes","edges","total_nodes","total_edges",
    "center","truncated"}，字段全部为前端可直接消费的简单类型。
    """
    g = load_graph(vault)
    nodes, adj = _index(g)
    rel = [e for e in g["edges"] if e["type"] != TYPE_MENTIONS
           and e.get("from") and e.get("to")]
    mentions = [e for e in g["edges"] if e["type"] == TYPE_MENTIONS]

    center = _resolve(g, entity_kw) if entity_kw else None
    keep = set()
    if center:
        keep.add(center)
        for e in adj.get(center, []):
            keep |= {e["from"], e["to"]}
    else:
        score = {}
        for e in rel:
            for side in (e["from"], e["to"]):
                score[side] = score.get(side, 0.0) + e.get("weight", 0.0)
        for e in mentions:
            score[e["from"]] = score.get(e["from"], 0.0) + 0.5
        keep = {k for k, _ in sorted(score.items(),
                                     key=lambda kv: (-kv[1], kv[0]))
                [:max(1, int(max_nodes))]}

    shown = [e for e in rel if e["from"] in keep and e["to"] in keep]
    if center:
        shown += [e for e in mentions
                  if center in (e["from"], e["to"])]
    used = set()
    for e in shown:
        used |= {e["from"], e["to"]}
    out_nodes = [
        {"id": nd["id"], "kind": nd["kind"], "name": nd.get("name", nd["id"]),
         "df": nd.get("df", 0), "hub": bool(nd.get("hub", False)),
         "tier": nd.get("tier", "")}
        for nid, nd in sorted(nodes.items()) if nid in used]
    return {"ts": g.get("ts", ""), "tier": g.get("tier", TIER),
            "n_docs": g.get("n_docs", 0), "center": center or "",
            "nodes": out_nodes,
            "edges": [{"from": e["from"], "to": e["to"], "type": e["type"],
                       "weight": e.get("weight", 0.0),
                       "source": e.get("source", "auto"),
                       "evidence": e.get("evidence", "")}
                      for e in shown],
            "total_nodes": len(nodes), "total_edges": len(g["edges"]),
            "truncated": len(nodes) > len(used), "schema_version": 1}


# ---------------------------------------------------------------- CLI ----
USAGE = (
    "usage: cenhua graph entity <实体> [--limit N]        [OFFLINE]\n"
    "       cenhua graph path <A> <B> [--max-hops N]      [OFFLINE]\n"
    "       cenhua graph cluster [--top N]                [OFFLINE]\n"
    "       cenhua graph mermaid [<实体>] [--max-nodes N] [OFFLINE]\n"
    "       cenhua graph rebuild                          [OFFLINE]\n"
    "       cenhua graph triples [--doc kw|--all] [--limit N]"
    " [--dry-run] [--force] [--max-cost X]\n"
    "                                     LLM 三元组抽取（按需；成本闸适用）"
)


def _pos(rest):
    return [a for a in rest if not a.startswith("-")]


def _num(rest, flag_name, default):
    if flag_name in rest:
        try:
            return int(rest[rest.index(flag_name) + 1])
        except (IndexError, ValueError):
            return default
    return default


def _triple_targets(vault, rest):
    """triples 的文档圈选：--doc kw（可重复/子串匹配）优先，否则 --all。"""
    docs = REL.primary_docs(vault)
    kws = [rest[i + 1] for i, a in enumerate(rest) if a == "--doc"
           and i + 1 < len(rest)]
    if kws:
        out = []
        for kw in kws:
            k = kw.lower()
            out += [d for d, nm in docs
                    if k in d.lower() or k in (nm or "").lower()]
        seen, uniq = set(), []
        for d in out:
            if d not in seen:
                seen.add(d)
                uniq.append(d)
        return uniq
    if "--all" in rest:
        return [d for d, _ in docs]
    return []


def triples_flow(vault, rest):
    """`graph triples`：按需 LLM 抽取 + 三闸（dry-run → 预算 → --force）。

    rc：0 成功；2 参数错；3 网关未配置；4 预算闸拒绝。
    """
    from cenhua_service import cost as C
    from cenhua_service import digest as D
    import m_lib as L                                # 网关可用性判定

    targets = _triple_targets(vault, rest)
    limit = _num(rest, "--limit", 0)
    if limit:
        targets = targets[:limit]
    if not targets:
        return {"rc": 2, "lines": [
            "triples: 未圈选文档 — 用 --doc <关键词> 或 --all（不默认全库跑）",
            USAGE]}
    texts = []
    for d in targets:
        try:
            texts.append(REL.read_text(vault, d) or "")
        except Exception:
            texts.append("x" * 6400)
    model = os.environ.get("PI_MODEL", "openai/gpt-4o-mini")
    est = C.estimate_docs(model, texts, tokens_out_per=PRED_MAX * 40)
    lines = [f"[graph] triples     : {len(targets)} doc(s) 待抽取",
             "[cost] estimate   : %.4f %s%s" % (
                 est["est_cost"], est["currency"],
                 "" if est.get("priced") else f"  ({est.get('note', '')})"),
             f"[graph] calls       : {len(targets)} × ~{PRED_MAX} 三元组"]
    if "--dry-run" in rest:                       # ① 只看价，不花钱
        lines.append("[graph] dry-run      : 未调用网关（去掉 --dry-run 即执行）")
        return {"rc": 0, "lines": lines}
    if not L.chat_ready(L.build_env(vault)):         # ③ 前置：网关可用性
        lines.append("[graph] gateway      : 未配置 PI_KEY/PI_BASE，"
                     "无法抽取三元组（规则实体图谱仍可用）")
        return {"rc": 3, "lines": lines}
    ok, msg = D.budget_check(vault, est, force="--force" in rest,
                             max_cost=(float(rest[rest.index("--max-cost") + 1])
                                       if "--max-cost" in rest else None))
    lines.append(f"[graph] budget      : {msg}")
    if not ok:
        return {"rc": 4, "lines": ["[graph] REFUSED — " + msg] + lines}
    r = extract_all(vault, doc_ids=targets)
    lines.append(f"[graph] extracted   : {r['docs']} doc(s) ok, "
                 f"{r['failed']} failed, {r['triples']} triple(s) 落盘")
    rb = rebuild(vault)
    lines.append(f"[graph] graph.json  : 重建 {rb['edges']} edge(s), "
                 f"{rb['entities']} entities, triples={rb['triples']}")
    return {"rc": 0, "lines": lines}


def cli(vault, rest):
    """`cenhua graph ...` 的参数分派（service 层，CLI 只负责打印）。"""
    rest = list(rest or [])
    sub = rest[0] if rest and not rest[0].startswith("-") else ""
    tail = rest[1:] if sub else rest
    pos = _pos(tail)
    if sub == "entity":
        if not pos:
            return {"rc": 2, "lines": ["usage: cenhua graph entity <实体>"]}
        return _wrap(entity(vault, pos[0], limit=_num(tail, "--limit", 10)))
    if sub == "path":
        if len(pos) < 2:
            return {"rc": 2, "lines": ["usage: cenhua graph path <A> <B>"]}
        return _wrap(path(vault, pos[0], pos[1],
                          max_hops=_num(tail, "--max-hops", 3)))
    if sub == "cluster":
        return _wrap(clusters(vault, top=_num(tail, "--top", 10)))
    if sub == "mermaid":
        return {"rc": 0, "lines": mermaid(
            vault, pos[0] if pos else None,
            max_nodes=_num(tail, "--max-nodes", 24)).split("\n")}
    if sub == "rebuild":
        r = rebuild(vault)
        return {"rc": 0, "lines": [
            f"+ graph rebuilt: {r['edges']} edge(s), {r['docs']} doc(s), "
            f"{r['entities']} entities, {r['hubs']} hub(s), "
            f"triples={r['triples']}, tier={r['tier']}"]}
    if sub == "triples":
        return triples_flow(vault, tail)
    return {"rc": 2, "lines": [f"graph: 未知子命令 '{sub or '(空)'}'"]
            + USAGE.split("\n")}


def _wrap(res):
    """查询结果 -> {rc, lines}：查不到返回 rc=1（空即结论，不是错误）。"""
    return {"rc": 0 if res.get("ok") else 1, "lines": res["lines"]}
