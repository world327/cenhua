#!/usr/bin/env python3
# pi_query.py — PageIndex query CLI: instant local text grep + parallel LLM chat.
try: import _site  # local site defaults (no-op in published pkg)
except ImportError: pass

#
# Query routing rule: exact names/keywords/numbers => --grep (local, ms, free).
# Only summaries / cross-page reasoning => --doc / --all (LLM).
#
# Env config:
#   PI_STORE    index storage dir                (default ~/.pageindex-rag/store)
#   PI_BASE     OpenAI-compatible base URL       (required for LLM modes)
#   PI_KEY      API key                          (required for LLM modes)
#   PI_MODEL    chat model 'openai/<name>'       (default openai/gpt-4o-mini)
#   PI_BASE2 / PI_KEY2 / PI_MODEL2               optional 2nd gateway (failover)
#   PI_TIMEOUT  per-request timeout seconds      (default 90)
#   PI_RETRIES  SDK max retries                  (default 1)
#   PI_WORKERS  parallel doc-threads             (default 5)
#   PI_SRC_CSV  optional csv with a doc_id column mapping docs to source files
#
# Usage:
#   pi_query.py --list
#   pi_query.py --grep term1 term2 ...              # local text layer, no LLM
#   pi_query.py --doc "kw1,kw2" "your question?"    # select docs by name (OR), chat
#   pi_query.py --all "your question?" --limit 20   # across corpus, parallel
#   pi_query.py --src kw                            # doc -> source file mapping only
import os, sys, json, csv, argparse, re
from concurrent.futures import ThreadPoolExecutor, as_completed

STORE = os.environ.get("PI_STORE", os.path.expanduser("~/.pageindex-rag/store"))
TEXT_DIR = os.path.join(STORE, "text")
CSV_MAP = os.environ.get("PI_SRC_CSV", "")
REQ_TIMEOUT = float(os.environ.get("PI_TIMEOUT", "90"))
MAX_RETRIES = int(os.environ.get("PI_RETRIES", "1"))

def gateways():
    """Primary gateway + optional second gateway for failover."""
    base = os.environ.get("PI_BASE")
    key = os.environ.get("PI_KEY")
    if not base or not key:
        sys.exit("PI_BASE and PI_KEY env vars are required for LLM modes "
                 "(--grep/--list/--src work offline)")
    gws = [{"name": "gw1", "base": base, "key": key,
            "model": os.environ.get("PI_MODEL", "openai/gpt-4o-mini")}]
    if os.environ.get("PI_BASE2") and os.environ.get("PI_KEY2"):
        gws.append({"name": "gw2", "base": os.environ["PI_BASE2"],
                    "key": os.environ["PI_KEY2"],
                    "model": os.environ.get("PI_MODEL2", gws[0]["model"])})
    return gws

def load_docs():
    """doc_id -> display name. PageIndex manifest.json is authoritative for
    which docs are indexed; ingest_manifest.json (our ledger) is preferred
    for names and carries v1.2 provenance (stored_as archived copy)."""
    try:
        m = json.load(open(os.path.join(STORE, "manifest.json")))["docs"]
    except (OSError, KeyError):
        m = {}
    names = {k: v.get("name", "") for k, v in m.items()}
    try:
        led = json.load(open(os.path.join(STORE, "ingest_manifest.json")))
    except (OSError, ValueError):
        led = {}
    for k, v in led.items():
        names[k] = v.get("name", names.get(k, "")) or names.get(k, "")
    return names

def load_ledger():
    try:
        return json.load(open(os.path.join(STORE, "ingest_manifest.json")))
    except (OSError, ValueError):
        return {}

def provenance(doc_id):
    """Human-verifiable origin line: original filename + archived copy status."""
    rec = load_ledger().get(doc_id)
    if not rec:
        return "  来源: (无台账记录)"
    stored = rec.get("stored_as", "")
    if stored and os.path.exists(stored):
        loc = f"已存档 {stored}"
    elif rec.get("source") and os.path.exists(rec["source"]):
        loc = f"原件在 {rec['source']}（库内未存档）"
    else:
        loc = "原件已删除且无存档（内容见 text/ 文本层）"
    return f"  源文档: {rec.get('name','?')}  |  {loc}"

def match(docs, kws):
    return {d: n for d, n in docs.items()
            if any(k.lower() in n.lower() for k in kws)}

def load_map():
    if CSV_MAP and os.path.exists(CSV_MAP):
        return {r["doc_id"]: r
                for r in csv.DictReader(open(CSV_MAP, encoding="utf-8-sig"))}
    return {}

