# CENHUA 项目规划（Roadmap）

> 岑华：以"收录—编织—检索—创造"四大模块为骨架、以"CLI / 智能体技能 / 本地
> Web UI"三种形态为外壳，打造**个人知识库（第二大脑）**。本文档统领项目演进
> 路线，是 design.md（设计原则）、architecture.md（技术架构）、user-guide.md
> （使用手册）的纲领性上层文档。
>
> 修订历史：
> - 2026-10-13 一轮：按 [R1 评审](roadmap-review-2026-10-13.md) 11 项裁决全面修订
>   （定位收敛个人、形态 5→3、里程碑 6→7 拆分、删除公网搜索页、新增写入默认免费/
>   衍生不冒充事实两原则、清除 `file:///` 私链、统一 v0.x 版本记号）。
> - 2026-10-13 二轮：按 [R2 评审](roadmap-review-2026-10-13-R2.md) 10 项裁决修订：
>   原则 10 措辞降级、原则 11 扩展为三层 artifact、M1 加 bench/pricing/契约登记制、
>   M2a/M2b 版本号分离与依赖修正、Playwright 默认安装、M3a 引入任务通道、M3b SSE
>   退为薄适配、M4 力导向图加 M3b 发布条件、`max_llm_calls` → `CENHUA_MAX_LLM_CALLS`。
> - 2026-10-13 三轮：按 [R3 评审](roadmap-review-2026-10-13-R3.md) 9 项裁决修订
>   （修 R1/R2 次生伤）：原则 11 改 hint-not-evidence 角色规则（T1）；QA 改跑 fixture
>   冻结语料（T2）；M1 拆 M1a/M1b（T3）；`verify_citation` 原语进 M1a（T4）；
>   ledger 全量记账仅免闸（T5）；四层降噪小库模式自动降档（T6）；digest/draft
>   all-or-nothing + 独立长任务预算（T7）；租户残肢清除（T8）；WSL2 chromium
>   系统库对策（T9）。
> - 2026-10-13 四轮：按 [R4 评审](roadmap-review-2026-10-13-R4.md) 11 项裁决（F1-F11）
>   修订——修前三轮在时间轴与执法轴复活的病灶：**长任务/批量任务豁免中途执法**
>   （F1，治 T7 只修启动豁免的腰斩）；`verify_citation` 升级 snippet 页内匹配
>   （F2，治 T4 同义反复校验）；**hint 两段式提前进 M2b**（F3，主人裁决，治 T1
>   语义修复被版本排期绕过）；M3b 创造模块收敛为洞察浏览、草稿编辑移 M4（F4）；
>   §4.4 归 M1b 唯一归属（F5）；fixture 冻结产物 + 门禁分层 + 拒答非确定性治理
>   （F6）；引文按条目计量（F7）；删 Nginx/open_id 租户残肢（F8）；pricing 加
>   currency + OpenClaw 全名匹配规则（F9）；test_71 白名单去 summarize、digest
>   事件触发改 watch 打印提示（F10）；矩阵编织行恢复 ✅(半)双标（F11）。

---

## 1. 项目定位

**一句话**：本地知识库（第二大脑）——既能作为个人智能体（OpenClaw 等）的技能被调用，
也能独立用本地 Web 页面录入管理，附带局域网 API 供个人设备/程序互联。

**背景**：市面 RAG 方案普遍存在三类痛点——① 依赖云端、数据主权不可控；② 索引不可信
（向量召回会静默漏掉存在性命中）；③ 成本不可控（LLM 用在本该 grep 解决的问题上）。
CENHUA 以"grep 管存在、LLM 管意义"为第一原则，用本地文本层 + 树索引 + 引文溯源，
把这三类痛点一次解决。

| 维度 | 取舍 |
|---|---|
| 目标用户 | **个人知识库（第二大脑）用户**——不假设企业租户、不承诺公网门户 |
| 数据来源 | 本地文档 + 在线网页（发链接自动摄取） |
| 数据主权 | 本地优先，端点自选（云端或本地 Ollama/vLLM），零云锁定 |
| 成本哲学 | grep 管存在（免费、毫秒），LLM 管意义（树索引=摄取固有成本；衍生分析=三道闸门按需付费）；**全量记账，仅免预算闸** |
| 验收标准 | 端到端：丢 / 发 → 索引 → 带页码引文 → 关联推荐 → 核验原件 |

### 1.1 与 OpenClaw 第二大脑的关系

CENHUA 是**承袭 OpenClaw 第二大脑思想的重构升级，目标是独立产品项目**：思想同源、
产品独立、不整合、不双写。CENHUA 不假设用户有 OpenClaw——本机 second-brain 是其
孵化环境而非依赖；任何能跑 shell 的智能体都可装 `cenhua` 当技能用。

---

## 2. 四大模块 × 三种形态 总览

### 2.1 四大功能模块

```
                ┌──────────────────────────────────────────────┐
                │   CENHUA · 个人知识库（第二大脑）           │
                └──────────────────────────────────────────────┘
                                    │
        ┌───────────────┬───────────┴───────────┬───────────────┐
        ▼               ▼                       ▼               ▼
   ① 收录 Ingest   ② 编织 Weave          ③ 检索 Retrieve   ④ 创造 Create
   本地文档+网页    文档总结+知识图谱       检索+延展+关联     定期洞察+主题创作
```

### 2.2 3 种用户形态（CLI / 技能 / 本地 Web UI）+ 1 附带局域网 API

```
                          ┌──────────────────┐
                          │  核心服务层      │
                          │  cenhua_service │
                          │  (dataclass 契约)│
                          └──────────────────┘
                                  │
        ┌─────────┬──────────┬────┴────┐
        ▼         ▼          ▼         ▼
   ① CLI     ② 技能    ③ Web UI   局域网 API
   (v0.1已成) (v0.1已成) (v0.5新增) (v0.5附带)
   本地命令    OpenClaw    浏览器     局域网内
              等智能体    录入管理    个人设备
              调用                  程序互联
```

**收敛理由**：单维护人项目不应承诺五种外壳的攻击面。公网搜索页与企业级多租户
已删除（见 [review](roadmap-review-2026-10-13.md) Q1/Q9）；对外 API 保留但定位
降级为"局域网内个人设备/程序互联"，不做企业租户化。

### 2.3 模块 × 形态 矩阵（F4 拆格 + F11 双标恢复）

| 模块 \ 形态 | CLI | 技能 | Web UI |
|---|:-:|:-:|:-:|
| ① 收录 | ✅ | ✅ | 📋 v0.5 |
| ② 编织 | ✅(半) 📋 v0.2 | ✅(半) 📋 v0.2 | 📋 v0.5 |
| ③ 检索 | ✅ | ✅ | 📋 v0.5 |
| ④ 创造 | 📋 v0.4 | 📋 v0.4 | 📋 v0.5（洞察浏览）→ 📋 v0.6（草稿编辑） |

✅ 已成 · ✅(半) 半成（v0.1 已交付 vault 分库/树索引/引文溯源/向量层，编织增强在 v0.2）· 📋 规划中

---

## 3. 部署形态演进（核心主线）

### 3.1 形态 A：CLI（v0.1 ✅ 已成）

- 单机 `~/.cenhua/`，命令行操作
- 依赖：Python 3.11+、RapidOCR、可选向量模型
- 适用：脚本化、定时任务、智能体调用底层

### 3.2 形态 B：智能体技能（v0.1 ✅ 已成）

- 作为 OpenClaw 等个人智能体的 skill 被安装调用
- 当前用户与 CENHUA 交流的主路径之一
- 薄包装：技能层只做参数转换与结果格式化，核心逻辑在 service 层
- 本地 socket 调用无需 token

### 3.3 形态 C：本地 Web UI + 局域网 API（v0.5 新增）

**目标**：脱离智能体也能用——浏览器打开本地页面即可录入、检索、看洞察、改草稿；
附带一个局域网 API 供个人设备/程序互联（不做企业租户化）。

**Web UI 功能**（F4 创造模块拆两阶段）：

| 模块 | v0.5 Web 页面 | v0.6 增量 |
|---|---|---|
| 收录 | 文件拖拽上传 · 网页 URL 输入框 · 摄取进度 SSE 实时显示 · 失败重试 | — |
| 编织 | 文档列表 + 标签/笔记编辑 · 关联图可视化（Mermaid / 力导向图需 M3b） | — |
| 检索 | 搜索框 → 命中+总结延展+引文+关联推荐（一条结果页四段呈现） | — |
| 创造 | **洞察浏览**（digest 只读） | 草稿在线编辑（带引文悬浮提示）· 版本对比 |

**技术选型**：FastAPI + Jinja2 + HTMX（薄包装在 service 层上）；SSE 推送进度与 LLM
流式输出（v0.5 起；任务通道在 M3a 已落，SSE 在 M3b 只是其薄适配）；
不承诺 SPA 升级（避免过早复杂度）。

**局域网 API**：`/api/v1/*` 端点直接挂到 service 层函数上；**单用户 token 鉴权 +
fail-closed 白名单**（不做 OAuth/WAF/多租户、不做行级过滤——T8.2 清除租户残肢）。

---

## 4. 模块一：知识收录（Ingest）

### 4.1 范围

两类来源：**离线本地文档** + **在线互联网网页**。

### 4.2 现状（v0.1 ✅ 已成）

- **格式覆盖**：`pdf` / `docx` / `pptx` / `xlsx` / `xls` / `md` / `txt` / `html` / `csv` / 图片 / 扫描件 PDF
- **本地 OCR 优先**：RapidOCR 免费离线识别，质量门校验（`CENHUA_OCR_MIN_CONF=0.5` / `CENHUA_OCR_MIN_CHARS=10`），不达标触发视觉大模型兜底
- **去重**：sha1 命中即跳过
- **失败隔离**：无法摄取的文件进 `inbox/.failed/`，原因写 `logs/`，绝不静默丢弃
- **摄取闭环**：`add --inbox` 一次性、`watch` 后台常驻；成功后自动 `flatten` 建文本层
- **归一化**：所有格式统一硬化为 PDF 再索引，原件存档在 `engine/sources/`

### 4.3 在线网页收录（v0.3.0 · M2a，重点）

**用户行为**：把网页 URL 发给智能体 / Web UI / API → CENHUA 自动摄取。

**技术流程**：

```
用户提交 URL
  → robots.txt 检查（遵循爬虫礼仪，禁爬则拒绝并提示）
  → 速率限制（同域名滑动窗口，避免压垮目标站）
  → Playwright 无头浏览器渲染（支持 JS 动态内容）
      · 等待网络空闲 / 关键元素可见
      · 注入 CJK 字体（防中文乱码）
  → 内容提取（readability 库提正文，去广告/导航/页脚）
  → 生成双产物：渲染后 PDF（带页码，进索引） + 原始 HTML 快照（溯源用）
  → 进 inbox 走标准摄取闭环
  → 台账记录 tier=primary，标注 source=url
```

**命令形态**：

```bash
cenhua add --url https://example.com/article        # CLI 单条
cenhua add --url-file urls.txt                      # 批量
cenhua watch                                        # 监听 <vault>/inbox/urls/ 下的 .url 文件
# Web UI：URL 输入框 → SSE 实时进度 → 完成后入库列表
# API：POST /api/v1/ingest { "url": "..." }
```

**关键约束**：
- 渲染超时硬上限（默认 60s），超时降级为静态 HTML 抓取
- 同 URL 去重（URL 规范化：去 fragment、统一 query 排序）
- 单页大小上限（防内存爆），超过则只取前 N 页
- 网页摄取失败不阻塞本地文档摄取

**Playwright 安装负担对策**（R2-R7 + R3-T9）：M2a 起 `requirements.txt` 默认装
`playwright>=1.45`，`cenhua setup` 装依赖后追加执行 chromium 安装——**有 root/sudo
时执行 `playwright install --with-deps chromium`**（同装系统库 libnss3/libatk 等），
**无权限时退回 `playwright install chromium`** 并明确警告系统库未装（运行时必崩）；
幂等步骤。`cenhua doctor` 新增 chromium **启动自检**：spawn chromium 无头加载
`about:blank`（超时 15s），失败标 PROBLEM 并输出精确修复命令
`sudo playwright install-deps chromium`。系统库依赖体积另计 ~100-200MB。自检失败时
`--url` 自动降级静态 HTML 抓取。

### 4.4 离线增强（v0.2.1 · M1b，唯一归属——F5）

- 邮件格式 `eml` / `msg` 摄取（带附件展开；与网页摄取无耦合，先做不欠账）
- `watch` 增强：文件可见性防护（flush + fsync + size 稳定后再摄取）、`create_time` 排序治乱序

> F5 备注：本节归 M1b 唯一归属（watch 强化服务本地摄取主路径）；M2a 交付物不再含此行。

### 4.5 摄取增强（按需扩展点，不进里程碑）

