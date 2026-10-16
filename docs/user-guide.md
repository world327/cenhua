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
INTAKE    add <files|dir|--inbox> · add --url <url> [--url ...] ·
          add --url-file <path> [--no-render] · watch [--interval N] [--once] [--urls]
          （.eml/.msg 邮件自动展开附件，v0.3.2 起）
RETRIEVE  find <terms> [-d doc] [-i] [-r] · read <doc> [-p N] [-g re] · list
DEEP READ ask [--doc kw | --all] "q" [--limit N] [--dry-run]   (成本护栏)
SEMANTIC  index build|status · seek "question"     (可选向量层)
WEAVING   related <doc> · link <A> <B> · link --ban <E1> <E2> · hub ·
          weave rebuild · refine [--all --dry-run | --drain [--force]]
COST      cost [--month YYYY-MM]     成本月报，按命令分组，摄取成本单列首位
QUALITY   bench [--corpus]           质量门禁：fixture（阻断）/ 用户库（报告）
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
cenhua ask --all "总结本库要点" --dry-run   # 先看要花几次调用
```

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

## 5. 库管理

```bash
cenhua init work --title "工作"     # 新建库
cenhua vaults                        # 列出所有库
cenhua use work                      # 切换默认库
cenhua status                        # 库内文档/待处理/可检索状态
cenhua doctor                        # 环境自检（迷路时先跑这个）
cenhua rm work --yes                 # 删除库
```

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
