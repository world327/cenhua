# CENHUA Roadmap 四轮评审意见与决议（2026-10-13 R4）

> 对三修版 [roadmap.md](roadmap.md)（已吸收 [R1](roadmap-review-2026-10-13.md) /
> [R2](roadmap-review-2026-10-13-R2.md) / [R3](roadmap-review-2026-10-13-R3.md) 三轮评审
> 全部裁决）的第四轮拷问：11 问（F1-F11）。
> 本轮核心发现：**前三轮修复自身在时间轴与执法轴上复活的病灶**——T7 只修了启动豁免没修
> 中途执法、T1 修了消费语义没修消费排期、我自己上轮设计的 verify_citation 是同义反复校验。
> 裁决方式说明：F1/F3 为主人显式拍板；F2、F4-F11 为补丁级方案，主人未持异议，按评审建议采纳。
> 本文档与 R1/R2/R3 评审同为 roadmap 下次修订的输入，修订完成后可归档。

---

## 0. 四轮评审结论摘要

1. **执法轴漏洞**：T7 的 all-or-nothing 只管了长任务预算（5.0），单命令预算（2.0）与
   次数上限（8）仍在中途腰斩 digest——断头洞察未根治（F1）
2. **质量门禁是纸老虎**：`verify_citation` 只验"页存在"不验"内容对"，≥95% 引文准确率
   形同虚设（F2）；10 题样本上跑 ≥95% 阈值是掷硬币（F7）；fixture 的构建成本、离线成立性、
   非确定性治理三处未定义（F6）
3. **排期复活病**：refine 在 v0.2.1→v0.4 之间没有消费者——T1 语义修复被版本时间轴绕过（F3）；
   M3b 画 M4 的草稿饼（F4）；§4.4 双份承诺（F5）
4. **租户时代残肢与呈现错位**：Nginx/open_id/货币/白名单/矩阵八处卫生项（F8-F11）

---

## 1. 裁决记录（F1-F11）

### F1 · 长任务被单命令预算与次数上限中途腰斩 —— ✅ 主人裁决：同意

**问题**：T7 只豁免了 `CENHUA_LONGJOB_MAX_COST_CNY` 这一轴。§6.4 明文 `CENHUA_MAX_COST_CNY`
(2.0) 与 `CENHUA_MAX_LLM_CALLS` (8) "并联，先到先停"，豁免名单只有 `add/watch`。推演：
digest 预估 ¥4.5 ≤ 5.0 放行启动 → 跑到 ¥2.0 单命令上限先到先停 → 断头洞察。次数轴更糟：
全库扫描 digest 动辄 30+ 调用，8 次上限必拦腰斩。`refine --drain` 批量同病，三闸执法顺序全文未定义。

**主人裁决**：**同意**——长任务与批量任务豁免中途执法。

**落地动作**：
- 规则一句话写死（§6.4 + §14 + §8 标准 6 三处同步）：
  > **长任务（digest/draft）与批量任务（`refine --drain`）豁免 `CENHUA_MAX_COST_CNY` 与
  > `CENHUA_MAX_LLM_CALLS` 的中途执法；仅受各自预算（`CENHUA_LONGJOB_MAX_COST_CNY` /
  > `CENHUA_REFINE_BUDGET_CNY`）的启动前 all-or-nothing 检查管辖。**
- 三闸执法顺序表（启动前依次检查，任一超即拒启）：
  ① dry-run 估价 → ② 对应任务预算（longjob/refine）→ ③ `--force`/`--max-cost` 放行通道
- 中途执法唯一保留项：硬件级异常（网关连续失败）走既有 try/except 降级，标 FAILED 不落半成品

### F2 · `verify_citation` 是重言式校验，引文准确率门禁形同虚设 —— ✅ 按评审建议采纳

**问题**：T4 定义的校验"本质为查文本层该页存在"——**引用一个存在但内容错误的页照样通过**。
幻觉引文只要页码在文档范围内即判"真"，门禁数字好看但无意义（同义反复当质量指标）。

**落地动作**：
- citations dataclass 契约升级：新增 `snippet` 字段（≤80 字锚文本，从命中页摘取）
- 原语签名升级：`verify_citation(doc, page, snippet) -> bool`——校验**该 snippet 归一化后
  确实存在于该页文本层**（NFKC 归一 + 去空白/全半角折叠后正则匹配）
- M4 `draft --verify` 与 M1a bench 门禁共用升级后原语（单一事实源不变）
- 契约登记：M1a 首 commit 建档时 `schema_version` 即含 snippet 字段（无历史兼容负担）
- LLM 输出格式约束：ask/query 响应 schema 强制 citations 带 snippet（无 snippet 的引文
  在门禁计为失败，倒逼 prompt 输出规范）

### F3 · refine 消费者缺口在版本时间轴上复活 —— ✅ 主人裁决：方案①，hint 两段式提前进 M2b

**问题**：M1b（v0.2.1）交付 refine 计费机制，hint 消费（两段式 prompt）却排在 M3a（v0.4）。
中间横跨 M2b 全程：用户设了预算、花了钱、summaries 变 refined——没有任何东西消费它。
T1 靠语义修复的缺口，靠排期又复活了。