下列扩展作为"按需扩展点"列出，**不进里程碑路线**，待真实需求出现时另立项评估：
- 多源摄取：本地目录 / S3 / 飞书云盘 / RSS 订阅 / Webhook 推送
- 增量摄取：文件变更检测、网页定期重抓（按站点配置 TTL）
- 站点级配置：每个域名独立的速率、超时、选择器规则

实现时在 `m_lib.EXTS` 注册扩展名、在 service 层 `ingest()` 增加源类型分支即可。

---

## 5. 模块二：知识编织（Weave）

### 5.1 范围

让孤立的文档变成相互关联的知识网络：**文档总结** + **跨文档关联** + **知识图谱**。

### 5.2 现状（v0.1，半成）

- **vault 分库**：按项目/领域分库，加库只改配置
- **文档内树形索引**：PageIndex 树导航，单文档深读
- **引文溯源**：每条命中带 `[doc P页]` + `Source:` 行
- **可选向量语义层**：`index build` / `seek`

### 5.3 文档总结分析（v0.2.1 · M1b，衍生分析默认免费 + hint 角色，hint 自 v0.3.1 生效）

**核心原则**：衍生分析（总结、NER、关联）默认免费，规则先行、按需精化、预算硬闸；
**树索引构建是摄取固有成本**（已在 §13 台账，不属三道闸门管辖——摄取被预算中途拒绝
会留下半成品库，风险大于收益；其成本走既有 dry-run 估算 + 进度可见即可）。

**三道闸门**（仅管衍生分析；树索引不在此列）：

1. **规则先行（免费层，摄取时跑）**：
   - 首段截取、正则实体粗提（金额/日期/邮箱/证件号/大写实体）
   - TF 关键词、标题结构（树索引已有）
   - 总结占位 `status=rule-only`，落 `<vault>/meta/summaries/<doc>.json`
     （**tier=internal-artifact**，正文不进引文，但可作 hint 进 prompt，见下）
2. **按需精化（延迟付费）**：LLM 总结/NER 不在摄取时跑，改为触发式：
   - 文档**首次被 `query`/`related` 命中**时入精化队列（用户价值明确）
   - 或 `cenhua refine --all --dry-run` 手动批量，先估价再执行
   - 队列持久化在 `<vault>/meta/refine_queue.jsonl`，`cenhua refine --drain` 消费
   - **`refine --drain` 是批量任务，豁免 `CENHUA_MAX_COST_CNY`/`CENHUA_MAX_LLM_CALLS`
     中途执法，仅受 `CENHUA_REFINE_BUDGET_CNY` 启动前 all-or-nothing 检查管辖**（F1）
3. **预算硬闸（货币层，配合 §6.4）**：
   - `CENHUA_REFINE_BUDGET_CNY`（默认 0 = 只允许规则层；设值才允许 LLM 精化）
   - 每次精化批次前：估算 token → 换算金额 → 超预算即拒，需 `--force` 或调预算
   - 台账 `<vault>/meta/cost-ledger.jsonl`：**全量记账**（含 add 树索引、OCR 视觉兜底），
     记 `{ts, cmd, doc, calls, tokens_in, tokens_out, est_cost}`
   - `cenhua cost [--month]` 汇总（按命令分组，摄取成本单列首位）
4. **批量折扣技巧**：精化队列攒批，单次请求合并 5-10 份短文档的总结任务

**新默认值**：`CENHUA_SUMMARY` 默认 `deferred`（规则先行 + 按需精化），不再 `on`。
强制摄取时跑 LLM 用 `CENHUA_SUMMARY=eager`（不推荐）。

**★ refine 价值消费者**（T1 + R4-F3）：refine 产出的精化总结（`tier=internal-artifact`）
正文**禁止作为事实证据进入引文**（not-evidence），**但可作为导航提示（hint 角色）
进入 LLM prompt**——**hint 消费自 v0.3.1 起生效**（M2b query 两段式 prompt 组装，
F3 主人裁决提前进 M2b；M3a 改为注入对抗硬化，不再是机制首发）。预算设置与用户可见
价值同版本出现，不再有"v0.2.1→v0.4 之间花钱生产没人看的文件"的排期缺口。

### 5.4 跨文档关联（v0.2.1 · M1b，四层降噪 + 小库模式）

**关联类型**：实体共现（自动，需降噪） / 主题相似（自动，向量层） / 显式引用（人工）/ 时间序列（自动）。

**存储**：`<vault>/meta/relations.jsonl`，每行 `{from, to, type, weight, evidence, source}`
（**tier=internal-artifact**，正文不进引文，仅作检索加速结构）。

**四层降噪（规则全免费，纯 Python 统计，零 LLM 零依赖）**——含**小库模式自动降档**
（T6；产品定位个人库 N≈30~300，企业阈值直接套小库会让 related 常年空转）：

`cenhua hub` 显示当前档位与 N，触发阈值 `CENHUA_SMALL_CORPUS_N`（默认 200）：

| 参数 | 标准档（N≥200） | 小库档（N<200） |
|---|---|---|
| 枢纽判定 | `df > N×0.30` | `df > N×0.50` |
| 共现地板 | `\|D_A∩D_B\| ≥ 2` | `≥ 1` |
| nPMI | 原始值 | +Laplace 平滑 |
| 每文档关联截断 | Top-8 | Top-8（不变） |

1. **IDF 过滤（自动）**：实体 IDF = `log(N/df)`；超过枢纽判定阈值判为"枢纽实体"，
   **不产生共现边**，只保留在实体索引里可查
2. **共现显著性 PMI（自动）**：边权用归一化 PMI：
   `nPMI(A,B) = log(N·|D_A∩D_B| / (|D_A|·|D_B|)) / log(N)`（小库档 +Laplace 平滑）；
   `nPMI ≤ 0`（共现不超过随机期望）直接不建边
3. **共现地板（自动）**：`|D_A∩D_B|` 小于阈值（见上表）不建边；
   每篇文档对外关联**截断 Top-8**，宁缺毋滥
4. **人工阀门（免费）**：`cenhua link --ban <实体A> <实体B>` 黑名单永久压制；
   `cenhua hub` 列出被判定的枢纽实体供人工复核（并显示当前档位）

**权重语义**：0.8 只属于人工显式关联（`cenhua link`）；自动共现边权重上限 0.6。

**可用性保障**：`related` 输出每条边带证据
（`evidence: "共现于 [docA P3, docB P12], nPMI=0.41"`），空结果明示
"无显著关联（正常）"而非沉默——**关联为空本身是信息**。

**命令形态**：

```bash
cenhua related <doc>                      # 查看与某文档关联的文档
cenhua related <doc> --type coreference   # 按关联类型过滤
cenhua link <docA> <docB> --type cites    # 人工声明关联（权重 0.8）
cenhua link --ban <实体A> <实体B>          # 黑名单压制
cenhua hub                                # 列出枢纽实体供复核（显示当前档位与 N）
# Web UI：文档详情页右侧栏"关联文档"区块
# API：GET /api/v1/relations?doc=xxx
```

### 5.5 知识图谱（v0.6 · M4）

实体级知识图谱，在文档关联之上构建。

- **实体抽取**：摄取时从文本层抽取实体（NER，规则粗提 + 按需 LLM 精化）
- **关系抽取**：实体-关系-实体三元组
- **图谱存储**：v0.6 用邻接表（JSON）；后续评估 neo4j
- **图谱查询**：`cenhua graph entity` / `path` / `cluster`
- **可视化**：CLI 邻接表 + Mermaid 输出（无条件交付）；**Web UI 力导向图仅在 M3b
  已发布时交付**（R2-R8）——M4 不强依赖 M3b，CLI 用户也能用图谱与草稿
- **衍生文档隔离**：digest/draft 不参与实体共现建边（防噪音炸弹，见 §7.3）

---

## 6. 模块三：知识检索（Retrieve）

### 6.1 范围

**重要的对外输出能力**：① 检索出现有内容 ② 总结延展 ③ 告知内容出处 ④ 推荐相关联文档。

### 6.2 现状（v0.1 ✅ 已成）

- **find**：本地正则扫文本层，毫秒级、免费、精确、带页码
- **read**：打印原文页用于核验
- **ask**：树导航式 LLM 深读，`--dry-run` 估算，`CENHUA_MAX_LLM_CALLS` 上限
- **seek**：向量语义检索（可选层）
- **sources**：查看原始上传与存档副本（M3a 起按三类 tier 分组显示，见 §7.3）

检索哲学：`find` → `ask --doc` → `seek` → `ask --all`，按成本递增调用。

### 6.3 总结延展检索（v0.3.1 · M2b，重点；hint 两段式 prompt 自此生效——F3）

把"检索 + 总结 + 关联推荐"合并为面向用户的检索命令。

```bash
cenhua query "ABC 合同的违约金条款"
# 输出四段：
#   1. 直接命中：哪些文档哪一页提到违约金（find）
#   2. 总结延展：LLM 基于命中内容做的总结 + 关键点延展（ask，prompt 两段式 hint-not-evidence）
#   3. 内容出处：每条结论带 [doc P页] + snippet 引文 + Source: 行
#   4. 关联推荐：基于关联层推荐的 N 个相关文档（related）
```

**关键设计**：
- **三路融合**：`find`（精确）+ `seek`（语义）+ `ask`（推理）单命令合并，按置信度排序
- **出处不可选**：延展结论必须带引文（含 snippet，见 §6.5/F2），无引文的结论标
  `[未溯源·LLM 推断]`
- **关联推荐**：依赖 §5.4 跨文档关联；无关联层时降级为向量相似
- **检索默认降级**：`find/query/seek` 默认**只在 primary 层召回**（见 §7.3）；
  `--include-derived` 显式开启 derived-doc 层
- **★ prompt 两段式 hint-not-evidence**（**F3 主人裁决，自 M2b 起生效**）：
  - hint 段（refined summaries，`tier=internal-artifact`）"去哪里看"，带显式
    `[HINT tier=internal]` 标记与证据段隔离；hint 段只许陈述、不许祈使（防注入）
  - 证据段（primary 文本层）"是什么"
  - 禁止引用 internal-artifact 正文作为事实证据（not-evidence）
  - 禁止直接引用 derived-doc（digest/draft）正文作为事实证据
  - 基于 hint 得出的结论必须从 primary 正文**重新验证**后引用
  - M3a 增量为**注入对抗硬化**（hint 段指令剥离、fixture 注入对抗题），不再是机制首发

### 6.4 成本货币化护栏（v0.2.0 · M1a 基础；v0.3.1 · M2b 推广至全命令 + hint 生效）

`--dry-run` 输出从"预估 calls"升级为"预估 calls + tokens + 金额"：

```
预计 6 次调用 · ~48K in / 12K out · ≈¥0.35（按 model 单价表）
```

**关键设计**：
- 单价表 `pricing.json`（随包分发，可覆盖）：model → {in, out, currency} 每 1K token
  价格；未知模型用保守默认价并在输出标注"估价，未配置单价"（F9 加 currency 字段，
  混合货币不强行折算，显示 `¥0.35 + $0.02` 加汇率提示脚注）
  - **OpenClaw 网关匹配规则**（F9）：先按全名 `openclaw:provider/model` 精确匹配 →
    再按裸 model id 匹配 → 未命中用保守默认价 + 输出标注
    "估价：未配置单价（provider/model）"
  （**M1a 已同包交付** pricing.json + 换算函数 + cost-ledger.jsonl，见 §8.M1a）
- `CENHUA_MAX_COST_CNY`（单命令花费上限，默认 2.0），与 `CENHUA_MAX_LLM_CALLS`
  （默认 8）并联，**先到先停**；**不适用 `add`/`watch`**（摄取无预算拒执，防半成品库）
- **全量记账，仅免预算闸**（T5）：所有 LLM 调用（含 `add` 树索引、OCR 视觉兜底）
  一律写 `cost-ledger.jsonl`；`cenhua cost` 输出按命令分组
  （ingest / ask / query / refine / digest…），**摄取成本单列首位**
- **★ 长任务/批量任务豁免中途执法**（F1，治 T7 只修启动豁免的腰斩）：
  > **长任务（digest/draft）与批量任务（`refine --drain`）豁免 `CENHUA_MAX_COST_CNY`
  > 与 `CENHUA_MAX_LLM_CALLS` 的中途执法；仅受各自预算
  > （`CENHUA_LONGJOB_MAX_COST_CNY` / `CENHUA_REFINE_BUDGET_CNY`）的启动前
  > all-or-nothing 检查管辖。**
  - **三闸执法顺序表**（启动前依次检查，任一超即拒启）：
    ① dry-run 估价 → ② 对应任务预算（longjob/refine）→ ③ `--force`/`--max-cost` 放行通道
  - 中途执法唯一保留项：硬件级异常（网关连续失败）走既有 try/except 降级，
    标 FAILED 不落半成品
- **digest/draft 独立长任务预算**（T7）：`CENHUA_LONGJOB_MAX_COST_CNY`（默认 5.0，
  与单命令默认 2.0 分离）；all-or-nothing——启动前强制 dry-run 估价，超预算**拒绝启动**
  （绝不中途停，防断头洞察），`--force` 或 `--max-cost` 显式放行
