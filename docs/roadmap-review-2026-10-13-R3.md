# CENHUA Roadmap 三轮评审意见与决议（2026-10-13 R3）

> 对二修版 [roadmap.md](roadmap.md)（已吸收 [R1 评审](roadmap-review-2026-10-13.md) 与
> [R2 评审](roadmap-review-2026-10-13-R2.md) 全部裁决）的第三轮拷问：9 问（T1-T9）。
> 本轮核心发现：**两轮修复自身引入的次生伤**——原则 11 的封禁令杀死了 refine 的商业价值、
> QA 门禁跑在活语料上必然假回归、M1 在拆完 M3 后自己变巨石、依赖倒置与记账遗漏再现。
> 裁决方式说明：T1/T3 为主人显式拍板；T2、T4-T9 为补丁级方案，主人未持异议，按评审建议采纳。
> 本文档与 R1/R2 评审同为 roadmap 下次修订的输入，修订完成后可归档。

---

## 0. 三轮评审结论摘要

1. **价值闭环断裂**：精化总结被 internal-artifact 全量封禁 → 用户花钱生产的 LLM 总结
   没有任何消费者（T1，本轮灵魂拷问，与 R1 的"写入假免费"构成成本哲学的二次校准）
2. **门禁工程性缺陷**：QA 集绑活库 → 语料增长即假回归（T2）；门禁引用的校验器
   在 M4 才存在（T4，R3 同款依赖倒置复发）
3. **里程碑再失衡**：拆了 M3 的捆绑，M1 自己长出 8 个子系统（T3）
4. **领域错配**：企业图谱的统计阈值与预算策略直接套个人小库（T6/T7）；
   记账漏掉最大成本头（T5）
5. **环境与卫生**：WSL2 下 Playwright chromium 缺系统库必崩（T9）；租户残肢三处（T8）

---

## 1. 裁决记录（T1-T9）

### T1 · refine 产品没有消费者——原则 11 杀死了原则 10 的钱包 —— ✅ 主人裁决：方案 A

**问题**：`refine` 花预算产出 LLM 精化总结，落盘为 `internal-artifact`；而该类别纪律是
"永不出现在用户可见引文 + LLM prompt 禁止引用其正文"。精化总结既不能进 prompt、不能作
引文、related 也不消费其正文——整套预算硬闸/精化队列/攒批机制沦为**花钱生产没人看的文件**，
`CENHUA_REFINE_BUDGET_CNY` 无从向用户解释。

**主人裁决**：**方案 A · hint-not-evidence**。

**落地动作**：
- internal-artifact 纪律改写为角色规则（design.md 原则 11 增补 + §5.3 + §15.2）：
  > internal-artifact 正文**禁止作为事实证据进入引文**（not-evidence）；
  > 精化总结**可作为导航提示（hint 角色）进入 LLM prompt**——形如
  > `【提示，非证据】该文档主旨为 X，重点段落 P12-15`；
  > 基于 hint 得出的任何结论，其证据必须从 primary 正文**重新验证**后引用。
- prompt 组装规则明确两段式：hint（summaries）负责"去哪里看"，证据（primary 文本层）
  负责"是什么"；hint 注入段带显式 `[HINT tier=internal]` 标记，与证据段隔离
- digest/draft 引文穿透规则不变（穿透 internal 直达 primary 页码）
- 攒批折扣等 refine 机制**保留**——消费者问题已解，不再砍复杂度
- 备案：hint 进 prompt 引入"LLM 摘要转述未信任文档"的注入面，见 §4 三轮预告第 1 条，实施期处理

### T2 · QA 门禁跑活库——语料增长必然"假回归" —— ✅ 按评审建议采纳

**问题**：`meta/qa/benchmark.jsonl` 按 vault 存放、"回归即阻断发版"。用户库是活的：
新增一份合同，昨天某道拒答题（"语料里没有 X"）今天就成立——正确答案变了、代码未变、
门禁红了。拿用户正常投喂当发版事故。且 `bench` 未在 §16 离线/LLM 分类清单中登记。

**落地动作**：
- `cenhua bench` 默认跑**随包分发的冻结 fixture 语料**：内置 ~30 份合成文档 + 30 题
  （存在性 15 + 溯源 10 + 拒答 5），全环境可复现，此结果才是**阻断级门禁**
- 用户库 QA 集降级为**报告模式**（`cenhua bench --corpus`，只打印不阻断）；
  每题带 `corpus_hash`，语料变更时自动标"题目过期（需重验答案）"，不计失败
- §16 分类清单补 `bench` 行：fixture 模式离线可跑（存在性+溯源题），拒答题需 LLM
- fixture 语料设计进 M1a 交付物（与 bench 同格）

### T3 · M1 巨石化——Q7 的病从 M3 切了，在 M1 复发 —— ✅ 主人确认拆法

**问题**：M1 交付物清点 ≈ 8 个子系统（deferred 总结、refine 队列、四层降噪、cost-ledger、
`cost`、pricing.json+换算+校准、`bench`+QA30、service-contract+搬迁+test_70/71）。
一轮评审以捆绑过多拆了 M3，同一把刀没落在 M1。

