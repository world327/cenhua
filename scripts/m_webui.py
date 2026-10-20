#!/usr/bin/env python3
"""m_webui.py — CENHUA 本地 Web UI / 局域网 API 入口（M3b）。

薄包装：argparse + app.serve()（契约 §3.6；test_71 CLI 入口口径）。
host/port/token/限流/超时全部 config 驱动，见 cenhua_service/webui/app.py。

USAGE
  python3 scripts/m_webui.py [--vault NAME] [--host H] [--port P]

  host/port: CENHUA_WEB_HOST/PORT env > vault.yaml web_host/web_port
             > 127.0.0.1:8765（局域网开放 = --host 0.0.0.0，须先配 token）
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                       # scripts/
sys.path.insert(0, os.path.dirname(_HERE))      # ROOT (cenhua_service/)
import m_lib as L  # noqa: E402


def serve_cmd(vault, host=None, port=None):
    """cenhua web 的实现体（薄包装：提示 + serve）。"""
    from cenhua_service.webui import app as W
    from cenhua_service.webui import security
    if not security.resolve_token(vault):
        L.say("! api_token 未配置：所有 API/页面请求将被 fail-closed 拒绝。")
        L.say("  export CENHUA_API_TOKEN=... 或 cenhua config api_token ...")
    host = host or W.resolve_host(vault)
    port = port or W.resolve_port(vault)
    L.say(f"CENHUA web : http://{host}:{port}  (vault: {vault.name})")
    L.say("  API      : /api/v1/*  (X-Cenhua-Token header)")
    W.serve(vault, host=host, port=port)
    return 0


def main():
    ap = argparse.ArgumentParser(prog="cenhua-web", add_help=True,
                                 description=__doc__.split("USAGE")[0])
    ap.add_argument("--vault", default=None, help="vault name")
    ap.add_argument("--host", default=None, help="bind host (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=None, help="bind port (8765)")
    args = ap.parse_args()
    return serve_cmd(L.Vault(args.vault), host=args.host, port=args.port)


if __name__ == "__main__":
    sys.exit(main())
