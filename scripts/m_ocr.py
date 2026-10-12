#!/usr/bin/env python3
"""m_ocr.py — local-first OCR for CENHUA intake: RapidOCR transcribes images
and image-only PDFs into searchable PDFs; the vision LLM is only a fallback.

Policy (do not break):
  * The bundled engine stays byte-identical to upstream pageindex-rag. OCR
    routing happens HERE: m_ingest hands the engine a text-layer PDF produced
    by this module, so the engine's vision route never fires unless we bail.
  * Fallback contract: on ANY problem (mode=vision, backend missing, init or
    runtime failure, no text recognized, OR recognition quality below
    threshold) `preconvert` returns the ORIGINAL path and the caller feeds
    that to the engine — exactly the pre-RapidOCR behavior. Local OCR can
    only make intake cheaper, never break it.
  * Rendering reuses the engine's pure PDF writer (html_to_pdf), so local
    output is layout-identical to the vision route (CJK-safe, integrity
    checked). These imports are plain functions; no PI_* wiring involved.

Recognition-quality gate (RapidOCR is trusted only when it reads well):
  * avg confidence >= CENHUA_OCR_MIN_CONF (default 0.5) AND
  * total recognized chars >= CENHUA_OCR_MIN_CHARS (default 10)
  Otherwise the image/page is handed to the vision model (LLM fallback).
  A backend that reports no confidence (e.g. rapidocr v2 .txts-only) skips
  the confidence check and relies on the text-volume check alone.

Backend: `rapidocr_onnxruntime` (classic wheel) or `rapidocr` (v2 unified) —
whichever imports first. Both bundle their models, so OCR runs fully offline.

Config: env CENHUA_OCR, or vault.yaml `ocr` key (env wins):
  rapidocr (default)  local first, vision fallback
  vision              bypass local OCR entirely (engine's LLM route)
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "engine")
sys.path.insert(0, ENGINE)
from pi_ingest import html_to_pdf  # noqa: E402  (pure renderer, offline)
from conv_image import md_to_html  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
MIN_CHARS = 20          # same "page counts as blank" threshold as conv_scan
SCAN_PROBE_PAGES = 3    # same quick heuristic as pi_ingest.to_pdf


def err(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- backend ---
_ENG = False      # False = not tried yet, None = unavailable, else instance


def _get_engine():
    """Lazy RapidOCR singleton. Never raises: any failure -> None (fallback)."""
    global _ENG
    if _ENG is not False:
        return _ENG
    _ENG = None
    try:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            from rapidocr import RapidOCR          # v2 unified package
        _ENG = RapidOCR()
    except Exception as e:
        err(f"! RapidOCR unavailable ({type(e).__name__}: {e}) — vision fallback")
    return _ENG


def available():
    """True when a RapidOCR backend imports and initializes."""
    return _get_engine() is not None


def backend():
    return "RapidOCR" if available() else "vision model"


def mode(vault=None):
    """Effective OCR mode: 'rapidocr' (local first) or 'vision' (bypass)."""
    raw = os.environ.get("CENHUA_OCR", "")
    if not raw and vault is not None:
        raw = vault.cfg().get("ocr", "")
    return "vision" if raw.strip().lower() in ("vision", "llm", "off") else "rapidocr"


# ------------------------------------------------------- quality thresholds --
def _env_float(key, default):
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def min_confidence(vault=None):
    """Lowest acceptable average recognition confidence (0..1)."""
    raw = os.environ.get("CENHUA_OCR_MIN_CONF", "")
    if not raw and vault is not None:
        raw = vault.cfg().get("ocr_min_conf", "")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return 0.5


def min_chars(vault=None):
    """Lowest acceptable total recognized characters per image/page."""
    raw = os.environ.get("CENHUA_OCR_MIN_CHARS", "")
    if not raw and vault is not None:
        raw = vault.cfg().get("ocr_min_chars", "")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return 10


def quality_ok(lines, avg_score, vault=None):
    """True when a recognition result is good enough to trust. `avg_score`
    may be None (backend reports no confidence) — then only the text-volume
    check applies."""
    if not lines:
        return False
    total = sum(len(l) for l in lines)
    if total < min_chars(vault):
        return False
    if avg_score is not None and avg_score < min_confidence(vault):
        return False
    return True


# ---------------------------------------------------------------- backend ---
def _ocr_result(path):
    """(lines, avg_score) for one image; (None, None) on backend/runtime
    failure. avg_score is None when the backend reports no confidence.
    Never raises."""
    eng = _get_engine()
    if eng is None:
        return None, None
    try:
        res = eng(path)
    except Exception as e:
        err(f"! RapidOCR failed on {os.path.basename(path)} "
            f"({type(e).__name__}: {e}) — vision fallback")
        return None, None
    # normalize v1 ([[box, text, score], ...]) and v2 (.txts / .scores)
    if isinstance(res, tuple) and len(res) == 2:
        res = res[0]                                # (result, elapse)
    if res is None:
        return [], None
    if hasattr(res, "txts"):
        lines = [t for t in (res.txts or []) if t and t.strip()]
        scores = getattr(res, "scores", None)
        avg = None
        if scores:
            try:
                avg = sum(float(s) for s in scores) / len(scores)
            except (TypeError, ValueError):
                avg = None
        return lines, avg
    lines, scores = [], []
    for row in res:
        if isinstance(row, (list, tuple)) and len(row) >= 2                 and isinstance(row[1], str) and row[1].strip():
            lines.append(row[1].strip())
            if len(row) >= 3:
                try:
                    scores.append(float(row[2]))
                except (TypeError, ValueError):
                    pass
    avg = (sum(scores) / len(scores)) if scores else None
    return lines, avg


def ocr_lines(path, vault=None):
    """[text lines] for one image, or None when the backend failed OR the
    recognition quality is below threshold (caller falls back to vision)."""
    lines, avg = _ocr_result(path)
    if lines is None:
        return None
    if not quality_ok(lines, avg, vault):
        err(f"! RapidOCR quality below threshold on {os.path.basename(path)} "
            f"(chars={sum(len(l) for l in lines)}, "
            f"conf={('%.2f' % avg) if avg is not None else 'n/a'}) "
            "— vision fallback")
        return None
    return lines


# ------------------------------------------------------------- rendering ----
def _pdf_of_images(images, out, vault=None):
    """Images -> ONE PDF whose text layer is the RapidOCR transcription.
    Returns None when any image fails quality (caller falls back to vision)."""
    parts = []
    for img in images:
        lines = ocr_lines(img, vault)
        if lines is None:
            return None
        parts.append(f"<h2>图: {os.path.basename(img)}</h2>")
        parts.append(md_to_html("\n".join(lines)))
    html_to_pdf("\n".join(parts), out)
    return out


def _scan_pdf(src, out, dpi=180, vault=None):
    """Scanned PDF -> PDF with text pages kept verbatim and blank pages OCR'd
    locally (structure mirrors engine conv_scan, backend swapped). Returns
    None to trigger the vision fallback on backend/runtime failure or a page
    whose recognition quality is below threshold."""
    import html as _html
    import pymupdf
    doc = pymupdf.open(src)
    if doc.needs_pass:
        doc.close()
        return None
    stats = [len((doc[i].get_text() or "").strip()) for i in range(len(doc))]
    todo = [i for i, n in enumerate(stats) if n < MIN_CHARS]
    if not todo:
        doc.close()
        return None
    stem = os.path.splitext(os.path.basename(src))[0]
    tmp = os.environ.get("PI_TMPDIR") or os.path.dirname(out) or "/tmp"
    os.makedirs(tmp, exist_ok=True)
    err(f"! {os.path.basename(src)}: local OCR (RapidOCR) on "
        f"{len(todo)}/{len(stats)} page(s)")
    parts = [f"<h1>{_html.escape(stem)} (OCR转录)</h1>",
             "<p><i>扫描件本地OCR转录（RapidOCR）；数字/姓名以原件为准。"
             f"原PDF共{len(stats)}页，本地OCR处理{len(todo)}页。</i></p>"]
    todo_set = set(todo)
    for i in range(len(doc)):
        if i not in todo_set:
            t = (doc[i].get_text() or "").strip()
            if t:
                parts.append(f"<h2>第{i+1}页</h2>")
                parts.append("<p>" + _html.escape(t).replace("\n", "<br>") + "</p>")
            continue
        png = os.path.join(tmp, f".cenhua_ocr_p{i+1}.png")
        doc[i].get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72)).save(png)
        lines = ocr_lines(png, vault)
        try:
            os.remove(png)
        except OSError:
            pass
        if lines is None:
            doc.close()
            return None
        parts.append(f"<h2>第{i+1}页 (本地OCR)</h2>")
        parts.append(md_to_html("\n".join(lines)) if lines
                     else "<p>（本页无可识别文字）</p>")
        done = todo.index(i) + 1
        if done % 25 == 0 or done == len(todo):
            err(f"! local OCR progress: {done}/{len(todo)} pages")
    doc.close()
    html_to_pdf("\n".join(parts), out)
    return out


# ---------------------------------------------------------------- routing ---
def _cache_path(vault, path, digest, suffix):
    """Deterministic cache name (<stem>_<sha8><suffix>) under vault meta, so a
    retried ingest never OCRs the same bytes twice."""
    stem = os.path.splitext(os.path.basename(path))[0]
    tag = (digest or "")[:8]
    base = f"{stem}_{tag}{suffix}" if tag else f"{stem}{suffix}"
    d = (os.path.join(vault.meta, "ocr") if vault is not None
         else os.path.join(os.environ.get("PI_TMPDIR", "/tmp"), "cenhua-ocr"))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, base)


def _looks_like_scan(src):
    """Mirror of pi_ingest.to_pdf's quick heuristic: only intercept PDFs the
    engine itself would route to vision OCR; text PDFs pass through untouched."""
    import pymupdf
    try:
        doc = pymupdf.open(src)
    except Exception:
        return False
    if doc.needs_pass:
        doc.close()
        return False
    try:
        n = sum(len((doc[p].get_text() or "").strip())
                for p in range(min(SCAN_PROBE_PAGES, len(doc))))
        pages = len(doc)
    finally:
        doc.close()
    return n < 20 * min(SCAN_PROBE_PAGES, pages)


def preconvert(path, vault=None, digest=None):
    """Intake hook called BEFORE the engine sees a file.
    Returns (engine_input_path, route):
      route ""            engine gets the ORIGINAL file (not applicable,
                          disabled, backend missing, or any failure -> the
                          engine's own vision route handles it as before)
      route "image"/"scan" engine gets a local-OCR PDF instead
    """
    if mode(vault) != "rapidocr":
        return path, ""
    ext = os.path.splitext(path)[1].lower()
    if ext not in IMAGE_EXT and ext != ".pdf":
        return path, ""
    if _get_engine() is None:
        return path, ""
    if ext in IMAGE_EXT:
        out = _cache_path(vault, path, digest, ".pdf")
        if os.path.isfile(out):
            return out, "image"
        try:
            pdf = _pdf_of_images([path], out, vault)
        except Exception as e:
            err(f"! local OCR failed ({type(e).__name__}: {e}) — vision fallback")
            return path, ""
        return (pdf, "image") if pdf else (path, "")
    out = _cache_path(vault, path, digest, "_ocr.pdf")
    if os.path.isfile(out):
        return out, "scan"
    try:
        if not _looks_like_scan(path):
            return path, ""
        pdf = _scan_pdf(path, out, vault=vault)
    except Exception as e:
        err(f"! local scan OCR failed ({type(e).__name__}: {e}) — vision fallback")
        return path, ""
    return (pdf, "scan") if pdf else (path, "")