**主人裁决**：**确认拆法 M1a / M1b**。

**落地动作**：
- **M1a · v0.2.0 · 成本与质量基础设施**（纯基础设施，不碰编织逻辑，可先行）：
  - `pricing.json` + token 估算/换算函数 + `cost-ledger.jsonl` + `cenhua cost` + 预估校准闭环
  - `cenhua bench` + 内置 fixture 语料（30 文档 + 30 题，吸收 T2/T4）
  - service 原语 `verify_citation(doc, page)`（吸收 T4）
  - `docs/service-contract.md` 建档（M1a 首个 commit：建档并登记本里程碑全部新函数）
- **M1b · v0.2.1 · 编织**：deferred 总结 + refine 队列（复用 M1a 换算）+ 四层降噪关联
  （含 T6 小库模式）+ `related`/`summarize` 迁入 service（白名单首批）
- 依赖：**M1b → M1a**（仅换算函数与 verify_citation 两处）；M2a 与 M1 支线并行，互不阻塞

### T4 · 引文校验器依赖倒置（门禁引用 M4 的 `draft --verify`） —— ✅ 按评审建议采纳

**问题**：M1 门禁"引文准确率 ≥95%，经 `draft --verify` 同源校验器验证"——`draft` 是 M4
交付物。R3 刚修完"预算闸依赖 M2b pricing"，门禁又引用 M4 工具，依赖倒置第三次出现。

**落地动作**：
- service 原语 **`verify_citation(doc, page)` 提前进 M1a**（本质为查文本层该页存在，
  不依赖草稿系统）
- M4 的 `cenhua draft --verify` 改为**反向包装**该原语；门禁与草稿共用同一校验实现，
  单一事实源

### T5 · ledger 漏记 add——`cost` 汇总系统性低报 —— ✅ 按评审建议采纳

**问题**：R1 裁决"树索引不设预算拒执"（正确：预算中途拒执会留半成品库），但文档未区分
**免闸**与**免记账**。`add` 的 LLM 调用若不写 ledger，`cenhua cost` 月报恰好漏掉占比最大的
树索引成本——用户见账 3 元、实烧 30 元。原则 10 要求树索引成本"明示"，账本却装看不见。

**落地动作**：
- ledger 规则一句话定死：**"全量记账，仅免预算闸"**——所有 LLM 调用（含 `add` 树索引、
  OCR 视觉兜底）一律写 `cost-ledger.jsonl`；`CENHUA_MAX_COST_CNY` 预算闸豁免 `add`
- §14 配置表 `CENHUA_MAX_COST_CNY` 行加注："不适用 add/watch（摄取无预算拒执，防半成品库）"
- `cenhua cost` 输出按命令分组（ingest / ask / query / refine / digest…），摄取成本单列首位

### T6 · 四层降噪的统计学在个人小库坍塌 —— ✅ 按评审建议采纳

**问题**：产品定位个人库（N≈30~300）。N=50 时 `df>N×0.30` 即 16 份文档的实体全判枢纽；
nPMI 小样本高噪声；再叠共现地板——三层筛后 `related` 常年空转，"关联为空是信息"退化为
"功能常年沉默"。企业图谱阈值直接套个人语料的领域错配。

**落地动作**：
- **小库模式自动降档**（`cenhua hub` 显示当前档位与 N）：

  | 参数 | 标准档（N≥200） | 小库档（N<200） |
  |---|---|---|
  | 枢纽判定 | df > N×0.30 | df > N×0.50 |
  | 共现地板 | \|D_A∩D_B\| ≥ 2 | ≥ 1 |
  | nPMI | 原始值 | +Laplace 平滑 |
  | 每文档关联截断 | Top-8 | Top-8（不变） |

- 只改参数表不改架构；降档触发阈值 `CENHUA_SMALL_CORPUS_N`（默认 200）可配

### T7 · digest/draft 中途预算停 = 半成品文章 —— ✅ 按评审建议采纳

**问题**：R1 豁免 add 的理由（中途拒执留半成品，风险大于收益）对 digest/draft 同样成立：
全库扫描长生成停在第 7 节就是断头洞察。文档对 add 想了这层，对 digest/draft 只字未提，
逻辑不自洽。

**落地动作**：
- digest/draft 改 **all-or-nothing**：启动前强制 dry-run 估价 → 超预算**拒绝启动**
  （绝不中途停）→ `--force` 或 `--max-cost` 显式放行
- 独立默认预算：`CENHUA_LONGJOB_MAX_COST_CNY`（默认 5.0，适用于 digest/draft），
  与单命令默认 2.0 分离；§14 配置表新增该行
- 断点续跑不做（M4 前），失败重跑从头估价——长任务幂等由 `rid` 记录保证可审计

### T8 · R10 同类卫生残留三处 —— ✅ 按评审建议采纳

**落地动作**：
1. §6.5 API 清单 `POST /api/v1/draft` 加版本脚注"(v0.6 起，随 M4 交付；v0.5 返回 404 +
   版本提示)"——与 graph 端点同款处理
