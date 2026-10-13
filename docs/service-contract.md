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
