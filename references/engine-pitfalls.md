# Engine pitfalls (learned from real failures — do not rediscover)

The `scripts/engine/` directory is the bundled pageindex-rag engine, kept
byte-identical to upstream so it can be diffed and upgraded. Everything below is
why CENHUA is shaped the way it is. `cenhua doctor` automates most checks.

## Retrieval correctness

- **Encrypted PDFs are silently skipped by naive scanners.** `pymupdf.open()` +
  `get_text()` on a password PDF raises; an `except: continue` drops the whole
  document, and you conclude "not in the vault" while it sits inside a
  password-protected bank statement. Exported bank/app PDFs often embed the
  password in the filename digit runs — try `doc.authenticate(<digits>)` from the
  filename before giving up (`engine/scan_corpus.py` and `scan_number.py` do
  this). Decrypt, re-ingest the decrypted copy, never log the password.
- **Never claim "not in corpus" from one path.** `find` hits and a negative
  scan over the source files must agree. If a path failed (timeout, crash,
  empty text layer), its silence is not evidence.
- **OCR text carries digit noise.** Search card/account numbers with the exact
  full form AND space/hyphen-stripped variants; treat tail-6/tail-8 fragments as
  leads only — transfer amounts collide with card tails. Use
  `cenhua find -r` with boundaries `(?<![\dA-Za-z])NUM(?![\dA-Za-z])`: an
  unbounded 11-digit scan once returned 110 "hits" versus 7 real numbers.
- **Person names**: sweep homophone/grapheme variants in one `find` call
  (`find 张三 张山 章三`).
- **OCR'd ID numbers commonly have 1-2 wrong digits.** Run
  `python3 scripts/engine/id_verify.py <num>`; a failing checksum blocks any
  identity conclusion until the original is checked.

## PageIndex client API

- `index={...}` dict and flat kwargs cannot be mixed — everything goes inside
  `index={"model":..., "backend":..., "storage_path":...}`.
- Local-mode connection params live under the key `backend`; `api_base` goes
  INSIDE that dict, otherwise "Unknown index keys".
- Model names need the `openai/` prefix (LiteLLM routing) even for
  OpenAI-compatible endpoints. `PI_MODEL=openai/gpt-4o-mini`.
- The backend dict passes extra keys (`timeout`, `max_retries`) to the openai
  SDK — always set them; a hung gateway otherwise blocks forever, and failover
  multiplies the hang across gateways.
- **Pure-table documents** (bank statements, xlsx→md) fail fast index mode with
  `found no layout structure (N pages)` — the engine resubmits with
  `mode="standard"` automatically. Standard mode costs more tokens.
- Indexing is slow (52 pages ≈ 140s; `Retrying LLM completion` mid-way is
  normal). Run long ingests in the background (`cenhua watch`).
- **Deterministic vs transient failure**: the same vague error at the same tree
  node across retries on a healthy file is deterministic → split the PDF in half
  (~50p → ~25p per volume) and re-index. Drifting errors are transient: retry.
- Rate-limit exhaustion: pace batches with 60-90s cooldowns, then resume —
  sha1 dedupe (engine + `meta/dedupe.json`) means no double billing.

## Markdown/HTML → PDF layout (PyMuPDF `insert_htmlbox`)

- **`insert_htmlbox` renders BLANK SILENTLY and returns success** when content
  overflows. Triggers: wide tables (>14 cells) at normal font; a block taller
  than the page; a measurement page rendered at a different `scale_low`; a giant
  merged `<p>` (~38+ lines) blanks the whole block regardless of CSS. Long
  spaceless tokens (transaction IDs) need U+200B every 12 chars.
  Defense built into the engine: post-render check
  `pdf_chars >= 0.85 * source_visible_chars`, else delete the PDF and raise.
  This exact bug produced 8 empty-shell indexes once. **`cenhua doctor` flags
  empty text layers as a PROBLEM — never ignore it.**
- Do NOT build PDFs with `fitz.Story`: its ToUnicode font mapping makes
  PageIndex's internal PyPDF2 extraction crash with `Odd-length string`.
- Wide tables (≥20 columns) converted to markdown can LOSE COLUMNS (measured on
  a 31-column roster). For record-shaped wide data emit per-record
  `## name` + `field: value` blocks instead of one table.
- Never name your own index manifest `manifest.json` at the store root —
  PageIndex owns it. The ingest ledger is `ingest_manifest.json`.
- Server-side manifests append `_<12hex>.pdf` dedupe suffixes to doc names;
  `m_lib.store_docs()` strips them before mapping docs to source files.
- Filenames with curly quotes: build paths from `os.listdir()` or `\u201c\u201d`
  escapes; hardcoded straight-quote paths will miss.
- Verify "is it indexed?" against `<store>/manifest.json` + `<store>/docs/`, not
  the ingest manifest (background jobs may not write it back).

## Scanned and image-only PDFs

- Probe the text layer first (`get_text()` per page; all blank = scan). Without
  a local OCR engine: render pages at `Matrix(2.5)` → PNG → a vision model
  transcribes → markdown → ingest the transcript. **Index quality = transcript
  quality; say so in answers.**
- `PI_VISION_MODEL` must be a BARE model id (the OpenAI SDK does
  `GET {base}/models`); a LiteLLM-style `openai/xxx` prefix 404s on raw
  endpoints. Many "flash" chat models are not vision-capable and fail with
  schema/400 errors rather than a clean "no vision" message — `doctor` probes it.
- Vision APIs time out on dense bank-statement pages. Use
  `pi_query`/`conv_scan --probe` for a cost check and `--max-pages` (default 40)
  as a quota guard.
- `openpyxl(read_only=True)` on WPS/exported xlsx with a wrong `<dimension>`
  returns ONE header row (looks like an empty sheet). Normal mode: 1 row vs
  24 rows measured on the same file.
- mammoth strips embedded images by default — keep that; base64 image spam
  inside the PDF destroys index quality.

## Text layer freshness (the classic silent-miss trap)

- `find` reads `engine/text/`, NOT the PDFs. After any ingest you must flatten,
  or `find` silently misses new documents. CENHUA runs `pi_flatten.py`
  automatically after every successful ingest and auto-flattens inside `find`
  when a doc lacks text — do not disable it (`--no-flatten` exists for bulk
  re-ingest only).
- `pages.json` field names are `markdown` / `page_index` (older builds:
  `content` / `page`); the flatten step tolerates both. Guessing wrong exports a
  blank text layer.

## Cost model (measured)

- 66 docs / ~90MB: local full-text extraction 1.3s; grep 0.05s; 2-doc parallel
  chat ~11s; 80-doc `--all` ~10min at 5 workers (was ~1h serial).
- A slow "search" is almost always the LLM chain (tree nav + answer = ≥2 round
  trips per doc, failover multiplying hangs), never the local scan. Profile
  before blaming retrieval — and remember `find` is free.
