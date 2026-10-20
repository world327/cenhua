# CENHUA Service 契约登记制（Service Contract）

> 契约登记制载体（roadmap R2-R6 + R3-T8.3 + R4-F2）。
> **M1a 首个 commit 建档**，建档时直接采用升级后契约（citations 含 `snippet`、
> `verify_citation` 三参签名、`schema_version`——F2）。
> 新函数必须登记 dataclass 字段与 `schema_version` 才能进实现；已有 dataclass
> 只加字段不删改（读侧容忍旧版本）。

---

## 1. 契约原则

1. **登记制**：任何新 service 函数必须先在本文件登记（dataclass 字段 +
   `schema_version`），再进实现。杜绝"先实现后登记"窗口期（T8.3）。
2. **只加不删**：已有 dataclass 只加字段，不删改既有字段；读侧容忍旧版本
   （`schema_version` 字段，读侧按版本兼容）。
3. **单一事实源**：门禁（`cenhua bench`）与草稿校验（`cenhua draft --verify`）
   共用同一 `verify_citation` 原语（T4+F2）。
4. **service 纪律**：service 函数禁 `print`/`exit`（`test_70_service_no_print`
   全量生效）；CLI 只做薄包装（`test_71_cli_is_thin` 白名单内）。

---

## 2. 核心 dataclass 契约

### 2.1 `Citation`（引文）

```python
@dataclass(frozen=True)
class Citation:
    doc: str          # doc_id
    page: str         # 页码（字符串，兼容 "1" / "P1"）
    snippet: str      # ≤80 字锚文本，从命中页摘取（F2 新增，强制）
    schema_version: int = 2   # 升级后契约版本
```

- `snippet` 为 **M1a 升级后契约**（F2）：ask/query 响应 schema 强制带 snippet，
  无 snippet 的引文在门禁计为失败。
- 读侧容忍旧版本（无 `snippet` 字段的旧记录按 `snippet=""` 处理）。

### 2.2 `AskResult` / `QueryResult`

```python
@dataclass
class AskResult:
    answer: str
    citations: list[Citation]   # 每题挂多个引用点（F7 按条目计量）
    cost: CostEstimate | None
    schema_version: int = 2

@dataclass
class QueryResult:
    answer: str
    citations: list[Citation]
    cost: CostEstimate | None
    schema_version: int = 2
```

### 2.3 `CostEstimate`（成本估算）

```python
@dataclass
class CostEstimate:
    calls: int
    tokens_in: int
    tokens_out: int
    est_cost: float
    currency: str            # 各模型自身货币（F9）
    priced: bool             # False = 未配置单价，保守默认价
    note: str = ""           # 混合货币 / 未配置单价标注
```

---

## 3. 核心 service 函数

### 3.1 6 核心函数（M0 既有，登记）

| 函数 | 签名 | 说明 |
|---|---|---|
| `ingest` | `ingest(vault, path) -> IngestResult` | 摄取单文件；status=added 时自动 rebuild 文本层（pi_flatten，失败不翻转摄取结果），与 CLI add 语义一致（E2E 防回潮 test_core.test_52） |
| `find` | `find(vault, terms, ...) -> list[FindHit]` | 离线精确检索 |
| `query` | `query(vault, question, ...) -> QueryResult` | 语义检索（M2b 起 hint 两段式） |
| `related` | `related(vault, doc) -> list[Relation]` | 关联（M1b 迁入） |
| `ask` | `ask(vault, question, doc, ...) -> AskResult` | LLM 深读 |
| `stats` | `stats(vault) -> VaultStats` | 库统计 |

### 3.2 M1a 新增函数（本里程碑登记）

