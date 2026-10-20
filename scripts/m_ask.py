#!/usr/bin/env python3
"""m_ask.py — CENHUA deep read: tree-navigation LLM Q&A with a cost guardrail.

One `ask` costs exactly one LLM round per selected document (the engine does
tree navigation + answer per doc). Across a big vault that is dozens of calls
and minutes of wall time, so CENHUA:
  * estimates the cost BEFORE spending anything (`--dry-run`),
  * enforces a per-run ceiling (`max_llm_calls` in vault.yaml, default 8),
  * keeps a running counter in meta/llm_calls.json.

Escalation ladder (cheapest first):
  cenhua find  ->  cenhua ask --doc <kw>  ->  cenhua seek  ->  cenhua ask --all
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))            # scripts/
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # ROOT(cenhua_service/)
import m_lib as L  # noqa: E402


def cost_file(vault):
    return os.path.join(vault.meta, "llm_calls.json")


def charged(vault):
    return (L.read_json(cost_file(vault), {}) or {}).get("total", 0)


def record(vault, n, mode, docs, est=None):
    """深读成功后的本地记账：llm_calls.json total + runs + cost-ledger。

    est 为 core.ask_estimate 的估价 dict（含 est_cost/currency/priced），
    None 时按未定价 0 元占位（保持旧行为兜底）。
    """
    path = cost_file(vault)
    data = L.read_json(path, {}) or {}
    data["total"] = data.get("total", 0) + n
    data.setdefault("runs", []).append(
        {"ts": time.strftime("%F %T"), "calls": n, "mode": mode, "docs": docs})
    data["runs"] = data["runs"][-200:]
    os.makedirs(vault.meta, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    # 全量记账（T5）：写 cost-ledger.jsonl（M3a：est 用真实估价）
    try:
        from cenhua_service import cost as C
        e = est or {}
        C.ledger_append(vault, {
            "cmd": "ask", "doc": ",".join(docs)[:200], "calls": n,
            "tokens_in": int(e.get("tokens_in", 0) or 0),
            "tokens_out": int(e.get("tokens_out", 0) or 0),
            "est_cost": float(e.get("est_cost", 0.0) or 0.0),
            "currency": e.get("currency", "CNY"),
            "priced": bool(e.get("priced", False)),
        })
    except Exception:
        pass


def _confirm_gate(vault, n, yes):
    """三闸通过后的人工确认（CLI 层职责：tty/stdin 假设不进 service）。"""
    if n <= 3 or yes:
        return True
    if not sys.stdin.isatty():
        L.die(f"{n} LLM calls pending and stdin is not a tty — "
              f"pass --yes to confirm", code=4)
    if L.ask_user(f"spend ~{n} LLM calls? type 'yes' to proceed") != "yes":
        L.say("aborted (nothing spent)")
        return False
    return True


def ask(vault, question, doc=None, all_docs=False, limit=10, workers=None,
        dry_run=False, yes=False, force=False):
    """`cenhua ask` CLI：估价/三闸/确认在 CLI 层，引擎执行走任务通道（M3a）。

    前置段与闸门委托 core.ask_estimate / service 纯函数（单一事实源）；
    引擎调用经 channel_job 进 jobs 通道，run_cli 增量打印 + 进度/心跳。
    """
    from cenhua_service import core as C
    from cenhua_service import cost as CC
    from cenhua_service import jobs as J

    if not question:
        L.die('usage: cenhua ask --doc <kw> "your question"  |  '
              'cenhua ask --all "..."')
    if not doc and not all_docs:
        L.die("choose a scope: --doc <name-keyword[,kw2]> or --all "
              "(scoping is the cost control — start narrow)")
    pre = C.ask_estimate(vault, question, doc=doc, all_docs=all_docs,
                         limit=limit)
    if pre.rc:
        for line in pre.lines:
            L.err(line)
        L.die(pre.error or "ask: bad request")
    est = pre.cost
    n = est.get("calls", 0)
    cap = vault.max_llm_calls()

    if dry_run:
        for line in pre.lines:
            L.say(line)
        L.say("\n(dry run — nothing was sent)")
        return 0

    ok, gate = CC.cost_gate(vault, est, force=force)
    if not ok:
        L.die(f"refusing: {gate}", code=4)
    if n > cap and not force:
        L.die(f"refusing: {n} calls exceeds the per-run ceiling {cap}. "
              f"Narrow with --doc, lower --limit, or pass --force.", code=4)
    if not L.chat_ready(L.build_env(vault)):
        L.die("LLM gateway not configured: export PI_BASE and PI_KEY "
              "(find/read/flatten work without them)", code=3)
    if not _confirm_gate(vault, n, yes):
        return 1

    # ---- 引擎执行进任务通道（M3a 任务 4）：chunks = [cost] 段 + 引擎输出 ----
    L.say(f"\n> deep read: {n} doc(s), parallel threads ... this takes a while")
    spec = C.channel_job(
        "ask", C.ask, vault, question,
        doc=doc, all_docs=all_docs, limit=limit, force=force,
        workers=workers, confirm=lambda k: True)
    handle = J.submit(spec)
    printed = [0]
    plen = len(pre.lines)

    def _print(line):
        if printed[0] < plen:                # 前置段 CLI 已打过，通道副本跳过
            printed[0] += 1
            return
        L.say(line)

    st = J.run_cli(handle, _print)
    try:
        res = J.job_result(handle)
    except (J.JobFailed, J.JobStale) as exc:
        L.die(f"ask: {exc}", code=1)
    rc = res.rc if st.state != J.ABORTED else 1
    if rc == 0:
        targets = (L.resolve_docs(vault, None, limit=limit) if all_docs
                   else L.resolve_docs(vault, doc))
        record(vault, n, "all" if all_docs else "doc",
               [name for _, name in targets][:30], est=est)
        L.say(f"\n[ask] {n} LLM call(s) used | every answer above carries a "
              f"'Source:' line — open the archived original to verify "
              f"before you publish")
    return rc


def flatten(vault, force=False):
    """Rebuild the local text layer (offline, incremental). find depends on it."""
    args = ["--force"] if force else []
    rc, out = L.run_engine("pi_flatten.py", args, vault, capture=True)
    L.say(out.strip())
    if rc == 0:
        have, missing, empty = L.text_status(vault)
        L.say(f"text layer: {len(have)} docs ready"
              + (f", {len(missing)} missing" if missing else "")
              + (f", {len(empty)} EMPTY (re-ingest!)" if empty else ""))
    return rc
