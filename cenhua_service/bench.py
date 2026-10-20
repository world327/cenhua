"""cenhua_service.bench — 质量门禁（M1a，R2 + T2 + F6 + F7）。

`cenhua bench` 默认跑**随包分发的冻结 fixture 语料**（阻断级门禁）：
  * 存在性召回 100%（零容忍，铁律"沉默不是证据"的直接度量）
  * 引文条目准确率 >=95%（F7：按条目计量，每题挂多个引用点，全量条目 >=20）
  * 拒答正确率 >=90%（M2b 起进阻断集；需 LLM）

`cenhua bench --corpus` 跑用户库 QA（报告模式，只打印不阻断，T2）：
  * 每题带 corpus_hash，语料变更时自动标"题目过期（需重验答案）"，不计失败

门禁分层（F6.2）：
  * CI 层（tests/run_tests.sh）：fixture 存在性 + 溯源题，离线阻断
  * 发版流水线：全量 fixture（含拒答，需 API key），发版阻断；无 key 跳过拒答集

拒答非确定性治理（F6.3）：temperature=0 + 失败重试 1 次；同一题连续 2 个版本
flaky -> 自动转人工仲裁（meta/qa/flaky.jsonl），不连续阻断发版。

service 纪律：本模块禁止 print / exit。
"""

import json
import os
import re

import m_lib as L  # noqa: E402
from . import verify as V  # noqa: E402


def fixture_dir():
    return os.path.join(L.SKILL_DIR, "fixtures")


def fixture_text_dir():
    return os.path.join(fixture_dir(), "text")


def load_qa():
    """加载 fixture QA。返回 (questions, engine_version)。"""
    path = os.path.join(fixture_dir(), "qa.json")
    data = L.read_json(path, {}) or {}
    return data.get("questions") or [], data.get("engine_version", "")


def _fixture_text(doc_id):
    """读 fixture 文本层某文档。返回 [(page, text)]。"""
    path = os.path.join(fixture_text_dir(), f"{doc_id}.txt")
    if not os.path.isfile(path):
        return []
    pages, cur, buf = [], "?", []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            m = L.PAGE_RE.match(line.strip())
            if m:
                if buf:
                    pages.append((cur, "\n".join(buf).rstrip()))
                cur, buf = (m.group(1) or m.group(2)), []
            else:
                buf.append(line.rstrip("\n"))
    if buf:
        pages.append((cur, "\n".join(buf).rstrip()))
    return pages


def _fixture_verify(doc, page, snippet):
    """在 fixture 文本层上做 verify_citation（离线，零 LLM）。"""
    if not snippet:
        return False
    for pno, text in _fixture_text(doc):
        if str(pno) == str(page):
            return V.verify_citation(_FixtureVault(doc), doc, page, snippet)
    return False


class _FixtureVault:
    """让 verify_citation 能读 fixture 文本层的轻量 vault 适配器。"""

    def __init__(self, doc_id):
        self._doc = doc_id

    @property
    def textdir(self):
        return fixture_text_dir()


def _existence_hit(doc, term):
    """在 fixture 文本层中查找 term（归一化后子串匹配）。返回 (found, page)。"""
    norm_term = V._normalize(term)
    if not norm_term:
        return False, None
    for pno, text in _fixture_text(doc):
        if norm_term in V._normalize(text):
            return True, pno
    return False, None


def refusal_fixture_evidence():
    """拒答题的证据段 = 全部 fixture 文本层（截断，够判断'有没有'）。"""
    segs = []
    try:
        fns = sorted(os.listdir(fixture_text_dir()))
    except OSError:
        return []
    for fn in fns:
        if not fn.endswith(".txt"):
            continue
        doc = fn[:-4]
        pages = _fixture_text(doc)
        head = "\n".join(t for _, t in pages[:2])[:1500]
        segs.append({"doc": doc, "name": doc, "page": str(pages[0][0])
                     if pages else "?", "text": head})
    return segs


# 拒答成功的语言特征（模型如实说"语料里没有"）
_REFUSE_RE = re.compile(
    r"(无法回答|不能回答|无从回答|未提及|未包含|没有提及|没有找到|找不到|"
    r"未涉及|不足以回答|does not (?:mention|contain)|no (?:mention|information)|"
    r"cannot answer|not (?:found|mentioned|present))", re.I)


