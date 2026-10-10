# CENHUA · 岑华

> *The Kunlun tree of the classic Mountain Classic (Shanhaijing) that marks the
> seasons and records all things.* — a time-aware memory tree for your personal
> knowledge.

**A personal second brain as a single CLI.** Drop any files into an inbox;
CENHUA indexes them (vectorless document trees + an exact local text layer),
and every answer comes back with `[doc P page]` citations traceable to *your
original upload* — archived inside the vault, so provenance survives even after
you delete the source file.

Built for AI agents (OpenClaw, Hermes, or any agent that can run a shell):
one `cenhua` command, one decision table, zero cloud lock-in. Any
OpenAI-compatible endpoint works — hosted or fully local (Ollama/vLLM).

## Why it is fast AND trustworthy

- **Deterministic grep first.** Per-page text is extracted at ingest time;
  "where does this term appear (and on which page)?" answers in <0.1s across
  ~70 docs, zero LLM cost, zero hallucination risk.
- **LLM only for meaning.** Summaries and cross-page reasoning navigate
  PageIndex-style tree indexes, in parallel, with timeouts and gateway failover.
- **Provenance is not optional.** Every hit prints which upload it came from
  and where the archived original lives.
- **Cost guardrails built in.** `ask --dry-run` estimates calls; a per-run
  ceiling refuses runaway sweeps.

## 60-second start

**A. Through your agent (recommended): send the GitHub link.**
CENHUA is a standard OpenClaw skill (SKILL.md at repo root). Tell your agent:

> install this skill: https://github.com/<you>/cenhua

or run it yourself:

```bash
openclaw skills install git:github.com/<you>/cenhua
openclaw skills check          # cenhua should show ✓ ready
# agent's first run (or yours):
~/.openclaw/skills/cenhua/bin/cenhua setup     # deps + default vault
```

`setup` then asks **two questions** and never answers them for you.
**1) where the knowledge base lives** — `~/.cenhua` (default), the install dir
(`cenhua setup --home <skill-dir>` → `<skill>/vaults/<name>`, self-contained but
update-fragile), or any path you name; `cenhua home set <path>` relocates later.
**2) which LLM to use**:

```text
1) reuse the OpenClaw model config found on this machine   (recommended)
   -> cenhua setup --gateway openclaw:<provider>[/<model>]
      keys stay in openclaw.json, resolved live, never copied
2) bring your own endpoint                                 (PI_BASE/PI_KEY)
   -> cenhua setup --gateway env
```

`cenhua gateway list` previews providers (OpenClaw's primary model and its
configured image model — auto-used for vision — are marked). Check anytime with
`cenhua gateway` / `cenhua doctor`. Then chat:
"index the files I uploaded" / "find X in my documents".

**B. Plain CLI:**

```bash
git clone https://github.com/<you>/cenhua && cd cenhua
./bin/cenhua setup                    # pip deps + default vault
export PI_BASE=https://api.example.com/v1  PI_KEY=***  PI_MODEL=openai/gpt-4o-mini

cp ~/Downloads/*.pdf ~/.cenhua/vaults/default/inbox/
cenhua add --inbox                    # or: cenhua watch   (background)
cenhua find 违约 penalty            # instant, offline, page numbers
cenhua ask --doc contract "what are the termination penalties?"
```

Works offline: `find`, `read`, `status`, `doctor`, `sources` need no LLM at all.

## Supported inputs

`pdf` (scans auto-routed to vision OCR) · `md txt html csv` ·
`docx pptx xlsx xls` (pure-python, no LibreOffice) · images `jpg png webp bmp gif`
(vision model). Everything is normalized to a hardened PDF before indexing;
duplicates are refused by sha1 (no double billing).

## Commands

```
VAULTS    init · vaults · use · status · doctor · rm · config · sources
INTAKE    add <files|dir|--inbox> · watch [--interval N] [--once]
RETRIEVE  find <terms> [-d doc] [-i] [-r] · read <doc> [-p N] [-g re] · list
DEEP READ ask [--doc kw | --all] "q" [--limit N] [--dry-run]   (cost-guarded)
SEMANTIC  index build|status · seek "question"     (optional embeddings layer)
```

Rule: **grep for existence, LLM for meaning.** `find` (free) → `ask --doc` →
`seek` → `ask --all` (last). See `SKILL.md` for the agent contract and
`zh/SKILL.zh.md` for 中文文档.

## Layout

```
cenhua/
├── SKILL.md                 # agent skill entry (English)
├── zh/SKILL.zh.md           # 中文辅助文档
├── scripts/
│   ├── cenhua               # the one CLI you ever call
│   ├── m_lib.py             # vaults, env, engine bridge, citations
│   ├── m_ingest.py          # inbox → index → text layer, dedupe, quarantine
│   ├── m_search.py          # find / read (offline)
│   ├── m_ask.py             # ask + cost guardrail
│   ├── m_vectors.py         # optional embeddings recall layer
│   ├── m_vault.py           # init / status / doctor / provenance
│   └── engine/              # bundled pageindex-rag engine (kept upstream-pure)
├── references/              # pitfalls · intake · retrieval playbook (load on demand)
└── tests/                   # offline unit tests + smoke script (no API needed)
```

Runtime vault (`~/.cenhua/vaults/<name>/`): `inbox/` (the only user-facing dir),
`engine/` (indexes + `sources/` archived originals + `text/` layer), `works/`,
`meta/`, `logs/`.

## Privacy & security

- API keys live only in environment variables; `vault.yaml` refuses to store them.
- Documents are indexed on your machine against an endpoint you choose.
- Keep `~/.cenhua/` out of synced folders; corpora contain PII.

## Testing

```bash
python3 tests/test_cenhua.py   # 24 offline unit tests (no API key needed)
bash tests/smoke.sh            # end-to-end offline smoke
```

## Credits & license

CENHUA bundles a self-contained copy of the **pageindex-rag** engine (v1.2, MIT)
under `scripts/engine/`, kept byte-identical to its source so it can be diffed
and upgraded. That engine performs document→PDF normalization and drives
[PageIndex](https://github.com/VectifyAI/PageIndex) (vectorless, reasoning-based
RAG by [VectifyAI](https://github.com/VectifyAI)). On top of it CENHUA adds
multi-vault management, the inbox intake loop, cost guardrails, provenance UX,
the optional semantic recall layer and the agent contract in `SKILL.md`.
MIT — see LICENSE.
