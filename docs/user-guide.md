# CENHUA 用户使用手册（User Guide）

> 岑华 · 个人第二大脑。本文档面向最终用户，覆盖安装、日常使用、检索、本地
> OCR 与常见操作。智能体（OpenClaw/Hermes）用户请同时参考 `SKILL.md`。

## 1. 安装

### 1.1 通过智能体（推荐）

把 GitHub 链接发给你的智能体：

```
install this skill: https://github.com/world327/cenhua
```

或手动：

```bash
openclaw skills install git:github.com/world327/cenhua
openclaw skills check          # cenhua 应显示 ✓ ready
```

首次运行（智能体或你自己）：

```bash
~/.openclaw/skills/cenhua/bin/cenhua setup
```

### 1.2 纯 CLI

```bash
git clone https://github.com/world327/cenhua && cd cenhua
./bin/cenhua setup                    # 安装依赖 + 建默认库
export PI_BASE=https://api.example.com/v1  PI_KEY=***  PI_MODEL=openai/gpt-4o-mini
```

### 1.3 安装时的两个确认

安装时智能体会向你确认两件事（不可代答）：

1. **LLM 网关**：复用 OpenClaw 配置，还是自填 `PI_BASE/PI_KEY`。
2. **知识库存储位置**：默认 `~/.cenhua`，还是安装目录。

## 2. 快速上手

```bash
# 建库（按项目/领域分库）
cenhua init contracts --title "客户合同"

# 投放文件到 inbox
cp ~/Downloads/*.pdf ~/.cenhua/vaults/contracts/inbox/

# 摄取
cenhua add --inbox          # 或后台常驻: cenhua watch

# 检索
cenhua find 违约金 penalty  # 存在性，离线免费
cenhua ask --doc contract "终止罚则是什么" --dry-run   # 先估算成本
cenhua ask --doc contract "终止罚则是什么"
```

## 3. 命令速查

```
VAULTS    init · vaults · use · status · doctor · rm · config · sources
          backup [--dest PATH] [--yes] · restore <backup.tar.gz> [--name N] [--yes]   （v0.7.0 起，tar.gz 备份/恢复）
INTAKE    add <files|dir|--inbox> · add --url <url> [--url ...] ·
          add --url-file <path> [--no-render] · watch [--interval N] [--once] [--urls]
          （.eml/.msg 邮件自动展开附件，v0.3.2 起）
RETRIEVE  find <terms> [-d doc] [-i] [-r] · read <doc> [-p N] [-g re] · list
QUERY     query "问题" [--include-derived] [--dry-run] [--force] [--top N]
          [--session SID] [--no-rerank]
          四段输出：直接命中 + 总结延展 + 内容出处 + 关联推荐（v0.3.3 起）；
          多轮上下文继承 + 小模型重排（v0.6.2 起，重排默认开）
DEEP READ ask [--doc kw | --all] "q" [--limit N] [--dry-run]   (成本护栏)
INSIGHT   digest --weekly | --monthly | --quarterly | --since YYYY-MM-DD
          [--dry-run] [--force] [--max-cost N]
          四节洞察文章，自动回流入库 tier=derived-doc（v0.4.0 起）
GRAPH     graph entity <实体> · path <A> <B> · cluster · mermaid ·
          rebuild · triples [--doc kw|--all] [--limit N]（v0.6.0 起）
DRAFT     draft "主题" [--top N] · --extend/--rewrite <段号> ·
          --list · --diff "主题" Va Vb · --verify · --restore <版本>
          产物 works/drafts/<主题>_V{N}_<日期>.md，tier=derived-doc（v0.6.0 起）
TEMPLATE  template --list · template <id> · template --add <id> [--name N]
          (--section S ... | --sections A,B) [--force]（离线）
          template <id> "主题" [--top N] [--dry-run] [--force] [--max-cost X]
          内置报告/备忘录/邮件/周报 + meta/templates/ 自定义（v0.6.2 起）
EXPORT    export <works/drafts 内文件名.md> [--md|--html|--pdf]
          产物 works/exports/<同名>.<fmt>，纯离线（v0.6.2 起）
SEMANTIC  index build|status · seek "question"     (可选向量层)
WEAVING   related <doc> · link <A> <B> · link --ban <E1> <E2> · hub ·
          weave rebuild · refine [--all --dry-run | --drain [--force]]
COST      cost [--month YYYY-MM]     成本月报，按命令分组，摄取成本单列首位
QUALITY   bench [--corpus]           质量门禁：fixture（阻断）/ 用户库（报告）
WEB       web [--host H] [--port P]  本地 Web UI + 局域网 API
          （默认 127.0.0.1:8765；v0.5.0 起，需 CENHUA_API_TOKEN）
```

