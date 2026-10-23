# CENHUA macOS 专属安装指南（Apple Silicon / Intel）

> 面向 **Mac mini（Apple Silicon M 系列，arm64）** 的本地安装。
> Intel Mac（x86_64）同样适用，仅个别依赖版本不同（见 §5）。
> 本指南覆盖：依赖兼容性 → 安装步骤 → 常驻服务 → 常见问题。

---

## 1. 兼容性结论

**完全支持。** 项目无 GPU/CUDA 硬依赖（OCR 用 RapidOCR + onnxruntime **CPU 推理**），
无 Linux 专属路径假设，所有依赖在 macOS arm64 均有可用 wheel。

| 依赖 | macOS arm64 | 说明 |
|---|---|---|
| onnxruntime | ✅ 最高 1.19.2 | pip 自动选 arm64 版（更高版本无 arm64 wheel） |
| rapidocr-onnxruntime | ✅ | 纯 Python 包装，要求 `onnxruntime>=1.7`，1.19.2 满足 |
| pypdfium2 | ✅ | pageindex 依赖 |
| pymupdf | ✅ | PDF 渲染 |
| opencv-python | ✅ | OCR 依赖 |
| playwright | ✅ | 网页摄取（可选） |
| litellm / pyyaml | ✅ | pageindex 依赖 |
| mammoth / python-pptx / openpyxl / xlrd / olefile / fastapi / feedparser | ✅ 纯 Python | `py3-none-any` 跨平台 |

**唯一注意点**：onnxruntime 在 macOS arm64 最高 1.19.2（更高版本无 arm64 wheel）。
pip 会自动降级选择，无需手动指定。若未来 rapidocr 要求更高 onnxruntime 版本需留意。

---

## 2. 前置准备

### 2.1 安装 Python 3.12（Homebrew）

```bash
# 安装 Homebrew（若未装）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 安装 Python 3.12
brew install python@3.12
python3.12 --version   # 确认
```

> 建议用 venv 隔离，避免污染系统 Python。

### 2.2 克隆仓库

```bash
git clone https://github.com/world327/cenhua && cd cenhua
```

---

## 3. 安装步骤

### 3.1 创建虚拟环境 + 装依赖

```bash
python3.12 -m venv .venv
source .venv/bin/activate

# 升级 pip + 装依赖
pip install --upgrade pip
pip install -r requirements.txt
```

> **onnxruntime 版本**：macOS arm64 上 pip 会自动选 1.19.2（最高可用）。
> 若想显式锁定，可 `pip install onnxruntime==1.19.2`。

### 3.2 安装 Playwright chromium（网页摄取，可选）

```bash
playwright install chromium
```

> 网页收录（`cenhua add --url`）需要；纯本地文件摄取可跳过。

### 3.3 初始化 + 配置网关

```bash
# 建默认库
./bin/cenhua init work --title "工作" --yes

# 配置 LLM 网关（query/ask/digest/draft 需要；find/摄取离线可用）
export PI_BASE=https://api.example.com/v1
export PI_KEY=你的密钥
export PI_MODEL=openai/gpt-4o-mini
```

> 网关配置也可写入 `~/.cenhua/vaults/work/vault.yaml`（见 user-guide §1.3）。
> **无网关也能用**：摄取/检索/Web UI 走离线降级（M5-4），仅 LLM 功能不可用。

### 3.4 验证安装

```bash
# 自检（应显示依赖齐全、网关状态）
./bin/cenhua doctor

# 离线冒烟：摄取 + 检索
echo "测试内容 中文语料" > /tmp/test.txt
./bin/cenhua add /tmp/test.txt
./bin/cenhua find 中文
```

---

## 4. 常驻服务（Web UI + 局域网 API）

macOS 没有 systemd，用 **launchd** 或直接 `service.sh`。

### 4.1 方式 A：直接启动（前台/后台）

```bash
# 前台（调试用）
./bin/cenhua web --vault work

# 后台（service.sh，nohup & disown）
CENHUA_VAULT=work deploy/service.sh start
deploy/service.sh status
deploy/service.sh stop
```

### 4.2 方式 B：launchd 常驻（推荐，开机自启）

创建 `~/Library/LaunchAgents/com.cenhua.web.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.cenhua.web</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/你的用户名/cenhua/.venv/bin/python</string>
    <string>/Users/你的用户名/cenhua/scripts/m_webui.py</string>
    <string>--vault</string>
    <string>work</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/你的用户名/cenhua</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CENHUA_HOME</key>
    <string>/Users/你的用户名/.cenhua</string>
    <key>PI_BASE</key>
    <string>https://api.example.com/v1</string>
    <key>PI_KEY</key>
    <string>你的密钥</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/你的用户名/cenhua/logs/web-stdout.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/你的用户名/cenhua/logs/web-stderr.log</string>
</dict>
</plist>
```

加载：

```bash
launchctl load ~/Library/LaunchAgents/com.cenhua.web.plist
launchctl start com.cenhua.web
# 验证
curl http://127.0.0.1:8765/health
```

> 浏览器打开 http://127.0.0.1:8765 进入 Web UI（首次需登录，token 见 vault.yaml）。

---

## 5. Intel Mac（x86_64）差异

- **onnxruntime**：Intel Mac 可装到最新版（有 x86_64 macOS wheel），无 1.19.2 上限。
- 其余依赖与 Apple Silicon 相同。
- 安装步骤完全一致。

---

## 6. 常见问题（FAQ）

### Q1: `pip install onnxruntime` 报 "No matching distribution"
macOS arm64 上 onnxruntime 最高 1.19.2。若 pip 尝试装更高版本失败，显式指定：
```bash
pip install onnxruntime==1.19.2
```

### Q2: OCR 不工作 / RapidOCR 报错
- 确认 `rapidocr-onnxruntime` 已装：`pip show rapidocr-onnxruntime`
- 确认 onnxruntime 版本：`pip show onnxruntime`（arm64 应为 1.19.2）
- 若仍失败，`cenhua doctor` 会提示；OCR 会自动降级到视觉大模型兜底（需网关）

### Q3: Playwright 网页摄取失败
- 确认已 `playwright install chromium`
- macOS 首次运行可能弹"允许网络访问"系统提示，需允许

### Q4: 如何开机自启？
用 §4.2 的 launchd plist（`RunAtLoad` + `KeepAlive`）。

### Q5: 无网关能用吗？
能。摄取/检索/Web UI 走离线降级（M5-4）；仅 `query/ask/digest/draft` 等 LLM 功能需网关。

---

## 7. 相关文档

- [用户使用手册](user-guide.md) — 完整命令与日常使用
- [技术架构](architecture.md) — 系统设计
- [避坑指南](pitfalls.md) — 已知坑与规避
