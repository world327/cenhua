# CENHUA Roadmap 二轮评审意见与决议（2026-10-13 R2）

> 对修订版 [roadmap.md](roadmap.md)（已吸收一轮评审 [roadmap-review-2026-10-13.md](roadmap-review-2026-10-13.md) 全部裁决）
> 的二次拷问：10 问（R1-R10）+ 主人逐项裁决 + 落地动作。
> 本轮多数问题是**修订本身引入的新伤**——依赖倒置、伪依赖复发、中间产物 tier 漏洞、契约透支。
> 状态标记：✅ 已裁决待落文档 · 本文档与 R1 评审同为 roadmap 下次修订的输入，修订完成后可归档。

---

## 0. 二轮评审结论摘要

一轮修订忠实落地（形态收敛、双层标记、依赖并线、ADR 沉淀均合格），但暴露三类新问题：

1. **原则 10 名不副实**——真正最贵的写入 LLM（树索引）不在成本闸门管辖内（R1）
2. **门禁与依赖的工程化漏洞**——发布门禁无人交付（R2）、预算闸依赖后置单价表（R3）、伪依赖与版本号捆绑复发（R4）
3. **抽象层的现实债**——tier 二元漏了中间产物（R5）、service 契约透支（R6）、流式契约缺失（R9）

---

## 1. 裁决记录（R1-R10）

### R1 · "写入默认免费"假命题：树索引不受成本闸门管 —— ✅ 已裁决（措辞降级）

**问题**：原则 10 宣称"LLM 不进摄取路径"、§5.3 称"摄取时只做零成本动作"，但 §13 风险表
自证**树索引构建是 LLM 驱动**（52 页 ≈140s），§16 承认 `add (建索引)` 需要 LLM。
一份 200 页合同的树索引成本 ≈ 十几次总结，三道闸门却只管总结/NER；
`watch` 常驻批量摄取 100 份文档时亦无预算闸。原则会被用户当营销条款验收，将来必被反噬。

**主人裁决**：**原则 10 措辞降级为"总结/NER 默认免费"**，不做树索引按需分层。

**落地动作**：
- design.md 原则 10 改为：**"总结/NER 默认免费——写入路径的衍生分析（总结、NER、关联）
  规则先行、按需精化、预算硬闸；树索引构建是摄取的核心成本，属显式已知成本"**
- §5.3 删除"摄取时只做零成本动作"的绝对化表述，改为"衍生分析默认免费，树索引为摄取固有
  成本（已在 §13 台账）"
- roadmap §1 成本哲学行同步改述：`grep 管存在（免费），LLM 管意义（树索引=摄取固有成本；
  衍生分析=三道闸门按需付费）`
- `CENHUA_MAX_COST_CNY` 适用范围明确排除 `add`（树索引成本走 §13 既有 dry-run 估算 + 进度
  可见，不设预算拒执——摄取被预算中途拒绝会留下半成品库，风险大于收益）

### R2 · `cenhua bench` 是无人交付的发布门禁 —— ✅ 已裁决

**问题**：§8 验收通用标准第 7 项要求"发布前跑 `cenhua bench`，回归即阻断发版"，
但 M1-M4 交付物清单里没有任何一格交付 `bench` 命令本身。没被构建的门禁不能阻断发版。

**主人裁决**：同意。`bench` + QA 集写入 M1 交付物，指标分阶段生效。

**落地动作**：
- **M1 交付物新增**：`cenhua bench` 命令 + QA 集冷启动（`meta/qa/benchmark.jsonl` ≥30 题：
  存在性 15 + 溯源 10 + 拒答 5，从 pitfalls.md 实战案例反推）
- **门禁指标分阶段生效**：
  - M1/M2：存在性召回 100%（阻断）+ 引文准确率 ≥95%（阻断）；拒答类不计（query 尚不存在）
  - M2b 起：拒答正确率 ≥90% 加入阻断集
- 遗留事项中"QA 集冷启动 30 题"随 M1 关闭，不再单列

### R3 · M1 预算闸依赖 M2b 才交付的 pricing.json —— ✅ 已裁决

**问题**：M1 三道闸门的第 3 闸（估算 token → 换算金额 → 超预算即拒）需要单价表，
但 `pricing.json` 写在 M2b 交付物里——M1 发布时换算不了金额，预算硬闸形同虚设；
M1 的 `cenhua cost` 汇总同样需要它。

**主人裁决**：同意。pricing.json 挪进 M1。

**落地动作**：
- **M1 交付物新增**：`pricing.json`（model → 每 1K token in/out 价格；未知模型保守默认价 +
  "未配置单价"标注）+ 换算函数 + `cost-ledger.jsonl` 三者同包交付