- token 估算方式：字符数/1.6（中英混合近似）+ 上次真实调用的校准系数；
  不追求精确、追求数量级正确
- 全部写入 §5.3 的 cost-ledger，形成"预估 vs 实际"闭环
  （M1a 起校准闭环同落：预估偏差 >3x 时告警，防单价表过期）

### 6.5 局域网 API（v0.5 · M3b 附带）

`/api/v1/*` 端点直接挂到 service 层函数上：

```
POST /api/v1/ingest                 # 摄取（文件 / URL）
GET  /api/v1/documents               # 文档列表
POST /api/v1/find                    # 存在性检索（免费、毫秒）
POST /api/v1/query                   # 总结延展检索（含关联推荐）
POST /api/v1/ask                     # LLM 深读（成本护栏）
POST /api/v1/draft                   # 主题创作（v0.6 起，随 M4 交付；v0.5 返回 404 + 版本提示）
POST /api/v1/digest                  # 触发洞察
GET  /api/v1/relations?doc=xxx       # 文档关联
GET  /api/v1/graph?entity=xxx        # 图谱查询（v0.6 起，随 M4 交付；v0.5 返回 404 + 版本提示）
```

响应统一格式（dataclass 直接序列化；F2 citations 新增 snippet 字段）：

```json
{
  "rid": "abc123",
  "hits": [{"doc": "contract.pdf", "page": 12, "snippet": "..."}],
  "summary": "基于命中内容的总结...",
  "extensions": ["延展要点1", "延展要点2"],
  "citations": [{"doc": "contract.pdf", "page": 12, "snippet": "违约金按日万分之五...", "tier": "primary"}],
  "related": [{"doc": "policy.pdf", "reason": "共现 nPMI=0.41", "weight": 0.6}]
}
```

**鉴权**：单用户 token + `CENHUA_API_TOKEN`（fail-closed 白名单，T8.2 清除租户残肢——
不做行级过滤、不做用户映射）。
**约束**：引文不可选；所有 LLM 端点支持 `?dry_run=true` 与
`CENHUA_MAX_LLM_CALLS`/`CENHUA_MAX_COST_CNY`；
滑动窗口 RateLimiter → 429；结构化日志带 rid 全链路追踪。
**任务化**：LLM 长任务（ask/query/digest/draft）走 M3a 任务通道（submit →
job_status → job_result），Web/API 层把 `job_status` 增量转 SSE 事件流（见 §8.M3a）。
**F2 引文 schema 约束**：ask/query 响应 schema 强制 citations 带 snippet（无 snippet
的引文在门禁计为失败，倒逼 prompt 输出规范）。

### 6.6 多轮与重排（v0.6+ 评估）

- 多轮对话：上下文继承
- 重排器：粗召回后用小模型重排，提升 Top-K 精度

---

## 7. 模块四：知识创造（Create）

### 7.1 范围

基于库内知识生成新文稿。两个子方向：① 定期洞察 ② 主题创作。

### 7.2 现状（v0.1，未实现）

检索与理解已具备，生成侧尚未落地。这是 v0.4+ 的核心增量。

### 7.3 定期洞察（v0.4 · M3a，CLI-only 交付）

周期性扫描全库，发现跨文档的模式、趋势、矛盾，输出洞察文章。

**触发方式**（F10 修正"事件触发自动建议"——产品无守护进程与通知通道）：
- cron 定时：`cenhua digest --weekly` / `--monthly` / `--quarterly`
- 手动触发：`cenhua digest --since 2026-09-01`
- **watch 提示**（F10）：`watch` 累计摄取 N 篇（默认 20）后在进度日志打印一行提示
  `提示：自上次洞察以来已摄取 N 篇，可运行 cenhua digest --dry-run 估价`；
  **无任何自动触发执行**

**洞察文章结构**：

```markdown
# CENHUA 知识洞察 · 2026 Q3

## 一、本期新增知识图谱（摄取摘要 + 关键实体变化）
## 二、跨文档发现
   - 模式：[多份合同均含 X 条款] —— [docA P3][docB P7]...
   - 趋势：[近 3 月政策文件转向 X 主张] —— [docC][docD]...
   - 矛盾：[文档 A 与文档 B 对 Y 的表述冲突] —— 引文对比
## 三、待澄清问题（建议下次摄取方向）
## 四、引用文档清单（按权重排序）
```

**关键设计**：
- 全程带引文（含 snippet），洞察结论必须可溯源到具体文档页
- 与 §5.3 文档总结、§5.4 跨文档关联复用
- 成本护栏：**all-or-nothing**（T7+F1）——启动前三闸执法顺序检查，超
  `CENHUA_LONGJOB_MAX_COST_CNY`（默认 5.0）**拒绝启动**，绝不中途停（防断头洞察）；
  `--force` 或 `--max-cost` 显式放行；豁免 `CENHUA_MAX_COST_CNY`/`CENHUA_MAX_LLM_CALLS`
  中途执法
- 输出位置：`<vault>/works/digests/`

**★ 三层 artifact 纪律**（R2-R5 + R3-T1 + R4-F2 改写）：

| 类别 | 成员 | 检索/引文规则 |
|---|---|---|
| `primary` | 原件、网页 HTML 快照、硬化 PDF | 事实源，检索默认召回，可作引文（带 snippet） |
| `derived-doc` | digest、draft | 默认不召回（`--include-derived` 开启），展示必带 ⚠ 标记，引文穿透到 primary |
| `internal-artifact` | summaries、entities、vectors、relations | **正文禁止作为事实证据进入引文**（not-evidence）；**可作为导航提示（hint 角色）进入 LLM prompt**——形如 `【提示，非证据】该文档主旨为 X，重点段落 P12-15`；基于 hint 得出的任何结论，其证据必须从 primary 正文**重新验证**后引用 |

落地要点：
1. **摄取台账 tier 字段三元化**：所有 artifact 入库时打 tier 标签；衍生文档
   （digest/draft）入库强制带 `derived_from: [原件 doc_id...]`
2. **检索默认降级**：`find/query/seek` 默认**只在 primary 层召回**；
   `--include-derived` 显式开启 derived-doc 层，且衍生命中必须显示
   `⚠ 衍生内容（由 X 生成）`
3. **prompt 组装两段式**（T1，**自 M2b 落地，F3 主人裁决**）：hint 段（summaries）
   负责"去哪里看"，带显式 `[HINT tier=internal]` 标记与证据段隔离；证据段
   （primary 文本层）负责"是什么"；hint 段只许陈述、不许祈使（防注入）；基于 hint
   得出的结论必须从 primary 正文重新验证后引用
4. **引文穿透链**：digest/draft 被作为依据时，输出必须列 `derived_from` 链，
   引文最终**穿透 internal-artifact 与 derived-doc 直达 primary 原件页码**；
   禁止引用 internal-artifact 与 derived-doc 的正文作为事实证据
5. **图谱隔离**：衍生文档（derived-doc）与 internal-artifact 均不参与实体共现建边
   （digest 罗列全库实体，参与建边 = 噪音炸弹）
6. **`cenhua sources` 输出按三类分组显示**（primary / derived-doc / internal-artifact）

### 7.4 主题创作（v0.6 · M4）

用户输入主题，CENHUA 基于库内素材辅助生成文稿。

```bash
cenhua draft "ABC 项目违约风险备忘录"
  # 流程：
  #   1. 主题分析：LLM 把主题拆为子问题
  #   2. 召回：每个子问题走 §6.3 总结延展检索（默认只召回 primary）
  #   3. 草稿生成：LLM 基于召回结果生成 Markdown 草稿
  #   4. 引文嵌入：草稿每段挂 [doc P页] + snippet 引文（穿透到 primary）
  #   5. 存档：<vault>/works/drafts/<主题>_V1_<日期>.md（tier=derived-doc）
```

**辅助能力**：
- `cenhua draft --extend <段号>`：基于库内素材扩写指定段落
- `cenhua draft --rewrite <段号>`：换种写法重写
- `cenhua draft --verify`：校验草稿中所有引文是否真存在于原件——**反向包装 M1a
  service 原语 `verify_citation(doc, page, snippet)`**（T4+F2；门禁与草稿共用同一
  校验实现，单一事实源；升级为三参签名，校验 snippet 归一化后确实存在于该页文本层，
  NFKC 归一 + 去空白/全半角折叠后正则匹配）
- `cenhua draft --list` / `--diff` / `--restore`：版本管理

**成本护栏**：与 digest 同款 all-or-nothing + `CENHUA_LONGJOB_MAX_COST_CNY`（T7+F1），
超预算拒绝启动；豁免 `CENHUA_MAX_COST_CNY`/`CENHUA_MAX_LLM_CALLS` 中途执法。

### 7.5 模板与导出（v0.6+ 评估）

- 模板系统：报告 / 备忘录 / 邮件 / 周报，自定义模板放 `<vault>/meta/templates/`
- 导出：Markdown / HTML / PDF

---

## 8. 里程碑式交付产品

每个里程碑都是一个**可独立交付的完整产品形态**。M3a 起 service 层完成，
Web UI 在 M3b 才名副其实是薄包装（避免 M3 大爆炸式捆绑）。

**里程碑验收通用标准**（参考 design.md §5）：
1. 端到端：完成本里程碑"用户场景"全流程，产物可读回比对
2. 离线项：本里程碑新增的离线命令在无 LLM 时正常工作
3. 测试：新增功能配套单测；`bash tests/run_tests.sh` 全绿；
   `test_61_engine_is_untouched` 始终守护引擎纯净
4. 文档：user-guide.md 同步更新；新坑回写 pitfalls.md
5. 形态：里程碑标注的形态实际可独立运行
6. **成本护栏（F1 三闸执法顺序）**：新增 LLM 端点都有 `--dry-run`（含金额）与
   `CENHUA_MAX_LLM_CALLS`/`CENHUA_MAX_COST_CNY` 并联；**长任务（digest/draft）与
   批量任务（`refine --drain`）豁免 `CENHUA_MAX_COST_CNY` 与 `CENHUA_MAX_LLM_CALLS`
   的中途执法，仅受各自预算（`CENHUA_LONGJOB_MAX_COST_CNY`/`CENHUA_REFINE_BUDGET_CNY`）
   的启动前 all-or-nothing 检查管辖**；三闸执法顺序：① dry-run 估价 → ② 对应任务
   预算 → ③ `--force`/`--max-cost` 放行通道；中途执法唯一保留项：硬件级异常（网关
   连续失败）走既有 try/except 降级，标 FAILED 不落半成品
7. **检索质量门禁**（R2-R2 + R3-T2/T4 + R4-F2/F6/F7；分阶段生效）：
   - **门禁载体**：M1a 交付 `cenhua bench` 命令 + **内置 fixture 冻结产物**
     （随包分发已建好的 tree index + 文本层 + 30 题 QA；合成语料源文件一并打包供审计，
     但 bench 不重建索引——F6.1；存在性+溯源子集零 LLM 零网络）
   - **门禁跑 fixture 不跑活库**（T2）：默认跑 fixture，此结果才是**阻断级门禁**；
     用户库 QA 集降级为**报告模式**（`cenhua bench --corpus`，只打印不阻断），每题带
     `corpus_hash`，语料变更时自动标"题目过期（需重验答案）"，不计失败
   - **门禁分层**（F6.2）：
     - CI 层（`tests/run_tests.sh`）：fixture 存在性 + 溯源题，**离线阻断**
     - 发版流水线：全量 fixture（含拒答，需 API key），**发版阻断**；无 key 环境
       发版跳过拒答集并在 release notes 标注
   - **拒答题非确定性治理**（F6.3）：temperature=0 + 失败重试 1 次；同一题连续 2 个
     版本 flaky → 自动转人工仲裁（进 `meta/qa/flaky.jsonl`），不连续阻断发版
   - **引文校验器**（T4+F2）：M1a service 原语 `verify_citation(doc, page, snippet) -> bool`
     落地，校验 snippet 归一化后确实存在于该页文本层（NFKC 归一 + 去空白/全半角折叠后
     正则匹配）；门禁与 M4 `draft --verify` 共用同一校验实现，单一事实源
   - **引文按条目计量**（F7）：引文准确率按引文条目计量（每题挂多个引用点，全量条目
     ≥20；阈值按条目占比 ≥95%，n≥20 时 1 条失败 ≈5pp 可容忍且有信号）；**存在性召回
     维持 100% 零容忍**（铁律"沉默不是证据"的直接度量，不因统计粒度让步）；失败处置：
     bench 输出逐条 diff 清单（题目、期望、实际、命中页、snippet 匹配详情）供归因
   - **M1a/M2**（存在性 + 引文，拒答类不计——query 尚不存在）：
     - 存在性召回 **100%**（回归即阻断发版）
     - 引文条目准确率 **≥95%**（引用页码 + snippet 经 `verify_citation` 验证真实存在）
   - **M2b 起**（拒答门禁加入阻断集，跑 fixture 拒答题）：
     - 拒答正确率 **≥90%**（语料外问题必须答"没有"，防幻觉）
