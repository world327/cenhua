# CENHUA 开发计划（Dev Plan）

> 基于 [roadmap.md](roadmap.md) R4 修订版制定，是各里程碑的**开发蓝图与质量把关书**。
> 本文回答两个问题：① 每个版本"做什么、做到什么程度才算完"；② "怎么保证每个
> 版本的质量"——通过 Definition of Done、门禁机制、任务分解、风险前置四套机制。
>
> 单维护人项目，时间估算以**任务粒度**（每任务 0.5-2 天）+ **建议节奏**（每周 3-5
> 个有效工作日）表达，不写硬性日期；并行支线（M2a）可与主线独立推进。

---

## 0. 总览

### 0.1 里程碑依赖图（复制自 roadmap §8）

```
M0 v0.1 CLI+技能(已成)
   │
   ├──────────────────┐
   ▼                  ▼
   M1a v0.2.0        M2a v0.3.0 网页收录(独立支线, 不含 §4.4)
   成本+质量基建       │     ★ 只并行不阻塞主线
   (pricing+bench+     │
    ledger+verify+     │
    service-contract)  │
   │                   │
   ▼                   │
   M1b v0.2.1         │
   编织+§4.4+小库模式  │
   (refine hint 待     │
    M2b 生效)          │
   │                   │
   ▼                   │
   M2b v0.3.1         │
   query+hint 两段式   │
   +拒答门禁+推广      │
   │                   │
   ▼                   │
   M3a v0.4           │
   service完成+digest  │
   +任务通道+hint硬化  │
   ├──────────────────┐
   ▼                  ▼
   M3b v0.5          M4 v0.6 图谱+draft+Web草稿编辑
   Web UI(洞察浏览)   (不依赖 M3b；Web 力导向图
   +SSE 薄适配         与草稿编辑需 M3b)
```

### 0.2 关键路径

`M0 → M1a → M1b → M2b → M3a → M3b/M4`（主线七节点，M2a 独立支线并行）

**M3a 是最大风险节点**：service 层完成 + digest + 任务通道 + hint 注入对抗硬化 +
三层 artifact 闭环 + 任务通道持久化边界裁决（R2/R3/R4 连续三轮预告，**M3a 开工前
必须拍板，不得再顺延**）——五事同里程碑，是整个项目工程难度最高点。

### 0.3 版本节奏建议

| 节奏项 | 建议 | 理由 |
|---|---|---|
| 每周有效工作日 | 3-5 天 | 单维护人，留缓冲应对评审/调试/文档 |
| 每里程碑缓冲 | 20% | R3/R4 评审揭示"修复自身引入次生伤"频繁，缓冲吸收返工 |
| 并行支线 | M2a 与 M1 主线并行 | 互不阻塞，可交错推进；建议 M1a 落地后启动 M2a |
| 评审触发 | 每里程碑完工后 + roadmap 修订 | 评审是质量护栏，不可跳过 |
| 发版流水线 | 全量 fixture（含拒答，需 API key） | 无 key 环境跳过拒答集并在 release notes 标注 |

### 0.4 不做的事（避免范围蔓延）

- 不承诺企业租户、行级过滤、用户映射（T8.2 已清除残肢）
- 不做公网搜索页（review Q9 已删）
- 不做 SPA 升级（避免过早复杂度）
- 不做断点续跑（M4 前，长任务幂等由 `rid` 保证可审计）
- 不做 neo4j（v0.6 用邻接表 JSON，后续评估）
- 不做任务通道持久化的"再顺延"（M3a 开工前必拍板）

---

## 1. 质量保障体系（贯穿所有版本）

### 1.1 测试金字塔

```
            ┌───────────────────┐
            │  端到端 / bench   │  ← fixture 冻结产物，发版前必跑
            └───────────────────┘
        ┌───────────────────────┐
        │  集成测试 / smoke     │  ← 跨模块流程，每里程碑增量
        └───────────────────────┘
    ┌───────────────────────────────┐
    │      单元测试                  │  ← 每函数/每模块，TDD 优先
    └───────────────────────────────┘
```

- **单元测试**：每新增 service 函数 / 命令 / 工具函数配套单测；目标覆盖率 ≥70%
  （不追求 100%，优先覆盖成本/引文/降级路径）
- **集成测试**：每里程碑增量编写跨模块 smoke（如 M1a 的 `ingest → flatten →
  find → verify_citation` 闭环）
- **端到端 / bench**：fixture 冻结产物，发版前必跑；存在性 100% + 引文条目 ≥95%
  + 拒答 ≥90%（M2b 起）

### 1.2 门禁机制三层（roadmap §8 标准 7 + R4-F6）

| 层级 | 触发时机 | 范围 | 阻断行为 |
|---|---|---|---|
| **CI 层** | 每次 push / PR | `tests/run_tests.sh`：单元 + 集成 + fixture 存在性+溯源题（离线） | 失败阻断合并 |
| **发版流水线** | 发版前 | 全量 fixture（含拒答，需 API key）；无 key 跳过拒答集并在 release notes 标注 | 失败阻断发版 |
| **bench 回归** | 发版前 | 存在性召回 100% + 引文条目 ≥95% + 拒答 ≥90%（M2b 起） | 回归阻断发版 |

**拒答非确定性治理**（F6.3）：temperature=0 + 失败重试 1 次；同一题连续 2 个版本
flaky → 自动转人工仲裁（进 `meta/qa/flaky.jsonl`），不连续阻断发版。

### 1.3 Definition of Done（DoD）模板

每个里程碑完工必须满足以下**全部**条件才算 Done：

- [ ] **交付物清单**：roadmap §8 该里程碑"交付物"列表逐项落地，无遗漏
- [ ] **端到端**：完成该里程碑"用户场景"全流程，产物可读回比对
- [ ] **测试**：新增功能配套单测；`bash tests/run_tests.sh` 全绿；
  `test_61_engine_is_untouched` 守护引擎纯净；`test_70_service_no_print` +
  `test_71_cli_is_thin`（白名单内）防回潮
- [ ] **门禁**：`cenhua bench`（fixture 模式）通过；指标不低于上一版（存在性 100%、
  引文条目 ≥95%、M2b 起拒答 ≥90%）
- [ ] **文档同步**：user-guide.md 同步更新；新坑回写 pitfalls.md；service 契约变更
  回写 service-contract.md（M1a 起）；architecture.md 同步（M1a 起 service 层、
  M3a 起任务通道、M2b 起 hint 两段式 prompt）
- [ ] **形态**：里程碑标注的形态实际可独立运行
- [ ] **成本护栏**：新增 LLM 端点都有 `--dry-run`（含金额）与
  `CENHUA_MAX_LLM_CALLS`/`CENHUA_MAX_COST_CNY` 并联；长任务（digest/draft）+
  批量任务（refine --drain）走 all-or-nothing + 豁免中途执法（F1）
- [ ] **配置项**：新增 env / vault.yaml 字段落 §14 配置表；删除项做兼容旧名一个版本
  （deprecation warning）
- [ ] **评审**：跑一轮自评对照 roadmap 该里程碑验收通用标准 8 项 + 本里程碑交付物
  清单；自评通过后触发下一轮 roadmap 评审（可选）

### 1.4 代码审查清单（单维护人项目自审）

每次 commit 前自审：
- [ ] **引擎纯净**：`scripts/engine/` 字节级未变（`test_61` 绿）
- [ ] **service 纪律**：service 函数禁 print/exit（`test_70` 绿）；CLI 函数体 ≤10 行
  （`test_71` 白名单内绿）
- [ ] **凭证安全**：未硬编码 key/token/secret；vault.yaml 拒绝存储
- [ ] **配置驱动**：变数进 `vault.yaml`/`config.json`，未硬编码
- [ ] **外部输入降级**：网页抓取、LLM 调用、OCR 有 try/except + 默认值
- [ ] **日志脱敏**：token/绝对路径/PI_KEY 前缀脱敏（F8 去 open_id 概念）
- [ ] **引文带 snippet**：ask/query 响应 citations 强制带 snippet（F2，M2b 起）
- [ ] **三层 artifact**：tier 字段正确标记（primary/derived-doc/internal-artifact）；
  internal-artifact 正文不进引文（M2b 起 hint 可进 prompt）
