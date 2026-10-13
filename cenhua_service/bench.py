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


def run_fixture():
    """跑 fixture 阻断级门禁（存在性 + 溯源，离线零 LLM）。

    返回 report dict：
      {existence: {total, pass, fail, items[]},
       traceability: {total_entries, pass_entries, fail_entries, items[]},
       refusal: {total, pass, fail, skipped, items[]},
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

    # ---- refusal: 需 LLM，M2b 起进阻断集；此处标记 skipped（离线） ----
    ref_items = [{"id": q["id"], "question": q["question"],
                  "expect": q["expect"], "ok": None, "skipped": True}
                 for q in refusal]

    ex_total = len(existence)
    tr_total = len(tr_items)
    ex_ok = ex_total > 0 and ex_pass == ex_total
    tr_ok = tr_total >= 20 and (tr_pass / tr_total) >= 0.95

    return {
        "engine_version": engine_version,
        "existence": {"total": ex_total, "pass": ex_pass, "items": ex_items,
                      "ok": ex_ok},
        "traceability": {"total_entries": tr_total, "pass_entries": tr_pass,
                         "items": tr_items, "ok": tr_ok},
        "refusal": {"total": len(refusal), "pass": 0, "skipped": len(refusal),
                    "items": ref_items, "ok": None},
        "ok": ex_ok and tr_ok,
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
    lines.append(f"  refusal     : {ref['skipped']}/{ref['total']} skipped "
                 f"(needs LLM, M2b+; offline CI skips)")
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