8. **service 层守护**（review Q6 + R2-R6 + R3-T8.3 + R4-F10；M1a 起）：
   - `test_70_service_no_print`（service 禁 print/exit）**自 M1a 起对 service 模块全量生效**
     （新建代码无历史债；`summarize` 等 service 函数由此管辖）
   - `test_71_cli_is_thin`（CLI 函数体 ≤10 行：解析参数 → 调 service → 渲染）
     **白名单制**：只收**用户命令**（F10；`related` / `refine` / `cost` / `bench` /
     `query` / `digest` / `draft`…），`summarize` 不是用户命令（无 CLI 面）移出白名单；
     白名单随里程碑只增不减（M1b: `related`/`refine`/`cost`/`bench` → M2b: `query` →
     M3a: `digest` → M4: `draft`），未迁移命令豁免
   - service 契约登记制：**M1a 首个 commit = `docs/service-contract.md` 建档并登记
     本里程碑全部新函数**（T8.3；杜绝"先实现后登记"窗口期）；**建档时直接采用升级后
     契约**（citations 含 snippet、`verify_citation` 三参签名、`schema_version`——F2）；
     已有 dataclass 只加字段不删改，读侧容忍旧版本

### M0 · v0.1.0 · CLI 与技能底座（✅ 已发布）

**交付物**：CLI `cenhua` 命令族（init/add/find/read/ask/seek/status/doctor）；
OpenClaw 技能包；离线文档摄取闭环（多格式 + 本地 OCR + 去重）；树形索引 + 文本层
+ 引文溯源；成本护栏（`--dry-run` + `CENHUA_MAX_LLM_CALLS`）；34 单测 + 14 OCR 单测 + smoke 全绿。

**用户场景**：智能体用户对 OpenClaw 说"把这些合同索引一下"，自动安装技能并完成摄取检索。

### M1a · v0.2.0 · 成本与质量基础设施（🚧 规划，★纯基础设施可先行）

**交付物**（T3 拆分；纯基础设施，不碰编织逻辑；F2/F6/F7 升级）：
- `pricing.json`（model → {in, out, currency} 每 1K token 价格；F9 加 currency 字段；
  未知模型保守默认价 + "未配置单价"标注；**OpenClaw 全名匹配规则**：先按
  `openclaw:provider/model` 全名精确匹配 → 再按裸 model id 匹配 → 未命中保守默认价）
- token 估算/换算函数（token → 金额；混合货币不强行折算，显示 `¥0.35 + $0.02` 加
  汇率提示脚注）
- `cost-ledger.jsonl`（**全量记账**——含 add 树索引、OCR 视觉兜底；T5）
- `cenhua cost [--month]` 汇总（按命令分组：ingest / ask / query / refine / digest…，
  **摄取成本单列首位**）
- 预估校准闭环（预估偏差 >3x 告警，防单价表过期）
- `cenhua bench` 命令 + **内置 fixture 冻结产物**（F6.1：随包分发已建好的 tree index +
  文本层 + 30 题 QA；合成语料源文件一并打包供审计，但 bench 不重建索引；存在性+溯源
  子集零 LLM 零网络）
- service 原语 **`verify_citation(doc, page, snippet) -> bool`**（T4+F2：校验 snippet
  归一化后确实存在于该页文本层，NFKC 归一 + 去空白/全半角折叠后正则匹配；非"页存在"
  同义反复校验）
- `docs/service-contract.md` 建档（**M1a 首个 commit**：建档并登记本里程碑全部新函数；
  T8.3；6 核心函数 dataclass 签名 + `schema_version` 字段；**建档时直接采用升级后契约**——
  citations 含 snippet、verify_citation 三参签名——F2）
- 防回潮测试：`test_70_service_no_print`（service 全量生效）

**用户场景**：`cenhua cost` 月报按命令分组显示开销，摄取成本单列首位；
`cenhua bench` 跑 fixture 验证存在性召回 100% 与引文条目 ≥95%；`verify_citation` 服务
作为门禁与草稿校验的单一事实源。

**依赖**：M0。

### M1b · v0.2.1 · 编织（🚧 规划）

**交付物**（T3 拆分；复用 M1a 换算函数与 verify_citation 两处；F5 唯一归属 §4.4）：
- §4.4 离线增强（**唯一归属**——邮件 `eml`/`msg` + watch 强化；F5；M2a 不再重复此行）
- §5.3 文档总结（deferred 模式：规则先行 + 按需精化 + 预算硬闸；refine 机制保留，
  hint 角色规则见 §7.3——**hint 消费自 v0.3.1 起生效**，F3；`refine --drain` 是批量
  任务豁免中途执法，仅受 `CENHUA_REFINE_BUDGET_CNY` 启动前 all-or-nothing 检查管辖，F1）
- §5.4 跨文档关联（四层降噪：IDF / nPMI / 共现地板 / 人工阀门；**含小库模式自动降档**，
  T6；`CENHUA_SMALL_CORPUS_N` 默认 200）
- service 层搬迁：`related` / `refine` / `cost` / `bench` 入 service
  （进入 `test_71` 白名单首批：M1b = `related`/`refine`/`cost`/`bench`；**`summarize`
  不是用户命令，移出白名单，由 test_70 管辖**——F10）
- 防回潮测试：`test_71_cli_is_thin`（白名单内命令生效）

**用户场景**：摄取一份新合同，CENHUA 规则层即时给出关键词与实体粗提；首次被 `query`
命中时入精化队列，`cenhua refine --drain` 消费（hint 消费待 v0.3.1 query 落地生效）；
`related` 输出带 nPMI 证据的关联；`cenhua hub` 显示当前档位与 N。

**依赖**：**M1a**（仅换算函数与 `verify_citation` 两处）。M2a 与 M1 支线并行，互不阻塞。

### M2a · v0.3.0 · 网页收录（📋 规划，★独立支线，只与主线并行不阻塞）

**交付物**（F5 删除 §4.4 重复行，只保留 §4.3 网页收录本体）：
- §4.3 在线网页收录（Playwright + readability + 双产物 PDF/HTML 快照）
- 网页摄取失败独立进 `inbox/.failed/`
- **Playwright 默认安装 + WSL2 系统库对策**（R2-R7 + R3-T9）：
  - `requirements.txt` 新增 `playwright>=1.45`（注释说明用途与体积）
  - `cenhua setup` chromium 安装步骤：有 root/sudo 时 `playwright install --with-deps
    chromium`（同装系统库 libnss3/libatk 等），无权限时退回 `playwright install
    chromium` 并明确警告系统库未装（运行时必崩）；幂等步骤
  - `cenhua doctor` 新增 chromium **启动自检**：spawn chromium 无头加载 `about:blank`
    （超时 15s），失败标 PROBLEM 并输出精确修复命令 `sudo playwright install-deps
    chromium`；自检失败时 `--url` 自动降级静态 HTML 抓取
  - 系统库依赖体积另计 ~100-200MB
  - 运行时降级保留：渲染超时/失败仍降级静态 HTML 抓取

**用户场景**：用户对智能体说"把这篇新闻索引一下"并发 URL，CENHUA 渲染并摄取。

**依赖**：M0（★不依赖 M1，可与 M1 并行开发；语料贡献是增益不是前置）。

### M2b · v0.3.1 · 延展检索 + 成本货币化推广 + 拒答门禁 + ★ hint 两段式 prompt 首发（📋 规划）

**交付物**：
- §6.3 总结延展检索 `cenhua query` 四段输出
- §6.4 成本货币化护栏：`--dry-run` 输出 calls + tokens + 金额；
  `CENHUA_MAX_COST_CNY` 与 `CENHUA_MAX_LLM_CALLS` 并联先到先停
- **dry-run 金额预估推广至全 LLM 命令**（R2-R3；复用 M1a 换算函数）：
  ask/query/digest/draft/refine 全部支持 `--dry-run` 金额预估
- **★ prompt 两段式 hint-not-evidence 首发落地**（F3 主人裁决，治 T1 排期缺口）：
  `query` 的 prompt 组装采用两段式——hint 段注入 refined summaries，标
  `[HINT tier=internal]`；证据段仅从 primary 文本层取；hint 段只许陈述、不许祈使
  （防注入）；基于 hint 得出的结论必须从 primary 正文重新验证后引用。**预算设置与
  用户可见价值同版本出现**（refine 自此有消费者）
- service 层搬迁：`query` 入 service（进入 `test_71` 白名单：M2b = `query`）
- §7.3 三层 artifact 标记：摄取台账 `tier` 字段（primary/derived-doc/internal-artifact）
  + 检索默认降级（只在 primary 召回）+ internal-artifact 正文不进引文（**但可作 hint
  进 prompt，自此生效**）

**门禁增量**（R2-R2 + R3-T2 + R4-F6.2）：自 M2b 起，拒答正确率 ≥90% 加入阻断集——
**跑 fixture 拒答题**（发版流水线，需 API key；无 key 环境跳过拒答集并在 release notes
标注）；拒答题非确定性治理：temperature=0 + 失败重试 1 次；连续 2 版 flaky 转人工仲裁
（`meta/qa/flaky.jsonl`）。

**用户场景**：问"违约金条款"得到带出处（含 snippet）和关联推荐的延展回答；`--dry-run`
显示"预计 6 次调用 · ~48K in / 12K out · ≈¥0.35"；fixture 语料外问题答"没有"；
refine 投入的预算自此有消费者（hint 进 prompt）。

**依赖**：**M1b**（关联层 + summaries）★ **不依赖 M2a**（R2-R4；本地合同库足以验收
query 四段输出）。

### M3a · v0.4.0 · service 层完成 + 定期洞察 + 任务通道 + hint 注入对抗硬化（📋 规划，CLI-only）

**交付物**：
- service 层完成：`ingest` / `find` / `query` / `related` / `ask` / `stats` 全部入 service
  （dataclass 返回，禁 print/exit；契约登记制建档持续维护）
- §7.3 定期洞察 `cenhua digest`（CLI-only，纯后端，无前端风险；**all-or-nothing + 豁免
  中途执法**，T7+F1；三闸执法顺序：① dry-run 估价 → ② `CENHUA_LONGJOB_MAX_COST_CNY`
  → ③ `--force`/`--max-cost` 放行；超预算拒绝启动绝不中途停；触发方式含 watch 打印
  提示，F10）
  （进入 `test_71` 白名单：M3a = `digest`）
- §7.3 三层 artifact 闭环：digest 入库 tier=derived-doc + derived_from 链；
  引文穿透链穿透 internal-artifact 直达 primary；`cenhua sources` 按三类分组显示
- §5.5 图谱隔离：衍生文档（derived-doc）与 internal-artifact 均不参与共现建边
- **★ hint 注入对抗硬化**（F3；不再是 hint 机制首发——首发在 M2b）：
  - hint 段指令剥离（prompt 中 hint 只许陈述、不许祈使，硬规则化）
  - fixture 加注入对抗题（**至少 1/3 对抗题人工撰写**，防出题方与攻击方同源盲区——R4 §4 预告）
  - hint 二段验证成本计入 refine ROI 账（hint 省下的是导航成本，不能倒贴验证成本）
- **ledger 摄取成本单列**（T5）：`cenhua cost` 输出按命令分组，摄取成本单列首位
- **任务通道**（R2-R9；service 契约登记制首选手）：
  ```python
  submit(job: JobSpec) -> JobHandle          # 立即返回，LLM 工作在后台线程/进程
  job_status(handle) -> JobStatus            # 含增量 output chunks、进度、终态、cost 累计
  job_result(handle) -> AskResult | QueryResult  # 终态后取完整 dataclass
  ```
  - LLM 长任务（ask/query/digest/draft/ingest 进度）统一走任务通道
  - CLI 轮询打印进度；CLI/Web/API 三形态共用同一进度协议
  - 摄取进度（watch 已有 `logs/` 进度）收敛到同一机制
  - **★ 任务通道持久化边界**（R2/R3/R4 连续三轮预告，**M3a 开工前必须拍板，不得再顺延**——R4 §4）：
    重启后未完成任务的续跑或标废策略

**用户场景**：`cenhua digest --weekly` 输出跨文档模式/趋势/矛盾洞察文章，本身回流库内
（tier=derived-doc），后续检索默认不召回，`--include-derived` 显式开启；
digest 走任务通道，CLI 实时打印进度；超预算拒绝启动不留半成品；hint 注入对抗硬化。

**依赖**：M2b。

### M3b · v0.5.0 · 本地 Web UI + 局域网 API（📋 规划，薄适配；F4 创造模块收敛）