- [ ] **成本记账**：所有 LLM 调用（含 add 树索引、OCR 视觉兜底）写 cost-ledger（T5）
- [ ] **长任务豁免**：digest/draft/refine --drain 不被 `CENHUA_MAX_COST_CNY`/
  `CENHUA_MAX_LLM_CALLS` 中途腰斩（F1）

### 1.5 文档同步规约

- **roadmap.md**：里程碑完工后归档对应 review 文档，决策沉淀进 §12 ADR
- **design.md**：原则变更回写（原则 10 全量记账仅免闸、原则 11 hint-not-evidence
  完整规则）
- **architecture.md**：M1a 起补 service 层架构；M2b 起补 hint 两段式 prompt 架构；
  M3a 起补任务通道架构
- **user-guide.md**：M0 快照已存；M3b 起补 Web UI 与 API 手册；Nginx 仅作为可选
  部署附件在此提一句（F8）
- **pitfalls.md**：新坑回写；QA fixture 语料从 pitfalls 反推
- **service-contract.md**：M1a 首 commit 建档；建档时直接采用升级后契约（citations
  含 snippet、verify_citation 三参签名、schema_version——F2）；每里程碑增量登记
- **dev-plan.md**（本文）：每里程碑完工后更新状态标记（✅/🚧/📋）

### 1.6 评审节奏

- **每轮评审触发**：里程碑完工 + 自评 DoD 全绿后
- **评审人**：用户（主人）+ 评审 agent（飞鸡）
- **裁决执行**：评审文档生成后按主人裁决修订 roadmap，再开工下一里程碑
- **四轮已落**：R1（11 项）/ R2（10 项）/ R3（9 项）/ R4（11 项）评审已全部吸收

---

## 2. M1a · v0.2.0 · 成本与质量基础设施

### 2.1 目标与范围

**一句话**：把成本与质量的"度量衡"先立起来——pricing/换算/ledger 全量记账 +
`cenhua cost` 汇总 + `cenhua bench` + fixture 冻结产物 + `verify_citation` 三参
原语 + service-contract 建档。**纯基础设施，不碰编织逻辑，可先行。**

### 2.2 前置依赖

- M0 v0.1.0 ✅ 已发布

### 2.3 任务分解

| # | 任务 | 粒度 | 依赖 | 验收 |
|---|---|---|---|---|
| 1 | `docs/service-contract.md` 建档（**首 commit**）：6 核心函数 dataclass 签名 + `schema_version`；**直接采用升级后契约**（citations 含 snippet、verify_citation 三参签名——F2） | 1 天 | — | 契约文档评审通过；新函数登记制确立 |
| 2 | `pricing.json` schema 设计：`{model: {in, out, currency}}`（F9 加 currency）；用当前 OpenClaw 配置里的模型实价填初版；未知模型保守默认价 + "未配置单价"标注 | 0.5 天 | 1 | schema 定稿；初版 pricing.json 落库 |
| 3 | OpenClaw 网关全名匹配规则实现：先按 `openclaw:provider/model` 全名精确匹配 → 再按裸 model id 匹配 → 未命中保守默认价 + 输出标注（F9） | 0.5 天 | 2 | 三级匹配单测全绿；混合货币显示 `¥0.35 + $0.02` 加汇率提示脚注 |
| 4 | token 估算函数：字符数/1.6（中英混合近似）+ 上次真实调用的校准系数 | 0.5 天 | 2 | 单测覆盖中英混合/纯中/纯英；数量级正确 |
| 5 | 金额换算函数：token → 金额，按 pricing.json 各模型自身货币显示；混合货币不强行折算 | 0.5 天 | 2,4 | 单测覆盖单货币/混合货币；汇率提示脚注正确 |
| 6 | `cost-ledger.jsonl` 写入逻辑：**全量记账**（含 add 树索引、OCR 视觉兜底——T5）；字段 `{ts, cmd, doc, calls, tokens_in, tokens_out, est_cost, currency}` | 1 天 | 5 | add/ask/OCR 三路调用均落 ledger；T5 全量记账单测绿 |
| 7 | `cenhua cost [--month]` 汇总命令：按命令分组（ingest/ask/query/refine/digest…），**摄取成本单列首位** | 1 天 | 6 | 月报输出格式正确；摄取成本首位；空 ledger 优雅降级 |
| 8 | 预估校准闭环：预估偏差 >3x 告警，防单价表过期 | 0.5 天 | 6 | 校准单测；告警日志可见 |
| 9 | `verify_citation(doc, page, snippet) -> bool` 原语实现：校验 snippet 归一化后确实存在于该页文本层（NFKC 归一 + 去空白/全半角折叠后正则匹配——F2） | 1 天 | 1 | 三参签名；snippet 错位/归一化/全半角折叠单测全绿 |
| 10 | fixture 冻结产物制作：合成 ~30 份文档语料 → 建索引 → 冻结打包（tree index + 文本层 + 30 题 QA：存在性 15 + 溯源 10 + 拒答 5——F6.1）；源文件一并打包供审计；bench 不重建索引 | 2 天 | 9 | fixture 离线可跑（存在性+溯源子集零 LLM 零网络）；30 题覆盖三类 |
| 11 | `cenhua bench` 命令：默认跑 fixture（阻断级）；`--corpus` 跑用户库 QA（报告模式，带 `corpus_hash` 过期标记——T2） | 1 天 | 10 | fixture 模式输出存在性召回 100% + 引文条目 ≥95%；用户库模式只打印不阻断 |
| 12 | 门禁分层实现：CI 层（`tests/run_tests.sh` 跑 fixture 存在性+溯源题，离线阻断）；发版流水线（全量含拒答需 API key，无 key 跳过并标注——F6.2） | 1 天 | 11 | CI 离线阻断生效；发版流水线拒答集无 key 时正确跳过 + release notes 标注 |
| 13 | 拒答非确定性治理：temperature=0 + 失败重试 1 次；连续 2 版 flaky 转人工仲裁（`meta/qa/flaky.jsonl`——F6.3） | 0.5 天 | 11 | flaky 检测单测；仲裁文件正确写入 |
| 14 | 引文按条目计量实现：每题挂多个引用点，全量条目 ≥20；阈值按条目占比 ≥95%（F7）；存在性 100% 零容忍；失败输出逐条 diff 清单 | 0.5 天 | 11 | 条目计量单测；diff 清单格式可归因 |
| 15 | service 层搬迁基础：`cenhua_service/__init__.py` 建立；M1a 新增函数（pricing/换算/ledger/cost/bench/verify_citation）登记入 service；契约登记制建档持续维护 | 1 天 | 1-9 | service 模块独立；契约文档与本里程碑实现一致 |
| 16 | 防回潮测试：`test_70_service_no_print`（service 全量生效）；`test_71_cli_is_thin` 白名单首批（M1a: `cost`/`bench`——`summarize` 移出由 test_70 管辖，F10） | 1 天 | 15 | test_70/71 全绿；白名单仅含用户命令 |
| 17 | 单测套件增量：pricing/换算/ledger/cost/bench/verify_citation 全覆盖；`bash tests/run_tests.sh` 全绿 | 1.5 天 | 2-14 | 覆盖率 ≥70%；run_tests.sh 全绿 |
| 18 | 文档同步：user-guide.md 补 `cenhua cost`/`cenhua bench` 手册；pitfalls.md 回写新坑；architecture.md 补 service 层架构；design.md 原则 10 增补"全量记账仅免闸" | 1 天 | 全 | 四份文档同步更新 |

**M1a 任务粒度合计**：约 16.5 任务日；建议节奏 4-5 周完工（含 20% 缓冲）。

### 2.4 Definition of Done

- [ ] §2.3 任务 1-18 全绿
- [ ] `cenhua cost` 月报按命令分组显示，摄取成本单列首位（T5）
- [ ] `cenhua bench` 跑 fixture：存在性召回 100% + 引文条目 ≥95%
- [ ] `verify_citation(doc, page, snippet)` 三参原语落库，snippet 归一化匹配正确
- [ ] `docs/service-contract.md` 首 commit 建档，直接采用升级后契约（citations 含 snippet、verify_citation 三参签名、schema_version）
- [ ] fixture 冻结产物随包分发，离线可跑（存在性+溯源子集零 LLM 零网络）
- [ ] 门禁分层：CI 离线阻断 / 发版流水线全量含拒答需 key
- [ ] `test_70_service_no_print` 全量生效；`test_71_cli_is_thin` 白名单首批（`cost`/`bench`）
- [ ] `pricing.json` schema 含 `currency` 字段；OpenClaw 全名匹配规则落地
- [ ] §1.3 DoD 模板全部勾选

