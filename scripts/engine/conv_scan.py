#!/usr/bin/env python3
"""conv_scan.py — image-only (scanned) PDFs -> transcribed PDF for PageIndex.
try: import _site  # local site defaults (no-op in published pkg)
except ImportError: pass


Pipeline:
  1. probe text layer page-by-page (get_text). Pages with enough chars are
     kept VERBATIM (hybrid PDFs: only blank pages go through vision).
  2. blank pages rendered at Matrix(SCAN_DPI/72) (default 180) -> PNG ->
     vision transcription (same contract/prompt as conv_image.py).
  3. verbatim + transcribed blocks assembled in page order, provenance header
     added, rendered through the hardened layout engine -> <stem>_scan.pdf.

Vision cost guard: --max-pages caps vision calls (default 40) so a 2000-page
scan cannot silently burn your quota; --probe only reports page stats.

Env: PI_VISION_BASE/KEY/MODEL (see conv_image.py), PI_TMPDIR.

Usage:
  python3 conv_scan.py FILE.pdf [--max-pages 40] [--dpi 180] [--probe]
Prints the produced PDF path (or stats with --probe).
"""
import argparse
import hashlib
import os
import sys
import tempfile

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from conv_image import transcribe, md_to_html  # noqa: E402
from pi_ingest import html_to_pdf  # noqa: E402

MIN_CHARS = 20  # page text below this counts as "scanned/blank"


def probe(src):
    doc = pymupdf.open(src)
    if doc.needs_pass:
        # filename digit-run passwords (same convention as scan_corpus.py)
        import re
        if not any(doc.authenticate(x)
                   for x in re.findall(r"\d{4,12}", os.path.basename(src))):
            doc.close()
            raise RuntimeError("encrypted and no filename-password worked")
    stats = []
    for pno in range(len(doc)):
        n = len((doc[pno].get_text() or "").strip())
        stats.append(n)
    doc.close()
    return stats


def convert(src, max_pages=40, dpi=180, keep_png=False):
    stats = probe(src)
    need_vision = [i for i, n in enumerate(stats) if n < MIN_CHARS]
    if not need_vision:
        sys.exit(f"{src}: has a text layer ({sum(stats)} chars) — "
                 "feed it to pi_ingest.py directly, no OCR needed")
    if len(need_vision) == len(stats):
        kind = "pure scan"
    else:
        kind = f"hybrid ({len(need_vision)}/{len(stats)} pages need vision)"
    truncated = len(need_vision) > max_pages
    todo = need_vision[:max_pages]
    print(f"! {kind}; vision on {len(todo)} pages"
          + (f" (TRUNCATED at --max-pages={max_pages}, "
             f"re-run on the remaining pages as a split volume)"
             if truncated else ""), file=sys.stderr)

    tmp = os.environ.get("PI_TMPDIR") or tempfile.gettempdir()
    os.makedirs(tmp, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    doc = pymupdf.open(src)
    blocks, pngs = [], []
    for i in range(len(doc)):
        if i not in set(todo):
            t = (doc[i].get_text() or "").strip()
            if t:
                blocks.append((i + 1, "text", f"<p>{t}</p>"))
            continue
        png = os.path.join(tmp, f"{stem}_p{i+1}.png")
        doc[i].get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72)).save(png)
        pngs.append(png)
        blocks.append((i + 1, "vision", png))
    doc.close()

    # parallel vision for the pending slots, order preserved
    from concurrent.futures import ThreadPoolExecutor
    workers = int(os.environ.get("PI_VISION_WORKERS", "3"))
    vpaths = [b[2] for b in blocks if b[1] == "vision"]
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(vpaths) or 1))) as ex:
        vtexts = list(ex.map(transcribe, vpaths))
    vmap = dict(zip(vpaths, vtexts))

    parts = [f"<h1>{stem} (OCR转录)</h1>",
             "<p><i>扫描件视觉转写，准确率=视觉模型水平；数字/姓名以原件为准。"
             f"原PDF共{len(stats)}页，视觉处理{len(todo)}页。</i></p>"]
    for pno, kind_, payload in blocks:
        if kind_ == "text":
            parts.append(f"<h2>第{pno}页</h2>")
            parts.append(payload.replace("\n", "<br>"))
        else:
            parts.append(f"<h2>第{pno}页 (视觉转写)</h2>")
            parts.append(md_to_html(vmap[payload]))
            if not keep_png:
                try:
                    os.remove(payload)
                except OSError:
                    pass
    out = os.path.join(tmp, f"{stem}_scan.pdf")
    html_to_pdf("\n".join(parts), out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--dpi", type=int, default=180)
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    if a.probe:
        st = probe(a.pdf)
        blank = sum(1 for n in st if n < MIN_CHARS)
        print(f"pages={len(st)} need_vision={blank} text_chars_total={sum(st)}"
              f" -> {'pure scan' if blank == len(st) else 'hybrid' if blank else 'text PDF, ingest directly'}")
    else:
        print(convert(a.pdf, a.max_pages, a.dpi))
