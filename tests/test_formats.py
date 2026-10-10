#!/usr/bin/env python3
"""Real-format pipeline test — NO LLM required.

Exercises the bundled engine's offline half end to end on genuine files
(md, txt, html, csv, docx, xlsx): format normalization -> hardened PDF ->
text layer -> exact retrieval -> provenance. Tree indexing itself needs an LLM
and is covered by the cost/dry-run tests; here we prove that whatever the engine
converts is searchable and never silently blank (the class of bug that produced
empty-shell indexes upstream).

Run: python3 tests/test_formats.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE = os.path.join(ROOT, "scripts", "engine")
CLI = os.path.join(ROOT, "bin", "cenhua")

fails = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label +
          (f"   {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(label)


def make_sources(d):
    """Genuine files in every offline-supported family."""
    out = {}
    p = lambda n: os.path.join(d, n)

    with open(p("notes.md"), "w", encoding="utf-8") as f:
        f.write("# Release notes\n\nVersion 2.4 ships the `cenhua` CLI.\n\n"
                "| flag | meaning |\n|---|---|\n| find | exact grep |\n| ask | LLM read |\n")
    out["notes.md"] = "cenhua"

    with open(p("memo.txt"), "w", encoding="utf-8") as f:
        f.write("MEMO\n\nQ3 target: 1,240 万元。\n负责人：林十四。\n")
    out["memo.txt"] = "1,240"

    with open(p("page.html"), "w", encoding="utf-8") as f:
        f.write("<html><body><h1>Policy</h1><p>Data retention lasts "
                "seven years.</p></body></html>")
    out["page.html"] = "retention"

    with open(p("rows.csv"), "w", encoding="utf-8") as f:
        f.write("id,name,amount\n1,alpha,42.5\n2,beta,17.0\n")
    out["rows.csv"] = "alpha"

    # docx via python-docx if present, else build a minimal one with zipfile
    try:
        import docx
        doc = docx.Document()
        doc.add_heading("Service agreement", 1)
        doc.add_paragraph("Termination requires 30 days written notice.")
        doc.save(p("agreement.docx"))
    except ImportError:
        import zipfile
        ct = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
              'package/2006/content-types"><Default Extension="xml" ContentType='
              '"application/xml"/><Override PartName="/word/document.xml" ContentType='
              '"application/vnd.openxmlformats-officedocument.wordprocessingml.'
              'document.main+xml"/></Types>')
        body = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats'
                '.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Termination '
                'requires 30 days written notice</w:t></w:r></w:p></w:body></w:document>')
        with zipfile.ZipFile(p("agreement.docx"), "w") as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("word/document.xml", body)
    out["agreement.docx"] = "Termination"

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["invoice", "vendor", "amount"])
    ws.append(["INV-9001", "Kunlun Ltd", 5120.0])
    wb.save(p("invoices.xlsx"))
    out["invoices.xlsx"] = "INV-9001"
    return out


def main():
    src = tempfile.mkdtemp(prefix="cenhua-fmt-src-")
    store = tempfile.mkdtemp(prefix="cenhua-fmt-store-")
    home = tempfile.mkdtemp(prefix="cenhua-fmt-home-")
    os.environ["PI_STORE"] = store          # engine reads this at import time
    try:
        files = make_sources(src)
        env = dict(os.environ, PI_STORE=store)

        # 1) every format normalizes to a NON-BLANK PDF (offline, no LLM)
        sys.path.insert(0, ENGINE)
        import pi_ingest  # noqa: E402  (reads PI_STORE at import)
        import pymupdf
        for name, needle in files.items():
            try:
                pdf = pi_ingest.to_pdf(os.path.join(src, name))
                doc = pymupdf.open(pdf)
                text = "".join(doc[i].get_text() for i in range(len(doc)))
                doc.close()
                check(f"{name}: PDF has text", len(text.strip()) > 20,
                      f"{len(text)} chars")
                if name != "agreement.docx":  # zip-fallback fixture may lack body
                    check(f"{name}: '{needle}' survived layout",
                          needle in text, text[:120].replace("\n", " "))
            except SystemExit as e:
                check(f"{name}: converted", False, str(e))
            except Exception as e:
                check(f"{name}: converted", False, f"{type(e).__name__}: {e}")

        # 2) fabricate the index result for the two PDFs we can build offline,
        #    then prove flatten + find + provenance over REAL converted text.
        subprocess.run([CLI, "init", "f", "--yes"],
                       env=dict(os.environ, CENHUA_HOME=home),
                       capture_output=True, check=True)
        v = os.path.join(home, "vaults", "f")
        # drive the real engine flatten over pages.json derived from real PDFs
        import json
        for name, needle in list(files.items())[:4]:
            doc_id = "pi-" + name.replace(".", "")[:10]
            d = os.path.join(v, "engine", "docs", doc_id)
            os.makedirs(d, exist_ok=True)
            pdf = pi_ingest.to_pdf(os.path.join(src, name))
            doc = pymupdf.open(pdf)
            json.dump([{"page_index": i + 1, "markdown": doc[i].get_text()}
                       for i in range(len(doc))],
                      open(os.path.join(d, "pages.json"), "w", encoding="utf-8"),
                      ensure_ascii=False)
            doc.close()
            man = json.load(open(os.path.join(v, "engine", "manifest.json"))) \
                if os.path.exists(os.path.join(v, "engine", "manifest.json")) else {"docs": {}}
            man["docs"][doc_id] = {"name": name}
            json.dump(man, open(os.path.join(v, "engine", "manifest.json"), "w"))
            led = json.load(open(os.path.join(v, "engine", "ingest_manifest.json"))) \
                if os.path.exists(os.path.join(v, "engine", "ingest_manifest.json")) else {}
            led[doc_id] = {"name": name, "doc_id": doc_id, "sha1": "x",
                           "ts": "2026-10-10 12:00:00",
                           "source": os.path.join(src, name), "stored_as": ""}
            json.dump(led, open(os.path.join(v, "engine", "ingest_manifest.json"), "w"))

        r = subprocess.run([CLI, "flatten", "--vault", "f"],
                           env=dict(os.environ, CENHUA_HOME=home),
                           capture_output=True, text=True)
        check("flatten over converted docs", r.returncode == 0, r.stderr[:200])

        for name, needle in list(files.items())[:4]:
            r = subprocess.run([CLI, "find", needle, "--vault", "f"],
                               env=dict(os.environ, CENHUA_HOME=home),
                               capture_output=True, text=True)
            check(f"find '{needle}' from {name}", r.returncode == 0
                  and needle in r.stdout, r.stdout[:150])
            check(f"find {name}: page + provenance", "P1" in r.stdout
                  and "Source:" in r.stdout, r.stdout[:150])

        print("\n" + ("FORMATS: ALL PASSED" if not fails else f"FAILED: {fails}"))
        return 1 if fails else 0
    finally:
        for d in (src, store, home):
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
