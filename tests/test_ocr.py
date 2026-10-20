#!/usr/bin/env python3
"""Offline tests for the local OCR layer (RapidOCR primary, vision fallback).

RapidOCR itself is NOT required here: the backend is stubbed at m_ocr._ENG,
so the suite runs on any machine. Everything downstream of the OCR call is
real: the engine's own html_to_pdf renders the PDFs and pymupdf reads them
back. Intake wiring (ingest_one -> preconvert -> ledger restore) is covered
with a stubbed engine bridge.

Run:  python3 tests/test_ocr.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ["CENHUA_CONFIG_DIR"] = tempfile.mkdtemp(prefix="cenhua-ocr-cfg-")
os.environ["CENHUA_HOME"] = tempfile.mkdtemp(prefix="cenhua-ocr-home-")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import m_lib as L        # noqa: E402
import m_ocr             # noqa: E402
import m_ingest          # noqa: E402
import pymupdf           # noqa: E402


class FakeEngine:
    """RapidOCR stand-in returning v1-style [[box, text, score], ...] rows."""

    def __init__(self, lines=None, per_file=None, conf=0.9):
        self.lines = lines if lines is not None else ["默认识别文本 alpha 123"]
        self.per_file = per_file or {}
        self.conf = conf
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        lines = self.per_file.get(os.path.basename(path), self.lines)
        return [["box", t, self.conf] for t in lines]


def make_vault(name="t"):
    root = os.path.join(os.environ["CENHUA_HOME"], "vaults", name)
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "vault.yaml"), "w", encoding="utf-8") as f:
        f.write("# test vault\n")
    v = L.Vault(name)
    v.create_dirs()
    return v


def tiny_png(path):
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 64)   # content irrelevant (stubbed)


def make_pdf(path, pages):
    """pages: list of text (None/'' = image-only blank page)."""
    doc = pymupdf.open()
    for text in pages:
        p = doc.new_page()
        if text:
            p.insert_text((72, 100), text, fontsize=14)
    doc.save(path)
    doc.close()


class OcrTest(unittest.TestCase):
    def setUp(self):
        self.v = make_vault(self._testMethodName[:12] or "t")
        self.saved_eng = m_ocr._ENG
        self.saved_env = os.environ.get("CENHUA_OCR")
        os.environ.pop("CENHUA_OCR", None)
        self.tmp = tempfile.mkdtemp(prefix="cenhua-ocr-src-")

    def tearDown(self):
        m_ocr._ENG = self.saved_eng
        if self.saved_env is None:
            os.environ.pop("CENHUA_OCR", None)
        else:
            os.environ["CENHUA_OCR"] = self.saved_env
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.v.root, ignore_errors=True)

    def src(self, name):
        p = os.path.join(self.tmp, name)
        return p

    # ------------------------------------------------------------- routing --
    def test_01_mode_resolution(self):
        self.assertEqual(m_ocr.mode(self.v), "rapidocr")             # default
        os.environ["CENHUA_OCR"] = "vision"
        self.assertEqual(m_ocr.mode(self.v), "vision")               # env wins
        os.environ.pop("CENHUA_OCR")
        with open(self.v.yaml, "a", encoding="utf-8") as f:
            f.write("ocr: vision\n")
        self.assertEqual(m_ocr.mode(self.v), "vision")               # vault.yaml
        os.environ["CENHUA_OCR"] = "rapidocr"
        self.assertEqual(m_ocr.mode(self.v), "rapidocr")             # env still wins

    def test_02_image_preconvert_to_text_pdf(self):
        m_ocr._ENG = FakeEngine(["本季度毛利 1,240 万元", "账号 6222 0200 1234 5678"])
        png = self.src("账单.png")
        tiny_png(png)
        pdf, route = m_ocr.preconvert(png, self.v, L.sha1(png))
        self.assertEqual(route, "image")
        self.assertTrue(os.path.isfile(pdf))
        self.assertIn(".pdf", os.path.basename(pdf))
        doc = pymupdf.open(pdf)
        text = "".join(p.get_text() for p in doc)
        doc.close()
        self.assertIn("毛利", text)
        self.assertIn("6222 0200 1234 5678", text)
        # second call hits the deterministic cache: no second OCR call
        n_calls = len(m_ocr._ENG.calls)
        pdf2, route2 = m_ocr.preconvert(png, self.v, L.sha1(png))
        self.assertEqual((pdf2, route2), (pdf, "image"))
        self.assertEqual(len(m_ocr._ENG.calls), n_calls)

    def test_03_image_fallback_no_text(self):
        m_ocr._ENG = FakeEngine([])                      # readable, nothing found
        png = self.src("blank.png")
        tiny_png(png)
        pdf, route = m_ocr.preconvert(png, self.v, L.sha1(png))
        self.assertEqual((pdf, route), (png, ""))        # -> engine vision route

    def test_04_image_fallback_backend_missing(self):
        m_ocr._ENG = None
        png = self.src("shot.png")
        tiny_png(png)
        pdf, route = m_ocr.preconvert(png, self.v, L.sha1(png))
        self.assertEqual((pdf, route), (png, ""))

    def test_05_mode_vision_bypasses_local(self):
        os.environ["CENHUA_OCR"] = "vision"
        m_ocr._ENG = FakeEngine()                        # would succeed, but:
        png = self.src("shot.png")
        tiny_png(png)
        pdf, route = m_ocr.preconvert(png, self.v, L.sha1(png))
        self.assertEqual((pdf, route), (png, ""))

    # --------------------------------------------------------------- scans --
    def test_06_scan_pdf_ocrs_blank_pages_keeps_text_pages(self):
        m_ocr._ENG = FakeEngine(["扫描页 OCR 文本 alpha 9527"])
        src = self.src("scan.pdf")
        # 24 chars: below pi_ingest's scan threshold (20*min(3,2)=40) so the
        # engine WOULD route it to vision OCR, but above MIN_CHARS=20 so the
        # page itself is kept verbatim once we intercept it.
        make_pdf(src, ["Native text page hybrid.", None])  # page 2 = image-only
        pdf, route = m_ocr.preconvert(src, self.v, L.sha1(src))
        self.assertEqual(route, "scan")
        doc = pymupdf.open(pdf)
        pages = [p.get_text() for p in doc]
        text = "".join(pages)
        doc.close()
        self.assertIn("Native text page", text)          # verbatim page kept
        self.assertIn("扫描页 OCR 文本", text)            # blank page OCR'd
        self.assertIn("本地OCR", text)
        self.assertIn("第2页", text)                      # page headers survive

    def test_07_text_pdf_passes_through(self):
        m_ocr._ENG = FakeEngine()
        src = self.src("text.pdf")
        make_pdf(src, ["Enough real text on the first pages to skip OCR entirely."])
        pdf, route = m_ocr.preconvert(src, self.v, L.sha1(src))
        self.assertEqual((pdf, route), (src, ""))

    def test_08_scan_fallback_backend_missing(self):
        m_ocr._ENG = None
        src = self.src("scan.pdf")
        make_pdf(src, [None, None])                      # pure scan
        pdf, route = m_ocr.preconvert(src, self.v, L.sha1(src))
        self.assertEqual((pdf, route), (src, ""))

    # ----------------------------------------------------------- provenance --
    def test_09_restore_provenance_points_at_original(self):
        pdf = self.src("shot_ab12cd34.pdf")
        tiny_png(pdf)                                    # stands in for a PDF
        orig = self.src("shot.png")
        tiny_png(orig)
        srcdir = os.path.join(self.v.store, "sources")
        os.makedirs(srcdir, exist_ok=True)
        old = os.path.join(srcdir, "shot_ab12cd34.pdf")
        shutil.copy2(pdf, old)                           # engine's archived copy
        man = os.path.join(self.v.store, "ingest_manifest.json")
        with open(man, "w", encoding="utf-8") as f:
            json.dump({"pi-fake123": {"name": "shot_ab12cd34.pdf",
                                      "source": pdf, "stored_as": old,
                                      "sha1": L.sha1(pdf),
                                      "doc_id": "pi-fake123"}}, f)
        m_ingest.restore_provenance(self.v, "pi-fake123", orig, "shot.png")
        rec = json.load(open(man, encoding="utf-8"))["pi-fake123"]
        self.assertEqual(rec["name"], "shot.png")
        self.assertEqual(rec["source"], orig)
        self.assertEqual(rec["stored_as"], os.path.join(srcdir, "shot.png"))
        self.assertTrue(os.path.isfile(rec["stored_as"]))
        self.assertFalse(os.path.exists(old))            # transcription copy gone
        self.assertIn("shot.png", L.provenance(self.v, "pi-fake123"))

    # -------------------------------------------------------------- wiring --
    def test_10_ingest_one_routes_and_restores(self):
        m_ocr._ENG = FakeEngine(["接线测试 OCR 文本 beta 42"])
        png = self.src("接线.png")
        tiny_png(png)
        # the real pi_ingest writes the ledger row our restore step patches;
        # the stubbed bridge does not, so seed what it would have written.
        man = os.path.join(self.v.store, "ingest_manifest.json")
        with open(man, "w", encoding="utf-8") as f:
            json.dump({"pi-wire123": {"name": "接线_ab12cd34.pdf",
                                      "source": "(ocr cache pdf)",
                                      "stored_as": "",
                                      "sha1": "0" * 40,
                                      "doc_id": "pi-wire123"}}, f)
        saved = L.run_engine

        def fake_engine_bridge(script, args, vault, capture=False, timeout=None):
            if script == "pi_ingest.py":
                return 0, ("+ 接线_ab12cd34.pdf -> pi-wire123 "
                           "(0s, gw=gw1, mode=default)")
            return 0, "flattened"

        L.run_engine = fake_engine_bridge
        try:
            self.assertEqual(m_ingest.ingest_one(self.v, png), "added")
        finally:
            L.run_engine = saved
        with open(os.path.join(self.v.meta, "dedupe.json")) as f:
            d = json.load(f)
        self.assertEqual(d[L.sha1(png)]["doc_id"], "pi-wire123")
        self.assertEqual(d[L.sha1(png)]["name"], "接线.png")
        with open(man, encoding="utf-8") as f:
            rec = json.load(f)["pi-wire123"]
        self.assertEqual(rec["name"], "接线.png")
        self.assertEqual(rec["source"], png)
        self.assertTrue(os.path.isfile(rec["stored_as"]))   # original archived

    def test_11b_added_re_survives_multiline_engine_output(self):
        """防回潮：真机 pi_ingest 输出是多行（先 converting/indexing 进度行，
        最后一行才是 `+ name -> doc_id`）。ADDED_RE 缺 re.M 时该场景曾被
        误判 failed（文件误进 .failed/、dedupe 漏记 → 重复计费）。"""
        m_ocr._ENG = FakeEngine(["多行输出测试 gamma 7"])
        png = self.src("多行.png")
        tiny_png(png)
        man = os.path.join(self.v.store, "ingest_manifest.json")
        with open(man, "w", encoding="utf-8") as f:
            json.dump({"pi-multi99": {"name": "多行_ab12cd34.pdf",
                                      "source": "(ocr cache pdf)",
                                      "stored_as": "",
                                      "sha1": "0" * 40,
                                      "doc_id": "pi-multi99"}}, f)
        saved = L.run_engine

        def multiline_engine(script, args, vault, capture=False, timeout=None):
            if script == "pi_ingest.py":
                return 0, ("> 多行_ab12cd34.pdf: converting...\n"
                           "> 多行_ab12cd34.pdf: indexing...\n"
                           "+ 多行_ab12cd34.pdf -> pi-multi99 "
                           "(26s, gw=gw1, mode=default)\n")
            return 0, "flattened"

        L.run_engine = multiline_engine
        try:
            self.assertEqual(m_ingest.ingest_one(self.v, png), "added")
        finally:
            L.run_engine = saved
        with open(os.path.join(self.v.meta, "dedupe.json")) as f:
            self.assertEqual(json.load(f)[L.sha1(png)]["doc_id"], "pi-multi99")
        # an OCR cache PDF exists under meta/ocr/
        cache = os.path.join(self.v.meta, "ocr")
        self.assertTrue(any(f.endswith(".pdf") for f in os.listdir(cache)))

    # -------------------------------------------------- quality validation --
    def test_11_low_confidence_falls_back(self):
        # avg confidence 0.2 < default 0.5 -> vision fallback
        m_ocr._ENG = FakeEngine(["这是一段足够长的识别文本 alpha 12345"])
        m_ocr._ENG.lines = ["这是一段足够长的识别文本 alpha 12345"]
        m_ocr._ENG.conf = 0.2
        png = self.src("lowconf.png")
        tiny_png(png)
        pdf, route = m_ocr.preconvert(png, self.v, L.sha1(png))
        self.assertEqual((pdf, route), (png, ""))

    def test_12_too_few_chars_falls_back(self):
        # 3 chars < default 10 -> vision fallback even with high confidence
        m_ocr._ENG = FakeEngine(["abc"])
        m_ocr._ENG.conf = 0.9
        png = self.src("tiny.png")
        tiny_png(png)
        pdf, route = m_ocr.preconvert(png, self.v, L.sha1(png))
        self.assertEqual((pdf, route), (png, ""))

    def test_13_no_confidence_uses_text_volume_only(self):
        # v2-style backend with no scores: long text passes, short text fails
        class NoConfEngine:
            def __init__(self, lines):
                self.lines = lines
            def __call__(self, path):
                return [["box", t] for t in self.lines]   # no score column
        m_ocr._ENG = NoConfEngine(["足够长的识别文本 alpha 12345 67890"])
        png = self.src("noconf.png")
        tiny_png(png)
        pdf, route = m_ocr.preconvert(png, self.v, L.sha1(png))
        self.assertEqual(route, "image")
        m_ocr._ENG = NoConfEngine(["ab"])
        png2 = self.src("noconf2.png")                 # fresh file: no cache hit
        tiny_png(png2)
        pdf2, route2 = m_ocr.preconvert(png2, self.v, L.sha1(png2))
        self.assertEqual((pdf2, route2), (png2, ""))

    def test_14_quality_thresholds_configurable(self):
        os.environ["CENHUA_OCR_MIN_CONF"] = "0.1"
        os.environ["CENHUA_OCR_MIN_CHARS"] = "2"
        m_ocr._ENG = FakeEngine(["ab"])                    # 2 chars, conf 0.9
        m_ocr._ENG.conf = 0.9
        png = self.src("cfg.png")
        tiny_png(png)
        pdf, route = m_ocr.preconvert(png, self.v, L.sha1(png))
        self.assertEqual(route, "image")                   # passes with looser gate
        os.environ.pop("CENHUA_OCR_MIN_CONF", None)
        os.environ.pop("CENHUA_OCR_MIN_CHARS", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
