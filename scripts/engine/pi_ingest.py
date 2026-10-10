#!/usr/bin/env python3
"""pi_ingest.py — any document -> PDF -> PageIndex index pipeline.

Usage:
  pi_ingest.py <file1> [file2 ...]      # ingest (auto-convert + index, sha1 dedupe)
  pi_ingest.py --list                   # list indexed docs
Formats: .pdf direct; .md/.markdown/.txt/.html/.htm/.csv converted to PDF via
PyMuPDF insert_htmlbox (CJK-safe, PyPDF2-compatible; do NOT use fitz.Story —
its ToUnicode font mapping breaks PageIndex's internal PyPDF2 extraction with
'Odd-length string'). .docx/.pptx/.xlsx: convert to PDF first.

Env:
  PI_STORE   storage dir            (default ~/.pageindex-rag/store)
  PI_BASE    OpenAI-compatible base URL          (required)
  PI_KEY     API key                             (required)
  PI_MODEL   index model 'openai/<name>'         (default openai/gpt-4o-mini)
  PI_CHAT_MODEL chat model override              (default = PI_MODEL)
  PI_BASE2/PI_KEY2/PI_MODEL2  optional 2nd gateway for rate-limit failover
"""
try: import _site  # local site defaults (no-op in published pkg)
except ImportError: pass

import csv, hashlib, json, os, re, shutil, sys, time

STORE = os.environ.get("PI_STORE", os.path.expanduser("~/.pageindex-rag/store"))
PDFDIR = os.path.join(STORE, "pdf")
SRCDIR = os.path.join(STORE, "sources")   # v1.2: copies of uploaded originals
SRCMAP = os.path.join(STORE, "source_map.csv")  # doc_id -> original name/path
HERE = os.path.dirname(os.path.abspath(__file__))
# NOTE: never name this file manifest.json — PageIndex owns <STORE>/manifest.json
MANIFEST = os.path.join(STORE, "ingest_manifest.json")
CONVERTIBLE = {".md", ".markdown", ".txt", ".html", ".htm", ".csv"}
OFFICE = {".docx", ".pptx", ".xlsx", ".xls"}
IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def gateways():
    base = os.environ.get("PI_BASE")
    key = os.environ.get("PI_KEY")
    if not base or not key:
        sys.exit("PI_BASE and PI_KEY env vars are required")
    gws = [{"name": "gw1", "base": base, "key": key,
            "model": os.environ.get("PI_MODEL", "openai/gpt-4o-mini"),
            "chat_model": os.environ.get("PI_CHAT_MODEL",
                                         os.environ.get("PI_MODEL",
                                                        "openai/gpt-4o-mini"))}]
    if os.environ.get("PI_BASE2") and os.environ.get("PI_KEY2"):
        m2 = os.environ.get("PI_MODEL2", gws[0]["model"])
        gws.append({"name": "gw2", "base": os.environ["PI_BASE2"],
                    "key": os.environ["PI_KEY2"], "model": m2,
                    "chat_model": os.environ.get("PI_CHAT_MODEL2", m2)})
    return gws


_clients = {}


def client(gw=None):
    """Build/cache PageIndexClient per gateway (same storage_path = shared index)."""
    gw = gw or gateways()[0]
    if gw["name"] in _clients:
        return _clients[gw["name"]]
    from pageindex import PageIndexClient
    be = {"api_key": gw["key"], "api_base": gw["base"]}
    c = PageIndexClient(
        mode="local",
        index={"model": gw["model"], "backend": be, "storage_path": STORE},
        chat={"model": gw["chat_model"], "backend": be},
    )
    _clients[gw["name"]] = c
    return c


def is_rate_limit(err):
    s = str(err).lower()
    return "ratelimit" in s or "rate limit" in s or "rate exceeds" in s


def submit_with_failover(pdf):
    """Per gateway try default index mode then 'standard' (pure-table docs
    report 'found no layout structure' in the fast mode); rate-limit -> next gw."""
    last_err = None
    for gw in gateways():
        for mode in (None, "standard"):
            try:
                c = client(gw)
                doc_id = (c.submit_document(pdf) if mode is None
                          else c.submit_document(pdf, mode=mode))["doc_id"]
                return doc_id, gw["name"], mode or "default"
            except Exception as e:
                last_err = e
                if is_rate_limit(e):
                    print(f"! [{gw['name']}] rate limited, switching gateway...")
                    break
                if mode is None and "no layout structure" in str(e):
                    print("! fast mode found no layout, retrying standard...")
                    continue
                raise
    raise RuntimeError(f"all gateways failed: {last_err}")


