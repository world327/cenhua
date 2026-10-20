"""cenhua_service.refine — deferred 总结的按需精化（M1b §5.3 任务 3-5）。

闭环：规则层（summaries.py，零 LLM）产出 rule-only -> 文档被 query/related
**首次命中**入队 `meta/refine_queue.jsonl` -> `cenhua refine --drain` 按预算
消费，LLM 精化升级为 status=refined。

三闸执法顺序（任务 4，全部启动前检查，all-or-nothing）：
  ① `--dry-run` 估价（不花钱，永远可用）
  ② 预算硬闸 `CENHUA_REFINE_BUDGET_CNY`（默认 0 = 默认拒绝，fail-closed）
  ③ `--force` 显式放行（越过 ②，仍全量记账）

批量任务豁免中途执法（F1）：drain 一旦通过启动前检查，逐篇执行不再
逐篇查预算；每篇完成即写 summaries + cost-ledger（全量记账 T5）。
单篇 LLM 失败：保留 rule-only、重新入队、继续下一篇（失败隔离）。

service 纪律：不 print/exit（test_70）；LLM 只在 refine_drain 内发生，
估价/队列/预算路径零网络。
"""

import json
import os
import time

from cenhua_service import summaries as S

QUEUE_NAME = "refine_queue.jsonl"
BUDGET_ENV = "CENHUA_REFINE_BUDGET_CNY"

# 精化 prompt：结构化 JSON 直接用 data（AGENTS.md 铁律），带 fallback 字段
PROMPT = (
    "你是文档摘要助手。基于下面的规则层粗提取，输出该文档的精炼总结。\n"
    "只输出一个 JSON 对象，不要其他文字：\n"
    '{{"summary": "80-200字中文摘要", '
    '"entities": ["关键实体，最多15个，保留原文写法"]}}\n\n'
    "文档名：{name}\n"
    "规则层标题：{title}\n"
    "规则层关键词：{keywords}\n"
    "规则层实体：{entities}\n"
    "正文（截断）：\n{text}\n"
)


def queue_path(vault):
    return os.path.join(vault.meta, QUEUE_NAME)


# ---------------------------------------------------------------- 队列 ----
def enqueue(vault, doc_id, reason="hit"):
    """文档首次被命中入队。已有未消费条目则跳过（幂等，防重复精化）。"""
    for item in pending(vault):
        if item["doc_id"] == doc_id:
            return False
    try:
        os.makedirs(vault.meta, exist_ok=True)
        with open(queue_path(vault), "a", encoding="utf-8") as f:
            f.write(json.dumps({"doc_id": doc_id, "reason": reason,
                                "ts": time.strftime("%F %T")},
                               ensure_ascii=False) + "\n")
    except OSError:
        return False
    return True


