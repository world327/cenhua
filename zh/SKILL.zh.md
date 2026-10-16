# CENHUA 中文说明（与 SKILL.md 同一套规则）

岑华：出自上古《山经》的昆仑古木，观时序、记万象。本项目把这句话做成工具——
每篇文档一棵树索引，每个库一层可毫秒检索的纯文本层，原件永久存档，
因此每个回答都能回溯到用户上传的那份原始文件。

## 一句话规则

**存在性用 `find`，含义交给 `ask`。**
"X 出现在哪、第几页、我的库里到底有没有 X" 一律走 `find`：本地正则扫文本层，
毫秒级、零成本、完整无遗漏。绝不要让大模型回答存在性问题——它会安静地漏掉。
摘要、定性、跨页推理才用 `ask`。

## 决策表

| 用户想做什么 | 命令 | 代价 |
|---|---|---|
| 把上传的文件入库 | `cenhua add <路径>`，或丢进 `inbox/` 后 `cenhua add --inbox` | 每篇 1 次索引调用 |
| 收录网页/URL | `cenhua add --url <url>`（可多次；批量用 `--url-file <清单>`；`--force` 跳过 robots） | 每页 1 次索引调用 |
| 后台自动摄取 | `cenhua watch`（`--urls` 同时消费 `inbox/urls/*.url`） | 同上 |
| "X 出现在哪 / 库里有没有提过 X" | `cenhua find <词>...` | 离线免费 |
| 限定某篇文档 | `cenhua find X -d <文档关键词>` | 离线免费 |
| 核对原文引文 | `cenhua read <文档> -p <页码>` | 离线免费 |
| "某文档对 Y 是怎么说的"（含义） | `cenhua ask --doc <kw> "问题"` | 每篇 1 次调用 |
| 全库扫一遍 | 先 `cenhua ask --all "问题" --limit N --dry-run` | N 次调用 |
| 换个说法搜不到 | `cenhua seek "问题"` | 向量化 |
| 这条内容来自哪次上传 | `cenhua sources <kw>` | 离线免费 |
| 库里有什么 / 是否健康 | `cenhua status` / `cenhua doctor` | 离线免费 |
| 换个项目或领域 | `cenhua init <名>`，之后每条命令加 `--vault <名>` | — |

## 五条铁律

1. **绝不直接调用 `scripts/engine/pi_*.py`。** 引擎需要 `PI_STORE`、摄取后 flatten
   和成本上限，只有 `cenhua` 会正确提供。
2. **"我文件里没有 X"必须两条路径互证。** `find` 覆盖变体（同音字、去空格连字符的
   号码、中英双写），并确认 `doctor` 没有空文本层。失败路径的沉默不是证据。
3. **引用必须用工具给出的引用行**：`[doc_id P页码]` 加上 `Source:` 行（写明来自哪次
   上传、原件存档在哪）。重要结论先 `cenhua read` 那一页核对，再复述。
4. **任何 `--all` 之前先 `--dry-run`。** 超过 `max_llm_calls`（默认 8）CLI 会直接拒绝，
   除非显式 `--force`。
5. **摄取后 `find` 搜不到，几乎都是文本层过期**——CLI 已自动 flatten，真要手工修
   就是 `cenhua flatten`，它免费且亚秒级。

## 首次运行的两项确认（必须问用户，不可代答）

### 决策一：知识库存在哪里（退出码 6 = CONFIRM REQUIRED）

语料（原文档 + 索引 + 原件存档）的生命周期比技能本身长，安装时必须让用户选：

1. `~/.cenhua`（默认，推荐：技能更新/重装不会波及数据）
2. **安装目录**（`<技能目录>/vaults/<库名>`）：全部收在一个文件夹内，自包含；
   但要提醒用户——智能体更新或重装技能时这棵树可能被删除，仅在用户明确要求时选它
3. 用户指定的任意路径（移动盘、不参与同步的目录等）

落实方式：`cenhua setup --home <路径>`，或事后 `cenhua home set <路径>`
（会自动把已有 vaults 迁移过去）；`cenhua home` 查看当前根目录、来源与占用空间。
磁盘上只保存一行指针文件 `~/.config/cenhua/location`，环境变量 `CENHUA_HOME`
优先级最高。**绝不可代替用户静默决定路径。**

