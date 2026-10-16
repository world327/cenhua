"""cenhua_service.relations — 跨文档关联 + 四层降噪（M1b §5.4）。

纯 Python 统计，零 LLM 零依赖。关联主体是**文档对**（`related <doc>`），
边由**非枢纽实体的显著共现**驱动：实体对 (A,B) 通过四层降噪后，在同时
含 A、B 的文档两两之间建边；每条边带证据（共现页码 + nPMI）。

四层降噪（档位随 N 自动切换，`CENHUA_SMALL_CORPUS_N` 默认 200）：
  ① IDF 过滤：df > N×ratio（标准 0.30 / 小库 0.50）判枢纽实体，不建边
  ② nPMI ≤ 0 不建边（小库档 +Laplace 平滑）
  ③ 共现地板 |D_A∩D_B| ≥ 2（标准）/ ≥ 1（小库）
  ④ 人工阀门：link --ban 黑名单永久压制

权重语义：人工显式关联 0.8；自动边 ≤ 0.6。每文档对外关联 Top-8 截断。
关系落 `meta/relations.jsonl`（tier=internal-artifact；正文不进引文）。
衍生文档（tier != primary）不参与建边（防噪音炸弹，§7.3）。

service 纪律：不 print/exit（test_70）。
"""

import json
import math
import os
import re
import time

from cenhua_service import summaries as S

REL_FILE = "relations.jsonl"
BAN_FILE = "link_bans.json"
SMALL_N_ENV = "CENHUA_SMALL_CORPUS_N"

TOP_K = 8
W_MANUAL = 0.8
W_AUTO_CAP = 0.6
HUB_MIN_DF = 3

TYPE_COOCCUR = "cooccurrence"
TYPE_TIME = "time_series"
TYPE_CITE = "cite"               # 人工 link
TYPE_SIMILAR = "similar"         # 向量层（可用时）

PAGE_MARK = re.compile(r"^(?:=== PAGE (\d+) ===|第(\d+)页)$")


# ------------------------------------------------------ 小工具（无 IO 假设）----
def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_text(vault, doc_id):
    p = os.path.join(vault.textdir, doc_id + ".txt")
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


DERIVED_RE = re.compile(r"(?:^|[/_.-])(?:digest|draft|周报|日报)[_.\-]", re.I)


def primary_docs(vault):
    """[(doc_id, name)]，排除衍生文档（digest/draft；§7.3 防噪音炸弹）。

    衍生文档（M3 digest/draft）默认不入库摄取；万一用户手动 add 了
    这类文件，按名称特征排除，避免其模板化文本把共现图刷满。
    """
    store = os.path.join(vault.store, "ingest_manifest.json")
    led = _read_json(store, {}) or {}
    out = []
    for doc_id, rec in led.items():
        name = rec.get("name", doc_id)
        if DERIVED_RE.search(name):
            continue
        out.append((doc_id, name))
    return sorted(out)


def rel_path(vault):
    return os.path.join(vault.meta, REL_FILE)


def ban_path(vault):
    return os.path.join(vault.meta, BAN_FILE)


# ------------------------------------------------------------ 档位/闸门 ----
def small_corpus_n():
    try:
        return int(os.environ.get(SMALL_N_ENV, "200"))
    except ValueError:
        return 200


def profile(n_docs):
    """当前档位与参数（hub 显示、建边共用一处配置）。"""
    small = n_docs < small_corpus_n()
    return {
        "tier": "small" if small else "standard",
        "n": n_docs,
        "hub_df_ratio": 0.50 if small else 0.30,
        "floor": 1 if small else 2,
        "laplace": small,
    }


# ---------------------------------------------------------- nPMI / IDF ----
def npmi(n, df_a, df_b, inter):
    """nPMI(A,B) = log(N·|D_A∩D_B| / (|D_A|·|D_B|)) / log(N)。

    小库档 Laplace 平滑由调用方在 inter/df 上 +1（此处纯计算）。
    N<=1 无定义，返回 0（不建边）。
    """
    if n <= 1 or df_a <= 0 or df_b <= 0:
        return 0.0
    if inter <= 0:
        return 0.0
    return math.log(n * inter / (df_a * df_b)) / math.log(n)


def hub_entities(df, n, ratio):
    """df > N×ratio 且 df >= HUB_MIN_DF 判枢纽（按 df 降序，供 hub 复核）。

    HUB_MIN_DF=3 绝对地板：极小库（N=3~5）下纯比例会把"共同出现 2 次"
    的正常信号误判成枢纽，related 常年空转——恰是 T6 要防的反面。
    """
    return sorted((e for e, d in df.items()
                   if d > n * ratio and d >= HUB_MIN_DF),
                  key=lambda e: -df[e])


# ---------------------------------------------------------- 实体索引 ----
def _norm_entity(e):
    return re.sub(r"\s+", " ", (e or "").strip()).lower()[:80]


