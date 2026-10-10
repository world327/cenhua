#!/usr/bin/env python3
"""Exact-string scan of every PDF inside the PageIndex store (offline, no LLM).

Usage: python3 scan_corpus.py TERM [VARIANT2 VARIANT3 ...]
Env:   PI_STORE (default ~/.pageindex-rag/store)

Fallback for the text layer (use pi_query.py --grep first; this re-extracts
from PDFs and additionally covers PDFs whose pages.json is missing).

Encrypted-PDF pitfall: pymupdf open()+get_text() on a password-protected PDF
fails; a naive `except: continue` silently SKIPS those documents (we once
concluded "person not in corpus" while they were inside an encrypted bank
statement). This scanner tries the digit-runs found in the filename as the
password before giving up — PDFs exported from banks/apps often carry the
password in the filename.
"""
try: import _site  # local site defaults (no-op in published pkg)
except ImportError: pass

import os, re, sys, json
import pymupdf

STORE = os.environ.get("PI_STORE", os.path.expanduser("~/.pageindex-rag/store"))
targets = sys.argv[1:] or ["TODO"]

def try_passwords(doc, fname):
    if not doc.needs_pass:
        return True
    cands = re.findall(r"\d{4,12}", fname)
    for pwd in cands:
        if doc.authenticate(pwd):
            return True
    return False

hits, seen = [], set()
for sub in ("pdf", "docs"):
    base = os.path.join(STORE, sub)
    if not os.path.isdir(base):
        continue
    for root, _, files in os.walk(base):
        for f in files:
            if not f.lower().endswith(".pdf"):
                continue
            p = os.path.join(root, f)
            if p in seen:
                continue
            seen.add(p)
            try:
                doc = pymupdf.open(p)
                if not try_passwords(doc, f):
                    print(f"! encrypted, no filename-password worked: {f}",
                          file=sys.stderr)
                    continue
            except Exception:
                continue
            for pno in range(len(doc)):
                t = doc[pno].get_text() or ""
                for tg in targets:
                    if tg in t:
                        lines = [l.strip() for l in t.splitlines() if tg in l]
                        hits.append({"target": tg, "file": f, "page": pno + 1,
                                     "lines": lines[:10]})
            doc.close()
print(json.dumps(hits, ensure_ascii=False, indent=1))
print("PDF_SCANNED:", len(seen), file=sys.stderr)
