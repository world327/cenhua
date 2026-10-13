#!/usr/bin/env python3
"""m_cost.py — CENHUA 成本与质量 CLI（M1a）。

用户命令（可 print）：
  * `cenhua cost [--month YYYY-MM]`：按命令分组汇总，摄取成本单列首位
  * `cenhua bench [--corpus]`：跑 fixture（阻断级）/ 用户库（报告模式）

service 逻辑在 cenhua_service/（禁 print）；本模块只做薄包装与输出。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                       # scripts/
sys.path.insert(0, os.path.dirname(_HERE))      # ROOT (cenhua_service/)
import m_lib as L  # noqa: E402
from cenhua_service import cost as C  # noqa: E402
from cenhua_service import bench as B  # noqa: E402


def cost_cmd(vault, month=None):
    """cenhua cost [--month YYYY-MM]。"""
    lines = C.cost_report_lines(vault, month=month)
    for line in lines:
        L.say(line)
    return 0


def bench_cmd(vault, corpus=False):
    """cenhua bench [--corpus]。"""
    lines = B.bench_report_lines(vault, corpus=corpus)
    for line in lines:
        L.say(line)
    return 1 if (not corpus and lines and lines[-1].startswith("  RESULT: FAIL")) else 0