| 函数 | 签名 | 说明 |
|---|---|---|
| `verify_citation` | `verify_citation(doc, page, snippet) -> bool` | **三参签名**（F2）：校验 snippet 归一化后确实存在于该页文本层（NFKC 归一 + 去空白/全半角折叠后正则匹配） |
| `estimate_tokens` | `estimate_tokens(text) -> int` | 字符数/1.6（中英混合近似） |
| `estimate_cost` | `estimate_cost(model, tokens_in, tokens_out) -> CostEstimate` | token → 金额，按 pricing.json 各模型自身货币 |
| `match_price` | `match_price(model) -> Price | None` | OpenClaw 全名匹配规则（F9）：全名 → 裸 id → 保守默认价 |
| `ledger_append` | `ledger_append(vault, entry) -> None` | 写 `cost-ledger.jsonl`（**全量记账**，T5） |
| `cost_summary` | `cost_summary(vault, month=None) -> CostSummary` | 按命令分组汇总，摄取成本单列首位 |
| `calibrate` | `calibrate(vault, actual) -> None` | 预估校准闭环（偏差 >3x 告警） |
| `bench` | `bench(vault, corpus=False) -> BenchReport` | 跑 fixture（阻断级）/ 用户库（报告模式） |

### 3.3 M1b 新增模块与函数（编织层，登记制先行）

`cenhua_service/summaries.py`（规则先行层，零 LLM；`summarize` 不是用户命令，
不入 test_71 白名单，由 test_70 管辖——F10）：

```python
# <vault>/meta/summaries/<doc_id>.json —— schema_version=1，只加不删
{
  "schema_version": 1, "doc_id": str, "name": str, "ts": str,
  "status": "rule-only" | "refined",
  "tier": "internal-artifact",          # 正文不进引文；hint 消费自 v0.3.3（F3）
  "title": str, "first_paragraph": str,
  "entities": {"money":[], "date":[], "email":[], "id_number":[], "capitalized":[]},
  "keywords": [{"term": str, "tf": int}],   # tf 降序
  "headings": [str], "chars": int, "tokens_estimate": int,
  "refined": null | {"summary": str, "entities_llm": [str], "ts": str, "model": str}
}
```

| 函数 | 签名 | 说明 |
|---|---|---|
| `summaries.rule_summarize` | `(doc_id, name, text_layer) -> dict` | 纯函数规则总结（首段/正则实体/TF 关键词/标题） |
| `summaries.refresh` / `ensure_all` / `load_summary` / `save_summary` | 见源码 | 落盘与幂等（refined 不降级） |
| `refine.enqueue` / `pending` | `(vault, doc_id, reason)` / `(vault) -> [item]` | `meta/refine_queue.jsonl`；幂等；refined 自动出队 |
| `refine.estimate` | `(vault, doc_ids) -> dict` | 队列估价（tokens_estimate 汇总） |
| `refine.budget_check` | `(est, force=False) -> (ok, msg)` | 三闸之②③：`CENHUA_REFINE_BUDGET_CNY`（默认 0 拒绝）；USD 按上限汇率折算收紧 |
| `refine.refine_one` / `drain` / `refine_flow` | 见源码 | LLM 精化 + JSON 解析失败走规则首段 fallback；F1 豁免中途执法；失败留队列 |

`cenhua_service/relations.py`（四层降噪，纯 Python 统计零 LLM）：

```python
# <vault>/meta/relations.jsonl 每行 —— schema_version 隐含 v1
{"from": doc_id, "to": doc_id,
 "type": "cooccurrence"|"time_series"|"cite"|"similar",
 "weight": float,          # 人工 0.8；自动 ≤0.6
 "evidence": str,          # "共现 [A, B] 于 [doc P1, doc P9], nPMI=0.42"
 "source": "auto"|"manual", "ts": str, "tier": "internal-artifact"}
# <vault>/meta/link_bans.json：黑名单实体对（永久压制）
```

| 函数 | 签名 | 说明 |
|---|---|---|
| `relations.profile` | `(n_docs) -> dict` | 档位（small/standard）+ 参数（floor/枢纽比/平滑），`CENHUA_SMALL_CORPUS_N` 默认 200 |
| `relations.npmi` / `hub_entities` | 纯函数 | nPMI 公式与枢纽判定（含 `HUB_MIN_DF=3` 绝对地板，防极小库误判） |
| `relations.build` | `(vault) -> stats` | 全量重建（先 ensure_summaries）；Top-8 截断；人工边保留 |
| `relations.related` / `related_lines` | `(vault, doc_id[, name])` | 权重降序 + 证据；空结果明示；命中入精化队列 |
| `relations.manual_link` / `add_ban` | 见源码 | 人工边 0.8 / 黑名单永久压制 |

