#!/usr/bin/env python3
"""m_vectors.py — CENHUA optional semantic layer (pluggable, offline-friendly).

PageIndex is vectorless by design and CENHUA keeps it that way: `find` (exact
grep on the flattened text layer) is always the first stop. This module adds a
*recall net* for fuzzy rephrasings that exact grep cannot catch, via any
OpenAI-compatible /embeddings endpoint. It never replaces grep.

Config (process env only; vault.yaml may carry *_base/_model defaults):
  PI_EMBED_BASE   embeddings endpoint (falls back to PI_BASE)
  PI_EMBED_KEY    key (falls back to PI_KEY)
  PI_EMBED_MODEL  e.g. text-embedding-v3 / bge-m3 / text-embedding-3-small

Storage (all rebuildable, safe to delete):
  <vault>/meta/vectors/chunks.json   [{doc, page, idx, text}, ...]
  <vault>/meta/vectors/vectors.npy   float32 L2-normalized, row-aligned
  <vault>/meta/vectors/state.json    doc_id -> {sha1, model} (incremental)

Usage (via the CLI):
  cenhua index build [--force]   (re)build the chunk/vector index
  cenhua index status            coverage + endpoint health
  cenhua seek "question" [--top] semantic recall; auto-builds when stale
"""

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_lib as L  # noqa: E402

MAX_CHARS = 900
BATCH = 16


# ------------------------------------------------------------------ config --
def embed_config(vault):
    env = L.build_env(vault)
    base = env.get("PI_EMBED_BASE") or env.get("PI_BASE")
    key = env.get("PI_EMBED_KEY") or env.get("PI_KEY")
    model = env.get("PI_EMBED_MODEL") or env.get("PI_EMBED")
    return base, key, model


def require_config(vault):
    base, key, model = embed_config(vault)
    if not (base and model):
        L.die(
            "semantic layer not configured. Set PI_EMBED_MODEL (and PI_EMBED_BASE/"
            "PI_EMBED_KEY, or reuse PI_BASE/PI_KEY) to any OpenAI-compatible "
            "embeddings endpoint, or remove it with: rm -rf <vault>/meta/vectors",
            code=3)
    return base, key, model


def np_mod():
    try:
        import numpy as np
        return np
    except ImportError:
        L.die("the semantic layer needs numpy: pip install numpy")


# ------------------------------------------------------------------ embed ---
def embed_texts(texts, base, key, model, timeout=60):
    url = base.rstrip("/") + "/embeddings"
    out = []
    for i in range(0, len(texts), BATCH):
        payload = {"model": model, "input": [t[:8000] for t in texts[i:i + BATCH]]}
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise SystemExit(f"x embeddings HTTP {e.code}: "
                             f"{e.read()[:300].decode('utf-8','replace')}")
        except Exception as e:
            raise SystemExit(f"x embeddings unreachable ({base}): {e}")
        rows = sorted(body["data"], key=lambda d: d.get("index", 0))
        out.extend(r_["embedding"] for r_ in rows)
        print(f"  embedded {min(i + BATCH, len(texts))}/{len(texts)}",
              file=sys.stderr)
    return out


def normalize(vec):
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