**交付物**（F4 创造模块收敛为洞察浏览，草稿编辑移 M4）：
- §3.3 本地 Web UI（FastAPI + Jinja2 + HTMX，薄包装在 M3a 的 service 上）
  - 摄取：文件拖拽 + URL 输入框 + SSE 进度
  - 检索：搜索框 → 命中+延展+引文（含 snippet）+关联四段结果页
  - 编织：文档列表 + 标签 / 关联图 Mermaid 可视化
  - **创造：洞察浏览（digest 只读）** ★ 草稿编辑/引文悬浮/版本对比三行移入 M4（F4）
- §6.5 局域网 API（`/api/v1/*` 挂到 service 层；**单用户 token + fail-closed 白名单**，
  T8.2 清除租户残肢——不做行级过滤、不做用户映射）
- **SSE 只是任务通道的薄适配**（R2-R9）：Web/API 层把 M3a 的 `job_status` 增量
  转 SSE 事件流；断线重连按 handle 重订阅天然安全
- **API 端点版本脚注**（R2-R10 + R3-T8.1）：`GET /api/v1/graph` 与
  `POST /api/v1/draft` 在 v0.5 均返回 404 + 版本提示（"v0.6 起，随 M4 交付"）

**用户场景**：用户浏览器打开 `http://localhost:8080`，拖文件、发链接、查结果、看洞察
（digest 只读），全程不依赖智能体；个人其他设备/程序通过局域网 API 调检索能力。

**依赖**：M3a。M3b 失败（Web UI 黄了）产品仍是完整 CLI（个人用户 90% 场景）。

### M4 · v0.6.0 · 知识图谱 + 主题创作 + Web 草稿编辑（📋 规划；F4 接收 Web 草稿编辑三件套）

**交付物**：
- §5.5 知识图谱（NER + 三元组 + 邻接表 + Mermaid 可视化）
  - **力导向图加发布条件**（R2-R8）：CLI 邻接表 + Mermaid 输出（无条件交付）；
    **Web UI 力导向图仅在 M3b 已发布时交付**
- §7.4 主题创作 `cenhua draft`（主题→拆解→召回→生成→引文穿透（含 snippet）→版本管理）
  （进入 `test_71` 白名单：M4 = `draft`）
  - **all-or-nothing + 独立长任务预算 + 豁免中途执法**（T7+F1）：三闸执法顺序检查，
    超 `CENHUA_LONGJOB_MAX_COST_CNY`（默认 5.0）拒绝启动绝不中途停；`--force`/`--max-cost`
    放行；断点续跑不做（M4 前），失败重跑从头估价——长任务幂等由 `rid` 记录保证可审计
  - **`draft --verify` 反向包装 M1a `verify_citation(doc, page, snippet)`**（T4+F2）：
    门禁与草稿共用同一校验实现，单一事实源；三参签名校验 snippet 归一化后确实存在于
    该页文本层
- **★ Web UI 草稿编辑三件套**（F4 从 M3b 移入）：草稿在线编辑（带引文悬浮提示）·
  版本对比 · 引文穿透到 primary
- §7.5 模板系统（报告 / 备忘录 / 邮件 / 周报）
- §6.6 多轮对话 + 重排器
- `GET /api/v1/graph` 与 `POST /api/v1/draft` 端点随 M4 交付（v0.6 起）

**用户场景**：用户说"为 ABC 项目违约风险写一份备忘录" → CENHUA 召回相关合同/政策 →
生成带引文（含 snippet，穿透到 primary）的草稿；若 M3b 已发布，用户可在 Web UI
力导向图浏览知识图谱、在线编辑草稿；若 M3b 未发布，CLI 邻接表 + Mermaid 仍可用。

**依赖**：M3a（★不依赖 M3b，CLI 用户也能用；但 Web UI 力导向图与草稿编辑需 M3b 已发布）。

### 里程碑依赖图

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

**每格失败只砍自己**：M2a 网页收录黄了不影响 M2b 检索升级（M2b 只依赖 M1b）；
M3b Web UI 黄了产品仍是完整 CLI（个人用户 90% 场景）；M4 不依赖 M3b，CLI 用户也能
用图谱与草稿（仅 Web 力导向图与草稿编辑需 M3b）。

---

## 9. 部署约束（贯穿所有形态；F8 清除租户时代器官）

参考内部项目工程惯例（不外链私人仓库路径，模式描述留正文）：

- **配置驱动**：变数进 `vault.yaml` / `config.json`，禁止硬编码；优先级 `ENV > config > 默认`
- **凭证安全**：`.gitignore` + `chmod 600`，agent/路由层永远不接触下游凭证；
  `vault.yaml` 拒绝存储 `key`/`token`/`secret`
- **局域网 API 鉴权**（T8.2 清除租户残肢）：单用户 token + `CENHUA_API_TOKEN` 白名单
  fail-closed；**不做行级过滤、不做用户映射、不做多租户**
- **ID/命名/版本集中一处生成**：草稿 `<主题>_V{N}_{日期>.md`，trace_id/rid 全链路唯一
- **结构化日志 + 全链路 trace**（F8 去飞书概念）：入口与下游共用 rid；日志脱敏
  （**token / 绝对路径 / PI_KEY 前缀脱敏**——产品内无飞书 open_id 概念）；RotatingFileHandler
- **外部输入必须 try/except + 默认值降级**：网页抓取、LLM 调用、OCR 必须有 fallback
- **限流 + 中间件异常降级**（F8 去 Nginx）：滑动窗口 RateLimiter → 429；**uvicorn
  `timeout_keep_alive` 与请求级 timeout 按推理时长设置**（产品无组件反代，Nginx 仅作为
  可选部署附件在 user-guide 提一句）
- **看门狗**：端口检测精确匹配、启动保护期 + 重启冷却/上限、PID 文件锁防重复
- **验收端到端**：容器内 curl /health + 校验产物内容，不只看启动成功
- **检索正确性铁律**（参考 pitfalls.md §2-3）：
  - 加密 PDF 不能被 `except: continue` 静默跳过——先试文件名数字段
    `doc.authenticate(<digits>)`，绝不记录密码
  - **绝不可凭一条路径断言"语料里没有"**：`find` 命中与源文件负扫描必须一致；
    某路径失败（超时/崩溃/空文本层）时，它的沉默不是证据
  - **文本层新鲜度**：`find` 读 `engine/text/` 不是 PDF，摄取后必须 `flatten`，
    否则静默漏掉新文档；`cenhua doctor` 把空文本层标为 PROBLEM 绝不忽略
  - **人名变体**：一次 `find` 扫同音/异体变体（`find 张三 张山 章三`）
  - **OCR 身份证号常有 1-2 位错**：用 `engine/id_verify.py` 校验，校验失败前不得下身份结论

---

## 10. 设计原则（不变量）

详见 design.md：

1. **grep 管存在，LLM 管意义** — 存在性问题绝不用 LLM
2. **引擎保持上游纯净** — `scripts/engine/` 字节级 diff 上游
3. **密钥永不落盘** — 只在 env 或 OpenClaw 配置实时解析
4. **安装时两问** — 网关与存储位置由用户拍板
5. **本地 OCR 优先，大模型兜底** — 质量门校验后才信任
6. **引文不可选 + snippet** — 每条命中、每个 LLM 结论必须可溯源到原件（含 snippet 锚文本，
   F2）；无引文结论必须显式标注 `[未溯源·LLM 推断]`；衍生内容永不冒充事实（见原则 11）
7. **核心服务层与前端解耦** — service 层返回 dataclass，CLI / Web UI / API / 技能都是薄包装
8. **扩展点开放**：新增格式在 `m_lib.EXTS` 注册；新增 OCR 后端替换 `m_ocr._get_engine()`；
   新增命令在 `m_cenhua.py` 加路由；新增前端形态基于 service 层薄包装
9. **测试守护**：`test_61_engine_is_untouched` 守护引擎纯净；`test_70_service_no_print` +
   `test_71_cli_is_thin` 防 service 回潮；全套离线测试 `bash tests/run_tests.sh`
   无需 API key；每个里程碑必须配套新增单测
10. **总结/NER 默认免费 + 全量记账仅免闸 + 长任务/批量任务豁免中途执法**
    （R2-R1 + R3-T5 + R4-F1）：
    - 写入路径的衍生分析（总结、NER、关联）规则先行、按需精化、预算硬闸
    - **树索引构建是摄取的核心成本，属显式已知成本**（不在三道闸门管辖内——
      `CENHUA_MAX_COST_CNY` 适用范围明确排除 `add`，树索引成本走 §13 既有 dry-run
      估算 + 进度可见，不设预算拒执）
    - **全量记账，仅免预算闸**：所有 LLM 调用（含 `add` 树索引、OCR 视觉兜底）一律
      写 `cost-ledger.jsonl`；`cenhua cost` 按命令分组，摄取成本单列首位
    - **★ 长任务（digest/draft）与批量任务（`refine --drain`）豁免 `CENHUA_MAX_COST_CNY`
      与 `CENHUA_MAX_LLM_CALLS` 的中途执法**，仅受各自预算启动前 all-or-nothing 检查管辖；
      三闸执法顺序：① dry-run 估价 → ② 对应任务预算 → ③ `--force`/`--max-cost` 放行通道
      （F1，治 T7 只修启动豁免的腰斩）
11. **三层 artifact 纪律 + hint-not-evidence**（R2-R5 + R3-T1 + R4-F2/F3）：
    - `primary`（原件 / 网页快照 / 硬化 PDF）：事实源，检索默认召回，可作引文（带 snippet）
    - `derived-doc`（digest / draft）：默认不召回（`--include-derived` 开启），
      展示必带 ⚠ 标记，引文穿透到 primary
    - `internal-artifact`（summaries / entities / vectors / relations）：
      **正文禁止作为事实证据进入引文**（not-evidence）；**可作为导航提示（hint 角色）
      进入 LLM prompt**——形如 `【提示，非证据】该文档主旨为 X，重点段落 P12-15`；
      基于 hint 得出的任何结论，其证据必须从 primary 正文**重新验证**后引用
    - prompt 组装两段式（**自 M2b 起生效，F3 主人裁决**）：hint（summaries）"去哪里看"
      + 证据（primary 文本层）"是什么"；hint 段带显式 `[HINT tier=internal]` 标记与证据段
      隔离；hint 段只许陈述、不许祈使（防注入）；M3a 增量为注入对抗硬化
    - **citations dataclass 含 snippet 字段**（F2）：≤80 字锚文本，从命中页摘取；
      `verify_citation(doc, page, snippet)` 校验 snippet 归一化后确实存在于该页文本层
      （NFKC 归一 + 去空白/全半角折叠后正则匹配）；ask/query 响应 schema 强制 citations
      带 snippet，无 snippet 在门禁计为失败
    - digest/draft 的引文穿透链必须穿透 internal-artifact 直达 primary 原件页码
    - 衍生文档与 internal-artifact 均不参与实体共现建边（防噪音炸弹）
    - `cenhua sources` 按三类分组显示

---

## 11. 与现有文档的关系

| 文档 | 定位 | 与本文关系 |
|---|---|---|
| design.md | 设计原则与范围 | 本文是 design 的演进版本；原则 10/11 待回写 design.md（F1 执法豁免、F2 snippet、F3 生效版本） |
| architecture.md | 技术架构与模块职责 | 本文按产品视角重组；M1a 起 service 层架构需补 |
| user-guide.md | 用户使用手册 | 本文是路线图；M3b 起需补 Web UI 与 API 手册（Nginx 仅作为可选部署附件在此提一句，F8） |
| pitfalls.md | 避坑指南 | 踩坑回写本文 §9 约束；QA fixture 语料从 pitfalls 反推 |
| service-contract.md | service 契约登记制载体（R2-R6 + R3-T8.3 + R4-F2） | **M1a 首 commit 建档**；建档时直接采用升级后契约（citations 含 snippet、verify_citation 三参签名、schema_version） |
| CENHUA-方案.md | 早期方案（MNEMOSYNE 期） | 项目起源与命名决策记录；五层架构 L1-L5 与本文 §15 数据流对应 |
| cenhua-release-kit.md | v0.1.0 发布材料包 | GitHub/ClawHub 分发渠道 |
| roadmap-review-2026-10-13.md | 一轮评审 | 本文一修输入；修订完成后归档，决策沉淀进 §12 ADR |
| roadmap-review-2026-10-13-R2.md | 二轮评审 | 本文二修输入；修订完成后归档 |
| roadmap-review-2026-10-13-R3.md | 三轮评审 | 本文三修输入；修订完成后归档 |
| roadmap-review-2026-10-13-R4.md | 四轮评审 | 本文四修输入；修订完成后归档，决策沉淀进 §12 ADR |

---

## 12. 关键决策记录（ADR）

合并 design.md §4 已有决策与一/二/三/四轮 review 裁决（仅列各轮新增 / 修订项）：