### 3.4 M2b 新增模块与函数（延展检索层，登记制先行）

`cenhua_service/tier.py`（三层 artifact + 引文穿透；tier 集中一处生成）：

```python
# 摄取台账 ingest_manifest.json 每行新增可选字段（读侧容忍缺失）：
#   "tier": "primary" | "derived-doc" | "internal-artifact"   # record_tier 补写
#   "derived_from": [doc_id, ...]                             # M3a digest 生成时写入
```

| 函数 | 签名 | 说明 |
|---|---|---|
| `tier.classify` | `(name, stored_as="") -> str` | 名称特征判 tier（`DERIVED_RE`） |
| `tier.doc_tier` | `(vault, doc_id) -> str` | 台账显式 tier > 名称判定 > 无行保守 primary |
| `tier.record_tier` | `(vault, doc_id) -> str` | 摄取成功后把 tier 补写台账（tmp+原子 rename；引擎不动） |
| `tier.derived_from` | `(vault, doc_id) -> [primary_id]` | 穿透链：优先台账字段，退关系层；防环 |
| `tier.penetration` | `(vault, doc_id, page) -> [{"doc","page"}]` | 引文位置 -> primary 位置；internal 恒 [] |
| `tier.sources_lines` | `(vault, kw="") -> list[str]` | `cenhua sources` 三层分组渲染（M3a 任务 11）：primary → derived-doc → internal-artifact 顺序，derived 组追加 derived_from 链；零 print |

`cenhua_service/prompt.py`（★ 两段式 hint-not-evidence，F3 自 v0.3.3 生效）：

| 函数 | 签名 | 说明 |
|---|---|---|
| `prompt.sanitize_hint` | `(text) -> (clean, n_dropped)` | 祈使/注入句逐句剔除（只许陈述；英文 .!? 后跟空白才切句，防 "128.5万" 切碎） |
| `prompt.hint_block` | `(vault, doc_ids) -> (lines, meta)` | 仅 refined；`[HINT tier=internal]` 标记；无 hint 明示不沉默 |
| `bench.run_injection` | `(qs) -> items[]` | M3a 任务 13 注入对抗门禁（离线零 LLM 阻断集）：sanitize_hint 后注入特征必须被剔除、事实句不误伤；fixture 对抗题 ≥1/3 `author:"human"` |
| `refine.roi_lines` | `(vault) -> list[str]` | hint 二段验证 ROI 账（M3a 任务 13）：refine 生产成本 vs query 验证轮成本（台账 cmd 分组），并入 `cenhua refine` 状态视图；零 print |
| `prompt.evidence_block` | `(segments) -> lines` | `[EVIDENCE tier=primary]`；调用方保证只传 primary |
| `prompt.build_prompt` | `(question, hint_lines, evidence_lines) -> str` | hint 前证据后；协议指令含 snippet 逐字强制 |
| `prompt.parse_answer` | `(text) -> dict\|None` | `{answer, citations[{doc,page,snippet}]}`；缺 snippet 留空串由 verify 计失败（F2） |

`cenhua_service/query.py`（四段编排，零 print；CLI 白名单 M2b=`query`）：

| 函数 | 签名 | 说明 |
|---|---|---|
| `query.terms_from_question` | `(q) -> [term]` | CJK ≤4 字整串 / 长串 2-gram + 拉丁词 + 停用词 |
| `query.find_hits` | `(vault, terms, include_derived=False)` | 默认 primary-only（§7.3 降级）；derived 带 derived_from |
| `query.fuse` | `(find_hits, seek_hits) -> ranked` | W_EXACT=1.0 / W_SEMANTIC=0.6，doc 去重降序 |
| `query.verify_citations` | `(vault, citations) -> [rec]` | verify_citation 原文校验 → 失败穿透重验 → 仍败降级标注 |
| `query.query_flow` | `(vault, q, ...) -> (rc, lines)` | 四段输出；无命中拒答 rc=1；预算闸拒绝 rc=4 |

