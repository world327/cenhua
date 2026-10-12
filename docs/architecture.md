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
- `configure_gateway()`：一次性网关决策，绝不静默（退出码 5）。
- `confirm_location()`：存储位置决策（退出码 6）。
- `feature_report()`：打印各功能开关状态。

### 2.4 `m_vault.py` — 库管理

- `init` / `listing` / `use` / `rm` / `status` / `doctor` / `sources`。
- `doctor` 分 5 段自检：python/引擎、网关、图片与扫描件（本地 OCR + 视觉
  兜底）、向量层、存储完整性。

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
  → --dry-run 先估算调用数
```

## 4. 关键机制

### 4.1 引擎纯净守护

`tests/test_cenhua.py::test_61_engine_is_untouched` 校验引擎文件与上游一致。
所有集成在 m 层完成，绝不修改引擎模块。

### 4.2 密钥安全

- `vault.yaml` 拒绝存储含 `key`/`token`/`secret` 的键。
- OpenClaw 网关在调用时实时解析 `~/.openclaw/openclaw.json`，一次轮换全局生效。

### 4.3 成本护栏

- `ask --dry-run` 打印调用数。
- `max_llm_calls`（默认 8）上限，超限需 `--force`。
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

## 6. 扩展点

- **新增格式**：在 `m_lib.EXTS` 注册扩展名，引擎 `conv_*` 处理转换。
- **新增 OCR 后端**：替换 `m_ocr._get_engine()` 的导入与 `_ocr_result()`
  归一化即可。
- **新增命令**：在 `m_cenhua.py` 加路由，逻辑放对应 m 模块。