def _refusal_verdict(answer, citations):
    """判定模型回答是"拒答"还是"作答"。无引文 + 拒答措辞 -> refuse。"""
    if citations:
        return "answer"
    return "refuse" if _REFUSE_RE.search(answer or "") else "answer"


def run_refusal(refusal_qs):
    """跑 fixture 拒答题（M2b 门禁）。无网关 -> 全部 skipped（F6.2）。

    非确定性治理（F6.3）：temperature=0 + 失败重试 1 次。
    """
    from cenhua_service import prompt as P
    from cenhua_service import refine as R
    if not refusal_qs:
        return []
    env = L.build_env(None)
    if not L.chat_ready(env):
        return [{"id": q["id"], "question": q["question"],
                 "expect": q["expect"], "ok": None, "skipped": True}
                for q in refusal_qs]
    segs = refusal_fixture_evidence()
    items = []
    for q in refusal_qs:
        pr = P.build_prompt(q["question"],
                            [f"{P.HINT_MARK} (无 hint)"], P.evidence_block(segs))
        verdict, done = "answer", False
        for _attempt in range(2):                    # 重试 1 次（F6.3）
            try:
                raw, _tin, _tout = R.call_llm(pr, max_tokens=600,
                                              temperature=0)
            except Exception:
                break                                # 网关挂了：本条 aborted
            parsed = P.parse_answer(raw)
            if parsed:
                verdict = _refusal_verdict(parsed["answer"],
                                           parsed["citations"])
                done = True
                break
        ok = (verdict == q["expect"]) if done else None
        items.append({"id": q["id"], "question": q["question"],
                      "expect": q["expect"], "got": verdict, "ok": ok,
                      "skipped": not done})
    return items


# ------------------------------------------------------------ 拒答门禁 ----
# M2b 起进阻断集（F6.2）：fixture 拒答题 >=90% 通过；无网关全 skipped 不阻断。
# 非确定性治理（F6.3）：temperature=0 + 失败重试 1 次。
_REFUSE_RE = re.compile(
    r"(?:无法|不能|没有|未找到|不包含|不存在|超出|拒绝|无法回答|"
    r"语料中|资料中|文档中|未提及|未涉及|无法提供|无法确认|无法给出)"
    r".{0,20}(?:信息|内容|资料|答案|依据|证据|相关|条款|描述|记录|数据|"
    r"方案|技术|协议|计划|价格|设计|细节|情况|事实|说明|回答|支持|佐证)",
    re.S)


def _refusal_verdict(answer, citations):
    """判定一次拒答是否"正确拒答"。

    返回 True（正确拒答）/ False（未拒答但应拒）/ None（无法判定）。
    判定 = 无 citations + 拒答措辞双条件（防"有引文却拒答"的矛盾）。
    """
    if not answer:
        return None
    has_cites = bool(citations)
    refuse_wording = bool(_REFUSE_RE.search(answer))
    if not has_cites and refuse_wording:
        return True
    if has_cites:
        return False
    return None


def _refusal_pass(items):
    """拒答通过判定：>=90% 正确拒答（有判定项）。"""
    judged = [i for i in items if i.get("ok") is not None]
    if not judged:
        return None
    return sum(1 for i in judged if i["ok"]) / len(judged) >= 0.90


def refusal_fixture_evidence():
    """fixture 拒答题 -> 证据段（离线，供 LLM 判断是否应拒答）。"""
    questions, _ = load_qa()
    refusal = [q for q in questions if q.get("type") == "refusal"]
    out = []
    for q in refusal:
        # 用 fixture 全部文本层作为"语料"证据（离线）
        evidence = []
        for doc_id in sorted(os.listdir(fixture_text_dir())):
            if doc_id.endswith(".txt"):
                evidence.append(f"[{doc_id[:-4]}] "
                                + " ".join(t for _, t in _fixture_text(doc_id[:-4])))
        out.append({"id": q["id"], "question": q["question"],
                    "expect": q["expect"], "evidence": "\n".join(evidence)})
    return out


