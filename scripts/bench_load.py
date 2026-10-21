#!/usr/bin/env python3
"""CENHUA 性能压测脚本（M5-2）— QPS / 延迟分位数 / 成功率基准。

三种模式：
  find    并发调用 service 层 find（文本层扫描，离线）
  ingest  并发调用 m_ingest.ingest_one（摄取单文件）
  web     并发调用 Web API（/health、/api/v1/find）

用法：
  python3 scripts/bench_load.py --mode find --concurrency 4 --rounds 3
  python3 scripts/bench_load.py --mode web --base http://127.0.0.1:8765 \
          --token xxx --concurrency 8 --rounds 3

输出：每轮 QPS / p50 / p95 / p99 延迟(ms) / 成功率，最后给多轮均值。
预热：每轮前发 --warmup 个请求（默认 5），不计入统计。
"""

import argparse
import concurrent.futures
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import m_lib as L  # noqa: E402


def _percentile(sorted_lat, p):
    if not sorted_lat:
        return 0.0
    k = (len(sorted_lat) - 1) * p
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_lat) else f
    return sorted_lat[f] + (sorted_lat[c] - sorted_lat[f]) * (k - f)


def _run_parallel(fn, n, args):
    """并发执行 fn(args) n 次，返回 (延迟ms列表, 成功数)。

    worker 内部计时（任务开始到结束），避免 as_completed 已完成的计时误差。
    """
    lat = []
    ok = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        futs = [ex.submit(fn, args) for _ in range(n)]
        for f in concurrent.futures.as_completed(futs):
            try:
                lat.append(f.result())
                ok += 1
            except Exception:
                pass
    return lat, ok


# ------------------------------------------------------------ find 模式 ----
def _find_worker(args):
    vault, terms = args
    from cenhua_service import core as C
    t0 = time.perf_counter()
    C.find(vault, terms)
    return (time.perf_counter() - t0) * 1000


def bench_find(vault, terms, concurrency, rounds, warmup):
    print(f"== find 压测（terms={terms}，并发={concurrency}，轮数={rounds}）")
    all_qps, all_p50, all_p95, all_p99 = [], [], [], []
    for r in range(1, rounds + 1):
        if warmup:
            _run_parallel(_find_worker, warmup, (vault, terms))
        t0 = time.perf_counter()
        lat, ok = _run_parallel(_find_worker, concurrency, (vault, terms))
        dt = time.perf_counter() - t0
        qps = concurrency / dt if dt > 0 else 0
        sl = sorted(lat)
        p50, p95, p99 = (_percentile(sl, .5), _percentile(sl, .95),
                         _percentile(sl, .99))
        rate = ok / concurrency * 100
        all_qps.append(qps); all_p50.append(p50)
        all_p95.append(p95); all_p99.append(p99)
        print(f"  轮{r}: QPS={qps:.1f}  p50={p50:.1f}ms  p95={p95:.1f}ms  "
              f"p99={p99:.1f}ms  成功率={rate:.0f}%")
    _summary(all_qps, all_p50, all_p95, all_p99)


# ---------------------------------------------------------- ingest 模式 ----
def _ingest_worker(args):
    vault, path = args
    import m_ingest
    t0 = time.perf_counter()
    m_ingest.ingest_one(vault, path, quiet=True)
    return (time.perf_counter() - t0) * 1000


