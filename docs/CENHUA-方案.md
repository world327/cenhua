# MNEMOSYNE · 个人第二大脑技能方案

> 状态：**待决策**（本文件仅为方案，不含实施）
> 基座：`/home/world/openclaw-skills/pageindex-rag` v1.2.0（MIT）
> 目标平台：OpenClaw / Hermes 等个人智能体（纯 SKILL.md + scripts 约定，可通用移植）

---

## 一、命名（古典神话）

**推荐主名：MNEMOSYNE**（Μνημοσύνη，谟涅摩叙涅）
希腊神话中的**记忆女神**，提坦神族，宙斯之女，**九位缪斯之母**。
寓意链完美贴合产品：*记忆 → 孕育一切创造*。第二大脑不是仓库，是创作的子宫。
CLI 用短名 `mnemo`，短代号 `MNE`，好敲好记。

备选（按推荐度）：

| 名称 | 神话出处 | 契合点 | 短板 |
|---|---|---|---|
| **MNEME** | 三位原始缪斯之一，名字本义即"记忆" | 短、好敲、仍是缪斯 | 辨识度低于 Mnemosyne |
| **CANGJIE / 仓颉** | 中国神话，仓颉造字，"天雨粟，鬼夜哭" | 中文语境最拉风，造字=知识创造 | 英文受众陌生 |
| **MIMIR / Mimir** | 北欧智慧之泉守护者，奥丁以一眼换智慧 | 本地库=泉，代价=一次摄取 | Mimir 已是常见开源组件名 |
| **YGGDRASIL** | 北欧世界之树，连接九界，藏万物知识 | 与 PageIndex **树索引**同构 | 拼写长 |
| **ALETHEIA** | 希腊"揭示/真理"，从遗忘（Lethe）中被捞出 | 检索即"去蔽" | 偏哲学，缺记忆直感 |

命名一旦定，包名 `mnemosyne`、skill 目录 `mnemosyne`、环境变量前缀 `MN_`、库目录 `~/.mnemosyne/`。

---

## 二、要解决的问题（pageindex-rag 现状 → 缺口）

pageindex-rag 已经很强，但它是**取证问答工具**：调用者必须知道脚本名、参数、环境变量，并且每次手动跑 `pi_flatten.py`。个人第二大脑要的是**"丢文件 → 直接问 → 出稿"**。

| pageindex-rag 已有 | 缺口（本项目新增） |
|---|---|
| 任意格式 → 硬化 PDF → 树索引（sha1 去重） | 无 inbox/自动摄取概念，需人肉传参 |
| 本地文本层 `--grep`（<0.1s，零成本） | 摄取与 flatten 是两步，忘跑即静默漏检 |
| LLM 深读 `--doc/--all`（并行+故障转移） | 无面向创作的输出（大纲、引文、草稿） |
| 原件存档 `sources/` + `source_map.csv` 溯源 | 无笔记/标签/反向链接/知识图谱沉淀 |
| 视觉 OCR、扫描件、加密 PDF 处理 | 无成本护栏（`--all` 一跑就是几十次 LLM 调用） |
| —— | 无多库（vault）概念、无"本周新增/未归档"体感 |

一句话：**引擎不动，加"入口、习惯、创作"三层。**

---

## 三、产品形态

用户视角三步：

```
① 丢     把 pdf/docx/xlsx/图片/md 扔进 ~/.mnemosyne/vaults/default/inbox/
② 问     "我上传的保险条款里，等待期和免责条款分别怎么说？"
③ 写     "基于我库里的资料，写一篇 XX 的长文大纲，每节标注出处页码"
```

智能体视角：`SKILL.md` 的 description 承担触发（"用户上传文件建索引 / 询问自己资料 / 基于个人知识写作"），一旦命中，只暴露一个 `mnemo` CLI，禁止智能体直接调底层 `pi_*.py`（这是 pageindex-rag 的 pitfall 高发区）。

---

## 四、架构（五层，四层复用）

```
inbox 投递 → [L1 摄取] → [L2 归一 PDF + 树索引] → [L3 文本层] → [L4 知识沉淀] → [L5 检索与创作]
              新增            复用 pageindex-rag      复用        新增            新增
```

**L1 摄取层（新增）**
`mnemo add <文件|目录>` / `mnemo watch`（inotify 轮询 inbox）；sha1 去重 + 原件归档复用 `pi_ingest.py`；**摄取成功后自动串接 `pi_flatten.py`**，把"ingest + flatten 必须原子"这个人为纪律变成代码保证。

