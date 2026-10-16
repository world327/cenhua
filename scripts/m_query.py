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


def query_cmd(vault, rest):
    """cenhua query "问题" [--include-derived --dry-run --force --top N]。"""
    question, kw = Q.parse_args(rest)
    rc, lines = Q.query_flow(vault, question, **kw)
    for line in lines:
        L.say(line)
    return rc