- M2b 交付物中该项改为："dry-run 金额预估**推广至全 LLM 命令**（复用 M1 换算函数）"
- 预估校准闭环（预估偏差 >3x 告警防单价过期）随 M1 的 ledger 一起落

### R4 · M2b 伪依赖 M2a + 共用 v0.3.0 版本号 —— ✅ 已裁决

**问题**：`query` 延展检索需要的是**语料**而非"网页语料"——本地合同库足以验收四段输出。
M2b 依赖 M2a 是刚修掉的"串行链白白拖住"换了方向复发；且 M2a/M2b 共用 v0.3.0，
设计上允许独立失败、并行开发，共版本意味着永远捆绑发布，独立性是假的。

**主人裁决**：同意。依赖修正，版本号分离。

**落地动作**：
- 依赖图修正：**M2b 只依赖 M1**（关联层）；M2a 为独立支线，语料贡献是增益不是前置
- 版本号分离：**M2a → v0.3.0**（网页收录），**M2b → v0.3.1**（query 延展检索）
- 依赖图重排：`M1 → M2b → M3a → M3b`；`M2a` 独立支线并行；两者先后互换不影响主线

### R5 · summaries 被打成 tier=primary，违反原则 11 —— ✅ 已裁决

**问题**：§15.1 摄取流把 `meta/summaries/<doc>.json` 标为 `tier=primary`。refined 态总结是
纯 LLM 生成内容，digest 引用它、related 展示它时就是"衍生内容冒充事实"现行犯。
二元 tier 没给"中间产物"立规矩。

**主人裁决**：同意。引入 internal-artifact 第三类。

**落地动作**：
- 台账 artifact class 三元化：
  | 类别 | 成员 | 检索/引文规则 |
  |---|---|---|
  | `primary` | 原件、网页 HTML 快照、硬化 PDF | 事实源，检索默认召回，可作引文 |
  | `derived-doc` | digest、draft | 默认不召回（`--include-derived` 开启），展示必带 ⚠ 标记，引文穿透到 primary |
  | `internal-artifact` | summaries、entities、vectors、relations | **永不出现在用户可见引文**；仅作检索加速结构；LLM prompt 组装禁止直接引用其正文 |
- digest/draft 的引文穿透链必须**穿透 internal-artifact 直达 primary 原件页码**
- `cenhua sources` 输出按三类分组显示

### R6 · service 契约"6 函数"透支 + test_71 全量误伤 —— ✅ 已裁决

**问题**：契约清单（ingest/find/query/related/ask/stats）不含修订版新增的
refine/cost/bench/digest/draft——dataclass 契约每里程碑扩张 = 每里程碑破坏 API 兼容。
且 v0.1 CLI 实为单 main() 巨石分发器，`test_71_cli_is_thin`（函数体≤10行）全量生效则 M1 当天 CI 全红。

**主人裁决**：同意。契约登记制 + 白名单增量生效。

**落地动作**：
- **契约登记制**：service 契约文档化于 `docs/service-contract.md`，"6 核心函数 +
  每里程碑增量登记"——新函数必须登记 dataclass 字段与 `schema_version` 才能进实现；
  已有 dataclass 只加字段不删改（加 `schema_version` 字段，读侧容忍旧版本）
- **test_71 白名单制**：`test_71_cli_is_thin` 只对白名单内已迁移命令生效；
  白名单随里程碑只增不减（M1: related/summarize → M2b: query → M3a: digest…），
  未迁移命令豁免——绞杀者模式的正确姿势
- test_70_service_no_print 自 M1 起对 service 模块全量生效（新建代码无历史债）

### R7 · Playwright 安装负担 —— ✅ 已裁决（写入 requirements 默认安装）

**问题**：M2a 引入 Playwright + headless Chromium（下载 >150MB），v0.1 依赖声明无此项，
对 `pip install` 即用的技能是安装体验分水岭。

**主人裁决**：**写入 requirements.txt，默认安装**（否决评审建议的 optional extra 方案）。

**落地动作**：
- `requirements.txt` M2a 时新增：`playwright>=1.45`，注释说明用途与体积
- `cenhua setup` 安装依赖后追加执行 `playwright install chromium`（浏览器二进制无法
  随 pip 分发，必须显式装；纳入 setup 的幂等步骤，已装则跳过）
- `cenhua doctor` 新增检查项：chromium 存在性/版本，缺失标 WARN 并给出修复命令
- 运行时降级保留：渲染超时/失败仍降级静态 HTML 抓取（§4.3 既有约束不变）
- 备注备案：默认安装保证 `--url` 开箱即用，代价是安装体积 +150MB 与首装时长；
  若未来用户反馈安装痛，可无破坏降级为惰性安装（功能行为不变）

### R8 · M4"力导向图"与"M4 不依赖 M3b"矛盾 —— ✅ 已裁决