**L2/L3 引擎层（复用，零改动）**
沿用 `pi_ingest.py` / `conv_office|image|scan.py` / `pi_flatten.py`；环境变量全部透传 `PI_BASE/PI_KEY/PI_MODEL/PI_VISION_*`，只在 `mnemo init` 时问一次、写进 `vault.yaml`，之后从环境或密钥管理器读取，永不落盘明文（保持 pageindex-rag "no secrets bundled" 原则）。

**L4 知识层（新增，纯文本可 git）**
- `knowledge/notes/*.md`：用户/AI 写的卡片笔记，YAML front matter（`tags`, `refs: [doc_id:page]`）
- `knowledge/tags.yaml`：标签词表 + 同义词（中英/谐音变体一并复用 pageindex 的同音字扫描经验）
- `knowledge/graph.json`：`notes ↔ docs ↔ tags` 轻量节点边（对齐你现有 `second-brain` 的 `knowledge-graph.json` 形状，便于以后合并）
- `knowledge/digest/<周>.md`：本周新增文档 + 高频命中 + 未打标签提醒

**L5 检索与创作层（新增）**
严格执行 pageindex-rag 的铁律 **grep 查存在，LLM 读含义**，路由内置不可绕过：

| 命令 | 底层 | 用途 |
|---|---|---|
| `mnemo find <词…>` | 文本层 grep | 关键词/号码/人名，毫秒级，带页码+源文档 |
| `mnemo ask "<问题>" [--doc kw] [--all]` | 树索引 LLM | 摘要、跨页推理、多文档扫 |
| `mnemo read <doc_id> --page n` | 文本层 | 拉原文上下文核对 |
| `mnemo ask --dry-run` | 估算 | **成本护栏**：先报"将调用 N 次 LLM / 约 M token"，确认再跑 |
| `mnemo note` / `tag` / `graph build` | 本地 | 知识沉淀 |
| `mnemo draft "<题目>" [--docs …] [--outline-only]` | grep+LLM | 检索证据 → 大纲 → 草稿，逐段带 `〔来源: 文件名 P12〕` |

所有输出强制保留 pageindex-rag 的溯源行 `源文档: <原文件名> | 已存档 vault/engine/sources/…`，AI 转写与原件永远分层。

---

## 五、目录结构（新项目）

```
mnemosyne/
├── SKILL.md                    # 触发描述 + 决策表 + 铁律 + 精简 pitfalls（详细版指向 references）
├── README.md                   # 面向用户：3 分钟建库
├── scripts/
│   ├── mnemo                   # 唯一 CLI 入口（子命令分发）
│   ├── m_inbox.py              # 投递/watch/去重/自动 flatten
│   ├── m_vault.py              # init / 多库 / 状态 / 配置
│   ├── m_search.py             # find / read（文本层）
│   ├── m_ask.py                # ask / --dry-run 成本护栏
│   ├── m_knowledge.py          # note / tag / graph / digest
│   ├── m_draft.py              # 大纲 + 草稿 + 引文装配
│   └── engine/                 # pageindex-rag 脚本原样纳入（保持可 upstream diff）
├── references/
│   ├── engine-pitfalls.md      # 从 pageindex-rag SKILL.md 迁移的完整坑库（按需加载，省上下文）
│   ├── intake-workflow.md      # 摄取分诊（继承 evidence-workflow.md 并泛化）
│   └── writing-workflow.md     # 创作装配规范：引文格式、禁止臆造、缺失声明
└── tests/
    ├── smoke_ingest.sh         # 极小样本：md+png 各一，端到端跑通
    └── fixtures/
```

vault 运行时目录（用户机器）：

```
~/.mnemosyne/vaults/<name>/
├── vault.yaml           # 库名、PI_* 网关引用、vision 模型、成本上限
├── inbox/               # ★ 用户唯一需要认识的目录
├── engine/              # = PI_STORE：sources/ pdf/ docs/ text/ manifest.json source_map.csv
├── knowledge/           # notes/ tags.yaml graph.json digest/
├── works/               # drafts/ exports/
└── logs/
```

---

## 六、SKILL.md 设计要点（决定智能体好不好用）

1. `description` 写"何时用"而非"是什么"：上传本地文件建索引 / 询问自己资料 / 基于个人知识库写作 / 需要带页码出处的回答。
2. 正文给**决策表**（借鉴你现有 `second-brain-search` 的写法，实测好用）：查什么 → 用哪个子命令，杜绝智能体乱 grep 全库或直接调 `pi_*.py`。
3. 三条不可协商铁律置顶：① 先 `find` 后 `ask`；② 未 flatten 视为索引不存在（CLI 已自动做，SKILL 里再兜一层）；③ 没查到必须说"未在库中找到"，并说明检索路径，禁止编造。
4. 坑库外置到 `references/`，SKILL.md 控制在 150 行内，避免污染智能体上下文窗口。

---

