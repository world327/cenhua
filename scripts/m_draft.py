#!/usr/bin/env python3
"""m_draft.py — CENHUA `cenhua draft` CLI 薄包装（M4a 任务 17）。

service 逻辑在 cenhua_service/draft.py（禁 print）；本模块只做
「辅助动作直接取 {rc,lines}」/「生成走任务通道」两种打印
（test_71 白名单：M4a = draft_cmd）。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                       # scripts/
sys.path.insert(0, os.path.dirname(_HERE))      # ROOT (cenhua_service/)
import m_lib as L  # noqa: E402
from cenhua_service import draft as F  # noqa: E402
from cenhua_service import core as C  # noqa: E402
from cenhua_service import jobs as J  # noqa: E402


def _aux(vault, rest):
    """离线辅助动作（list/verify/diff/restore）：直接打印并返回 rc。"""
    res = F.flow(vault, rest)
    for line in res["lines"]:
        L.say(line)
    return res["rc"]


def _rc(handle):
    """终态 rc；failed/stale 记 1。"""
    try:
        return J.job_result(handle).rc
    except Exception:
        return 1


def draft_cmd(vault, rest):
    """cenhua draft（生成走任务通道；list/verify/diff/restore 即时返回）。"""
    if not F.needs_channel(rest):
        return _aux(vault, rest)
    spec = C.channel_job("draft", F.draft_flow, vault, **F.gen_kwargs(rest))
    handle = J.submit(spec)
    J.run_cli(handle, L.say)
    return _rc(handle)