### 2.5 风险点与对策

| 风险 | 对策 |
|---|---|
| fixture 冻结产物与 pageindex 引擎升级断裂（R4 §4 预告） | fixture 绑定 `engine_version`；提供 `bench --rebuild`（显式重建，烧 LLM 需确认） |
| pricing.json 单价过期 | 预估校准闭环（偏差 >3x 告警）；用户可覆盖 |
| OpenClaw 全名匹配规则与实际网关返回不符 | M1a 开工前用 `/models` 探测实网关返回格式；匹配规则单测覆盖三种命中路径 |
| verify_citation snippet 摘取的诚实性（R4 §4 预告） | verify 只证"该句在该页"不证"该句支撑该结论"；引文准确率诚实上限是逐字可溯率，文档措辞不得升格为"语义正确率" |
| fixture 30 题冷启动出题权（R4 §4 预告注入对抗题） | 至少 1/3 对抗题人工撰写，防出题方与攻击方同源盲区 |

---

## 3. M1b · v0.2.1 · 编织

### 3.1 目标与范围

**一句话**：让孤立文档变关联网络——deferred 总结（规则先行 + 按需精化 + 预算硬闸）+
四层降噪关联（含小库模式自动降档）+ §4.4 离线增强（唯一归属，F5）+ related/refine/
cost/bench 入 service。

### 3.2 前置依赖

- M1a v0.2.0 ✅（仅换算函数与 verify_citation 两处复用）
- M2a 与 M1 支线并行，互不阻塞

### 3.3 任务分解

| # | 任务 | 粒度 | 依赖 | 验收 |
|---|---|---|---|---|
| 1 | §4.4 离线增强（**唯一归属**——F5）：邮件 `eml`/`msg` 摄取（带附件展开）；watch 强化（flush+fsync+size 稳定后再摄取、`create_time` 排序治乱序） | 1.5 天 | M1a | eml/msg 单测；watch 文件可见性防护单测 |
| 2 | §5.3 规则先行层：首段截取 + 正则实体粗提（金额/日期/邮箱/证件号/大写实体）+ TF 关键词 + 标题结构；落 `<vault>/meta/summaries/<doc>.json`（`status=rule-only`, `tier=internal-artifact`） | 1.5 天 | M1a | summaries JSON 格式正确；tier=internal-artifact；规则层零 LLM |
| 3 | §5.3 按需精化队列：`<vault>/meta/refine_queue.jsonl` 持久化；文档首次被 query/related 命中入队；`cenhua refine --all --dry-run` 手动批量估价；`cenhua refine --drain` 消费 | 1.5 天 | 2 | 队列入队/消费单测；`refine --drain` 批量任务豁免中途执法（F1） |
| 4 | §5.3 预算硬闸：`CENHUA_REFINE_BUDGET_CNY`（默认 0）；三闸执法顺序：① dry-run → ② refine 预算 → ③ `--force` 放行；超预算拒启 | 1 天 | 3, M1a | 三闸顺序单测；超预算正确拒启 |
| 5 | §5.3 LLM 精化执行：跑 LLM 总结/NER；更新 `summaries/<doc>.json`（`status=refined`）；写 cost-ledger（全量记账） | 1 天 | 3, M1a | 精化后 summaries 状态正确；ledger 写入 |
| 6 | §5.4 关联存储：`<vault>/meta/relations.jsonl`，每行 `{from, to, type, weight, evidence, source}`（`tier=internal-artifact`） | 0.5 天 | — | relations 格式正确；tier 标记 |
| 7 | §5.4 IDF 过滤层：实体 IDF = `log(N/df)`；枢纽判定（标准档 `df>N×0.30`，小库档 `df>N×0.50`——T6）；枢纽实体不产生共现边 | 1 天 | 2 | IDF 单测；小库模式自动降档触发正确 |
| 8 | §5.4 nPMI 显著性：`nPMI(A,B) = log(N·|D_A∩D_B| / (|D_A|·|D_B|)) / log(N)`（小库档 +Laplace 平滑）；`nPMI ≤ 0` 不建边 | 1 天 | 7 | nPMI 单测；Laplace 平滑生效 |
| 9 | §5.4 共现地板：标准档 `|D_A∩D_B| ≥ 2`，小库档 `≥ 1`；每文档对外关联截断 Top-8 | 0.5 天 | 8 | 共现地板单测；Top-8 截断 |
| 10 | §5.4 人工阀门：`cenhua link --ban <A> <B>` 黑名单；`cenhua hub` 列枢纽实体（显示当前档位与 N） | 1 天 | 7 | ban 单测；hub 输出档位+ N |
| 11 | §5.4 关联类型：实体共现（自动）/ 主题相似（向量层）/ 显式引用（人工 `cenhua link`，权重 0.8）/ 时间序列（自动）；自动边权 ≤0.6 | 1 天 | 6,9 | 四类型单测；权重上限 |
| 12 | `cenhua related <doc>` 命令：输出每条边带证据（`evidence: "共现于 [docA P3, docB P12], nPMI=0.41"`）；空结果明示"无显著关联（正常）" | 1 天 | 11 | related 输出格式；空结果不沉默 |
| 13 | service 层搬迁：`related` / `refine` / `cost` / `bench` 入 service（**`summarize` 不是用户命令移出 test_71 白名单，由 test_70 管辖——F10**）；CLI 改薄包装 | 1.5 天 | 5,12, M1a | service 函数签名登记入 service-contract.md；CLI ≤10 行 |
| 14 | 防回潮测试：`test_71_cli_is_thin` 白名单首批（M1b: `related`/`refine`/`cost`/`bench`）；`test_70_service_no_print` 全量 | 0.5 天 | 13 | test_70/71 全绿；白名单仅含用户命令 |
| 15 | 单测套件增量：四层降噪/小库模式/精化队列/related 全覆盖 | 1.5 天 | 7-12 | 覆盖率 ≥70%；小库模式降档单测 |
| 16 | 文档同步：user-guide.md 补 `related`/`refine`/`hub` 手册；pitfalls.md 回写新坑；architecture.md 同步；design.md 原则 11 增补 hint-not-evidence（**hint 消费自 v0.3.1 起生效——F3**） | 1 天 | 全 | 四份文档同步 |

**M1b 任务粒度合计**：约 16 任务日；建议节奏 4-5 周完工（含 20% 缓冲）。

### 3.4 Definition of Done

- [ ] §3.3 任务 1-16 全绿
- [ ] §4.4 离线增强唯一归属 M1b（F5；M2a 不再重复此行）
- [ ] deferred 总结闭环：规则先行（零 LLM）→ 按需精化（触发式）→ 预算硬闸（三闸执法顺序）
- [ ] 四层降噪 + 小库模式自动降档（`cenhua hub` 显示档位与 N）
- [ ] `refine --drain` 批量任务豁免中途执法，仅受 `CENHUA_REFINE_BUDGET_CNY` 启动前 all-or-nothing 检查管辖（F1）
- [ ] `related` 输出带证据，空结果不沉默
- [ ] service 层搬迁：`related`/`refine`/`cost`/`bench` 入 service（白名单首批；`summarize` 移出由 test_70 管辖）
- [ ] §1.3 DoD 模板全部勾选

### 3.5 风险点与对策

| 风险 | 对策 |
|---|---|
| 小库模式阈值在真实个人库（N=30~50）下仍空转 | M1b 开工前用真实合同库做 dry-run；阈值可配（`CENHUA_SMALL_CORPUS_N` 默认 200） |
| refine 队列在 M2b 之前没有消费者（T1 排期缺口，F3 已裁决 hint 提前进 M2b） | M1b 文档明示"hint 消费自 v0.3.1 起生效"；用户设预算即知消费者版本 |
| 精化 LLM 输出格式不稳定（ summaries 字段缺失） | summaries dataclass 在 service-contract.md 登记；读侧容忍旧版本（schema_version） |
| 邮件 eml/msg 附件嵌套复杂 | 附件展开走既有 `m_lib.EXTS` 注册；失败进 `inbox/.failed/` 不阻塞 |

---

## 4. M2a · v0.3.0 · 网页收录（独立支线，并行）

### 4.1 目标与范围

