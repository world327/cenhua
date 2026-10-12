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

## 7. 安装与决策

- 安装时两个确认（网关退出码 5、存储位置退出码 6）**不可由智能体代答**，
  必须转达用户。
- 存储位置决策后数据生命周期长于技能安装；迁移用 `cenhua home set <path>`
  （自动搬移已有库）。

## 8. 测试

- 全套离线测试：`bash tests/run_tests.sh`（unit 34 + OCR 14 + semantic +
  formats + smoke），无需 API key。
- 本地 OCR 单测：`python3 tests/test_ocr.py`（后端打桩、渲染真实）。
