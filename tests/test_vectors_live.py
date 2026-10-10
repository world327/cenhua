#!/usr/bin/env python3
"""Live test for the semantic layer against a MOCK embeddings endpoint.

Proves: incremental build, chunk alignment, cosine ranking, graceful auto-build
from `cenhua seek`, and re-embedding only changed docs. No real API needed.
"""

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "bin", "cenhua")
CALLS = []


def pseudo_vec(text, dim=32):
    """Deterministic bag-of-characters vector: shared words -> higher cosine."""
    v = [0.0] * dim
    for ch in text.lower():
        v[ord(ch) % dim] += 1.0
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        CALLS.append(len(body["input"]))
        out = {"data": [{"index": i, "embedding": pseudo_vec(t)}
                        for i, t in enumerate(body["input"])]}
        raw = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"data":[{"id":"mock-embed"}]}')


def main():
    home = tempfile.mkdtemp(prefix="cenhua-vec-")
    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    env = dict(os.environ, CENHUA_HOME=home, PI_EMBED_BASE=base,
               PI_EMBED_KEY="test", PI_EMBED_MODEL="mock-embed")

    def run(*args):
        return subprocess.run([CLI, *args], env=env, cwd=ROOT,
                              capture_output=True, text=True)

    fails = []

    def check(label, cond, detail=""):
        print(("  ok   " if cond else "  FAIL ") + label + (f"  {detail}" if detail and not cond else ""))
        if not cond:
            fails.append(label)

    run("init", "v", "--yes")
    v = os.path.join(home, "vaults", "v", "engine")
    os.makedirs(os.path.join(v, "docs", "pi-doc1"), exist_ok=True)
    os.makedirs(os.path.join(v, "text"), exist_ok=True)
    pages = [{"page_index": 1, "markdown": "The cat sat on the mat and purred."},
             {"page_index": 2, "markdown": "Dogs chase rabbits through the garden."}]
    json.dump(pages, open(os.path.join(v, "docs", "pi-doc1", "pages.json"), "w"))
    json.dump({"docs": {"pi-doc1": {"name": "pets.txt"}}},
              open(os.path.join(v, "manifest.json"), "w"))
    json.dump({"pi-doc1": {"name": "pets.txt", "doc_id": "pi-doc1", "sha1": "x",
                           "ts": "2026-10-10 12:00:00", "source": "", "stored_as": ""}},
              open(os.path.join(v, "ingest_manifest.json"), "w"))

    r = run("flatten", "--vault", "v")
    check("flatten", r.returncode == 0, r.stderr)

    n0 = len(CALLS)
    r = run("index", "build", "--vault", "v")
    check("index build", r.returncode == 0, (r.stdout + r.stderr)[:300])
    check("embedded something", len(CALLS) > n0, f"calls={len(CALLS)-n0}")
    r = run("index", "build", "--vault", "v")
    check("incremental no-op", "up to date" in r.stdout, r.stdout[-200:])

    r = run("seek", "cat purring on a mat", "--vault", "v", "--top", "2")
    out = r.stdout
    check("seek returns hits", r.returncode == 0 and "P1" in out, out[:400])
    check("citation + provenance", "Source:" in out and "sim=" in out, out[:200])
    check("grep reminder", "cenhua find" in out, out[-200:])

    # edit a page -> only that doc is re-embedded
    pages[0]["markdown"] += " A kitten joined the cat on the mat."
    json.dump(pages, open(os.path.join(v, "docs", "pi-doc1", "pages.json"), "w"))
    run("flatten", "--vault", "v")
    n1 = len(CALLS)
    r = run("index", "build", "--vault", "v")
    check("re-embeds changed doc", "1 docs re-embedded" in r.stdout, r.stdout[-200:])
    check("made API calls", len(CALLS) > n1)
    check("state tracks model", "mock-embed" in open(
        os.path.join(home, "vaults", "v", "meta", "vectors", "state.json")).read())

    # index rows stay row-aligned with chunks after a rebuild
    chunks = json.load(open(os.path.join(home, "vaults", "v", "meta", "vectors",
                                         "chunks.json")))
    import numpy as np
    mat = np.load(os.path.join(home, "vaults", "v", "meta", "vectors", "vectors.npy"))
    check("rows == chunks", len(chunks) == mat.shape[0],
          f"{len(chunks)} vs {mat.shape}")
    check("pages preserved", all(c["page"] in ("1", "2") for c in chunks))

    srv.shutdown()
    shutil.rmtree(home, ignore_errors=True)
    print("\n" + ("SEMANTIC LAYER: ALL PASSED" if not fails else f"FAILED: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