def bench_ingest(vault, path, concurrency, rounds, warmup):
    print(f"== ingest 压测（file={os.path.basename(path)}，并发={concurrency}）")
    all_qps, all_p50, all_p95, all_p99 = [], [], [], []
    for r in range(1, rounds + 1):
        if warmup:
            _run_parallel(_ingest_worker, warmup, (vault, path))
        t0 = time.perf_counter()
        lat, ok = _run_parallel(_ingest_worker, concurrency, (vault, path))
        dt = time.perf_counter() - t0
        qps = concurrency / dt if dt > 0 else 0
        sl = sorted(lat)
        p50, p95, p99 = (_percentile(sl, .5), _percentile(sl, .95),
                         _percentile(sl, .99))
        rate = ok / concurrency * 100
        all_qps.append(qps); all_p50.append(p50)
        all_p95.append(p95); all_p99.append(p99)
        print(f"  轮{r}: QPS={qps:.1f}  p50={p50:.1f}ms  p95={p95:.1f}ms  "
              f"p99={p99:.1f}ms  成功率={rate:.0f}%")
    _summary(all_qps, all_p50, all_p95, all_p99)


# ------------------------------------------------------------ web 模式 ----
def _web_worker(args):
    base, token, path, method, body = args
    import urllib.request
    data = None
    headers = {}
    if token:
        headers["X-Cenhua-Token"] = token
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers=headers)
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
    return (time.perf_counter() - t0) * 1000


def bench_web(base, token, path, concurrency, rounds, warmup, method="GET", body=None):
    print(f"== web 压测（{path}，并发={concurrency}）")
    all_qps, all_p50, all_p95, all_p99 = [], [], [], []
    for r in range(1, rounds + 1):
        if warmup:
            _run_parallel(_web_worker, warmup, (base, token, path, method, body))
        t0 = time.perf_counter()
        lat, ok = _run_parallel(_web_worker, concurrency, (base, token, path, method, body))
        dt = time.perf_counter() - t0
        qps = concurrency / dt if dt > 0 else 0
        sl = sorted(lat)
        p50, p95, p99 = (_percentile(sl, .5), _percentile(sl, .95),
                         _percentile(sl, .99))
        rate = ok / concurrency * 100
        all_qps.append(qps); all_p50.append(p50)
        all_p95.append(p95); all_p99.append(p99)
        print(f"  轮{r}: QPS={qps:.1f}  p50={p50:.1f}ms  p95={p95:.1f}ms  "
              f"p99={p99:.1f}ms  成功率={rate:.0f}%")
    _summary(all_qps, all_p50, all_p95, all_p99)


def _summary(qps, p50, p95, p99):
    print(f"  均值: QPS={statistics.mean(qps):.1f}  "
          f"p50={statistics.mean(p50):.1f}ms  "
          f"p95={statistics.mean(p95):.1f}ms  "
          f"p99={statistics.mean(p99):.1f}ms")


def main():
    ap = argparse.ArgumentParser(prog="bench_load", description=__doc__)
    ap.add_argument("--mode", choices=["find", "ingest", "web"], required=True)
    ap.add_argument("--vault", default=None)
    ap.add_argument("--terms", default="合同 违约金")
    ap.add_argument("--file", default=None, help="ingest 模式的测试文件")
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--token", default="")
    ap.add_argument("--path", default="/health", help="web 模式的 API 路径")
    ap.add_argument("--method", default="GET", help="HTTP 方法（GET/POST）")
    ap.add_argument("--body", default=None, help="POST JSON body（如 '{\"terms\":[\"合同\"]}'）")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=5)
    args = ap.parse_args()

    vault = L.Vault(args.vault) if args.vault else None
    if args.mode == "find":
        if vault is None:
            vault = L.Vault()
        bench_find(vault, args.terms.split(), args.concurrency,
                   args.rounds, args.warmup)
    elif args.mode == "ingest":
        if vault is None:
            vault = L.Vault()
        if not args.file or not os.path.isfile(args.file):
            sys.exit("ingest 模式需要 --file <存在的文件>")
        bench_ingest(vault, args.file, args.concurrency,
                     args.rounds, args.warmup)
    elif args.mode == "web":
        body = None
        if args.body:
            import json as _json
            body = _json.loads(args.body)
        bench_web(args.base, args.token, args.path, args.concurrency,
                  args.rounds, args.warmup, method=args.method, body=body)


if __name__ == "__main__":
    main()