def entity_index(vault, summaries_dir_docs=None):
    """实体 -> {doc_ids}，页码索引 entity->doc->页。

    只收 primary 文档（衍生文档不参与共现建边）；
    refined 的 entities_llm 并入。返回 (ent_docs, ent_pages, doc_dates, n_docs)
    ent_pages[entity][doc] = [页码...]（文本层现扫，N≤300 可接受）
    """
    docs = primary_docs(vault)
    ent_docs, ent_pages = {}, {}
    doc_dates = {}
    for doc_id, name in docs:
        summ = S.load_summary(vault, doc_id)
        if not summ:
            continue
        ents = set()
        for vals in (summ.get("entities") or {}).values():
            ents.update(_norm_entity(v) for v in vals)
        refined = summ.get("refined") or {}
        for v in refined.get("entities_llm") or []:
            ents.add(_norm_entity(v))
        ents.discard("")
        text = read_text(vault, doc_id) or ""
        pages = _entity_pages(text, ents)
        for e in ents:
            ent_docs.setdefault(e, set()).add(doc_id)
            if pages.get(e):
                ent_pages.setdefault(e, {})[doc_id] = pages[e]
        ds = (summ.get("entities") or {}).get("date") or []
        doc_dates[doc_id] = _best_date(ds)
    return ent_docs, ent_pages, doc_dates, len(docs)


def _entity_pages(text, ents):
    """文本层扫一遍：实体 -> 命中页码列表。"""
    pages, page = {}, "?"
    for line in text.splitlines():
        m = PAGE_MARK.match(line.strip())
        if m:
            page = m.group(1) or m.group(2)
            continue
        low = line.lower()
        for e in ents:
            if e in low:
                pages.setdefault(e, [])
                if page not in pages[e] and len(pages[e]) < 4:
                    pages[e].append(page)
    return pages


DATE = re.compile(r"(\d{4})[-/](\d{1,2})(?:[-/](\d{1,2}))?")


def _best_date(date_list):
    """实体日期列表 -> 最大日期 (y,m,d)（文档"最新时间"语义）。"""
    best = None
    for s in date_list:
        m = DATE.search(s.replace("年", "-").replace("月", "-").replace("日", ""))
        if not m:
            continue
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)
        if best is None or (y, mo, d) > best:
            best = (y, mo, d)
    return best


def _days_apart(a, b):
    if not a or not b:
        return None
    import datetime
    try:
        da = datetime.date(*a)
        db = datetime.date(*b)
    except ValueError:
        return None
    return abs((da - db).days)


# ------------------------------------------------------------ 建边 ----
def _auto_weight(score):
    """自动边权：nPMI(0..1] 映射到 (0.2, 0.6]，硬上限 0.6。"""
    return round(min(W_AUTO_CAP, 0.2 + 0.4 * max(0.0, min(1.0, score))), 3)


def ensure_summaries(vault):
    """建边前保证规则层存在（零 LLM）。缺失会静默 0 边，必须补。"""
    return S.ensure_all(vault, {d: {"name": n} for d, n in primary_docs(vault)},
                        lambda d: read_text(vault, d))


def build(vault):
    """全量重建 relations.jsonl（个人库规模 N≤300，秒级，零 LLM）。

    返回统计 {"docs","entities","hubs","edges","tier"}。
    人工边（cite）与 ban 名单在重建后原样保留/应用。
    """
    ensure_summaries(vault)
    ent_docs, ent_pages, doc_dates, n = entity_index(vault)
    prof = profile(n)
    hubs = set(hub_entities({e: len(d) for e, d in ent_docs.items()},
                            n, prof["hub_df_ratio"]))
    bans = load_bans(vault)
    lap = 1 if prof["laplace"] else 0

    # 候选实体对：同文档内非枢纽实体两两组合，聚合共现文档集
    pairs = {}
    for doc_id, _ in primary_docs(vault):
        summ = S.load_summary(vault, doc_id)
        if not summ:
            continue
        ents = {_norm_entity(v) for vals in
                (summ.get("entities") or {}).values() for v in vals}
        ents |= {_norm_entity(v) for v in
                 (summ.get("refined") or {}).get("entities_llm") or []}
        ents = sorted(e for e in ents if e and e not in hubs)
        for i, a in enumerate(ents):
            for b in ents[i + 1:]:
                pairs.setdefault((a, b), set()).add(doc_id)

    # 四层降噪 + 文档对投影
    doc_edges = {}                       # (d1,d2) -> best edge
    for (a, b), inter_docs in pairs.items():
        inter = len(inter_docs)
        if inter < prof["floor"]:                        # ③ 地板
            continue
        if (a, b) in bans or (b, a) in bans:             # ④ 人工阀门
            continue
        df_a, df_b = len(ent_docs[a]) + lap, len(ent_docs[b]) + lap
        score = npmi(n + lap, df_a, df_b, inter + lap) if lap \
            else npmi(n, df_a, df_b, inter)
        if score <= 0:                                   # ② nPMI
            continue
        w = _auto_weight(score)
        docs_l = sorted(inter_docs)
        for i, d1 in enumerate(docs_l):
            for d2 in docs_l[i + 1:]:
                pa = ent_pages.get(a, {}).get(d1, [])
                pb = ent_pages.get(b, {}).get(d2, [])
                ev = (f"共现 [{a}, {b}] 于 [{_pg(d1, pa)}, {_pg(d2, pb)}], "
                      f"nPMI={score:.2f}")
                # 时间序列：共现 + 双方日期 ≤90 天 -> time_series
                days = _days_apart(doc_dates.get(d1), doc_dates.get(d2))
                etype = TYPE_TIME if (days is not None and days <= 90) \
                    else TYPE_COOCCUR
                key = (d1, d2)
                old = doc_edges.get(key)
                if not old or w > old["weight"]:
                    doc_edges[key] = {"from": d1, "to": d2, "type": etype,
                                      "weight": w, "evidence": ev,
                                      "source": "auto"}

    # 人工边保留（0.8，不参与降噪）
    manual = [r for r in _load_relations_raw(vault)
              if r.get("source") == "manual"]
    edges = list(doc_edges.values()) + manual

    # Top-K 截断（人工边不截——人工声明优先）
    per = {}
    for e in edges:
        if e.get("source") == "manual":
            continue
        for d in (e["from"], e["to"]):
            per.setdefault(d, []).append(e)
    drop = set()
    for d, es in per.items():
        es.sort(key=lambda x: -x["weight"])
        for e in es[TOP_K:]:
            drop.add(id(e))
    edges = [e for e in edges if id(e) not in drop]

    _write_relations(vault, edges)
    names = dict(primary_docs(vault))
    return {"docs": n, "entities": len(ent_docs), "hubs": len(hubs),
            "edges": len(edges), "tier": prof["tier"], "names": names}


