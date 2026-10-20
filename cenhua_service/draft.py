"""cenhua_service.draft — `cenhua draft` 主题创作（M4a 任务 7-10，roadmap §7.4）。

五步流程（§7.4）：主题拆解 -> 召回（§6.3，默认仅 primary）-> LLM 生成
Markdown 草稿 -> 每段挂 `[doc P页] + snippet` 引文并穿透 -> 存档
`works/drafts/<主题>_V{N}_<日期>.md`（tier=derived-doc）。

复用清单（dev-plan §8.6，逐项实证核对过）：
  * 三闸之预算闸  -> digest.budget_check（longjob 预算，不另写一份）
  * 引文校验      -> query.verify_citations（内含 verify.verify_citation
                     (vault, doc, page, snippet) + tier.penetration 穿透）
  * 证据段/hint   -> query.evidence_for + prompt.hint_block（两段式，
                     HINT 不是证据、事实只来自 EVIDENCE）
  * 版本管理      -> 同 digest._next_version 口径（前缀换成 <主题>_V{N}_）
  * 回流改写 tier -> digest.ingest_back（只依赖 path/derived_from）
  * 长任务通道    -> core.channel_job（返回带 lines/cost 的 dataclass）

铁律落点：
  * 规则优先 / LLM 兜底：LLM 失败或无法解析 -> _rule_fallback（原文摘录，
    零编造、零 LLM 消费，并明示二/三节需 LLM）。
  * 派生隔离：草稿落盘即 tier=derived-doc（回流显式改写台账），
    默认不参与召回（query.find_hits 已按 tier 过滤）。
  * rid 幂等：rid = sha1(mode|topic|section|doc_ids)[:12]，成功落盘后写
    <vault>/meta/draft_rids.json；同 rid 且产物仍在 -> 短路不重复花钱。
  * 原子写：tmp + os.replace + fsync（works/drafts 与 rid 台账同规范）。

service 纪律：零 print / 零 exit（test_70）；参数解析下沉本模块，
CLI 只做 submit + 打印（test_71）。rc 语义与 digest/graph 对齐：
0 成功 / 1 生成失败或召回为空 / 2 参数错 / 3 网关未配置 / 4 预算闸拒绝。
"""
from __future__ import annotations

import difflib
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Tuple

import m_lib as L  # noqa: E402  (scripts/ 在 sys.path)

DRAFT_DIR = "drafts"                 # <vault>/works/drafts
RID_FILE = "draft_rids.json"         # <vault>/meta/draft_rids.json
RID_KEEP = 200                       # rid 台账保留条数（防无界增长）

MAX_DOCS = 3                         # 草稿默认召回文档数
MAX_BODY_CHARS = 900                 # 兜底模式每段正文上限

# 草稿文件内嵌元信息（回流/续写/diff 都从这里读，不另建索引）
_FRONT_RE = re.compile(r"^<!--\s*draft:\s*(.*?)\s*-->\s*$", re.M)
_DERIVED_RE = re.compile(r"^<!--\s*derived_from:\s*(.*?)\s*-->\s*$", re.M)
_MODE_RE = re.compile(r"^<!--\s*mode:\s*(.*?)\s*-->\s*$", re.M)
_SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.*)$", re.M)
# 引文行：`> 引文 [doc前8位 P页] 逐字原文  · ✓|✗`（尾部标记不属于 snippet）
_CITE_RE = re.compile(r"^\s*>\s*引文\s+\[([0-9A-Za-z][\w.\-]{2,63})\s+P([^\]]*)\]"
                      r"\s*(.*?)\s*(?:·\s*[✓✗][^\n]*)?$", re.M)
_UNSAFE_RE = re.compile(r"[^\w.\-]+")


@dataclass
class DraftResult:
    """draft 结构化返回（渲染归 CLI；channel_job 需要 lines/cost）。"""
    lines: List[str] = field(default_factory=list)
    rc: int = 0
    cost: dict = field(default_factory=dict)
    topic: str = ""
    mode: str = ""                   # llm | rules
    path: str = ""                   # 已生成草稿路径（未生成则空）
    version: int = 0
    rid: str = ""
    sections: List[dict] = field(default_factory=list)
    citations: List[dict] = field(default_factory=list)
    derived_from: List[str] = field(default_factory=list)
    schema_version: int = 1


# ------------------------------------------------------ 目录与命名 ----


def drafts_dir(vault) -> str:
    """草稿目录（works/ 是全新目录，须自行创建）。"""
    return os.path.join(vault.works, DRAFT_DIR)


def slug(topic: str) -> str:
    """主题 -> 文件名安全片段（保留 CJK/字母数字，其余折叠为 _）。"""
    s = _UNSAFE_RE.sub("_", (topic or "").strip()).strip("._-")
    return (s[:40] or "主题")


