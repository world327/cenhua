---
name: cenhua
description: "Personal second brain / local knowledge base. Use when the user uploads local files to build an index (pdf, docx, pptx, xlsx, md, txt, html, csv, images, scans), asks about their own documents ('what did my contract say about...', 'find in my notes', 'in which file did X appear'), or wants drafts/outlines grounded in their own corpus with page-level citations. One CLI: cenhua. Multi-vault (per project/domain). Vectorless tree index plus an exact local grep layer."
metadata:
  {
    "openclaw":
      {
        "emoji": "🌳",
        "skillKey": "cenhua",
        "requires": { "bins": ["python3"] },
        "primaryEnv": "PI_KEY",
      },
  }
---

# CENHUA — personal second brain

Cen-hua 岑华: the Kunlun tree of the classic Mountain Classic that marks the
seasons and records all things. One tree index per document, one exact text
layer per vault, every original archived so every answer stays verifiable.
Version 0.1.0 · MIT.

## First run (after a fresh install, e.g. from a GitHub link)

```bash
<skill-dir>/bin/cenhua setup        # installs python deps, creates default vault
```

Idempotent. It then needs **TWO decisions from the user**, which you must NOT
make on their behalf:

**Decision 1 — where the knowledge base lives** (`setup`/`init` exit **6** with
`CONFIRM REQUIRED` when undecided). The corpus (documents + indexes + archived
originals) outlives skill updates, so ask:

- **1) `~/.cenhua`** — recommended default, survives skill updates
- **2) the install dir** (`<skill>/vaults/<name>`) — self-contained; warn that a
  skill update/reinstall may delete that tree; choose only if the user asks
- **3) a custom path** they name (external disk, non-synced folder)

Apply and verify:
```bash
cenhua setup --home <path>        # or: cenhua home set <path>   (relocates, carries vaults)
cenhua home                       # current root, source, size, vault list
```
Only a one-line pointer is stored (`~/.config/cenhua/location`); `CENHUA_HOME`
still overrides everything. Never pick a location silently — and never write
personal documents into the repo.

**Decision 2 — which LLM to use** — tree indexing (`add`) and deep read (`ask`)
cost LLM calls:

- If setup exits **5** with `CONFIRM REQUIRED`, it found a local OpenClaw config
  and is asking which gateway to use. Relay the two options verbatim:
  **1) reuse OpenClaw's model config** (recommended — keys stay in
  `openclaw.json`, are read live, never copied by CENHUA) or
  **2) bring their own endpoint** (`PI_BASE/PI_KEY/PI_MODEL`).
- Apply the answer, then verify:
  ```bash
  cenhua setup --gateway openclaw:<provider>[/<model>]   # option 1
  cenhua setup --gateway env                             # option 2
  cenhua gateway        # shows base/model, key: ***
  ```
  `cenhua gateway list` shows the providers (marking OpenClaw's own primary
  model and any configured image model, the vision FALLBACK for images/scans).
- Never pick a provider or model silently, and never copy a key into a vault
  file: the OpenClaw choice stores a *reference* and resolves it at call time.

Without a gateway the vault still works offline: `flatten`, `find`, `read`,
`status`, `doctor`, `sources` all run. Only ingest and `ask` need LLM.

## The one rule that matters

**`find` for existence, `ask` for meaning.**
"Where does X appear / on which page / does my corpus mention Y at all" are
answered by `find` — local regex over the flattened text layer, milliseconds,
free, exact, complete. Never ask an LLM an existence question: it silently
misses. Reserve `ask` for summaries, characterizations and cross-page inference.

## Decision table

| User wants | Command | Costs |
|---|---|---|
| store uploaded files | `cenhua add <paths>` or drop into `<vault>/inbox` then `cenhua add --inbox` (`.eml`/`.msg` auto-expand attachments) | 1 LLM index/doc (image/scan transcription: local, free) |
| store a web page / URL | `cenhua add --url <url>` (repeatable; `--url-file <list>` for many; `--force` to ignore robots) | 1 LLM index/page |
| keep inbox ingested automatically | `cenhua watch` (background; `--urls` also drains `inbox/urls/*.url`) | same |
| "which docs relate to X?" | `cenhua related <doc>` (evidence per edge; empty result is meaningful) | offline, free |
| declare a relation / suppress an entity pair | `cenhua link <A> <B>` / `cenhua link --ban <e1> <e2>`; review hubs with `cenhua hub` | offline, free |
| refine rule-summaries with LLM (budgeted) | `cenhua refine --all --dry-run`, then `CENHUA_REFINE_BUDGET_CNY=<n> cenhua refine --drain` | queue-gated, ledger-recorded |
| "where does X appear? / does my corpus mention X?" | `cenhua find <term>...` | offline, free |
| narrow to one document | `cenhua find X -d <doc-kw>` | offline, free |
| verify a quote against the original | `cenhua read <doc> -p <page>` | offline, free |
| "what does doc X say about Y?" (meaning) | `cenhua ask --doc <kw> "question"` | 1 call/doc |
| sweep the whole vault | `cenhua ask --all "question" --limit N --dry-run` first | N calls |
| fuzzy rephrasing, grep found nothing | `cenhua seek "question"` | embeddings |
| which upload did this come from | `cenhua sources <kw>` | offline, free |
| what is in here / is it healthy | `cenhua status` / `cenhua doctor` | offline, free |
| another project or domain | `cenhua init <name>` + `--vault <name>` on every call | — |