**一句话**：把网页 URL 发给 CENHUA → Playwright 渲染 → 双产物（PDF + HTML 快照）→
走标准摄取闭环。**独立支线，不含 §4.4**（F5 唯一归属 M1b）。

### 4.2 前置依赖

- M0 v0.1.0 ✅
- **不依赖 M1**（可与 M1a/M1b 并行开发；语料贡献是增益不是前置）

### 4.3 任务分解

| # | 任务 | 粒度 | 依赖 | 验收 |
|---|---|---|---|---|
| 1 | `requirements.txt` 新增 `playwright>=1.45`（注释说明用途与体积） | 0.5 天 | — | requirements 更新；注释清晰 |
| 2 | `cenhua setup` chromium 安装步骤：有 root/sudo 时 `playwright install --with-deps chromium`（同装系统库 libnss3/libatk 等），无权限时退回 `playwright install chromium` 并明确警告系统库未装（R3-T9） | 1 天 | 1 | 两种权限路径单测/手测；警告文案明确 |
| 3 | `cenhua doctor` 新增 chromium 启动自检：spawn chromium 无头加载 `about:blank`（超时 15s），失败标 PROBLEM 并输出精确修复命令 `sudo playwright install-deps chromium` | 1 天 | 2 | doctor 自检通过/失败两路径 |
| 4 | 自检失败时 `--url` 自动降级静态 HTML 抓取（§4.3 既有降级约束，行为闭环——R3-T9） | 0.5 天 | 3 | 降级路径单测；用户感知 |
| 5 | robots.txt 检查（遵循爬虫礼仪，禁爬则拒绝并提示） | 0.5 天 | — | robots 解析单测；禁爬正确拒绝 |
| 6 | 同域名滑动窗口速率限制（避免压垮目标站） | 0.5 天 | — | 速率限制单测 |
| 7 | Playwright 无头渲染：等待网络空闲/关键元素可见；注入 CJK 字体（防中文乱码） | 1.5 天 | 1 | 渲染超时硬上限 60s；CJK 字体注入生效 |
| 8 | readability 库提正文（去广告/导航/页脚） | 1 天 | 7 | 正文提取单测；广告/导航剥离 |
| 9 | 双产物生成：渲染后 PDF（带页码，进索引） + 原始 HTML 快照（溯源用） | 1 天 | 8 | PDF 页码正确；HTML 快照完整 |
| 10 | 进 inbox 走标准摄取闭环；台账记录 `tier=primary`，标注 `source=url` | 0.5 天 | 9 | 台账字段正确；走既有 ingest_one() |
| 11 | URL 规范化去重：去 fragment、统一 query 排序 | 0.5 天 | — | URL 规范化单测；同 URL 去重 |
| 12 | 单页大小上限（防内存爆），超过则只取前 N 页 | 0.5 天 | 9 | 大小上限单测；截断行为 |
| 13 | 网页摄取失败独立进 `inbox/.failed/`，不阻塞本地文档摄取 | 0.5 天 | 9 | 失败隔离单测 |
| 14 | `cenhua add --url` / `--url-file` / `watch` 监听 `inbox/urls/.url` 文件 | 1 天 | 10 | 三种命令形态单测 |
| 15 | 单测套件增量：robots/速率/渲染/readability/双产物/去重全覆盖 | 1.5 天 | 5-13 | 覆盖率 ≥70%；run_tests.sh 全绿 |
| 16 | 文档同步：user-guide.md 补 `cenhua add --url` 手册；pitfalls.md 回写新坑；architecture.md 同步 m_web.py 模块 | 1 天 | 全 | 三份文档同步 |

**M2a 任务粒度合计**：约 12.5 任务日；建议节奏 3-4 周完工（含 20% 缓冲）。

### 4.4 Definition of Done

- [ ] §4.3 任务 1-16 全绿
- [ ] Playwright 默认安装 + WSL2 系统库对策（`--with-deps` + doctor 启动自检）
- [ ] 自检失败自动降级静态 HTML 抓取（行为闭环）
- [ ] **不含 §4.4**（F5；§4.4 唯一归属 M1b）
- [ ] 双产物（PDF + HTML 快照）+ 走标准摄取闭环
- [ ] robots.txt + 速率限制 + 单页大小上限
- [ ] 网页摄取失败独立进 `inbox/.failed/`，不阻塞本地文档摄取
- [ ] §1.3 DoD 模板全部勾选

### 4.5 风险点与对策

| 风险 | 对策 |
|---|---|
| WSL2 缺系统库必崩 | setup 有 sudo 用 `--with-deps`；doctor 启动自检；自检失败自动降级静态抓取（§4.3 既有约束不变） |
| 渲染超时 | 60s 硬上限降级静态 HTML 抓取 |
| 反爬 | robots.txt 遵循；同域名速率限制 |
| 安装体积 +150MB + 系统库 ~100-200MB | 默认装保证 `--url` 开箱即用；未来可无破坏降级为惰性安装 |

---

## 5. M2b · v0.3.1 · 延展检索 + hint 两段式 prompt 首发

### 5.1 目标与范围

**一句话**：把"检索 + 总结 + 关联推荐"合并为 `cenhua query` 四段输出；**★ hint
两段式 prompt 首发落地**（F3 主人裁决，治 T1 排期缺口）；dry-run 金额预估推广
至全 LLM 命令；拒答门禁生效（跑 fixture）；三层 artifact 标记。

### 5.2 前置依赖

- M1b v0.2.1 ✅（关联层 + summaries）
- **不依赖 M2a**（R2-R4；本地合同库足以验收 query 四段输出）

### 5.3 任务分解

| # | 任务 | 粒度 | 依赖 | 验收 |
|---|---|---|---|---|
| 1 | `cenhua query` 命令骨架：四段输出（直接命中 find + 总结延展 ask + 内容出处 + 关联推荐 related） | 1 天 | M1b | 四段输出格式正确 |
| 2 | 三路融合：`find`（精确）+ `seek`（语义）+ `ask`（推理）单命令合并，按置信度排序 | 1 天 | 1 | 三路融合单测；去重排序 |
| 3 | 检索默认降级：`find/query/seek` 默认只在 primary 层召回；`--include-derived` 显式开启 derived-doc 层 | 0.5 天 | 1 | 默认降级单测；derived 命中显示 ⚠ |
| 4 | 引文穿透：衍生命中带 `derived_from` 链，引文穿透 internal-artifact 与 derived-doc 直达 primary 原件页码 | 1 天 | 1 | 穿透链单测；引文直达 primary |
| 5 | **★ hint 两段式 prompt 首发落地**（F3 主人裁决）：hint 段注入 refined summaries，标 `[HINT tier=internal]`；证据段仅从 primary 文本层取；hint 段只许陈述、不许祈使（防注入，首发即硬规则化） | 2 天 | M1b | hint 段标记正确；prompt 组装两段式；祈使句检测单测 |
| 6 | LLM 输出格式约束：ask/query 响应 schema 强制 citations 带 snippet（无 snippet 在门禁计为失败，倒逼 prompt 输出规范——F2） | 1 天 | 1 | schema 强制 snippet；无 snippet 计失败 |
| 7 | `--dry-run` 金额预估推广至全 LLM 命令（ask/query/digest/draft/refine——R2-R3；复用 M1a 换算函数） | 1 天 | M1a | 全命令 --dry-run 输出 calls+tokens+金额 |
| 8 | 三层 artifact 标记：摄取台账 `tier` 字段（primary/derived-doc/internal-artifact）；internal-artifact 正文不进引文（**但可作 hint 进 prompt，自此生效**） | 1 天 | M1b | tier 标记全覆盖；引文规则正确 |
| 9 | service 层搬迁：`query` 入 service（进入 `test_71` 白名单：M2b = `query`） | 1 天 | 1,5 | service 函数签名登记；CLI ≤10 行 |
| 10 | 拒答门禁生效：跑 fixture 拒答题（拒答正确率 ≥90% 加入阻断集）；发版流水线需 API key；无 key 跳过并在 release notes 标注（F6.2） | 1 天 | M1a | 拒答门禁触发；无 key 跳过路径正确 |
| 11 | 单测套件增量：query 四段/hint 两段式/snippet 强制/三层 artifact 全覆盖 | 1.5 天 | 1-8 | 覆盖率 ≥70%；run_tests.sh 全绿 |
| 12 | 文档同步：user-guide.md 补 `cenhua query` 手册；pitfalls.md 回写；architecture.md 补 hint 两段式 prompt 架构（**M2b 起**，F3）；design.md 原则 11 hint-not-evidence 完整规则（snippet 强制、生效版本 v0.3.1、执法豁免边界） | 1 天 | 全 | 四份文档同步 |

