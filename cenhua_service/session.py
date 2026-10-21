"""cenhua_service.session — M4c-14 多轮对话上下文继承（roadmap §6.6）。

`cenhua query --session <sid> "问题"`：同一 sid 的问答轮次落
`<vault>/meta/sessions/<sid>.json`，下一轮把先前轮次注入 prompt。

纪律：
  * 先前轮次含 LLM 生成文本 —— prompt 中明示 [PRIOR tier=context]
    **不是证据**，不得引用、不得作为事实来源（hint-not-evidence 同族）；
  * 答案/引文截断存储，至多 TURNS_MAX 轮（超限裁最旧）；
  * 原子写 tmp + os.replace + fsync；sid 白名单字符（防路径穿越）；
  * 任何读写异常静默降级（无上下文继续单轮），绝不拖垮 query。

service 纪律：不 print/exit（test_70）。
"""

import json
import os
import re

TURNS_MAX = 6        # 上下文最多保留轮数
ANSWER_CHARS = 300   # 每轮答案摘要截断
CITES_MAX = 3        # 每轮保留引文数

_SID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$")

SESSIONS_DIR = "sessions"


def _dir(vault):
    return os.path.join(vault.meta, SESSIONS_DIR)


def _path(vault, sid):
    """sid -> 路径。非法 sid -> None（防穿越）。"""
    if not sid or not _SID_RE.match(sid):
        return None
    return os.path.join(_dir(vault), f"{sid}.json")


def load(vault, sid):
    """读取会话。返回 {"turns": [...]}；不存在/非法/损坏 -> None。"""
    path = _path(vault, sid)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("turns"), list):
        return None
    return data


def _atomic_write(path, text):
    """tmp + os.replace + fsync（AGENTS.md §1 原子写纪律）。"""
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def record(vault, sid, question, answer, cites):
    """追加一轮。成功 True；非法 sid/写失败 False（永不抛）。"""
    path = _path(vault, sid)
    if not path:
        return False
    data = load(vault, sid) or {"sid": sid, "turns": []}
    data["turns"].append({
        "q": str(question)[:200],
        "a": str(answer or "")[:ANSWER_CHARS],
        "cites": [f"{c.get('doc', '')[:8]} P{c.get('page', '')}"
                  for c in (cites or [])[:CITES_MAX]],
    })
    data["turns"] = data["turns"][-TURNS_MAX:]
    try:
        _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=1))
        return True
    except OSError:
        return False


def history_block(vault, sid):
    """先前轮次 -> prompt 段。无会话/无轮次 -> []。

    明示 tier=context 非证据；LLM 若需事实仍须引用本轮 EVIDENCE。
    """
    data = load(vault, sid)
    if not data or not data.get("turns"):
        return []
    lines = ["[PRIOR tier=context]（先前对话，仅供理解指代与延续话题；"
             "**不是证据**，不得作为事实来源、不得在 citations 中引用）"]
    for i, t in enumerate(data["turns"], 1):
        line = f"{i}. 问：{t.get('q', '')}"
        if t.get("a"):
            line += f"\n   答：{t['a']}"
        if t.get("cites"):
            line += f"\n   引文：{'、'.join(t['cites'])}"
        lines.append(line)
    return lines


def tail_lines(vault, sid, saved):
    """CLI 展示行：已保存 N 轮 或 非法 sid 提示。"""
    if not _SID_RE.match(sid or ""):
        return ['[session] 非法 sid（限字母/数字/_/-，<=64 字符），本轮未存档']
    data = load(vault, sid)
    n = len((data or {}).get("turns", []))
    if saved:
        return [f"[session] {sid}：已保存 {n} 轮上下文（--session {sid} 续用）"]
    return [f"[session] {sid}：本轮未存档（无延展结果）"]