| 决策 | 选择 | 理由 | 生效版本 |
|---|---|---|---|
| 引擎集成 | 独立内嵌 pageindex-rag | 自包含、可 diff、可升级 | v0.1 |
| 语义层 | 引入向量（可选） | 覆盖"换种说法"的召回，可降级 | v0.1 |
| SKILL.md 语言 | 英文 + 中文辅助文件 | 面向国际社区 | v0.1 |
| 存储位置 | 默认 `~/.cenhua` | 数据生命周期长于技能安装 | v0.1 |
| 图片/扫描转写 | RapidOCR 本地优先 + 视觉兜底 | 免费离线，质量校验保证可信 | v0.1 |
| 提交身份 | Hugh Han | 关联 GitHub 账号 | v0.1 |
| **项目命名** | MNEMOSYNE → CENHUA | 中文语境拉风、与"树索引"同构 | v0.1 |
| **分发渠道** | GitHub（主） + ClawHub | 主仓 GitHub，技能市场走 ClawHub `world327/cenhua` | v0.1 |
| **五层架构** | L1 摄取 / L2 归一PDF / L3 文本层 / L4 知识沉淀 / L5 检索创作 | L2/L3 复用 pageindex-rag 零改动 | v0.1 |
| **目标用户收敛**（Q1） | 个人知识库用户 | 单维护人项目不应承诺企业租户/公网门户攻击面 | v0.1→v0.2 |
| **形态收敛**（Q1/Q9） | 5 形态 → 3 + 局域网 API | 删除公网搜索页与企业级多租户 | v0.1→v0.2 |
| **与 second-brain 关系**（Q2） | 思想同源、产品独立、不整合 | CENHUA 是通用化独立产品 | v0.1→v0.2 |
| **衍生分析默认免费 + 全量记账仅免闸 + 长任务/批量任务豁免中途执法**（Q3 + R2-R1 + R3-T5 + R4-F1） | 总结/NER 默认免费；规则先行 + 按需精化 + 预算硬闸；树索引是摄取固有成本不在闸门管辖；**全量记账仅免闸**；**长任务/批量任务豁免中途执法仅受各自预算启动前 all-or-nothing 检查管辖**，三闸执法顺序：① dry-run → ② 任务预算 → ③ `--force`/`--max-cost` 放行 | 防每份文档进库即多打一轮 LLM；树索引按预算拒执留半成品库；ledger 漏 add 致 cost 月报低报；T7 只修启动豁免没修中途执法，digest 跑到 ¥2.0 单命令上限先到先停仍腰斩 | v0.2→v0.6 |
| **总结默认 deferred**（Q3） | `CENHUA_SUMMARY` 默认 `deferred` | 摄取时只跑规则层 | v0.2 |
| **成本货币化护栏 + 长任务独立预算 + 货币字段**（Q4 + R2-R3 + R3-T7 + R4-F1/F9） | `--dry-run` calls+tokens+金额；`CENHUA_MAX_COST_CNY` 与 `CENHUA_MAX_LLM_CALLS` 并联；pricing.json 在 M1a 同包交付；M2b 推广至全命令；digest/draft all-or-nothing + `CENHUA_LONGJOB_MAX_COST_CNY`；**pricing.json 加 currency 字段混合货币不折算；OpenClaw 全名匹配规则** | 次数护栏对 token 失真；预算闸需单价表；长任务中途停留断头洞察；网关全名 vs 裸 id 匹配未定义 | v0.2→v0.6 |
| **`CENHUA_MAX_COST_CNY` 排除 add + 长任务/批量任务豁免中途执法**（R2-R1 + R3-T5 + R4-F1） | 树索引成本走 dry-run 估算 + 进度可见，不设预算拒执（免闸）；但全量记账（不免记账）；**长任务（digest/draft）与批量任务（refine --drain）豁免中途执法，仅受各自预算启动前检查管辖** | 摄取被预算中途拒绝留半成品；ledger 漏记致 cost 低报；T7 启动豁免被单命令预算/次数上限中途腰斩 | v0.2→v0.6 |
| **关联四层降噪 + 小库模式**（Q5 + R3-T6） | IDF + nPMI + 共现地板 + 人工阀门；自动边权 ≤0.6；**小库模式自动降档**（N<200 用更松阈值 + Laplace） | 防高共现实体让全库变全连接毛球；企业阈值套个人小库（N≈30~300）会让 related 常年空转 | v0.2.1 |
| **Service 层绞杀者抽取 + 契约登记制 + 白名单**（Q6 + R2-R6 + R3-T8.3 + R4-F2/F10） | 渐进搬家：M1a 起 6 函数签名 → 每里程碑搬一块；契约登记制（**M1a 首 commit 建档**，**建档时直接采用升级后契约**：citations 含 snippet、verify_citation 三参签名、schema_version）+ `test_71` 白名单制（**只收用户命令**，`summarize` 移出由 test_70 管辖） | 不做大爆炸式重构；契约登记防每里程碑扩张破坏 API 兼容；M1a 首 commit 杜绝"先实现后登记"窗口期；F2 snippet 升级与 F10 白名单收紧 | v0.2→v0.4 |
| **M3 拆分**（Q7） | M3 → M3a（service 完成 + digest + 任务通道 + hint 注入对抗硬化，CLI-only）+ M3b（Web UI 洞察浏览 + 局域网 API + SSE 薄适配） | 避免单里程碑捆绑多形态 | v0.4→v0.5 |
| **M1 拆分**（R3-T3） | M1 → M1a（成本与质量基础设施，可先行）+ M1b（编织，复用 M1a 换算与 verify_citation） | 拆 M3 后 M1 自己长出 8 个子系统；M1a 纯基础设施无编织依赖可先行 | v0.2→v0.2.1 |
| **三层 artifact 纪律 + hint-not-evidence + snippet + hint 提前进 M2b**（Q8 + R2-R5 + R3-T1 + R4-F2/F3） | tier=primary/derived-doc/internal-artifact；检索默认降级；引文穿透穿透 internal-artifact 直达 primary；图谱隔离；sources 分组；internal-artifact 正文禁作事实证据进引文但可作 hint 进 prompt；**citations 含 snippet，verify_citation 三参签名校验 snippet 归一化后存在于该页文本层**；**prompt 两段式自 M2b 起生效**（F3 主人裁决） | 防 provenance laundering；R2 全量封禁 internal-artifact 进 prompt 杀死 refine 消费者→hint-not-evidence；T1 语义修复被版本排期绕过→hint 提前进 M2b；verify_citation"页存在"同义反复→升级 snippet 匹配 | v0.3.1→v0.4 |
| **删除公网搜索页**（Q9） | 删除 §3.5/§6.5/M6 公网部分 | 与"本地优先、数据主权"定位冲突 | — |
| **检索质量门禁跑 fixture 不跑活库 + fixture 冻结产物 + 门禁分层 + 引文按条目计量 + snippet 校验**（Q10 + R2-R2 + R3-T2/T4 + R4-F2/F6/F7） | M1a 交付 `cenhua bench` + 内置 fixture 冻结产物（tree index + 文本层 + 30 题，零 LLM 零网络子集）；门禁分层（CI 离线阻断 / 发版流水线全量含拒答需 key）；拒答非确定性治理（temperature=0 + 重试 + flaky 转人工）；**引文按条目计量**（全量 ≥20，阈值按条目占比 ≥95%）；存在性 100% 零容忍；`verify_citation(doc, page, snippet)` 原语进 M1a | 铁律"沉默不是证据"的直接度量；用户库是活的语料增长即假回归；fixture 不冻结则"离线可跑"破产；n=10 的 ≥95% 是掷硬币；verify_citation 只验"页存在"是同义反复当质量指标 | v0.2→v0.3.1 |
| **文档卫生**（Q11） | 删除 P3/P4/P5 记号，统一 v0.x；清除 `file:///` 私链 | 公开仓库文档不应含外部死链 | — |
| **M2a/M2b 版本号分离与依赖修正**（R2-R4） | M2a → v0.3.0（网页收录，独立支线，**不含 §4.4**——R4-F5）；M2b → v0.3.1（query 延展检索，只依赖 M1b） | M2b 需语料不需"网页语料"；共版本号意味着永远捆绑发布 | v0.3.0/v0.3.1 |
| **§4.4 唯一归属 M1b**（R4-F5） | §4.4 离线增强归 M1b 唯一归属；M2a 交付物删除重复行 | M1b 与 M2a 双份承诺，两处发布各自以为对方做了或同一功能计两次工时 | v0.2.1/v0.3.0 |
| **Playwright 默认安装 + WSL2 系统库对策**（R2-R7 + R3-T9） | requirements 默认装；setup 有 sudo 用 `--with-deps` 同装系统库，无权限警告；doctor chromium 启动自检（spawn about:blank）；自检失败自动降级静态抓取 | 否决 optional extra；默认装保证 `--url` 开箱即用；WSL2 缺 libnss3/libatk 必崩 | v0.3.0 |
| **任务通道 + SSE 薄适配**（R2-R9） | service 契约新增 submit/job_status/job_result 任务接口；LLM 长任务统一走任务通道；M3a 落，M3b SSE 是薄适配 | CLI/Web/API 共用同一进度协议；断线重连天然安全 | v0.4→v0.5 |
| **任务通道持久化边界**（R4 §4 强制裁决） | **M3a 开工前必须拍板**——重启后未完成任务的续跑或标废策略，不得再顺延 | R2/R3/R4 连续三轮预告未关闭 | v0.4 开工前 |
| **M4 力导向图加发布条件**（R2-R8） | CLI 邻接表 + Mermaid 无条件；Web UI 力导向图仅 M3b 已发布时交付 | M4 不强依赖 M3b，但 Web 力导向图需 M3b 前端存在 | v0.6 |
| **命名卫生 + 租户残肢清除 + 删 Nginx/open_id**（R2-R10 + R3-T8 + R4-F8） | `max_llm_calls` → `CENHUA_MAX_LLM_CALLS`；§2.2 标题改述；graph/draft API 加版本脚注；删 `X-Agent-Id` 行级过滤与 `user_mapping.json`，`CENHUA_API_ALLOWED_AGENTS` 并入单 token；**删 Nginx 反代叙述改 uvicorn timeout_keep_alive；日志脱敏示例去 open_id 改 token/绝对路径/PI_KEY 前缀** | env 名对齐 `CENHUA_*` 前缀；端点版本透明；与 Q1 形态收敛对齐清除租户残肢；产品无组件反代与飞书概念 | v0.2→v0.5 |
| **hint-not-evidence 角色规则 + hint 提前进 M2b + 注入对抗硬化**（R3-T1 + R4-F3） | internal-artifact 正文禁作事实证据进引文，但可作 hint 进 prompt；prompt 两段式（hint+证据）带 `[HINT tier=internal]` 标记；hint 段禁祈使防注入；基于 hint 得出的结论必须从 primary 重新验证；**两段式自 M2b 起生效**（F3 主人裁决）；M3a 改为注入对抗硬化（指令剥离、fixture 注入对抗题至少 1/3 人工撰写、hint 二段验证成本计入 refine ROI） | R2 全量封禁 internal-artifact 进 prompt 杀死 refine 消费者；T1 语义修复被版本排期绕过（M1b 交付 refine，hint 消费却排 M3a，中间横跨 M2b 全程）→ hint 提前进 M2b；预算设置与用户可见价值同版本出现 | v0.3.1→v0.4 |
| **digest/draft all-or-nothing + 独立长任务预算 + 豁免中途执法**（R3-T7 + R4-F1） | 启动前三闸执法顺序检查，超 `CENHUA_LONGJOB_MAX_COST_CNY`（默认 5.0）拒绝启动绝不中途停；`--force`/`--max-cost` 放行；**豁免 `CENHUA_MAX_COST_CNY`/`CENHUA_MAX_LLM_CALLS` 中途执法**；断点续跑 M4 前不做 | R1 豁免 add 的理由对 digest/draft 同样成立；T7 只修启动豁免没修中途执法，digest 跑到 ¥2.0 单命令上限先到先停仍腰斩；次数轴更糟全库扫描动辄 30+ 调用 8 次上限必拦 | v0.4→v0.6 |
| **verify_citation 升级 snippet 页内匹配**（R4-F2） | 原语签名升级为 `verify_citation(doc, page, snippet) -> bool`——校验 snippet 归一化后确实存在于该页文本层（NFKC 归一 + 去空白/全半角折叠后正则匹配）；citations dataclass 新增 snippet 字段（≤80 字锚文本）；ask/query 响应 schema 强制 citations 带 snippet，无 snippet 在门禁计为失败；M1a 首 commit 建档时 schema_version 即含 snippet | T4 定义的校验"页存在"是同义反复——引用一个存在但内容错误的页照样通过，门禁数字好看但无意义 | v0.2→v0.6 |
| **fixture 冻结产物 + 门禁分层 + 拒答非确定性治理 + 引文按条目计量**（R4-F6/F7） | fixture 是冻结产物（随包分发已建好的 tree index + 文本层 + 30 题，bench 不重建索引，存在性+溯源子集零 LLM 零网络）；门禁分层（CI 离线阻断 / 发版流水线全量含拒答需 key，无 key 跳过并在 release notes 标注）；拒答非确定性治理（temperature=0 + 重试 1 次 + 连续 2 版 flaky 转人工仲裁 `meta/qa/flaky.jsonl`）；引文按条目计量（全量 ≥20，阈值按条目占比 ≥95%）；存在性 100% 零容忍；失败输出逐条 diff 清单 | fixture 不冻结则 bench 建索引烧 LLM "离线可跑"破产；"离线测试绿"与"拒答门禁阻断需 key"冲突；n=10 的 ≥95% 是掷硬币阈值（1 对一错摆动 10pp） | v0.2→v0.3.1 |
| **M3b 创造模块收敛为洞察浏览 + 草稿编辑移 M4 + 矩阵拆格 + 编织行双标**（R4-F4/F11） | M3b 创造模块收敛为洞察浏览（digest 只读）；草稿编辑/引文悬浮/版本对比三行移入 M4；§2.3 矩阵"④创造 × Web UI"拆两格（v0.5 洞察浏览 → v0.6 草稿编辑）；"②编织 × CLI/技能"恢复 ✅(半)+📋 v0.2 双标 | M3b 画 M4 才有的草稿饼（同款错误反向再犯）；纯 📋 否定了 v0.1 已交付的 vault 分库/树索引/引文溯源/向量层能力 | v0.5→v0.6 |
| **digest 事件触发改 watch 打印提示**（R4-F10） | 删除"摄取量超阈值自动建议跑一次"；改为 `watch` 累计摄取 N 篇（默认 20）后在进度日志打印一行提示 `提示：自上次洞察以来已摄取 N 篇，可运行 cenhua digest --dry-run 估价`；无任何自动触发执行 | 产品无守护进程与通知通道，"自动建议"无载体 | v0.4 |
| **test_71 白名单去 summarize**（R4-F10） | `test_71_cli_is_thin` 白名单只收用户命令（related/refine/cost/bench/query/digest/draft…）；`summarize` 不是用户命令（无 CLI 面）移出白名单，其 service 函数由 test_70 管辖 | `summarize` 从未在 CLI 面暴露，白名单概念错位 | v0.2.1 |