**M2b 任务粒度合计**：约 13 任务日；建议节奏 3-4 周完工（含 20% 缓冲）。

### 5.4 Definition of Done

- [ ] §5.3 任务 1-12 全绿
- [ ] `cenhua query` 四段输出格式正确（命中+延展+引文+关联）
- [ ] **★ hint 两段式 prompt 首发落地**（F3）：hint 段标 `[HINT tier=internal]`，证据段仅从 primary 取，hint 段禁祈使
- [ ] citations 强制带 snippet（F2），无 snippet 在门禁计失败
- [ ] dry-run 金额预估推广至全 LLM 命令
- [ ] 三层 artifact 标记（primary/derived-doc/internal-artifact）；internal-artifact 可作 hint 进 prompt
- [ ] 拒答门禁生效（跑 fixture 拒答题 ≥90%）
- [ ] service 层 `query` 入 service（白名单 M2b）
- [ ] §1.3 DoD 模板全部勾选

### 5.5 风险点与对策

| 风险 | 对策 |
|---|---|
| hint 进 prompt 的注入面（R3/R4 §4 预告） | hint 段首发即硬规则化"只许陈述、不许祈使"；M3a 加注入对抗硬化（fixture 注入对抗题至少 1/3 人工撰写） |
| hint 二段验证成本（R4 §4 预告） | 验证轮次 token 开销计入 refine ROI 账；hint 省下的是导航成本，不能倒贴验证成本 |
| 拒答题非确定性 | temperature=0 + 重试 1 次；连续 2 版 flaky 转人工仲裁 |
| n=10 的 ≥95% 掷硬币（F7） | 引文按条目计量（全量 ≥20）；存在性 100% 零容忍 |
| query 依赖关联层（M1b）但 M2a 未发布时语料不足 | 本地合同库足以验收（R2-R4）；M2a 是增益不是前置 |

---

## 6. M3a · v0.4.0 · service 完成 + digest + 任务通道 + hint 注入对抗硬化

### 6.1 目标与范围

**一句话**：service 层 6 核心函数全部入 service；`cenhua digest` 定期洞察
（all-or-nothing + 豁免中途执法）；任务通道 `submit/job_status/job_result`；
**★ hint 注入对抗硬化**（不再是机制首发——首发在 M2b）；三层 artifact 闭环。
**CLI-only，纯后端，无前端风险。**

### 6.2 前置依赖

- M2b v0.3.1 ✅
- **★ 任务通道持久化边界必须开工前拍板**（R2/R3/R4 连续三轮预告，不得再顺延——
  R4 §4 强制裁决）

### 6.3 任务分解

| # | 任务 | 粒度 | 依赖 | 验收 |
|---|---|---|---|---|
| 1 | **★ 任务通道持久化边界裁决**（R4 §4 强制）：重启后未完成任务的续跑或标废策略；**开工前必须拍板** | 0.5 天（决策） | — | 决策文档落库；ADR 记录 |
| 2 | service 层完成：`ingest`/`find`/`query`/`related`/`ask`/`stats` 全部入 service（dataclass 返回，禁 print/exit）；契约登记制建档持续维护 | 2 天 | M2b | 6 核心函数全部入 service；契约文档与本里程碑实现一致 |
| 3 | 任务通道实现：`submit(job: JobSpec) -> JobHandle` / `job_status(handle) -> JobStatus`（含增量 output chunks、进度、终态、cost 累计）/ `job_result(handle) -> AskResult \| QueryResult` | 2 天 | 1 | 三接口单测；任务通道契约登记 |
| 4 | LLM 长任务（ask/query/digest/draft/ingest 进度）统一走任务通道；CLI 轮询打印进度；CLI/Web/API 三形态共用同一进度协议 | 1.5 天 | 3 | 长任务走通道单测；CLI 进度打印 |
| 5 | 摄取进度（watch 已有 `logs/` 进度）收敛到任务通道同一机制 | 1 天 | 3,4 | watch 进度走通道；旧 logs/ 兼容 |
| 6 | `cenhua digest` 命令骨架：cron 定时（`--weekly`/`--monthly`/`--quarterly`）+ 手动触发（`--since`）+ **watch 提示**（累计摄取 N 篇默认 20 后打印一行提示，F10） | 1 天 | — | 三种触发单测；watch 提示文案正确，无自动触发执行 |
| 7 | digest 洞察文章结构生成：四节模板（本期新增知识图谱 / 跨文档发现 / 待澄清问题 / 引用文档清单） | 1.5 天 | M2b | 文章结构正确；全程带引文（含 snippet） |
| 8 | digest 成本护栏：all-or-nothing + 豁免中途执法（T7+F1）；三闸执法顺序：① dry-run → ② `CENHUA_LONGJOB_MAX_COST_CNY` → ③ `--force`/`--max-cost` 放行；超预算拒绝启动绝不中途停 | 1 天 | 3 | 三闸顺序单测；超预算拒启；中途不被 `MAX_COST`/`MAX_LLM_CALLS` 腰斩 |
| 9 | digest 走任务通道：`submit` → `job_status` 实时进度 → `job_result` 终态 | 0.5 天 | 3,7 | digest 走通道单测；CLI 实时打印 |
| 10 | digest 回流闭环：输出存 `<vault>/works/digests/`（`tier=derived-doc` + `derived_from` 链）；自动作为新文档进 inbox 走摄取闭环 | 1 天 | 7 | 回流单测；tier=derived-doc；默认不召回 |
| 11 | 三层 artifact 闭环：digest 入库 `tier=derived-doc`；引文穿透穿透 internal-artifact 直达 primary；`cenhua sources` 按三类分组显示 | 1 天 | 10 | sources 分组单测；穿透链正确 |
| 12 | 图谱隔离：衍生文档（derived-doc）与 internal-artifact 均不参与实体共现建边 | 0.5 天 | M1b | 隔离单测 |
| 13 | **★ hint 注入对抗硬化**（F3，不再是机制首发）：hint 段指令剥离（硬规则化只许陈述、不许祈使）；fixture 加注入对抗题（**至少 1/3 对抗题人工撰写**，防出题方与攻击方同源盲区——R4 §4 预告）；hint 二段验证成本计入 refine ROI 账 | 2 天 | M2b | 祈使句检测硬规则化；对抗题至少 1/3 人工；ROI 账可见 |
| 14 | `cenhua cost` 摄取成本单列首位（T5；ledger 全量记账含 add 树索引） | 0.5 天 | M1a | cost 输出格式；摄取成本首位 |
| 15 | service 层搬迁：`digest` 入 service（进入 `test_71` 白名单：M3a = `digest`） | 0.5 天 | 7 | service 函数签名登记；CLI ≤10 行 |
| 16 | 防回潮测试：`test_70_service_no_print` 全量；`test_71_cli_is_thin` 白名单（M3a: `digest`） | 0.5 天 | 2,15 | test_70/71 全绿 |
| 17 | 单测套件增量：service 完成/任务通道/digest 闭环/hint 注入对抗全覆盖 | 2 天 | 2-13 | 覆盖率 ≥70%；run_tests.sh 全绿 |
| 18 | 文档同步：user-guide.md 补 `cenhua digest` 手册；pitfalls.md 回写；architecture.md 同步补 service 层架构 + 任务通道架构（**M3a 起**）+ hint 注入对抗硬化架构；design.md 原则 11 增补注入对抗 | 1 天 | 全 | 四份文档同步 |

**M3a 任务粒度合计**：约 20 任务日；建议节奏 5-6 周完工（含 20% 缓冲，M3a 是工程难度最高点）。

### 6.4 Definition of Done

