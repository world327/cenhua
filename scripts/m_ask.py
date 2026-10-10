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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_lib as L  # noqa: E402


def cost_file(vault):
    return os.path.join(vault.meta, "llm_calls.json")


def charged(vault):
    return (L.read_json(cost_file(vault), {}) or {}).get("total", 0)


def record(vault, n, mode, docs):
    path = cost_file(vault)
    data = L.read_json(path, {}) or {}
    data["total"] = data.get("total", 0) + n
    data.setdefault("runs", []).append(
        {"ts": time.strftime("%F %T"), "calls": n, "mode": mode, "docs": docs})
    data["runs"] = data["runs"][-200:]
    os.makedirs(vault.meta, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def ask(vault, question, doc=None, all_docs=False, limit=10, workers=None,
        dry_run=False, yes=False, force=False):
    if not question:
        L.die('usage: cenhua ask --doc <kw> "your question"  |  cenhua ask --all "..."')
    if not doc and not all_docs:
        L.die("choose a scope: --doc <name-keyword[,kw2]> or --all "
              "(scoping is the cost control — start narrow)")

    env = L.build_env(vault)
    targets = (L.resolve_docs(vault, None, limit=limit) if all_docs
               else L.resolve_docs(vault, doc))
    if not targets:
        L.die(f"no document matches (selector={doc or '<all>'}; see: cenhua list)")
    n = len(targets)
    cap = vault.max_llm_calls()
    have, missing, _ = L.text_status(vault)
    stale = [d for d, _ in targets if d not in have]

    L.say(f"[cost] scope      : {'whole vault' if all_docs else '--doc ' + doc}")
    L.say(f"[cost] documents  : {n}")
    for d, name in targets[:20]:
        L.say(f"           - {name}")
    if n > 20:
        L.say(f"           ... {n - 20} more")
    L.say(f"[cost] LLM calls  : ~{n} (1 per doc)   charged so far: {charged(vault)}")
    L.say(f"[cost] gateway    : {env.get('PI_MODEL', 'openai/gpt-4o-mini')} "
          f"@ {env.get('PI_BASE', '(PI_BASE unset)')}")
    L.say(f"[cost] ceiling    : {cap} calls/run "
          f"(raise: cenhua config max_llm_calls=<n>)")
    if stale:
        L.say(f"[cost] note       : {len(stale)} target(s) lack a text layer — "
              f"deep read still works (it uses the tree index)")
    L.say(f"[cost] cheaper    : cenhua find <terms> first; grep for existence, "
          f"LLM for meaning")

    if dry_run:
        L.say("\n(dry run — nothing was sent)")
        return 0
    if n > cap and not force:
        L.die(f"refusing: {n} calls exceeds the per-run ceiling {cap}. "
              f"Narrow with --doc, lower --limit, or pass --force.", code=4)
    if not L.chat_ready(env):
        L.die("LLM gateway not configured: export PI_BASE and PI_KEY "
              "(find/read/flatten work without them)", code=3)
    if n > 3 and not yes:
        if not sys.stdin.isatty():
            L.die(f"{n} LLM calls pending and stdin is not a tty — "
                  f"pass --yes to confirm", code=4)
        if L.ask_user(f"spend ~{n} LLM calls? type 'yes' to proceed") != "yes":
            L.say("aborted (nothing spent)")
            return 1

    args = (["--all", question, "--limit", n] if all_docs
            else ["--doc", doc, question])
    if workers:
        args += ["--workers", workers]
    L.say(f"\n> deep read: {n} doc(s), parallel threads ... this takes a while")
    t0 = time.time()
    rc, _ = L.run_engine("pi_query.py", args, vault)
    vault.log("query", [f"mode={'--all' if all_docs else '--doc ' + (doc or '')}",
                        f"question={question}", f"calls={n} rc={rc} "
                        f"{time.time()-t0:.0f}s"])
    if rc == 0:
        record(vault, n, "all" if all_docs else "doc",
               [name for _, name in targets][:30])
        L.say(f"\n[ask] {n} LLM call(s) used | {time.time()-t0:.0f}s | "
              f"every answer above carries a 'Source:' line — open the archived "
              f"original to verify before you publish")
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