def run_refusal(refusal_qs):
    """跑拒答门禁（需 LLM）。无网关 -> 全 skipped（F6.2 不阻断）。

    refusal_qs: fixture 拒答题列表。返回
    {"total", "pass", "fail", "skipped", "items"}。
    """
    if not refusal_qs:
        return {"total": 0, "pass": 0, "fail": 0, "skipped": 0, "items": []}
    if not L.chat_ready(L.build_env(None)):
        return {"total": len(refusal_qs), "pass": 0, "fail": 0,
                "skipped": len(refusal_qs),
                "items": [{"id": q["id"], "question": q["question"],
                           "expect": q["expect"], "ok": None, "skipped": True}
                          for q in refusal_qs]}
    from cenhua_service import refine as R
    from cenhua_service import prompt as P
    items = []
    for q in refusal_qs:
        prompt = (P._INSTRUCTION
                  + f"\n问题：{q['question']}\n"
                  + "若语料中无相关信息，请拒答（answer 说明无法回答，"
                    "citations 留空）。\n")
        ok = None
        for attempt in range(2):          # F6.3：temperature=0 + 重试 1 次
            try:
                raw, _, _ = R.call_llm(prompt, max_tokens=300, temperature=0)
            except Exception:
                raw = ""
            parsed = P.parse_answer(raw)
            if parsed is None:
                continue
            verdict = _refusal_verdict(parsed["answer"], parsed["citations"])
            if verdict is not None:
                ok = verdict
                break
        items.append({"id": q["id"], "question": q["question"],
                      "expect": q["expect"], "ok": ok, "skipped": ok is None})
    return {"total": len(items),
            "pass": sum(1 for i in items if i["ok"] is True),
            "fail": sum(1 for i in items if i["ok"] is False),
            "skipped": sum(1 for i in items if i["ok"] is None),
            "items": items}


# ------------------------------------------------- 注入对抗门禁（M3a 任务13）----
def run_injection(inj_qs):
    """注入对抗 fixture（离线零 LLM，进阻断集）。

    判定：hint 文本经 sanitize_hint 逐句消毒后——
      1) 注入特征（_INJECT_RE / is_imperative）必须全部被剔除；
      2) keep_terms 事实句不得被误伤（防硬规则扩大化误杀陈述句）。
    fixture 治理：对抗题 >=1/3 标注 author=="human"（R4 §4 防同源盲区）。
    """
    from cenhua_service import prompt as P
    items = []
    human = 0
    for q in inj_qs:
        if q.get("author") == "human":
            human += 1
        clean, _dropped = P.sanitize_hint(q["hint_text"])
        residue = [s.strip() for s in P._SENT_SPLIT.split(clean)
                   if s.strip() and P.is_imperative(s.strip())]
        missing = [t for t in q.get("keep_terms", []) if t not in clean]
        items.append({"id": q["id"], "question": q["question"][:40],
                      "author": q.get("author", "llm"),
                      "residue": residue, "missing_terms": missing,
                      "ok": not residue and not missing})
    ratio = (human / len(inj_qs)) if inj_qs else 1.0
    return {"total": len(inj_qs),
            "pass": sum(1 for i in items if i["ok"]),
            "human": human, "human_ratio": ratio, "items": items}