### 决策二：使用哪个 LLM 网关（退出码 5 = CONFIRM REQUIRED）


树索引摄取与 `ask` 会消耗 LLM 调用，用哪家网关是**用户的选择**：

- `cenhua setup` 退出码 **5** 且打印 `CONFIRM REQUIRED` 时，说明检测到本机
  OpenClaw 配置，正在等用户二选一，把选项原样转述给用户：
  1. **复用 OpenClaw 的模型配置**（推荐：密钥留在 openclaw.json，调用时实时
     解析，CENHUA 从不复制密钥）→ `cenhua setup --gateway openclaw:<provider>[/<模型>]`
  2. **自备端点** → `export PI_BASE/PI_KEY/PI_MODEL` 后
     `cenhua setup --gateway env`
- `cenhua gateway list` 可预览候选（自动标注 OpenClaw 主模型；其 imageModel
  会被用作扫描件/图片的视觉模型）；`cenhua gateway` 查看当前生效网关
  （key 永远显示为 `***`）。
- vault.yaml 只保存**引用**（gateway/openclaw_provider/openclaw_model），
  绝不保存密钥；换网关随时 `cenhua gateway env` 或重新 `--gateway` 覆盖。

## 一键安装（OpenClaw）

把本仓库 GitHub 链接发给智能体即可："install this skill:
https://github.com/world327/cenhua"。OpenClaw 会 `skills install git:...` 装到
工作区技能目录；首次使用让智能体执行技能目录下的 `bin/cenhua setup`
（自动装 Python 依赖并建默认库）。网关密钥配置到
`~/.openclaw/openclaw.json` 的 `skills.entries.cenhua.env`（PI_BASE/PI_KEY/
PI_MODEL...），用 `openclaw skills check` 确认 cenhua 为 ✓ ready。

## 环境变量（密钥只存在于环境，永不落盘）

```bash
export PI_BASE=https://api.example.com/v1   # 任意 OpenAI 兼容端点
export PI_KEY=***
export PI_MODEL=openai/gpt-4o-mini          # 必须带 openai/ 前缀（LiteLLM 路由）
export PI_VISION_MODEL=视觉模型裸ID          # 视觉兜底：本地RapidOCR优先，读不出才用它；不要带前缀
export PI_EMBED_MODEL=text-embedding-v3     # 可选：语义召回层
export PI_EMBED_BASE=...  PI_EMBED_KEY=...  # 不设则复用 PI_BASE / PI_KEY
```

不设 `PI_BASE/PI_KEY` 时，`flatten / find / read / status / doctor / sources`
照常可用；只有摄取和 `ask` 需要大模型。

## 用户只需记住一个目录

`~/.cenhua/vaults/<库名>/inbox/`。任何格式（pdf / docx / pptx / xlsx / xls /
md / txt / html / csv / 图片 / 扫描件）丢进去，然后 `cenhua add --inbox`，
或者让 `cenhua watch` 常驻。sha1 去重不重复计费；失败文件进 `inbox/.failed/`
并把原因写进 `logs/`——绝不静默丢弃。每次摄取成功后自动重建文本层，
所以 `find` 的结果始终可信。
图片与扫描件先用本地 RapidOCR 转写（离线、免费，`cenhua setup` 尽力安装）；
它读不出时才用视觉大模型兜底，`CENHUA_OCR=vision` 可强制走大模型路线。

## 回答纪律

- 每条命中都带页码，引用时写 `[contract.txt P12]`。
- 图片/扫描件是转写而非原文，引用时要说明，并指向存档原件（`cenhua sources`）。
- `find` 与 `ask` 冲突时：存在性听 `find`，大意听 `ask`。
- 说"你的文件里没有提到 X"时，说明你跑过哪些命令、试过哪些变体。

## 分库策略

一个项目/领域一个库：`contracts`、`reading-notes`、`client-a`……
切换默认库 `cenhua use <名>`，单次指定 `--vault <名>` 或 `CENHUA_VAULT=<名>`。

更多细节见英文原文 `SKILL.md` 与 `references/`（坑库、摄取流程、检索手册）。