- [ ] §6.3 任务 1-18 全绿
- [ ] **★ 任务通道持久化边界开工前已拍板**（R4 §4 强制，不得再顺延）
- [ ] service 层 6 核心函数全部入 service（契约登记制持续维护）
- [ ] 任务通道 `submit/job_status/job_result` 三接口落地，CLI/Web/API 共用同一进度协议
- [ ] `cenhua digest` 走任务通道，CLI 实时打印进度
- [ ] digest all-or-nothing + 豁免中途执法（三闸执法顺序）
- [ ] **★ hint 注入对抗硬化**（不再是机制首发）：指令剥离硬规则化、fixture 注入对抗题至少 1/3 人工撰写、hint 二段验证成本计入 refine ROI
- [ ] 三层 artifact 闭环：digest 入库 `tier=derived-doc`；`cenhua sources` 按三类分组
- [ ] digest 触发方式含 watch 打印提示（F10，无自动触发执行）
- [ ] §1.3 DoD 模板全部勾选

### 6.5 风险点与对策

| 风险 | 对策 |
|---|---|
| **任务通道持久化边界未拍板** | **开工前必须裁决**（R4 §4 强制）；选项：① 重启后续跑 ② 重启后标废 ③ 持久化到 sqlite |
| M3a 工程难度最高（5 事同里程碑） | 任务粒度缓冲 20%；建议先做任务通道 + service 完成，再做 digest + hint 硬化 |
| digest 全库扫描成本（R3 §4 预告） | `cenhua digest --dry-run` 估价；超 `CENHUA_LONGJOB_MAX_COST_CNY`（5.0）拒启；库到 1000 篇时考虑抽样策略 |
| hint 注入对抗题出题权盲区 | 至少 1/3 对抗题人工撰写；fixture 注入对抗题进 `meta/qa/flaky.jsonl` 跟踪 |
| 任务通道持久化方案影响断线重连设计 | 持久化边界先拍板再设计 job_status 增量协议 |

---

## 7. M3b · v0.5.0 · 本地 Web UI + 局域网 API（薄适配）

### 7.1 目标与范围

**一句话**：脱离智能体也能用——浏览器打开本地页面即可录入、检索、看洞察
（**洞察浏览 digest 只读——草稿编辑移 M4，F4**）；附带局域网 API 供个人设备/程序
互联（单 token + fail-closed，清除租户残肢）；SSE 只是任务通道的薄适配。

### 7.2 前置依赖

- M3a v0.4.0 ✅
- M3b 失败（Web UI 黄了）产品仍是完整 CLI（个人用户 90% 场景）

### 7.3 任务分解

| # | 任务 | 粒度 | 依赖 | 验收 |
|---|---|---|---|---|
| 1 | FastAPI + Jinja2 + HTMX 脚手架（薄包装在 M3a 的 service 上） | 1 天 | M3a | 脚手架可起服务；薄包装无业务逻辑 |
| 2 | 摄取页：文件拖拽上传 + URL 输入框 + SSE 进度 + 失败重试 | 2 天 | 1 | 拖拽/SSE/重试三路径手测 |
| 3 | 检索页：搜索框 → 命中+延展+引文（含 snippet）+关联四段结果页 | 2 天 | 1 | 四段呈现正确；引文 snippet 悬浮 |
| 4 | 编织页：文档列表 + 标签/笔记编辑 + 关联图 Mermaid 可视化 | 2 天 | 1 | Mermaid 渲染；标签编辑 |
| 5 | **创造页：洞察浏览**（digest 只读——F4；草稿编辑/引文悬浮/版本对比移 M4） | 1 天 | 1 | digest 只读浏览；无草稿编辑 |
| 6 | 局域网 API `/api/v1/*` 端点挂到 service 层（POST ingest/GET documents/POST find/POST query/POST ask/POST digest/GET relations） | 2 天 | M3a | API 端点契约登记；dataclass 序列化 |
| 7 | 鉴权：单用户 token + `CENHUA_API_TOKEN`（fail-closed 白名单；T8.2 清除租户残肢——不做行级过滤、不做用户映射） | 1 天 | 6 | fail-closed 单测；无 token 拒绝 |
| 8 | 滑动窗口 RateLimiter → 429；结构化日志带 rid 全链路追踪 | 1 天 | 6 | 限流单测；rid 全链路 |
| 9 | SSE 薄适配：Web/API 层把 M3a 的 `job_status` 增量转 SSE 事件流；断线重连按 handle 重订阅天然安全（R2-R9） | 1.5 天 | M3a | SSE 增量推送；断线重连手测 |
| 10 | API 端点版本脚注：`GET /api/v1/graph` 与 `POST /api/v1/draft` 在 v0.5 均返回 404 + 版本提示（"v0.6 起，随 M4 交付"——R2-R10 + R3-T8.1 + R4-F4） | 0.5 天 | 6 | 404 + 版本提示正确 |
| 11 | uvicorn `timeout_keep_alive` 与请求级 timeout 按推理时长设置（F8 删 Nginx 反代叙述） | 0.5 天 | 1 | timeout 配置；无 Nginx 依赖 |
| 12 | 单测套件增量：API 端点/鉴权/限流/SSE 全覆盖 | 1.5 天 | 6-10 | 覆盖率 ≥70%；run_tests.sh 全绿 |
| 13 | 文档同步：user-guide.md 补 Web UI 与 API 手册（M3b 起）；Nginx 仅作为可选部署附件在此提一句（F8）；pitfalls.md 回写；architecture.md 同步 | 1 天 | 全 | 文档同步 |

**M3b 任务粒度合计**：约 17 任务日；建议节奏 4-5 周完工（含 20% 缓冲）。

### 7.4 Definition of Done

- [ ] §7.3 任务 1-13 全绿
- [ ] Web UI 四页（摄取/检索/编织/洞察浏览）独立运行
- [ ] **创造页只读 digest**（F4；草稿编辑/引文悬浮/版本对比移 M4）
- [ ] 局域网 API `/api/v1/*` 端点挂到 service 层
- [ ] 单用户 token + fail-closed 白名单（清除租户残肢）
- [ ] SSE 是任务通道的薄适配（断线重连按 handle 重订阅）
- [ ] `GET /api/v1/graph` 与 `POST /api/v1/draft` 在 v0.5 返回 404 + 版本提示
- [ ] uvicorn `timeout_keep_alive` 配置（无 Nginx 反代依赖）
- [ ] §1.3 DoD 模板全部勾选

### 7.5 风险点与对策

| 风险 | 对策 |
|---|---|
| Web UI 黄了 | M3b 失败产品仍是完整 CLI（个人用户 90% 场景）；薄包装无业务逻辑，黄了不影响 service 层 |
| SSE 长连接挂起 | 任务通道（M3a 落）+ 空闲 10s 心跳 + 30s 探测 + 短总兜底；透传 `response.failed` |
| 局域网 API 暴露风险 | 单 token + fail-closed；不做 OAuth/WAF/多租户；个人局域网定位 |
| 草稿编辑误承诺（F4 同款错误反向再犯） | 创造页严格只读 digest；草稿编辑三件套移 M4 交付物 |

---

## 8. M4 · v0.6.0 · 知识图谱 + 主题创作 + Web 草稿编辑

### 8.1 目标与范围

**一句话**：实体级知识图谱（NER + 三元组 + 邻接表 + Mermaid；Web 力导向图需 M3b
已发布）+ 主题创作 `cenhua draft`（all-or-nothing + 独立预算 + `draft --verify`
反向包装 verify_citation）+ **★ Web 草稿编辑三件套**（从 M3b 移入，F4）+ 模板系统
+ 多轮与重排。

### 8.2 前置依赖

- M3a v0.4.0 ✅
- **不依赖 M3b**（CLI 用户也能用图谱与草稿；但 Web 力导向图与草稿编辑需 M3b 已发布）

### 8.3 任务分解

