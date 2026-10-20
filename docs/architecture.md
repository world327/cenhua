# CENHUA 技术架构（Architecture）

本文档描述 CENHUA 的模块划分、数据流、关键机制与扩展点。面向想理解或扩展
代码的开发者。

## 1. 总体架构

```
                    ┌─────────────────────────────────────────────┐
                    │              bin/cenhua (CLI 入口)          │
                    │         m_cenhua.py 命令分发 / 参数解析      │
                    └─────────────────────────────────────────────┘
                                      │
        ┌─────────────┬───────────────┼───────────────┬─────────────┐
        ▼             ▼               ▼               ▼             ▼
   m_setup.py    m_vault.py      m_ingest.py     m_search.py    m_ask.py
   安装/网关/     库管理/         摄取闭环/        离线检索        LLM 深读
   存储位置       doctor/status   本地OCR          find/read      成本护栏
        │             │               │               │             │
        └─────────────┴───────┬───────┴───────────────┴─────────────┘
                              ▼
                       m_lib.py (共享库)
              vault 布局 · 网关解析 · 引擎桥接 · 引文
                              │
                              ▼
                 scripts/engine/ (pageindex-rag, 上游纯净)
              pi_ingest · pi_flatten · pi_query · conv_*
                              │
                              ▼
                 PageIndex (vectorless 树索引) + 本地文本层
```

## 2. 模块职责

### 2.1 `m_cenhua.py` — CLI 分发器

- 解析 `--vault`（可从任意位置提取）、位置参数（`positional()` 跳过 flag 及
  其值，避免 `--home /path` 被误当库名）。
- 按命令路由到各 m 模块。
- 捕获 `KeyboardInterrupt` / `BrokenPipeError`。

### 2.2 `m_lib.py` — 共享库

- **存储根解析**：`CENHUA_HOME` env > 指针文件 `~/.config/cenhua/location` >
  `~/.cenhua` 默认。数据生命周期长于技能安装，故只存一行指针。
- **Vault 布局**：`<root>/vaults/<name>/` 下 `inbox/`、`engine/`、`works/`、
  `meta/`、`logs/`。
- **网关解析**：`resolve_gateway()` 返回 `{base, key, model, vision, source}`，
  密钥只从环境或 OpenClaw 配置实时读取，绝不落盘。
- **引擎桥接**：`run_engine()` 用 subprocess 调引擎脚本，注入 `PI_STORE` 等
  环境变量。
- **引文**：`provenance()` / `cite()` 生成统一溯源格式。

### 2.3 `m_setup.py` — 安装与决策

- `ensure_deps()`：安装 python 依赖（pageindex 走 pypi.org `--no-deps`）。
- `ensure_ocr()`：校验 RapidOCR 是否安装（必需依赖，缺失则提示）。
- `ensure_chromium()`：安装 Playwright chromium（M2a 网页收录；有 root 走
  `--with-deps`，无权限退回普通安装并警告系统库缺失，幂等）。
- `configure_gateway()`：一次性网关决策，绝不静默（退出码 5）。
- `confirm_location()`：存储位置决策（退出码 6）。
- `feature_report()`：打印各功能开关状态。

### 2.4 `m_vault.py` — 库管理

- `init` / `listing` / `use` / `rm` / `status` / `doctor` / `sources`。
- `doctor` 分 6 段自检：python/引擎、网关、图片与扫描件（本地 OCR + 视觉
  兜底）、向量层、存储完整性、网页收录（chromium 启动自检，失败输出精确
  修复命令）。

### 2.5 `m_ingest.py` — 摄取闭环

- `ingest_one()`：单文件摄取，sha1 去重，失败进 `inbox/.failed/`。
- **本地 OCR 预转换**：`m_ocr.preconvert()` 先把图片/扫描 PDF 转成带文本层
  的 PDF，再交给引擎；成功后 `restore_provenance()` 把台账指回原始上传。
- `add()` / `watch()`：显式添加或后台轮询 inbox。

