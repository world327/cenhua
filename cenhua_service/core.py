"""cenhua_service.core — 六核心函数 service 化（M3a 任务 2，契约 §3.5）。

ingest / find / query / related / ask / stats 全部以 dataclass 返回，
零 print / 零 exit（test_70 管辖）。CLI 层（m_*.py）只做参数解析 +
渲染（test_71 白名单管辖）。

设计裁决：
  * ingest 委托 m_ingest.ingest_one(quiet=True)——OCR/邮件展开/引擎子进程
    链是摄取固有形态，整体搬迁风险大收益零；quiet 模式即纯结果面。
  * find 是全 tier 存在性 grep（tier 降级是 query 的职责，find 不做）。
  * ask 的 citations 诚实留空：引擎 pi_query.py 输出是非结构化文本带
    Source: 行，结构化引文走 query 两段式路径；service 不编造 schema。
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

import m_lib as L  # noqa: E402

MAX_HITS_PER_DOC = 15


# ------------------------------------------------------------ dataclass ----
@dataclass
class IngestResult:
    status: str = "failed"         # "added"|"dupe"|"failed"
    doc_id: str = ""
    name: str = ""
    error: str = ""
    schema_version: int = 1


@dataclass
class FindHit:
    doc: str = ""
    name: str = ""
    page: str = "?"
    line: str = ""
    term: str = ""
    schema_version: int = 1


@dataclass
class Relation:
    from_doc: str = ""
    to_doc: str = ""
    type: str = ""
    weight: float = 0.0
    evidence: str = ""
    source: str = "auto"
    schema_version: int = 1


@dataclass
class VaultStats:
    name: str = ""
    title: str = ""
    docs: int = 0
    text_have: int = 0
    text_missing: int = 0
    text_empty: int = 0
    inbox_pending: int = 0
    failed_count: int = 0
    llm_calls_total: int = 0
    gateway_ready: bool = False
    model: str = ""
    schema_version: int = 1


@dataclass
class AskResult:
    answer: str = ""
    citations: list = field(default_factory=list)
    cost: Optional[dict] = None
    rc: int = 0
    lines: list = field(default_factory=list)
    error: str = ""
    schema_version: int = 2


@dataclass
class QueryResult:
    answer: str = ""
    citations: list = field(default_factory=list)
    cost: Optional[dict] = None
    rc: int = 0
    lines: list = field(default_factory=list)
    error: str = ""
    schema_version: int = 2


# ------------------------------------------------------------ ingest ----
def ingest(vault, path) -> IngestResult:
    """摄取单文件 -> IngestResult。引擎成功行里解析 doc_id；失败带原因。"""
    import m_ingest                      # 懒加载：避免 CLI 模块环
    name = os.path.basename(os.path.abspath(path))
    # 前置 sha1：dupe 场景 ingest_one 不给 doc_id，这里自查 dedupe 索引
    pre_doc = ""
    try:
        d = m_ingest.dedupe_index(vault)
        pre_doc = d.get(L.sha1(path), {}).get("doc_id", "")
    except (OSError, KeyError):
        pass
    status = m_ingest.ingest_one(vault, path, quiet=True)
    doc_id = ""
    if status in ("added", "dupe"):
        try:
            d = m_ingest.dedupe_index(vault)
            doc_id = d.get(L.sha1(path), {}).get("doc_id", "") or pre_doc
        except (OSError, KeyError):
            doc_id = pre_doc
    if status == "added":
        # 与 CLI add() 语义对齐：新文档立刻 rebuild 文本层，否则 find
        # 静默漏检（Web/API 上传后"搜不到"即源于此）。离线、增量、秒级。
        try:
            L.run_engine("pi_flatten.py", [], vault, capture=True)
        except Exception:               # flatten 失败不吞掉摄取成功的事实
            pass
    return IngestResult(status=status, doc_id=doc_id, name=name,
                        error="" if status != "failed" else "ingest failed")


# ------------------------------------------------------------ find ----
# 文本层扫描（M5-2 性能优化）：单文件扫描逻辑提取为顶层函数 _scan_file，
# 可被 multiprocessing.Pool 跨进程 pickle 调用。文档数超过阈值时用进程池
# 并行扫描（绕过 GIL——find 是纯 Python 文本扫描，多线程受 GIL 限制，
# 并发反而因锁竞争导致延迟暴涨，实测 2000 文档并发 4 时 p50 从 71ms 飙到
# 1477ms）。小库保持单进程（避免进程启动开销）。
FIND_MP_THRESHOLD_ENV = "CENHUA_FIND_MP_THRESHOLD"
FIND_MP_THRESHOLD_DEFAULT = 200
# 模块级复用进程池（M5-2）：避免每次 find 新建进程池的启动开销。
# multiprocessing.Pool.starmap 内部有锁，线程安全，可被 Web 多线程并发调用。
_FIND_POOL = None
_FIND_POOL_LOCK = None


def _get_find_pool():
    global _FIND_POOL, _FIND_POOL_LOCK
    if _FIND_POOL_LOCK is None:
        import threading
        _FIND_POOL_LOCK = threading.Lock()
    if _FIND_POOL is None:
        import multiprocessing
        with _FIND_POOL_LOCK:
            if _FIND_POOL is None:
                _FIND_POOL = multiprocessing.Pool()
    return _FIND_POOL


def _scan_file(textdir, fn, pat, docs, max_per_doc):
    """扫描单个文本层文件，返回该文件的 [FindHit]（供进程池调用）。"""
    doc_id = fn[:-4]
    page = "?"
    n_doc = 0
    hits = []
    try:
        fh = open(os.path.join(textdir, fn), encoding="utf-8",
                  errors="ignore")
    except OSError:
        return hits
    with fh:
        for l in fh:
            m = L.PAGE_RE.match(l.strip())
            if m:
                page = m.group(1) or m.group(2)
                continue
            mm = pat.search(l)
            if mm:
                if n_doc >= max_per_doc:
                    break
                n_doc += 1
                hits.append(FindHit(
                    doc=doc_id,
                    name=docs.get(doc_id, {}).get("name", doc_id),
                    page=page, line=l.strip()[:200],
                    term=mm.group(0)[:80]))
    return hits


def _find_mp_threshold():
    try:
        return int(os.environ.get(FIND_MP_THRESHOLD_ENV,
                                  FIND_MP_THRESHOLD_DEFAULT))
    except ValueError:
        return FIND_MP_THRESHOLD_DEFAULT


def find(vault, terms, docs_selector=None, max_per_doc=MAX_HITS_PER_DOC,
         regex=False, ignore_case=False) -> List[FindHit]:
    """文本层精确/正则扫描 -> [FindHit]（全 tier；存在性问题零 token）。

    terms 为空 -> []（CLI 负责 usage 提示，service 不 die）。
    文本层缺失的文档跳过（引擎层 flatten 由 CLI find 负责触发）。
    文档数 > CENHUA_FIND_MP_THRESHOLD（默认 200）时用进程池并行扫描，
    绕过 GIL 提升并发吞吐（M5-2）。
    """
    if not terms:
        return []
    if regex:
        try:
            pat = re.compile("|".join("(?:%s)" % t for t in terms),
                             0 if not ignore_case else re.IGNORECASE)
        except re.error:
            return []
    else:
        pat = re.compile("|".join(re.escape(t) for t in terms),
                         re.IGNORECASE if ignore_case else 0)

    only = None
    if docs_selector:
        if isinstance(docs_selector, (list, tuple)):
            docs_selector = ",".join(str(s) for s in docs_selector)
        picked = L.resolve_docs(vault, docs_selector)
        if not picked:
            return []
        only = {d for d, _ in picked}

    docs = L.store_docs(vault)
    if not os.path.isdir(vault.textdir):
        return []
    files = [fn for fn in sorted(os.listdir(vault.textdir))
             if fn.endswith(".txt")]
    if only:
        files = [fn for fn in files if fn[:-4] in only]
    if not files:
        return []

    # 大库：复用进程池并行扫描（绕过 GIL）；小库：单进程（避免进程开销）
    if len(files) >= _find_mp_threshold():
        try:
            pool = _get_find_pool()
            results = pool.starmap(
                _scan_file,
                [(vault.textdir, fn, pat, docs, max_per_doc)
                 for fn in files])
            hits: List[FindHit] = []
            for r in results:
                hits.extend(r)
            return hits
        except Exception:
            # 进程池失败（如受限环境）降级单进程，不吞掉检索能力
            pass

    hits: List[FindHit] = []
    for fn in files:
        hits.extend(_scan_file(vault.textdir, fn, pat, docs, max_per_doc))
    return hits


# ------------------------------------------------------------ query ----
def query(vault, question, include_derived=False, dry=False, force=False,
          top=3, session="", no_rerank=False) -> QueryResult:
    """四段检索（委托 query_flow），结构化返回。"""
    from cenhua_service import query as Q
    rc, lines = Q.query_flow(vault, question, include_derived=include_derived,
                             dry=dry, force=force, top=top, session=session,
                             no_rerank=no_rerank)
    return QueryResult(answer="\n".join(lines), lines=list(lines), rc=rc)


# ------------------------------------------------------------ related ----
def related(vault, doc) -> List[Relation]:
    """文档关联边（权重降序）。doc 支持选择器（resolve_docs 归一）。"""
    from cenhua_service import relations as REL
    doc_id = doc
    picked = L.resolve_docs(vault, doc, limit=1)
    if picked:
        doc_id = picked[0][0]
    out = []
    for e in REL.related(vault, doc_id):
        out.append(Relation(from_doc=e.get("from", ""),
                            to_doc=e.get("to", ""),
                            type=e.get("type", ""),
                            weight=float(e.get("weight", 0.0)),
                            evidence=e.get("evidence", ""),
                            source=e.get("source", "auto")))
    return out


# ------------------------------------------------------------ ask ----
def ask_estimate(vault, question, doc=None, all_docs=False,
                 limit=10) -> AskResult:
    """深读前置段（M3a 任务 4）：scope 解析 + 估价 + [cost] 渲染行，零副作用。

    rc=2 参数/范围错；成功时 cost=est（含 calls=n），lines 为 [cost] 全部
    渲染行（含 dry_run_cost_lines）。CLI 用它预取 n 决定是否交互确认；
    core.ask 内部复用同一实现（单一事实源）。
    """
    from cenhua_service import cost as CC
    if not question:
        return AskResult(rc=2, error="question required",
                         lines=["usage: ask(vault, question, doc=...|all_docs=True)"])
    if not doc and not all_docs:
        return AskResult(rc=2, error="scope required",
                         lines=["choose a scope: doc=<kw> or all_docs=True "
                                "(scoping is the cost control)"])
    env = L.build_env(vault)
    targets = (L.resolve_docs(vault, None, limit=limit) if all_docs
               else L.resolve_docs(vault, doc))
    if not targets:
        return AskResult(rc=2, error="no document matches",
                         lines=["no document matches "
                                "(selector=%s; see: cenhua list)" % (doc or "<all>")])
    n = len(targets)
    cap = vault.max_llm_calls()

    texts = []
    for d, _ in targets:
        p = os.path.join(vault.textdir, "%s.txt" % d)
        try:
            texts.append(open(p, encoding="utf-8", errors="ignore").read())
        except OSError:
            texts.append("x" * 6400)       # 无文本层按 4K tokens 保守估
    model = env.get("PI_MODEL", "openai/gpt-4o-mini")
    est = CC.estimate_docs(model, texts)
    est["calls"] = n                       # 1 call per doc，通道 add_cost 用

    # [cost] 前置说明行：文本与旧 CLI 逐字一致（test_cenhua ask 断言兼容）
    have, _missing, _empty = L.text_status(vault)
    stale = [d for d, _ in targets if d not in have]
    charged = (L.read_json(os.path.join(vault.meta, "llm_calls.json"),
                           {}) or {}).get("total", 0)
    pre = ["[cost] scope      : %s" % ("whole vault" if all_docs
                                       else "--doc " + (doc or "")),
           "[cost] documents  : %d" % n]
    for _d, name in targets[:20]:
        pre.append("           - %s" % name)
    if n > 20:
        pre.append("           ... %d more" % (n - 20))
    pre.append("[cost] LLM calls  : ~%d (1 per doc)   charged so far: %d"
               % (n, charged))
    pre.append("[cost] gateway    : %s @ %s"
               % (env.get("PI_MODEL", "openai/gpt-4o-mini"),
                  env.get("PI_BASE", "(PI_BASE unset)")))
    pre.append("[cost] ceiling    : %d calls/run "
               "(raise: cenhua config max_llm_calls=<n>)" % cap)
    if stale:
        pre.append("[cost] note       : %d target(s) lack a text layer — "
                   "deep read still works (it uses the tree index)"
                   % len(stale))
    pre.append("[cost] cheaper    : cenhua find <terms> first; grep for "
               "existence, LLM for meaning")
    pre += CC.dry_run_cost_lines(vault, est)
    return AskResult(rc=0, cost=est, lines=pre)


def ask(vault, question, doc=None, all_docs=False, limit=10,
        dry_run=False, force=False, workers=None, confirm=None) -> AskResult:
    """LLM 深读（service 原生流：scope→估价→闸门→确认→引擎→记账）。

    rc 语义与 CLI 对齐：0 成功；1 用户放弃；2 参数错；3 网关未配置；
    4 预算/上限拒绝。引擎 stdout 全文进 answer/lines；citations 诚实留空
    （见模块 docstring）。confirm(n)->bool 由 CLI 注入交互确认（三闸通过、
    引擎调用前执行；service 层不做 tty/stdin 假设）。
    """
    from cenhua_service import cost as CC
    pre_res = ask_estimate(vault, question, doc=doc, all_docs=all_docs,
                           limit=limit)
    if pre_res.rc:
        return pre_res
    est, pre = pre_res.cost, pre_res.lines
    n = est.get("calls", 0)
    env = L.build_env(vault)
    targets = (L.resolve_docs(vault, None, limit=limit) if all_docs
               else L.resolve_docs(vault, doc))
    cap = vault.max_llm_calls()

    if dry_run:
        return AskResult(rc=0, cost=est,
                         lines=pre + ["", "(dry run — nothing was sent)"])
    ok, gate = CC.cost_gate(vault, est, force=force)
    if not ok:
        return AskResult(rc=4, cost=est, error=gate,
                         lines=pre + ["refusing: %s" % gate])
    if n > cap and not force:
        msg = ("%d calls exceeds the per-run ceiling %d. Narrow scope "
               "or pass force." % (n, cap))
        return AskResult(rc=4, cost=est, error=msg,
                         lines=pre + ["refusing: %s" % msg])
    if not L.chat_ready(env):
        return AskResult(rc=3, cost=est,
                         error="LLM gateway not configured (PI_BASE/PI_KEY)",
                         lines=pre + ["LLM gateway not configured"])
    if confirm is not None:
        try:
            agreed = bool(confirm(n))
        except Exception:
            agreed = False
        if not agreed:
            return AskResult(rc=1, cost=est,
                             lines=pre + ["aborted (nothing spent)"])

    args = (["--all", question, "--limit", n] if all_docs
            else ["--doc", doc, question])
    if workers:
        args += ["--workers", workers]
    t0 = time.time()
    rc, out = L.run_engine("pi_query.py", args, vault, capture=True)
    vault.log("query", ["mode=%s" % ("--all" if all_docs else "--doc " + (doc or "")),
                        "question=%s" % question,
                        "calls=%d rc=%d %.0fs" % (n, rc, time.time() - t0)])
    lines = (out or "").strip().splitlines()
    if rc == 0:
        try:                                # 命中入精化队列（失败隔离）
            from cenhua_service import refine as R
            for d, _ in targets:
                R.enqueue(vault, d, reason="ask")
        except Exception:
            pass
        # 台账（ledger）由 CLI 侧 m_ask.record 统一记（含 llm_calls.json
        # total），service 层不重复记账，避免一次深读两条台账。
    return AskResult(answer="\n".join(lines), lines=pre + lines, rc=rc,
                     cost=est)


# ------------------------------------------------------------ stats ----
def stats(vault) -> VaultStats:
    """库统计（纯读取；渲染走 stats_lines）。"""
    cfg = vault.cfg()
    docs = L.store_docs(vault)
    have, missing, empty = L.text_status(vault)
    inbox = ([f for f in os.listdir(vault.inbox)
              if os.path.isfile(os.path.join(vault.inbox, f))]
             if os.path.isdir(vault.inbox) else [])
    fail = os.listdir(vault.failed) if os.path.isdir(vault.failed) else []
    cost = L.read_json(os.path.join(vault.meta, "llm_calls.json"),
                       {"total": 0}) or {"total": 0}
    env = L.build_env(vault)
    return VaultStats(
        name=vault.name, title=cfg.get("title", ""), docs=len(docs),
        text_have=len(have), text_missing=len(missing), text_empty=len(empty),
        inbox_pending=len(inbox), failed_count=len(fail),
        llm_calls_total=cost.get("total", 0),
        gateway_ready=L.chat_ready(env),
        model=env.get("PI_MODEL", ""))


def channel_job(kind, fn, *args, **kwargs):
    """长任务 → 任务通道统一适配（M3a 任务 4，契约 §3.5）。

    fn 须返回带 lines/cost 字段的 dataclass（AskResult/QueryResult/
    DigestResult…）；body 逐行 emit 到 JobRuntime.chunks，cost 映射
    add_cost。CLI 端 jobs.submit + run_cli 打印，Web/API 轮询同一协议。
    """
    from cenhua_service import jobs as J

    def _body(rt):
        rt.progress(0.05)                   # 启动信号：闸门/引擎即将执行
        result = fn(*args, **kwargs)
        for line in (getattr(result, "lines", None) or []):
            rt.emit(line)
        c = getattr(result, "cost", None) or {}
        if c:
            rt.add_cost(calls=int(c.get("calls", c.get("docs", 0)) or 0),
                        cost=float(c.get("est_cost", 0.0) or 0.0),
                        currency=c.get("currency", ""))
        rt.progress(1.0)
        return result

    return J.JobSpec(kind=kind, run=_body, meta={"fn": getattr(fn, "__name__", "fn")})


def stats_lines(vault, st: Optional[VaultStats] = None) -> List[str]:
    """VaultStats -> 渲染行（CLI 消费；与 m_vault.status 头部对齐）。"""
    st = st or stats(vault)
    lines = [
        "vault      : %s — %s" % (st.name, st.title),
        "documents  : %d indexed" % st.docs,
        "text layer : %d ready / %d missing / %d empty"
        % (st.text_have, st.text_missing, st.text_empty),
        "inbox      : %d pending" % st.inbox_pending,
        "llm calls  : %d charged by this CLI (cap/run: %d)"
        % (st.llm_calls_total, vault.max_llm_calls()),
        "llm gateway: %s  model=%s" % (
            "ready" if st.gateway_ready else "NOT configured",
            st.model or "-"),
    ]
    if st.failed_count:
        lines.insert(4, "FAILED     : %d file(s) -> check logs/"
                    % st.failed_count)
    return lines
