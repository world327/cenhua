# Intake workflow (triage before indexing)

What the bundled engine does per format, and what you must decide yourself
before dropping a file into the inbox. CENHUA routes by extension automatically;
the decisions that remain are about *quality* and *cost*.

## Triage table

| Source | What happens | What you should check |
|---|---|---|
| Native-text PDF | indexed directly | — |
| Password-protected PDF | engine refuses; ingest fails loudly | try filename digit-runs as the password, save `<name>-decrypted.pdf`, ingest that; never log the password |
| Image-only scan PDF | per-page probe: text pages kept verbatim, blank pages → vision OCR | `PI_VISION_MODEL` set and vision-capable; page count vs `--max-pages` quota (default 40) |
| Screenshot / photo | vision transcription → PDF with a real text layer | warn the user: index quality = transcript quality |
| Roster / very wide table (≥20 cols) | `conv_office.py` emits per-record blocks, not one wide table | if you pre-convert to markdown yourself, use per-record `## name` + `field: value` blocks |
| Chat-log / huge CSV export | fine as-is below ~1500 pages | above that, split into ~500-page volumes and ingest per volume |
| Office (docx/pptx/xlsx/xls) | pure-python converters, no LibreOffice | nothing |

## Transcription contract (applies to every image/scan)

The vision step is instructed to follow this, and you must hold to it when you
summarize what it produced:

- Keep digits verbatim (amounts, account numbers, IDs). Never "fix" one.
- Preserve table structure.
- Uncertain character → `X?`; unreadable → `○`.
- Never guess a name. If two copies of a document disagree, record BOTH readings
  and mark it "needs original".
- Handwriting: mark confidence. An ambiguous amount is a lead, not a fact.

After ingest, the original file is archived under `engine/sources/<original
name>` and recorded in `source_map.csv` + `ingest_manifest.json`. The transcript
layer and the archived original always stay separate: quote the transcript,
verify against the original.

## Batch etiquette

- `cenhua add dir/...` ingests file by file in separate subprocesses, so one bad
  file cannot strand the batch. Failures land in `inbox/.failed/` with the reason
  in `logs/ingest-*.log`.
- On a rate-limited plan: ingest in chunks, wait some minutes, re-run — sha1
  dedupe means nothing is billed twice. For paced automation use
  `python3 scripts/engine/batch_ingest.py` (cooldown + retry round) or just loop
  `cenhua watch`.
- Long jobs: run `cenhua watch` in the background; it indexes files whose size
  has been stable for one polling round, so a half-copied file is never grabbed.
- Escape hatch for forensics (export `PI_STORE=<vault>/engine` before running
  them): `engine/scan_corpus.py` offline exact-string scan of cached PDFs,
  `engine/scan_number.py` OCR-tolerant number variants, `engine/id_verify.py`
  mainland-CN resident-ID checksum and decoder.

## Privacy

Personal corpora contain PII (IDs, cards, phones, contracts). Keep
`~/.cenhua/` out of synced and shared folders, never paste raw PII into generated
or published content, and strip it before committing anything.