### 2.6 `m_ocr.py` — 本地 OCR（RapidOCR 优先 + 视觉兜底）

- 后端：`rapidocr_onnxruntime` 或 `rapidocr`（v2），懒加载单例。
- **识别效果校验**：平均置信度 ≥ `CENHUA_OCR_MIN_CONF`（默认 0.5）且总字符
  ≥ `CENHUA_OCR_MIN_CHARS`（默认 10），否则触发视觉兜底。
- 渲染复用引擎的 `html_to_pdf`（CJK 安全、完整性校验）。
- 转写 PDF 缓存在 `<vault>/meta/ocr/`，重试不重复 OCR。
- 开关：`CENHUA_OCR=vision` 或 vault.yaml `ocr: vision` 强制走大模型。

### 2.7 `m_search.py` — 离线检索

- `find`：本地正则扫文本层，毫秒级、免费、精确。
- `read`：打印原文页用于核验。
- `list_docs`：列出库内文档。

### 2.8 `m_ask.py` — LLM 深读

- `ask`：树导航式深读，`--dry-run` 估算调用数，`max_llm_calls` 上限。
- `flatten`：重建文本层（离线、增量、亚秒级）。

### 2.9 `m_vectors.py` — 向量语义层（可选）

- `build` / `status` / `search`（`seek`）。
- 无 embedding 配置时优雅降级。

### 2.10 `scripts/engine/` — 上游纯净引擎

- 字节级保持与 pageindex-rag 一致，可 diff、可升级。
- `pi_ingest`（文档→PDF→索引）、`pi_flatten`（文本层）、`pi_query`（检索）、
  `conv_*`（格式转换）。

### 2.11 `cenhua_service/` — service 层（M1a 起）

契约登记制（`docs/service-contract.md`），service 函数禁 `print`/`exit`
（`test_70_service_no_print` 全量生效）：

- `cost.py`：pricing.json 加载、OpenClaw 全名匹配（F9）、token 估算、金额换算、
  cost-ledger 全量记账、`cost` 汇总（摄取成本单列首位）、预估校准闭环。
- `verify.py`：`verify_citation(doc, page, snippet)` 三参原语（F2），NFKC 归一 +
  去空白 + 全半角折叠后正则匹配；门禁与草稿校验的单一事实源。
- `bench.py`：`cenhua bench` 门禁（fixture 阻断级 / 用户库报告模式）、引文按条目
  计量（F7）、拒答非确定性治理（flaky.jsonl，F6.3）。

CLI 层（`m_cost.py`）只做薄包装与输出，逻辑全部下沉到 service 层。

### 2.12 `m_web.py` — 网页收录核心（M2a 起）

- **抓取降级链**（R3-T9 行为闭环）：chromium 渲染（Playwright 无头，
  `domcontentloaded` + 固定等 JS + 60s 硬上限 + CJK 字体注入 + 浏览器
  UA/zh-CN 语境防反爬验证页）→ 渲染失败/缺失/空壳 → 静态 HTML 抓取
  （`fetch_page()` 返回 `source='render'|'static'`）。
- **正文守卫与干净 PDF**：两条抓取路径都要过 `MIN_CONTENT_CHARS` 门槛
  （JS 空壳页/反爬验证页直接失败并给可读提示，不产出 0 字符 PDF）；
  进索引的 PDF 由 readability 提取正文后 `build_clean_html()` 重排
  （导航/推荐流/评论不进 PDF），整页只进快照溯源。
- **爬虫礼仪**：`robots_allowed()`（robots.txt 不可达 fail-open；明确
  Disallow 默认拒绝，CLI `--force` 显式覆盖）；
  `RateLimiter` 同域名滑动窗口限速。
- **纯函数离线可测**：`normalize_url()`（去 fragment、query 排序）、
  `enforce_size_limit()`（5 MB 截断到标签边界）、`extract_readable()`
  （readability 优先，降级 `<article>/<main>/<body>` 提取）、`slugify_url()`。
