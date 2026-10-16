# CENHUA 避坑指南（Pitfalls）

> 从真实失败中总结的坑，不要重新踩一遍。`cenhua doctor` 会自动检查大部分项。
> 引擎层（pageindex-rag）的坑见 `references/engine-pitfalls.md`，本文档聚焦
> 项目整体与本地 OCR。

## 1. 本地 OCR（RapidOCR）相关

### 1.1 RapidOCR 是必需依赖

- 图片/扫描件默认走 RapidOCR 本地识别。**未安装时**自动回退视觉大模型，但
  会多花 LLM 成本。安装：`pip install rapidocr-onnxruntime`（已写入
  requirements.txt，`cenhua setup` 会装）。
- 包名是 `rapidocr-onnxruntime`（经典 wheel）或 `rapidocr`（v2 统一包），
  两者都内置模型，完全离线。

### 1.2 识别效果校验（关键）

RapidOCR 只在识别好时才被信任，否则触发视觉兜底：

```
平均置信度 >= CENHUA_OCR_MIN_CONF (0.5)  且  识别字符 >= CENHUA_OCR_MIN_CHARS (10)
```

- **低置信度**：模糊、倾斜、低分辨率图片平均置信度低 → 自动走大模型。
- **字符过少**：空白/噪声图识别字符 < 10 → 自动走大模型。
- **无置信度后端**（rapidocr v2 `.txts`）：仅按文本量校验。

**阈值配置实例**（env 优先于 vault.yaml）：

```bash
# env（临时，本次会话生效）
export CENHUA_OCR_MIN_CONF=0.6
export CENHUA_OCR_MIN_CHARS=20

# vault.yaml（持久，写入库配置）
cenhua config ocr_min_conf 0.6
cenhua config ocr_min_chars 20
# 或直接编辑 ~/.cenhua/vaults/<库名>/vault.yaml 追加：
#   ocr_min_conf: 0.6
#   ocr_min_chars: 20

# env 覆盖 vault.yaml（本次运行临时调高）
CENHUA_OCR_MIN_CONF=0.9 cenhua add --inbox
```

### 1.3 常见坑

- **噪声/纯色图**：RapidOCR 可能抛 `image file is truncated` 或返回空 → 已
  自动兜底，属正常行为，不是 bug。
- **转写 PDF 缓存**：`<vault>/meta/ocr/<stem>_<sha8>.pdf`。同一文件重试不
  重复 OCR；若想强制重识别，删掉对应缓存文件。
- **强制走大模型**：`CENHUA_OCR=vision` 或 `cenhua config ocr vision`。
- **OCR 文本带数字噪声**：卡号/账号用完整形式 + 去空格/连字符变体搜；尾号
  片段只当线索。`cenhua find -r` 加边界 `(?<![\dA-Za-z])NUM(?![\dA-Za-z])`。
- **OCR 的身份证号常有 1-2 位错**：用 `engine/id_verify.py` 校验；校验失败
  前不得下身份结论。

## 2. 检索正确性

- **加密 PDF 会被朴素扫描静默跳过**：`pymupdf.open()` + `get_text()` 对密码
  PDF 抛异常，`except: continue` 会整篇丢弃，导致误判"库里没有"。先试文件名
  数字段 `doc.authenticate(<digits>)`，解密后再摄取，绝不记录密码。
- **绝不可凭一条路径断言"语料里没有"**：`find` 命中与源文件负扫描必须一致；
  某路径失败（超时/崩溃/空文本层）时，它的沉默不是证据。
- **人名**：一次 `find` 扫同音/异体变体（`find 张三 张山 章三`）。

## 3. 文本层新鲜度（经典静默漏检陷阱）

- `find` 读的是 `engine/text/`，不是 PDF。摄取后必须 flatten，否则 `find`
  静默漏掉新文档。CENHUA 摄取后自动 flatten，`find` 内也会自动补 flatten——
  不要禁用（`--no-flatten` 仅用于批量重摄取）。
- `pages.json` 字段名是 `markdown` / `page_index`（旧版 `content` / `page`），
  flatten 两者都容忍；猜错会导出空白文本层。
- **`cenhua doctor` 把空文本层标为 PROBLEM，绝不忽略。**

## 4. 引擎纯净守护

- `scripts/engine/` 必须与上游 pageindex-rag 字节一致（`test_61` 守护）。
  所有集成在 m 层完成，**绝不修改引擎模块**。升级引擎时 diff 校验。

## 5. 密钥安全

- `vault.yaml` 拒绝存储含 `key`/`token`/`secret` 的键。
- OpenClaw 网关在调用时实时解析 `~/.openclaw/openclaw.json`，一次轮换全局
  生效，密钥绝不复制到 CENHUA 文件。

## 6. 成本控制

- `ask` 前先 `--dry-run` 看调用数；`max_llm_calls` 默认 8，超限需 `--force`。
- 慢的"搜索"几乎总是 LLM 链（树导航 + 回答 = 每文档 ≥2 次往返，failover 会
  放大挂起），不是本地扫描。先 profile 再怪检索——`find` 是免费的。
- 本地 OCR 免费，能显著降低图片/扫描摄取成本。
- **全量记账，仅免预算闸**（M1a）：所有 LLM 调用（含摄取树索引）都写
  `cost-ledger.jsonl`，`cenhua cost` 按命令分组，摄取成本单列首位。用户见账
  必须等于实烧，杜绝"见账 3 元、实烧 30 元"。