# ----------------------------------------------------------- chunking -------
def split_page(page_text, limit=MAX_CHARS):
    """One page -> 1..n chunks (never crosses pages: citations stay exact)."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", page_text) if b.strip()]
    chunks, cur = [], ""
    for b in blocks:
        if len(b) > limit:  # hard split long block with overlap
            if cur:
                chunks.append(cur)
                cur = ""
            step = int(limit * 0.7)
            for i in range(0, len(b), step):
                chunks.append(b[i:i + limit])
            continue
        if len(cur) + len(b) + 2 <= limit:
            cur = f"{cur}\n\n{b}" if cur else b
        else:
            chunks.append(cur)
            cur = b
    if cur:
        chunks.append(cur)
    return chunks or [""]


def doc_chunks(doc_id, pages):
    out = []
    for pno, ptext in pages:
        for idx, ch in enumerate(split_page(ptext)):
            if ch.strip():
                out.append({"doc": doc_id, "page": pno, "idx": idx,
                            "text": ch})
    return out


# -------------------------------------------------------------- store -------
def load_state(vault):
    return L.read_json(os.path.join(vault.vectors, "state.json"), {}) or {}


def save_state(vault, st):
    os.makedirs(vault.vectors, exist_ok=True)
    with open(os.path.join(vault.vectors, "state.json"), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)


def load_index(vault):
    np = np_mod()
    cj = os.path.join(vault.vectors, "chunks.json")
    vy = os.path.join(vault.vectors, "vectors.npy")
    if not (os.path.isfile(cj) and os.path.isfile(vy)):
        return [], None
    chunks = json.load(open(cj, encoding="utf-8"))
    mat = np.load(vy)
    if len(chunks) != mat.shape[0]:  # corrupted — force rebuild
        return [], None
    return chunks, mat


def save_index(vault, chunks, mat):
    np = np_mod()
    os.makedirs(vault.vectors, exist_ok=True)
    with open(os.path.join(vault.vectors, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False)
    np.save(os.path.join(vault.vectors, "vectors.npy"),
            mat.astype("float32"))


# ------------------------------------------------------------- commands -----
def build(vault, force=False):
    np = np_mod()
    base, key, model = require_config(vault)
    have, missing, empty = L.text_status(vault)
    if not have:
        L.die("text layer is empty — run `cenhua add <files>` first")
    if missing:
        L.say(f"! {len(missing)} doc(s) lack a text layer; run: cenhua flatten")
    state = load_state(vault)
    chunks, mat = ([], None) if force else load_index(vault)
    if force:
        state = {}

    changed = []
    for doc_id in sorted(have - set(empty)):
        path = os.path.join(vault.textdir, f"{doc_id}.txt")
        digest = L.sha1(path)
        rec = state.get(doc_id)
        if not force and rec and rec.get("sha1") == digest \
                and rec.get("model") == model:
            continue
        changed.append((doc_id, digest))

    if not changed:
        L.say(f"= vector index up to date ({len(chunks)} chunks, model={model})")
        return

    drop = {d for d, _ in changed}
    keep_rows = [i for i, c in enumerate(chunks) if c["doc"] not in drop]
    chunks = [chunks[i] for i in keep_rows]
    mat = mat[keep_rows] if mat is not None and len(keep_rows) else None

    docs = L.store_docs(vault)
    new_chunks, old_total = [], len(chunks)
    for doc_id, _ in changed:
        pages = L.text_pages(vault, doc_id)
        cs = doc_chunks(doc_id, pages)
        L.say(f"> {docs.get(doc_id, {}).get('name', doc_id)}: {len(cs)} chunks")
        new_chunks.extend(cs)
    if not new_chunks:
        L.die("no chunks produced (empty text layer?)")

    L.say(f"embedding {len(new_chunks)} new chunks with '{model}' ...")
    t0 = time.time()
    vecs = embed_texts([c["text"] for c in new_chunks], base, key, model)
    new_mat = np.array([normalize(v) for v in vecs], dtype="float32")
    mat = new_mat if mat is None or len(mat) == 0 else np.vstack([mat, new_mat])
    chunks.extend(new_chunks)
    save_index(vault, chunks, mat)
    for doc_id, digest in changed:
        state[doc_id] = {"sha1": digest, "model": model,
                         "chunks": sum(1 for c in new_chunks if c["doc"] == doc_id),
                         "ts": time.strftime("%F %T")}
    save_state(vault, state)
    L.say(f"+ index: {len(chunks)} chunks total (+{len(new_chunks)} new, "
          f"{len(changed)} docs re-embedded) | {time.time()-t0:.0f}s")


def search(vault, query, top=6):
    np = np_mod()
    base, key, model = require_config(vault)
    chunks, mat = load_index(vault)
    if not chunks:
        L.die("vector index empty — run: cenhua index build")
    qv = np.array(normalize(embed_texts([query], base, key, model)[0]),
                  dtype="float32")
    sims = mat @ qv
    order = sims.argsort()[::-1][:top]
    docs = L.store_docs(vault)
    L.say(f"[seek] semantic recall (fallback layer — grep stays authoritative)")
    last_doc = None
    for i in order:
        c = chunks[int(i)]
        if c["doc"] != last_doc:
            name = docs.get(c["doc"], {}).get("name", c["doc"])
            L.say(f"\n----- {name} ({c['doc'][:12]}...) -----")
            L.say(L.provenance(vault, c["doc"], name))
            last_doc = c["doc"]
        first = c["text"].strip().splitlines()[0] if c["text"].strip() else ""
        L.say(L.cite(vault, c["doc"], c["page"],
                     f"sim={sims[int(i)]:.3f} {first[:140]}"))
    L.say("\n[next] verify with `cenhua find <exact-terms>` before concluding.")


def status(vault):
    chunks, mat = ([], None)
    try:
        chunks, mat = load_index(vault)
    except SystemExit:
        pass
    base, key, model = embed_config(vault)
    state = load_state(vault)
    L.say(f"semantic layer : {'configured' if (base and model) else 'NOT configured (optional)'}")
    if model:
        L.say(f"  model        : {model}")
    if base:
        ok, detail = probe_ok(base, key)
        L.say(f"  endpoint     : {base} [{'ok: ' + detail if ok else 'UNREACHABLE: ' + detail}]")
    L.say(f"  chunks       : {len(chunks)}" if chunks else "  chunks       : 0 (run: cenhua index build)")
    if state:
        L.say(f"  docs covered : {len(state)}")


def probe_ok(base, key):
    import urllib.request as u
    try:
        with u.urlopen(base.rstrip("/") + "/models", timeout=6) as r:
            r.read(200)
        return True, "reachable"
    except Exception as e:
        return False, str(e)[:60]