---

## 13. 风险与对策（合并自 CENHUA-方案.md §8 + review + R2/R3/R4）

| 风险 | 状态 | 对策 |
|---|---|---|
| `pageindex` 仅官方 PyPI 有 | ✅ 已落地 | 安装固定 `--index-url pypi.org` + `--no-deps`；`cenhua doctor` 自检 |
| 成本失控（`ask --all` 每文档一次 LLM） | ✅ 已落地 | `--dry-run` 默认；`CENHUA_MAX_LLM_CALLS` 默认 8；超限需 `--force` |
| 静默空白 PDF（`insert_htmlbox`） | ✅ 已落地 | 0.85 字符完整性校验；`doctor` 扫描空文本层标 PROBLEM |
| 加密 PDF 被静默跳过 | ✅ 已落地 | 文件名口令尝试 + "双路径一致才敢说没有"纪律 |
| 扫描/图片 OCR 成本与质量 | ✅ 已落地 | RapidOCR 本地优先 + 质量门校验 + 视觉兜底 |
| vision 模型需裸 model id | ✅ 已落地 | `setup` 时 `/models` 探测；`PI_VISION_MODEL` 裸 ID |
| 索引慢（52 页≈140s） | ✅ 已落地 | `watch` 后台 + 进度写 `logs/` + `status` 显示进行中 |
| 写入路径 LLM 成本失控（Q3） | 📐 v0.2 对策 | 衍生分析默认免费（规则先行 + 按需精化 + 预算硬闸） |
| 关联全连接毛球（Q5） | 📐 v0.2.1 对策 | 四层降噪 + 自动边权 ≤0.6 |
| 关联常年空转（小库统计学坍塌，R3-T6） | 📐 v0.2.1 对策 | 小库模式自动降档，`cenhua hub` 显示档位 |
| 引文洗白 provenance laundering（Q8 + R2-R5） | 📐 v0.3.1 对策 | 三层 artifact + 检索默认降级 + 引文穿透 + 图谱隔离 + sources 分组 |
| refine 没有消费者 + 排期缺口（R3-T1 + R4-F3） | 📐 v0.3.1 对策 | hint-not-evidence 角色 + **prompt 两段式自 M2b 起生效**；M3a 注入对抗硬化（指令剥离、fixture 注入对抗题至少 1/3 人工撰写） |
| 网页渲染超时/被反爬 | 📋 v0.3.0 对策 | 60s 硬上限降级静态抓取；robots.txt 遵循；同域名速率限制 |
| Playwright 安装负担 + WSL2 缺系统库必崩（R2-R7 + R3-T9） | 📋 v0.3.0 对策 | requirements 默认装 + setup 有 sudo 用 `--with-deps` + doctor chromium 启动自检 + 自检失败自动降级静态抓取 |
| LLM 网关挂起致 SSE 空转 | 📋 v0.5 对策 | 任务通道（M3a 落）+ 空闲 10s 心跳 + 30s 探测 + 短总兜底；透传 `response.failed` |
| service 层回潮 | 📋 v0.2 对策 | `test_70_service_no_print`（service 全量）+ `test_71_cli_is_thin`（白名单制，只收用户命令） |
| service 契约透支（R2-R6 + R3-T8.3 + R4-F2） | 📋 v0.2 对策 | 契约登记制（M1a 首 commit 建档，**直接采用升级后契约**含 snippet/三参签名）+ dataclass 只加字段不删改 + schema_version 读侧容忍 |
| 树索引成本被用户当营销条款验收反噬（R2-R1） | 📐 v0.2 对策 | 原则 10 措辞降级为"总结/NER 默认免费"；`CENHUA_MAX_COST_CNY` 排除 add |
| ledger 漏记 add 致 cost 月报系统性低报（R3-T5） | 📐 v0.2 对策 | 全量记账仅免闸——所有 LLM 调用（含 add 树索引、OCR 视觉兜底）一律写 ledger；`cenhua cost` 按命令分组摄取成本单列首位 |
| QA 门禁跑活库致语料增长假回归（R3-T2） | 📐 v0.2 对策 | `cenhua bench` 默认跑 fixture 冻结语料（阻断级）；用户库 QA 报告模式 |
| 门禁引用 M4 校验器依赖倒置（R3-T4） | 📐 v0.2 对策 | `verify_citation(doc, page, snippet)` 原语进 M1a；M4 `draft --verify` 反向包装 |
| digest/draft 中途预算停留半成品 + 单命令预算/次数上限腰斩（R3-T7 + R4-F1） | 📐 v0.4→v0.6 对策 | all-or-nothing + 独立长任务预算 `CENHUA_LONGJOB_MAX_COST_CNY`（默认 5.0）+ **豁免 `CENHUA_MAX_COST_CNY`/`CENHUA_MAX_LLM_CALLS` 中途执法**，仅受各自预算启动前 all-or-nothing 检查管辖；三闸执法顺序：① dry-run → ② 任务预算 → ③ `--force`/`--max-cost` 放行 |
| verify_citation 同义反复校验（R4-F2） | 📐 v0.2 对策 | 升级为 `verify_citation(doc, page, snippet) -> bool`，校验 snippet 归一化后确实存在于该页文本层（NFKC + 去空白/全半角折叠后正则匹配）；citations dataclass 含 snippet 字段；ask/query 响应 schema 强制带 snippet |
| fixture 门禁三处工程矛盾（R4-F6） | 📐 v0.2 对策 | fixture 是冻结产物（tree index + 文本层 + 30 题，bench 不重建索引，存在性+溯源子集零 LLM 零网络）；门禁分层（CI 离线阻断 / 发版流水线全量含拒答需 key，无 key 跳过并在 release notes 标注）；拒答非确定性治理（temperature=0 + 重试 + flaky 转人工仲裁 `meta/qa/flaky.jsonl`） |
| n=10 的 ≥95% 掷硬币阈值（R4-F7） | 📐 v0.2 对策 | 引文按条目计量（每题挂多个引用点，全量 ≥20，阈值按条目占比 ≥95%）；存在性 100% 零容忍；失败输出逐条 diff 清单 |
| M3b 画 M4 草稿饼 + §4.4 双份承诺 + 矩阵现状倒退（R4-F4/F5/F11） | 📐 v0.5→v0.6 对策 | M3b 创造模块收敛为洞察浏览，草稿编辑移 M4；§4.4 唯一归 M1b；矩阵"④创造 × Web UI"拆两格（v0.5 洞察浏览 → v0.6 草稿编辑），"②编织 × CLI/技能"恢复 ✅(半)+📋 v0.2 双标 |
| 部署约束残留租户时代器官（R4-F8） | 📐 全文对策 | 删 Nginx 反代叙述改 uvicorn `timeout_keep_alive` 与请求级 timeout；Nginx 仅作为可选部署附件在 user-guide 提一句；日志脱敏去 open_id 改 token/绝对路径/PI_KEY 前缀 |
| pricing 货币与网关匹配未定义（R4-F9） | 📐 v0.2 对策 | pricing.json 加 `currency` 字段（per-model），混合货币不强行折算（显示 `¥0.35 + $0.02` 加汇率提示脚注）；OpenClaw 全名匹配规则：先按 `openclaw:provider/model` 全名精确匹配 → 再按裸 model id 匹配 → 未命中保守默认价 |
| hint 进 prompt 的注入面（R3 §4 + R4 §4 预告） | 📋 v0.4 实施期自查 | hint 段只许陈述、不许祈使（M2b 首发即硬规则化）；fixture 注入对抗题至少 1/3 人工撰写；hint 二段验证成本计入 refine ROI 账 |
| 冻结 fixture 与引擎升级断裂（R4 §4 预告） | 📋 实施期自查 | fixture 绑定 `engine_version`；提供 `bench --rebuild`（显式重建，烧 LLM 需确认） |
| snippet 摘取的诚实性（R4 §4 预告） | 📋 实施期自查 | snippet 由 LLM 摘录可能摘错页文本；verify 只证"该句在该页"不证"该句支撑该结论"；引文准确率诚实上限是逐字可溯率，文档措辞不得升格为"语义正确率" |
| 任务通道持久化边界（R2/R3/R4 连续三轮预告） | 📋 **M3a 开工前必须拍板** | 重启后未完成任务的续跑或标废策略，本轮仍无裁决——不得再顺延 |

---

## 14. 配置项速查

来源 architecture.md §5。优先级 `ENV > vault.yaml > 默认`。

| 配置 | 来源 | 默认 | 说明 |
|---|---|---|---|
| `CENHUA_HOME` | env | `~/.cenhua` | 存储根 |
| `CENHUA_OCR` | env / `vault.yaml: ocr` | `rapidocr` | `vision` 强制走大模型 |
| `CENHUA_OCR_MIN_CONF` | env / `vault.yaml: ocr_min_conf` | `0.5` | 平均置信度阈值 |
| `CENHUA_OCR_MIN_CHARS` | env / `vault.yaml: ocr_min_chars` | `10` | 最少识别字符数 |
| `CENHUA_SUMMARY` | env / `vault.yaml: summary` | `deferred` | `off` / `eager`（不推荐）/ `deferred` |
| `CENHUA_REFINE_BUDGET_CNY` | env / `vault.yaml: refine_budget` | `0` | 精化预算硬闸（0=只允许规则层）；**`refine --drain` 批量任务仅受此管辖，豁免 `CENHUA_MAX_COST_CNY`/`CENHUA_MAX_LLM_CALLS` 中途执法**（F1） |
| `CENHUA_MAX_COST_CNY` | env / `vault.yaml: max_cost` | `2.0` | 单命令花费上限，与 `CENHUA_MAX_LLM_CALLS` 并联先到先停；**不适用 `add`/`watch`（摄取无预算拒执）；不适用 digest/draft/refine --drain（长任务/批量任务豁免中途执法，F1）** |
| `CENHUA_LONGJOB_MAX_COST_CNY` | env / `vault.yaml: longjob_max_cost` | `5.0` | **长任务（digest/draft）独立预算**（T7）；all-or-nothing，超预算拒绝启动绝不中途停 |
| `CENHUA_MAX_LLM_CALLS` | env / `vault.yaml` | `8` | 单命令 LLM 调用次数上限（辅助护栏）；命令行参数 `--max-llm-calls` 保留；**不适用 digest/draft/refine --drain（豁免中途执法，F1）** |
| `CENHUA_SMALL_CORPUS_N` | env / `vault.yaml: small_corpus_n` | `200` | **小库模式降档触发阈值**（T6）；N<此值时四层降噪用更松阈值 + Laplace 平滑 |
| `PI_BASE`/`PI_KEY`/`PI_MODEL` | env | — | LLM 网关 |
| `PI_VISION_MODEL` | env | — | 视觉兜底模型（裸 ID） |
| `PI_EMBED_MODEL` | env | — | 向量模型 |
| `CENHUA_API_TOKEN` | env | — | 局域网 API 鉴权 token（v0.5 起；T8.2 合并 `CENHUA_API_ALLOWED_AGENTS` 为单 token） |
| `pricing.json` | 随包分发，可覆盖 | — | model → {in, out, **currency**} 每 1K token 价格表（**M1a 起**，R2-R3 + R4-F9）；**OpenClaw 全名匹配规则**：先按 `openclaw:provider/model` 全名精确匹配 → 再按裸 model id 匹配 → 未命中保守默认价 + 输出标注 |