- **预算闸豁免**：`CENHUA_MAX_COST_CNY`/`CENHUA_MAX_LLM_CALLS` 不适用
  `add`/`watch`（摄取无预算拒执，防半成品库）；长任务/批量任务豁免中途执法。
- **单价表过期**：预估偏差 >3x 会告警（`cenhua cost` 校准闭环），此时核对
  `pricing.json` 单价是否过期。
- **混合货币**：不同模型用不同货币时，`cenhua cost` 不强行折算，显示
  `¥0.35 + $0.02` 加汇率提示脚注。

## 7. 安装与决策

- 安装时两个确认（网关退出码 5、存储位置退出码 6）**不可由智能体代答**，
  必须转达用户。
- 存储位置决策后数据生命周期长于技能安装；迁移用 `cenhua home set <path>`
  （自动搬移已有库）。

## 8. 测试

- 全套离线测试：`bash tests/run_tests.sh`（unit 34 + **service 19** +
  **web 24** + OCR 14 + semantic + formats + smoke），无需 API key。
- 本地 OCR 单测：`python3 tests/test_ocr.py`（后端打桩、渲染真实）。
- **service 层纪律**：`cenhua_service/` 禁 `print`/`exit`（`test_70` 全量生效）；
  白名单命令 CLI 薄包装（`test_71`，M1a: cost/bench）。
- **质量门禁**：`cenhua bench` 跑 fixture（存在性 100% + 引文条目 ≥95%），
  发版前必跑；`--corpus` 跑用户库 QA（报告模式）。
- **`m_lib.HOME` 是 import 时常量**：测试文件若要重定向存储根，必须在
  **import 任何 m 模块之前**设置 `CENHUA_HOME` env（setUpClass 里设无效，
  见 test_service.py / test_web.py 顶部写法）。

## 9. 网页收录（M2a）

- **双产物不要都进索引**：HTML 快照与渲染 PDF 内容重复，索引它会污染检索
  且双倍 sha1；快照归档 `works/snapshots/`（溯源用），只有 PDF 进 inbox。
  无 PDF（静态降级）时 HTML 才直接进 inbox，保证内容不丢。
- **产物必须写 vault 根 inbox**（`url-` 前缀标注来源）：`ingest_one()` 的
  `.processed/.failed` 暂存语义只对 inbox 根的文件生效，写子目录会丢暂存。
- **树索引需要 LLM 网关**（`PI_BASE/PI_KEY`）：无网关时 `add --url` 抓取与
  产物落盘成功、摄取失败进 `.failed/`——测试按"失败隔离"设计断言，
  不假装端到端成功。
- **chromium 缺系统库（WSL2 常见）**：`playwright install chromium` 只装
  浏览器二进制；`--with-deps` 才装 libnss3 等。doctor 启动自检失败时输出
  `sudo playwright install-deps chromium`；运行时自动降级静态抓取，不断链。
- **robots.txt 不可达选择 fail-open**：站点没放 robots.txt 很常见，
  fail-closed 会误伤；明确 Disallow 才拒绝。明确禁爬默认拒绝，
  `--force` 显式覆盖（个人知识库自用场景，如微信公众号）。
- **UA 按 bot 判定的站点要浏览器语境**：微信公众平台对默认 UA 返回
  "环境异常"验证页（渲染成功但正文是空壳）。渲染走 `new_context(
  user_agent=BROWSER_UA, locale='zh-CN')`，静态抓取也带浏览器 UA。
  排障口诀：**渲染"成功"但正文极短 → 先怀疑反爬验证页，不是抓取失败**。
- **`wait_until` 用 `domcontentloaded` 而非 `networkidle`**：信息流站点
  （头条 m 站）埋点/长连接让网络永不空闲，networkidle 必然拖到 60s 超时
  后降级静态——而静态 HTML 可见文本为 0（纯 JS 渲染），最终 PDF 0 字符。
  正解：`domcontentloaded` + 固定等 JS 渲染（实测头条 3s 出正文）。
- **整页 PDF 会被噪声淹没**：信息流站整页渲染把导航、推荐流、评论、播放
  列表全排进去（实测页首是"首页 反馈 下载 扫码下载"，正文标题被埋）。
  进索引的 PDF 用 readability 提取正文后**重新排版**（`build_clean_html`），
  整页只留在 HTML 快照溯源。
- **正文守卫（MIN_CONTENT_CHARS，默认 100）**：JS 空壳页/反爬验证页会
  "抓取成功"但正文极少，必须在 fetch 层拦下给出可读错误，否则到 PDF 转换
  才以 `layout integrity check failed: PDF has 0 chars` 崩。
- **JS 动态提取文本时**别用字符串 `*10`（JS 里得 `NaN`），用 `.repeat(10)`。
- **MB 级 HTML 转 PDF 是分钟级**：引擎 `insert_htmlbox` 逐块排版，5MB 页面
  转换实测 >80s（无网关时也先转换再报 env 缺失）。截断行为测试用
  `CENHUA_MAX_PAGE_BYTES` 调小上限，别真转 5MB。
- **测试内 HTTP server 用 ThreadingTCPServer**：客户端按大小上限提前收手时，
  单线程 `TCPServer` 会永久阻塞在 `wfile.write`（死锁假象）；handler 还需
  吞掉 `BrokenPipeError`。