`cenhua_service/cost.py` M2b 增量（dry-run 金额推广，全 LLM 命令共用）：
`estimate_prompt` / `estimate_docs` / `cost_gate`（`CENHUA_MAX_COST_CNY` env >
vault.yaml `max_cost` > 2.0；保守汇率折算只收紧）/ `dry_run_cost_lines`。

`cenhua_service/bench.py` M2b 增量：`run_refusal`（拒答门禁 ≥90% 进阻断集；
无网关 skipped 不阻断，F6.2；temperature=0+重试 1 次，F6.3）；
`_refusal_verdict`（无引文 + 拒答措辞 = refuse）。

### 3.5 M3a 新增模块与函数（任务通道 + digest，登记制先行）

`cenhua_service/jobs.py`（任务通道，**ADR-001 纯内存态/重启后标废**，
见 architecture.md §2.20）：

```python
@dataclass
class JobSpec:                 # 提交物：kind + 可执行体 + 元信息
    kind: str                  # "ask"|"query"|"digest"|"ingest"...
    run: Callable[[JobRuntime], Any]   # 后台线程执行；经 runtime 上报进度/cost
    meta: dict = field(default_factory=dict)
    schema_version: int = 1

@dataclass(frozen=True)
class JobHandle:               # 不透明句柄（跨形态传递用 to_dict/from_dict）
    job_id: str
    kind: str
    schema_version: int = 1

@dataclass
class JobStatus:               # job_status(handle, cursor) 返回值
    state: str                 # queued|running|done|failed|aborted
    progress: float            # 0.0–1.0（不可估算时长任务保持低水位）
    chunks: list[str]          # **增量**：仅 cursor 之后的新输出（M3b SSE 薄适配）
    cursor: int                # 已产出 chunk 总数（下轮 cursor 传入值）
    cost: dict                 # {"calls":int,"cost":float,"currency":str} 累计
    error: str = ""            # failed 时的用户可读错误
    reason: str = ""           # aborted 原因："stale"=进程重启后旧 handle（ADR-001）
    schema_version: int = 1
```

| 函数 | 签名 | 说明 |
|---|---|---|
| `jobs.submit` | `(spec: JobSpec) -> JobHandle` | 内存 job 表登记 + daemon 线程执行，立即返回句柄 |
| `jobs.run_cli` | `(handle, printer, poll=0.2, timeout=None, heartbeat=10.0) -> JobStatus` | CLI 轮询打印器（M3a 任务 4）：增量 chunks 逐行 printer + 进度变化行 + 无进展心跳行；终态/超时返回。service 层禁 print，printer 由 CLI 注入（`L.say`）；M3b SSE 是同协议另一适配 |
| `jobs.job_status` | `(handle, cursor=0) -> JobStatus` | 增量协议；**未知 handle（含进程重启后）恒返回 `aborted/stale` 终态，不抛错**（ADR-001） |
| `jobs.job_result` | `(handle) -> Any` | done → AskResult/QueryResult/DigestResult；未完成/失败/stale → 抛 `JobNotDone`/`JobFailed`/`JobStale` |
| `jobs.wait` | `(handle, poll=0.2, timeout=None) -> JobStatus` | CLI 轮询便捷器（CLI 打印 chunks 走同一协议） |
| `JobRuntime` | `progress(f)` / `emit(chunk)` / `add_cost(calls=,cost=,currency=)` | 执行体回调面（线程安全） |

`cenhua_service/digest.py`（digest 编排，零 print；CLI 白名单 M3a=`digest`）：

```python
@dataclass
class DigestResult:
    path: str                  # <vault>/works/digests/<主题>_V{N}_<日期>.md
    doc_id: str                # 回流入库后的 doc_id（tier=derived-doc）
    derived_from: list[str]    # 本期引用 primary doc_ids
    citations: list[Citation]  # 四节全文引文（含 snippet）
    cost: CostEstimate | None
    schema_version: int = 1
```

