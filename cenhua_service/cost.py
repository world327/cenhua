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


# ------------------------------------------------------------ 预估/预算闸 ----
# CENHUA_MAX_COST_CNY（单命令花费上限，默认 2.0）：与 CENHUA_MAX_LLM_CALLS
# 并联先到先停；不适用 add/watch（摄取无预算拒执）；不适用 digest/draft/
# refine --drain（长任务/批量任务豁免中途执法，F1）。
MAX_COST_ENV = "CENHUA_MAX_COST_CNY"

# 保守汇率上限（闸只收紧不放松；混合货币显示时不折算）
FX_UPPER = {"CNY": 1.0, "USD": 7.4, "EUR": 8.0, "GBP": 9.4}


def max_cost_cny(vault=None):
    """env > vault.yaml(max_cost) > 2.0；非法值回落 2.0。"""
    raw = os.environ.get(MAX_COST_ENV)
    if raw is None and vault is not None:
        raw = (vault.cfg() or {}).get("max_cost")
    try:
        return float(raw) if raw not in (None, "") else 2.0
    except ValueError:
        return 2.0


def estimate_prompt(prompt_text, calls=1, out_tokens=900, model=None):
    """prompt 文本 -> 预估 dict（calls/tokens/金额），dry-run 通用。"""
    m = model or os.environ.get("PI_MODEL", "openai/gpt-4o-mini")
    tin = estimate_tokens(prompt_text)
    est_cost, currency, priced, note = estimate_cost(m, tin, out_tokens)
    return {"calls": calls, "tokens_in": tin, "tokens_out": out_tokens,
            "model": m, "est_cost": est_cost, "currency": currency,
            "priced": priced, "note": note}


def estimate_docs(doc_texts, out_tokens=900, model=None):
    """多文档深读（ask）预估：每文档一次调用，输入=正文长度。"""
    m = model or os.environ.get("PI_MODEL", "openai/gpt-4o-mini")
    tin = sum(estimate_tokens(t or "") for t in doc_texts)
    tout = out_tokens * max(1, len(doc_texts))
    est_cost, currency, priced, note = estimate_cost(m, tin, tout)
    return {"calls": len(doc_texts), "tokens_in": tin, "tokens_out": tout,
            "model": m, "est_cost": est_cost, "currency": currency,
            "priced": priced, "note": note}


def to_cny(amount, currency):
    """按保守汇率上限折 CNY（仅用于闸门比较，不用于展示折算）。"""
    return amount * FX_UPPER.get(currency, 7.4)


def cost_gate(vault, est, force=False):
    """CENHUA_MAX_COST_CNY 预算闸。返回 (ok, message)。

    超出时 force 放行（仍全量记账）。
    """
    limit = max_cost_cny(vault)
    cost = est.get("est_cost") or 0.0
    cur = est.get("currency", "CNY")
    cost_cny = to_cny(cost, cur)
    shown = f"{cost:.4f} {cur}" + (f" ≈¥{cost_cny:.4f}" if cur != "CNY" else "")
    if cost_cny <= limit:
        return True, f"within budget ({shown} <= ¥{limit:g})"
    if force:
        return True, f"estimate {shown} exceeds ¥{limit:g}; --force overrides"
    return False, (f"estimate {shown} exceeds ¥{limit:g} ({MAX_COST_ENV}); "
                   f"raise it or pass --force")


def dry_run_cost_lines(est, vault=None, gate=None, prefix="cost"):
    """dry-run 金额预估输出行（M2b 推广至全 LLM 命令：calls+tokens+金额）。"""
    lines = [
        f"[{prefix}] calls     : ~{est['calls']} LLM call(s)",
        f"[{prefix}] tokens    : ~{est['tokens_in']} in / ~{est['tokens_out']} out",
        f"[{prefix}] gateway   : {est['model']}",
        f"[{prefix}] estimate  : "
        + format_cost([(est["est_cost"], est["currency"])])
        + ("" if est["priced"] else f"  ({est['note']})"),
        f"[{prefix}] budget    : ¥{max_cost_cny(vault):g} ({MAX_COST_ENV})",
    ]
    if gate is not None:
        lines.append(f"[{prefix}] gate      : {gate}")
    return lines