## 4. 日常使用

### 4.1 投放文件

每个库只有一个用户目录：`~/.cenhua/vaults/<库名>/inbox/`。把任何格式丢进去
（pdf / docx / pptx / xlsx / xls / md / txt / html / csv / 图片 / 扫描件），
然后 `cenhua add --inbox` 或让 `cenhua watch` 常驻。

- sha1 去重，重复投放不重复计费。
- 失败文件进 `inbox/.failed/`，原因写进 `logs/`，绝不静默丢弃。
- 摄取成功后自动重建文本层，`find` 结果始终可信。

### 4.2 图片与扫描件（本地 OCR）

图片和扫描 PDF 默认用 **RapidOCR 本地识别**（免费、离线），并做质量校验：

- 平均置信度 ≥ 0.5 且识别字符 ≥ 10 才被信任。
- 不达标或 RapidOCR 缺失时，自动回退到视觉大模型。

#### 阈值配置实例

两个阈值支持 **env** 和 **vault.yaml** 两种方式，**env 优先于 vault.yaml**。

**方式 A：环境变量（临时，本次会话/进程生效）**

```bash
# 提高置信度要求：平均置信度 < 0.6 的图片走视觉大模型兜底
export CENHUA_OCR_MIN_CONF=0.6

# 提高最少字符要求：识别字符 < 20 的图片走视觉大模型兜底
export CENHUA_OCR_MIN_CHARS=20
```

**方式 B：vault.yaml（持久，写入库配置）**

```bash
# 用 cenhua config 写入（推荐，自动写入 vault.yaml）
cenhua config ocr_min_conf 0.6
cenhua config ocr_min_chars 20

# 或直接编辑 ~/.cenhua/vaults/<库名>/vault.yaml，追加两行：
#   ocr_min_conf: 0.6
#   ocr_min_chars: 20
```

**优先级：env 覆盖 vault.yaml**

```bash
# vault.yaml 里是 0.8，但本次运行用 env 覆盖为 0.9
CENHUA_OCR_MIN_CONF=0.9 cenhua add --inbox
```

**阈值含义与效果**

| 配置 | 默认 | 含义 | 调高后 |
|---|---|---|---|
| `CENHUA_OCR_MIN_CONF` / `ocr_min_conf` | `0.5` | 平均置信度下限 | 更多低质量图片走大模型兜底 |
| `CENHUA_OCR_MIN_CHARS` / `ocr_min_chars` | `10` | 最少识别字符数 | 更短的识别结果走大模型兜底 |

判断逻辑：`平均置信度 >= min_conf 且 识别字符 >= min_chars` 才信任本地 OCR，
否则触发视觉大模型兜底。

强制走大模型：

```bash
export CENHUA_OCR=vision
# 或写入库配置: cenhua config ocr vision
```

### 4.3 网页收录（v0.3.0 · M2a 起）

把网页 URL 发给 CENHUA，自动抓取 → 生成产物 → 走标准摄取闭环：

```bash
# 单个 / 多个 URL
cenhua add --url https://example.com/article
cenhua add --url https://a.com/1 --url https://b.com/2

# 从文件读（每行一个 URL，# 开头为注释）
cenhua add --url-file urls.txt

# 禁用渲染，直接静态抓取（快，但 JS 重页面内容不全）
cenhua add --url https://example.com --no-render

# robots.txt 明确禁爬但你有把握（如自己的站点、已获授权的站点）
cenhua add --url https://mp.weixin.qq.com/s/xxxx --force

# 监听 inbox/urls/*.url 文件（浏览器扩展/脚本写入，读后删除）
cenhua watch --urls
```

工作方式与保障：

