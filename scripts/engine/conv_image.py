#!/usr/bin/env python3
"""conv_image.py — screenshots/images -> transcribed markdown -> PDF (ready for
try: import _site  # local site defaults (no-op in published pkg)
except ImportError: pass

PageIndex), via an OpenAI-compatible VISION model.

Handles: .jpg/.jpeg/.png/.webp/.bmp/.gif (first frame) and multi-image bursts
(one chat screenshot is one document; pass them together: pages = images).

Transcription contract sent to the vision model (tuned for evidence/records):
preserve table structure as markdown tables, keep every digit string intact,
mark uncertain OCR `?`, placeholder unreadable glyphs with ○, keep handwriting,
never guess names/numbers. Output is wrapped with provenance headers
(## 图N: <filename>) then rendered to PDF by the hardened layout engine.

Env (vision gateway; falls back to PI_BASE/PI_KEY):
  PI_VISION_BASE / PI_VISION_KEY / PI_VISION_MODEL   (default
      model: openai/gpt-4o-mini — must be vision-capable, set explicitly!)
  PI_VISION_TIMEOUT (default 120)   PI_VISION_WORKERS (default 3)

Usage:
  python3 conv_image.py shot1.png shot2.png ...   # -> one PDF per batch arg
  python3 conv_image.py --each img1.jpg img2.png  # -> one PDF per image
Prints produced PDF paths.
"""
import base64
import hashlib
import mimetypes
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pi_ingest import html_to_pdf  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

PROMPT = """Transcribe this document image to Markdown EXACTLY.
Rules:
- Preserve layout: tables as markdown tables (keep column alignment), lists as lists.
- Keep ALL numbers, codes, IDs, account numbers character-for-character.
- Uncertain character: append ?. Truly unreadable: ○. NEVER guess or "fix" names/numbers.
- Include stamps/seals/handwriting as bracketed notes, e.g. [红色公章: ...], [手写: ...].
- Output ONLY the markdown, no commentary."""


def vision_cfg():
    base = os.environ.get("PI_VISION_BASE") or os.environ.get("PI_BASE")
    key = os.environ.get("PI_VISION_KEY") or os.environ.get("PI_KEY")
    model = os.environ.get("PI_VISION_MODEL", "gpt-4o-mini")
    # strip LiteLLM-style 'openai/' routing prefix — the raw OpenAI SDK wants
    # the bare model id registered on the endpoint (see GET {base}/models)
    if model.startswith("openai/"):
        model = model[len("openai/"):]
    if not base or not key:
        sys.exit("PI_VISION_BASE/KEY (or PI_BASE/PI_KEY) required")
    return base, key, model


def _b64(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


def transcribe(path):
    from openai import OpenAI
    base, secret, model = vision_cfg()
    kw = dict(base_url=base,
              timeout=float(os.environ.get("PI_VISION_TIMEOUT", "120")),
              max_retries=1)
    kw["api_key"] = secret
    c = OpenAI(**kw)
    r = c.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url",
             "image_url": {"url": _b64(path), "detail": "high"}}]}])
    txt = (r.choices[0].message.content or "").strip()
    if not txt:
        raise RuntimeError(f"vision returned empty for {path}")
    return txt


def md_to_html(md):
    try:
        import markdown as mdlib
        return mdlib.markdown(md, extensions=["tables", "fenced_code"])
    except ImportError:
        esc = md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return "".join(f"<p>{l}</p>" for l in esc.split("\n") if l.strip())


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def batch_to_pdf(images, out=None):
    """Multiple images -> ONE document (parallel transcription, ordered)."""
    workers = int(os.environ.get("PI_VISION_WORKERS", "3"))
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(images)))) as ex:
        texts = list(ex.map(transcribe, images))
    parts = []
    for img, txt in zip(images, texts):
        parts.append(f"<h2>图: {os.path.basename(img)}</h2>")
        parts.append(md_to_html(txt))
    _t = os.environ.get("PI_TMPDIR")
    if _t: os.makedirs(_t, exist_ok=True)
    out = out or os.path.join(
        os.environ.get("PI_TMPDIR") or tempfile.gettempdir(),
        f"images_{_sha1(''.join(os.path.abspath(i) for i in images).encode())[:12]}.pdf")
    html_to_pdf("\n".join(parts), out)
    return out


def convert(paths, each=False):
    if each:
        return [batch_to_pdf([p]) for p in paths]
    return [batch_to_pdf(paths)]


if __name__ == "__main__":
    argv = sys.argv[1:]
    each = "--each" in argv
    paths = [p for p in argv if not p.startswith("--")]
    bad = [p for p in paths
           if os.path.splitext(p)[1].lower() not in IMAGE_EXT]
    if bad:
        sys.exit(f"not images: {bad}")
    for p in convert(paths, each):
        print(p)
