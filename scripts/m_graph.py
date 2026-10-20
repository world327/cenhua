#!/usr/bin/env python3
"""m_graph.py — CENHUA 知识图谱 CLI 薄包装（M4a）。

用户命令：
  * `cenhua graph entity <实体>` / `path <A> <B>` / `cluster`
  * `cenhua graph mermaid [<实体>]` / `rebuild`
  * `cenhua graph triples [--doc kw|--all] [--dry-run|--force|--max-cost X]`

全部逻辑在 cenhua_service/graph.py（禁 print）；本模块只打印 + rc
（test_71 白名单：graph_cmd）。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                       # scripts/
sys.path.insert(0, os.path.dirname(_HERE))      # ROOT (cenhua_service/)
import m_lib as L  # noqa: E402
from cenhua_service import graph as G  # noqa: E402


def graph_cmd(vault, rest):
    """cenhua graph <entity|path|cluster|mermaid|rebuild|triples> ...。"""
    res = G.cli(vault, rest)
    for line in res["lines"]:
        L.say(line)
    return res["rc"]
