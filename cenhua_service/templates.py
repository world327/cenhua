"""cenhua_service.templates — `cenhua template` 模板化创作（M4c 任务 12，roadmap §7.5）。

内置四模板：报告 report / 备忘录 memo / 邮件 email / 周报 weekly；
自定义模板放 `<vault>/meta/templates/<id>.md`（同名 **覆盖** 内置）。

与 draft 的关系（dev-plan §8.6 复用优先，不复制一份生成逻辑）：
  * 召回          -> draft.recall（fuse 后仅 primary）
  * 证据/hint     -> query.evidence_for + prompt.hint_block（两段式）
  * LLM           -> refine.call_llm（唯一网关出口）
  * 解析/兜底     -> draft.parse_draft / draft.rule_fallback（规则优先铁律）
  * 引文校验      -> query.verify_citations（F2 同一门禁）
  * 版本/落盘/rid -> draft.next_version / assemble / rid_*（命名集中一处）
  * 产物          -> works/drafts/<主题>_V{N}_<日期>.md（tier=derived-doc，
                     与 draft 同一目录 -> Web 编辑三件套/导出天然可用）

模板差异只落在两处：小节骨架（sections）与文风指令（style）。
自定义模板格式（meta/templates/<id>.md）：
    <!-- template: id=xxx name=显示名 -->
    ## 小节一
    ## 小节二
零 LLM 的模板浏览（list/show）离线即时；生成走三闸（dry-run →
网关可用 → longjob 预算），rc 语义与 draft 对齐：
0 成功 / 1 召回为空或生成失败 / 2 参数错 / 3 网关未配置 / 4 预算拒绝。

service 纪律：零 print / 零 exit（test_70）。
"""
from __future__ import annotations

import os
import re
import time
from typing import List

import m_lib as L  # noqa: E402  (scripts/ 在 sys.path)

TPL_DIR = "templates"               # <vault>/meta/templates/
_TPL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_TPL_FRONT_RE = re.compile(r"^<!--\s*template:\s*(.*?)\s*-->\s*$", re.M)
_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)

# 内置四模板（roadmap §7.5）：小节骨架 + 文风指令差异
BUILTIN = {
    "report": {
        "id": "report", "name": "报告",
        "style": "正式的决策支持报告：结论先行，逐节论证，措辞审慎",
        "sections": ["背景", "现状与证据", "风险与缺口", "结论与建议"]},
    "memo": {
        "id": "memo", "name": "备忘录",
        "style": "内部备忘录：要点式直陈利害，避免铺陈，突出待决事项",
        "sections": ["事项概述", "关键事实", "影响分析", "建议行动"]},
    "email": {
        "id": "email", "name": "邮件",
        "style": "对外邮件：礼貌简洁，事由清晰，正文控制在可一屏读完的篇幅",
        "sections": ["称呼与事由", "核心信息", "依据与数据", "下一步"]},
    "weekly": {
        "id": "weekly", "name": "周报",
        "style": "工作周报：量化进展，如实暴露问题，计划可验收",
        "sections": ["本周进展", "关键数据", "问题与风险", "下周计划"]},
}


def tpl_dir(vault) -> str:
    return os.path.join(vault.meta, TPL_DIR)


def load(vault, tid: str):
    """模板 id -> dict（自定义同名覆盖内置）。不存在 -> None。"""
    tid = (tid or "").strip().lower()
    if not tid:
        return None
    path = os.path.join(tpl_dir(vault), tid + ".md")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
        meta = {}
        m = _TPL_FRONT_RE.search(text)
        if m:
            for pair in m.group(1).split():
                if "=" in pair:
                    k, val = pair.split("=", 1)
                    meta[k] = val
        secs = _H2_RE.findall(text)
        base = dict(BUILTIN.get(tid) or {})
        base.update({"id": tid,
                     "name": meta.get("name") or base.get("name") or tid,
                     "sections": secs or base.get("sections", []),
                     "style": meta.get("style") or base.get("style", ""),
                     "builtin": tid in BUILTIN, "custom": True,
                     "path": path})
        return base
    if tid in BUILTIN:
        row = dict(BUILTIN[tid])
        row.update({"builtin": True, "custom": False, "path": ""})
        return row
    return None