| 函数 | 签名 | 说明 |
|---|---|---|
| `digest.window` | `(vault, weekly/monthly/quarterly/since) -> (start, end, doc_ids)` | 时间窗内 primary 文档（按摄取台账 ts） |
| `digest.estimate` | `(vault, doc_ids) -> dict` | dry-run 估价（estimate_docs 复用） |
| `digest.budget_check` | `(vault, est, force=False, max_cost=None) -> (ok, msg)` | 三闸②③：`CENHUA_LONGJOB_MAX_COST_CNY`（默认 5.0）；all-or-nothing 拒启不中途停 |
| `digest.compose` | `(vault, doc_ids, label="weekly", runtime=None, start=None, force=False, max_cost=None) -> (DigestResult, lines)` | 四节文章生成（M3a 任务 7 已落地）：LLM 主路径 + 规则兜底（铁律 fallback）；引文全量 verify_citations 校验；文章落 `works/digests/洞察_<窗口>_V{N}_<日期>.md`；runtime 为任务通道进度回报（可选）；豁免中途执法 F1 |
| `digest.ingest_back` | `(vault, result) -> doc_id` | 回流闭环（M3a 任务 10 已落地）：复制 works/digests 文章 → inbox → core.ingest → 台账显式改写 tier=derived-doc + derived_from（原子写）；永不抛，失败返回 "" |
| `digest.watch_hint` | `(vault) -> str` | F10 watch 提示文案（N≥20 默认，只提示不触发） |

`cenhua_service/cost.py` M3a 增量：`longjob_max_cost_cny(vault=None)`——
`CENHUA_LONGJOB_MAX_COST_CNY` env > vault.yaml `longjob_max_cost` > 5.0。

`cenhua_service/core.py`（六核心函数 service 化，M3a 任务 2；§3.1 契约落地）：

```python
@dataclass
class IngestResult:
    status: str                # "added"|"dupe"|"failed"
    doc_id: str = ""
    name: str = ""
    error: str = ""
    schema_version: int = 1

@dataclass
class FindHit:
    doc: str; name: str; page: str; line: str; term: str
    schema_version: int = 1

@dataclass
class Relation:
    from_doc: str; to_doc: str; type: str; weight: float
    evidence: str = ""; source: str = "auto"
    schema_version: int = 1

@dataclass
class VaultStats:
    name: str; title: str; docs: int
    text_have: int; text_missing: int; text_empty: int
    inbox_pending: int; failed_count: int
    llm_calls_total: int; gateway_ready: bool; model: str
    schema_version: int = 1
```

`AskResult`/`QueryResult` 只加字段（读侧容忍）：`rc: int = 0`、
`lines: list = []`、`error: str = ""`——CLI/任务通道按 rc 分发，
`lines` 为渲染行（`answer` 保留四段全文本）。