# ------------------------------------------------------------ 预估/预算闸 ----
# M2b 成本货币化推广：通用 estimate_prompt/estimate_docs/cost_gate/dry_run_cost_lines。
# 预算以 CNY 计（CENHUA_MAX_COST_CNY，env > vault.yaml max_cost > 2.0 保守默认）；
# 模型报价可能是 USD 等，按保守汇率上限折 CNY 再比（闸只收紧不放松）。
MAX_COST_ENV = "CENHUA_MAX_COST_CNY"
FX_UPPER = {"CNY": 1.0, "USD": 7.4, "EUR": 8.0, "GBP": 9.4}


def max_cost_cny(vault=None):
    """预算上限（CNY）。env > vault.yaml max_cost > 2.0 保守默认。"""
    env = os.environ.get(MAX_COST_ENV)
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    if vault is not None:
        try:
            return float(vault.cfg().get("max_cost", "2.0"))
        except ValueError:
            pass
    return 2.0


def to_cny(amount, currency):
    """按保守汇率上限折 CNY（只收紧不放松）。"""
    return amount * FX_UPPER.get(currency, 7.4)


def estimate_prompt(model, prompt_text, tokens_out=1400):
    """按 prompt 文本估价。返回
    {"tokens_in", "tokens_out", "est_cost", "currency", "priced", "note"}。
    """
    tin = estimate_tokens(prompt_text)
    est, currency, priced, note = estimate_cost(model, tin, tokens_out)
    return {"tokens_in": tin, "tokens_out": tokens_out,
            "est_cost": est, "currency": currency,
            "priced": priced, "note": note}


def estimate_docs(model, texts, tokens_out_per=1400):
    """按文档正文列表估价（ask/query 等）。texts: list[str]。
    返回 {"docs", "tokens_in", "tokens_out", "est_cost", "currency",
          "priced", "note"}。
    """
    tin = sum(estimate_tokens(t) for t in texts)
    tout = tokens_out_per * max(1, len(texts))
    est, currency, priced, note = estimate_cost(model, tin, tout)
    return {"docs": len(texts), "tokens_in": tin, "tokens_out": tout,
            "est_cost": est, "currency": currency,
            "priced": priced, "note": note}


def cost_gate(vault, est, force=False):
    """预算闸。返回 (ok, message)。est 需含 est_cost/currency。"""
    limit = max_cost_cny(vault)
    cost = est.get("est_cost") or 0.0
    cur = est.get("currency", "CNY")
    cost_cny = to_cny(cost, cur)
    shown = f"{cost:.4f} {cur}" + (f" ≈¥{cost_cny:.4f}" if cur != "CNY" else "")
    if cost_cny <= limit:
        return True, f"within budget ({shown} <= ¥{limit:g})"
    if force:
        return True, (f"estimate {shown} exceeds budget ¥{limit:g}; "
                      f"--force overrides")
    return False, (f"estimate {shown} exceeds budget ¥{limit:g} "
                   f"({MAX_COST_ENV}); raise the budget or pass --force")


def dry_run_cost_lines(vault, est):
    """--dry-run 金额预估报告行（供 CLI 打印；格式化在 service 层）。"""
    lines = [
        f"[cost] gateway    : {est.get('model', '')}",
        f"[cost] estimate   : "
        + format_cost([(est["est_cost"], est["currency"])])
        + ("" if est.get("priced") else f"  ({est.get('note', '')})"),
        f"[cost] budget     : {max_cost_cny(vault):g} CNY "
        f"({MAX_COST_ENV}; env > vault.yaml max_cost > 2.0)",
    ]
    ok, msg = cost_gate(vault, est)
    lines.append(f"[cost] gate       : {'PASS' if ok else 'REFUSE'} — {msg}")
    return lines


# ------------------------------------------------------- calibration ----
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