def list_drafts(vault, topic: str = "") -> List[dict]:
    """列出草稿（topic 为空=全部）。按 (主题, 版本) 排序，同主题版本升序。"""
    ddir = drafts_dir(vault)
    out: List[dict] = []
    if not os.path.isdir(ddir):
        return out
    for fn in sorted(os.listdir(ddir)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(ddir, fn)
        m = re.match(r"^(.*)_V(\d+)_(\d{4}-\d{2}-\d{2})\.md$", fn)
        if not m:
            continue
        meta = _parse_front(_read(path))
        name = m.group(1)
        if topic and name != slug(topic):
            continue
        out.append({"file": fn, "path": path, "slug": name,
                    "topic": meta.get("topic") or name,
                    "version": int(m.group(2)), "date": m.group(3),
                    "mtime": os.path.getmtime(path),
                    "rid": meta.get("rid", ""),
                    "mode": meta.get("mode", "")})
    out.sort(key=lambda r: (r["slug"], r["version"]))
    return out


def _versions(vault, topic: str) -> List[dict]:
    return [r for r in list_drafts(vault, topic=topic)]


def next_version(vault, topic: str) -> int:
    """同主题既有 V{N} 取 max+1（AGENTS.md §1 命名集中一处生成）。"""
    vs = [r["version"] for r in _versions(vault, topic)]
    return (max(vs) + 1) if vs else 1


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _atomic_write(path: str, text: str) -> None:
    """tmp + os.replace + fsync（AGENTS.md §1 原子写纪律）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _parse_front(text: str) -> dict:
    """解析草稿头 `<!-- draft: k=v ... -->`（外加 derived_from/mode）。"""
    meta: dict = {}
    m = _FRONT_RE.search(text or "")
    if m:
        for pair in m.group(1).split():
            if "=" in pair:
                k, v = pair.split("=", 1)
                meta[k] = v
    d = _DERIVED_RE.search(text or "")
    if d:
        meta["derived_from"] = [x for x in d.group(1).split(",") if x]
    mo = _MODE_RE.search(text or "")
    if mo:
        meta["mode"] = mo.group(1)
    return meta


def split_sections(text: str) -> List[dict]:
    """草稿正文 -> [{"no","title","body"}]（按 `## N. 标题` 切分）。"""
    hits = list(_SECTION_RE.finditer(text or ""))
    out = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        out.append({"no": int(m.group(1)), "title": m.group(2).strip(),
                    "body": text[m.end():end].strip()})
    return out


# ------------------------------------------------------------- rid ----


def _rid_path(vault) -> str:
    return os.path.join(vault.meta, RID_FILE)


def make_rid(mode, topic, section, doc_ids) -> str:
    """幂等键：同一 (mode,主题,段号,召回集) 生成同一 rid。

    召回集变化（新摄取/精化）-> rid 变化 -> 允许重新生成。
    """
    import hashlib
    key = "|".join([mode, topic, str(section or ""),
                    ",".join(sorted(doc_ids))])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _load_rids(vault) -> dict:
    return L.read_json(_rid_path(vault), {}) or {}


def rid_seen(vault, rid: str) -> str:
    """已存在且产物仍在的 rid -> 返回其 path；否则 ""（需要重跑）。"""
    if not rid:
        return ""
    rec = _load_rids(vault).get(rid) or {}
    path = rec.get("path", "")
    return path if path and os.path.isfile(path) else ""


def rid_record(vault, rid: str, path: str, topic: str) -> None:
    """登记 rid（tmp+os.replace 原子写，保留最近 RID_KEEP 条）。永不抛。"""
    try:
        led = _load_rids(vault)
        led[rid] = {"path": path, "topic": topic,
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if len(led) > RID_KEEP:
            for k in sorted(led, key=lambda k: str(led[k].get("ts", "")))[:
                    len(led) - RID_KEEP]:
                led.pop(k, None)
        _atomic_write(_rid_path(vault),
                      json.dumps(led, ensure_ascii=False, indent=2,
                                 sort_keys=True))
    except Exception:               # rid 台账是护栏，不许拖垮主流程
        pass


# --------------------------------------------------------- 召回与生成 ----


def recall(vault, topic: str, top: int = MAX_DOCS) -> List[str]:
    """主题 -> 召回文档（§6.3 融合排序），**仅保留 primary**。

    派生/ internal 层默认不召回（草稿的引文必须能落到 primary 原文）。
    """
    from cenhua_service import query as Q
    from cenhua_service import tier as T

    terms = Q.terms_from_question(topic)
    fused = Q.fuse(Q.find_hits(vault, terms),
                   Q.semantic_hits(vault, topic, top=top * 2))
    out: List[str] = []
    for a in fused:
        if T.evidence_eligible(vault, a["doc"]) and a["doc"] not in out:
            out.append(a["doc"])
        if len(out) >= top:
            break
    return out


_SCHEMA = ('{"sections": [{"title": "小节标题", "body": "中文正文（结论+关键'
           '点），行内标注 [doc前8位 P页]", "citations": [{"doc": "文档ID",'
           ' "page": "页码", "snippet": "该页原文逐字摘录（<=80字，禁止改写）'
           '}]}]}')

_INSTRUCTION = (
    "你是知识库主题创作助手，产出一份可追溯的 Markdown 草稿。\n"
    "规则：\n"
    "1. [HINT tier=internal] 段只是背景提示，**不是证据**，不得作为事实来源。\n"
    "2. 事实只能来自 [EVIDENCE tier=primary] 段；每个小节至少 1 条引文，"
    "snippet 必须逐字摘录原文（<=80字，禁止改写、禁止拼接）。\n"
    "3. 证据不足的小节直接写明证据不足，citations 留空数组——禁止编造。\n"
    "4. 输出 2-5 个小节，围绕主题拆解（背景/现状/风险/结论一类结构自选）。\n"
    "5. 只输出一个 JSON 对象，不要其他文字：\n" + _SCHEMA + "\n\n"
)


def build_prompt(vault, topic, doc_ids, segs, hint_lines) -> str:
    """组装草稿 prompt：指令 + HINT 段 + EVIDENCE 段 + 主题。"""
    from cenhua_service import prompt as P

    parts = [_INSTRUCTION, "\n".join(hint_lines),
             "\n".join(P.evidence_block(segs)), f"\n主题：{topic}"]
    return "\n\n".join(parts)


def parse_draft(text: str):
    """LLM 输出 -> {"sections": [...]}；解析失败/无 sections -> None。"""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("sections")
    if not isinstance(raw, list) or not raw:
        return None
    sections = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        cites = []
        for c in item.get("citations") or []:
            if not isinstance(c, dict):
                continue
            cites.append({"doc": str(c.get("doc", "")),
                          "page": str(c.get("page", "")),
                          "snippet": str(c.get("snippet", "") or "")})
        sections.append({"title": str(item["title"]),
                         "body": str(item.get("body", "")).strip(),
                         "citations": cites})
    return {"sections": sections} if sections else None


def _all_citations(data) -> List[dict]:
    if not data:
        return []
    out = []
    for s in data.get("sections", []):
        out.extend(s.get("citations", []))
    return out


def resolve_ids(vault, citations) -> List[dict]:
    """LLM 给的 doc 可能是前 8 位（正文行内标注口径），补全为完整 doc_id。

    只在唯一前缀命中时替换；歧义/未命中原样保留（让校验计失败，不猜）。
    """
    ids = list(L.store_docs(vault).keys())
    out = []
    for c in citations:
        d = c.get("doc", "")
        if d and d not in ids:
            hit = [x for x in ids if x.startswith(d)]
            if len(hit) == 1:
                c = dict(c, doc=hit[0])
        out.append(c)
    return out


def rule_fallback(vault, doc_ids, topic: str = "") -> dict:
    """规则兜底（铁律）：证据段原文摘录成小节，零 LLM 消费、零编造。

    明示"需 LLM"：分析性小节不由规则伪造（digest 同口径）。
    """
    from cenhua_service import query as Q

    docs = L.store_docs(vault)
    segs = Q.evidence_for(vault, doc_ids)
    sections = [{"title": "主题拆解（需 LLM）",
                 "body": "证据摘录模式未调用网关，无法给出分析性拆解。"
                         "配置 PI_BASE/PI_KEY 后重跑本命令可得完整草稿。",
                 "citations": []}]
    for did in doc_ids:
        name = docs.get(did, {}).get("name", did)
        mine = [s for s in segs if s[0] == did]
        body = "\n".join(t.strip()[:MAX_BODY_CHARS] for _d, _n, _p, t in mine[:2])
        # 引文行协议前提是单行：snippet 内部换行压成空格（verify 归一化去空白，安全）
        cites = [{"doc": did, "page": mine[0][2],
                  "snippet": " ".join(mine[0][3].split())[:80]}] if mine else []
        sections.append({"title": f"{name}（原文摘录）",
                         "body": body or "（无文本层）",
                         "citations": cites})
    return {"sections": sections}


def _extend_prompt(topic, title, prior, segs, hint_lines) -> str:
    """续写 prompt：基于既有小节扩写（沿用同一套证据纪律）。"""
    from cenhua_service import prompt as P

    inst = ("你是知识库主题创作助手。请在既有小节基础上**扩写**，"
            "保留原有事实，补充证据与细节。\n"
            "1. [HINT tier=internal] 段不是证据。\n"
            "2. 事实只来自 [EVIDENCE tier=primary] 段；snippet 逐字摘录"
            "（<=80字，禁止改写）；至少给出 3 个句子与 1 条新引文。\n"
            "3. 只输出一个 JSON 对象：\n" + _SCHEMA + "\n\n")
    return "\n\n".join([inst, "\n".join(hint_lines),
                        "\n".join(P.evidence_block(segs)),
                        f"主题：{topic}\n待扩写小节标题：{title}\n"
                        f"既有正文：\n{prior[:1200]}"])


def _rewrite_prompt(topic, title, prior, segs, hint_lines) -> str:
    """改写 prompt：修正引文/措辞，不得新增未取证事实。"""
    from cenhua_service import prompt as P

    inst = ("你是知识库主题创作助手。请**改写**下列小节：措辞更清晰、"
            "结论与证据严格对齐，删除未取证的断言。\n"
            "1. [HINT tier=internal] 段不是证据。\n"
            "2. 事实只来自 [EVIDENCE tier=primary] 段；snippet 逐字摘录"
            "（<=80字，禁止改写）。\n"
            "3. 只输出一个 JSON 对象：\n" + _SCHEMA + "\n\n")
    return "\n\n".join([inst, "\n".join(hint_lines),
                        "\n".join(P.evidence_block(segs)),
                        f"主题：{topic}\n待改写小节标题：{title}\n"
                        f"原正文：\n{prior[:1200]}"])


# --------------------------------------------------------- 文章组装 ----


def assemble(vault, topic, version, sections, cites, mode, doc_ids,
             rid) -> List[str]:
    """渲染草稿（头部含 tier 声明与 rid，尾部含 derived_from/mode）。"""
    docs = L.store_docs(vault)
    ok_map = {}
    for c in cites:
        key = (str(c.get("doc", "")), str(c.get("page", "")),
               str(c.get("snippet", ""))[:80])
        ok_map.setdefault(key, c)
    lines = ["# %s（V%d · %s）" % (topic, version,
                                   time.strftime("%Y-%m-%d")), "",
             "> ⚠ tier=derived-doc：本文基于以下 primary 文档派生，"
             "默认不参与召回；引文已按 `--verify` 口径校验。", "",
             "<!-- draft: topic=%s version=%d rid=%s -->" % (topic, version,
                                                             rid), ""]
    for i, s in enumerate(sections, 1):
        lines.append("## %d. %s" % (i, s.get("title", "")))
        lines.append("")
        body = (s.get("body") or "").strip()
        lines.append(body if body else "（本节无正文）")
        for c in s.get("citations", []):
            key = (str(c.get("doc", "")), str(c.get("page", "")),
                   str(c.get("snippet", ""))[:80])
            res = ok_map.get(key, {})
            mark = "✓" if res.get("ok") else "✗"
            lines.append("> 引文 [%s P%s] %s  · %s"
                         % (c["doc"][:8], c["page"], c["snippet"][:80], mark))
        lines.append("")
    lines += ["## 参考文档", ""]
    for d in doc_ids:
        cs = [c for c in cites if c["doc"] == d]
        okn = sum(1 for c in cs if c.get("ok"))
        lines.append("- %s（doc=%s · 引文校验 %d/%d ✓）"
                     % (docs.get(d, {}).get("name", d), d[:12], okn, len(cs)))
    if mode != "llm":
        lines += ["", "~ 本文为规则兜底产物（零 LLM 消费）：分析性小节需配置"
                      "网关后重跑。"]
    lines += ["", "---", "",
              "<!-- derived_from: %s -->" % ",".join(doc_ids),
              "<!-- mode: %s -->" % mode, ""]
    return lines


# ------------------------------------------------------------ 主流程 ----


def _gate(vault, est, rest_kw, lines, topic):
    """三闸：① dry-run ② longjob 预算 ③ --force/--max-cost 放行 + 网关可用性。

    返回 None 表示放行；否则返回 DraftResult（rc 0/3/4）。
    """
    from cenhua_service import digest as D
    import m_lib as _L

    lines.append("[cost] estimate     : %.4f %s%s"
                 % (est.get("est_cost", 0.0), est.get("currency", "CNY"),
                    "" if est.get("priced")
                    else "  (%s)" % est.get("note", "")))
    if rest_kw.get("dry_run"):
        lines.append("[draft] dry-run     : 未调用网关（去掉 --dry-run 即执行）")
        return DraftResult(lines=lines, rc=0, cost=est, topic=topic)
    if not _L.chat_ready(_L.build_env(vault)):
        lines.append("[draft] gateway     : 未配置 PI_BASE/PI_KEY，"
                     "无法生成草稿（--dry-run 可看估价）")
        return DraftResult(lines=lines, rc=3, cost=est, topic=topic)
    ok, msg = D.budget_check(vault, est, force=rest_kw.get("force", False),
                             max_cost=rest_kw.get("max_cost"))
    lines.append("[draft] budget       : %s" % msg)
    if not ok:
        return DraftResult(lines=["[draft] REFUSED — " + msg] + lines,
                           rc=4, cost=est, topic=topic)
    return None


def draft_flow(vault, topic="", mode="new", section=None, version=None,
               top=MAX_DOCS, dry_run=False, force=False, max_cost=None,
               rid="", runtime=None):
    """`cenhua draft` 主编排（供 channel_job 调用；返回 DraftResult）。

    mode：new（新草稿）/ extend（扩写第 N 段）/ rewrite（改写第 N 段）。
    rc：0 成功 / 1 召回为空或生成失败 / 2 参数错 / 3 网关未配置 / 4 预算拒绝。
    """
    from cenhua_service import cost as CC
    from cenhua_service import prompt as P
    from cenhua_service import query as Q
    from cenhua_service import refine as R

    lines: List[str] = []
    topic = (topic or "").strip()
    if not topic:
        return DraftResult(lines=[
            "usage: cenhua draft \"主题\" [--dry-run] [--force] "
            "[--max-cost X] [--top N]"], rc=2)
    if mode not in ("new", "extend", "rewrite"):
        return DraftResult(lines=["draft: 未知 mode '%s'" % mode], rc=2)
    gate_kw = {"dry_run": dry_run, "force": force, "max_cost": max_cost}

    # ---- 召回（new）或定位既有版本（extend/rewrite） ----
    prior_sections: List[dict] = []
    if mode == "new":
        doc_ids = recall(vault, topic, top=top if top else MAX_DOCS)
        if not doc_ids:
            lines.append("= 召回为空（find+seek 均无 primary 命中）——"
                         "先 `cenhua add` 补语料，或换措辞")
            return DraftResult(lines=lines, rc=1, topic=topic)
        version = next_version(vault, topic)
    else:
        try:
            section = int(section)
        except (TypeError, ValueError):
            return DraftResult(lines=[
                "usage: cenhua draft \"%s\" --%s <段号>" % (topic, mode)],
                rc=2)
        if section < 1:
            return DraftResult(lines=["draft: 段号需 >= 1"], rc=2,
                               topic=topic)
        cands = _versions(vault, topic)
        if not cands:
            lines.append("draft: 未找到主题「%s」的既有草稿"
                         "（`cenhua draft --list` 查看）" % topic)
            return DraftResult(lines=lines, rc=1, topic=topic)
        want = 0
        try:
            want = int(version) if version else 0
        except (TypeError, ValueError):
            want = 0
        by_v = {r["version"]: r for r in cands}
        pick = by_v.get(want) if want else cands[-1]
        if not pick:
            avail = ",".join("V%d" % v for v in sorted(by_v))
            lines.append("draft: 版本 V%s 不存在（现有 %s）" % (version, avail))
            return DraftResult(lines=lines, rc=2, topic=topic)
        content = _read(pick["path"])
        prior_meta = _parse_front(content)
        prior_sections = split_sections(content)
        if section > len(prior_sections):
            lines.append("draft: 段号 %d 超出范围（共 %d 段）"
                         % (section, len(prior_sections)))
            return DraftResult(lines=lines, rc=2, topic=topic,
                               path=pick["path"])
        doc_ids = [d for d in (prior_meta.get("derived_from") or [])]
        if not doc_ids:
            doc_ids = recall(vault, topic, top=top or MAX_DOCS)
        if not doc_ids:
            lines.append("draft: 该草稿无 derived_from 且召回为空，无法取证")
            return DraftResult(lines=lines, rc=1, topic=topic)
        version = next_version(vault, topic)

    rid = rid or make_rid(mode, topic, section, doc_ids)
    hit = rid_seen(vault, rid)
    if hit and not dry_run:          # ④ rid 幂等：同键已成功，不再花钱
        lines.append("[draft] idempotent   : rid=%s 已产出 %s（未重复调用网关）"
                     % (rid, os.path.basename(hit)))
        return DraftResult(lines=lines, rc=0, topic=topic, path=hit,
                           version=0, rid=rid, mode="cached",
                           derived_from=list(doc_ids))

    # ---- 证据段 + hint（仅 primary） + prompt ----
    segs = Q.evidence_for(vault, doc_ids)
    hint_lines, hint_meta = P.hint_block(vault, doc_ids)
    if not segs:
        lines.append("[draft] evidence     : 无 primary 文本层，无法取证")
        return DraftResult(lines=lines, rc=1, topic=topic, rid=rid,
                           derived_from=list(doc_ids))
    if mode == "new":
        prompt_text = build_prompt(vault, topic, doc_ids, segs, hint_lines)
    else:
        cur = prior_sections[section - 1]
        maker = _extend_prompt if mode == "extend" else _rewrite_prompt
        prompt_text = maker(topic, cur["title"], cur["body"], segs, hint_lines)
    if runtime:
        runtime.progress(0.2)

    est = Q.estimate(vault, prompt_text, calls=1)
    blocked = _gate(vault, est, gate_kw, lines, topic)
    if blocked is not None:
        blocked.cost = est
        blocked.rid = rid
        blocked.derived_from = list(doc_ids)
        return blocked
    if runtime:
        runtime.progress(0.35)

    # ---- LLM 主路径 -> 规则兜底（铁律） ----
    raw, tin, tout, m = "", 0, 0, "llm"
    try:
        raw, tin, tout = R.call_llm(prompt_text, max_tokens=2600)
    except Exception as exc:
        vault.log("draft", ["llm_error=%s" % type(exc).__name__])
        lines.append("[draft] llm          : 调用失败（%s），转规则兜底"
                     % type(exc).__name__)
        m = "rules"
    data = parse_draft(raw) if m == "llm" else None
    if m == "llm" and data is None:
        vault.log("draft", ["parse_failed"])
        lines.append("[draft] parse        : LLM 输出无法解析，转规则兜底")
        m = "rules"
    if runtime:
        runtime.progress(0.7)

    if mode == "new":
        sections = (data or rule_fallback(vault, doc_ids, topic))["sections"]
        if m == "rules":
            est = Q.estimate(vault, prompt_text, calls=0)
    else:
        sections = [dict(s) for s in prior_sections]
        new_sec = (data or {}).get("sections", [])
        if new_sec:
            sections[section - 1] = {"no": sections[section - 1]["no"],
                                     "title": new_sec[0].get(
                                         "title",
                                         sections[section - 1]["title"]),
                                     "body": new_sec[0].get("body", ""),
                                     "citations": new_sec[0].get("citations",
                                                                 [])}
        else:                        # 兜底：保留原文并明示需 LLM
            sections[section - 1]["body"] = (
                sections[section - 1]["body"]
                + "\n\n> 未变更多：%s 需 LLM（网关未响应或输出不可解析）。"
                % ("扩写" if mode == "extend" else "改写"))

    cites = Q.verify_citations(vault, resolve_ids(
        vault, _all_citations({"sections": sections})))
    okn = sum(1 for c in cites if c.get("ok"))

    # ---- 落盘（版本化 + 原子写） ----
    article = assemble(vault, topic, version, sections, cites, m, doc_ids, rid)
    fname = "%s_V%d_%s.md" % (slug(topic), version,
                              time.strftime("%Y-%m-%d"))
    path = os.path.join(drafts_dir(vault), fname)
    try:
        _atomic_write(path, "\n".join(article))
    except OSError as exc:
        vault.log("draft", ["write_failed=%s" % exc])
        lines.append("[draft] write        : 落盘失败（%s）" % exc)
        return DraftResult(lines=lines, rc=1, cost=est, topic=topic, mode=m,
                           rid=rid, derived_from=list(doc_ids))
    rid_record(vault, rid, path, topic)

    ccny = CC.to_cny(est.get("est_cost") or 0.0,
                     est.get("currency", "CNY"))
    CC.ledger_append(vault, {"cmd": "draft", "doc": fname[:200], "mode": mode,
                             "rid": rid, "calls": est.get("calls", 0),
                             "tokens_in": tin or est.get("tokens_in", 0),
                             "tokens_out": tout or est.get("tokens_out", 0),
                             "est_cost": est.get("est_cost"),
                             "currency": est.get("currency"),
                             "priced": est.get("priced"),
                             "hint_docs": hint_meta["docs"]})
    if runtime:
        runtime.add_cost(calls=est.get("calls", 0), cost=ccny, currency="CNY")
        runtime.progress(1.0)

    lines.append("[draft] engine        : %s"
                 % ("LLM 生成" if m == "llm" else "规则兜底（零 LLM 消费）"))
    lines.append("[draft] evidence      : %d primary（hint %d 篇）"
                 % (len(doc_ids), hint_meta["docs"]))
    lines.append("[draft] citations     : %d/%d 校验通过" % (okn, len(cites)))
    lines.append("[draft] article       : works/%s/%s" % (DRAFT_DIR, fname))
    lines.append("[draft] rid           : %s" % rid)
    vault.log("draft", ["topic=%s mode=%s engine=%s docs=%d cites=%d ok=%d "
                        "rid=%s file=%s" % (topic, mode, m, len(doc_ids),
                                            len(cites), okn, rid, fname)])
    result = DraftResult(lines=lines, rc=0, cost=est, topic=topic, mode=m,
                         path=path, version=version, rid=rid,
                         sections=sections, citations=cites,
                         derived_from=list(doc_ids))
    # 回流闭环（M3a 任务 10 同模式）：works/drafts -> inbox 摄取 ->
    # 台账 tier=derived-doc；best-effort，失败只加提示行，绝不改 rc。
    back = ingest_back(vault, result)
    if back:
        lines.append("[draft] backflow      : inbox -> %s "
                     "(tier=derived-doc)" % back)
    else:
        lines.append("[draft] backflow      : skipped "
                     "(回流失败或摄取未产出 doc_id，不影响文章)")
    return result


# --------------------------------------------- 辅助能力（任务 8/9）----


def verify_draft(vault, target: str):
    """`draft --verify`：对草稿全文引文做与生成同一口径的校验。

    target 可为文件名 / V 版本号 / 主题（空=该主题最新版；无参=全部草稿）。
    复用 query.verify_citations（内含 verify.verify_citation(vault, doc,
    page, snippet) + tier.penetration 穿透），门禁与草稿同一实现。
    rc：0 全通过 / 1 有失败 / 2 未找到草稿。
    """
    from cenhua_service import query as Q

    all_rows = list_drafts(vault)
    if not all_rows:
        return {"rc": 1, "lines": ["draft --verify: works/drafts/ 下无草稿"]}
    rows, key = [], (target or "").strip()
    for r in all_rows:
        if (not key or r["file"] == key or r["path"] == key
                or key in (r["slug"], r["topic"])
                or r["file"] == "%s.md" % key
                or str(r["version"]) == key.lstrip("Vv")):
            rows.append(r)
    if not rows:
        return {"rc": 2, "lines": ["draft --verify: 未匹配到草稿 '%s'" % key]}
    picked, seen = [], set()
    for slug in sorted({r["slug"] for r in rows}):
        group = [r for r in rows if r["slug"] == slug]
        picked.append(group[-1] if key in ("", slug) else group[0])
    lines: List[str] = []
    total, passed, bad_file = 0, 0, 0
    for r in picked:
        cites = [{"doc": m.group(1), "page": m.group(2), "snippet": m.group(3)}
                 for m in _CITE_RE.finditer(_read(r["path"]))]
        head = "= %s（V%d · %d 条引文）" % (r["file"], r["version"], len(cites))
        if not cites:
            lines.append(head + " — 无引文行（规则兜底草稿），跳过")
            continue
        # 引文行里 doc 只有前 8 位（渲染口径），与生成路径同口径先补全再校验
        res = Q.verify_citations(vault, resolve_ids(vault, cites))
        okn = sum(1 for c in res if c.get("ok"))
        total += len(res)
        passed += okn
        mark = "✓" if okn == len(res) else "✗"
        lines.append("%s — %s %d/%d 通过" % (head, mark, okn, len(res)))
        if okn != len(res):
            bad_file += 1
        for c in res:
            if c.get("ok"):
                continue
            via = (" (%s)" % c["via"]) if c.get("via") not in ("direct",
                                                                "none") else ""
            lines.append("  ✗ [%s P%s] %s%s — %s"
                         % (c["doc"][:8], c["page"], c["snippet"][:60], via,
                            c.get("note", "")))
    lines.append("")
    lines.append("= 汇总：%d 条引文，%d 通过，%d 篇存在失败引文"
                 % (total, passed, bad_file))
    return {"rc": 0 if (passed == total and bad_file == 0) else 1,
            "lines": lines}


def diff_draft(vault, topic: str, a, b):
    """同主题两版本 unified diff。rc：0 有差异 / 1 无差异或版本不存在。"""
    rows = _versions(vault, topic)
    if not rows:
        return {"rc": 1, "lines": ["draft --diff: 主题「%s」无草稿" % topic]}
    want = {r["version"]: r for r in rows}
    va, vb = int(a), int(b)
    for v in (va, vb):
        if v not in want:
            avail = ",".join(str(x) for x in sorted(want))
            return {"rc": 1, "lines": ["draft --diff: 版本 V%d 不存在（现有 %s）"
                                       % (v, avail)]}
    da = _read(want[va]["path"]).splitlines()
    db = _read(want[vb]["path"]).splitlines()
    out = list(difflib.unified_diff(da, db, fromfile="V%d" % va,
                                    tofile="V%d" % vb, lineterm="", n=2))
    if not out:
        return {"rc": 1, "lines": ["draft --diff: V%d 与 V%d 内容一致"
                                   % (va, vb)]}
    same = sum(1 for x in out if x.startswith("+") and not
               x.startswith("+++"))
    return {"rc": 0, "lines": ["= %s V%d -> V%d（+%d 行）"
                               % (rows[0]["file"].rsplit("_V", 1)[0], va, vb,
                                  same)] + out}


def restore_draft(vault, topic: str, version: int):
    """把指定历史版本另存为新版本（不覆盖历史；tier 仍 derived-doc）。

    rc：0 成功 / 1 版本不存在 / 2 参数错。
    """
    if not topic or not version:
        return {"rc": 2, "lines": ["usage: cenhua draft \"主题\" "
                                  "--restore <版本号>"]}
    rows = _versions(vault, topic)
    src = next((r for r in rows if r["version"] == int(version)), None)
    if not src:
        avail = ",".join(str(r["version"]) for r in rows) or "无"
        return {"rc": 1, "lines": ["draft --restore: 版本 V%s 不存在（现有 %s）"
                                   % (version, avail)]}
    content = _read(src["path"])
    nv = next_version(vault, topic)
    new_name = "%s_V%d_%s.md" % (slug(topic), nv, time.strftime("%Y-%m-%d"))
    body = re.sub(r"<!--\s*draft:.*?-->",
                  "<!-- draft: topic=%s version=%d rid=%s -->"
                  % (topic, nv, make_rid("restore", topic, 0,
                                         _parse_front(content).get(
                                             "derived_from", []))),
                  content, count=1, flags=re.S)
    body = _MODE_RE.sub("<!-- mode: %s(restore V%s) -->" % (src["mode"],
                                                            version), body)
    path = os.path.join(drafts_dir(vault), new_name)
    try:
        _atomic_write(path, body)
    except OSError as exc:
        return {"rc": 1, "lines": ["draft --restore: 落盘失败（%s）" % exc]}
    return {"rc": 0, "lines": ["+ draft restored: V%s -> works/%s/%s"
                               % (version, DRAFT_DIR, new_name),
                               "~ 历史版本保留；新副本 tier=derived-doc"]}


def list_lines(vault, topic=""):
    """`draft --list` 渲染。rc：0 有 / 1 无。"""
    rows = list_drafts(vault, topic=topic)
    if not rows:
        return {"rc": 1, "lines": ["draft --list: works/%s/ 下无草稿"
                                   % DRAFT_DIR]}
    lines = ["= 草稿 %d 篇（works/%s/）：" % (len(rows), DRAFT_DIR)]
    cur = None
    for r in rows:
        if r["slug"] != cur:
            cur = r["slug"]
            lines.append("· %s" % r["topic"])
        lines.append("    V%-3d %s  %s  rid=%s"
                     % (r["version"], r["date"], r["mode"] or "-",
                        r["rid"] or "-"))
    return {"rc": 0, "lines": lines}


# ------------------------------------------------------------ CLI ----
USAGE = (
    "usage: cenhua draft \"主题\" [--top N] [--dry-run] [--force] "
    "[--max-cost X]\n"
    "       cenhua draft \"主题\" --extend <段号> | --rewrite <段号>\n"
    "       cenhua draft \"主题\" --restore <版本号>\n"
    "       cenhua draft --list [\"主题\"]        [OFFLINE]\n"
    "       cenhua draft --diff \"主题\" <Va> <Vb> [OFFLINE]\n"
    "       cenhua draft --verify [\"主题|文件名\"]  [OFFLINE]\n"
    "                                     产物 works/drafts/<主题>_V{N}_<日期>.md"
    "（tier=derived-doc）"
)

# 带值 flag -> kwargs 键（restore 的值是版本号，diff 的版本走位置参数）
_VALUES = (("--extend", "section", str), ("--rewrite", "section", str),
           ("--restore", "version", str), ("--max-cost", "max_cost", float),
           ("--top", "top", int), ("--rid", "rid", str))
_ACTIONS = ("--list", "--verify", "--diff", "--restore")


def parse_cli(rest):
    """draft CLI 参数 -> draft_flow kwargs / 辅助动作（service 层解析）。

    位置参数：主题；`--diff` 后额外两个位置参数是版本号（Va Vb）。
    """
    rest = list(rest or [])
    kw = {"mode": "new", "section": "", "version": "", "dry_run": False,
          "force": False, "max_cost": None, "top": MAX_DOCS, "rid": "",
          "action": "", "target": "", "diff": ("", "")}
    for flag in _ACTIONS:
        if flag in rest:
            kw["action"] = flag[2:]
    for flag in ("--extend", "--rewrite"):
        if flag in rest:
            kw["mode"] = flag[2:]
    kw["dry_run"] = "--dry-run" in rest
    kw["force"] = "--force" in rest
    for flag, key, cast in _VALUES:
        if flag in rest and rest.index(flag) + 1 < len(rest):
            try:
                kw[key] = cast(rest[rest.index(flag) + 1])
            except ValueError:
                pass
    consumed = {rest.index(f) + 1 for f, _k, _c in _VALUES if f in rest}
    pos = [a for i, a in enumerate(rest)
           if i not in consumed and not a.startswith("-")]
    if kw["action"] == "diff" and len(pos) >= 3:
        kw["target"], kw["diff"] = pos[0], (pos[1], pos[2])
    elif pos:
        kw["target"] = pos[0]
    if kw["mode"] in ("extend", "rewrite"):
        kw["action"] = ""
    return kw


def aux_flow(vault, kw):
    """辅助动作分派（list/verify/diff/restore）——全部离线，零 LLM。"""
    action = kw.get("action", "")
    if action == "list":
        return list_lines(vault, kw["target"])
    if action == "verify":
        return verify_draft(vault, kw["target"])
    if action == "diff":
        return diff_draft(vault, kw["target"], *kw["diff"])
    if action == "restore":
        return restore_draft(vault, kw["target"], kw["version"])
    return {"rc": 2, "lines": [USAGE]}


def gen_kwargs(rest):
    """生成类参数 -> draft_flow kwargs（CLI 侧 channel_job 直接 **展开）。"""
    kw = parse_cli(rest)
    return {"topic": kw["target"], "mode": kw["mode"],
            "section": kw["section"], "version": kw["version"],
            "top": kw["top"], "dry_run": kw["dry_run"], "force": kw["force"],
            "max_cost": kw["max_cost"], "rid": kw["rid"]}


def needs_channel(rest) -> bool:
    """是否需要走任务通道：辅助动作（list/verify/diff/restore）离线即时。"""
    return not parse_cli(rest)["action"]


def flow(vault, rest):
    """`cenhua draft ...` 总入口：辅助动作直接返回，生成走 draft_flow。"""
    kw = parse_cli(rest)
    if kw["action"]:
        return aux_flow(vault, kw)
    return draft_flow(vault, topic=kw["target"], mode=kw["mode"],
                      section=kw["section"], version=kw["version"],
                      top=kw["top"], dry_run=kw["dry_run"],
                      force=kw["force"], max_cost=kw["max_cost"],
                      rid=kw["rid"])


def ingest_back(vault, result):
    """草稿回流：照抄 digest 实现（只依赖 path + derived_from 两个字段）。"""
    from cenhua_service import digest as D
    return D.ingest_back(vault, result)