def list_templates(vault) -> List[dict]:
    """内置 + 自定义全量（同 id 自定义胜出）。按 id 排序。"""
    ids = set(BUILTIN)
    d = tpl_dir(vault)
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.endswith(".md"):
                ids.add(fn[:-3].lower())
    rows = []
    for tid in sorted(ids):
        t = load(vault, tid)
        if t:
            rows.append({"id": t["id"], "name": t["name"],
                         "builtin": t["builtin"], "custom": t.get("custom"),
                         "sections": list(t["sections"])})
    return rows


def add_template(vault, tid: str, name: str = "", sections=None,
                 overwrite=False):
    """新增/覆盖自定义模板（验收：自定义可加）。原子写。

    rc：0 成功 / 2 id 非法或已存在且未 --force。
    """
    tid = (tid or "").strip().lower()
    if not _TPL_ID_RE.match(tid):
        return {"rc": 2, "lines": ["template: id 需为小写字母/数字/下划线"
                                   "（2-32 位），如 board_brief"]}
    path = os.path.join(tpl_dir(vault), tid + ".md")
    if os.path.isfile(path) and not overwrite:
        return {"rc": 2, "lines": ["template: %s/%s.md 已存在"
                                   "（--force 覆盖）" % (TPL_DIR, tid)]}
    secs = [s.strip() for s in (sections or []) if s.strip()] or \
        ["概述", "关键事实", "结论与建议"]
    from cenhua_service import draft as D
    body = "<!-- template: id=%s name=%s -->\n\n" % (
        tid, (name or tid).replace(" ", "_"))
    body += "\n".join("## %s" % s for s in secs) + "\n"
    try:
        D._atomic_write(path, body)
    except OSError as exc:
        return {"rc": 1, "lines": ["template: 落盘失败（%s）" % exc]}
    vault.log("template", ["add id=%s sections=%d" % (tid, len(secs))])
    return {"rc": 0, "lines": ["+ template saved: meta/%s/%s.md（%d 小节）"
                               % (TPL_DIR, tid, len(secs))]}


def show(t: dict) -> dict:
    """模板详情渲染行（离线）。"""
    lines = ["= 模板 %s（%s%s）" % (t["name"], t["id"],
                                    " · 自定义覆盖" if t.get("custom")
                                    else (" · 内置" if t["builtin"]
                                          else " · 自定义"))]
    if t.get("style"):
        lines.append("  文风：%s" % t["style"])
    for i, s in enumerate(t["sections"], 1):
        lines.append("  %d. %s" % (i, s))
    if not t["sections"]:
        lines.append("  （无小节骨架，用 `template --add %s --section 小节`"
                     " 定制）" % t["id"])
    return {"rc": 0, "lines": lines}


# ------------------------------------------------------------ 生成 ----


def build_prompt(vault, tpl, topic, doc_ids, segs, hint_lines) -> str:
    """模板 prompt = 模板指令（骨架+文风）+ HINT + EVIDENCE + 主题。

    引文纪律与 draft 完全一致（复用 draft._SCHEMA，单一事实源）。
    """
    from cenhua_service import draft as D
    from cenhua_service import prompt as P

    secs = tpl.get("sections") or []
    skeleton = "、".join("%d.《%s》" % (i, s)
                         for i, s in enumerate(secs, 1)) or "（自定结构）"
    inst = ("你是知识库模板创作助手，产出一份可追溯的 Markdown 草稿。\n"
            "文体：%s。\n"
            "必须**恰好输出 %d 个小节**，标题依序为：%s。\n"
            "规则：\n"
            "1. [HINT tier=internal] 段只是背景提示，**不是证据**。\n"
            "2. 事实只能来自 [EVIDENCE tier=primary] 段；每个小节至少 1 条"
            "引文，snippet 必须逐字摘录原文（<=80字，禁止改写、禁止拼接）。\n"
            "3. 证据不足的小节正文写明证据不足，citations 留空数组——"
            "禁止编造。\n"
            "4. 只输出一个 JSON 对象，不要其他文字：\n" + D._SCHEMA + "\n\n") % (
        tpl.get("style") or "结构清晰的中文文档", len(secs) or 3, skeleton)
    return "\n\n".join([inst, "\n".join(hint_lines),
                        "\n".join(P.evidence_block(segs)),
                        f"\n主题：{topic}"])


