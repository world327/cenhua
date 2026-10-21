#!/usr/bin/env python3
"""m_export.py — CENHUA `cenhua export` CLI 薄包装（M4c 任务 13）。

service 逻辑在 cenhua_service/exporter.py（禁 print）；导出纯离线，
直接取 {rc,lines} 打印（test_71 白名单：M4c = export_cmd）。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                       # scripts/
sys.path.insert(0, os.path.dirname(_HERE))      # ROOT (cenhua_service/)
import m_lib as L  # noqa: E402
from cenhua_service import exporter as F  # noqa: E402


def export_cmd(vault, rest):
    """cenhua export（离线即时）。"""
    res = F.flow(vault, rest)
    for line in res["lines"]:
        L.say(line)
    return res["rc"]
