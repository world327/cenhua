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
| `ingest` | `ingest(vault, path) -> IngestResult` | 摄取单文件 |
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

---

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