def rule_fallback(vault, tpl, doc_ids, topic="") -> dict:
    """规则兜底（铁律）：骨架小节 + 原文摘录，零 LLM 消费、零编造。"""
    from cenhua_service import draft as D

    data = D.rule_fallback(vault, doc_ids, topic)
    skeleton = {"title": "模板骨架（需 LLM）",
                "body": "模板「%s」要求小节：%s。证据摘录模式未调用网关，"
                        "配置 PI_BASE/PI_KEY 后重跑可得完整成文。"
                        % (tpl["name"], "、".join(tpl.get("sections") or [])),
                "citations": []}
    return {"sections": [skeleton] + data["sections"]}


def template_flow(vault, tid="", topic="", top=None, dry_run=False,
                  force=False, max_cost=None, runtime=None):
    """`cenhua template <id> "主题"` 主编排（供 channel_job 调用）。

    与 draft_flow 同一套闸门/rid/落盘/回流，只是 prompt 换成模板骨架。
    rc：0 成功 / 1 召回为空或生成失败 / 2 参数错 / 3 网关未配置 / 4 预算拒绝。
    """
    from cenhua_service import cost as CC
    from cenhua_service import draft as D
    from cenhua_service import prompt as P
    from cenhua_service import query as Q
    from cenhua_service import refine as R
    from cenhua_service import digest as DG

    lines: List[str] = []
    tid = (tid or "").strip().lower()
    topic = (topic or "").strip()
    if not tid or not topic:
        return D.DraftResult(lines=[
            "usage: cenhua template <报告|备忘录|邮件|周报|自定义id> \"主题\""
            " [--dry-run] [--force] [--max-cost X] [--top N]"], rc=2)
    tpl = load(vault, tid)
    if not tpl:
        avail = ",".join(t["id"] for t in list_templates(vault))
        return D.DraftResult(lines=["template: 未知模板 '%s'（现有 %s）"
                                    % (tid, avail)], rc=2)

    doc_ids = D.recall(vault, topic, top=top or D.MAX_DOCS)
    if not doc_ids:
        lines.append("= 召回为空（find+seek 均无 primary 命中）——"
                     "先 `cenhua add` 补语料，或换措辞")
        return D.DraftResult(lines=lines, rc=1, topic=topic)
    version = D.next_version(vault, topic)
    rid = D.make_rid("tpl:" + tid, topic, None, doc_ids)
    hit = D.rid_seen(vault, rid)
    if hit and not dry_run:            # rid 幂等：同键已成功，不重复花钱
        lines.append("[template] idempotent : rid=%s 已产出 %s（未重复调用网关）"
                     % (rid, os.path.basename(hit)))
        return D.DraftResult(lines=lines, rc=0, topic=topic, path=hit,
                             rid=rid, mode="cached",
                             derived_from=list(doc_ids))

    segs = Q.evidence_for(vault, doc_ids)
    hint_lines, hint_meta = P.hint_block(vault, doc_ids)
    if not segs:
        lines.append("[template] evidence    : 无 primary 文本层，无法取证")
        return D.DraftResult(lines=lines, rc=1, topic=topic, rid=rid,
                             derived_from=list(doc_ids))
    prompt_text = build_prompt(vault, tpl, topic, doc_ids, segs, hint_lines)
    if runtime:
        runtime.progress(0.2)

    est = Q.estimate(vault, prompt_text, calls=1)
    lines.append("[template] cost        : %.4f %s%s"
                 % (est.get("est_cost", 0.0), est.get("currency", "CNY"),
                    "" if est.get("priced") else "  (%s)" % est.get("note", "")))
    if dry_run:
        lines.append("[template] dry-run     : 未调用网关（去掉 --dry-run 即执行）")
        return D.DraftResult(lines=lines, rc=0, cost=est, topic=topic, rid=rid)
    if not L.chat_ready(L.build_env(vault)):
        lines.append("[template] gateway     : 未配置 PI_BASE/PI_KEY，"
                     "无法生成（--dry-run 可看估价）")
        return D.DraftResult(lines=lines, rc=3, cost=est, topic=topic,
                             rid=rid, derived_from=list(doc_ids))
    ok, msg = DG.budget_check(vault, est, force=force, max_cost=max_cost)
    lines.append("[template] budget      : %s" % msg)
    if not ok:
        return D.DraftResult(lines=["[template] REFUSED — " + msg] + lines,
                             rc=4, cost=est, topic=topic, rid=rid,
                             derived_from=list(doc_ids))
    if runtime:
        runtime.progress(0.35)

    raw, tin, tout, m = "", 0, 0, "llm"
    try:
        raw, tin, tout = R.call_llm(prompt_text, max_tokens=2600)
    except Exception as exc:
        vault.log("template", ["llm_error=%s" % type(exc).__name__])
        lines.append("[template] llm         : 调用失败（%s），转规则兜底"
                     % type(exc).__name__)
        m = "rules"
    data = D.parse_draft(raw) if m == "llm" else None
    if m == "llm" and data is None:
        vault.log("template", ["parse_failed"])
        lines.append("[template] parse       : LLM 输出无法解析，转规则兜底")
        m = "rules"
    if runtime:
        runtime.progress(0.7)

    sections = (data or rule_fallback(vault, tpl, doc_ids, topic))["sections"]
    if m == "rules":
        est = Q.estimate(vault, prompt_text, calls=0)
    cites = Q.verify_citations(vault, D.resolve_ids(
        vault, D._all_citations({"sections": sections})))
    okn = sum(1 for c in cites if c.get("ok"))

    article = D.assemble(vault, topic, version, sections, cites, m,
                         doc_ids, rid)
    # 模板溯源标记跟在 draft front 行之后（Web/回流不需感知）
    for i, ln in enumerate(article):
        if ln.startswith("<!-- draft: "):
            article.insert(i + 1, "<!-- template: %s -->" % tid)
            break
    fname = "%s_V%d_%s.md" % (D.slug(topic), version,
                              time.strftime("%Y-%m-%d"))
    path = os.path.join(D.drafts_dir(vault), fname)
    try:
        D._atomic_write(path, "\n".join(article))
    except OSError as exc:
        vault.log("template", ["write_failed=%s" % exc])
        lines.append("[template] write       : 落盘失败（%s）" % exc)
        return D.DraftResult(lines=lines, rc=1, cost=est, topic=topic,
                             mode=m, rid=rid, derived_from=list(doc_ids))
    D.rid_record(vault, rid, path, topic)

    ccny = CC.to_cny(est.get("est_cost") or 0.0, est.get("currency", "CNY"))
    CC.ledger_append(vault, {"cmd": "template", "doc": fname[:200],
                             "template": tid, "rid": rid,
                             "calls": est.get("calls", 0),
                             "tokens_in": tin or est.get("tokens_in", 0),
                             "tokens_out": tout or est.get("tokens_out", 0),
                             "est_cost": est.get("est_cost"),
                             "currency": est.get("currency"),
                             "priced": est.get("priced"),
                             "hint_docs": hint_meta["docs"]})
    if runtime:
        runtime.add_cost(calls=est.get("calls", 0), cost=ccny, currency="CNY")
        runtime.progress(1.0)

    lines.append("[template] engine      : %s"
                 % ("LLM 生成" if m == "llm" else "规则兜底（零 LLM 消费）"))
    lines.append("[template] citations   : %d/%d 校验通过" % (okn, len(cites)))
    lines.append("[template] article     : works/%s/%s" % (D.DRAFT_DIR, fname))
    vault.log("template", ["id=%s topic=%s engine=%s docs=%d cites=%d ok=%d"
                           " rid=%s file=%s" % (tid, topic, m, len(doc_ids),
                                                len(cites), okn, rid, fname)])
    result = D.DraftResult(lines=lines, rc=0, cost=est, topic=topic, mode=m,
                           path=path, version=version, rid=rid,
                           sections=sections, citations=cites,
                           derived_from=list(doc_ids))
    back = D.ingest_back(vault, result)
    lines.append("[template] backflow    : %s"
                 % (("inbox -> %s (tier=derived-doc)" % back) if back
                    else "skipped（不影响文章）"))
    return result


