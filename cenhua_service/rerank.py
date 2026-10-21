"""cenhua_service.rerank — M4c-15 重排器（roadmap §6.6）。

粗召回（fuse 三路融合）后取 top * POOL_MULT 候选，用一次小模型调用按
"与问题的相关性"重排，提升 Top-K 精度。

纪律（规则优先/失败降级，AGENTS.md §1）：
  * 开关：env CENHUA_RERANK（0/off/false 关）> vault.yaml rerank > 默认开；
  * 任何不满足条件（候选不足 / 网关未配置 / 调用失败 / 输出不可解析）
    一律**原序降级**，绝不因重排失败拖垮 query；
  * 成本极小（预览截断 PREVIEW_CHARS/候选），估价与台账由 query_flow 负责
    （三闸顺序在 query_flow 统一执法，本模块只产出 prompt 与纯函数）。

service 纪律：不 print/exit（test_70）。
"""

import json
import os
import re

import m_lib as L  # noqa: E402

POOL_MULT = 3          # 粗召回池 = top * 3
PREVIEW_CHARS = 220    # 每候选进 prompt 的首预览字数
ENV_FLAG = "CENHUA_RERANK"

_ORDER_SCHEMA = '{"order": [候选编号按相关性从高到低，整数数组]}'


def enabled(vault):
    """重排开关。env CENHUA_RERANK > vault.yaml rerank > 默认开。"""
    raw = os.environ.get(ENV_FLAG)
    if raw is None and vault is not None:
        try:
            raw = (vault.cfg() or {}).get("rerank")
        except Exception:
            raw = None
    if raw is None:
        return True
    return str(raw).strip().lower() not in ("0", "off", "false", "no", "")


def previews(vault, pool):
    """候选 -> [{"idx","name","preview"}]（text_pages 首页前段）。"""
    out = []
    for i, a in enumerate(pool):
        prev = ""
        try:
            pages = L.text_pages(vault, a["doc"])
            if pages:
                prev = pages[0][1].strip()[:PREVIEW_CHARS]
        except Exception:
            pass
        out.append({"idx": i, "name": (a.get("name") or a["doc"])[:40],
                    "preview": prev})
    return out


def build_prompt(question, cands):
    """小模型重排 prompt：编号候选 + 只输出 JSON order。"""
    lines = [
        "你是检索重排器。判断每个候选文档与问题的相关性，"
        "按相关性从高到低输出候选编号。",
        "只输出一个 JSON 对象，不要其他文字：",
        _ORDER_SCHEMA,
        f"\n问题：{question}",
        "候选：",
    ]
    for c in cands:
        lines.append(f"[{c['idx']}] {c['name']}：{c['preview']}")
    return "\n".join(lines)


def prepare(vault, question, fused, top):
    """可重排则返回 (prompt, pool)；候选 <= top 返回 None。"""
    if len(fused) <= top:
        return None
    pool = fused[:top * POOL_MULT]
    return build_prompt(question, previews(vault, pool)), pool


def parse_order(text, n):
    """LLM 输出 -> 长度 n 的编号排列（无效丢弃、缺失按原序补尾）。

    不可解析 -> None（调用方原序降级）。
    """
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        order = json.loads(m.group(0)).get("order")
    except (ValueError, AttributeError):
        return None
    if not isinstance(order, list):
        return None
    seen, out = set(), []
    for x in order:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= i < n and i not in seen:
            seen.add(i)
            out.append(i)
    out += [i for i in range(n) if i not in seen]
    return out


def apply(prompt, fused, pool):
    """执行一次重排调用。返回 (fused_new, note, (tin,tout)|None)。

    调用失败/输出不可解析 -> (原 fused, 降级说明, None)。永不抛。
    """
    from cenhua_service import refine as R
    try:
        raw, tin, tout = R.call_llm(prompt, max_tokens=200)
    except Exception as e:
        return fused, f"调用失败原序（{type(e).__name__}）", None
    order = parse_order(raw, len(pool))
    if order is None:
        return fused, "输出不可解析原序", None
    rest = [a for i, a in enumerate(fused) if i >= len(pool)]
    return [pool[i] for i in order] + rest, "ok", (tin, tout)


def rerank(vault, question, fused, top):
    """prepare + apply 的便捷入口（供单测/独立调用）。"""
    prepared = prepare(vault, question, fused, top)
    if prepared is None:
        return fused, "skip(候选<=top)", None
    prompt, pool = prepared
    return apply(prompt, fused, pool)
