# CENHUA 方案文档（Design）

> 岑华：出自《山海经》，昆仑古木，观时序、记万象。CENHUA 以此为名，做个人
> 智能体的"第二大脑"——本地知识库。

本文档记录 CENHUA 的产品定位、设计原则、范围与关键决策，是后续技术架构、
使用手册与避坑指南的纲领。

## 1. 背景与目标

个人智能体（OpenClaw、Hermes 等）需要一个**本地、可验证、低成本**的知识库，
用来回答"我的文件里有什么、在哪一页、怎么理解"。市面上的 RAG 方案要么依赖
云端、要么索引不可信、要么成本不可控。

CENHUA 的目标：

- **一个 CLI**：`cenhua`，任何能跑 shell 的智能体都能调用。
- **本地优先**：文档在本地索引，端点由用户自选（云端或本地 Ollama/vLLM）。
- **可验证**：每条回答带 `[doc P页]` 引文，指向存档原件。
- **低成本**：存在性检索用本地 grep（免费、毫秒级），大模型只用于"理解"。
- **零云锁定**：任何 OpenAI 兼容端点即可。

## 2. 设计原则

### 2.1 grep 管存在，LLM 管意义

这是 CENHUA 的第一原则：

- **`find` 管存在**："X 出现在哪 / 哪一页 / 我的语料是否提到 Y"——本地正则
  扫文本层，毫秒级、免费、精确、完整。绝不用 LLM 回答存在性问题（它会静默漏掉）。
- **`ask` 管意义**：总结、刻画、跨页推理——才用 LLM。

### 2.2 引擎保持上游纯净

CENHUA 内嵌一份 **pageindex-rag** 引擎（`scripts/engine/`），**字节级保持与
上游一致**，以便 diff 和升级。所有集成都在 m 层（`m_lib.py` 等）通过
subprocess + `PI_*` 环境变量完成，**绝不修改引擎模块**。测试 `test_61` 守护
这一点。

### 2.3 密钥永不落盘

API 密钥只存在于环境变量或用户显式选择的网关引用中。`vault.yaml` 拒绝存储
密钥；OpenClaw 网关在调用时从 `~/.openclaw/openclaw.json` **实时解析**，一次
轮换全局生效。

### 2.4 安装时两问，绝不静默

安装时有两个决策必须由用户确认，智能体不可代答：

1. **LLM 网关**：复用 OpenClaw 配置，还是自填 `PI_BASE/PI_KEY`（退出码 5）。
2. **知识库存储位置**：默认 `~/.cenhua`，还是安装目录（退出码 6）。

### 2.5 本地 OCR 优先，大模型兜底

图片与扫描件转写：**RapidOCR 本地识别优先**（免费、离线），并做**识别效果
校验**（置信度 + 文本量阈值）；不达标或 RapidOCR 缺失时，才回退到视觉大模型。
本地 OCR 只能让摄取更省，绝不因它失败而中断摄取。

### 2.6 全量记账，仅免预算闸（M1a 起）

成本哲学（roadmap §6.4 + R3-T5 + R4-F1）：

- **全量记账**：所有 LLM 调用（含 `add` 树索引、OCR 视觉兜底）一律写
  `cost-ledger.jsonl`，`cenhua cost` 按命令分组汇总，**摄取成本单列首位**。
  用户见账必须等于实烧，杜绝"见账 3 元、实烧 30 元"。
- **仅免预算闸**：`CENHUA_MAX_COST_CNY`/`CENHUA_MAX_LLM_CALLS` 预算闸**不适用
  `add`/`watch`**（摄取无预算拒执，防半成品库）；**长任务（digest/draft）与
  批量任务（`refine --drain`）豁免中途执法**，仅受各自预算启动前 all-or-nothing
  检查管辖（F1）。
- **预估校准闭环**：预估偏差 >3x 告警，防单价表过期。
- **单价表** `pricing.json`（随包分发，可覆盖）：model → {in, out, currency}；
  OpenClaw 全名匹配规则（F9）：全名 → 裸 id → 保守默认价；混合货币不强行折算。

### 2.7 原则 11：hint-not-evidence（v0.3.3 · M2b 起生效，F2+F3）