- **双产物** `build_artifacts()`：PDF 进 vault 根 inbox（进索引，暂存语义
  生效）；HTML 快照归档 `works/snapshots/` + `.meta.json` 溯源回链（溯源用、
  不重复索引，roadmap §4.3）；无 PDF（静态降级）时 HTML 直接进 inbox 索引。

### 2.13 `m_web_cli.py` — 网页收录编排（M2a 起）

- `add --url/--url-file`：规范化去重 → robots → 限速 → 抓取 → 双产物 →
  走既有 `m_ingest.ingest_one()` 闭环（sha1 去重、失败进 `.failed/`），
  成功后 flatten 文本层。返回 rc（有失败=1）。
- `watch --urls`：监听 `inbox/urls/*.url` 文件（浏览器扩展投放模式），读后删除。

### 2.14 `m_mail.py` — 邮件展开（M1b · §4.4 唯一归属）

- `.eml` 走标准库 `email`（policy=default），`.msg` 走 olefile 按 [MS-OXMSG]
  读属性表（`__properties_version1.0` 顶层流）与附件表
  （`__attach_version1.0_*` 2 层结构）；olefile 缺失只影响 .msg。
- `expand()` 产出部件列表：正文 Markdown（抬头+正文+附件清单）+ 受支持格式
  的附件文件，落 `meta/mail/<sha1前12>/`；不支持的附件在清单留痕。
- `m_ingest.ingest_one()` 路由邮件：逐部件走同一闭环，单部件失败移入
  `.failed/` 不拖垮整封；`restore_provenance()` 把台账指回邮件原件。
- **尖括号消毒**（`_desugar`）：`<a@b.c>` 会被 markdown 转成实体编码自动链接，
  引擎完整性校验按 HTML 文本计数虚高 → 短邮件必现 `PDF has N chars` 失败；
  引擎字节级不动，生产端消毒。

### 2.15 `cenhua_service/{summaries,refine,relations}.py` — 编织层（M1b）

- **summaries**（规则先行，零 LLM）：首段（跳标题行）/正则实体（金额/日期/
  邮箱/证件号/大写实体）/TF 关键词（英文词 + 中文 n-gram 加权）/标题结构；
  落 `meta/summaries/<doc>.json`（`status=rule-only`，
  `tier=internal-artifact`）；refined 结果幂等刷新不降级。
- **refine**（按需精化 + 三闸）：`refine_queue.jsonl` 幂等入队（ask/related
  命中触发）、refined 自动出队；三闸顺序 ① dry-run 估价 → ②
  `CENHUA_REFINE_BUDGET_CNY`（默认 0 拒绝；USD 按保守汇率折 CNY）→ ③
  `--force`；`drain` 启动前 all-or-nothing（F1 豁免中途执法），失败留队列，
  JSON 解析失败走规则首段 fallback，每篇写 cost-ledger（T5）。
- **relations**（四层降噪，纯统计零 LLM）：实体对候选 → ①枢纽判定
  （`df>N×ratio` 且 `df>=HUB_MIN_DF=3` 绝对地板防极小库误判）→ ②nPMI≤0 不建边
  （小库档 +Laplace）→ ③共现地板（2/1）→ ④`link_bans.json` 人工压制；
  实体对边投影为文档对边（证据含共现实体/页码/nPMI），日期≤90 天标
  `time_series`；自动边权 ≤0.6、人工 0.8；每文档 Top-8 截断（人工边不截）；
  衍生文档（digest/draft）不参与建边（§7.3）。
- 档位一处定义：`profile(N)`（small: floor1/ratio0.5/Laplace；standard:
  floor2/ratio0.3/raw），阈值 `CENHUA_SMALL_CORPUS_N` 默认 200。

### 2.16 `m_weave.py` — 编织层 CLI 薄包装（M1b）