**主人裁决**：**hint 两段式提前进 M2b query。**

**落地动作**：
- M2b（v0.3.1）交付物增补：`query` 的 prompt 组装采用**两段式 hint-not-evidence**
  （hint 段注入 refined summaries，标 `[HINT tier=internal]`；证据段仅从 primary 文本层取）
- M3a 交付物中该项改为：**注入对抗硬化**（hint 段指令剥离、只许陈述不许祈使、
  fixture 注入对抗题），不再是 hint 机制本身的首发
- §5.3 refine 价值叙述补一句："hint 消费自 v0.3.1 起生效"——预算设置与用户可见价值同版本出现
- M1b→M2b 依赖链已有（M2b 依赖 M1），无新增依赖

### F4 · M3b Web UI 承诺 M4 才有的草稿编辑 —— ✅ 按评审建议采纳

**问题**：§3.3 功能表、§2.3 矩阵（Web×创造=v0.5）、M3b 交付物三处写"草稿在线编辑
（带引文悬浮）/版本对比"，而 `cenhua draft` 在 v0.6。graph 端点记得加 404 脚注，Web 页面
却先画不存在的饼（同款错误反向再犯）。

**落地动作**：
- M3b（v0.5）创造模块收敛为：**洞察浏览**（digest 只读）
- 草稿编辑 / 引文悬浮 / 版本对比三行移入 M4（v0.6）交付物
- §2.3 矩阵"④创造 × Web UI"拆两格：📋 v0.5（洞察浏览）→ 📋 v0.6（草稿编辑）

### F5 · §4.4 离线增强在 M1b 与 M2a 双份承诺 —— ✅ 按评审建议采纳

**问题**：M1b 交付物含"§4.4 离线增强（邮件/watch 强化）"，M2a 交付物逐字重复同一行。
两处发布各自以为对方做了，或同一功能计两次工时。

**落地动作**：
- §4.4 **归 M1b**（watch 强化服务本地摄取主路径；邮件 eml/msg 与网页摄取无耦合，
  先做不欠账）
- M2a 交付物删除该行，只保留 §4.3 网页收录本体

### F6 · fixture 门禁三处工程矛盾 —— ✅ 按评审建议采纳

**问题**：① fixture 若随包只发原始文档，bench 建索引要烧 LLM，"离线可跑"当场破产；
② "全套测试离线绿"与"拒答门禁阻断（需 API key）"冲突；③ LLM 拒答题非确定性 + 阻断级
门禁 = 偶发红。

**落地动作**（三句补丁进 §8 标准 7）：
1. **fixture 是冻结产物**：随包分发已建好的 `tree index + 文本层 + 30 题 QA`（合成语料
   源文件一并打包供审计，但 bench 不重建索引）；`bench` 的存在性+溯源子集零 LLM 零网络
2. **门禁分层**：
   - CI 层（`tests/run_tests.sh`）：fixture 存在性 + 溯源题，**离线阻断**
   - 发版流水线：全量 fixture（含拒答，需 API key），**发版阻断**；无 key 环境发版跳过
     拒答集并在 release notes 标注
3. **拒答题非确定性治理**：temperature=0 + 失败重试 1 次；同一题连续 2 个版本 flaky →
   自动转人工仲裁（进 `meta/qa/flaky.jsonl`），不连续阻断发版

### F7 · 门禁统计粒度：n=10 的 ≥95% 是掷硬币阈值 —— ✅ 按评审建议采纳

**问题**：溯源题 10 道、按题计量，1 错 = 90% < 95% 直接阻断——1 对一错摆动 10pp，
门禁在噪声上跳舞。

**落地动作**：
- 引文准确率**按引文条目计量**：每题挂多个引用点，全量条目 ≥20；阈值按条目占比 ≥95%
  （n≥20 时 1 条失败 ≈ 5pp，可容忍且有信号）
- 存在性召回维持 100% 零容忍（铁律"沉默不是证据"的直接度量，不因统计粒度让步）
- 失败处置：bench 输出逐条 diff 清单（题目、期望、实际、命中页、snippet 匹配详情）供归因

### F8 · 部署约束残留租户时代器官 —— ✅ 按评审建议采纳

**落地动作**：
- "AI 超时按推理时间设（Nginx 300s）"→ 产品无组件反代，改为 "uvicorn `timeout_keep_alive`
  与请求级 timeout 按推理时长设置"；Nginx 仅作为可选部署附件在 user-guide 提一句
- 日志脱敏示例 "open_id 截断" → 泛化为 "token / 绝对路径 / PI_KEY 前缀脱敏"（产品内无飞书概念）

### F9 · 定价货币与网关匹配路径未定义 —— ✅ 按评审建议采纳

**落地动作**：
- `pricing.json` schema 增 `currency` 字段（per-model），`cenhua cost`/dry-run 输出按
  各模型自身货币显示，混合货币时不强行折算（显示 `¥0.35 + $0.02`，加汇率提示脚注）
