#!/usr/bin/env python3
"""Precise numeric-identifier scan over cached PDFs (card/account/ID numbers).

Usage: python3 scan_number.py <digits...> [--fuzzy=9]
Env:   PI_STORE (default ~/.pageindex-rag/store)

Rules encoded here:
- digits are normalized (spaces/hyphens stripped) on both query and page text
  (OCR and bank exports love inserting separators every 4 digits)
- exact full-number match = hit; tail-8/tail-6 fragments = LEADS only, verify
  context before concluding (amounts can collide with card tails!)
- --fuzzy N (e.g. 9) adds sliding-window substring probing to tolerate OCR
  digit errors; report fuzzy hits as unconfirmed
"""
try: import _site  # local site defaults (no-op in published pkg)
except ImportError: pass

import os, sys, re, json
import pymupdf

STORE = os.environ.get("PI_STORE", os.path.expanduser("~/.pageindex-rag/store"))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
fuzzy = 0
for a in sys.argv[1:]:
    if a.startswith("--fuzzy"):
        fuzzy = int(a.split("=")[1]) if "=" in a else 9
ROOTS = [os.path.join(STORE, "pdf"), os.path.join(STORE, "docs")]

def norm(s):
    return re.sub(r"[\s\-]+", "", s)

variants = {}
for q in args:
    q = norm(q)
    vs = [q]
    if len(q) >= 10:
        vs += [q[-8:], q[-6:]]
    if fuzzy and len(q) > fuzzy:
        vs += [q[i:i+fuzzy] for i in range(len(q) - fuzzy + 1)]
    variants[q] = list(dict.fromkeys(vs))

seen, hits = set(), []
for base in ROOTS:
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
                if doc.needs_pass:
                    # try digit-runs in filename as password (common convention:
                    # exported bank PDFs embed the password in the filename)
                    if not any(doc.authenticate(x)
                               for x in re.findall(r"\d{4,12}", f)):
                        print(f"! encrypted, skipped: {f}", file=sys.stderr)
                        continue
            except Exception:
                continue
            for pno in range(len(doc)):
                t = doc[pno].get_text() or ""
                tn = norm(t)
                for raw, vs in variants.items():
                    for v in vs:
                        if v in tn:
                            lines = [l.strip() for l in t.splitlines()
                                     if v in norm(l)][:10]
                            hits.append({"query": raw, "variant": v,
                                         "exact": v == raw,
                                         "file": f, "page": pno + 1,
                                         "lines": lines})
                            break
            doc.close()

print(json.dumps(hits, ensure_ascii=False, indent=1))
print("PDFS_SCANNED:", len(seen))
for raw in variants:
    if not any(h["query"] == raw for h in hits):
        print("NO_HIT:", raw)