`refine` / `related` / `link` / `hub` / `weave rebuild` 五个用户命令只做参数
解析与打印；输出格式化在 service 层（`refine_flow` / `related_lines`）。
`refine`/`related` 进 test_71 白名单（≤10 行）；`summarize` 不是用户命令、
不入白名单，由 test_70 管辖（F10）。

### 2.17 `cenhua_service/tier.py` — 三层 artifact 判定与引文穿透（M2b）

防"引文洗白"（§7.3）：LLM 回答只能引用 primary 证据源。判定优先级：
台账 `ingest_manifest.json` 显式 `tier` 字段（在三常量内）→ 名称特征
`DERIVED_RE`（digest/draft/周报/日报）→ 无行保守 primary。
`penetration()` 把 derived 引文沿 `derived_from` 链穿透到 primary 原件页码；
`record_tier()` 摄取后补写台账 tier（引擎字节级不动，test_61）。

### 2.18 `cenhua_service/query.py` + `scripts/m_query.py` — 四段检索（M2b）

`cenhua query` 四段输出：① 直接命中（find 精确 W_EXACT=1.0）② 总结延展
（ask，hint 两段式 prompt + 证据段）③ 内容出处（citations + snippet 强制
校验，F2）④ 关联推荐（related）。三路融合 find+seek+ask 按置信度排序去重。
检索默认仅 primary 层，`--include-derived` 显式开启 derived（命中显 ⚠）。
service 逻辑全在 query.py（禁 print）；`m_query.py` 只做打印与 rc，进
test_71 白名单（M2b = query_cmd）。

### 2.19 拒答门禁（M2b 进阻断集）

`cenhua bench` 的 fixture 拒答题（type=refusal）自 v0.3.3 起进阻断集：
正确拒答率 ≥90%。判定 = 无 citations + 拒答措辞双条件（`_refusal_verdict`）。
无 LLM 网关时全 skipped 不阻断离线 CI（F6.2）；发版流水线必须带
`PI_BASE`/`PI_KEY` 跑全量。非确定性治理（F6.3）：temperature=0 + 失败重试
1 次；同一题连续 2 版 flaky 自动转人工仲裁（meta/qa/flaky.jsonl）。

### 2.20 `cenhua_service/jobs.py` — 任务通道（M3a）+ 持久化边界 ADR

LLM 长任务（ask/query/digest 等）统一经任务通道执行，CLI/Web/API 三形态
共用同一进度协议（roadmap §6.5）：

- `submit(job: JobSpec) -> JobHandle`：登记并提交后台执行（线程），立即返回句柄；
- `job_status(handle) -> JobStatus`：**增量** output chunks + 进度 + 终态 + cost 累计
  （增量语义为 M3b SSE 薄适配预留，客户端按 cursor 拉新增 chunk）；
- `job_result(handle) -> AskResult | QueryResult | DigestResult`：终态后取结构化结果。

**ADR-001 持久化边界（2026-10-16 用户拍板）：重启后标废。**
- 决策：任务通道**纯内存态**（进程内 job 表 + 线程执行），不做任何磁盘/sqlite 持久化；
  进程重启（或正常退出）后未完成的任务不续跑、不恢复——新进程查旧 handle 一律返回
  `aborted(stale)` 终态。
- 备选否决：① 重启后续跑（需持久化执行现场，复杂度与 CLI-only 场景收益完全不成比例）；
  ② 持久化到 sqlite（引入 job 表与主库一致性负担，且 LLM 任务幂等重跑本就便宜）。
- 理由：实现最简；digest/ask 类任务重跑成本低（重跑 = 重新 submit）；CLI 形态下每个
  命令本就是独立进程，"进程退出即任务终点"与用户直觉一致；M3b 的 SSE/WebSocket 断线
  重连只需支持"重订阅**本进程内仍存活**的 job"，历史 job 明确不可恢复（对用户诚实）。
- 后果：`job_status` 对未知/过期 handle 必须返回明确的 stale 终态而非抛错；UI 层对
  stale 任务提示"任务已随进程结束，请重新发起"。