| # | 任务 | 粒度 | 依赖 | 验收 |
|---|---|---|---|---|
| 1 | §5.5 实体抽取：摄取时从文本层抽取实体（NER，规则粗提 + 按需 LLM 精化） | 1.5 天 | M3a | NER 单测；规则+LLM 两路 |
| 2 | §5.5 关系抽取：实体-关系-实体三元组 | 1.5 天 | 1 | 三元组单测 |
| 3 | §5.5 图谱存储：v0.6 用邻接表（JSON）；后续评估 neo4j | 1 天 | 2 | 邻接表格式；JSON 可序列化 |
| 4 | §5.5 图谱查询：`cenhua graph entity` / `path` / `cluster` | 1.5 天 | 3 | 三子命令单测 |
| 5 | §5.5 可视化：CLI 邻接表 + Mermaid 输出（无条件交付） | 1 天 | 3 | Mermaid 输出格式 |
| 6 | §5.5 Web UI 力导向图（**仅 M3b 已发布时交付**——R2-R8） | 2 天 | M3b | 力导向图渲染；M3b 未发布时跳过 |
| 7 | §7.4 `cenhua draft` 命令骨架：主题→拆解→召回→生成→引文穿透（含 snippet）→版本管理 | 2 天 | M3a | draft 流程单测；存档 `<vault>/works/drafts/` |
| 8 | `cenhua draft --extend` / `--rewrite` / `--list` / `--diff` / `--restore` | 1.5 天 | 7 | 五子命令单测 |
| 9 | `cenhua draft --verify`：**反向包装 M1a `verify_citation(doc, page, snippet)`**（T4+F2；门禁与草稿共用同一校验实现，单一事实源） | 1 天 | 7, M1a | verify 包装单测；snippet 归一化匹配 |
| 10 | draft 成本护栏：all-or-nothing + 独立长任务预算 + 豁免中途执法（T7+F1）；三闸执法顺序：① dry-run → ② `CENHUA_LONGJOB_MAX_COST_CNY` → ③ `--force`/`--max-cost` 放行；断点续跑 M4 前不做，失败重跑从头估价（幂等由 `rid` 保证） | 1 天 | 7 | 三闸顺序单测；超预算拒启；rid 幂等 |
| 11 | **★ Web UI 草稿编辑三件套**（F4 从 M3b 移入）：草稿在线编辑（带引文悬浮提示）+ 版本对比 + 引文穿透到 primary | 2.5 天 | M3b,7 | 三件套手测；引文悬浮 |
| 12 | §7.5 模板系统：报告/备忘录/邮件/周报，自定义模板放 `<vault>/meta/templates/` | 1.5 天 | — | 四模板示例；自定义可加 |
| 13 | §7.5 导出：Markdown / HTML / PDF | 1 天 | 12 | 三导出格式单测 |
| 14 | §6.6 多轮对话：上下文继承 | 1.5 天 | M3a | 多轮上下文单测 |
| 15 | §6.6 重排器：粗召回后用小模型重排，提升 Top-K 精度 | 1.5 天 | M3a | 重排单测；Top-K 提升 |
| 16 | API 端点：`GET /api/v1/graph` 与 `POST /api/v1/draft` 端点随 M4 交付（v0.6 起） | 1 天 | 4,7 | 两端点契约登记；dataclass 序列化 |
| 17 | service 层搬迁：`draft` 入 service（进入 `test_71` 白名单：M4 = `draft`） | 0.5 天 | 7 | service 函数签名登记；CLI ≤10 行 |
| 18 | 防回潮测试：`test_70_service_no_print` 全量；`test_71_cli_is_thin` 白名单（M4: `draft`） | 0.5 天 | 17 | test_70/71 全绿 |
| 19 | 单测套件增量：图谱/draft/模板/导出/多轮/重排全覆盖 | 2 天 | 1-15 | 覆盖率 ≥70%；run_tests.sh 全绿 |
| 20 | 文档同步：user-guide.md 补 `cenhua graph`/`cenhua draft`/模板/导出手册；pitfalls.md 回写；architecture.md 同步图谱+draft 架构；design.md 原则 11 完整闭环 | 1 天 | 全 | 四份文档同步 |

**M4 任务粒度合计**：约 25.5 任务日；建议节奏 6-7 周完工（含 20% 缓冲，M4 范围最广）。

### 8.4 Definition of Done

- [ ] §8.3 任务 1-20 全绿
- [ ] 知识图谱：NER + 三元组 + 邻接表 + Mermaid（无条件交付）
- [ ] Web UI 力导向图仅在 M3b 已发布时交付（R2-R8）
- [ ] `cenhua draft` 主题创作闭环（all-or-nothing + 豁免中途执法 + rid 幂等）
- [ ] `draft --verify` 反向包装 M1a `verify_citation(doc, page, snippet)`（单一事实源）
- [ ] **★ Web 草稿编辑三件套**（F4 从 M3b 移入）：草稿编辑/引文悬浮/版本对比
- [ ] 模板系统（报告/备忘录/邮件/周报）+ 导出（Markdown/HTML/PDF）
- [ ] 多轮对话 + 重排器
- [ ] `GET /api/v1/graph` 与 `POST /api/v1/draft` 端点随 M4 交付
- [ ] service 层 `draft` 入 service（白名单 M4）
- [ ] §1.3 DoD 模板全部勾选

### 8.5 风险点与对策

| 风险 | 对策 |
|---|---|
| M4 范围最广（图谱+draft+模板+导出+多轮+重排+Web 草稿编辑） | 任务粒度缓冲 20%；建议先做图谱 + draft 闭环，再做模板/导出/多轮/重排/Web 草稿编辑 |
| Web 力导向图依赖 M3b 已发布 | M3b 未发布时 CLI 邻接表 + Mermaid 仍可用；Web 力导向图跳过 |
| NER 规则粗提质量 | 规则粗提 + 按需 LLM 精化（复用 M1b refine 机制）；小库模式降档 |
| draft 全库扫描成本 | all-or-nothing + 独立预算；超预算拒启 |
| 断点续跑不做 | 失败重跑从头估价；长任务幂等由 `rid` 保证可审计 |

---

## 9. 风险登记册（合并 roadmap §13 + 实施期）

### 9.1 已落地对策（M0-M1a 阶段）

| 风险 | 对策 | 状态 |
|---|---|---|
| `pageindex` 仅官方 PyPI 有 | 安装固定 `--index-url pypi.org` + `--no-deps`；`cenhua doctor` 自检 | ✅ |
| 成本失控（`ask --all`） | `--dry-run` 默认；`CENHUA_MAX_LLM_CALLS` 默认 8；超限需 `--force` | ✅ |
| 静默空白 PDF | 0.85 字符完整性校验；doctor 扫描空文本层标 PROBLEM | ✅ |
| 加密 PDF 被静默跳过 | 文件名口令尝试 + "双路径一致才敢说没有"纪律 | ✅ |
| OCR 成本与质量 | RapidOCR 本地优先 + 质量门校验 + 视觉兜底 | ✅ |
| vision 模型需裸 model id | `setup` 时 `/models` 探测；`PI_VISION_MODEL` 裸 ID | ✅ |
| 索引慢（52 页≈140s） | `watch` 后台 + 进度写 `logs/` + `status` 显示进行中 | ✅ |

### 9.2 待落地对策（M1a-M4 阶段）

