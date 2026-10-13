"""cenhua_service.cost — 成本度量衡（M1a 核心）。

职责（roadmap §6.4 + §8.M1a + R4-F9）：
  * pricing.json 加载（随包分发，可覆盖）
  * OpenClaw 全名匹配规则（F9）：全名 `openclaw:provider/model` -> 裸 model id -> 保守默认价
  * token 估算（字符数/1.6 中英混合近似）+ 金额换算（各模型自身货币，混合货币不强行折算）
  * cost-ledger.jsonl 全量记账（T5：含 add 树索引、OCR 视觉兜底）
  * cenhua cost 汇总（按命令分组，摄取成本单列首位）
  * 预估校准闭环（偏差 >3x 告警，防单价表过期）

service 纪律：本模块禁止 print / exit。
"""

import json
import os
import time

import m_lib as L  # noqa: E402  (scripts/ 在 sys.path)

# 汇率提示脚注（混合货币时显示；不强行折算）
FX_NOTE = "（混合货币未折算，按各模型自身货币显示；汇率请以当日为准）"

# 校准告警阈值：预估偏差 >3x 告警
CALIBRATE_WARN_FACTOR = 3.0

# 默认保守单价（未配置单价时使用，并标注）
DEFAULT_PRICE = {"in": 0.0005, "out": 0.0015, "currency": "USD"}


def pricing_path():
    """pricing.json 位置：优先用户覆盖，其次随包分发。"""
    env = os.environ.get("CENHUA_PRICING")
    if env and os.path.isfile(env):
        return env
    return os.path.join(L.SKILL_DIR, "pricing.json")


def load_pricing():
    """{model: {in, out, currency}} + default。永不抛异常。"""
    try:
        with open(pricing_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    models = data.get("models") or {}
    default = data.get("default") or DEFAULT_PRICE
    return models, default


def match_price(model):
    """OpenClaw 全名匹配规则（F9）。

    返回 (price_dict, priced, note)：
      * 先按全名 `openclaw:provider/model` 精确匹配
      * 再按裸 model id 匹配
      * 未命中用保守默认价 + 输出标注
    """
    models, default = load_pricing()
    if not model:
        return default, False, "估价：未配置单价（无模型）"
    # 1) 全名精确匹配（含 openclaw: 前缀）
    if model in models:
        return models[model], True, ""
    # 2) 去掉 openclaw: 前缀再匹配
    bare = model.split(":", 1)[1] if model.startswith("openclaw:") else model
    if bare in models:
        return models[bare], True, ""
    # 3) 裸 model id 匹配（如 gpt-4o-mini）
    if bare in models:
        return models[bare], True, ""
    # 4) 保守默认价 + 标注
    return default, False, f"估价：未配置单价（{model}）"


def estimate_tokens(text):
    """token 估算：字符数/1.6（中英混合近似）。数量级正确即可。"""
    if not text:
        return 0
    return max(1, int(len(text) / 1.6))


def estimate_cost(model, tokens_in, tokens_out):
    """token -> 金额。返回 (est_cost, currency, priced, note)。

    混合货币不强行折算：单模型只有一种货币，故此处返回该模型自身货币。
    """
    price, priced, note = match_price(model)
    cost_in = tokens_in / 1000.0 * price["in"]
    cost_out = tokens_out / 1000.0 * price["out"]
    return cost_in + cost_out, price["currency"], priced, note


def format_cost(parts):
    """把 [(amount, currency), ...] 格式化为可读字符串。

    混合货币不强行折算，显示如 `¥0.35 + $0.02` 加汇率提示脚注。
    """
    if not parts:
        return "¥0.00"
    symbols = {"CNY": "¥", "USD": "$", "EUR": "€", "GBP": "£"}
    rendered = []
    for amount, currency in parts:
        sym = symbols.get(currency, currency + " ")
        rendered.append(f"{sym}{amount:.2f}")
    out = " + ".join(rendered)
    if len({c for _, c in parts}) > 1:
        out += " " + FX_NOTE
    return out


# ---------------------------------------------------------------- ledger ----
def ledger_path(vault):
    return os.path.join(vault.meta, "cost-ledger.jsonl")


def ledger_append(vault, entry):
    """写一条 cost-ledger.jsonl（全量记账，T5）。

    entry: {cmd, doc, calls, tokens_in, tokens_out, est_cost, currency, priced}
    自动补 ts。永不抛异常（记账失败不阻断主流程）。
    """
    try:
        os.makedirs(vault.meta, exist_ok=True)
        rec = {"ts": time.strftime("%F %T"), **entry}
        with open(ledger_path(vault), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_ledger(vault):
    """读取全部 ledger 记录（list[dict]）。"""
    path = ledger_path(vault)
    if not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def _month_key(ts):
    """'2026-10-13 10:00:00' -> '2026-10'。"""
    return ts[:7] if ts and len(ts) >= 7 else ""


def cost_summary(vault, month=None):
    """按命令分组汇总。返回 (groups: list[(cmd, {calls, cost, currency_parts})],
    total_parts, total_calls)。

    摄取成本单列首位（T5）：ingest 组排最前。
    """
    records = read_ledger(vault)
    if month:
        records = [r for r in records if _month_key(r.get("ts", "")) == month]
    groups = {}
    for r in records:
        cmd = r.get("cmd", "other")
        g = groups.setdefault(cmd, {"calls": 0, "cost": 0.0, "parts": []})
        g["calls"] += r.get("calls", 0)
        g["cost"] += r.get("est_cost", 0.0)
        g["parts"].append((r.get("est_cost", 0.0), r.get("currency", "CNY")))
    # 摄取成本单列首位
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] != "ingest", kv[0]))
    total_calls = sum(g["calls"] for _, g in ordered)
    total_parts = []
    for _, g in ordered:
        total_parts.extend(g["parts"])
    return ordered, total_parts, total_calls


def cost_report_lines(vault, month=None):
    """生成 `cenhua cost` 的可打印行（service 层组装，CLI 只负责输出）。"""
    groups, total_parts, total_calls = cost_summary(vault, month=month)
    if not groups:
        return ["(no cost ledger yet — run an LLM command like `cenhua ask` "
                "or `cenhua add` to start recording)"]
    lines = [f"cost ledger{(' for ' + month) if month else ''} "
             f"({total_calls} LLM calls):"]
    for cmd, g in groups:
        mark = "  <- ingest (tree index, 摄取固有成本)" if cmd == "ingest" else ""
        lines.append(f"  {cmd:<10} {g['calls']:>4} calls  "
                     f"{format_cost(g['parts'])}{mark}")
    lines.append(f"  {'TOTAL':<10} {total_calls:>4} calls  "
                 f"{format_cost(total_parts)}")
    return lines


# ------------------------------------------------------------ calibration ----
def calibrate(vault, actual_cost, est_cost, model=""):
    """预估校准闭环：预估偏差 >3x 告警，防单价表过期。

    返回告警消息（无告警返回 ""）。不 print。
    """
    if est_cost <= 0:
        return ""
    ratio = actual_cost / est_cost
    if ratio > CALIBRATE_WARN_FACTOR or ratio < 1.0 / CALIBRATE_WARN_FACTOR:
        return (f"[calibrate] 预估偏差 {ratio:.1f}x（预估 {est_cost:.3f} vs "
                f"实际 {actual_cost:.3f}）——单价表可能过期，请核对 pricing.json"
                + (f"（model={model}）" if model else ""))
    return ""