- **双产物**：有 chromium 时渲染为 PDF（readability 提取正文后重新排版，
  导航/推荐流/评论不进 PDF；进索引）+ HTML 快照
  （整页归档 `works/snapshots/`，溯源用，不重复索引）；无 chromium 时降级
  静态 HTML 抓取（此时 HTML 直接进索引，内容不丢；纯 JS 渲染的站点如
  头条 m 站静态无正文，会明确报错提示 `cenhua setup` 装 chromium）。
- **chromium 安装**：`cenhua setup` 会装 chromium（约 150 MB）；装不上也能用，
  自动走静态抓取。自检：`cenhua doctor`（失败时输出
  `sudo playwright install-deps chromium` 修复命令）。
- **爬虫礼仪**：遵循 robots.txt（明确禁爬则拒绝，可用 `--force` 显式覆盖并
  打印一次告警）；同域名每秒最多 1 次。注意：微信公众平台 robots 写
  `Disallow: /`，收录微信文章需要 `--force`。
- **去重**：URL 规范化（去 fragment、query 排序）后去重；产物 sha1 去重同本地文件。
- **大小上限**：单页 5 MB，超出截断到标签边界并提示（可用
  `CENHUA_MAX_PAGE_BYTES` 调整；注意 MB 级 HTML 转 PDF 是分钟级，树索引慢）。
- **失败隔离**：抓取/摄取失败进 `inbox/.failed/`，不影响其他 URL 与本地文档摄取。

### 4.3a 邮件收录（v0.3.2 · M1b 起）

`.eml` / `.msg`（Outlook）直接 `add` 或丢 inbox，自动**展开**后进标准闭环：

- 正文生成一份 Markdown（主题/发件人/日期/收件人抬头 + 正文 + 附件清单）；
- 附件逐个还原成文件并各自独立摄取（仅支持的格式；不支持的类型在附件
  清单留痕，不静默丢弃）；
- 单个附件失败进 `.failed/` 不拖垮整封邮件；台账指回**邮件原件**，
  `cenhua sources` 溯源到 .eml/.msg 本体；
- `.msg` 解析依赖 olefile（`cenhua setup` 会装；缺失时 .eml 不受影响）。

`cenhua watch` 强化（同版本）：inbox 文件按**到达时间**（创建时间）排序摄取
——IM 工具落盘的文件名是乱序的，按名字排序会乱序；小于一个轮询间隔的新文件
先跳过（防止读到写了一半的文件）。

### 4.3b 知识编织（v0.3.2 · M1b 起，全程离线零 LLM）

孤立文档变关联网络。摄取后自动生成**规则层粗总结**（首段/实体/关键词/标题，
零 LLM）与共现**关联边**（四层降噪，纯统计）；LLM 精化按需、按预算消费。

```bash
cenhua related 合同A              # 关联文档 + 每条边的证据（共现实体/页码/nPMI）
cenhua link 合同A 付款单B         # 人工声明关联（权重 0.8，自动边上限 0.6）
cenhua link --ban 公司名 常见词   # 永久压制某实体对（重建也不复活）
cenhua hub                        # 枢纽实体复核 + 当前档位与 N
cenhua weave rebuild              # 手动重建关联（摄取时已自动做）
cenhua refine --all --dry-run     # 精化队列估价（永远免费）
CENHUA_REFINE_BUDGET_CNY=5 cenhua refine --drain   # 按预算消费
```

要点：

- **空结果不沉默**：`related` 无显著关联时明示"无显著关联（正常）"——
  关联为空本身是信息。
- **小库模式自动降档**（个人库 N<200 更松阈值 + Laplace 平滑），
  `cenhua hub` 显示当前档位；阈值 `CENHUA_SMALL_CORPUS_N` 可调。
- **三闸成本顺序**：① `--dry-run` 估价永远可用 → ② 预算硬闸
  `CENHUA_REFINE_BUDGET_CNY`（默认 0 = 拒绝，fail-closed；USD 报价按
  保守汇率折 CNY 比较）→ ③ `--force` 显式放行。`--drain` 启动前一次性
  过闸，中途不再逐篇执法；每篇全量记账（`cenhua cost` 可见 `cmd=refine`）。
