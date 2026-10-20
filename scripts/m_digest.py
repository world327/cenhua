#!/usr/bin/env python3
"""m_digest.py — CENHUA `cenhua digest` CLI 薄包装（M3a 任务 9）。

service 逻辑在 cenhua_service/digest.py（禁 print）；
本模块只做参数解析 + 任务通道提交与轮询打印
（test_71 白名单：M3a = digest_cmd）。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                       # scripts/
sys.path.insert(0, os.path.dirname(_HERE))      # ROOT (cenhua_service/)
import m_lib as L  # noqa: E402
from cenhua_service import digest as G  # noqa: E402
from cenhua_service import core as C  # noqa: E402
from cenhua_service import jobs as J  # noqa: E402


def digest_cmd(vault, rest):
    """cenhua digest（M3a：长任务走任务通道，run_cli 增量打印）。"""
    handle = J.submit(C.channel_job("digest", G.digest_flow, vault,
                                    **G.parse_cli(rest)))
    J.run_cli(handle, L.say)
    try:                                    # 终态 rc；failed/stale 记 1
        return J.job_result(handle).rc
    except Exception:
        return 1