- OpenClaw 网关主路径（`openclaw:provider/model` 全名）的单价匹配规则写明：
  先按全名精确匹配 → 再按裸 model id 匹配 → 未命中用保守默认价 + 输出标注
  "估价：未配置单价（provider/model）"

### F10 · test_71 白名单与 digest 事件触发两处小错位 —— ✅ 按评审建议采纳

**落地动作**：
- `test_71_cli_is_thin` 白名单只收**用户命令**（related / refine / cost / bench /
  query / digest / draft…）；`summarize` 不是用户命令（无 CLI 面），移出白名单概念，
  其 service 函数由 test_70（禁 print）管辖即可
- digest"事件触发：摄取量超阈值自动建议"——产品无守护进程与通知通道，改为：
  **watch 累计摄取 N 篇（默认 20）后在进度日志打印一行提示**
  `提示：自上次洞察以来已摄取 N 篇，可运行 cenhua digest --dry-run 估价`；
  无任何自动触发执行

### F11 · §2.3 矩阵现状语义倒退 —— ✅ 按评审建议采纳

**落地动作**："②编织 × CLI/技能"恢复 `✅(半) + 📋 v0.2` 双标——vault 分库、树索引、
引文溯源、向量层均已在 v0.1 交付（§5.2 现状半成为事实），纯 📋 否定了已交付能力。

---

## 2. 修订后里程碑增量总览（仅本轮变化）

| 里程碑 | 版本 | 本轮新增/修正 |
|---|---|---|
| M1a | v0.2.0 | `verify_citation` 升级页内 snippet 匹配（F2）；fixture=冻结产物随包分发（F6.1）；CI/发版门禁分层（F6.2）；引文按条目计量（F7）；test_71 白名单去 summarize（F10） |
| M1b | v0.2.1 | 承接 §4.4 离线增强唯一归属（F5）；refine 价值叙述补"hint 自 v0.3.1 生效"（F3） |
| M2a | v0.3.0 | 交付物删除 §4.4 重复行（F5） |
| M2b | v0.3.1 | ★ 交付物增补：query 两段式 hint-not-evidence prompt 组装（F3，主人裁决）；发版流水线含拒答集（F6.2） |
| M3a | v0.4 | hint 项语义改为"注入对抗硬化"（F3）；三闸执法顺序表（F1） |
| M3b | v0.5 | 创造模块收敛为洞察浏览；草稿编辑/版本对比移 M4（F4）；矩阵拆格（F4/F11） |
| M4 | v0.6 | 接收 Web 草稿编辑三件套（F4）；`draft --verify` 包装升级后的 verify_citation（F2） |

**全局文字同步**：§6.4/§14/§8 三处写死长任务/批量任务中途执法豁免（F1）；§9 部署约束
去 Nginx/open_id（F8）；§14 pricing 货币字段与 OpenClaw 网关匹配规则（F9）；digest 事件
触发改 watch 打印提示（F10）。

---

## 3. 遗留事项

- [ ] roadmap.md 按 R1+R2+R3+R4 四份评审修订（主人指示：本轮仍只落 review）
- [ ] design.md：原则 11 增补 hint-not-evidence 完整规则（F2 snippet 强制、F3 生效版本、
  执法豁免边界）
- [ ] `docs/service-contract.md` 建档时直接采用升级后契约（citations 含 snippet、
  verify_citation 三参签名、schema_version）
- [ ] fixture 冻结产物制作流程（合成语料 → 建索引 → 冻结打包，M1a 交付物内完成）
- [ ] pricing.json `currency` 字段与 OpenClaw 全名匹配规则落 M1a
- [ ] README 形态叙述同步（R1 遗留，仍未关闭，随 roadmap 修订一并处理）

---

## 4. 五轮拷问预告（实施期自查项，不再阻塞发版）

- **snippet 摘取的诚实性**：snippet 由 LLM 摘录——LLM 可能摘错页的文本（snippet 与页码
  同源于幻觉）；verify 只证"该句在该页"，不证"该句支撑该结论"。引文准确率的诚实上限
  是**逐字可溯率**，文档措辞不得升格为"语义正确率"
- **hint 注入对抗题的出题权**：fixture 注入对抗题若也由 LLM 生成，存在出题方与攻击方
  同源盲区；至少 1/3 对抗题人工撰写
- **冻结 fixture 与引擎升级的断裂**：tree index 格式随 pageindex 引擎升级可能不兼容，
  fixture 需绑定 `engine_version` 并提供 `bench --rebuild`（显式重建，烧 LLM 需确认）
- 任务通道持久化边界（R2/R3 连续两轮预告未关闭）：重启后未完成任务续跑或标废，
  本轮仍无裁决——**M3a 开工前必须拍板，不得再顺延**

---

*评审：飞鸡 🦅 · 2026-10-13 · 裁决人：主人（F1 同意豁免中途执法、F3 选方案①hint 提前进
M2b；F2/F4-F11 按评审建议采纳）。与 R1/R2/R3 评审同为 roadmap 修订输入；本文档不含实现代码。*