**主人裁决**：同意，加发布条件。

**落地动作**：M4 交付物该行改为：
"图谱可视化：CLI 邻接表 + Mermaid 输出（无条件交付）；**Web UI 力导向图仅在 M3b 已发布时交付**"。

### R9 · SSE 流式 vs dataclass 阻塞返回 —— ✅ 已裁决（任务化 + SSE 轮询）

**问题**：§3.3 承诺 SSE 推 LLM 流式输出，service 契约一律 dataclass 阻塞返回，
流式需要 generator/回调/任务轮询三选一，契约未定，M3b 会现场补架构。

**主人裁决**：**采用任务化 + SSE 轮询**。

**落地动作**：
- service 契约新增任务接口（登记制首选手，见 R6）：
  ```python
  submit(job: JobSpec) -> JobHandle          # 立即返回，LLM 工作在后台线程/进程
  job_status(handle) -> JobStatus            # 含增量 output chunks、进度、终态、cost 累计
  job_result(handle) -> AskResult | QueryResult   # 终态后取完整 dataclass
  ```
- LLM 长任务（ask/query/digest/draft/ingest 进度）统一走任务通道；
  CLI 轮询打印进度，Web/API 层把 `job_status` 增量转 SSE 事件流
- 好处备案：CLI/Web/API 三形态共用同一进度协议；断线重连天然安全（按 handle 重订阅）；
  摄取进度（watch 已有 logs/ 进度）可收敛到同一机制
- 交付时点：任务通道随 **M3a**（service 完成期）落，M3b 的 SSE 只是薄适配

### R10 · 命名与呈现卫生 —— ✅ 已裁决

**主人裁决**：同意，全修。

**落地动作**：
1. 配置表 `max_llm_calls` 更名为 `CENHUA_MAX_LLM_CALLS`（env 名与 `CENHUA_*` 前缀规范
   对齐；`--max-llm-calls` 命令行参数保留现写法）
2. §2.2 标题改述：**"3 种用户形态（CLI / 技能 / 本地 Web UI）+ 1 附带局域网 API"**，
   图与文一致
3. §16 对外 API 离线端点 `GET /api/v1/graph` 加脚注"(v0.6 起，随 M4 交付；v0.5 返回 404
   + 版本提示)"

---

## 2. 修订后里程碑增量总览（仅本轮变化）

| 里程碑 | 版本 | 本轮新增/修正 |
|---|---|---|
| M1 | v0.2 | ＋ `bench` + QA30 题（R2）；＋ pricing.json + 换算 + ledger（R3）；契约登记制 + test_70/71 白名单（R6） |
| M2a | **v0.3.0** | 独立支线，只与主线并行不阻塞（R4）；＋ requirements 默认装 playwright + setup 装 chromium + doctor 检查（R7） |
| M2b | **v0.3.1** | 依赖修正：只依赖 M1（R4）；拒答门禁自本版本起生效（R2）；金额预估推广至全命令（R3） |
| M3a | v0.4 | ＋ 任务通道 submit/job_status/job_result（R9）；artifact 三元化落台账（R5） |
| M3b | v0.5 | SSE 只是任务通道的薄适配（R9）；API 端点版本脚注（R10） |
| M4 | v0.6 | 力导向图加 M3b 发布条件（R8）；graph API 404 处理（R10） |

**原则措辞修订**（design.md）：原则 10 降级为"**总结/NER 默认免费**"（R1）；
原则 11 扩展为三层 artifact 纪律（R5）。

---

## 3. 遗留事项

- [ ] roadmap.md 按本文档 + R1 评审修订（主人指示：本轮只落 review，修订另行执行）
- [ ] design.md 原则 10 措辞降级 + 原则 11 三层 artifact 增补
- [ ] `docs/service-contract.md` 建档（契约登记制的载体，M1 开工前置）
- [ ] QA 集 30 题冷启动（已并入 M1 交付物，遗留清单关闭）
- [ ] README 形态叙述同步（R1 评审遗留，仍待 roadmap 修订时一并处理）
- [ ] `max_llm_calls` → `CENHUA_MAX_LLM_CALLS` 迁移需兼容旧 env 名一个版本（deprecation warning）

---

## 4. 三轮拷问预告（不再阻塞，实施期自查项）

- M3a digest 的"全库扫描"成本模型：库到 1000 篇时 weekly digest 的单次花费估算与抽样策略
- `--include-derived` 打开后 LLM prompt 的组装规则细节（衍生正文到底进不进 prompt）
- 任务通道的持久化边界：Gateway/服务重启后未完成任务的续跑或标废策略

---

*评审：飞鸡 🦅 · 2026-10-13 · 裁决人：主人。与 R1 评审同为 roadmap 修订输入；本文档不含实现代码。*