## Iron rules

1. **Never call `scripts/engine/pi_*.py` directly.** The engine needs `PI_STORE`
   wiring, post-ingest flatten and a cost ceiling; only `cenhua` provides them.
2. **Never conclude "not in my files" from one path.** Run `find` with variants
   (homophones, hyphen/space-stripped numbers, English/Chinese), and confirm
   `doctor` reports no empty text layer. A failed path's silence is not evidence.
3. **Quote with the citation the tool gives you**: `[doc_id P<n>]` plus the
   `Source:` line naming the original upload and its archived copy. If a claim
   matters, `cenhua read` that page and check it before repeating it.
4. **Run `--dry-run` before any `--all`.** It prints the call count; the CLI
   also refuses above `max_llm_calls` (default 8) unless `--force`.
5. **`find` returning nothing after ingest is usually a stale text layer** — the
   CLI auto-flattens, but `cenhua flatten` is the fix and it is free.

## Escalation ladder (always cheapest first)

```
find (free)  →  ask --doc <kw>  →  seek (if configured)  →  ask --all (last)
```

## Invocation

The CLI is `bin/cenhua` **inside this skill directory** (it resolves its own
path — no PATH edit, no `~/.local/bin` dependency). Call it by absolute path:

```bash
CENHUA=~/.openclaw/skills/cenhua/bin/cenhua     # adjust if installed elsewhere
"$CENHUA" status
```

Every command below is written as `cenhua ...` and means that binary.

## Setup (once per machine / per agent env)

```bash
export PI_BASE=https://api.example.com/v1   # any OpenAI-compatible endpoint
export PI_KEY=***                        # keys live in env ONLY, never on disk
export PI_MODEL=openai/gpt-4o-mini          # needs the openai/ prefix
export PI_VISION_MODEL=vision-model-id      # bare id; FALLBACK for images/scans (local RapidOCR runs first)
# optional semantic recall layer:
export PI_EMBED_MODEL=text-embedding-v3
cenhua init default --title "Everything"    # add more: cenhua init contracts
```

## Intake: the only thing users must remember

The vault has one user-facing folder: `~/.cenhua/vaults/<name>/inbox/`.
Drop anything there (pdf/docx/pptx/xlsx/xls/md/txt/html/csv/jpg/png/webp/scans),
then `cenhua add --inbox` (or leave `cenhua watch` running). Duplicates are
skipped by sha1 (no double billing); failures move to `inbox/.failed/` with the
reason in `logs/` — nothing is silently dropped. After every successful ingest
the CLI flattens the text layer automatically; that is why `find` is trustworthy.
Images and scanned PDFs are transcribed LOCALLY by RapidOCR (installed
best-effort by `cenhua setup`; free, offline); the vision model only handles
what RapidOCR cannot read. `CENHUA_OCR=vision` forces the LLM route.

## Answer discipline

- Every hit carries a page number. Cite it: `[contract.txt P12]`.
- OCR'd images/scans are transcriptions, not the original text — say so when
  quoting them, and point at the archived original (`cenhua sources`).
- If `find` and `ask` disagree, `find` wins on existence; `ask` wins on gist.
- Report which commands you ran when you say "your files do not mention X".

## Layout

```
~/.cenhua/vaults/<name>/
  inbox/          user drop zone (.processed/ .failed/ are internal staging)
  engine/         PageIndex store: manifest.json docs/ text/ sources/ pdf/
  engine/sources/ ★ archived originals — provenance survives file deletion
  works/          drafts and exports
  meta/           dedupe index, LLM call ledger, optional vectors/, OCR cache
  logs/           ingest + query history
```

## References (load on demand, keep context small)

- `references/engine-pitfalls.md` — every known failure mode of the bundled
  engine (silently-blank PDFs, encrypted PDFs, PageIndex API quirks, OCR cost).
  Read before debugging an ingest or trusting a negative result.
- `references/intake-workflow.md` — transcription contract for images/scans.
- `references/retrieval-playbook.md` — query routing, variants, citation format.
- `zh/SKILL.zh.md` — 中文说明（同一套规则）.
