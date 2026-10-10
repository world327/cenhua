#!/usr/bin/env python3
# pi_flatten.py — export a plain-text page layer from PageIndex doc stores.
try: import _site  # local site defaults (no-op in published pkg)
except ImportError: pass

# Reads <PI_STORE>/docs/<doc_id>/pages.json (already-extracted per-page text,
# captured at ingest time) and writes <PI_STORE>/text/<doc_id>.txt with
# "=== PAGE n ===" markers for the grep layer. Incremental: only rebuilds when
# pages.json/doc.json is newer than the .txt (or --force).
#
# Env: PI_STORE (default ~/.pageindex-rag/store)
# Usage: pi_flatten.py [--force]
import os, json, sys, time

STORE = os.environ.get("PI_STORE", os.path.expanduser("~/.pageindex-rag/store"))
TEXT_DIR = os.path.join(STORE, "text")

def main():
    force = "--force" in sys.argv
    os.makedirs(TEXT_DIR, exist_ok=True)
    manifest = os.path.join(STORE, "manifest.json")
    if not os.path.exists(manifest):
        sys.exit(f"no index store at {STORE} (missing manifest.json)")
    docs = json.load(open(manifest))["docs"]
    t0 = time.time()
    made = skip = miss = 0
    for doc_id in docs:
        d = os.path.join(STORE, "docs", doc_id)
        pj = os.path.join(d, "pages.json")
        dj = os.path.join(d, "doc.json")
        out = os.path.join(TEXT_DIR, f"{doc_id}.txt")
        if not os.path.exists(pj):
            miss += 1
            print(f"! no pages.json: {doc_id}")
            continue
        if not force and os.path.exists(out) and os.path.getmtime(out) >= max(
                os.path.getmtime(pj),
                os.path.getmtime(dj) if os.path.exists(dj) else 0):
            skip += 1
            continue
        pages = json.load(open(pj, encoding="utf-8"))
        parts = []
        # tolerate list[str] / list[dict] / {"pages": [...]} shapes.
        # Known PageIndex field names: markdown / page_index (NOT content/page).
        if isinstance(pages, dict):
            pages = pages.get("pages", [])
        for i, pg in enumerate(pages):
            if isinstance(pg, dict):
                content = (pg.get("markdown") or pg.get("content")
                           or pg.get("text") or "")
                pno = pg.get("page_index") or pg.get("page") or (i + 1)
            else:
                content, pno = str(pg), i + 1
            parts.append(f"=== PAGE {pno} ===\n{content}")
        open(out, "w", encoding="utf-8").write("\n".join(parts))
        made += 1
    print(f"done: rebuilt {made}, skipped {skip}, missing pages {miss} "
          f"| {time.time()-t0:.1f}s | {TEXT_DIR}")

if __name__ == "__main__":
    main()