def _pg(doc, pages):
    p = pages[0] if pages else "?"
    return f"{doc[:8]} P{p}"


def _write_relations(vault, edges):
    os.makedirs(vault.meta, exist_ok=True)
    tmp = rel_path(vault) + ".tmp"
    ts = time.strftime("%F %T")
    with open(tmp, "w", encoding="utf-8") as f:
        for e in edges:
            rec = dict(e)
            rec.setdefault("ts", ts)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp, rel_path(vault))


def _load_relations_raw(vault):
    try:
        with open(rel_path(vault), encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except (OSError, ValueError):
        return []


def load_relations(vault):
    """读全部关系（tier 字段对外可见）。"""
    out = []
    for r in _load_relations_raw(vault):
        r.setdefault("tier", "internal-artifact")
        out.append(r)
    return out


# ------------------------------------------------------------ 人工阀门 ----
def load_bans(vault):
    return {tuple(x) for x in _read_json(ban_path(vault), []) or []}


def add_ban(vault, a, b):
    bans = {tuple(sorted([_norm_entity(a), _norm_entity(b)]))}
    existing = load_bans(vault)
    if bans <= existing:
        return False
    _write_json(ban_path(vault), sorted(existing | bans))
    # 已建的边立刻压制
    keep = [r for r in _load_relations_raw(vault)
            if not _banned_edge(r, existing | bans)]
    _write_relations(vault, keep)
    return True


def _banned_edge(edge, bans):
    ev = edge.get("evidence", "")
    for a, b in bans:
        if a in ev and b in ev and edge.get("source") != "manual":
            return True
    return False


def manual_link(vault, doc_a, doc_b, etype=TYPE_CITE):
    """人工显式关联（权重 0.8，doc 已由 CLI 解析成 doc_id）。"""
    edges = [r for r in _load_relations_raw(vault)
             if not (r.get("source") == "manual"
                     and {r["from"], r["to"]} == {doc_a, doc_b})]
    edges.append({"from": doc_a, "to": doc_b, "type": etype,
                  "weight": W_MANUAL, "evidence": "人工声明",
                  "source": "manual"})
    _write_relations(vault, edges)
    return True


# ------------------------------------------------------------ 查询 ----
def related(vault, doc_id):
    """某文档的全部关联（按权重降序）。"""
    return sorted([r for r in load_relations(vault)
                   if doc_id in (r.get("from"), r.get("to"))],
                  key=lambda r: -r.get("weight", 0))


def related_lines(vault, doc_id, name):
    """related 输出行（格式化在 service 层；空结果明示而非沉默）。

    命中即入精化队列（M1b §5.3：文档首次被 query/related 命中入队）。
    """
    from cenhua_service import refine as R
    edges = related(vault, doc_id)
    R.enqueue(vault, doc_id, reason="related")
    for e in edges:
        R.enqueue(vault, e["to"] if e["from"] == doc_id else e["from"],
                  reason="related")
    if not edges:
        return [f"related({name}): 无显著关联（正常——关联为空本身是信息；"
                f"人工声明: cenhua link）"]
    names = dict(primary_docs(vault))
    lines = [f"related({name}) — {len(edges)} edge(s), strongest first:"]
    for e in edges:
        other = e["to"] if e["from"] == doc_id else e["from"]
        oname = names.get(other, other)
        tag = "人工" if e.get("source") == "manual" else "自动"
        lines.append(f"  {e['weight']:.2f} [{e['type']}/{tag}] {oname}")
        lines.append(f"        evidence: {e.get('evidence', '')}")
    return lines