### 2.21 `cenhua_service/core.py` — 六核心函数 service 化（M3a 任务 2）

`ingest / find / query / related / ask / stats` 全部入 service（dataclass 返回、
零 print），CLI 只做参数解析与打印。`core.channel_job(kind, fn, *args)` 把
"返回带 `lines`/`cost` 的 dataclass"的长任务函数适配成 `jobs.JobSpec`——
ask/query/digest 三命令共用同一适配，progress/heartbeat 语义由 `jobs.run_cli`
（CLI）与 M3b 的 SSE 各自适配。`core.ask_estimate` 是深读前置段的单一事实源
（scope 解析 + 估价 + `[cost]` 渲染行，零副作用），CLI 预取 n 决定是否交互确认。

### 2.22 `cenhua_service/digest.py` + `scripts/m_digest.py` — 周期洞察（M3a）

`digest_flow` 主编排：窗口解析（`parse_window`）→ 时间窗圈选 primary 文档
（按摄取台账 ts）→ dry-run 估价 → longjob 三闸（`budget_check`：
`CENHUA_LONGJOB_MAX_COST_CNY` 默认 ¥5，all-or-nothing 拒启不中途停，F1）→
`compose` 四节文章生成（LLM 主路径 + 规则兜底；引文全量 `verify_citation`
校验；命名 `洞察_<窗口>_V{N}_<日期>.md` 集中一处生成）→ `ingest_back` 回流
闭环（复制进 inbox 走标准摄取，台账原子改写 `tier=derived-doc` +
`derived_from`；永不抛，失败不改 rc）。

图谱隔离：衍生文档与 internal-artifact 不参与建边（relations 只认 primary），
digest 产物不污染关联层。watch 只打印提示（`watch_hint`，F10），永不自动触发。
CLI `digest_cmd` 8 行薄包装：`J.submit(core.channel_job(...)) + J.run_cli`
（test_71 白名单 M3a = digest_cmd）。

### 2.23 hint 注入对抗硬化（M3a 任务 13）

`prompt._INJECT_RE`（中英 prompt-injection 形态：ignore/disregard previous、
system prompt、"忽略…指令"、"你现在是"、"新的指令"、"系统提示"）+
`_IMPERATIVE_RE`（祈使形态含 `[你您]应该/[你您]需要`，`注意(?!事项|意义|力)`
防误伤）在 hint 装配时逐句消毒。fixture 新增 `type="injection"` 对抗题
（≥1/3 `author:"human"`，防出题方与攻击方同源盲区），`bench.run_injection`
离线零 LLM 进**阻断集**：消毒后残留祈使零、事实片段零丢失，任一失败阻断发版。
hint 二段验证成本进 ROI 账：query 台账记 `hint_docs`/`hint_dropped`，
`refine.roi_lines` 并入 `cenhua refine` 状态视图（验证成本倒贴生产成本时
重新评估 hint 段价值）。

### 2.24 `cenhua_service/webui/` — 本地 Web UI + 局域网 API（M3b）

四件套薄适配层，**零业务逻辑**（一切走 `core`/`jobs`/`docmeta` service）：

- `security.py`：`resolve_token`（`CENHUA_API_TOKEN` env > vault.yaml
  `api_token`）+ `check_token` fail-closed 双拒（未配置拒一切、空 token 拒，
  `hmac.compare_digest` 常数时间）+ `RateLimiter` 滑动窗口（超限 429 +
  `Retry-After`）。纯标准库，可脱离 fastapi 单测。
- `api.py`：`build_router(vault, deps)` → `/api/v1/*`（ingest/documents/
  stats/find/query/ask/digest/relations/docmeta/jobs…）；长任务端点返回
  `job_id`+`events_url`；`graph`/`draft` 恒 404 + 版本提示（随 M4 交付）。
  错误统一 `{"detail": {error, detail, schema_version}}`；未知 job 恒定
  `aborted/stale`（200 而非 404，与 ADR-001 口径一致）。
