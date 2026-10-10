# Retrieval playbook

How to answer questions from a CENHUA vault without hallucinating and without
burning tokens. The engine's hard-won rule, verbatim: **grep for existence,
LLM for meaning.**

## Routing

| Question shape | Command | Why |
|---|---|---|
| "does X appear / where / how often / which page" | `find X` | deterministic, complete, free — an LLM silently misses occurrences |
| "summarize / what does it say / which doc covers Y" | `ask --doc <kw> "q"` | needs reasoning; scope to name keywords first |
| "across everything, which documents mention/relate to Z" | `find Z` first, then `ask --doc` on the hit docs | `--all` = 1 LLM call per doc; grep narrows for free |
| rephrasing misses ("that thing about leaving the job early") | `seek "…"` then `find` the exact terms it surfaced | embeddings catch synonyms, grep confirms facts |
| "quote me the exact clause" | `find` → `read -p <page>` | the quote must come from the text layer, never from memory or an LLM paraphrase |

## Term variants (the difference between "not found" and wrong)

One `find` call takes many terms (OR): `cenhua find 违约金 liquidated-damages penalty "breach fee"`.
- Chinese names: homophones/graphemes (张/章, 华/桦).
- Numbers: full form, spaced, hyphen-stripped (`6222020012345678` /
  `6222 0200 1234 5678`); for ID-like strings add `-r` with boundaries so order
  IDs embedding phone-shaped digits do not flood results.
- English: singular/plural and British/American spellings as separate terms
  (regex `-r` also works: `find 'organis|organiz' -r`).
- Filenames: use `-d <kw>` to scope by document name instead.

A negative result is only defensible when: (1) variants were tried, (2)
`doctor` shows no missing/empty text layers, and (3) any failed ingest was
retried. Say which of these you checked when reporting absence.

## Cost discipline

- `ask` prints `[cost] ~N LLM calls` before spending; vault ceiling is
  `max_llm_calls` (default 8; `cenhua config max_llm_calls N`).
- Always `--dry-run` a `--all` sweep. Prefer a 3-doc `--doc` probe over an
  80-doc `--all` sweep; the answer usually lives in 2 files that grep finds.
- The ledger (`meta/llm_calls.json`) is shown in `status` — check it when the
  user asks "what did this cost".

## Citation format (use it verbatim in answers)

`find`/`ask` print, per document:

```
===== contract.txt  (pi-3f8a21...) — 2 hits =====
Source: contract.txt | original archived at ~/.cenhua/vaults/<v>/engine/sources/contract.txt
    [pi-3f8a21 P1] The penalty for early termination is 30% ...
```

In your answer cite as: **[contract.txt P1]** and state the Source line when the
claim is load-bearing. For OCR'd docs add "(transcribed from image/scan; verify
against archived original)".

## Drafting grounded answers / outlines

1. `find` the key entities/numbers → collect `[doc P page]` lines.
2. `ask --doc` the top docs for gist and cross-page inference.
3. Write the outline; attach a `[doc P page]` citation to every factual
   statement. No citation → it is your inference: label it as such.
4. For anything quoted verbatim, `read -p` the page and copy from there.
5. Save output under `<vault>/works/` so provenance stays with the vault.

## Three levels, always separated in your answer

- **What the document says** — quoted/paraphrased with `[doc P page]`.
- **Inference** — your reasoning across documents; label it.
- **Doubts** — OCR conflicts, missing counterparts, stale text layers; list
  them so the user can verify against `engine/sources/`.
