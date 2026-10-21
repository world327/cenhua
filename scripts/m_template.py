#!/usr/bin/env python3
"""m_template.py — CENHUA `cenhua template` CLI 薄包装（M4c 任务 12）。

service 逻辑在 cenhua_service/templates.py（禁 print）；本模块只做
「离线动作直接取 {rc,lines}」/「生成走任务通道」两种打印
（test_71 白名单：M4c = template_cmd）。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                       # scripts/
sys.path.insert(0, os.path.dirname(_HERE))      # ROOT (cenhua_service/)
import m_lib as L  # noqa: E402
from cenhua_service import templates as F  # noqa: E402
from cenhua_service import core as C  # noqa: E402
from cenhua_service import jobs as J  # noqa: E402


def _aux(vault, rest):
    """离线动作（list/show/add）：直接打印并返回 rc。"""
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


def template_cmd(vault, rest):
    """cenhua template（生成走任务通道；list/show/add 即时返回）。"""
    if not F.needs_channel(rest):
        return _aux(vault, rest)
    spec = C.channel_job("template", F.template_flow, vault,
                         **F.gen_kwargs(rest))
    handle = J.submit(spec)
    J.run_cli(handle, L.say)
    return _rc(handle)
