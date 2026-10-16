#!/usr/bin/env python3
"""m_weave.py — CENHUA 编织层 CLI 薄包装（M1b）。

用户命令（可 print）：
  * `cenhua refine [--all --dry-run | --drain [--force]]`
  * `cenhua related <doc>`
  * `cenhua link <docA> <docB> | --ban <实体A> <实体B>`
  * `cenhua hub`
  * `cenhua weave rebuild`（重建 relations.jsonl）

service 逻辑在 cenhua_service/{summaries,refine,relations}.py（禁 print）；
本模块只做参数解析、打印与 rc（test_71 白名单：refine/related）。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                       # scripts/
sys.path.insert(0, os.path.dirname(_HERE))      # ROOT (cenhua_service/)
import m_lib as L  # noqa: E402
from cenhua_service import refine as R  # noqa: E402


def refine_cmd(vault, rest):
    """cenhua refine [--all --dry-run|--drain [--force]]。"""
    from cenhua_service import relations as REL
    if "--all" in rest and "--dry-run" not in rest and "--drain" not in rest:
        REL.ensure_summaries(vault)     # --all 单独用 = 规则层补齐（零 LLM）
    rc, lines = R.refine_flow(vault, "--all" in rest, "--dry-run" in rest,
                              "--drain" in rest, "--force" in rest)
    for line in lines:
        L.say(line)
    return rc


def _build_hint(vault):
    """relations 为空/过期时先增量重建（秒级、零 LLM）。"""
    from cenhua_service import relations as REL
    if not os.path.isfile(REL.rel_path(vault)):
        return REL.build(vault)
    return None


def _picks(vault, rest, want, usage):
    """位置参数逐个解析成 (doc_id, name)；数量不足/不存在则终止。"""
    pos = [a for a in rest if not a.startswith("-")]
    if len(pos) < want:
        L.die(f"usage: {usage}")
    out = []
    for kw in pos[:want]:
        picked = L.resolve_docs(vault, kw, limit=1)
        if not picked:
            L.die(f"no doc matches '{kw}' (see: cenhua list)")
        out.append(picked[0])
    return out


def related_cmd(vault, rest):
    """cenhua related <doc>。空结果明示"无显著关联（正常）"。"""
    from cenhua_service import relations as REL
    (doc_id, name), = _picks(vault, rest, 1, "cenhua related <doc>")
    _build_hint(vault)
    for line in REL.related_lines(vault, doc_id, name):
        L.say(line)
    return 0


def link_cmd(vault, rest):
    """cenhua link <docA> <docB> | cenhua link --ban <实体A> <实体B>。"""
    from cenhua_service import relations as REL
    if "--ban" in rest:
        args = [a for a in rest[rest.index("--ban") + 1:]
                if not a.startswith("-")]
        if len(args) < 2:
            L.die("usage: cenhua link --ban <entityA> <entityB>")
        ok = REL.add_ban(vault, args[0], args[1])
        L.say(f"{'+ banned' if ok else '= already banned'}: "
              f"{args[0]} <-> {args[1]}（永久压制，重建也不复活）")
        return 0
    (ida, na), (idb, nb) = _picks(
        vault, rest, 2, "cenhua link <docA> <docB>  (weight 0.8, manual)")
    REL.manual_link(vault, ida, idb)
    L.say(f"+ linked {na} <-> {nb}  (type=cite, weight=0.8)")
    return 0


def hub_cmd(vault, rest):
    """cenhua hub：列枢纽实体 + 当前档位与 N（人工复核入口）。"""
    from cenhua_service import relations as REL
    REL.ensure_summaries(vault)
    ent_docs, _, _, n = REL.entity_index(vault)
    prof = REL.profile(n)
    df = {e: len(d) for e, d in ent_docs.items()}
    hubs = REL.hub_entities(df, n, prof["hub_df_ratio"])
    L.say(f"corpus: N={n} docs  tier={prof['tier']} "
          f"(threshold CENHUA_SMALL_CORPUS_N={REL.small_corpus_n()})")
    L.say(f"hub rule: df > N×{prof['hub_df_ratio']:g}  "
          f"| co-occurrence floor >= {prof['floor']}  "
          f"| nPMI {'+Laplace' if prof['laplace'] else 'raw'}")
    if not hubs:
        L.say("hubs: (none) — 无实体超过枢纽阈值")
        return 0
    L.say(f"hubs: {len(hubs)} entity(ies) suppressed from co-occurrence edges")
    for e in hubs[:20]:
        L.say(f"  df={df[e]:>4}  {e}")
    if len(hubs) > 20:
        L.say(f"  ... {len(hubs) - 20} more")
    return 0


def weave_cmd(vault, rest):
    """cenhua weave rebuild：全量重建关联（个人库秒级）。"""
    from cenhua_service import relations as REL
    if rest and rest[0] == "rebuild":
        r = REL.build(vault)
        L.say(f"+ relations rebuilt: {r['edges']} edge(s) from {r['docs']} "
              f"doc(s), {r['entities']} entities, {r['hubs']} hub(s), "
              f"tier={r['tier']}")
        return 0
    L.die("usage: cenhua weave rebuild")