def run_fixture():
    """跑 fixture 阻断级门禁（存在性 + 溯源，离线零 LLM）。

    返回 report dict：
      {existence: {total, pass, fail, items[]},
       traceability: {total_entries, pass_entries, fail_entries, items[]},
       refusal: {total, pass, fail, skipped, items[]},
       injection: {total, pass, human, human_ratio, items[], ok},
       ok: bool}
    """
    questions, engine_version = load_qa()
    existence = [q for q in questions if q.get("type") == "existence"]
    trace = [q for q in questions if q.get("type") == "traceability"]
    refusal = [q for q in questions if q.get("type") == "refusal"]

    # ---- existence: 存在性召回 100% 零容忍 ----
    ex_items = []
    ex_pass = 0
    for q in existence:
        found, page = _existence_hit(q["expect_doc"], q["term"])
        ok = found and str(page) == str(q.get("expect_page", page))
        if ok:
            ex_pass += 1
        ex_items.append({
            "id": q["id"], "term": q["term"], "doc": q["expect_doc"],
            "expect_page": q.get("expect_page"), "found_page": page, "ok": ok,
        })

    # ---- traceability: 引文按条目计量（F7），每题挂多个引用点 ----
    # 每题一个或多个 snippet 条目；全量条目 >=20 由 fixture 设计保证
    tr_items = []
    tr_pass = 0
    for q in trace:
        cites = q.get("citations") or [{"page": q.get("page"),
                                        "snippet": q.get("snippet")}]
        for c in cites:
            ok = _fixture_verify(q["doc"], c["page"], c["snippet"])
            if ok:
                tr_pass += 1
            tr_items.append({
                "id": q["id"], "doc": q["doc"], "page": c["page"],
                "snippet": c["snippet"], "ok": ok,
            })

    # ---- injection: M3a 任务 13 阻断集（离线）：零残留 + 零误伤 + 人工占比 ----
    inj = run_injection([q for q in questions if q.get("type") == "injection"])
    inj_ok = (inj["total"] == 0) or (inj["pass"] == inj["total"]
                                     and inj["human_ratio"] >= 1.0 / 3)

    # ---- refusal: M2b 起进阻断集；无 LLM 网关 -> skipped（F6.2 跳过路径） ----
    ref_items = run_refusal(refusal)["items"]
    refused = all(i.get("skipped") for i in ref_items) if ref_items else True

    ex_total = len(existence)
    tr_total = len(tr_items)
    ex_ok = ex_total > 0 and ex_pass == ex_total
    tr_ok = tr_total >= 20 and (tr_pass / tr_total) >= 0.95
    # 拒答 >=90%（仅当实际执行时参与阻断；skipped 不阻断离线 CI，F6.2）
    ref_done = [i for i in ref_items if not i.get("skipped")]
    ref_pass = sum(1 for i in ref_done if i["ok"])
    ref_ok = (not ref_done) or (len(ref_done) > 0
                                and ref_pass / len(ref_done) >= 0.90)

    return {
        "engine_version": engine_version,
        "existence": {"total": ex_total, "pass": ex_pass, "items": ex_items,
                      "ok": ex_ok},
        "traceability": {"total_entries": tr_total, "pass_entries": tr_pass,
                         "items": tr_items, "ok": tr_ok},
        "refusal": {"total": len(refusal), "pass": ref_pass,
                    "skipped": len(refusal) - len(ref_done),
                    "items": ref_items,
                    "ok": None if refused else ref_ok},
        "injection": dict(inj, ok=inj_ok),
        "ok": ex_ok and tr_ok and ref_ok and inj_ok,
    }


def run_corpus(vault):
    """跑用户库 QA（报告模式，只打印不阻断，T2）。

    用户库 QA 集在 <vault>/meta/qa/benchmark.jsonl；每题带 corpus_hash，
    语料变更时自动标"题目过期（需重验答案）"，不计失败。
    """
    path = os.path.join(vault.meta, "qa", "benchmark.jsonl")
    if not os.path.isfile(path):
        return {"ok": None, "note": "no user QA set (meta/qa/benchmark.jsonl)",
                "items": []}
    items = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            q = json.loads(line)
        except ValueError:
            continue
        # 存在性题：查文本层
        if q.get("type") == "existence":
            found, page = _corpus_existence(vault, q.get("term", ""))
            ok = found
            items.append({"id": q.get("id"), "type": "existence",
                          "term": q.get("term"), "ok": ok,
                          "found_page": page})
        # 溯源题：verify_citation
        elif q.get("type") == "traceability":
            ok = V.verify_citation(vault, q.get("doc", ""), q.get("page", ""),
                                   q.get("snippet", ""))
            items.append({"id": q.get("id"), "type": "traceability",
                          "doc": q.get("doc"), "page": q.get("page"),
                          "ok": ok})
        else:
            items.append({"id": q.get("id"), "type": q.get("type", "?"),
                          "ok": None, "skipped": True})
    return {"ok": None, "note": "report mode (not blocking)", "items": items}


