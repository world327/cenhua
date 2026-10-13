# CENHUA v0.1.0 发布材料包

仓库：https://github.com/world327/cenhua ·已推送 `main`（2 commits, 35 files）+ 标签 `v0.1.0`
本机无 `gh` CLI 与 GitHub API token，以下三项均在网页端粘贴即可（每段可独立复制）。

---

## 一、仓库 About（Settings → General → Description / Topics，或直接点首页右上角齿轮）

**Description**（285 字符，GitHub 上限 350）

```
Personal second brain as a single CLI and OpenClaw skill. Drop files into an inbox; get answers with [doc P page] citations traceable to your archived originals. Vectorless tree indexes + exact local grep, any OpenAI-compatible endpoint.
```

**Website**（可选）：留空，或填 `https://github.com/world327/cenhua`

**Topics**（16 个，GitHub 规则：小写、连字符、无空格）

```
second-brain
openclaw
openclaw-skill
knowledge-base
rag
vectorless
retrieval-augmented-generation
document-qa
personal-knowledge-management
pkm
local-first
offline-first
self-hosted
citations
ai-agents
python
```

**社交预览图**（可选）：无图时用默认；若要一张，建议把 `🌳 CENHUA — the memory tree that records all things` 做成 1280×640。

---

## 二、v0.1.0 Release notes

页面：`https://github.com/world327/cenhua/releases/new`
Choose tag → 选已存在的 **v0.1.0** · Release title：`CENHUA v0.1.0 — the memory tree` · 勾选 *Set as the latest release*

```markdown
**Cen-hua 岑华** — the Kunlun tree of the classic *Mountain Classic* that marks the seasons and records all things. One tree index per document, one exact text layer per vault, every original archived so every answer stays verifiable.

> Install it by sending the repo link to your agent: `openclaw skills install git:github.com/world327/cenhua`

## Why

Most personal RAG gives you a black-box "answer" and no way to check it. CENHUA keeps two layers apart and never confuses them:

- **Exact layer (`find`)** — per-page text extracted at ingest time; milliseconds, zero tokens, zero hallucination. Existence questions never go to an LLM, because LLMs silently miss occurrences.
- **Meaning layer (`ask`)** — PageIndex-style vectorless tree navigation, in parallel, with timeouts and gateway failover, behind a cost guardrail.

Every hit prints `[doc_id P12]` plus a `Source:` line naming the upload it came from and where the archived original sits — provenance survives you deleting the source file.

## What's in this release

**Intake**
- One folder to remember: `inbox/`. Any format — pdf (scans auto-routed to vision OCR), md/txt/html/csv, docx/pptx/xlsx/xls (pure-python, no LibreOffice), jpg/png/webp images.
- sha1 dedupe on top of the engine's own → re-dropping a file is a no-op, no double billing.
- **Failures are loud**: bad files move to `inbox/.failed/` with the reason in `logs/`; nothing is silently dropped.
- Text layer is rebuilt automatically after every ingest, killing the classic "searched my own vault and missed yesterday's file" trap.

**Retrieval**
- `find` — regex over the text layer, page numbers, offline, free, complete.
- `ask --doc <kw> | --all` — deep read, **`--dry-run` prints the LLM-call estimate before spending**, and a per-run ceiling (default 8) refuses runaway sweeps; ledger in `status`.
- `seek` — optional embeddings recall net for fuzzy rephrasings; degrades gracefully when unconfigured, and always tells you to confirm with `find`.
- `read` / `sources` — quote verification against the raw page and the archived upload.

**Install-time consent — two questions the agent must NOT answer for you**
1. `exit 6 CONFIRM REQUIRED`: where the corpus lives — `~/.cenhua` (default), the install dir, or any path. Only a one-line pointer is stored; `cenhua home set <path>` relocates and carries your vaults.
2. `exit 5 CONFIRM REQUIRED`: which LLM — reuse the local **OpenClaw** model config (vault stores a *reference*; keys are read live from `openclaw.json` and never copied), or bring your own `PI_BASE/PI_KEY`.

Multi-vault by project/domain (`init` / `use` / `--vault`). `doctor` self-checks python deps, gateway reachability, vision-model quirks, empty text layers.

## Privacy & offline

Keys live only in the environment or in a gateway you explicitly referenced — `vault.yaml` refuses to store them. `find`, `read`, `status`, `doctor`, `sources`, `flatten` need no LLM and no network at all.

## Verified

- `openclaw skills install git:github.com/world327/cenhua` → `🌳 cenhua ✓ Ready`, entrypoint runnable from the installed path.
- 34 offline unit tests + mock-endpoint semantic suite + real-format pipeline (md/txt/html/csv/docx/xlsx → hardened PDF → grep) + offline smoke script: `bash tests/run_tests.sh`, no API key required.
- Bundled pageindex-rag engine is kept byte-identical to upstream; a test fails if anyone edits it (integration is subprocess + `PI_*` env only).

## Install

```bash
openclaw skills install git:github.com/world327/cenhua
~/.openclaw/skills/cenhua/bin/cenhua setup
```

or plain CLI:

```bash
git clone https://github.com/world327/cenhua && cd cenhua
./bin/cenhua setup
cp your_files.pdf ~/.cenhua/vaults/default/inbox/ && cenhua add --inbox
cenhua find <keyword>
```

## Known limits (v0.1.0)

- Tree indexing and `ask` were validated with mocked/cost-guarded paths offline; a real-gateway end-to-end ingest on a large corpus is the next thing to exercise.
- No note/tag/graph layer and no `draft` command yet (P3/P4 of the plan).
- Index quality for scans equals OCR transcript quality — the tool says so in its answers.

MIT · bundled engine credit in LICENSE / `scripts/engine/ENGINE_SOURCE`.
```

