#!/usr/bin/env python3
"""m_ingest.py — CENHUA intake loop: inbox -> engine -> text layer -> ready.

The one habit this CLI removes: the engine requires `pi_flatten.py` after every
ingest, and forgetting it makes `find` silently miss new documents. Here,
flatten runs automatically after any successful ingest (flatten is offline,
incremental and sub-second, so this is free).

Isolation rule: one engine subprocess per file. A crash/OCR timeout in one
document can never strand the rest of the batch; failures land in
inbox/.failed/ with the reason in logs/ingest-*.log.

Dedupe: CENHUA keeps meta/dedupe.json (sha1 -> doc_id) on top of the engine's
own sha1 dedupe, so re-dropping the same file is a no-op (no LLM call, no
double billing).

零网关降级（M5-4）：pi_ingest.py 硬卡 PI_BASE/PI_KEY sys.exit()，
pi_flatten.py 完全离线无 LLM 依赖。缺网关时走 _offline_ingest
（手动造 pages.json/manifest/dedupe + 跑 flatten）—— find 立即可用，
LLM 功能（query/ask/digest/draft）继续 fail-closed。这不是改引擎，是
service 层 fallback（引擎字节不可改，AGENTS.md 铁律）。
"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))            # scripts/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # ROOT (cenhua_service/)
import m_lib as L  # noqa: E402
import m_ocr  # noqa: E402

ADDED_RE = re.compile(r"^\+\s(.+?)\s->\s(\S+)\s", re.M)


def restore_provenance(vault, doc_id, orig_path, name):
    """After a local-OCR preconvert ingest the engine ledger row describes the
    transcription PDF. Rewrite it to the ORIGINAL upload (name, source path,
    archived copy) so citations and `cenhua sources` keep pointing at the real
    source file; sources/ holds originals only."""
    man_path = os.path.join(vault.store, "ingest_manifest.json")
    man = L.read_json(man_path, {}) or {}
    rec = man.get(doc_id)
    if not rec:
        return
    old_stored = rec.get("stored_as", "")
    digest = L.sha1(orig_path)
    srcdir = os.path.join(vault.store, "sources")
    os.makedirs(srcdir, exist_ok=True)
    stored = os.path.join(srcdir, name)
    if os.path.exists(stored) and L.sha1(stored) != digest:
        stem, suf = os.path.splitext(name)
        stored = os.path.join(srcdir, f"{stem}_{digest[:8]}{suf}")
    try:
        if not os.path.exists(stored):
            import shutil
            shutil.copy2(orig_path, stored)
    except OSError as e:
        L.err(f"! could not archive original ({e}); ledger still rewritten")
        stored = old_stored
    rec.update({"name": name, "source": orig_path, "stored_as": stored})
    import json
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    # the engine archived our transcription PDF; drop that copy (the OCR PDF
    # stays at its cache path under meta/ocr/) so sources/ = true originals
    if old_stored and old_stored != stored \
            and old_stored.startswith(os.path.join(vault.store, "sources")) \
            and os.path.isfile(old_stored):
        try:
            os.remove(old_stored)
        except OSError:
            pass


def dedupe_index(vault):
    return L.read_json(os.path.join(vault.meta, "dedupe.json"), {}) or {}


def save_dedupe(vault, d):
    os.makedirs(vault.meta, exist_ok=True)
    import json
    with open(os.path.join(vault.meta, "dedupe.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def sync_dedupe(vault):
    """Rebuild the dedupe index from the engine ledger (self-healing)."""
    led = L.read_json(os.path.join(vault.store, "ingest_manifest.json"), {}) or {}
    d = dedupe_index(vault)
    for doc_id, rec in led.items():
        if rec.get("sha1") and rec["sha1"] not in d:
            d[rec["sha1"]] = {"doc_id": doc_id, "name": rec.get("name", "")}
    save_dedupe(vault, d)
    return d


# ---------------------------------------------------------------- 零网关降级 ---
def _offline_ingest(vault, path, quiet=False):
    """纯离线摄取（无网关 fallback，零 LLM）。

    pi_flatten.py 完全离线无网关依赖，但它需要 pages.json + manifest.json
    这些都是 pi_ingest.py（LLM 树索引）生成的——引擎字节不可改，所以在
    service 层手动造最小可用结构：pages.json（按 === PAGE N === 标记分页）
    + manifest.json + ingest_manifest.json + dedupe 索引。之后跑 flatten
    生成文本层——find 就能工作。LLM 功能（query/ask/digest/draft）继续
    fail-closed（它们本身就需要网关）。
    """
    import json, shutil
    path = os.path.abspath(path)
    name = os.path.basename(path)
    digest = L.sha1(path)

    # 1) 造 doc_id（与引擎格式一致，offline_<sha1[:12]>）
    doc_id = "offline_" + digest[:12]

    # 2) 归档原件到 sources/（与引擎同位置）
    srcdir = os.path.join(vault.store, "sources")
    os.makedirs(srcdir, exist_ok=True)
    stored = os.path.join(srcdir, name)
    if os.path.exists(stored) and L.sha1(stored) != digest:
        stem, suf = os.path.splitext(name)
        stored = os.path.join(srcdir, f"{stem}_{digest[:8]}{suf}")
    try:
        if not os.path.exists(stored):
            shutil.copy2(path, stored)
    except OSError:
        stored = path

    # 3) 提取文本（conv_* 或直接读）
    try:
        ext = os.path.splitext(path)[1].lower()
        if ext in (".md", ".markdown", ".txt", ".csv", ".html", ".htm"):
            text = open(path, encoding="utf-8", errors="replace").read()
        elif ext in (".docx", ".pptx"):
            import mammoth as _mm
            with open(path, "rb") as fh:
                text = _mm.extract_raw_text(fh)
        else:
            text = ""
    except Exception as exc:
        vault.log("ingest", ["offline 文本提取失败 %s: %s" %
                              (name, type(exc).__name__)])
        return "failed"

    if not text.strip():
        vault.log("ingest", ["offline 空文本 %s (图片/扫描？)" % name])
        return "failed"

    # 4) 按 === PAGE N === 标记分页（无标记则整页；与引擎 pages.json 格式一致）
    pages_dir = os.path.join(vault.store, "docs", doc_id)
    os.makedirs(pages_dir, exist_ok=True)
    pages = []
    cur_page, cur_text = 1, []
    for line in text.splitlines():
        m = re.match(r"^=== (?:PAGE (\d+)|第(\d+)页) ===$", line)
        if m and cur_text:
            pages.append({"page": cur_page,
                          "markdown": "\n".join(cur_text)})
            cur_page = int(m.group(1) or m.group(2))
            cur_text = [line]
        elif m:
            cur_page = int(m.group(1) or m.group(2))
            cur_text = [line]
        else:
            cur_text.append(line)
    if cur_text:
        pages.append({"page": cur_page, "markdown": "\n".join(cur_text)})
    if not pages:
        pages = [{"page": 1, "markdown": text}]

    with open(os.path.join(pages_dir, "pages.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"pages": pages}, fh, ensure_ascii=False)
    with open(os.path.join(pages_dir, "doc.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"name": name, "doc_id": doc_id}, fh, ensure_ascii=False)

    # 5) 更新 manifest + ingest_manifest
    man = L.read_json(os.path.join(vault.store, "manifest.json"), {}) or {}
    man.setdefault("docs", {})[doc_id] = {"name": name, "stored_as": stored,
                                          "source": path}
    with open(os.path.join(vault.store, "manifest.json"), "w",
              encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=1)

    led = L.read_json(os.path.join(vault.store, "ingest_manifest.json"), {}) or {}
    led[doc_id] = {"doc_id": doc_id, "name": name, "source": path,
                   "stored_as": stored, "sha1": digest,
                   "ts": time.strftime("%F %T")}
    with open(os.path.join(vault.store, "ingest_manifest.json"), "w",
              encoding="utf-8") as fh:
        json.dump(led, fh, ensure_ascii=False, indent=1)

    # 6) dedupe 索引
    d = dedupe_index(vault)
    d[digest] = {"doc_id": doc_id, "name": name,
                 "ts": time.strftime("%F %T")}
    save_dedupe(vault, d)

    # 7) 跑 flatten（零网关依赖，生成 engine/text/<doc_id>.txt）
    rc, out = L.run_engine("pi_flatten.py", [], vault, capture=True)
    if rc != 0:
        vault.log("ingest",
                  ["offline flatten rc=%d: %s" % (rc, out.strip()[:200])])

    # 8) stage inbox + tier 标记
    in_inbox = os.path.dirname(path) == os.path.abspath(vault.inbox)
    if in_inbox:
        L.move_into(path, vault.processed)
    try:
        from cenhua_service import tier as TG
        TG.record_tier(vault, doc_id)
    except Exception:
        pass

    if not quiet:
        L.say(f"+ {name} -> offline doc_id {doc_id}  "
              f"(zero-gateway fallback)")
    vault.log("ingest", ["offline added %s -> %s" % (name, doc_id)])
    return "added"


# ---------------------------------------------------------------- ingest_one ---
def ingest_one(vault, path, quiet=False):
    """Returns 'added' | 'dupe' | 'failed'. Never raises.

    Only files that live INSIDE the inbox get moved to .processed/.failed
    staging; explicitly-added files stay where the user put them.
    """
    path = os.path.abspath(path)
    name = os.path.basename(path)
    in_inbox = os.path.dirname(path) == os.path.abspath(vault.inbox)

    # 无网关 → 离线降级（find 可用，LLM 功能继续 fail-closed）
    if not L.chat_ready():
        if os.path.exists(path) and L.is_supported(path):
            if not quiet:
                L.say(f"~ no gateway — offline mode: {name}")
            return _offline_ingest(vault, path, quiet=quiet)
        return "failed"

    def stage(src, dstdir, suffix=""):
        return L.move_into(src, dstdir, suffix) if in_inbox else src

    if not L.is_supported(path):
        L.err(f"! skipped (unsupported extension): {name}")
        stage(path, vault.failed, suffix="_unsupported")
        return "failed"
    try:
        digest = L.sha1(path)
    except OSError as e:
        L.err(f"! unreadable: {name} ({e})")
        return "failed"

    d = dedupe_index(vault)
    if digest in d:
        if not quiet:
            L.say(f"= already in vault: {name} (doc_id={d[digest]['doc_id'][:12]}...)")
        stage(path, vault.processed)
        return "dupe"

    # 邮件（M1b §4.4）：展开成正文 Markdown + 附件部件，逐个走同一闭环。
    # 单部件失败进 .failed/ 不拖垮整封；台账经 restore_provenance 指回
    # 邮件原件（sources/ 归档 .eml/.msg 本体）。
    import m_mail
    if m_mail.is_mail(path):
        try:
            parts, mail_fails = m_mail.expand(vault, path, digest)
        except Exception as e:
            dest = stage(path, vault.failed, suffix="_failed")
            where = f" kept for retry at {dest}" if in_inbox else ""
            L.err(f"x FAILED {name}: mail expand: {e}{where}")
            return "failed"
        if not quiet:
            L.say(f"! {name}: mail -> {len(parts)} part(s)"
                  + (f", {len(mail_fails)} attachment(s) logged only"
                     if mail_fails else ""))
        counts = {"added": 0, "dupe": 0, "failed": 0}
        for part in parts:
            r = ingest_one(vault, part["path"], quiet=quiet)
            if r in ("added", "dupe"):
                # 台账指回邮件原件：按部件自身 sha1 查 dedupe 拿 doc_id
                pd = L.sha1(part["path"])
                did = d.get(pd, {}).get("doc_id", "")
                if did:
                    restore_provenance(vault, did, path, part["name"])
            else:
                # 部件本体在 meta/mail/ 展开目录（不在 inbox，闭环不会
                # 自动暂存）：手动移进 .failed/，失败隔离、可查可重试
                try:
                    L.move_into(part["path"], vault.failed,
                                suffix=f"_{os.path.splitext(name)[0]}_failed")
                except OSError:
                    pass
            counts[r] += 1
        if counts["added"] or counts["dupe"]:
            stage(path, vault.processed)
        else:
            stage(path, vault.failed, suffix="_failed")
        if not quiet:
            L.say(f"~ {name}: +{counts['added']} new, = {counts['dupe']} dupes,"
                  f" x{counts['failed']} failed")
        return ("added" if counts["added"]
                else "dupe" if counts["dupe"] else "failed")

    t0 = time.time()
    if not quiet:
        L.say(f"> ingesting {name} ... (tree index: minutes for long PDFs; "
              f"logs -> {vault.logs})")
    engine_in, ocr_route = m_ocr.preconvert(path, vault, digest)
    if ocr_route:
        L.say(f"! {name}: local OCR ({m_ocr.backend()}) -> "
              f"{os.path.basename(engine_in)}")
    rc, out = L.run_engine("pi_ingest.py", [engine_in], vault, capture=True)
    vault.log("ingest", out.strip().splitlines() or [f"(no output, rc={rc})"])
    m = ADDED_RE.search(out)
    if rc == 0 and m:
        doc_id = m.group(2)
        d[digest] = {"doc_id": doc_id, "name": name, "ts": time.strftime("%F %T")}
        save_dedupe(vault, d)
        if ocr_route:
            restore_provenance(vault, doc_id, path, name)
        # 三层 artifact 标记（M2b 任务8）：tier 写进台账行（引擎不动，摄取层补写）
        try:
            from cenhua_service import tier as TG
            TG.record_tier(vault, doc_id)
        except Exception:
            pass
        stage(path, vault.processed)
        # 全量记账（T5）：树索引成本=摄取固有成本，写 cost-ledger.jsonl
        try:
            from cenhua_service import cost as C
            C.ledger_append(vault, {
                "cmd": "ingest", "doc": name[:200], "calls": 1,
                "tokens_in": 0, "tokens_out": 0, "est_cost": 0.0,
                "currency": "CNY", "priced": False,
            })
        except Exception:
            pass
        if not quiet:
            L.say(f"+ {name} -> doc_id {doc_id}  ({time.time()-t0:.0f}s)")
            L.say(f"  {L.provenance(vault, doc_id, name)}")
        return "added"
    if "= already indexed" in out:
        stage(path, vault.processed)
        if not quiet:
            L.say(f"= already in vault (engine dedupe): {name}")
        return "dupe"
    reason = (out.strip().splitlines() or [f"exit {rc}"])[-1]
    dest = stage(path, vault.failed, suffix="_failed")
    where = f" kept for retry at {dest}" if in_inbox else ""
    L.err(f"x FAILED {name}: {reason}{where}")
    return "failed"


def _rule_summaries(vault):
    """摄取后补规则先行总结（M1b §5.3，零 LLM、离线、秒级）。
    失败只 warn，绝不拖垮摄取闭环。"""
    try:
        from cenhua_service import summaries as S
        docs = L.store_docs(vault)

        def read_text(doc_id):
            p = os.path.join(vault.textdir, doc_id + ".txt")
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    return f.read()
            except OSError:
                return None
        r = S.ensure_all(vault, docs, read_text)
        if r["rule-only"]:
            L.say(f"~ rule summaries: +{r['rule-only']} "
                  f"(zero-LLM; refine: cenhua refine --all --dry-run)")
        # 共现关联同步重建（M1b §5.4，零 LLM；失败只 warn）
        try:
            from cenhua_service import relations as REL
            rel = REL.build(vault)
            L.say(f"~ relations: {rel['edges']} edge(s), {rel['hubs']} hub(s), "
                  f"tier={rel['tier']} (cenhua related <doc>)")
        except Exception as e2:
            L.say(f"~ relations skipped: {e2}")
    except Exception as e:
        L.say(f"~ rule summaries skipped: {e}")


def add(vault, paths, use_inbox=False, flatten=True):
    """Explicit add of files/dirs, or drain the inbox with --inbox."""
    queue = []
    if use_inbox:
        queue += L.pending(vault.inbox)
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            queue += [os.path.join(r, f)
                      for r, _, fs in os.walk(p) for f in sorted(fs)
                      if not any(part.startswith(".") for part in r.split(os.sep))]
        elif os.path.isfile(p):
            queue.append(p)
        else:
            L.err(f"! not found: {p}")

    if not queue:
        L.say("= inbox is empty (drop files into the inbox, then: cenhua add --inbox)")
        return 0

    sync_dedupe(vault)
    L.say(f"~ {len(queue)} file(s) to process in vault '{vault.name}'")
    counts = {"added": 0, "dupe": 0, "failed": 0}
    for path in queue:
        counts[ingest_one(vault, path)] += 1

    if flatten and counts["added"]:
        rc, out = L.run_engine("pi_flatten.py", [], vault, capture=True)
        L.say(f"~ text layer: {out.strip().splitlines()[-1] if out.strip() else 'done'}")
        if rc != 0:
            L.err("! flatten reported a problem — run: cenhua flatten")
        _rule_summaries(vault)
    L.say(f"\ndone: +{counts['added']} new, = {counts['dupe']} dupes, "
          f"x{counts['failed']} failed")
    if counts["added"]:
        L.say(f"next: cenhua find <keyword>   (instant, offline)")
        L.say(f"      cenhua ask --all \"<question>\" --dry-run   (LLM, cost-checked)")
    return 1 if counts["failed"] else 0


def _digest_hint(vault):
    """digest 提示（M3a 任务 6，F10）：只打印一行提示，绝不自动触发执行。"""
    try:
        from cenhua_service import digest as G
        since = G.docs_since_last_digest(vault)
        if since >= G.hint_threshold(vault):
            L.say(f"提示：自上次洞察以来已摄取 {since} 篇，"
                  f"可运行 cenhua digest --dry-run 估价")
    except Exception:
        pass                                    # 提示失败绝不拖垮 watch


def watch(vault, interval=5.0, once=False, idle_rounds=10):
    """Poll the inbox; ingest files whose size has been stable for one round.
    A partially-copied large file therefore never gets grabbed mid-write.
    Files are taken in arrival order (creation time), and files younger than
    one interval are skipped outright (age guard, M1b §4.4).
    `--once` drains and exits; otherwise runs until interrupted (or --rounds)."""
    L.say(f"watching {vault.inbox} every {interval:.0f}s (Ctrl-C to stop)")
    stable, rounds, idle = {}, 0, 0
    while True:
        files = L.pending(vault.inbox, min_age=0 if once else interval)
        ready = []
        for f in files:
            try:
                size = os.path.getsize(f)
            except OSError:
                continue
            if (once or stable.get(f) == size) and size > 0:
                # --once = drain now; otherwise require a size-stable round so a
                # partially-copied large file is never grabbed mid-write.
                ready.append(f)
            stable[f] = size
        for f in list(stable):
            if f not in files and f not in ready:
                stable.pop(f, None)

        if ready:
            idle = 0
            sync_dedupe(vault)
            n = 0
            for f in ready:
                if ingest_one(vault, f) == "added":
                    n += 1
            if n:
                L.run_engine("pi_flatten.py", [], vault, capture=True)
                _rule_summaries(vault)
                L.say(f"+ {n} document(s) indexed and searchable")
                _digest_hint(vault)
        else:
            idle += 1
        rounds += 1
        if once:
            break
        if idle_rounds and idle >= idle_rounds:
            L.say(f"= inbox quiet for {idle} rounds — exiting (relaunch: cenhua watch)")
            break
        time.sleep(interval)