- `pages.py`：Jinja2+HTMX 四页（摄取/检索/编织/洞察浏览）+ `/login`
  httpOnly cookie 会话；insights 正文渲染前消毒（`<script>`/onerror）+
  文件名防穿越。
- `app.py`：`create_app(vault, rate)` rid 中间件（响应头 `X-Cenhua-Rid`，
  结构化日志 `logs/web-YYYYMM.log`）；`serve()` uvicorn 薄调用，
  `timeout_keep_alive` 配置驱动（F8 无 Nginx 依赖）。
- SSE：`GET /api/v1/jobs/{id}` 把 `job_status` 增量 cursor 协议转事件流；
  断线重连带 cursor 只重放未消费段（任务通道薄适配，无独立状态）。

`scripts/m_webui.py` 仅 argparse + `serve_cmd`（CLI 入口白名单口径，
test_71）。

## 3. 关键数据流

### 3.1 摄取（含本地 OCR）

```
用户投放文件到 inbox/
  → cenhua add --inbox
  → ingest_one():
      sha1 去重（命中则跳过）
      → m_ocr.preconvert():
          图片/扫描 PDF → RapidOCR 本地转写 → 质量校验
          不达标/缺失 → 返回原文件（视觉兜底）
      → run_engine(pi_ingest.py, [engine_in])
      → 成功: restore_provenance() 台账指回原始上传
      → 自动 flatten 建文本层
```

### 3.2 检索

```
cenhua find 违约 penalty
  → 本地正则扫 <vault>/engine/text/*.txt
  → 命中带 [doc P页] + Source: 行

cenhua ask --doc contract "终止罚则是什么"
  → 树导航定位相关页 → LLM 总结 → 带引文
  → --dry-run 先估算调用数 + tokens + 金额（M2b 推广）

cenhua query "违约金条款"                       (M2b, v0.3.3)
  → 路1 find_hits 精确扫文本层（默认 primary-only）
  → 路2 semantic_hits 语义召回（无 embedding 配置则空）
  → fuse 置信度排序 → 命中入 refine 队列
  → tier: 证据段仅 primary；hint 段 = refined summaries（sanitize 祈使句）
  → 两段式 prompt → LLM → citations 逐条 verify_citation
     （失败 → derived 穿透重验 → 仍败标 [未溯源·LLM 推断]）
  → 第4段 related 关联推荐（M1b 关联层）
  → 无命中 → 拒答 rc=1
```

## 4. 关键机制

### 4.1 引擎纯净守护

`tests/test_cenhua.py::test_61_engine_is_untouched` 校验引擎文件与上游一致。
所有集成在 m 层完成，绝不修改引擎模块。

### 4.2 密钥安全

- `vault.yaml` 拒绝存储含 `key`/`token`/`secret` 的键。
- OpenClaw 网关在调用时实时解析 `~/.openclaw/openclaw.json`，一次轮换全局生效。

### 4.3 成本护栏

- `ask/query/digest --dry-run` 打印调用数 + tokens + 金额（M2b 起推广至全
  LLM 命令：ask/query/refine；M3a 起 digest 同规格；draft 随 M4 落地）。
- 长任务（digest）走 all-or-nothing 三闸：dry-run 看账 →
  `CENHUA_LONGJOB_MAX_COST_CNY` 拒启（rc=4）→ `--force`/`--max-cost` 放行；
  启动后豁免中途执法（F1）。
- `max_llm_calls`（默认 8）与 `CENHUA_MAX_COST_CNY`（默认 ¥2）并联，先到先停；
  超限需 `--force`。
- 本地 OCR 免费，降低摄取成本。

### 4.4 本地 OCR 质量校验

RapidOCR 只在识别效果好时才被信任：

```
avg_conf >= CENHUA_OCR_MIN_CONF (0.5)  AND  chars >= CENHUA_OCR_MIN_CHARS (10)
```

不达标 → 视觉大模型兜底。后端无置信度（v2 `.txts`）时仅按文本量校验。