# ------------------------------------------------------------ CLI ----
USAGE = (
    "usage: cenhua template --list                     [OFFLINE]\n"
    "       cenhua template <id>                       查看模板骨架 [OFFLINE]\n"
    "       cenhua template --add <id> [--name 名称] --section 小节 ...\n"
    "                                     自定义模板 -> meta/templates/ [OFFLINE]\n"
    "       cenhua template <id> \"主题\" [--top N] [--dry-run] [--force]\n"
    "                       [--max-cost X]\n"
    "                                     产物 works/drafts/（tier=derived-doc）"
    "，longjob 预算闸"
)

def parse_cli(rest):
    """template CLI 参数 -> kwargs（service 层解析；test_71 下沉）。

    按下标扫描：`--section` 可重复，其余带值 flag 取下一个 token。
    """
    rest = list(rest or [])
    kw = {"action": "", "tid": "", "topic": "", "name": "", "sections": [],
          "dry_run": False, "force": False, "max_cost": None, "top": None}
    pos, i = [], 0
    while i < len(rest):
        a = rest[i]
        if a in ("--list", "--add"):
            kw["action"] = a[2:]
        elif a == "--dry-run":
            kw["dry_run"] = True
        elif a == "--force":
            kw["force"] = True
        elif a == "--name" and i + 1 < len(rest):
            kw["name"] = rest[i + 1]
            i += 1
        elif a == "--section" and i + 1 < len(rest):
            kw["sections"].append(rest[i + 1])
            i += 1
        elif a == "--sections" and i + 1 < len(rest):
            kw["sections"] += [s for s in rest[i + 1].split(",") if s]
            i += 1
        elif a == "--top" and i + 1 < len(rest):
            try:
                kw["top"] = int(rest[i + 1])
            except ValueError:
                pass                        # 坏值降级默认
            i += 1
        elif a == "--max-cost" and i + 1 < len(rest):
            try:
                kw["max_cost"] = float(rest[i + 1])
            except ValueError:
                pass
            i += 1
        elif a.startswith("-") and len(a) > 1:
            pass
        else:
            pos.append(a)
        i += 1
    if pos:
        kw["tid"] = pos[0].lower()
    if len(pos) > 1:
        kw["topic"] = " ".join(pos[1:])
    return kw