- **命中入队**：文档被 `ask`/`related` 命中即进 `meta/refine_queue.jsonl`；
  LLM 精化失败留在队列可重试；JSON 解析失败走规则首段兜底（不白花钱）。
- hint 消费（精化摘要进 prompt）**自 v0.3.3 起生效**；现在设预算即知
  消费者版本。

### 4.4 检索

**存在性用 `find`，意义用 `ask`。**

```bash
cenhua find 违约金              # 哪些文件/哪一页提到
cenhua find 6222 -d contract    # 限定某文档
cenhua read contract -p 12      # 核验原文第 12 页
cenhua ask --doc contract "终止罚则是什么"
cenhua ask --all "总结本库要点" --dry-run   # 先看要花几次调用（含金额预估）
```

#### 4.4a 总结延展检索 `query`（v0.3.3 · M2b 起）

把"检索 + 总结 + 关联推荐"合并成一条命令，四段输出：

```bash
cenhua query "ABC 合同的违约金条款"
# 1. 直接命中：find 离线精确（毫秒、零 token），带 [doc P页]
# 2. 总结延展：LLM 两段式 prompt（hint-not-evidence）；无网关时明示降级不硬编
# 3. 内容出处：每条结论 [doc P页] + snippet 逐字引文，本地校验 ✓/✗
# 4. 关联推荐：基于关联层（四层降噪）推荐相关文档
```

多轮与重排（v0.6.2 · M4c 起）：

```bash
cenhua query "ABC 合同的违约金条款" --session deal42   # 第 1 轮，轮次存档
cenhua query "那赔偿上限呢" --session deal42           # 第 2 轮，自动带上先前轮次
cenhua query "违约金条款" --no-rerank                  # 关掉小模型重排（默认开）
CENHUA_RERANK=0 cenhua query "违约金条款"              # 会话级/进程级关闭
cenhua config rerank false                             # 库配置里长期关闭
```

- 同一 `--session <sid>` 的问答轮次落 `meta/sessions/<sid>.json`（至多 6 轮，
  超限裁最旧）；先前轮次以 `[PRIOR tier=context]` 段进 prompt，**只用于理解
  指代与延续话题，不是证据**，事实仍须出自本轮 `[EVIDENCE tier=primary]`。
- 重排在粗召回融合后、Top-K 截断前用一次小模型调用重排候选池（候选 > `--top`
  且网关可用才执行），开关优先级 `CENHUA_RERANK` > vault.yaml `rerank` > 默认开；
  重排的花钱行独立记台账（`cenhua cost` 可见 `cmd=query_rerank`）。
- 两者都是**可降级增强**：非法 sid（限字母/数字/`_`/`-`，≤64 字符）不存档、
  重排调用失败或输出不可解析一律原序返回，rc 与不带这两个选项时完全一致。

规则与习惯：

- **引文强制带 snippet**：snippet 必须逐字来自该页文本层，本地校验不过的结论
  自动标 `[未溯源·LLM 推断]`——发布前务必 `cenhua read` 人工复核。
- **检索默认只在原件（primary）层召回**：周报/摘要类衍生文档默认不召回，
  `--include-derived` 显式开启，命中标 `⚠derived` 且引文穿透指回原件页码。
- **hint 只当路标不当证据**：精化过的总结以 `[HINT tier=internal]` 段进入
  prompt 提示"去哪里看"，事实一律以原件原文为准。
- 先看账再花钱：`--dry-run` 输出 calls + tokens + 金额；超
  `CENHUA_MAX_COST_CNY`（默认 ¥2）拒绝启动，`--force` 放行。
- 无命中时 query 直接拒答（rc=1）——"沉默不是证据"，拒答是正确行为。

### 4.4b 周期洞察 `digest`（v0.4.0 · M3a 起）

按时间窗把库内新文档编织成一篇四节洞察文章（全程引文 + snippet 校验）：

```bash
cenhua digest --weekly --dry-run     # 先看账：窗口圈选 + calls + tokens + 金额
cenhua digest --weekly               # 正式生成（长任务通道，CLI 实时打印进度）
cenhua digest --monthly              # 自然月窗口
cenhua digest --quarterly            # 自然季窗口
cenhua digest --since 2026-09-01     # 自定义起点（与三周期互斥）
```