阈值配置实例（env 优先于 vault.yaml）：

```bash
# env（临时）
export CENHUA_OCR_MIN_CONF=0.6
export CENHUA_OCR_MIN_CHARS=20

# vault.yaml（持久）
cenhua config ocr_min_conf 0.6
cenhua config ocr_min_chars 20
# 或直接编辑 vault.yaml 追加: ocr_min_conf: 0.6 / ocr_min_chars: 20

# env 覆盖 vault.yaml
CENHUA_OCR_MIN_CONF=0.9 cenhua add --inbox
```

## 5. 配置项

| 配置 | 来源 | 默认 | 说明 |
|---|---|---|---|
| `CENHUA_HOME` | env | `~/.cenhua` | 存储根 |
| `CENHUA_OCR` | env / vault.yaml `ocr` | `rapidocr` | `vision` 强制走大模型 |
| `CENHUA_OCR_MIN_CONF` | env / vault.yaml `ocr_min_conf` | `0.5` | 平均置信度阈值 |
| `CENHUA_OCR_MIN_CHARS` | env / vault.yaml `ocr_min_chars` | `10` | 最少识别字符数 |
| `PI_BASE`/`PI_KEY`/`PI_MODEL` | env | — | LLM 网关 |
| `PI_VISION_MODEL` | env | — | 视觉兜底模型（裸 ID） |
| `PI_EMBED_MODEL` | env | — | 向量模型 |
| `CENHUA_MAX_COST_CNY` | env / vault.yaml `max_cost` | `2.0` | 单命令花费上限（M1a 登记，M2b 起 ask/query 执法）；不适用 add/watch 与长任务/批量任务 |
| `CENHUA_LONGJOB_MAX_COST_CNY` | env / vault.yaml `longjob_max_cost` | `5.0` | 长任务（digest/draft）独立预算（M1a 起登记） |
| `CENHUA_DIGEST_HINT_DOCS` | env / vault.yaml `digest_hint_docs` | `20` | watch 洞察提示阈值：自上次 digest 以来新摄取文档数（M3a） |
| `CENHUA_PRICING` | env | `pricing.json` | 单价表覆盖路径（M1a） |
| `CENHUA_REFINE_BUDGET_CNY` | env | `0`（拒绝） | refine 预算硬闸，CNY；USD 报价按保守汇率折算比较（M1b） |
| `CENHUA_SMALL_CORPUS_N` | env | `200` | 小库模式阈值：N 低于该值用降档参数（M1b） |
| `CENHUA_MIN_CONTENT_CHARS` | env | `100` | 网页正文守卫下限（渲染/静态共用）（M2a） |
| `CENHUA_API_TOKEN` | env / vault.yaml `api_token` | —（未配置=拒绝一切） | Web/API 单用户 token，fail-closed（M3b） |
| `CENHUA_WEB_HOST` / `CENHUA_WEB_PORT` | env / vault.yaml `web_host` / `web_port` | `127.0.0.1` / `8765` | Web 监听地址/端口（M3b） |
| `CENHUA_WEB_RATE_CALLS` / `CENHUA_WEB_RATE_WINDOW_S` | env / vault.yaml `web_rate_calls` / `web_rate_window_s` | `30` / `60` | 滑动窗口限流（M3b） |
| `CENHUA_WEB_HEARTBEAT_S` / `CENHUA_WEB_KEEPALIVE_S` | env / vault.yaml `web_heartbeat_s` / `web_keepalive_s` | `10` / `120` | SSE 心跳间隔 / uvicorn keep-alive 秒（M3b） |

## 6. 扩展点

- **新增格式**：在 `m_lib.EXTS` 注册扩展名，引擎 `conv_*` 处理转换。
- **新增 OCR 后端**：替换 `m_ocr._get_engine()` 的导入与 `_ocr_result()`
  归一化即可。
- **新增命令**：在 `m_cenhua.py` 加路由，逻辑放对应 m 模块。
