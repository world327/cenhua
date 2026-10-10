#!/usr/bin/env python3
"""m_search.py — CENHUA exact retrieval: `find` (offline grep) and `read`.

Routing rule inherited from the engine and NOT negotiable:
  grep for EXISTENCE, LLM for MEANING.
"Where does X appear, on which page" questions are answered here, exactly,
in milliseconds, with zero tokens. Never outsource existence questions to an
LLM — it silently misses.

`find` reads the flattened text layer (<vault>/engine/text/*.txt). If that
layer is stale the answer is silently wrong, so find auto-flattens when any
doc lacks text (offline, sub-second) and flags empty text layers.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_lib as L  # noqa: E402

MAX_HITS_PER_DOC = 15
CONTEXT = 0  # lines of context around a hit (page number already given)


def ensure_text_layer(vault):
    docs = L.store_docs(vault)
    have, missing, _ = L.text_status(vault)
    if docs and missing:
        L.say(f"~ {len(missing)} doc(s) missing text layer — flattening (offline) ...")
        rc, out = L.run_engine("pi_flatten.py", [], vault, capture=True)
        if rc != 0:
            L.err("! flatten failed: " + (out.strip().splitlines() or [""])[-1])
    _, missing, empty = L.text_status(vault)
    if empty:
        L.err(f"! WARNING: {len(empty)} doc(s) have an EMPTY text layer "
              f"(silently-blank PDF?). They are invisible to `find`. "
              f"Re-ingest originals or check with: cenhua doctor")
    return not missing


def find(vault, terms, docs_selector=None, max_per_doc=MAX_HITS_PER_DOC,
         regex=False, ignore_case=False):
    """Exact (or regex) scan of the text layer. terms: list of str."""
    if not terms:
        L.die("usage: cenhua find <term> [term2 ...]")
    ensure_text_layer(vault)
    if not os.path.isdir(vault.textdir) or not os.listdir(vault.textdir):
        L.say("(vault is empty or has no text layer — ingest first)")
        return 1

    if regex:
        try:
            pat = re.compile("|".join(f"(?:{t})" for t in terms),
                             0 if not ignore_case else re.IGNORECASE)
        except re.error as e:
            L.die(f"bad regex: {e}")
        mode = "regex"
    else:
        flags = re.IGNORECASE if ignore_case else 0
        pat = re.compile("|".join(re.escape(t) for t in terms), flags)
        mode = "exact"

    only = None
    if docs_selector:
        picked = L.resolve_docs(vault, docs_selector)
        if not picked:
            L.die(f"no doc matches '{docs_selector}' (see: cenhua list)")
        only = {d for d, _ in picked}

    docs = L.store_docs(vault)
    total_docs = total_hits = scanned = 0
    for fn in sorted(os.listdir(vault.textdir)):
        if not fn.endswith(".txt"):
            continue
        doc_id = fn[:-4]
        if only and doc_id not in only:
            continue
        scanned += 1
        lines = open(os.path.join(vault.textdir, fn),
                     encoding="utf-8", errors="ignore").read().splitlines()
        hits, page = [], "?"
        for l in lines:
            m = L.PAGE_RE.match(l.strip())
            if m:
                page = m.group(1) or m.group(2)
                continue
            if pat.search(l):
                hits.append((page, l.strip()))
        if not hits:
            continue
        total_docs += 1
        total_hits += len(hits)
        name = docs.get(doc_id, {}).get("name", doc_id)
        L.say(f"\n===== {name}  ({doc_id[:12]}...) — {len(hits)} hits =====")
        L.say(L.provenance(vault, doc_id, name))
        for pg, l in hits[:max_per_doc]:
            L.say(L.cite(vault, doc_id, pg, l[:200]))
        if len(hits) > max_per_doc:
            L.say(f"    ... {len(hits) - max_per_doc} more (read: cenhua read {doc_id[:8]})")
    L.say(f"\n[find/{mode}] {total_hits} hits in {total_docs}/{scanned} docs | "
          f"offline, exact, complete")
    if total_docs == 0:
        L.say("NOT FOUND is only trustworthy if every doc has a text layer "
              "(see cenhua doctor) and variants were tried "
              "(homophones, hyphen/space-stripped numbers).")
        return 1
    return 0


def read(vault, selector, page=None, grep=None):
    """Print raw pages of a document for verification before any conclusion."""
    picked = L.resolve_docs(vault, selector, limit=2)
    if not picked:
        L.die(f"no doc matches '{selector}' (see: cenhua list)")
    if len(picked) > 1:
        L.say("ambiguous — narrow it down:")
        for d, n in picked:
            L.say(f"  {d[:12]}...  {n}")
        return 1
    doc_id, name = picked[0]
    pages = L.text_pages(vault, doc_id)
    if not pages:
        L.die(f"no text layer for {name} — run: cenhua flatten")
    L.say(f"===== {name} ({doc_id[:12]}...) — {len(pages)} pages =====")
    L.say(L.provenance(vault, doc_id, name))
    for pno, text in pages:
        if page and str(pno) != str(page):
            continue
        if grep and not re.search(grep, text, re.I):
            continue
        L.say(f"\n--- page {pno} ---")
        L.say(text)
    if page:
        L.say(f"\n(page {page} shown; pages available: "
              f"{', '.join(str(p) for p, _ in pages)})")
    return 0


def list_docs(vault):
    docs = L.store_docs(vault)
    if not docs:
        L.say("(empty vault)")
        return
    have, _, _ = L.text_status(vault)
    for doc_id, d in sorted(docs.items(), key=lambda kv: kv[1].get("name", "")):
        flag = "" if doc_id in have else "  [NO TEXT LAYER]"
        L.say(f"{doc_id[:12]:<14} {d.get('name', '')}{flag}")
    L.say(f"total {len(docs)}")