| 函数 | 签名 | 说明 |
|---|---|---|
| `core.ingest` | `(vault, path) -> IngestResult` | 委托 `m_ingest.ingest_one(quiet=True)`（兼容包装：OCR/邮件子进程链留 CLI 侧）；sha1 前置解析 doc_id |
| `core.find` | `(vault, terms, docs_selector=None, max_per_doc=15, regex=False, ignore_case=False) -> list[FindHit]` | 全 tier 原样扫文本层（find=存在性 grep，不做 tier 过滤；tier 降级是 query 的职责） |
| `core.query` | `(vault, question, include_derived=False, dry=False, force=False, top=3) -> QueryResult` | 委托 `query.query_flow`；rc/lines 结构化返回 |
| `core.related` | `(vault, doc) -> list[Relation]` | 委托 `relations.related`，dict → dataclass |
| `core.ask_estimate` | `(vault, question, doc=None, all_docs=False, limit=10) -> AskResult` | 深读前置段（M3a 任务 4）：scope 解析 + estimate_docs + `[cost]` 渲染行（含 dry_run_cost_lines），**零副作用**；rc=2 参数/范围错；成功 `cost` 含 `calls=n`。CLI 预取 n 决定是否交互确认；`core.ask` 内部复用（单一事实源） |
| `core.ask` | `(vault, question, doc=None, all_docs=False, limit=10, dry_run=False, force=False, workers=None, confirm=None) -> AskResult` | service 原生实现：复用 ask_estimate→dry_run 短路→cost_gate→ceiling→chat_ready→confirm(n)->bool 回调（CLI 注入交互确认；拒绝/异常→rc=1 `aborted (nothing spent)`）→run_engine(capture)→enqueue（失败隔离）。rc 语义：0 成功；1 用户放弃；2 参数错；3 网关未配置；4 预算/上限拒绝。台账由 CLI 侧 m_ask.record 统一记；引擎输出非结构化，citations=[] 诚实留空 |
| `core.stats` | `(vault) -> VaultStats` | 纯读取统计；`core.stats_lines(vault, st=None) -> list[str]` 供 CLI 渲染 |
| `digest.digest_flow` | `(vault, weekly=False, monthly=False, quarterly=False, since=None, dry_run=False, force=False, max_cost=None) -> DigestResult` | digest 主编排：窗口解析→圈选→估价→longjob 三闸→compose 四节生成；rc=0 成功/2 参数错/3 网关未配置/4 预算闸拒绝；compose 成功后自动回流（ingest_back，best-effort 不改 rc）；CLI 经 core.channel_job 任务通道执行。零 print |
| `digest.parse_cli` | `(rest) -> dict` | digest CLI 参数解析（下沉 service 保 CLI 薄）：三周期/`--since`/`--dry-run`/`--force`/`--max-cost N` -> digest_flow kwargs |
| `digest.parse_window` | `(weekly, monthly, quarterly, since) -> (start_date, label)` | 触发参数解析：三周期互斥、`--since` 与三周期互斥且须 YYYY-MM-DD；错误返回 `(None, 文案)` |
| `digest.docs_since_last_digest` | `(vault) -> int` | 自上次洞察（works/digests/ 最新 mtime）以来摄取量；watch 提示（F10）计数口径 |
| `digest.hint_threshold` | `(vault) -> int` | 提示阈值 N：`CENHUA_DIGEST_HINT_DOCS` > vault.yaml `digest_hint_docs` > 20 |
| `core.channel_job` | `(kind, fn, *args, **kwargs) -> jobs.JobSpec` | 长任务→任务通道统一适配（M3a 任务 4）：fn 返回带 `lines`/`cost` 的 dataclass（AskResult/QueryResult/DigestResult），body 逐行 emit + cost 映射 `JobRuntime.add_cost`（cost 键 docs/calls/est_cost/currency） |

---

### 3.6 M3b 新增模块与函数（本地 Web UI + 局域网 API，登记制先行）

**放位与约束**：适配层住 `cenhua_service/webui/`（可导入、可单测）；
`scripts/m_webui.py` 只做 argparse + uvicorn.run（归入 CLI 入口白名单，
与 m_cenhua 同级，test_71 口径）。依赖 `fastapi / jinja2 / uvicorn`
**延迟导入**（只在 `create_app`/`serve` 内 import），core 层零污染；
requirements.txt 增补 `fastapi>=0.110 jinja2>=3.1 uvicorn>=0.29`（F8：
Nginx 仅可选部署附件，不进依赖清单）。

`cenhua_service/webui/security.py`：

| 函数 | 签名 | 说明 |
|---|---|---|
| `check_token` | `(vault, provided: str) -> bool` | **fail-closed**：`CENHUA_API_TOKEN` env > vault.yaml `api_token`；**未配置 token = 拒绝一切**（空 token 也拒）；常数时间比较（`hmac.compare_digest`）；T8.2 无租户/用户映射残肢 |
| `RateLimiter` | `(max_calls: int, window_s: float)`；`allow(key) -> bool` | 滑动窗口限流（与 OCR 服务同款模式）；超限 → API 429 / 页面 429 文本 |

`cenhua_service/webui/api.py` — `build_router(vault, deps) -> fastapi.APIRouter`：

- 端点挂 service 函数零业务逻辑：`POST /api/v1/ingest`（multipart 落 inbox →
  `core.ingest`）、`GET /api/v1/documents`、`POST /api/v1/find`、
  `POST /api/v1/query`、`POST /api/v1/ask`、`POST /api/v1/digest`、
  `GET /api/v1/relations?doc=`（长任务走 `jobs.submit` 返回 handle）。