def aux_flow(vault, kw):
    """离线辅助动作：list / show / add。"""
    action = kw.get("action", "")
    if action == "list":
        rows = list_templates(vault)
        lines = ["= 模板 %d 个（内置 4 + meta/%s/ 自定义）：" % (len(rows),
                                                                TPL_DIR)]
        for t in rows:
            tag = "自定义覆盖" if t["custom"] and t["builtin"] else \
                ("内置" if t["builtin"] else "自定义")
            lines.append("  %-10s %s  [%s]  %d 小节"
                         % (t["id"], t["name"], tag, len(t["sections"])))
        return {"rc": 0, "lines": lines}
    if action == "add":
        return add_template(vault, kw["tid"], kw["name"], kw["sections"],
                            overwrite=kw["force"])
    t = load(vault, kw["tid"])
    if not t:
        return {"rc": 2, "lines": ["template: 未知模板 '%s'" % kw["tid"],
                                   USAGE]}
    return show(t)


def gen_kwargs(rest):
    """生成类参数 -> template_flow kwargs（CLI 侧 channel_job 直接 **展开）。"""
    kw = parse_cli(rest)
    return {"tid": kw["tid"], "topic": kw["topic"], "top": kw["top"],
            "dry_run": kw["dry_run"], "force": kw["force"],
            "max_cost": kw["max_cost"]}


def needs_channel(rest) -> bool:
    """list/show/add 离线即时；生成（有主题）走任务通道。"""
    kw = parse_cli(rest)
    return not kw["action"] and bool(kw["topic"])


def flow(vault, rest):
    """`cenhua template ...` 总入口。"""
    kw = parse_cli(rest)
    if kw["action"] or not kw["topic"]:      # list/add/show 均离线
        return aux_flow(vault, kw)
    return template_flow(vault, tid=kw["tid"], topic=kw["topic"],
                         top=kw["top"], dry_run=kw["dry_run"],
                         force=kw["force"], max_cost=kw["max_cost"])