def pending(vault):
    """队列中仍未消费的条目（按 doc_id 去重，保首个 reason；
    已 refined 的自动出队）。"""
    try:
        with open(queue_path(vault), encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    seen, out = set(), []
    for ln in lines:
        try:
            item = json.loads(ln)
        except ValueError:
            continue
        did = item.get("doc_id")
        if not did or did in seen:
            continue
        seen.add(did)
        summ = S.load_summary(vault, did)
        if summ and summ.get("status") == S.STATUS_REFINED:
            continue                      # 已精化 -> 视为已消费
        out.append(item)
    return out


def _rewrite_queue(vault, remaining):
    """消费后重写队列文件（tmp + 原子 rename）。"""
    tmp = queue_path(vault) + ".tmp"
    os.makedirs(vault.meta, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        for item in remaining:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    os.replace(tmp, queue_path(vault))


# ---------------------------------------------------------------- 估价 ----
def estimate(vault, doc_ids):
    """按 summaries.tokens_estimate 估价。返回
    {"docs": n, "tokens_in": int, "tokens_out": int,
     "est_cost": float|None, "currency": str, "priced": bool, "note": str}
    """
    from cenhua_service import cost as C
    n = tin = tout = 0
    for did in doc_ids:
        summ = S.load_summary(vault, did)
        est = (summ or {}).get("tokens_estimate") or 0
        n += 1
        tin += est
        tout += max(150, est // 6)        # 摘要输出粗估
    model = os.environ.get("PI_MODEL", "openai/gpt-4o-mini")
    est_cost, currency, priced, note = C.estimate_cost(model, tin, tout)
    return {"docs": n, "tokens_in": tin, "tokens_out": tout,
            "est_cost": est_cost, "currency": currency,
            "priced": priced, "note": note, "model": model}


def budget_limit():
    """预算硬闸额度（CNY）。env 缺失/非法 -> 0（默认拒绝，fail-closed）。"""
    try:
        return float(os.environ.get(BUDGET_ENV, "0"))
    except ValueError:
        return 0.0


def budget_check(estimate_result, force=False):
    """三闸之 ②③。返回 (ok, message)。dry-run 不调用此闸（①在前）。

    预算以 CNY 计（CENHUA_REFINE_BUDGET_CNY）；模型报价可能是 USD 等，
    按保守汇率上限折 CNY 再比（闸只收紧不放松）。
    """
    limit = budget_limit()
    cost = estimate_result["est_cost"] or 0.0
    cur = estimate_result.get("currency", "CNY")
    rate = {"CNY": 1.0, "USD": 7.4, "EUR": 8.0, "GBP": 9.4}.get(cur, 7.4)
    cost_cny = cost * rate
    shown = f"{cost:.4f} {cur}" + (f" ≈¥{cost_cny:.4f}" if rate != 1.0 else "")
    if cost_cny <= limit:
        return True, f"within budget ({shown} <= ¥{limit:g})"
    if force:
        return True, (f"estimate {shown} exceeds budget ¥{limit:g}; "
                      f"--force overrides")
    return False, (f"estimate {shown} exceeds budget ¥{limit:g} "
                   f"({BUDGET_ENV}); raise the budget or pass --force")


# ------------------------------------------------------------ LLM 精化 ----
def call_llm(prompt, max_tokens=900, temperature=0.2):
    """OpenAI 兼容网关单轮调用。返回 (text, tokens_in, tokens_out)。
    失败抛异常（调用方做失败隔离）。refine/query 共用（M2b）。"""
    import os as _os
    from openai import OpenAI
    base = _os.environ.get("PI_BASE")
    key = _os.environ.get("PI_KEY")
    model = _os.environ.get("PI_MODEL", "openai/gpt-4o-mini")
    client = OpenAI(base_url=base, api_key=key, timeout=120)
    resp = client.chat.completions.create(
        model=model.replace("openai/", "") if base else model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens, temperature=temperature)
    text = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)
    return (text,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0)


# 兼容别名（M1b 内部调用仍走 _call_llm）
_call_llm = call_llm


def _parse_llm_json(text):
    """LLM 输出 -> dict；解析失败返回 None（走 fallback，不崩）。"""
    import re
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if isinstance(data, dict) and data.get("summary"):
        return data
    return None


def refine_one(vault, doc_id, read_text):
    """精化单篇。read_text(doc_id)->正文文本。

    返回 'refined' | 'fallback' | 'failed'（永不抛）：
      refined  : LLM 成功，status=refined
      fallback : LLM 有输出但 JSON 解析失败 -> 规则首段兜底，仍标 refined
      failed   : LLM 调用失败/无网关 -> 保持 rule-only（调用方负责留在队列）
    """
    from cenhua_service import cost as C
    summ = S.load_summary(vault, doc_id)
    if not summ:
        return "failed"
    text = read_text(doc_id) or ""
    if not text.strip():
        return "failed"
    prompt = PROMPT.format(
        name=summ.get("name", ""), title=summ.get("title", ""),
        keywords=", ".join(k["term"] for k in summ.get("keywords", [])[:10]),
        entities=json.dumps(summ.get("entities", {}), ensure_ascii=False)[:800],
        text=text[:6000])
    t0 = time.time()
    try:
        raw, tin, tout = _call_llm(prompt)
    except Exception:
        return "failed"
    parsed = _parse_llm_json(raw)
    if parsed:
        summary = str(parsed["summary"])[:1200]
        entities = [str(e) for e in (parsed.get("entities") or [])][:15]
        status = S.STATUS_REFINED
    else:
        # 非 LLM fallback（铁律）：解析失败用规则首段兜底，也算消费完成
        summary = summ.get("first_paragraph", "")[:600]
        entities = []
        status = S.STATUS_REFINED
    summ.update({"status": status,
                 "refined": {"summary": summary,
                             "entities_llm": entities,
                             "ts": time.strftime("%F %T"),
                             "model": os.environ.get("PI_MODEL", "")}})
    S.save_summary(vault, summ)
    est, currency, priced, _ = C.estimate_cost(
        os.environ.get("PI_MODEL", "openai/gpt-4o-mini"), tin, tout)
    C.ledger_append(vault, {"cmd": "refine", "doc": summ.get("name", "")[:200],
                            "calls": 1, "tokens_in": tin, "tokens_out": tout,
                            "est_cost": est, "currency": currency,
                            "priced": priced})
    vault.log("refine", [f"doc={doc_id} status={status} "
                         f"{time.time()-t0:.1f}s parse_ok={bool(parsed)}"])
    return "refined" if parsed else "fallback"


def drain(vault, read_text, doc_ids=None):
    """消费队列（或指定 doc_ids）。F1：启动前已过闸，中途不再执法。

    失败条目**保留在队列**（下次 drain 重试），成功条目出队。
    返回 {"refined": n, "fallback": n, "failed": n}。
    """
    queue_mode = doc_ids is None
    items = pending(vault) if queue_mode else []
    if queue_mode:
        doc_ids = [i["doc_id"] for i in items]
    counts = {"refined": 0, "fallback": 0, "failed": 0}
    failed = set()
    for did in doc_ids:
        r = refine_one(vault, did, read_text)
        counts[r] += 1
        if r == "failed":
            failed.add(did)
    if queue_mode:
        _rewrite_queue(vault, [i for i in items if i["doc_id"] in failed])
    return counts


# ------------------------------------------------------------ 输出行 ----
def dry_run_lines(vault, est, queue_len):
    """--dry-run 估价报告行（供 CLI 打印；格式化在 service 层）。"""
    from cenhua_service.cost import format_cost
    lines = [
        f"[refine] queue      : {queue_len} document(s) waiting",
        f"[refine] to spend   : {est['docs']} LLM call(s), "
        f"~{est['tokens_in']} in / ~{est['tokens_out']} out tokens",
        f"[refine] gateway    : {est['model']}",
        f"[refine] estimate   : "
        + format_cost([(est["est_cost"], est["currency"])])
        + ("" if est["priced"] else f"  ({est['note']})"),
        f"[refine] budget     : {budget_limit():g} CNY "
        f"({BUDGET_ENV}; 0 = refuse)",
    ]
    ok, msg = budget_check(est)
    lines.append(f"[refine] gate       : {'PASS' if ok else 'REFUSE'} — {msg}")
    lines.append("(dry run — nothing was sent)")
    return lines


def roi_lines(vault):
    """hint 二段验证 ROI 账（M3a 任务 13）。

    口径（dev-plan §6.3 任务 13 / R3 §4）：验证轮次（cmd=query 的 LLM 延展）
    token 开销计入 refine ROI 账——hint 省下的是导航成本，不能倒贴验证成本。
    refine=生产成本，query=验证成本，两行并排可见。零 print。
    """
    from cenhua_service import cost as C
    refine_parts, query_parts = [], []
    refine_calls = query_calls = 0
    hint_docs = hint_dropped = query_rounds = 0
    for r in C.read_ledger(vault):
        cmd = r.get("cmd")
        if cmd == "refine":
            refine_calls += r.get("calls", 0)
            refine_parts.append((r.get("est_cost", 0.0),
                                 r.get("currency", "CNY")))
        elif cmd == "query":
            query_calls += r.get("calls", 0)
            query_rounds += 1
            query_parts.append((r.get("est_cost", 0.0),
                                r.get("currency", "CNY")))
            hint_docs += r.get("hint_docs", 0)
            hint_dropped += r.get("hint_dropped", 0)
    lines = ["[ROI] hint 导航收益 vs 验证轮成本（cmd 台账口径）:"]
    lines.append(f"  refine 生产 : {refine_calls} calls  "
                 + C.format_cost(refine_parts))
    lines.append(f"  query 验证  : {query_calls} calls / {query_rounds} rounds  "
                 + C.format_cost(query_parts))
    lines.append(f"  hint 使用   : {hint_docs} doc-round(s), "
                 f"{hint_dropped} 祈使句已剔除")
    lines.append("  裁决口径    : 验证成本持续倒贴生产成本时，"
                 "重新评估 hint 段价值")
    return lines


def status_lines(vault):
    """无参状态报告行：rule-only/refined 覆盖 + 队列 + ROI 账。"""
    d = S.summaries_dir(vault)
    rule_only = refined = 0
    try:
        for fn in os.listdir(d):
            if fn.endswith(".json"):
                summ = S.load_summary(vault, fn[:-5])
                if summ and summ.get("status") == S.STATUS_REFINED:
                    refined += 1
                else:
                    rule_only += 1
    except OSError:
        pass
    q = len(pending(vault))
    return [f"summaries: {rule_only} rule-only, {refined} refined",
            f"queue    : {q} document(s) waiting",
            "usage    : cenhua refine --all --dry-run | --drain [--force]"] \
        + roi_lines(vault)


# ------------------------------------------------------------ 编排 ----
def read_text(vault, doc_id):
    """文本层读取（service 层自带，CLI 无需注入）。"""
    p = os.path.join(vault.textdir, doc_id + ".txt")
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def refine_flow(vault, do_all=False, dry=False, do_drain=False, force=False):
    """`cenhua refine` 主编排（三闸顺序：① dry-run → ② 预算 → ③ --force）。

    返回 (rc, lines)。零 print；打印归 CLI。
    """
    if not do_all and not do_drain:
        return 0, status_lines(vault)
    queue = pending(vault)
    est = estimate(vault, [i["doc_id"] for i in queue])
    if dry:                                            # ① 估价永远可用
        return 0, dry_run_lines(vault, est, len(queue))
    if not queue:
        return 0, ["= refine queue is empty "
                   "(documents join it after a query/related hit)"]
    ok, msg = budget_check(est, force=force)           # ②③ 启动前 all-or-nothing
    if not ok:
        return 4, [f"! REFUSED: {msg}"]
    lines = [f"~ draining {est['docs']} doc(s) — {msg}"]
    counts = drain(vault, lambda d: read_text(vault, d))
    lines.append(f"done: {counts['refined']} refined, "
                 f"{counts['fallback']} fallback(规则首段), "
                 f"{counts['failed']} failed(留在队列可重试)")
    return (1 if counts["failed"] else 0), lines
