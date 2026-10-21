# -*- coding: utf-8 -*-
"""Web 应用组装（M3b 任务 1/8/11）— 契约 §3.6。

fastapi/uvicorn/jinja2 全部延迟导入：core 层零污染，
`import cenhua_service` 在无 web 依赖的机器上照常工作。

配置驱动（零硬编码）：
  host  : CENHUA_WEB_HOST   env > vault.yaml web_host   > 127.0.0.1
  port  : CENHUA_WEB_PORT   env > vault.yaml web_port   > 8765
  心跳  : CENHUA_WEB_HEARTBEAT_S > vault.yaml web_heartbeat_s > 10
  保活  : CENHUA_WEB_KEEPALIVE_S > vault.yaml web_keepalive_s > 120
  限流  : CENHUA_WEB_RATE_CALLS/WINDOW_S > vault.yaml web_rate_calls/
          web_rate_window_s > 30 次 / 60 秒
"""
import os
import time
import uuid

from cenhua_service.webui import security

HOST_ENV, PORT_ENV = "CENHUA_WEB_HOST", "CENHUA_WEB_PORT"
DEFAULT_HOST, DEFAULT_PORT = "127.0.0.1", 8765


def _version():
    """CENHUA 版本号（m_lib.VERSION，延迟导入避免循环依赖）。"""
    try:
        import m_lib as L
        return L.VERSION
    except Exception:
        return "unknown"


def web_setting(vault, key, env=None, default=""):
    """env > vault.yaml > default（与 Vault.setting 同序）。"""
    if env and os.environ.get(env):
        return os.environ[env]
    return vault.cfg().get(key, default)


def resolve_host(vault):
    return web_setting(vault, "web_host", HOST_ENV, DEFAULT_HOST) or DEFAULT_HOST


def resolve_port(vault):
    try:
        return int(web_setting(vault, "web_port", PORT_ENV, DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


def _int_setting(vault, key, env, default):
    try:
        return int(web_setting(vault, key, env, default))
    except ValueError:
        return int(default)


def _float_setting(vault, key, env, default):
    try:
        return float(web_setting(vault, key, env, default))
    except ValueError:
        return float(default)


def create_app(vault, rate=None):
    """组装 FastAPI：rid 日志中间件 -> api router -> pages。

    token 走配置（CENHUA_API_TOKEN env > vault.yaml api_token，fail-closed）；
    rate=(calls, window_s) 仅供单测覆盖限流参数。
    """
    from fastapi import FastAPI, Request
    from fastapi.staticfiles import StaticFiles

    from cenhua_service.webui.api import build_router
    from cenhua_service.webui.pages import build_pages

    app = FastAPI(title="CENHUA web", docs_url=None, redoc_url=None)

    # 运行期状态（api.py / pages.py 经 request.app.state 取用）
    app.state.vault = vault
    calls = rate[0] if rate else _int_setting(
        vault, "web_rate_calls", "CENHUA_WEB_RATE_CALLS", 30)
    window = rate[1] if rate and len(rate) > 1 else _int_setting(
        vault, "web_rate_window_s", "CENHUA_WEB_RATE_WINDOW_S", 60)
    app.state.limiter = security.RateLimiter(max_calls=calls, window_s=window)
    app.state.heartbeat_s = _float_setting(
        vault, "web_heartbeat_s", "CENHUA_WEB_HEARTBEAT_S", 10.0)

    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir),
                  name="static")

    # rid 中间件：全链路追踪 + 结构化访问日志（logs/web-YYYYMM.log）
    @app.middleware("http")
    async def rid_log(request: Request, call_next):
        rid = request.headers.get("x-cenhua-rid") or uuid.uuid4().hex[:8]
        t0 = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            vault.log("web", "%s ! %s %s 500 %.0fms" % (
                rid, request.method, request.url.path,
                (time.monotonic() - t0) * 1000))
            raise
        vault.log("web", "%s %s %s %d %.0fms" % (
            rid, request.method, request.url.path, response.status_code,
            (time.monotonic() - t0) * 1000))
        response.headers["X-Cenhua-Rid"] = rid
        return response

    app.include_router(build_router(vault))
    app.include_router(build_pages(vault))

    # ---- /health 探活端点（M5-1）：容器/看门狗探活用，不经过 token 鉴权 ----
    @app.get("/health")
    def health():
        import shutil as _sh
        from cenhua_service import core as C
        st = C.stats(vault)
        disk = _sh.disk_usage(vault.root) if os.path.isdir(vault.root) else None
        return {
            "status": "ok",
            "version": _version(),
            "vault": vault.name,
            "docs": st.docs,
            "gateway_ready": st.gateway_ready,
            "disk_free_bytes": disk.free if disk else None,
            "ts": time.strftime("%F %T"),
        }

    return app


def serve(vault, host=None, port=None):
    """uvicorn.run 薄调用（scripts/m_webui.py 唯一消费方）。

    timeout_keep_alive 走配置（任务 11，F8：无 Nginx 依赖）。
    长任务不占 HTTP 连接（任务通道 + SSE），故无需超长请求超时。
    """
    import uvicorn

    host = host or resolve_host(vault)
    port = port or resolve_port(vault)
    keepalive = _int_setting(vault, "web_keepalive_s",
                             "CENHUA_WEB_KEEPALIVE_S", 120)
    uvicorn.run(create_app(vault), host=host, port=port,
                timeout_keep_alive=keepalive, access_log=False)