四节结构：① 图谱速览（本期实体/关联动态）② 跨文档发现 ③ 待澄清问题
④ 引用清单（每条结论 `[doc P页]` + 逐字 snippet，校验不过自动标
`[未溯源·LLM 推断]`）。

规则与习惯：

- **产物自动回流入库**：文章落 `works/digests/洞察_<窗口>_V{N}_<日期>.md`
  并走标准摄取闭环，台账 `tier=derived-doc` + `derived_from` 链；
  检索默认不召回它（`--include-derived` 显式开启，引文穿透指回原件）。
- **all-or-nothing 三闸**（长任务预算，F1）：① `--dry-run` 先看账；
  ② 预估超 `CENHUA_LONGJOB_MAX_COST_CNY`（默认 ¥5，vault.yaml
  `longjob_max_cost` 可覆盖）拒绝启动 rc=4；③ `--force` / `--max-cost N`
  放行。**启动后不中途掐**（豁免中途执法），宁可启动前拒死。
- **watch 只提示不触发**：自上次洞察以来新摄取 ≥N 篇（默认 20，
  `CENHUA_DIGEST_HINT_DOCS` / vault.yaml `digest_hint_docs` 可调）时
  watch 日志提示一句，生成永远由人发起（F10）。
- 命名版本集中一处生成（`_V{N}_` 自动递增），cron 定时跑安全。

### 4.4c Web UI 与局域网 API（v0.5.0 · M3b 起）

一条命令起本地 Web 服务，四页界面 + `/api/v1/*` JSON API，全部是既有
service 层的**薄适配**（无独立业务逻辑；Web 挂了 CLI 完全不受影响）。

```bash
export CENHUA_API_TOKEN=一串自己的长随机串     # 必需，fail-closed
cenhua web                                     # 默认 127.0.0.1:8765
cenhua web --host 0.0.0.0 --port 9000          # 开放局域网（务必先配 token）
```

**鉴权（fail-closed）**：token 解析顺序 `CENHUA_API_TOKEN` env >
vault.yaml `api_token`；**未配置 = 所有页面和 API 一律拒绝**（API 401、
页面重定向 /login）。页面用登录后的 httpOnly cookie 会话；程序化调用带
`X-Cenhua-Token: <token>`（或 `Authorization: Bearer <token>`）头。
滑动窗口限流（默认 30 次/60 秒）超限返回 429 + `Retry-After` 头。

**页面**（浏览器打开 http://127.0.0.1:8765 自动跳 /login；导航栏
下拉可直接切换知识库，多库语义见下）：

| 页面 | 路径 | 功能 |
|---|---|---|
| 摄取 | `/ingest` | 拖拽上传（支持多文件）/ URL 收录，SSE 实时进度 |
| 检索 | `/search` | find 即时检索（正则/大小写/docs 过滤）+ query/ask LLM 任务（dry-run/force/limit 等） |
| 编织 | `/weave` | 文档列表 + 标签/笔记编辑 + Mermaid 关联图 |
| 图谱 | `/graph` | 力导向知识图谱（M4 起） |
| 洞察 | `/insights` | digest 产物浏览 + 页面直接触发周记/月报/季报（M5-3 起） |
| 草稿 | `/drafts` | 主题草稿列表/编辑/版本对比/引文穿透（M4 起） |

