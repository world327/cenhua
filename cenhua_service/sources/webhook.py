# -*- coding: utf-8 -*-
"""cenhua_service.sources.webhook — Webhook 接收适配器（M5-4）。

被动触发：POST /webhook/{path} → HMAC-SHA256 验签 → 按配置解析 body
→ 写 inbox → 触发 core.ingest。

fetch() 统一接口：webhook 本身增量触发，fetch() 处理积压队列
（离线场景 webhook 先落盘，下次 sync 消费）。

鉴权：X-Cenhua-Signature 头，值 = `sha256=HMAC-SHA256(secret, request.body)`，
fail-closed——无签名/签名错 → 401。

service 纪律：零 print / 零 exit。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from typing import Optional

from fastapi import Request, HTTPException
from fastapi.responses import PlainTextResponse

from cenhua_service.sources import Source, SourceResult, register, _REGISTRY, \
    load_state, save_state


# -------------------------------------------------------------- 工具 ---
def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    """HMAC-SHA256 验证（常数时间比较防时序攻击）。"""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body,
                        hashlib.sha256).hexdigest()
    sig = signature.strip()
    if sig.startswith("sha256="):
        sig = sig[7:].strip()
    return hmac.compare_digest(expected, sig)


def _resolve_webhook_secret(cfg: dict, name: str) -> str:
    """secret 解析优先级：env > sources.yaml > 空（fail-closed）。"""
    env_key = "CENHUA_WEBHOOK_SECRET_" + name.upper().replace("-", "_")
    if os.environ.get(env_key):
        return os.environ[env_key]
    return (cfg.get("secret") or "").strip()


def _sanitize_html(text: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>", "", text)
    text = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", text)
    return text


# -------------------------------------------------------------- Source ---
@register
class WebhookSource(Source):
    _type = "webhook"

    def fetch(self, vault, cfg: dict) -> SourceResult:
        """Webhook 被动触发，fetch() 处理积压队列。"""
        name = cfg.get("name") or "webhook"
        queue_path = os.path.join(vault.meta, "webhook_queue.jsonl")
        if not os.path.isfile(queue_path):
            return SourceResult(source=name, source_type="webhook", rc=0)

        from cenhua_service import core
        added = dupe = failed = 0
        lines = []
        try:
            with open(queue_path, encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        item = json.loads(raw)
                        path = item.get("path")
                        fname = item.get("filename", "?")
                        if path and os.path.isfile(path):
                            res = core.ingest(vault, path)
                            if res.status == "added": added += 1
                            elif res.status == "dupe": dupe += 1
                            else: failed += 1
                            lines.append("+ %s %s" % (res.status, fname))
                        else:
                            failed += 1
                    except Exception as exc:
                        failed += 1
                        lines.append("! queue: %s" % type(exc).__name__)
        except Exception as exc:
            vault.log("sources", ["%s queue 处理失败: %s" %
                                   (name, type(exc).__name__)])
            return SourceResult(source=name, source_type="webhook", rc=1,
                                error=str(exc))
        try:
            os.remove(queue_path)
        except OSError:
            pass
        vault.log("sources", ["%s webhook queue: +%d ~%d !%d"
                               % (name, added, dupe, failed)])
        return SourceResult(source=name, source_type="webhook", rc=0,
                            added=added, dupe=dupe, failed=failed, lines=lines)


# -------------------------------------------------------------- FastAPI 路由 ---
def mount_webhook_routes(app) -> list[str]:
    """把 webhook 路由挂到 FastAPI app（create_app 时调用）。"""

    import m_lib as L
    from cenhua_service import core
    from cenhua_service.sources import parse_sources

    vault = getattr(app.state, "vault", None)
    if vault is None:
        return []
    try:
        import yaml
    except ImportError:
        return []
    sources = [s for s in parse_sources(vault) if s.get("type") == "webhook"]
    if not sources:
        return []

    paths = []
    for cfg in sources:
        name = cfg.get("name") or "webhook"
        path = (cfg.get("path") or name).strip("/")
        full_path = "/webhook/" + path
        secret = _resolve_webhook_secret(cfg, name)
        max_kb = int(cfg.get("max_body_kb") or 256) * 1024
        fmt = (cfg.get("format") or "auto").strip().lower()

        def _make_handler(n, fp, sec, mk, fm, c):
            async def handler(request: Request):
                body = await request.body()
                if len(body) > mk:
                    vault.log("sources",
                              ["%s webhook body too large: %d" % (n, len(body))])
                    raise HTTPException(413, detail="body too large")
                sig = request.headers.get("x-cenhua-signature", "")
                if not sec or not verify_signature(sec, body, sig):
                    vault.log("sources", ["%s webhook sig invalid" % n])
                    raise HTTPException(401, detail="invalid signature")
                try:
                    raw = body.decode("utf-8", errors="replace")
                    if fm == "html":
                        raw = _sanitize_html(raw)
                    elif fm == "auto":
                        try:
                            payload = json.loads(raw)
                            if isinstance(payload, dict):
                                for key in ("text", "message", "content",
                                            "body", "description",
                                            "summary", "title"):
                                    if key in payload and isinstance(
                                            payload[key], str):
                                        raw = payload[key]; break
                        except (json.JSONDecodeError, ValueError):
                            pass
                    ext_map = {"text": ".txt", "html": ".html", "md": ".md"}
                    ext = ext_map.get(fm, ".txt")
                    fname = Source._sanitize_filename(
                        n + "-" + str(int(time.time()))) + ext
                    dest = Source._append_to_inbox(
                        vault, fname, raw.encode("utf-8"))
                    res = core.ingest(vault, dest)
                    vault.log("sources",
                              ["%s webhook: %s %s" % (n, res.status, dest)])
                    state = load_state(vault)
                    st = state.setdefault(n, {"last_seen": [],
                                               "last_success": 0,
                                               "last_error": None})
                    st["last_success"] = int(time.time()); st["last_error"] = None
                    state[n] = st
                    save_state(vault, state)
                    return PlainTextResponse("ok %s %s" % (res.status, fname))
                except HTTPException:
                    raise
                except Exception as exc:
                    vault.log("sources", ["%s webhook err: %s" %
                                          (n, type(exc).__name__)])
                    raise HTTPException(500, detail="ingest failed")
            return handler

        handler = _make_handler(name, full_path, secret, max_kb, fmt, cfg)
        app.add_api_route(full_path, handler, methods=["POST"])
        paths.append(full_path)
        vault.log("sources",
                  ["webhook: %s secret=%s" % (full_path,
                                               "set" if secret else "MISSING")])

    return paths


# 触发注册
assert WebhookSource._type in _REGISTRY, "WebhookSource failed to register"