三层 artifact（防引文洗白）：**primary**（原件，唯一证据来源）/
**derived-doc**（digest/draft/周报：默认检索降级，`--include-derived` 显式开启，
引文必须沿 `derived_from` 穿透直达 primary 原件页码）/
**internal-artifact**（summaries 总结/NER：正文永不进引文）。

prompt 两段式（`cenhua_service/prompt.py` 装配）：

- **hint 段**：refined summaries，标 `[HINT tier=internal]`，只回答"去哪里看"；
  **只许陈述、不许祈使**——装配时逐句消毒（中文祈使特征 + 英文
  prompt-injection 形态命中即整句剔除），首发即硬规则化，M3a 增量为注入对抗
  硬化（fixture 对抗题），不是机制首发。
- **证据段**：仅 primary 文本层，标 `[EVIDENCE tier=primary]`，回答"是什么"；
  禁止引用 internal-artifact / derived-doc 正文作为事实证据。
- **snippet 强制**（F2）：citations schema 强制 `{doc, page, snippet}`，
  snippet 必须逐字摘录该页原文；无 snippet / 归一化校验
  （`verify_citation` 三参原语）失败 → 该结论按 `[未溯源·LLM 推断]` 降级，
  门禁计为失败。
- **基于 hint 的结论必须回到 primary 正文重新验证后引用**；证据段不足以
  回答时如实拒答（沉默不是证据，编造更不是）。
- **注入对抗硬化**（v0.4.0 · M3a 起）：消毒正则覆盖中英 prompt-injection
  形态（"忽略…指令"/"你现在是"/"system prompt" 等），fixture 注入对抗题
  ≥1/3 人工撰写（`author:"human"`，防出题方与攻击方同源盲区）并进 bench
  **离线阻断集**（消毒零残留 + 事实零误伤，任一失败不发版）；hint 二段验证
  的 token 开销计入 refine ROI 账（`refine.roi_lines`，验证成本倒贴生产
  成本时重新评估 hint 段价值）。
- **执法豁免边界**：两段式管辖 ask/query/digest/draft 的 prompt 组装；
  `refine` 自身的精化 prompt 不在管辖内（其输入本就是 internal-artifact
  的规则层粗提取，产出的 refined 字段才是 hint 原料）。

## 3. 范围

### P0–P2（当前版本 0.1.0，最小可用）

- 多库（vault）管理：按项目/领域分库，保留默认位置。
- 摄取闭环：inbox 投放 → 去重 → 索引 → 自动建文本层。
- 检索闭环：`find`（存在）/ `ask`（意义）/ `read`（原文核验）。
- 成本护栏：`ask --dry-run` 估算调用数，`max_llm_calls` 上限。
- 统一溯源引文：每条命中带 `[doc P页]` + `Source:` 行。
- 向量语义层（可选）：`seek`，可优雅降级。
- 本地 OCR：RapidOCR 优先 + 视觉兜底。

### 后续（未实现）

- P3：笔记 / 标签 / 知识图谱。
- P4：草稿（draft）。
- Web/CLI 之外的 UI。

## 4. 关键决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 引擎集成 | 独立内嵌，不依赖外部 | 自包含、可 diff、可升级 |
| 语义层 | 引入向量（可选） | 覆盖"换种说法"的召回，可降级 |
| SKILL.md 语言 | 英文 + 中文辅助文件 | 面向国际社区，中文辅助 |
| 存储位置 | 默认 `~/.cenhua`，可迁移 | 数据生命周期长于技能安装 |
| 图片/扫描转写 | RapidOCR 本地优先 + 视觉兜底 | 免费离线，质量校验保证可信 |
| 提交身份 | Hugh Han（noreply 邮箱） | 关联 GitHub 账号 |

## 5. 验收标准

- 端到端：`openclaw skills install git:github.com/world327/cenhua` → `✓ Ready`，
  安装路径直接可跑 `cenhua 0.1.0`。
- 两问协议实测：真实 openclaw.json 下正确触发退出码 5/6。
- 离线检索：`find`/`read`/`status`/`doctor` 无需 LLM。
- 本地 OCR：清晰图片本地识别，低质量图片触发视觉兜底。
- 测试：34 单测 + 14 OCR 单测 + formats + smoke 全绿。