**API 端点**（前缀 `/api/v1`，响应均带 `schema_version`）：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/ingest` | POST | multipart 文件上传，同步摄取 |
| `/documents` `/stats` | GET | 文档台账 / 库状态 |
| `/find` | POST | 离线精确检索（零 LLM） |
| `/query` `/ask` `/digest` | POST | 长任务 → 返回 `job_id` + `events_url` |
| `/relations` | GET | 关联层查询 |
| `/docmeta` | GET·POST | 文档标签/笔记读写 |
| `/jobs/{id}/status` `/jobs/{id}/result` | GET | 任务状态（增量 cursor）/ 结果 |
| `/jobs/{id}` | GET(SSE) | 任务进度流；断线带 cursor 重连只重放未消费段 |
| `/graph` | GET | 知识图谱视图（`entity`/`max_nodes`） |
| `/draft` | POST | 草稿生成长任务（M4 起） |
| `/drafts` `/drafts/{f}` | GET·PUT | 草稿列表 / 详情 / 保存重验（M4 起） |
| `/drafts/{f}/export` | GET | 导出下载 `?fmt=md\|html\|pdf`（M5-3 起） |
| `/vaults` | GET | 库列表 + 当前库（M5-3 多库切换） |

**多库切换（v0.7.0 · M5-3 起）**：一个 web 进程绑定一个启动库，
鉴权始终用启动库的 token；数据面（所有 `/api/v1` 端点与页面）可切库——
API 加 `?vault=库名`（非法名 400），页面用导航下拉（写 `cenhua_vault`
cookie，持久生效）。`GET /api/v1/vaults` 可查库列表与当前库。

每个请求分配全链路 rid，响应头 `X-Cenhua-Rid`，结构化日志落
`vaults/<库>/logs/web-YYYYMM.log`（token 不落盘）。

**配置键**（优先级 env > vault.yaml > 默认）：

| 用途 | env | vault.yaml | 默认 |
|---|---|---|---|
| 监听地址/端口 | `CENHUA_WEB_HOST` / `CENHUA_WEB_PORT` | `web_host` / `web_port` | `127.0.0.1` / `8765` |
| SSE 心跳间隔 | `CENHUA_WEB_HEARTBEAT_S` | `web_heartbeat_s` | 10 秒 |
| keep-alive 超时 | `CENHUA_WEB_KEEPALIVE_S` | `web_keepalive_s` | 120 秒 |
| 限流 | `CENHUA_WEB_RATE_CALLS` / `CENHUA_WEB_RATE_WINDOW_S` | `web_rate_calls` / `web_rate_window_s` | 30 次 / 60 秒 |

无需 Nginx 反代；如需接入现有反代，SSE 路径记得关缓冲
（`proxy_buffering off`）并把读超时调到分钟级。

### 4.4d 知识图谱 `graph` 与主题草稿 `draft`（v0.6.0 · M4a 起，纯 CLI）

**图谱**（实体共现图离线可建，LLM 三元组按需花钱）：

```bash
cenhua graph rebuild                 # 离线重建：规则实体 × 共现 + 已有三元组加权
cenhua graph entity 违约金            # 实体邻域（含出处文档）
cenhua graph path 甲公司 乙公司        # 两实体最短路径（BFS）
cenhua graph cluster --top 10        # 枢纽聚簇
cenhua graph mermaid [实体]           # Mermaid 文本（可直接贴飞书 markdown）
cenhua graph triples --doc 合同 --dry-run   # LLM 三元组：先估价（三闸同 digest）
cenhua graph triples --all --force          # 正式抽取（网关+预算闸）
```

- 图数据落 `meta/graph.json` / `meta/triples.jsonl`（原子写），查询全离线零 LLM。
- 入图实体只来自 **primary 文档**；LLM 抽不出的关系宁缺毋滥（谓词白名单），
  解析失败自动降级规则兜底（同文档共现 → `同时提及` 边）。

**主题草稿**（roadmap §7.4 闭环：召回 → 生成 → 引文穿透 → 存档）：

```bash
cenhua draft "合同违约条款演变" --dry-run   # 先看账：召回文档 + calls + 金额
cenhua draft "合同违约条款演变"             # 生成 V1（长任务通道，实时进度）
cenhua draft "合同违约条款演变" --extend 2  # 在第 2 段基础上追加（出 V2）
cenhua draft "合同违约条款演变" --rewrite 1 # 重写第 1 段（出新版本）
cenhua draft --list                        # 版本序列
cenhua draft --diff "合同违约条款演变" 1 2 # 版本差异
cenhua draft --verify                      # 离线重验全部草稿引文（rc=1 有失败）
cenhua draft "合同违约条款演变" --restore 1 # 旧版本另存为最新版本
```

规则与习惯：

- 召回**只认 primary 文档**（digest/草稿等派生物永不作为证据）；每段引文
  `[doc前8位 P页] + 逐字 snippet`，与门禁 `bench` 同一校验器，校验不过标 `✗`。
- 产物落 `works/drafts/<主题>_V{N}_<日期>.md`（tier=derived-doc，检索默认
  不召回），并自动回流入库（台账 `tier=derived-doc` + `derived_from` 链，
  同 digest；回流失败不影响草稿）；`draft --verify`  rc=0 全过 / 1 有失败 / 2 未匹配。
- **rid 幂等**：同主题+同段+同证据集重复提交直接复用既有产物（`mode=cached`），
  零花费；三闸与 digest 完全一致（`--dry-run` → 预算闸 rc=4 → `--force`/`--max-cost`）。
- 无网关或 LLM 输出解析失败 → 规则兜底（原文摘录小节 + 明示"需 LLM"），
  绝不硬编（calls=0）。

### 4.4e 模板生成 `template` 与导出 `export`（v0.6.2 · M4c 起）

**模板生成**（在 draft 闭环之上只换"小节骨架 + 文风"，产物同目录、同一引文门禁）：

```bash
cenhua template --list                        # 内置 4 个 + 自定义（离线即时）
cenhua template memo                          # 查看某个模板的骨架与文风（离线）
cenhua template --add board_brief --name 董事会简报 \
        --section 摘要 --section 风险 --section 决议    # 自定义模板（离线）