def load_manifest():
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as f:
            return json.load(f)
    return {}


def save_manifest(m):
    os.makedirs(STORE, exist_ok=True)
    with open(MANIFEST, "w") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


CSS = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.5; }
h1 { font-size: 17pt; } h2 { font-size: 14pt; } h3 { font-size: 12pt; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 0.5pt solid #999; padding: 4px; font-size: 9.5pt; }
pre, code { font-size: 9pt; }
pre { background: #f4f4f4; padding: 6px; }
blockquote { color: #555; border-left: 3pt solid #ccc; margin-left: 0; padding-left: 10px; }
"""
CSS_WIDE = CSS + "\ntable td, table th { font-size: 5.5pt; padding: 1px; }"
BLOCK_RE = re.compile(r"<(h[1-6]|p|pre|table|blockquote|ul|ol)[^>]*>.*?</\1>", re.S)


def _split_giant(blk):
    """Re-split giant <p> blocks (markdown merges consecutive lines) so a block
    can never exceed one page: insert_htmlbox SILENTLY renders blank when a
    block is too tall (returns success!). Row-count cap (~38 lines x 16pt ~
    608pt on A4) is the hard constraint, not char count. Long unbroken tokens
    (transaction IDs) get U+200B every 12 chars or MuPDF overflow blanks the
    whole block."""
    blk = re.sub(r"([A-Za-z0-9]{12})", lambda m: m.group(1) + "\u200b", blk)
    txt = re.sub(r"<[^>]+>", " ", blk)
    if len(txt) <= 1800 and blk.count("<br>") <= 38:
        return [blk]
    inner = re.sub(r"^<\w+[^>]*>|</\w+>\s*$", "", blk.strip())
    lines = [l for l in re.split(r"<br\s*/?>|\n", inner) if l.strip()]
    out, cur, curlen = [], [], 0
    for l in lines:
        cur.append(l)
        curlen += len(re.sub(r"<[^>]+>", "", l))
        if curlen >= 1500 or len(cur) >= 38:
            out.append("<p>" + "<br>".join(cur) + "</p>")
            cur, curlen = [], 0
    if cur:
        out.append("<p>" + "<br>".join(cur) + "</p>")
    return out


def _html_blocks(html):
    blocks = []
    for m in BLOCK_RE.finditer(html):
        tag, blk = m.group(1), m.group(0)
        if tag == "table" and blk.count("<tr") > 25:
            rows = re.findall(r"<tr.*?</tr>", blk, re.S)
            thead = rows[0] if rows and "<th" in rows[0] else ""
            body = rows[1:] if thead else rows
            for i in range(0, len(body), 20):
                blocks.append(blk.split(">")[0] + ">" + thead
                              + "".join(body[i:i + 20]) + "</table>")
        elif tag in ("p", "pre", "blockquote"):
            blocks.extend(_split_giant(blk))
        else:
            blocks.append(blk)
    return blocks


def _table_rows(blk):
    rows = re.findall(r"<tr.*?</tr>", blk, re.S)
    thead = rows[0] if rows and "<th" in rows[0] else ""
    body = rows[1:] if thead else rows
    return blk.split(">")[0] + ">", thead, body


def fit_block(measure_page, b, w, css, usable):
    """Split tables that cannot fit one page, binary-searching rows/page.
    Measurement MUST use the same scale_low=0.3 as rendering, else splits go
    haywire (overly pessimistic measurement)."""
    import pymupdf
    def need(bb):
        spare, _ = measure_page.insert_htmlbox(pymupdf.Rect(0, 0, w, 38000),
                                               bb, css=css, scale_low=0.3)
        return 38000 - spare
    if need(b) <= usable or not b.startswith("<table"):
        return [b]
    open_tag, thead, body = _table_rows(b)
    if len(body) <= 1:
        return [b]
    lo, hi = 1, len(body)
    while lo < hi:
        mid = (lo + hi) // 2
        if need(open_tag + thead + "".join(body[:mid]) + "</table>") <= usable:
            hi = mid
        else:
            lo = mid + 1
    per = max(1, lo - 1) if need(open_tag + thead + "".join(body[:lo]) + "</table>") > usable else lo
    return [open_tag + thead + "".join(body[i:i + per]) + "</table>"
            for i in range(0, len(body), per)]


def html_to_pdf(html, out):
    """HTML -> multi-page PDF via per-block insert_htmlbox (built-in CJK fonts).
    Wide tables (>14 cells) go on landscape pages at 5.5pt or they render
    BLANK silently. Final integrity check: PDF char count >= 85% of source
    visible chars, else raise and delete the bad PDF (silent blanking once
    produced 8 empty-shell indexes before anyone noticed)."""
    import pymupdf
    PAGE = pymupdf.paper_rect("a4")
    M = 50
    doc = pymupdf.open()
    measure = pymupdf.open()
    mp = measure.new_page(width=1000, height=40000)

    def need(b, w, css):
        spare, _ = mp.insert_htmlbox(pymupdf.Rect(0, 0, w, 38000),
                                     b, css=css, scale_low=0.3)
        return max(10.0, (38000 - spare) * 1.0 + 2)

    def is_wide(b):
        return b.startswith("<table") and (b.count("<th") + b.count("<td")) > 14

    work = []
    for b in _html_blocks(html):
        wide = is_wide(b)
        w = float(PAGE.height) - 2 * M if wide else float(PAGE.width) - 2 * M
        h_page = float(PAGE.width) if wide else float(PAGE.height)
        css = CSS_WIDE if wide else CSS
        for sb in fit_block(mp, b, w, css, h_page - 2 * M - 10):
            work.append((sb, wide))

    page = doc.new_page(width=PAGE.width, height=PAGE.height)
    pw, ph = float(PAGE.width), float(PAGE.height)
    y = float(M)

    def newpage(w, h):
        nonlocal page, y, pw, ph
        page = doc.new_page(width=w, height=h)
        pw, ph, y = w, h, float(M)

    if work and all(w_ for _, w_ in work):
        newpage(float(PAGE.height), float(PAGE.width))

    for b, wide in work:
        want_w = float(PAGE.height) if wide else float(PAGE.width)
        want_h = float(PAGE.width) if wide else float(PAGE.height)
        if abs(pw - want_w) > 1:
            newpage(want_w, want_h)
        css = CSS_WIDE if wide else CSS
        h = need(b, want_w - 2 * M, css)
        if y + h > want_h - M and y > M:
            newpage(want_w, want_h)
        rect = pymupdf.Rect(M, y, want_w - M, want_h - M)
        spare, shrink = page.insert_htmlbox(rect, b, css=css, scale_low=0.3)
        used = rect.height - max(spare, 0.0)
        y += used * (shrink if shrink else 1.0) + 6
        if y > want_h - M - 20:
            newpage(want_w, want_h)
    doc.save(out, garbage=4, deflate=True)
    doc.close(); measure.close()
    chk = pymupdf.open(out)
    got = sum(len(p.get_text().replace(" ", "").replace("\n", "")) for p in chk)
    chk.close()
    want = len(re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", html)))
    if want > 200 and got < want * 0.85:
        os.remove(out)
        raise RuntimeError(f"layout integrity check failed: PDF has {got} chars "
                           f"vs source {want}; bad PDF deleted")


def text_to_html(text):
    esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    parts = []
    for line in esc.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            parts.append(f"<h{len(m.group(1))}>{m.group(2)}</h{len(m.group(1))}>")
        elif line.strip():
            parts.append(f"<p>{line}</p>")
    return "\n".join(parts)


def to_pdf(src):
    os.makedirs(PDFDIR, exist_ok=True)
    ext = os.path.splitext(src)[1].lower()
    if ext == ".pdf":
        # auto-detect image-only scans; route through vision OCR
        if os.environ.get("PI_SKIP_SCAN_DETECT") != "1":
            import pymupdf
            try:
                doc = pymupdf.open(src)
                if doc.needs_pass:
                    doc = None
                else:
                    n = sum(len((doc[p].get_text() or "").strip())
                            for p in range(min(3, len(doc))))
                    pages = len(doc)
                    doc.close()
                    if n < 20 * min(3, pages):
                        print(f"! {src}: image-only scan -> vision OCR route")
                        import conv_scan
                        src = conv_scan.convert(src)
            except pymupdf.FileDataError:
                pass
        return src
    if ext in OFFICE:
        import conv_office
        print(f"! {src}: office -> PDF (no LibreOffice)")
        return conv_office.convert(src)
    if ext in IMAGES:
        import conv_image
        print(f"! {src}: image -> vision OCR -> PDF")
        return conv_image.convert([src])[0]
    if ext not in CONVERTIBLE:
        sys.exit(f"unsupported format: {ext} "
                 "(supported: pdf md txt html csv docx pptx xlsx xls images)")
    digest = sha1(src)[:12]
    base = os.path.splitext(os.path.basename(src))[0]
    # filesystem-safe name (quotes/CJK are fine on linux; strip path separators)
    out = os.path.join(PDFDIR, f"{base.replace(os.sep, '_')}_{digest}.pdf")
    if os.path.exists(out):
        return out
    if ext in (".md", ".markdown"):
        import markdown as mdlib
        html = mdlib.markdown(open(src, encoding="utf-8").read(),
                              extensions=["tables", "fenced_code"])
    elif ext in (".html", ".htm"):
        html = open(src, encoding="utf-8").read()
    else:
        html = text_to_html(open(src, encoding="utf-8").read())
    html_to_pdf(html, out)
    return out


def _append_srcmap(doc_id, name, source, stored):
    """Human-auditable CSV ledger: doc_id, original filename, upload path,
    archived copy inside the store, sha1, timestamp. Append-only."""
    new = not os.path.exists(SRCMAP)
    with open(SRCMAP, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["doc_id", "name", "source_path", "stored_copy",
                        "sha1", "ts"])
        w.writerow([doc_id, name, source, stored, sha1(source),
                    time.strftime("%F %T")])


def ingest(path):
    path = os.path.abspath(path)
    if not os.path.exists(path):
        print(f"x not found: {path}")
        return
    digest = sha1(path)
    m = load_manifest()
    for rec in m.values():
        if rec["sha1"] == digest:
            print(f"= already indexed: {rec['name']} (doc_id={rec['doc_id']})")
            return
    name = os.path.basename(path)
    print(f"> {name}: converting...")
    pdf = to_pdf(path)
    print(f"> {name}: indexing...")
    t0 = time.time()
    doc_id, gw_name, mode = submit_with_failover(pdf)
    # v1.2 personal knowledge base: archive the uploaded original INSIDE the
    # store so provenance survives source-file deletion; map doc_id -> name.
    os.makedirs(SRCDIR, exist_ok=True)
    # archive under the ORIGINAL filename (user-facing). On name collision
    # with different content, keep both: append sha1-8 before the extension.
    stored = os.path.join(SRCDIR, name)
    if os.path.exists(stored) and sha1(stored) != digest:
        stem, suf = os.path.splitext(name)
        stored = os.path.join(SRCDIR, f"{stem}_{digest[:8]}{suf}")
    try:
        if not os.path.exists(stored):
            shutil.copy2(path, stored)
    except OSError as e:
        print(f"! could not archive original ({e}); mapping still written",
              file=sys.stderr)
        stored = ""
    m[doc_id] = {"name": name, "source": path, "stored_as": stored,
                 "sha1": digest, "doc_id": doc_id,
                 "ts": time.strftime("%F %T")}
    save_manifest(m)
    _append_srcmap(doc_id, name, path, stored)
    print(f"+ {name} -> {doc_id} ({time.time()-t0:.0f}s, gw={gw_name}, mode={mode})")


def list_docs():
    m = load_manifest()
    if not m:
        print("(empty)")
        return
    for rec in m.values():
        stored = rec.get("stored_as", "")
        mark = "✓存档" if stored and os.path.exists(stored) else "✗仅路径"
        print(f"{rec['doc_id']}  {rec['name']}  [{rec['ts']}] {mark}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    if sys.argv[1] == "--list":
        list_docs()
    else:
        for p in sys.argv[1:]:
            ingest(p)
