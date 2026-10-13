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
INTAKE    add <files|dir|--inbox> · watch [--interval N] [--once]
RETRIEVE  find <terms> [-d doc] [-i] [-r] · read <doc> [-p N] [-g re] · list
DEEP READ ask [--doc kw | --all] "q" [--limit N] [--dry-run]   (成本护栏)
SEMANTIC  index build|status · seek "question"     (可选向量层)
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

### 4.3 检索

**存在性用 `find`，意义用 `ask`。**

```bash
cenhua find 违约金              # 哪些文件/哪一页提到
cenhua find 6222 -d contract    # 限定某文档
cenhua read contract -p 12      # 核验原文第 12 页
cenhua ask --doc contract "终止罚则是什么"
cenhua ask --all "总结本库要点" --dry-run   # 先看要花几次调用
```

### 4.4 溯源

每条命中都带 `[doc P页]` 和 `Source:` 行，指向存档原件：

```bash
cenhua sources 违约金    # 查看原始上传与存档副本
```

### 4.5 成本与质量（M1a 起）

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