## 七、实施阶段（可分次交付）

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **P0 骨架** | 仓库布局、`mnemo` 分发器、`vault init/status`、引擎薄封装、SKILL.md 首版 | `mnemo init && mnemo add x.md && mnemo find x` 通 |
| **P1 摄取闭环** | inbox watch、自动 flatten、重复/失败可视化、成本与页数护栏 | 丢一批混合格式文件进 inbox，全程无人工命令，`mnemo status` 准确 |
| **P2 检索闭环** | find/ask/read + `--dry-run` 成本护栏 + 统一引文格式 | 20 文档库上，10 个真实问题命中率与出处可核对 |
| **P3 知识沉淀** | note/tag/graph/digest | 能回答"这些资料之间有什么关联"，图谱可视化可读 |
| **P4 创作输出** | `draft` 大纲→草稿→导出 md/html | 产出文章逐段有页码出处，抽查无幻觉 |
| **P5 打磨发布** | 多 vault、隐私（PII 脱敏开关、本地模式）、测试、安装文档、发布到 skills 库 | 干净机器 3 分钟内从安装到首次问答 |

建议首版只做 **P0–P2**（最小可用第二大脑），P3/P4 视使用体感再排期。

---

## 八、风险与对策（多数来自 pageindex-rag 已付过学费的坑）

| 风险 | 影响 | 对策 |
|---|---|---|
| `pageindex` 仅官方 PyPI 有，镜像会挂 | 装不上 | 安装脚本固定 `--index-url pypi.org` 装 pageindex，依赖走镜像；`mnemo doctor` 自检 |
| 成本失控（`--all` 每文档一次 LLM） | 费用/限速 | `--dry-run` 默认；vault.yaml 里 `max_llm_calls_per_run`；批量走 `batch_ingest.py` 节奏 |
| 静默空白 PDF（`insert_htmlbox`） | 空壳索引 | 沿用 0.85 字符完整性校验；`mnemo doctor` 扫描 `text/` 空文件并告警 |
| 加密 PDF 被静默跳过 → 误判"库里没有" | 结论错误 | 复用文件名口令尝试 + "双路径一致才敢说没有"纪律写进 SKILL.md |
| 扫描/图片 OCR 成本与质量 | 索引质量=转写质量 | `conv_scan --probe` 预算先探；答案中标注"来自 OCR 转写" |
| vision 模型需裸 model id（LiteLLM 前缀 404） | 图片摄取失败 | `mnemo init` 时做一次 `/models` 探测，错误即时反馈 |
| 索引慢（52 页≈140s） | 体感卡 | watch 模式后台跑 + 进度写 `logs/`，`status` 显示进行中任务 |

---

## 九、可复用资产盘点

- **直接搬**：`pi_ingest.py` / `pi_flatten.py` / `pi_query.py` / `conv_*.py` / `batch_ingest.py`（本项目不改引擎，只做薄封装，保持与上游可 diff）
- **经验搬**：pageindex-rag SKILL.md 的 30+ 条 pitfalls → `references/engine-pitfalls.md`；`evidence-workflow.md` 的取证契约（不确定标 `?`、绝不猜人名号码）→ `intake-workflow.md`
- **对齐**：现有 `~/.openclaw/skills/second-brain-search` 与 `/home/world/second-brain`（wiki + 向量 RAG + 知识图谱）。建议 MNEMOSYNE 定位"**任意用户的通用第二大脑 skill**"，你现有 second-brain 作为**首个真实语料与迁移试验场**（把 articles 指向 `mnemo add`，两套检索并存、逐步收敛）。

---

## 十、需要你决策的点

1. **名称**：MNEMOSYNE / MNEME / CANGJIE / YGGDRASIL / 其他
2. **首版范围**：P0–P2 最小可用，还是一步做到 P4（含创作输出）
3. **引擎集成方式**：(a) 复制进 `scripts/engine/`（自包含，离线可用，需人工同步上游）／(b) 声明对 pageindex-rag 的依赖 + 路径探测（体积小，但安装多一步）
4. **是否引入向量语义层**：现方案纯 vectorless（毫秒 grep + 树导航）。若要"换个说法也能搜到"，可加可选 embedding 兜底（对齐你现有 `rag_search.py`），但会引入向量库依赖与索引维护成本 —— 我倾向**先不加**，用 `tags/同义词` 顶一段时间看体感
5. **SKILL.md 语言**：中文（自用友好）／英文（可发布社区）／双语
6. **vault 默认位置与多库**：`~/.mnemosyne/vaults/default`，是否需要按项目/领域分库
7. **是否包含 Web/CLI 之外的 UI**（例如极简本地浏览页看图谱与草稿）—— 默认**不做**，避免首版失焦

确认后我按 P0 起步实施。