- dataclass 序列化：`dataclasses.asdict` 透传；所有响应顶层带
  `schema_version`；错误响应 `{"error": 用户可读, "detail": ...}` 统一形态。
- `GET /api/v1/jobs/{handle}` SSE：`jobs.job_status(handle, cursor)` 增量转
  `event: chunk/progress/done/failed`，空闲 10s 发 `event: heartbeat` 注释行；
  断线按 handle 重订阅（cursor 从 0 幂等重放），stale 返回终态
  `aborted/stale`（ADR-001）。
- 版本脚注：`GET /api/v1/graph`、`POST /api/v1/draft` v0.5 恒 404 +
  `{"message": "v0.6 起，随 M4 交付"}`（R2-R10/R3-T8.1/R4-F4）。

`cenhua_service/webui/pages.py` — Jinja2+HTMX 四页（摄取/检索/编织/洞察浏览）：
只调用 `core.*`/`tier.*`/`digest.*`/`docmeta.*` 既有函数与 `*_lines` 渲染行，
零业务逻辑；创造页**只读 digest**（F4，草稿编辑移 M4）。
页面鉴权：与 API 同一 `check_token`（fail-closed），通过后落 httpOnly cookie
`cenhua_token`；未鉴权 → 极简 token 输入页，零会话状态存服务端。
EventSource 无法携带自定义 header，故 API 鉴权额外接受**同源 cookie**
`cenhua_token` 回退（页面登录时落；纯 header 客户端不受影响）。

`cenhua_service/docmeta.py`（编织页任务 4 的"标签/笔记"最小 service 面）：

| 函数 | 签名 | 说明 |
|---|---|---|
| `load` | `(vault) -> dict[doc_id, {"tags": [...], "note": str}]` | 读 `meta/docmeta.json`，缺失/损坏返回 `{}`（降级不抛） |
| `get` | `(vault, doc_id) -> DocMeta{doc_id, tags, note}` | 单文档视图，未标注返回空值 |
| `update` | `(vault, doc_id, tags=None, note=None) -> DocMeta` | None=不改该字段；tags 去空去重保序；**tmp+rename 原子写**（AGENTS §1） |

API 面：`GET /api/v1/docmeta?doc=`、`POST /api/v1/docmeta`（body
`{doc, tags?, note?}`）。CLI 面 M3b 不做（Web 专属编辑，避免双入口漂移）。

`cenhua_service/webui/app.py`：

| 函数 | 签名 | 说明 |
|---|---|---|
| `create_app` | `(vault, token=None, rate=None) -> FastAPI` | 组装：rid 中间件（uuid4 短码，响应头 `X-Cenhua-Rid` + `vault.log("web", ...)` 结构化行）→ token/限流依赖 → api router + pages；`timeout_keep_alive` 走 uvicorn 配置（任务 11） |
| `serve` | `(vault, host, port) -> None` | uvicorn.run 薄调用；host/port/token 全部 config 驱动（`CENHUA_WEB_HOST/PORT` env > vault.yaml `web_host/web_port` > 默认 `127.0.0.1:8765`），零硬编码 |

**日志**：Web 层独立流 `logs/web-YYYYMM.log`（复用 `Vault.log`），行含
rid/方法/路径/状态/耗时——结构化 + 全链路追踪，不外泄 token。

## 4. `schema_version` 演进记录

| 版本 | 变更 |
|---|---|
| 1 | M0 初版（无 snippet） |
| **2** | **M1a 升级后契约**（F2）：`Citation` 加 `snippet` 字段；`verify_citation` 三参签名；`CostEstimate` 加 `currency`/`priced`/`note` |

---

## 5. 门禁与草稿共用校验器

- `cenhua bench`（M1a）与 `cenhua draft --verify`（M4）共用 `verify_citation`
  原语（T4+F2），单一事实源。
- 引文按条目计量（F7）：每题挂多个引用点，全量条目 ≥20；阈值按条目占比 ≥95%。
- 存在性召回 100% 零容忍（铁律"沉默不是证据"的直接度量）。

---

*建档：M1a 首个 commit · 2026-10-13 · 后续里程碑增量登记于此。*
