#!/usr/bin/env python3
"""m_ingest.py — CENHUA intake loop: inbox -> engine -> text layer -> ready.

The one habit this CLI removes: the engine requires `pi_flatten.py` after every
ingest, and forgetting it makes `find` silently miss new documents. Here,
flatten runs automatically after any successful ingest (flatten is offline,
incremental and sub-second, so this is free).

Isolation rule: one engine subprocess per file. A crash/OCR timeout in one
document can never strand the rest of the batch; failures land in
inbox/.failed/ with the reason in logs/ingest-*.log.

Dedupe: CENHUA keeps meta/dedupe.json (sha1 -> doc_id) on top of the engine's
own sha1 dedupe, so re-dropping the same file is a no-op (no LLM call, no
double billing).
"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_lib as L  # noqa: E402

ADDED_RE = re.compile(r"^\+\s(.+?)\s->\s(\S+)\s")


def dedupe_index(vault):
    return L.read_json(os.path.join(vault.meta, "dedupe.json"), {}) or {}


def save_dedupe(vault, d):
    os.makedirs(vault.meta, exist_ok=True)
    import json
    with open(os.path.join(vault.meta, "dedupe.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def sync_dedupe(vault):
    """Rebuild the dedupe index from the engine ledger (self-healing)."""
    led = L.read_json(os.path.join(vault.store, "ingest_manifest.json"), {}) or {}
    d = dedupe_index(vault)
    for doc_id, rec in led.items():
        if rec.get("sha1") and rec["sha1"] not in d:
            d[rec["sha1"]] = {"doc_id": doc_id, "name": rec.get("name", "")}
    save_dedupe(vault, d)
    return d


def ingest_one(vault, path, quiet=False):
    """Returns 'added' | 'dupe' | 'failed'. Never raises.

    Only files that live INSIDE the inbox get moved to .processed/.failed
    staging; explicitly-added files stay where the user put them.
    """
    path = os.path.abspath(path)
    name = os.path.basename(path)
    in_inbox = os.path.dirname(path) == os.path.abspath(vault.inbox)

    def stage(src, dstdir, suffix=""):
        return L.move_into(src, dstdir, suffix) if in_inbox else src

    if not L.is_supported(path):
        L.err(f"! skipped (unsupported extension): {name}")
        stage(path, vault.failed, suffix="_unsupported")
        return "failed"
    try:
        digest = L.sha1(path)
    except OSError as e:
        L.err(f"! unreadable: {name} ({e})")
        return "failed"

    d = dedupe_index(vault)
    if digest in d:
        if not quiet:
            L.say(f"= already in vault: {name} (doc_id={d[digest]['doc_id'][:12]}...)")
        stage(path, vault.processed)
        return "dupe"

    t0 = time.time()
    if not quiet:
        L.say(f"> ingesting {name} ... (tree index: minutes for long PDFs; "
              f"logs -> {vault.logs})")
    rc, out = L.run_engine("pi_ingest.py", [path], vault, capture=True)
    vault.log("ingest", out.strip().splitlines() or [f"(no output, rc={rc})"])
    m = ADDED_RE.search(out)
    if rc == 0 and m:
        doc_id = m.group(2)
        d[digest] = {"doc_id": doc_id, "name": name, "ts": time.strftime("%F %T")}
        save_dedupe(vault, d)
        stage(path, vault.processed)
        if not quiet:
            L.say(f"+ {name} -> doc_id {doc_id}  ({time.time()-t0:.0f}s)")
            L.say(f"  {L.provenance(vault, doc_id, name)}")
        return "added"
    if "= already indexed" in out:
        stage(path, vault.processed)
        if not quiet:
            L.say(f"= already in vault (engine dedupe): {name}")
        return "dupe"
    reason = (out.strip().splitlines() or [f"exit {rc}"])[-1]
    dest = stage(path, vault.failed, suffix="_failed")
    where = f" kept for retry at {dest}" if in_inbox else ""
    L.err(f"x FAILED {name}: {reason}{where}")
    return "failed"


def add(vault, paths, use_inbox=False, flatten=True):
    """Explicit add of files/dirs, or drain the inbox with --inbox."""
    queue = []
    if use_inbox:
        queue += L.pending(vault.inbox)
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            queue += [os.path.join(r, f)
                      for r, _, fs in os.walk(p) for f in sorted(fs)
                      if not any(part.startswith(".") for part in r.split(os.sep))]
        elif os.path.isfile(p):
            queue.append(p)
        else:
            L.err(f"! not found: {p}")

    if not queue:
        L.say("= inbox is empty (drop files into the inbox, then: cenhua add --inbox)")
        return 0

    sync_dedupe(vault)
    L.say(f"~ {len(queue)} file(s) to process in vault '{vault.name}'")
    counts = {"added": 0, "dupe": 0, "failed": 0}
    for path in queue:
        counts[ingest_one(vault, path)] += 1

    if flatten and counts["added"]:
        rc, out = L.run_engine("pi_flatten.py", [], vault, capture=True)
        L.say(f"~ text layer: {out.strip().splitlines()[-1] if out.strip() else 'done'}")
        if rc != 0:
            L.err("! flatten reported a problem — run: cenhua flatten")
    L.say(f"\ndone: +{counts['added']} new, = {counts['dupe']} dupes, "
          f"x{counts['failed']} failed")
    if counts["added"]:
        L.say(f"next: cenhua find <keyword>   (instant, offline)")
        L.say(f"      cenhua ask --all \"<question>\" --dry-run   (LLM, cost-checked)")
    return 1 if counts["failed"] else 0


def watch(vault, interval=5.0, once=False, idle_rounds=10):
    """Poll the inbox; ingest files whose size has been stable for one round.
    A partially-copied large file therefore never gets grabbed mid-write.
    `--once` drains and exits; otherwise runs until interrupted (or --rounds)."""
    L.say(f"watching {vault.inbox} every {interval:.0f}s (Ctrl-C to stop)")
    stable, rounds, idle = {}, 0, 0
    while True:
        files = L.pending(vault.inbox)
        ready = []
        for f in files:
            try:
                size = os.path.getsize(f)
            except OSError:
                continue
            if (once or stable.get(f) == size) and size > 0:
                # --once = drain now; otherwise require a size-stable round so a
                # partially-copied large file is never grabbed mid-write.
                ready.append(f)
            stable[f] = size
        for f in list(stable):
            if f not in files and f not in ready:
                stable.pop(f, None)

        if ready:
            idle = 0
            sync_dedupe(vault)
            n = 0
            for f in ready:
                if ingest_one(vault, f) == "added":
                    n += 1
            if n:
                L.run_engine("pi_flatten.py", [], vault, capture=True)
                L.say(f"+ {n} document(s) indexed and searchable")
        else:
            idle += 1
        rounds += 1
        if once:
            break
        if idle_rounds and idle >= idle_rounds:
            L.say(f"= inbox quiet for {idle} rounds — exiting (relaunch: cenhua watch)")
            break
        time.sleep(interval)
