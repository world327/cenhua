"""cenhua_service.prompt — ★ hint 两段式 prompt（M2b F3 首发）。

结构（hint-not-evidence，§7.3）：
  [HINT tier=internal]  精化摘要（refined summaries），仅作背景提示，非证据
  [EVIDENCE tier=primary]  证据段（仅 primary 原文），LLM 事实只来自这里

安全（防提示注入）：
  * sanitize_hint 逐句消毒：剔除祈使句（请/务必/必须/禁止/不要/忽略…），
    一处注入只废掉该句，不废整段（逐句而非整段）。
  * _INSTRUCTION 明确 HINT 段不是证据、事实只来自 EVIDENCE 段 + snippet 逐字。
  * 引文强制 snippet（F2）：无 snippet 的引文在门禁计失败。

service 纪律：不 print/exit（test_70）。
"""

import json
import re

from cenhua_service import summaries as S  # noqa: E402

HINT_MARK = "[HINT tier=internal]"
EVIDENCE_MARK = "[EVIDENCE tier=primary]"
UNVERIFIED = "[未溯源·LLM 推断]"

# 祈使句判定：句首/句中双字祈使词（单字"须/应"不匹配，防误伤合同条款）
_IMPERATIVE_RE = re.compile(
    r"(?:^|[，,。；;：:\s])(?:请|麻烦|务必|切勿|禁止|不要|不准|别|应该|需要你|"
    r"建议你|让我们|立即执行|现在开始|记住|注意|注意：)|必须|应当|严禁|请勿")

# 注入特征（英文）：忽略先前指令 / 你现在是 / 系统提示 / 新指令
_INJECT_RE = re.compile(
    r"(?:\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+)?"
    r"(?:previous|prior|above)\b|\byou\s+(?:must|should|are)\s+now\b|"
    r"\bsystem\s+prompt\b|\bnew\s+instructions?\b)", re.I)

# 切句正则：中文句读 / 英文 .!? 仅后跟空白才切（防 "128.5万元" 切碎）
_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])|(?<=[.!?])(?=\s)|\n")


def is_imperative(sentence):
    """判定一句是否祈使/注入。前导空格让句首词也能被 `^` 匹配。"""
    s = " " + sentence.strip()
    return bool(_IMPERATIVE_RE.search(s) or _INJECT_RE.search(s))


def sanitize_hint(text):
    """逐句消毒 hint 文本。返回 (clean, dropped)。

    剔除祈使句/注入句；保留其余。空输入 -> ("", 0)。
    """
    if not text:
        return "", 0
    kept, dropped = [], 0
    for sent in _SENT_SPLIT.split(text):
        s = sent.strip()
        if not s:
            continue
        if is_imperative(s):
            dropped += 1
            continue
        kept.append(s)
    return " ".join(kept), dropped


def hint_block(vault, doc_ids):
    """生成 HINT 段（仅 refined summaries，逐句消毒）。

    返回 (lines, {"docs": n, "dropped_imperative": m})。
    无可用 hint -> 占位行（明示而非沉默）。
    """
    lines = [HINT_MARK]
    dropped = 0
    used = 0
    for did in doc_ids:
        summ = S.load_summary(vault, did)
        if not summ or summ.get("status") != S.STATUS_REFINED:
            continue
        summary = (summ.get("refined") or {}).get("summary") or ""
        clean, d = sanitize_hint(summary)
        dropped += d
        if not clean:
            continue
        used += 1
        lines.append(f"- [{summ.get('name', did)[:40]}] {clean}")
    if not used:
        lines.append("(无可用 hint——相关文档尚未精化；"
                     "cenhua refine --drain 生产)")
    return lines, {"docs": used, "dropped_imperative": dropped}


def evidence_block(segments):
    """生成 EVIDENCE 段。segments: [(doc_id, name, page, text)]。

    每段以 `--- [doc[:8] P页] name ---` 分隔，正文原样（LLM 逐字摘录）。
    """
    lines = [EVIDENCE_MARK]
    for doc_id, name, page, text in segments:
        lines.append(f"--- [{doc_id[:8]} P{page}] {name} ---")
        lines.append(text)
    return lines


ANSWER_SCHEMA = ('{{"answer": "中文回答（结论+关键点延展）", '
                 '"citations": [{{"doc": "文档ID", "page": "页码", '
                 '"snippet": "该页原文逐字摘录（<=80字，禁止改写）"}}]}}')

# 指令：HINT 段不是证据；事实只来自 EVIDENCE 段 + snippet 逐字；不足则拒答。
# 注意：HINT 指令必须排在 EVIDENCE 指令之前（test_33 顺序断言）。
_INSTRUCTION = (
    "你是知识库问答助手。回答必须严格基于证据，禁止编造。\n"
    "规则：\n"
    "1. [HINT tier=internal] 段只是背景提示，**不是证据**，不得作为事实来源。\n"
    "2. 事实只能来自 [EVIDENCE tier=primary] 段，且引文 snippet 必须逐字摘录"
    "原文（<=80字，禁止改写、禁止拼接）。\n"
    "3. 若证据不足或问题超出证据范围，直接拒答：answer 说明无法回答，"
    "citations 留空数组。\n"
    "4. 只输出一个 JSON 对象，不要其他文字：\n"
    + ANSWER_SCHEMA + "\n\n"
)


def build_prompt(question, hint_lines, evidence_lines):
    """组装完整 prompt：指令 + HINT 段 + EVIDENCE 段 + 问题。"""
    parts = [_INSTRUCTION]
    parts.append("\n".join(hint_lines))
    parts.append("\n".join(evidence_lines))
    parts.append(f"\n问题：{question}")
    return "\n\n".join(parts)


def parse_answer(text):
    """LLM 输出 -> dict。缺 snippet 留空串；无 answer 键 -> None。

    返回 {"answer": str, "citations": [{"doc","page","snippet"}]} 或 None。
    """
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict) or not data.get("answer"):
        return None
    cites = []
    for c in data.get("citations") or []:
        if not isinstance(c, dict):
            continue
        cites.append({
            "doc": str(c.get("doc", "")),
            "page": str(c.get("page", "")),
            "snippet": str(c.get("snippet", "") or ""),
        })
    return {"answer": str(data["answer"]), "citations": cites}