cenhua template --add board_brief --sections 摘要,风险,决议 --force  # 等价写法+覆盖
cenhua template report "合同违约条款演变" --dry-run   # 先看账：召回文档 + calls + 金额
cenhua template weekly "本季度供应链融资进展"          # 正式生成（长任务通道，实时进度）
cenhua template memo "预算追加申请" --max-cost 1.5     # 单次放宽预算上限
```

- **内置四模板**：`report` 报告 / `memo` 备忘录 / `email` 邮件 / `weekly` 周报，
  各 4 个小节骨架 + 一段文风指令；`template --list` 可看全量。
- **自定义模板**落 `<vault>/meta/templates/<id>.md`（id 限小写字母/数字/下划线，
  2–32 位），**同名覆盖内置**（例如自定义 `memo.md` 会顶掉内置备忘录骨架）；
  文件就是普通 markdown，`##` 标题即小节骨架，首行
  `<!-- template: id=xxx name=显示名 -->` 是可选元信息，可直接手工编辑。
- **产物与 draft 同一目录**：`works/drafts/<主题>_V{N}_<日期>.md`
  （tier=derived-doc，检索默认不召回），因此 Web 编辑三件套与 `export`
  天然可用；文件内多一行 `<!-- template: <id> -->` 溯源标记，自动回流入库
  （`derived_from` 链，回流失败只加提示行不改 rc）。
- **rc 语义与 draft 对齐**：`0` 成功 / `1` 召回为空或生成、落盘失败 /
  `2` 参数错（未知模板、缺主题、`--add` 时 id 非法或已存在未加 `--force`）/
  `3` 网关未配置（`--dry-run` 仍可看账）/ `4` 预算拒绝
  （`CENHUA_LONGJOB_MAX_COST_CNY`，默认 ¥5，`--force`/`--max-cost` 放行）。
- **rid 幂等**：同模板+同主题+同证据集重复提交直接复用既有产物（`mode=cached`），
  零花费；台账记 `cmd=template`（`cenhua cost` 可见）。
- 无网关或 LLM 输出解析失败 → 规则兜底（模板骨架说明 + 原文摘录小节，
  calls=0），绝不硬编。

**导出**（纯离线零 LLM，源限 `works/drafts/` 内的 `.md`）：

```bash
cenhua draft --list                            # 先找文件名
cenhua export 合同违约条款演变_V1_2026-10-20.md            # 默认 md
cenhua export 合同违约条款演变_V1_2026-10-20.md --html
cenhua export 合同违约条款演变_V1_2026-10-20.md --pdf
```

- 产物落 `works/exports/<同名>.<fmt>`。`md` 逐字节复制；`html` 与 `pdf` 都走
  **同一套 markdown → 受限 HTML 渲染**（表格 + 代码块，`<script>` 与 `on*`
  属性一律剥除，与 Web 页面同一消毒口径），PDF 再由引擎渲染（内置中文字体、
  宽表自动横排、字符完整性 >=85% 校验）。
- **失败不留半成品**：渲染或 PDF 完整性校验不过会删掉半成品并 rc=1；
  源文件名不在 `works/drafts/` 内、带路径分隔符、非 `.md` 或不存在 → rc=2。