def show_src(ids):
    mp = load_map()
    if not mp:
        led = load_ledger()
        for d in ids:
            rec = led.get(d)
            if rec:
                print(f"{d}\n  name: {rec.get('name','')}\n  source: {rec.get('source','')}\n  stored: {rec.get('stored_as','') or '(未存档)'}")
            else:
                print(f"{d}  (no ledger row)")
        return
    for d in ids:
        r = mp.get(d)
        if r:
            print(f"{d}\n  " + "\n  ".join(f"{k}: {v}" for k, v in r.items()))
        else:
            print(f"{d}  (no mapping row)")

def chat_with_failover(question, doc_id):
    from pageindex import PageIndexClient
    last = None
    for gw in gateways():
        be = {"api_key": gw["key"], "api_base": gw["base"],
              "timeout": REQ_TIMEOUT, "max_retries": MAX_RETRIES}
        try:
            c = PageIndexClient(mode="local",
                index={"model": gw["model"], "backend": be, "storage_path": STORE},
                chat={"model": gw["model"], "backend": be})
            ans = c.chat(question, doc_id=doc_id)
            print(f"  [{gw['name']} OK]", file=sys.stderr)
            return ans
        except Exception as e:
            last = e
            print(f"  [{gw['name']} fail: {str(e)[:80]}, switching...]",
                  file=sys.stderr)
    raise RuntimeError(f"all gateways failed: {last}")

PAGE_RE = re.compile(r"^=== (?:PAGE (\d+)|第(\d+)页) ===$")

def grep_text(terms):
    """Local text-layer search over <STORE>/text/<doc_id>.txt (pi_flatten.py)."""
    if not os.path.isdir(TEXT_DIR):
        sys.exit("text layer missing: run pi_flatten.py first")
    docs = load_docs()
    pat = re.compile("|".join(re.escape(t) for t in terms))
    n_docs = 0
    for fn in sorted(os.listdir(TEXT_DIR)):
        if not fn.endswith(".txt"):
            continue
        doc_id = fn[:-4]
        try:
            lines = open(os.path.join(TEXT_DIR, fn),
                         encoding="utf-8", errors="ignore").read().splitlines()
        except Exception:
            continue
        hits, page = [], "?"
        for l in lines:
            ls = l.strip()
            m = PAGE_RE.match(ls)
            if m:
                page = m.group(1) or m.group(2)
                continue
            if pat.search(ls):
                hits.append((page, ls))
        if hits:
            print(f"\n===== {docs.get(doc_id, doc_id)} ({doc_id[:12]}...) — {len(hits)} hits =====")
            print(provenance(doc_id))
            for pg, l in hits[:15]:
                print(f"  P{pg}: {l[:160]}")
            if len(hits) > 15:
                print(f"  ... {len(hits)-15} more")
            n_docs += 1
    print(f"\n[grep] {n_docs} docs hit; use --doc for exact pages / deep read")

def run_llm(targets, question, workers):
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(targets)))) as ex:
        fut = {ex.submit(chat_with_failover, question, d): (d, n)
               for d, n in targets}
        for f in as_completed(fut):
            d, n = fut[f]
            try:
                results[d] = (None, f.result())
            except Exception as e:
                results[d] = (str(e), None)
    for d, n in targets:  # stable original order
        print(f"\n===== {n} ({d[:12]}...) =====")
        print(provenance(d))
        err, ans = results.get(d, ("not run", None))
        print(ans if ans is not None else f"  x {err}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--doc", help="select docs by name keyword, comma = OR")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--grep", nargs="+", help="local text-layer terms (no LLM)")
    ap.add_argument("--src", help="doc->source mapping only")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--workers", type=int,
                    default=int(os.environ.get("PI_WORKERS", "5")))
    a = ap.parse_args()
    docs = load_docs()

    if a.list:
        for d, n in sorted(docs.items(), key=lambda x: x[1]):
            print(f"{d[:12]}...  {n}")
        print(f"total {len(docs)}")
        return
    if a.src:
        show_src(match(docs, a.src.split(",")))
        return
    if a.grep:
        grep_text(a.grep)
        return
    if not a.question:
        ap.error("missing question")
    if a.all:
        targets = list(docs.items())[: a.limit]
    elif a.doc:
        targets = list(match(docs, a.doc.split(",")).items())
        if not targets:
            sys.exit(f"no doc name matches: {a.doc} (use --list)")
    else:
        sys.exit("choose --doc <kw> / --all / --grep")
    run_llm(targets, a.question, a.workers)

if __name__ == "__main__":
    main()
