#!/usr/bin/env python3
"""m_query.py — CENHUA `cenhua query` CLI 薄包装（M2b）。

service 逻辑在 cenhua_service/query.py（禁 print）；
本模块只做打印与 rc（test_71 白名单：M2b = query_cmd）。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                       # scripts/
sys.path.insert(0, os.path.dirname(_HERE))      # ROOT (cenhua_service/)
import m_lib as L  # noqa: E402
from cenhua_service import query as Q  # noqa: E402
from cenhua_service import core as C  # noqa: E402
from cenhua_service import jobs as J  # noqa: E402


def query_cmd(vault, rest):
    """cenhua query（M3a：检索执行进任务通道，run_cli 增量打印）。"""
    question, kw = Q.parse_args(rest)
    handle = J.submit(C.channel_job("query", C.query, vault, question, **kw))
    J.run_cli(handle, L.say)
    try:                                    # 终态 rc；failed/stale 记 1
        return J.job_result(handle).rc
    except Exception:
        return 1
