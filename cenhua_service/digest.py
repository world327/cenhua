"""digest.py — `cenhua digest` 定期洞察（M3a 任务 6，契约 §3.5）。

窗口解析 + 文档圈选 + 估价展示 + watch 提示计数（m3a-5）；
四节文章生成 compose()（m3a-6）：LLM 主路径 + 规则兜底（铁律）、
引文全量 verify_citations 校验、落盘 works/digests/。
all-or-nothing 三闸（任务 8）、任务通道接入（任务 9）、
回流闭环（任务 10）由后续任务补齐。零 print/exit。

触发窗口（roadmap §7.3，F10）：--weekly(7d) / --monthly(30d) /
--quarterly(91d) 互斥；--since YYYY-MM-DD 手动指定。四者必选其一。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import List, Tuple

import m_lib as L  # noqa: E402  (scripts/ 在 sys.path)

_WINDOWS = {"weekly": 7, "monthly": 30, "quarterly": 91}

# F10 watch 提示：默认累计 20 篇提示一次（env > vault.yaml > 默认）
HINT_DOCS_ENV = "CENHUA_DIGEST_HINT_DOCS"
HINT_DOCS_KEY = "digest_hint_docs"
HINT_DOCS_DEFAULT = 20


@dataclass
class DigestResult:
    """digest 结构化返回（渲染归 CLI）。"""
    lines: List[str] = field(default_factory=list)
    rc: int = 0
    cost: dict = field(default_factory=dict)
    docs: List[Tuple[str, str]] = field(default_factory=list)
    label: str = ""
    mode: str = ""                   # llm | rules-fallback
    path: str = ""                   # 已生成文章路径（未生成则空）
    derived_from: List[str] = field(default_factory=list)
    citations: List[dict] = field(default_factory=list)
    schema_version: int = 1


def parse_window(weekly=False, monthly=False, quarterly=False, since=None):
    """触发参数 -> (start_date, label)。返回 (None, 错误文案) 表示参数错。"""
    chosen = [k for k, on in (("weekly", weekly), ("monthly", monthly),
                              ("quarterly", quarterly)) if on]
    if since is not None:
        if chosen:
            return None, "--since 与 --weekly/--monthly/--quarterly 互斥"
        try:
            time.strptime(since, "%Y-%m-%d")
        except ValueError:
            return None, "--since 需要 YYYY-MM-DD（例：2026-09-01）"
        return since, "since " + since
    if len(chosen) != 1:
        return None, ("usage: cenhua digest --weekly | --monthly | "
                      "--quarterly | --since YYYY-MM-DD [--dry-run]")
    name = chosen[0]
    start = time.strftime("%Y-%m-%d",
                          time.localtime(time.time() - _WINDOWS[name] * 86400))
    return start, name


def docs_in_window(vault, start_date) -> List[Tuple[str, str]]:
    """摄取时间 >= start_date 的文档（manifest ts 前 10 位日期比较）。"""
    docs = L.store_docs(vault)
    out = [(d, info.get("name", d)) for d, info in sorted(docs.items())
           if str(info.get("ts", ""))[:10] >= start_date]
    return out


def last_digest_date(vault) -> str:
    """最近一篇已产出洞察的日期（works/digests/*.md 的 mtime）；无则 ""。"""
    ddir = os.path.join(vault.works, "digests")
    if not os.path.isdir(ddir):
        return ""
    ts = [os.path.getmtime(os.path.join(ddir, f)) for f in os.listdir(ddir)
          if f.endswith(".md")]
    return time.strftime("%Y-%m-%d", time.localtime(max(ts))) if ts else ""


def docs_since_last_digest(vault) -> int:
    """自上次洞察以来的摄取量（watch 提示 F10 的计数口径）。"""
    last = last_digest_date(vault)
    if not last:
        return len(L.store_docs(vault))
    return len([1 for _info in L.store_docs(vault).values()
                if str(_info.get("ts", ""))[:10] >= last])


def hint_threshold(vault) -> int:
    """提示阈值 N：env > vault.yaml > 默认 20（配置驱动，禁硬编码）。"""
    try:
        return int(vault.setting(HINT_DOCS_KEY, HINT_DOCS_ENV,
                                 str(HINT_DOCS_DEFAULT)))
    except (ValueError, AttributeError):
        return HINT_DOCS_DEFAULT


def parse_cli(rest):
    """解析 digest CLI 参数 -> digest_flow kwargs（service 层，CLI 保持薄）。"""
    kw = {"weekly": "--weekly" in rest, "monthly": "--monthly" in rest,
          "quarterly": "--quarterly" in rest, "dry_run": "--dry-run" in rest,
          "force": "--force" in rest,
          "since": rest[rest.index("--since") + 1] if "--since" in rest else None,
          "max_cost": None}
    if "--max-cost" in rest:
        kw["max_cost"] = float(rest[rest.index("--max-cost") + 1])
    return kw


def budget_check(vault, est, force=False, max_cost=None):
    """三闸之 ②③（longjob 预算）。返回 (ok, message)。dry-run 不调此闸。

    限额 = --max-cost 覆盖 > CENHUA_LONGJOB_MAX_COST_CNY >
    vault.yaml longjob_max_cost > 5.0；模型报价非 CNY 时按保守汇率上限
    折算再比（闸只收紧不放松）。
    """
    from cenhua_service import cost as CC
    limit = CC.longjob_max_cost_cny(vault)
    if max_cost is not None:
        limit = float(max_cost)
    cost = est.get("est_cost") or 0.0
    cur = est.get("currency", "CNY")
    cost_cny = CC.to_cny(cost, cur)
    shown = "%.4f %s" % (cost, cur) + (
        " ≈¥%.4f" % cost_cny if cur != "CNY" else "")
    if cost_cny <= limit:
        return True, "within longjob budget (%s <= ¥%g)" % (shown, limit)
    if force:
        return True, ("estimate %s exceeds longjob budget ¥%g; "
                      "--force overrides" % (shown, limit))
    return False, ("estimate %s exceeds longjob budget ¥%g (%s); "
                   "raise the budget or pass --force / --max-cost"
                   % (shown, limit, CC.LONGJOB_COST_ENV))


def digest_flow(vault, weekly=False, monthly=False, quarterly=False,
                since=None, dry_run=False, force=False,
                max_cost=None) -> DigestResult:
    """digest 主编排（骨架版）：窗口 -> 圈选 -> 估价 -> 引擎占位。

    rc 语义：0 成功；2 参数错；3 网关未配置；4 预算闸拒绝。
    """
    from cenhua_service import cost as CC

    start, label = parse_window(weekly=weekly, monthly=monthly,
                                quarterly=quarterly, since=since)
    if start is None:
        return DigestResult(rc=2, lines=[label])
    targets = docs_in_window(vault, start)
    lines = ["[digest] window     : %s (since %s)" % (label, start),
             "[digest] documents  : %d" % len(targets)]
    for _d, name in targets[:20]:
        lines.append("             - %s" % name)
    if len(targets) > 20:
        lines.append("             ... %d more" % (len(targets) - 20))
    if not targets:
        lines.append("[digest] note       : 窗口内无新摄取，无需生成洞察")
        return DigestResult(lines=lines, rc=0, docs=targets)

    env = L.build_env(vault)
    texts = []
    for d, _ in targets:
        p = os.path.join(vault.textdir, "%s.txt" % d)
        try:
            texts.append(open(p, encoding="utf-8", errors="ignore").read())
        except OSError:
            texts.append("x" * 6400)       # 无文本层按 4K tokens 保守估
    model = env.get("PI_MODEL", "openai/gpt-4o-mini")
    est = CC.estimate_docs(model, texts)
    est["calls"] = 1                       # 洞察=1 次全库综合调用
    # ① dry-run 估价 + longjob 预算展示（digest 走长任务闸，不展示 MAX_COST）
    lines.append("[cost] estimate   : " + CC.format_cost(
        [(est["est_cost"], est["currency"])])
        + ("" if est.get("priced") else
           "  (%s)" % est.get("note", "")))
    lines.append("[digest] budget      : ¥%g longjob (%s; env > vault.yaml "
                 "longjob_max_cost > 5.0)"
                 % (float(max_cost) if max_cost is not None
                    else CC.longjob_max_cost_cny(vault),
                    CC.LONGJOB_COST_ENV))

    if dry_run:
        ok0, msg0 = budget_check(vault, est, force=force, max_cost=max_cost)
        lines.append("[digest] gate        : %s — %s"
                     % ("PASS" if ok0 else "WOULD-REFUSE", msg0))
        lines.append("")
        lines.append("(dry run \u2014 nothing was sent)")
        return DigestResult(lines=lines, rc=0, cost=est, docs=targets)
    if not L.chat_ready(env):
        lines.append("LLM gateway not configured: export PI_BASE and PI_KEY")
        return DigestResult(lines=lines, rc=3, cost=est, docs=targets,
                            label=label)
    # 预算闸：longjob all-or-nothing（豁免 MAX_COST/MAX_LLM_CALLS 中途执法）
    ok, msg = budget_check(vault, est, force=force, max_cost=max_cost)
    lines.append("[digest] gate        : " + msg)
    if not ok:
        lines.append("")
        lines.append("[digest] refused      : " + msg)
        return DigestResult(lines=lines, rc=4, cost=est, docs=targets,
                            label=label)
    # 引擎体（任务通道 = M3a 任务 9；回流台账 = M3a 任务 10 接入）
    sub, _cl = compose(vault, [d for d, _ in targets], label=label,
                       start=start, force=force, max_cost=max_cost)
    lines.extend(sub.lines)
    merged = DigestResult(
        lines=lines, rc=sub.rc, cost=sub.cost or est, docs=targets,
        label=label, mode=sub.mode, path=sub.path,
        derived_from=sub.derived_from, citations=sub.citations)
    # 回流闭环（M3a 任务 10）：文章复制进 inbox 走摄取，台账标 derived-doc；
    # best-effort，失败只追加提示行，绝不改变 digest 的 rc。
    if sub.rc == 0 and sub.path:
        doc_id = ingest_back(vault, sub)
        if doc_id:
            lines.append("[digest] backflow     : inbox -> %s "
                         "(tier=derived-doc)" % doc_id)
        else:
            lines.append("[digest] backflow     : skipped "
                         "(回流失败或摄取未产出 doc_id，不影响文章)")
    return merged


# ------------------------------------------------- 四节文章引擎（任务 7）----
_LABEL_CN = {"weekly": "周报", "monthly": "月报", "quarterly": "季报"}

# 四节 JSON schema（.format 用，故字面花括号双写）
_SCHEMA = (
    '{{"graph": {{"overview": "本期新增知识一句话概览", '
    '"entity_changes": [{{"entity": "实体名", "note": "出现于哪些文档/变化"}}]}}, '
    '"findings": {{"patterns": [{{"text": "模式结论", "citations": '
    '[{{"doc": "doc_id", "page": "页码", "snippet": "该页原文逐字摘录"}}]}}], '
    '"trends": [...同 patterns...], '
    '"contradictions": [{{"text": "矛盾描述", "citations": [...], '
    '"verdict": "如何消解或待查证"}}]}}, '
    '"open_questions": [{{"text": "待澄清问题（可转为下次摄取方向）", '
    '"citations": [...]}}], '
    '"notes": "可选备注"}}')

_INSTRUCTION = (
    "你是私有知识库的洞察分析师。基于下列证据撰写定期知识洞察。\n"
    "规则：\n"
    "1. [HINT tier=internal] 段只是背景提示，**不是证据**，不得作为事实来源。\n"
    "2. 事实只能来自 [EVIDENCE tier=primary] 段；每条发现/问题必须带 citations，"
    "snippet 必须逐字摘录证据段原文（<=80字，禁止改写、禁止拼接）。\n"
    "3. 证据不足时宁可少写：对应数组留空，禁止编造。\n"
    "4. 只输出一个 JSON 对象，不要其他文字：\n"
    + _SCHEMA + "\n\n")


def build_digest_prompt(vault, doc_ids, label, start, segs, hint_lines):
    """组装洞察 prompt：指令 + HINT 段 + EVIDENCE 段 + 任务描述。

    与 prompt.build_prompt 同构（HINT 段排在 EVIDENCE 段之前）。
    """
    from cenhua_service import prompt as P
    task = ("任务：为窗口「%s」（自 %s 起，共 %d 篇新文档）撰写定期知识洞察："
            "本期图谱、跨文档发现（模式/趋势/矛盾）、待澄清问题。"
            % (_LABEL_CN.get(label, label), start, len(doc_ids)))
    parts = [_INSTRUCTION,
             "\n".join(hint_lines or []),
             "\n".join(P.evidence_block(segs)),
             task]
    return "\n\n".join(parts)


def _parse_digest_json(text):
    """LLM 输出 -> dict（四节结构）；解析失败返回 None（走规则兜底）。"""
    import json as _json
    import re as _re
    m = _re.search(r"\{.*\}", text or "", _re.S)
    if not m:
        return None
    try:
        data = _json.loads(m.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(
        data.get("graph"), dict) else None


def _all_citations(data):
    """收集二/三节全部 citations（保持出现顺序）。"""
    out = []
    f = data.get("findings") or {}
    for group in ("patterns", "trends", "contradictions"):
        for item in f.get(group) or []:
            out += [c for c in (item.get("citations") or [])
                    if isinstance(c, dict)]
    for item in data.get("open_questions") or []:
        out += [c for c in (item.get("citations") or [])
                if isinstance(c, dict)]
    return out


def _cite_note(cit):
    """引文尾注：[doc[:8] P页] 「snippet」 ✓|✗（note）。"""
    mark = "\u2713" if cit.get("ok") else "\u2717"
    note = ("（%s）" % cit["note"]) if cit.get("note") else ""
    return "[%s P%s] \u300c%s\u300d %s%s" % (
        str(cit.get("doc", ""))[:8], cit.get("page", ""),
        str(cit.get("snippet", ""))[:80], mark, note)


def _rule_fallback(vault, doc_ids):
    """非 LLM 兜底（铁律）：一/四节规则生成；二/三节明示需 LLM 且零编造。

    返回 data dict（形态同 _SCHEMA）。
    """
    from cenhua_service import summaries as S
    ent = {}
    for d in doc_ids:
        text = "\n".join(t for _p, t in L.text_pages(vault, d))
        for _k, vals in S.extract_entities(text, per_type=8).items():
            for v in vals:
                ent[v] = ent.get(v, 0) + 1
    top = sorted(ent.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    graph = {"overview": "本期新摄取 %d 篇文档（规则兜底：未做 LLM 综合，"
                         "实体为正则粗提，未消歧）。" % len(doc_ids),
             "entity_changes": [{"entity": k,
                                 "note": "正则粗提，出现 %d 次" % n}
                                for k, n in top]}
    gap = {"text": "模式/趋势/矛盾等跨文档发现需 LLM 网关（PI_BASE/PI_KEY）"
                   "配置后重跑 cenhua digest 生成；本节规则兜底不做推断，"
                   "避免编造。",
           "citations": []}
    return {"graph": graph,
            "findings": {"patterns": [dict(gap)], "trends": [],
                         "contradictions": []},
            "open_questions": [{"text": "待 LLM 生成：建议保证窗口内文档均有"
                                        "文本层，并配置网关后重跑本命令。",
                                "citations": []}],
            "mode": "rules"}


def _weight_of(vault, doc_id):
    """引用清单排序权重：关联边数 + 正文信息量（字符数/4000）。"""
    try:
        from cenhua_service import relations as REL
        edges = len(REL.related(vault, doc_id))
    except Exception:
        edges = 0
    chars = sum(len(t) for _p, t in L.text_pages(vault, doc_id))
    return edges + chars / 4000.0


def _assemble_article(vault, doc_ids, label, start, data, cites, mode):
    """四节 markdown 组装。引文一律以尾注呈现（snippet + 校验标记），
    正文不注入行内标记，保证 snippet 逐字可核验。"""
    from cenhua_service import prompt as P
    docs = L.store_docs(vault)
    ok_map = {}
    for c in cites:
        ok_map.setdefault((str(c.get("doc", "")), str(c.get("page", ""))),
                          []).append(c)

    def cite_tail(item):
        cs = [c for c in (item.get("citations") or []) if isinstance(c, dict)]
        if not cs:
            return ["  " + P.UNVERIFIED + "（无引文，F2 计失败）"]
        out = []
        for c in cs:
            matched = ok_map.get((str(c.get("doc", "")),
                                  str(c.get("page", "")))) or []
            hit = next((m for m in matched
                        if str(m.get("snippet", ""))[:80]
                        == str(c.get("snippet", ""))[:80]), None)
            out.append("  " + _cite_note(hit if hit else {
                **c, "ok": False, "note": "未在校验集中（幻觉或改写）"}))
        return out

    title = "# CENHUA 知识洞察 · %s（%s，自 %s）" % (
        _LABEL_CN.get(label, label), label, start)
    lines = [title, "",
             "> \u26a0 tier=derived-doc：本文基于以下 primary 文档派生，"
             "默认不参与召回；证据请回溯第四节引用原文。", ""]
    g = data.get("graph") or {}
    lines += ["## 一、本期新增知识图谱", "", g.get("overview", "")]
    for e in (g.get("entity_changes") or [])[:15]:
        lines.append("- **%s** — %s" % (e.get("entity", ""),
                                        e.get("note", "")))
    f = data.get("findings") or {}
    lines += ["", "## 二、跨文档发现"]
    for head, key in (("模式", "patterns"), ("趋势", "trends"),
                      ("矛盾", "contradictions")):
        items = f.get(key) or []
        lines.append("")
        lines.append("### %s" % head)
        if not items:
            lines.append("- （证据不足或未启用 LLM，无发现）")
        for it in items:
            lines.append("- %s" % it.get("text", ""))
            if key == "contradictions" and it.get("verdict"):
                lines.append("  消解： %s" % it["verdict"])
            lines += cite_tail(it)
    lines += ["", "## 三、待澄清问题"]
    oq = data.get("open_questions") or []
    if not oq:
        lines.append("- （无待澄清问题）")
    for it in oq:
        lines.append("- %s" % it.get("text", ""))
        lines += cite_tail(it)
    lines += ["", "## 四、引用文档清单（按权重排序）", ""]
    ranked = sorted(doc_ids, key=lambda d: (-_weight_of(vault, d), d))
    for i, d in enumerate(ranked, 1):
        rec = docs.get(d, {})
        cs = [c for k, v in ok_map.items() if k[0] == d for c in v]
        okn = sum(1 for c in cs if c.get("ok"))
        lines.append("%d. %s（doc=%s · 引文校验 %d/%d ✓ · 权重 %.2f）"
                     % (i, rec.get("name", d), d[:12], okn, len(cs),
                        _weight_of(vault, d)))
    lines += ["", "---", "",
              "<!-- derived_from: %s -->" % ",".join(doc_ids),
              "<!-- mode: %s -->" % mode, ""]
    return lines


def _next_version(vault, label):
    """扫描 works/digests/ 同窗口既有 V{N}，返回 N+1。"""
    import re as _re
    ddir = os.path.join(vault.works, "digests")
    pat = _re.compile(r"^洞察_" + _re.escape(label) + r"_V(\d+)_.*\.md$")
    ns = []
    if os.path.isdir(ddir):
        for f in os.listdir(ddir):
            m = pat.match(f)
            if m:
                ns.append(int(m.group(1)))
    return (max(ns) + 1) if ns else 1


def compose(vault, doc_ids, label="weekly", runtime=None, start=None,
            force=False, max_cost=None):
    """四节文章生成（契约 §3.5）：LLM 主路径 + 规则兜底（铁律）。

    返回 (DigestResult, lines)。doc_ids 应已按窗口圈选；证据段只取
    primary（tier.evidence_eligible 过滤）。引文全量 verify_citations
    校验（含穿透）；文章落 works/digests/洞察_<label>_V{N}_<日期>.md。
    runtime 为任务通道 JobRuntime（可选，进度回报）。
    豁免中途执法 F1（本函数=单次原子调用）；rc：0 成功 / 1 生成失败 /
    3 网关不可用 / 4 预算闸拒绝。
    """
    from cenhua_service import cost as CC
    from cenhua_service import prompt as P
    from cenhua_service import query as Q
    from cenhua_service import refine as R
    from cenhua_service import tier as T

    lines: List[str] = []
    if runtime:
        runtime.progress(0.05)
    # 证据圈选：仅 primary 进证据段（三层 artifact 纪律）
    primary = [d for d in doc_ids if T.evidence_eligible(vault, d)]
    skipped = len(doc_ids) - len(primary)
    segs = Q.evidence_for(vault, primary)
    hint_lines, _meta = P.hint_block(vault, primary)
    if runtime:
        runtime.progress(0.15)
    prompt_text = build_digest_prompt(vault, primary, label,
                                      start or "", segs, hint_lines)
    est = Q.estimate(vault, prompt_text, calls=1)
    # 事后预算闸：同样按 longjob 预算（防 prompt 膨胀，且不被 MAX_COST 腰斩）
    ok, msg = budget_check(vault, est, force=force, max_cost=max_cost)
    if not ok:
        lines.append("[digest] refused      : " + msg)
        return (DigestResult(lines=lines, rc=4, cost=est,
                             docs=[(d, "") for d in doc_ids], label=label,
                             derived_from=list(primary)), lines)
    # LLM 主路径（失败 -> 规则兜底，铁律）
    raw, tin, tout, mode = "", 0, 0, "llm"
    try:
        raw, tin, tout = R.call_llm(prompt_text, max_tokens=2600)
    except Exception as exc:                       # 失败隔离，不拖垮调用方
        vault.log("digest", ["llm_error=%s" % type(exc).__name__])
        lines.append("[digest] llm        : 调用失败（%s），转规则兜底"
                     % type(exc).__name__)
        mode = "rules"
    data = _parse_digest_json(raw) if mode == "llm" else None
    if mode == "llm" and data is None:
        vault.log("digest", ["parse_failed"])
        lines.append("[digest] parse      : LLM 输出无法解析，转规则兜底")
        mode = "rules"
    if runtime:
        runtime.progress(0.7)
    if mode == "rules":
        data = _rule_fallback(vault, primary)
        est = Q.estimate(vault, prompt_text, calls=0)   # 兜底零 LLM 消费
    # 引文全量校验（F2 + 穿透）
    cites = Q.verify_citations(vault, _all_citations(data))
    okn = sum(1 for c in cites if c.get("ok"))
    # 组装 + 版本化落盘（AGENTS.md §1 命名：{主题}_V{N}_{日期}）
    article = _assemble_article(vault, primary, label, start or "", data,
                                cites, mode)
    ddir = os.path.join(vault.works, "digests")
    os.makedirs(ddir, exist_ok=True)
    fname = "洞察_%s_V%d_%s.md" % (
        label, _next_version(vault, label), time.strftime("%Y-%m-%d"))
    path = os.path.join(ddir, fname)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(article))
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        vault.log("digest", ["write_failed=%s" % exc])
        lines.append("[digest] write      : 落盘失败（%s）" % exc)
        return (DigestResult(lines=lines, rc=1, cost=est,
                             docs=[(d, "") for d in doc_ids], label=label,
                             mode=mode, derived_from=list(primary)), lines)
    # 记账（全量 ledger，T5）
    ccny = CC.to_cny(est.get("est_cost") or 0.0,
                     est.get("currency", "CNY"))
    CC.ledger_append(vault, {"cmd": "digest", "doc": fname[:200],
                             "calls": est.get("calls", 0),
                             "tokens_in": tin or est.get("tokens_in", 0),
                             "tokens_out": tout or est.get("tokens_out", 0),
                             "est_cost": est.get("est_cost"),
                             "currency": est.get("currency"),
                             "priced": est.get("priced")})
    if runtime:
        runtime.add_cost(calls=est.get("calls", 0), cost=ccny, currency="CNY")
        runtime.progress(1.0)
    lines.append("[digest] engine       : %s"
                 % ("LLM 综合" if mode == "llm" else "规则兜底（零 LLM 消费）"))
    if cites:
        lines.append("[digest] citations    : %d/%d 校验通过"
                     % (okn, len(cites)))
    else:
        lines.append("[digest] citations    : 0 条（兜底模式无引文，"
                     "二/三节明示需 LLM）")
    lines.append("[digest] article      : works/digests/%s" % fname)
    lines.append("[digest] evidence     : %d primary（衍生/internal 排除 %d）"
                 % (len(primary), skipped))
    vault.log("digest", ["label=%s mode=%s docs=%d cites=%d ok=%d file=%s"
                         % (label, mode, len(primary), len(cites), okn,
                            fname)])
    res = DigestResult(lines=lines, rc=0, cost=est,
                       docs=[(d, "") for d in doc_ids], label=label,
                       mode=mode, path=path, derived_from=list(primary),
                       citations=cites)
    return res, lines


# ------------------------------------------------- 回流闭环（任务 10）----


def ingest_back(vault, result):
    """把 digest 文章回流进 inbox 摄取，并改写台账 tier=derived-doc。

    流程：复制 result.path -> vault.inbox -> core.ingest（inbox 内文件成功后
    自动 stage 到 .processed，works/ 原件保留）-> 台账显式改写
    tier="derived-doc" + derived_from（"洞察_weekly_…" 不命中 DERIVED_RE，
    record_tier 默认会误标 primary，必须在此显式覆盖；doc_tier 优先读台账）。
    永不抛：任何异常吞掉返回 ""；成功返回 doc_id（dupe 也返回既有 doc_id）。
    """
    import json
    import shutil
    try:
        if not result.path or not os.path.isfile(result.path):
            return ""
        os.makedirs(vault.inbox, exist_ok=True)
        dest = os.path.join(vault.inbox, os.path.basename(result.path))
        if os.path.exists(dest):            # 同名旧回流件先让位，避免 sha1 dupe
            os.remove(dest)
        src_sha = L.sha1(result.path)          # 复制前算好：inbox 文件摄取后会被 stage 走
        shutil.copy2(result.path, dest)
        from cenhua_service import core as CO
        ir = CO.ingest(vault, dest)
        if ir.status not in ("added", "dupe"):
            return ""
        # core.ingest 对 inbox 新文件在 stage 后重算 sha1 会失败（doc_id 为空），
        # 用源文件 sha1 直接查 dedupe 索引回填（复制件与源内容一致）。
        doc_id = ir.doc_id
        if not doc_id:
            import m_ingest
            doc_id = (m_ingest.dedupe_index(vault).get(src_sha)
                      or {}).get("doc_id", "")
        if not doc_id:
            return ""
        # 台账改写：tmp + os.replace 原子写（仿 tier.record_tier）
        store = os.path.join(vault.store, "ingest_manifest.json")
        led = L.read_json(store, {}) or {}
        rec = led.get(doc_id)
        if rec is not None:
            rec["tier"] = "derived-doc"
            rec["derived_from"] = list(result.derived_from or [])
            led[doc_id] = rec
            tmp = store + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(led, f, ensure_ascii=False, indent=2,
                          sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, store)
        return doc_id
    except Exception:                       # 回流是锦上添花，永不拖垮 digest
        return ""