> **迁移兼容**（R2-R10）：`max_llm_calls` → `CENHUA_MAX_LLM_CALLS` 迁移需兼容旧 env 名
> 一个版本（读取时 deprecation warning 并 fallback 到新名）。
> **配置删除**（T8.2）：`CENHUA_API_ALLOWED_AGENTS` 删除，并入 `CENHUA_API_TOKEN` 单 token 白名单。

---

## 15. 关键数据流

### 15.1 摄取流（含本地 OCR + 网页 + 规则先行总结 + 三层 artifact + 全量记账）

```
用户投放文件到 inbox/ 或提交 URL
  → cenhua add --inbox | --url | watch
  → ingest_one():
      sha1 去重（命中则跳过）
      ┌─ URL 来源: m_web.py 渲染 → PDF + HTML 快照 (tier=primary, source=url)
      └─ 文件来源: 直接进预转换 (tier=primary)
      → m_ocr.preconvert():
          图片/扫描 PDF → RapidOCR 本地转写 → 质量校验
          不达标/缺失 → 返回原文件（视觉兜底, 全量记账）
      → run_engine(pi_ingest.py, [engine_in])  ★ 树索引成本: 摄取固有, 不受 CENHUA_MAX_COST_CNY 管
                                              ★ 但全量记账 (T5): 写 cost-ledger.jsonl
      → 成功: restore_provenance() 台账指回原始上传
      → 自动 flatten 建文本层
      → [v0.2.1] m_summarize 规则层:
          首段 + 正则实体粗提 + TF 关键词 + 标题结构
          → meta/summaries/<doc>.json (status=rule-only, tier=internal-artifact)
      → [v0.2.1] 首次被 query/related 命中 → 入 meta/refine_queue.jsonl
      → [v0.2.1] cenhua refine --drain 消费队列 (批量任务, 豁免中途执法, F1):
          三闸执法顺序: ① dry-run 估价 → ② CENHUA_REFINE_BUDGET_CNY → ③ --force 放行
          估算 token + 金额 (复用 M1a pricing.json + 换算函数, 含 currency)
          → 超预算拒 → 跑 LLM 精化
          → 更新 summaries/<doc>.json (status=refined, tier=internal-artifact)
          → 写 cost-ledger.jsonl
```

### 15.2 检索流（三路融合 + 关联推荐 + 三层 artifact + hint 两段式 prompt，M2b 起生效）

```
cenhua query "ABC 合同违约金"
  → 默认只在 primary 层召回 (--include-derived 显式开启 derived-doc 层)
  → 并行三路:
      find:  本地正则扫 engine/text/*.txt  (免费、毫秒)
      seek:  向量语义召回  (可选层, tier=internal-artifact, 仅作加速结构)
      ask:   树导航定位相关页 → LLM 总结  (成本护栏 calls+tokens+金额)
  → 合并去重，按置信度排序
  → LLM 基于命中做总结延展 ★ prompt 两段式 (T1, ★自 M2b 起生效, F3 主人裁决):
      hint 段 (refined summaries, tier=internal-artifact): "去哪里看"
        带显式 [HINT tier=internal] 标记, 与证据段隔离
        只许陈述, 不许祈使 (防注入, M2b 首发即硬规则化, M3a 加注入对抗硬化)
      证据段 (primary 文本层): "是什么"
      ★ 禁止引用 internal-artifact 正文作为事实证据 (not-evidence)
      ★ 禁止直接引用 derived-doc (digest/draft) 正文
      ★ 基于 hint 得出的结论必须从 primary 正文重新验证后引用
  → cenhua related: 跨文档关联推荐 (tier=internal-artifact, 仅作加速结构)
      四层降噪: IDF 过滤 → nPMI 显著性 → 共现地板 → 人工阀门
      小库模式 (N<200): 更松阈值 + Laplace 平滑
      输出每条边带证据: "共现于 [docA P3, docB P12], nPMI=0.41"
      自动边权 ≤0.6；人工 link 边权 0.8
  → 输出四段: 命中 + 延展 + 引文(含 snippet) + 关联
  → 引文穿透: 衍生命中带 derived_from 链, 穿透 internal-artifact 与 derived-doc
       直达 primary 原件页码
  ★ citations 强制带 snippet (F2): 无 snippet 在门禁计为失败, 倒逼 prompt 输出规范
```

### 15.3 创造回流闭环（三层标记 + 图谱隔离 + all-or-nothing + 豁免中途执法）

```
cenhua digest --weekly  |  cenhua draft "主题"
  → 走任务通道 (M3a 起: submit → job_status → job_result)
  → all-or-nothing + 豁免中途执法 (T7 + F1):
      三闸执法顺序: ① dry-run 估价 → ② CENHUA_LONGJOB_MAX_COST_CNY (默认 5.0) →
        ③ --force / --max-cost 放行通道
      超预算 → 拒绝启动 (绝不中途停, 防断头洞察)
      豁免 CENHUA_MAX_COST_CNY / CENHUA_MAX_LLM_CALLS 中途执法
      中途执法唯一保留项: 硬件级异常 (网关连续失败) 走既有 try/except 降级, 标 FAILED 不落半成品
  → 召回: 走 §15.2 检索流 (默认只召回 primary)
  → LLM 生成洞察文章 / 草稿
  → 嵌入 [doc P页] + snippet 引文 (穿透到 primary, 穿透 internal-artifact 与 derived-doc)
  → 存档: <vault>/works/digests/ | drafts/
       tier=derived-doc
       derived_from: [原 doc_id 列表]
  → 回流: 自动作为新文档进 inbox 走摄取闭环 (tier=derived-doc)
       ★ 创造的知识可被检索，但默认不召回 (--include-derived 显式开启)
       ★ 衍生命中显示 "⚠ 衍生内容（由 X 生成）"
       ★ derived-doc 与 internal-artifact 均不参与实体共现建边 (防噪音炸弹)
```

---

## 16. 离线能力清单

下列命令/端点**完全离线**，无需 LLM（参考 user-guide.md §7）：

```
find · read · list · flatten · status · doctor · sources · vaults · use · rm · config
bench (fixture 冻结产物: 存在性+溯源题离线可跑; 拒答题需 LLM)
```

需要 LLM 的：

```
add (建索引, 树索引成本=摄取固有, 不受 CENHUA_MAX_COST_CNY 管, 但全量记账) · ask · seek (向量层)
query (v0.3.1 总结延展, hint 两段式) · refine (v0.2.1 精化) · digest (v0.4 洞察) · draft (v0.6 草稿)
bench --corpus (用户库 QA 拒答题)
```

**局域网 API 离线端点**（v0.5 起）：

```
GET  /api/v1/documents
POST /api/v1/find
GET  /api/v1/relations
GET  /api/v1/graph            # (v0.6 起，随 M4 交付；v0.5 返回 404 + 版本提示)
```

> fixture 子集（存在性+溯源题）零 LLM 零网络（F6.1），CI 层离线阻断；
> 拒答题需 API key，发版流水线阻断（F6.2）。

---

## 17. 落地优先级总览

| 优先级 | 里程碑 | 主要交付 | 形态 |
|---|---|---|---|
| ✅ 已成 | M0 v0.1.0 | CLI + 技能 + 离线检索 + 护栏 | A + B |
| 🚧 高 | M1a v0.2.0 | 成本与质量基础设施（pricing+currency + 换算 + ledger 全量记账 + cost + 校准 + bench fixture 冻结产物 + verify_citation 三参 snippet + service-contract 建档直接采用升级后契约） | A + B |
| 🚧 高 | M1b v0.2.1 | 编织（deferred 总结 + refine hint 待 M2b + 四层降噪+小库模式 + §4.4 唯一归属 + related/refine/cost/bench 入 service；summarize 由 test_70 管辖） | A + B |
| 🚧 高（并行）| M2a v0.3.0 | 网页收录（Playwright 默认装 + WSL2 系统库对策 + doctor 启动自检；**不含 §4.4**） | A + B |
| 🚧 高 | M2b v0.3.1 | `query` 延展检索 + ★ hint 两段式 prompt 首发 + cost 推广全命令 + 拒答门禁（跑 fixture，分层+flaky 治理）+ 三层 artifact | A + B |
| 📋 重大 | M3a v0.4.0 | service 层完成 + digest（all-or-nothing+豁免中途执法）+ 任务通道（**持久化边界开工前必拍板**）+ hint 注入对抗硬化 + 三层 artifact 闭环（CLI-only） | A + B |
| 📋 重大 | M3b v0.5.0 | 本地 Web UI（**洞察浏览，草稿编辑移 M4**）+ 局域网 API（单 token，清除租户残肢）+ SSE 薄适配 | **C** + 局域网 API |
| 📋 高 | M4 v0.6.0 | 知识图谱 + 主题创作 draft（all-or-nothing + 独立预算 + 豁免中途执法 + draft --verify 包装升级后 verify_citation）+ ★ Web 草稿编辑三件套（从 M3b 移入） | A + B + C |

**关键拐点**：M1a 是成本与质量基础设施点（可先行无编织依赖）；M2b 是 hint 两段式
prompt 首发点（refine 自此有消费者）；M3a 是 service 层完成点 + 任务通道落地点 +
hint 注入对抗硬化点，M3b 才让 Web UI 名副其实是薄包装（SSE 只是其薄适配，洞察浏览
只读）。M3b 失败产品仍是完整 CLI（个人用户 90% 场景）。

---

## 18. 遗留事项（合并 review §3 + R2/R3/R4 §3）

- [x] roadmap.md 按一轮评审修订（一修完成）
- [x] roadmap.md 按二轮评审 R1-R10 修订（二修完成）
- [x] roadmap.md 按三轮评审 T1-T9 修订（三修完成）
- [x] roadmap.md 按四轮评审 F1-F11 修订（四修完成，本文即完成）
- [ ] design.md：原则 10 增补"全量记账仅免闸 + 长任务/批量任务豁免中途执法"（T5+F1）；
  原则 11 增补 hint-not-evidence 完整规则（F2 snippet 强制、F3 生效版本 v0.3.1、
  执法豁免边界）
- [ ] `docs/service-contract.md` 建档（**M1a 首 commit**，T8.3；**建档时直接采用升级后
  契约**：citations 含 snippet、verify_citation 三参签名、schema_version——F2）
- [ ] fixture 冻结产物制作流程（合成语料 → 建索引 → 冻结打包，M1a 交付物内完成；
  绑定 `engine_version`，提供 `bench --rebuild`——R4 §4 预告）
- [ ] pricing.json `currency` 字段与 OpenClaw 全名匹配规则落 M1a（F9）
- [ ] README 形态叙述同步（R1 遗留，仍未关闭，随 roadmap 修订一并处理）
- [ ] architecture.md 同步补 service 层架构（M1a 起）+ 任务通道架构（M3a 起）+
  hint 两段式 prompt 架构（**M2b 起**，F3）
- [ ] `max_llm_calls` → `CENHUA_MAX_LLM_CALLS` 迁移需兼容旧 env 名一个版本（deprecation warning）
- [ ] `CENHUA_API_ALLOWED_AGENTS` 删除迁移：旧配置读取时 warn 并降级为单 token 模式（T8.2）
- [ ] **★ 任务通道持久化边界**（R2/R3/R4 连续三轮预告，**M3a 开工前必须拍板**）：
  重启后未完成任务的续跑或标废策略——本轮仍无裁决，不得再顺延
- [ ] **实施期自查**（R3 §4 + R4 §4 预告，不阻塞发版）：
  - hint 注入面：hint 段指令剥离 + fixture 加注入对抗题至少 1/3 人工撰写
  - hint 二段验证成本：验证轮次 token 开销计入 refine ROI 账
  - 用户库 QA 报告模式告警阈值：引文准确率连续下滑时主动提示重新出题
  - 冻结 fixture 与引擎升级断裂：绑定 `engine_version` + 提供 `bench --rebuild`
  - snippet 摘取的诚实性：verify 只证"该句在该页"不证"该句支撑该结论"；引文准确率
    诚实上限是逐字可溯率，文档措辞不得升格为"语义正确率"

---

*本文档随版本演进持续更新；新坑回写 pitfalls.md，设计原则变更回写 design.md，
技术架构变更回写 architecture.md，service 契约变更回写 service-contract.md。
评审历史见 [一轮](roadmap-review-2026-10-13.md)、[二轮](roadmap-review-2026-10-13-R2.md)、
[三轮](roadmap-review-2026-10-13-R3.md) 与 [四轮](roadmap-review-2026-10-13-R4.md)。*