---

## 三、ClawHub 提交材料

ClawHub 现状（已实测 clawhub.ai）：条目形状为 `<owner>/<slug>`，两条上架路径 —— ① 首页 **/import** 从 GitHub 导入；② CLI `npm i -g clawhub` → `clawhub login` → `clawhub skill publish ./cenhua --slug cenhua --version 0.1.0`。

**推荐路径**：先走 `/import`（指向 world327/cenhua，仓库根已有 SKILL.md，满足导入前提）；若要精确控制版本号/渠道，再用 CLI。

### 1) 列表条目字段

| 字段 | 填写 |
|---|---|
| Slug | `cenhua`（安装引用 `world327/cenhua`） |
| Display name | `CENHUA — 岑华` |
| Icon | 🌳（SKILL.md metadata 已声明 `emoji: 🌳`） |
| Version | `0.1.0` |
| Category | Productivity / Knowledge & Research |
| Requires | binary: `python3`；可选 env: `PI_BASE` `PI_KEY` `PI_MODEL` `PI_VISION_MODEL` `PI_EMBED_MODEL` |
| License | MIT |
| Tags | `second-brain` `rag` `knowledge-base` `local-first` `offline` `document-qa` `citations` `multi-vault` `vectorless` |

### 2) 短介绍（搜索结果/卡片，≤200 字符）

```
Personal second brain: drop files in an inbox, get answers with page-level citations traceable to your archived originals. Offline exact search is free; LLM only for meaning.
```

### 3) 完整详情（详情页正文，可直接粘贴）

```markdown
A local knowledge base your agent can actually be trusted with.

Drop any files (pdf/docx/pptx/xlsx/md/html/csv/images/scans) into a vault inbox. CENHUA normalizes them, builds a vectorless tree index per document, and keeps an exact per-page text layer on disk. Then:

• "does my corpus mention X, and on which page?" → `find` — offline, milliseconds, zero tokens, complete.
• "what does my contract say about penalties?" → `ask` — tree navigation, with a cost estimate printed before any spend.
• "quote me the clause" → `read -p 12` against the page, and `sources` to open the archived original.

The rule the whole tool is built on: grep for existence, LLM for meaning. Mixing them up is exactly how personal RAG starts hallucinating "your files don't mention that".

Security & consent posture
- API keys are never written to disk. Choosing the OpenClaw gateway stores only a reference; keys are resolved live from openclaw.json at call time.
- Two install-time questions are refused on your behalf by design (storage location, which LLM): the agent gets exit 6 / exit 5 and must relay both options to you.
- Works fully offline with no gateway for find/read/status/doctor/sources.

Requires: python3. Optional: any OpenAI-compatible endpoint (hosted or local Ollama/vLLM), plus optional vision and embeddings.
Tests: 34 offline unit tests + mock-endpoint suites, no API key needed.
MIT licensed; bundles an unmodified copy of the pageindex-rag engine (credited).
```

### 4) 审核自检清单（提交前）

- [x] 仓库根有 `SKILL.md`（ClawHub / OpenClaw 导入的硬前提）
- [x] `SKILL.md` frontmatter：`name` / `description`（含触发场景）/ `metadata.openclaw.requires.bins=["python3"]` + `primaryEnv`
- [x] `LICENSE` = MIT，含内嵌引擎出处声明；`scripts/engine/ENGINE_SOURCE` 记录来源与升级流程
- [x] 无密钥入库（已扫描：仅测试用占位 `sk-p1-secret`）
- [x] 安装即可运行：`bin/cenhua` 自定位，首启 `setup` 自举依赖
- [x] 文档双语：`SKILL.md`（英）+ `zh/SKILL.zh.md`
- [ ] 提交人需登录 ClawHub（GitHub OAuth）后执行 import / publish —— 这步要你本人点

### 5) 提交后收尾

- 在 README 顶部加一行 ClawHub 徽章与 `openclaw skills install clawhub:world327/cenhua`（以实际返回的引用为准），保留 git 安装方式作为无账号备选。
- 社区帖子/issue 首发时带上"两个必答题"的截图（exit 6 / exit 5 输出），这是最容易引发讨论的差异点。