| 风险 | 对策 | 落地版本 |
|---|---|---|
| 写入路径 LLM 成本失控 | 衍生分析默认免费（规则先行 + 按需精化 + 预算硬闸） | M1b |
| 关联全连接毛球 | 四层降噪 + 自动边权 ≤0.6 | M1b |
| 关联常年空转（小库坍塌） | 小库模式自动降档，`cenhua hub` 显示档位 | M1b |
| 引文洗白 provenance laundering | 三层 artifact + 检索默认降级 + 引文穿透 + 图谱隔离 + sources 分组 | M2b |
| refine 没有消费者 + 排期缺口 | hint-not-evidence 角色 + **prompt 两段式自 M2b 起生效**；M3a 注入对抗硬化 | M2b/M3a |
| 网页渲染超时/被反爬 | 60s 硬上限降级静态抓取；robots.txt 遵循；同域名速率限制 | M2a |
| Playwright 安装负担 + WSL2 缺系统库 | requirements 默认装 + setup `--with-deps` + doctor 启动自检 + 自检失败自动降级 | M2a |
| LLM 网关挂起致 SSE 空转 | 任务通道（M3a 落）+ 空闲 10s 心跳 + 30s 探测 + 短总兜底；透传 `response.failed` | M3a/M3b |
| service 层回潮 | `test_70_service_no_print`（service 全量）+ `test_71_cli_is_thin`（白名单制，只收用户命令） | M1a 起 |
| service 契约透支 | 契约登记制（M1a 首 commit 建档，直接采用升级后契约）+ dataclass 只加字段不删改 + schema_version | M1a 起 |
| 树索引成本被用户当营销条款验收反噬 | 原则 10 措辞降级；`CENHUA_MAX_COST_CNY` 排除 add | M1a |
| ledger 漏记 add 致 cost 月报低报 | 全量记账仅免闸——所有 LLM 调用（含 add、OCR 视觉兜底）一律写 ledger；摄取成本单列首位 | M1a |
| QA 门禁跑活库致语料增长假回归 | `cenhua bench` 默认跑 fixture 冻结产物；用户库 QA 报告模式 | M1a |
| 门禁引用 M4 校验器依赖倒置 | `verify_citation(doc, page, snippet)` 原语进 M1a；M4 `draft --verify` 反向包装 | M1a/M4 |
| digest/draft 中途预算停留半成品 + 单命令预算/次数上限腰斩 | all-or-nothing + 独立长任务预算 + **豁免 `CENHUA_MAX_COST_CNY`/`CENHUA_MAX_LLM_CALLS` 中途执法**；三闸执法顺序 | M3a/M4 |
| verify_citation 同义反复校验 | 升级为三参签名 `verify_citation(doc, page, snippet)`，校验 snippet 归一化后存在于该页文本层（NFKC + 去空白/全半角折叠后正则匹配）；citations dataclass 含 snippet；ask/query 响应 schema 强制带 snippet | M1a/M2b |
| fixture 门禁三处工程矛盾 | fixture 是冻结产物（tree index + 文本层 + 30 题，bench 不重建索引）；门禁分层（CI 离线阻断 / 发版流水线全量含拒答需 key）；拒答非确定性治理（temperature=0 + 重试 + flaky 转人工仲裁） | M1a |
| n=10 的 ≥95% 掷硬币阈值 | 引文按条目计量（全量 ≥20，按条目占比 ≥95%）；存在性 100% 零容忍；失败输出逐条 diff 清单 | M1a |
| M3b 画 M4 草稿饼 + §4.4 双份承诺 + 矩阵现状倒退 | M3b 创造模块收敛为洞察浏览，草稿编辑移 M4；§4.4 唯一归 M1b；矩阵拆格 + 编织行双标 | M1b/M3b/M4 |
| 部署约束残留租户时代器官 | 删 Nginx 反代叙述改 uvicorn `timeout_keep_alive`；日志脱敏去 open_id 改 token/绝对路径/PI_KEY 前缀 | M3b |
| pricing 货币与网关匹配未定义 | pricing.json 加 `currency` 字段混合货币不折算；OpenClaw 全名匹配规则（先全名 → 再裸 id → 未命中保守默认价） | M1a |

### 9.3 实施期自查项（不阻塞发版）

| 自查项 | 触发版本 | 对策 |
|---|---|---|
| hint 注入面 | M2b/M3a | hint 段首发即硬规则化"只许陈述、不许祈使"；M3a 加注入对抗题至少 1/3 人工撰写 |
| hint 二段验证成本 | M3a | 验证轮次 token 开销计入 refine ROI 账 |
| 用户库 QA 报告模式告警阈值 | M1a 起 | 引文准确率连续下滑时主动提示重新出题 |
| 冻结 fixture 与引擎升级断裂 | M1a 起 | fixture 绑定 `engine_version`；提供 `bench --rebuild`（显式重建，烧 LLM 需确认） |
| snippet 摘取的诚实性 | M1a 起 | verify 只证"该句在该页"不证"该句支撑该结论"；引文准确率诚实上限是逐字可溯率，文档措辞不得升格为"语义正确率" |
| **★ 任务通道持久化边界** | **M3a 开工前必拍板** | 重启后未完成任务的续跑或标废策略；R2/R3/R4 连续三轮预告，不得再顺延 |
| digest 全库扫描成本（库到 1000 篇） | M3a 起 | `digest --dry-run` 估价；抽样策略评估 |

---

## 10. 发布流程

### 10.1 发版前检查清单

- [ ] DoD 模板全部勾选（§1.3）
- [ ] 代码审查清单全部通过（§1.4）
- [ ] `bash tests/run_tests.sh` 全绿
- [ ] `cenhua bench`（fixture 模式）通过：存在性 100% + 引文条目 ≥95% + 拒答 ≥90%（M2b 起）
- [ ] 文档同步：user-guide.md / pitfalls.md / architecture.md / design.md / service-contract.md
- [ ] CHANGELOG 更新
- [ ] 版本号 bump（语义化版本）
- [ ] release notes 标注（含无 API key 跳过拒答集的标注——F6.2）
- [ ] GitHub release 创建（Hugh Han 提交身份）
- [ ] ClawHub 技能包同步（如涉及技能层变更）

### 10.2 版本号规范

- 主版本号 `v0.X.Y`：X 里程碑编号，Y 子版本（M1a=v0.2.0 / M1b=v0.2.1 / M2a=v0.3.0 / M2b=v0.3.1 / M3a=v0.4.0 / M3b=v0.5.0 / M4=v0.6.0）
- 预发布：`v0.X.Y-rc.N`
- 紧急修复：`v0.X.Y+1`（仅 bugfix，不新增功能）

### 10.3 发布后

- 归档对应 review 文档（R1/R2/R3/R4 已归档；后续 review 同款处理）
- 决策沉淀进 roadmap §12 ADR
- 更新 dev-plan.md 状态标记（✅）
- 触发下一轮 roadmap 评审（如需）

---

## 11. 遗留事项追踪（合并 roadmap §18）

| 事项 | 状态 | 落地版本 |
|---|---|---|
| roadmap.md 按 R1-R4 四份评审修订 | ✅ 已完成 | — |
| design.md：原则 10 增补"全量记账仅免闸 + 长任务/批量任务豁免中途执法"（T5+F1） | 📋 待 | M1a 起 |
| design.md：原则 11 增补 hint-not-evidence 完整规则（F2 snippet 强制、F3 生效版本、执法豁免边界） | 📋 待 | M2b 起 |
| `docs/service-contract.md` 建档（M1a 首 commit，直接采用升级后契约：citations 含 snippet、verify_citation 三参签名、schema_version——F2） | 📋 待 | M1a 首 commit |
| fixture 冻结产物制作流程（合成语料 → 建索引 → 冻结打包，绑定 engine_version，提供 `bench --rebuild`） | 📋 待 | M1a |
| pricing.json `currency` 字段与 OpenClaw 全名匹配规则落 M1a（F9） | 📋 待 | M1a |
| README 形态叙述同步（R1 遗留，仍未关闭） | 📋 待 | M1a 起 |
| architecture.md 同步补 service 层架构（M1a 起）+ 任务通道架构（M3a 起）+ hint 两段式 prompt 架构（**M2b 起**，F3） | 📋 待 | M1a 起 |
| `max_llm_calls` → `CENHUA_MAX_LLM_CALLS` 迁移需兼容旧 env 名一个版本（deprecation warning） | 📋 待 | M1a |
| `CENHUA_API_ALLOWED_AGENTS` 删除迁移：旧配置读取时 warn 并降级为单 token 模式（T8.2） | 📋 待 | M3b |
| **★ 任务通道持久化边界**（R2/R3/R4 连续三轮预告，**M3a 开工前必须拍板**） | 📋 待 | M3a 开工前 |

---

## 12. 状态总览

| 里程碑 | 版本 | 状态 | 任务粒度 | 建议节奏 |
|---|---|---|---|---|
| M0 | v0.1.0 | ✅ 已发布 | — | — |
| M1a | v0.2.0 | 🚧 开发中（成本+质量基建已落地） | 16.5 任务日 | 4-5 周 |
| M1b | v0.2.1 | 📋 规划 | 16 任务日 | 4-5 周 |
| M2a | v0.3.0 | 📋 规划（独立支线） | 12.5 任务日 | 3-4 周 |
| M2b | v0.3.1 | 📋 规划 | 13 任务日 | 3-4 周 |
| M3a | v0.4.0 | 📋 规划（工程难度最高点） | 20 任务日 | 5-6 周 |
| M3b | v0.5.0 | 📋 规划 | 17 任务日 | 4-5 周 |
| M4 | v0.6.0 | 📋 规划（范围最广） | 25.5 任务日 | 6-7 周 |

**主线总粒度**：约 108 任务日（M1a+M1b+M2b+M3a+M3b+M4）；M2a 独立支线 12.5 任务日。
**主线总节奏**：约 26-32 周（含 20% 缓冲，单维护人 3-5 有效工作日/周）。

---

*本文档随里程碑完工持续更新；每里程碑完工后状态标记改 ✅ 并归档对应 review 文档。
评审历史见 roadmap.md 修订历史。开发计划变更回写本文，设计原则变更回写 design.md。*