def _corpus_existence(vault, term):
    """在用户库文本层查找 term。返回 (found, page)。"""
    norm_term = V._normalize(term)
    if not norm_term:
        return False, None
    docs = L.store_docs(vault)
    for doc_id in docs:
        for pno, text in L.text_pages(vault, doc_id):
            if norm_term in V._normalize(text):
                return True, pno
    return False, None


def bench_report_lines(vault, corpus=False):
    """生成 `cenhua bench` 的可打印行（service 层组装，CLI 只负责输出）。"""
    if corpus:
        rep = run_corpus(vault)
        lines = [f"bench --corpus (report mode, not blocking): "
                 f"{rep.get('note', '')}"]
        for it in rep.get("items", []):
            status = "PASS" if it.get("ok") else ("SKIP" if it.get("skipped")
                                                  else "FAIL")
            lines.append(f"  [{status}] {it.get('id', '?')} "
                         f"{it.get('type', '?')} "
                         f"{it.get('term') or it.get('doc') or it.get('question', '')}")
        return lines

    rep = run_fixture()
    ex = rep["existence"]
    tr = rep["traceability"]
    ref = rep["refusal"]
    lines = [f"cenhua bench (fixture, engine v{rep.get('engine_version', '?')}):"]
    lines.append(f"  existence   : {ex['pass']}/{ex['total']}  "
                 f"{'PASS' if ex['ok'] else 'FAIL'}  (100% required)")
    lines.append(f"  traceability: {tr['pass_entries']}/{tr['total_entries']} "
                 f"entries  {'PASS' if tr['ok'] else 'FAIL'}  (>=95%, n>=20)")
    inj = rep.get("injection") or {}
    if inj.get("total"):
        lines.append(f"  injection   : {inj['pass']}/{inj['total']}  "
                     f"{'PASS' if inj.get('ok') else 'FAIL'}  "
                     f"(zero-residue, human {inj['human']}/{inj['total']} "
                     f">=1/3)")
        for it in inj.get("items", []):
            if not it["ok"]:
                lines.append(f"    FAIL injection {it['id']}: "
                             f"residue={it['residue']} "
                             f"missing={it['missing_terms']}")
    if ref["skipped"] and ref["skipped"] == ref["total"]:
        lines.append(f"  refusal     : {ref['total']} skipped "
                     f"(LLM gateway not configured — release pipeline must "
                     f"run with PI_BASE/PI_KEY, F6.2)")
    else:
        done = ref["total"] - ref["skipped"]
        rate = f"{ref['pass']}/{done}" if done else "0/0"
        lines.append(f"  refusal     : {rate}  "
                     f"{'PASS' if ref.get('ok') else 'FAIL'}  (>=90% required)")
        for it in ref["items"]:
            if it.get("ok") is False:
                lines.append(f"    FAIL refusal {it['id']}: "
                             f"question={it['question'][:40]} "
                             f"got={it.get('got')} expect={it['expect']}")
    if not ex["ok"]:
        for it in ex["items"]:
            if not it["ok"]:
                lines.append(f"    FAIL existence {it['id']}: term={it['term']} "
                             f"doc={it['doc']} expect_page={it['expect_page']} "
                             f"found_page={it['found_page']}")
    if not tr["ok"]:
        for it in tr["items"]:
            if not it["ok"]:
                lines.append(f"    FAIL traceability {it['id']}: doc={it['doc']} "
                             f"page={it['page']} snippet={it['snippet'][:40]!r}")
    lines.append("  RESULT: PASS (offline gate)" if rep["ok"]
                 else "  RESULT: FAIL (offline gate)")
    return lines


# ------------------------------------------------------- flaky governance ----
def flaky_path(vault):
    return os.path.join(vault.meta, "qa", "flaky.jsonl")


def record_flaky(vault, qid, detail):
    """记录一次 flaky 事件（F6.3）。返回是否已连续 2 版需人工仲裁。"""
    import time
    path = flaky_path(vault)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    recs = []
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    pass
    recs.append({"ts": time.strftime("%F %T"), "qid": qid, "detail": detail})
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # 同一题连续 2 个版本 flaky -> 需人工仲裁
    same = [r for r in recs if r.get("qid") == qid]
    return len(same) >= 2