- PDF 建议读回自检：`python3 -c "import pymupdf;print(pymupdf.open('x.pdf')[0].get_text()[:200])"`。

### 4.5 溯源

每条命中都带 `[doc P页]` 和 `Source:` 行，指向存档原件：

```bash
cenhua sources 违约金    # 查看原始上传与存档副本
```

### 4.6 成本与质量（M1a 起）

**成本月报**：所有 LLM 调用（含摄取树索引）都记入成本台账，按命令分组汇总，
摄取成本单列首位：

```bash
cenhua cost                 # 本月成本汇总
cenhua cost --month 2026-10 # 指定月份
```

**质量门禁**：`cenhua bench` 跑随包分发的冻结 fixture 语料（离线、零 LLM），
验证存在性召回 100% 与引文条目准确率 ≥95%：

```bash
cenhua bench                # fixture 阻断级门禁（发版前必跑）
cenhua bench --corpus       # 用户库 QA（报告模式，只打印不阻断）
```

自 v0.3.3 起门禁加入**拒答正确率 ≥90%**（fixture 拒答题需 LLM）：
离线 CI 无网关时拒答集显示 skipped 不阻断；**发版流水线必须带
`PI_BASE`/`PI_KEY` 跑全量**，否则 release notes 需标注"拒答门禁未验证"。

自 v0.4.0 起门禁加入**注入对抗集**（fixture 注入题，离线零 LLM）：hint 摘要
中混入的中英祈使/注入句必须被 `sanitize_hint` 整句剔除且事实片段零误伤，
对抗题至少 1/3 人工撰写（`author:"human"`），任何一题失败即阻断发版。

## 5. 库管理

```bash
cenhua init work --title "工作"     # 新建库
cenhua vaults                        # 列出所有库
cenhua use work                      # 切换默认库
cenhua status                        # 库内文档/待处理/可检索状态
cenhua doctor                        # 环境自检（迷路时先跑这个）
cenhua rm work --yes                 # 删除库
cenhua backup --yes                  # 备份当前库（默认 <HOME>/backups/）
cenhua restore <backup.tar.gz> --yes # 从备份恢复（--name 可改名）
```

> 备份/恢复（v0.7.0 起）：`backup` 把整个 vault（engine 索引、文本层、
> works 产物、meta、logs）打包成 tar.gz，排除可重建的 `inbox/.processed`
> 与 `inbox/.failed`。`restore` 默认恢复到原库名，`--name` 可改名；
> 目标库非空时需 `--yes` 确认。

## 6. 网关与存储

```bash
cenhua gateway                       # 查看当前网关（密钥打码）
cenhua gateway openclaw:<provider>   # 复用 OpenClaw 配置
cenhua gateway env                   # 改用环境变量
cenhua home                          # 查看存储位置
cenhua home set /path/to/disk        # 迁移存储（自动搬移已有库）
```

## 7. 离线能力

以下命令**不需要 LLM**，完全离线：

```
find · read · list · flatten · status · doctor · sources
```

只有 `add`（建索引）和 `ask` 需要 LLM。

## 8. 常见问题

**Q: 图片识别效果差怎么办？**
A: 提高 `CENHUA_OCR_MIN_CONF`，让更多低质量图片走视觉大模型兜底；或
`CENHUA_OCR=vision` 全部走大模型。

**Q: 找不到某个词？**
A: 先 `cenhua doctor` 确认文本层非空；再试变体（同音、连字符、中英文）。
`find` 返回空通常是文本层过期，`cenhua flatten` 可修复。

**Q: 如何避免 `ask` 花太多钱？**
A: 始终先 `--dry-run` 看调用数；`max_llm_calls` 默认 8，超限需 `--force`。

**Q: 密钥会存到磁盘吗？**
A: 不会。`vault.yaml` 拒绝存储密钥，密钥只在环境变量或 OpenClaw 配置中。

## 9. 隐私

- 语料含 PII（身份证、卡号、电话、合同），保持 `~/.cenhua/` 远离同步/共享
  文件夹。
- 文档在本地索引，端点由你选择（云端或本地 Ollama/vLLM）。