2. **删除企业租户残肢**：§9 "`X-Agent-Id` → 用户映射 → 行级过滤"整条移除；
   `CENHUA_API_ALLOWED_AGENTS` 降级合并为单 token（`CENHUA_API_TOKEN`）局域网白名单模式，
   **fail-closed 原则保留**；`user_mapping.json` 相关叙述全部清除（与 Q1 形态收敛对齐）
3. 契约时序写明：**M1a 首个 commit = `docs/service-contract.md` 建档并登记本里程碑全部
   新函数**，杜绝"先实现后登记"窗口期

### T9 · WSL2 下 Playwright chromium 缺系统库必崩 —— ✅ 按评审建议采纳

**问题**：`playwright install chromium` 只下载浏览器二进制，运行还依赖系统库
（libnss3、libatk 等，apt 范畴）；非 root 的 setup 补不齐。孵化机正是 WSL2——M2a 落地后
`--url` 首用即崩。

**落地动作**：
- `cenhua setup` 的 chromium 安装步骤升级：有 root/sudo 时执行
  `playwright install --with-deps chromium`；无权限时退回 `playwright install chromium`
  并**明确警告**系统库未装
- `cenhua doctor` 新增**启动自检**项：spawn chromium 无头加载 `about:blank`（超时 15s），
  失败标 PROBLEM 并输出精确修复命令 `sudo playwright install-deps chromium`
- §4.3 安装负担段补充：系统库依赖属发行版包管理范畴，体积另计 ~100-200MB；
  自检失败时 `--url` 自动降级静态 HTML 抓取（§4.3 既有降级约束，行为闭环）

---

## 2. 修订后里程碑增量总览（仅本轮变化）

| 里程碑 | 版本 | 本轮新增/修正 |
|---|---|---|
| **M1a**（新拆） | v0.2.0 | pricing + 换算 + ledger（**全量记账含 add**，T5）+ cost + 校准 + bench + **内置 fixture 语料**（T2/T3）+ `verify_citation` 原语（T4）+ service-contract 建档（T8.3） |
| **M1b**（新拆） | v0.2.1 | deferred 总结 + refine（**hint 角色规则**，T1）+ 四层降噪（**小库模式**，T6）+ related 入 service；依赖 M1a |
| M2a | v0.3.0 | setup `--with-deps` + doctor chromium 启动自检（T9） |
| M2b | v0.3.1 | 拒答门禁改跑 fixture（T2）；用户库 QA 报告模式上线 |
| M3a | v0.4 | hint 两段式 prompt 组装规则落地（T1）；ledger 摄取成本单列（T5） |
| M3b | v0.5 | API 清单删行级过滤残肢（T8.2）；draft/graph 端点 404 脚注（T8.1） |
| M4 | v0.6 | digest/draft **all-or-nothing + 独立预算**（T7）；`draft --verify` 反向包装 verify_citation（T4） |

**配置表增量**：`CENHUA_SMALL_CORPUS_N`（默认 200）、`CENHUA_LONGJOB_MAX_COST_CNY`（默认 5.0）、
`CENHUA_MAX_COST_CNY` 加注豁免 add、`CENHUA_API_ALLOWED_AGENTS` 删除并入单 token。

**design.md 同步**：原则 10 增补"全量记账仅免闸"；原则 11 增补 **hint-not-evidence** 角色规则。

---

## 3. 遗留事项

- [ ] roadmap.md 按 R1+R2+R3 三份评审修订（主人指示：本轮仍只落 review）
- [ ] design.md：原则 10/11 增补（T1 hint、T5 记账）
- [ ] `docs/service-contract.md` 建档（M1a 首 commit，T8.3 已定序）
- [ ] fixture 语料设计：30 份合成文档 + 30 题（M1a 交付物，T2）
- [ ] README 形态叙述同步（R1 遗留，仍未关闭）
- [x] ~~QA 集 30 题冷启动（用户库）~~ → 改为 fixture 语料进 M1a，用户库 QA 降报告模式（T2 关闭原项）

---

## 4. 四轮拷问预告（实施期自查项，不再阻塞发版）

- **hint 的注入面**：精化总结本身是 LLM 对未信任文档的转述，进 prompt 后成为注入载体；
  实施时需对 hint 段做指令剥离（prompt 中 hint 只许陈述、不许祈使）并在 fixture 里加注入对抗题
- **hint 的二段验证成本**：hint-not-evidence 意味着"看提示→回原件验证"，验证轮次的
  token 开销要计入 refine 的 ROI 账（hint 省下的是导航成本，不能倒贴验证成本）
- **fixture 绿 ≠ 用户库好**：报告模式需要告警阈值（用户库引文准确率连续下滑时主动提示
  重新出题），否则报告模式等于没人看的报告
- 任务通道持久化边界（R2 预告遗留）：重启后未完成任务的续跑或标废策略

---

*评审：飞鸡 🦅 · 2026-10-13 · 裁决人：主人（T1 选方案 A、T3 确认 M1a/M1b 拆法；
T2/T4-T9 按评审建议采纳）。与 R1/R2 评审同为 roadmap 修订输入；本文档不含实现代码。*
