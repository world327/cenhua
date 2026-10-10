#!/usr/bin/env python3
"""conv_office.py — Office documents (docx/pptx/xlsx/xls) -> PDF (no LibreOffice).
try: import _site  # local site defaults (no-op in published pkg)
except ImportError: pass


Renders to PDF via the hardened insert_htmlbox layout engine in pi_ingest.py
(CJK-safe, silent-blank-proof), NOT LibreOffice (broken on many hosts; and its
output fonts sometimes break PageIndex's internal PyPDF2 extraction).

Routes:
  .docx  -> mammoth docx->HTML (semantic headings/lists/tables/images-stripped)
  .pptx  -> python-pptx per-slide text + tables, "## Slide n" sections
  .xlsx  -> openpyxl per-sheet HTML tables; sheets >=20 wide cols are emitted
            as per-record "## row" blocks (wide markdown tables can lose cols)
  .xls   -> xlrd (legacy format) same table path as xlsx

Usage: python3 conv_office.py FILE...      # writes <stem>_<sha1_12>.pdf beside cwd
Prints the produced PDF paths (one per line) for the caller to ingest.
Env: PI_TMPDIR for intermediates (default system temp).
"""
import hashlib
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pi_ingest import html_to_pdf  # noqa: E402


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def conv_docx(src):
    import mammoth
    with open(src, "rb") as f:
        html = mammoth.convert_to_html(
            f, convert_image=mammoth.images.img_element(
                lambda i: {"src": "", "alt": "[IMAGE stripped]"})).value
    return html


def conv_pptx(src):
    from pptx import Presentation
    prs = Presentation(src)
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        parts.append(f"<h2>Slide {i}</h2>")
        for shape in slide.shapes:
            if shape.has_table:
                rows = []
                for r in shape.table.rows:
                    cells = [f"<td>{esc(c.text)}</td>" for c in r.cells]
                    rows.append("<tr>" + "".join(cells) + "</tr>")
                parts.append("<table>" + "".join(rows) + "</table>")
            elif shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = "".join(run.text for run in para.runs).strip()
                    if t:
                        lvl = min((para.level or 0) + 2, 6)
                        parts.append(f"<h{lvl}>" if lvl == 2 and len(t) < 40
                                     else "<p>")
                        parts.append(esc(t))
                        parts.append(f"</h{lvl}>" if lvl == 2 and len(t) < 40
                                     else "</p>")
        if slide.has_notes_slide:
            nt = slide.notes_slide.notes_text_frame.text.strip()
            if nt:
                parts.append(f"<blockquote>notes: {esc(nt)}</blockquote>")
    return "\n".join(parts)


def _table_html(rows, header_first=True):
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    if width >= 20:
        # wide roster -> per-record blocks (wide tables lose columns in
        # downstream extraction; measured on a 31-col list)
        head = [str(c).strip() for c in rows[0]] if header_first else []
        body = rows[1:] if header_first else rows
        out = []
        for r in body:
            cells = [str(c).strip() for c in r]
            first = next((c for c in cells[:3] if c), "row")
            out.append(f"<h3>{esc(first)}</h3><p>")
            out.append("<br>".join(
                f"{esc(head[j] if j < len(head) and head[j] else 'col' + str(j + 1))}: {esc(c)}"
                for j, c in enumerate(cells) if c))
            out.append("</p>")
        return "".join(out)
    parts = ["<table>"]
    if header_first:
        parts.append("<tr>" + "".join(f"<th>{esc(c)}</th>"
                                      for c in rows[0]) + "</tr>")
        body = rows[1:]
    else:
        body = rows
    for r in body:
        parts.append("<tr>" + "".join(f"<td>{esc(c)}</td>"
                                      for c in r) + "</tr>")
    parts.append("</table>")
    return "".join(parts)


def conv_xlsx(src):
    import openpyxl
    # NOTE: do NOT use read_only=True — WPS/exported files carry wrong
    # <dimension> so read-only mode returns a single header row. Normal mode
    # reads the real data (measured: 1 row vs 24 rows on the same file).
    wb = openpyxl.load_workbook(src, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"<h2>Sheet: {esc(ws.title)}</h2>")
        rows = [[("" if c is None else c) for c in row]
                for row in ws.iter_rows(values_only=True)]
        parts.append(_table_html(rows))
    wb.close()
    return "\n".join(parts)


def conv_xls(src):
    import xlrd
    wb = xlrd.open_workbook(src)
    parts = []
    for ws in wb.sheets():
        parts.append(f"<h2>Sheet: {esc(ws.name)}</h2>")
        rows = [[ws.cell_value(r, c) for c in range(ws.ncols)]
                for r in range(ws.nrows)]
        parts.append(_table_html(rows))
    return "\n".join(parts)


CONVERTERS = {".docx": conv_docx, ".pptx": conv_pptx,
              ".xlsx": conv_xlsx, ".xls": conv_xls}


def convert(src):
    ext = os.path.splitext(src)[1].lower()
    fn = CONVERTERS.get(ext)
    if fn is None:
        raise ValueError(f"unsupported office format: {ext}")
    html = fn(src)
    if not re.search(r"\w", re.sub(r"<[^>]+>", " ", html)):
        raise RuntimeError(f"extracted no text from {src} (empty/corrupt?)")
    tmp = os.environ.get("PI_TMPDIR") or tempfile.gettempdir()
    os.makedirs(tmp, exist_ok=True)
    out = os.path.join(tmp, f"{os.path.splitext(os.path.basename(src))[0]}"
                            f"_{_sha1(src)[:12]}.pdf")
    if not os.path.exists(out):
        html_to_pdf(html, out)
    return out


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(convert(os.path.abspath(p)))
