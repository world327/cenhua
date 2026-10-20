# -*- coding: utf-8 -*-
"""鉴权与限流（M3b 任务 7-8）。

单用户 token + fail-closed（T8.2：不做行级过滤、不做用户映射、无租户残肢）。
零第三方依赖，纯标准库，可脱离 fastapi 单测。
"""
import hmac
import threading
import time

TOKEN_ENV = "CENHUA_API_TOKEN"     # 环境变量名（优先级高于 vault.yaml）
TOKEN_KEY = "api_token"            # vault.yaml 键


def resolve_token(vault):
    """token 解析顺序：ENV > vault.yaml `api_token` > 空串（= 未配置）。"""
    return vault.setting(TOKEN_KEY, TOKEN_ENV)


def check_token(vault, provided):
    """fail-closed 双拒：服务端未配置 token 拒绝一切；比对常数时间。"""
    secret = resolve_token(vault)
    if not secret:                       # 未配置 = 全部拒绝（fail-closed）
        return False
    if not provided:                     # 空 token 也拒
        return False
    return hmac.compare_digest(secret, provided)


class RateLimiter:
    """滑动窗口限流（与 OCR 服务同款模式）：window_s 内最多 max_calls 次。"""

    def __init__(self, max_calls=30, window_s=60.0):
        self.max_calls = int(max_calls)
        self.window_s = float(window_s)
        self._hits = {}                  # key -> [ts, ...]
        self._lock = threading.Lock()

    def allow(self, key, now=None):
        """True=放行；False=超限（调用方回 429）。"""
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_s
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(hits) >= self.max_calls:
                self._hits[key] = hits   # 顺手修剪，防无界增长
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

    def retry_after(self, key, now=None):
        """距离窗口内最早命中过期的秒数（429 的 Retry-After）。"""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.get(key, [])
        if not hits:
            return 1
        return max(1, int(self.window_s - (now - hits[0])) + 1)
