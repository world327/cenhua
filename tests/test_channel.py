#!/usr/bin/env python3
"""test_channel.py — M3a 任务 4：长任务统一走任务通道 + CLI 轮询打印。

覆盖：core.channel_job 适配（lines/cost 映射、进度 0.05→1.0、异常透传）、
jobs.run_cli（增量逐行打印、终态、超时、心跳）、core.ask 的 confirm 回调
语义（拒绝/异常 -> rc=1 零花费、零引擎调用）、ask_estimate 前置段
（scope 缺失 rc=2、成功含 calls 与 [cost] 行）。纯离线零网关。
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_TEST_HOME = tempfile.mkdtemp(prefix="cenhua-chan-")
os.environ["CENHUA_HOME"] = _TEST_HOME
os.environ["CENHUA_CONFIG_DIR"] = os.path.join(_TEST_HOME, "config-dir")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import m_lib as L  # noqa: E402
import m_ask  # noqa: E402
from cenhua_service import core  # noqa: E402
from cenhua_service import jobs as J  # noqa: E402

DOC_A = ("=== PAGE 1 ===\n华兴科技采购合同，金额 128.5万元。\n"
         "=== PAGE 2 ===\n违约罚金按日 0.05% 计，penalty clause 见第 7.2 条。\n")


class _FakeResult(object):
    """channel_job 适配面假结果：只要求 lines/cost 字段。"""

    def __init__(self, lines, cost):
        self.lines = lines
        self.cost = cost


class ChannelJobTest(unittest.TestCase):
    def setUp(self):
        J.reset()

    def test_01_lines_emitted_and_cost_mapped(self):
        spec = core.channel_job(
            "ask", lambda: _FakeResult(["a", "b"], {"calls": 3, "docs": 3,
                                                    "est_cost": 0.42,
                                                    "currency": "CNY"}))
        h = J.submit(spec)
        st = J.wait(h, poll=0.01, timeout=10)
        self.assertEqual(st.state, J.DONE)
        self.assertEqual(st.chunks, ["a", "b"])
        self.assertEqual(st.cost["calls"], 3)
        self.assertAlmostEqual(st.cost["cost"], 0.42)
        self.assertEqual(st.cost["currency"], "CNY")
        self.assertEqual(st.progress, 1.0)

    def test_02_no_cost_and_progress_started(self):
        def _fn():
            return _FakeResult(["x"], None)

        spec = core.channel_job("query", _fn)
        h = J.submit(spec)
        st = J.wait(h, poll=0.01, timeout=10)
        self.assertEqual(st.state, J.DONE)
        self.assertEqual(st.cost["calls"], 0)
        self.assertEqual(st.progress, 1.0)

    def test_03_exception_marks_failed(self):
        def _boom():
            raise RuntimeError("engine exploded")

        h = J.submit(core.channel_job("ask", _boom))
        st = J.wait(h, poll=0.01, timeout=10)
        self.assertEqual(st.state, J.FAILED)
        self.assertIn("engine exploded", st.error)
        with self.assertRaises(J.JobFailed):
            J.job_result(h)


class RunCliTest(unittest.TestCase):
    def setUp(self):
        J.reset()

    def _spec(self):
        def _body(rt):
            rt.emit("l1\nl2")
            rt.progress(0.5)
            rt.emit("l3")
            rt.progress(1.0)
            return "ok"

        return J.JobSpec(kind="ask", run=_body)

    def test_04_lines_before_progress(self):
        import time as _t

        def _body(rt):
            rt.emit("l1\nl2")
            rt.progress(0.5)
            _t.sleep(0.15)                   # 留出 RUNNING 窗口给轮询
            rt.emit("l3")
            return "ok"

        printed = []
        h = J.submit(J.JobSpec(kind="ask", run=_body))
        st = J.run_cli(h, printed.append, poll=0.01, timeout=10)
        self.assertEqual(st.state, J.DONE)
        self.assertEqual(printed[:2], ["l1", "l2"])
        self.assertTrue(any("[进度]" in p for p in printed), printed)
        self.assertIn("l3", printed)

    def test_05_heartbeat_when_idle(self):
        import threading as _th

        def _body(rt):
            _th.Event().wait(0.4)           # 静默期 > heartbeat
            rt.emit("late")
            return "ok"

        printed = []
        h = J.submit(J.JobSpec(kind="digest", run=_body))
        st = J.run_cli(h, printed.append, poll=0.01, timeout=10,
                       heartbeat=0.05)
        self.assertEqual(st.state, J.DONE)
        self.assertIn("late", printed)
        self.assertTrue(any("[心跳]" in p for p in printed), printed)


class AskGateTest(unittest.TestCase):
    """core.ask 闸门与 confirm 语义（无网关、假引擎，零花费）。"""

    @classmethod
    def setUpClass(cls):
        import subprocess
        for k in ("PI_BASE", "PI_KEY"):
            os.environ.pop(k, None)
        r = subprocess.run([os.path.join(ROOT, "bin", "cenhua"), "init",
                            "ch", "--yes"], capture_output=True, text=True,
                           env=dict(os.environ, CENHUA_HOME=_TEST_HOME),
                           timeout=120)
        assert r.returncode == 0, r.stderr
        cls.vault = L.Vault("ch")
        os.makedirs(cls.vault.textdir, exist_ok=True)
        os.makedirs(cls.vault.store, exist_ok=True)
        with open(os.path.join(cls.vault.textdir, "pi-x1.txt"),
                  "w", encoding="utf-8") as f:
            f.write(DOC_A)
        with open(os.path.join(cls.vault.store, "ingest_manifest.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"pi-x1": {"name": "合同A.pdf", "tier": "primary",
                                 "ts": "2026-10-16 10:00:00"}}, f)

    def test_06_ask_estimate_ok_with_calls_and_cost_lines(self):
        res = core.ask_estimate(self.vault, "罚金多少", doc="合同")
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.cost["calls"], 1)
        self.assertTrue(any(l.startswith("[cost] documents  : 1")
                            for l in res.lines))
        self.assertTrue(any(l.startswith("[cost] LLM calls  : ~1")
                            for l in res.lines))

    def test_07_ask_estimate_scope_required(self):
        res = core.ask_estimate(self.vault, "罚金多少")
        self.assertEqual(res.rc, 2)
        self.assertIn("scope required", res.error)

    def setUp(self):
        J.reset()
        # confirm 在 chat_ready 闸门之后：装个假网关才能走到确认环节
        self._env = {k: os.environ.get(k)
                     for k in ("PI_BASE", "PI_KEY")}
        os.environ["PI_BASE"] = "http://gateway.invalid/v1"
        os.environ["PI_KEY"] = "sk-test"

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_08_confirm_refused_rc1_zero_calls(self):
        calls = {"n": 0}
        orig = L.run_engine

        def _spy(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)

        L.run_engine = _spy
        try:
            res = core.ask(self.vault, "罚金多少", doc="合同",
                           confirm=lambda n: False)
        finally:
            L.run_engine = orig
        self.assertEqual(res.rc, 1)
        self.assertIn("aborted (nothing spent)", res.lines)
        self.assertEqual(calls["n"], 0)         # 零引擎调用 = 零花费
        self.assertEqual(calls["n"], 0)

    def test_09_confirm_exception_counts_as_refused(self):
        def _boom(n):
            raise IOError("stdin gone")

        res = core.ask(self.vault, "罚金多少", doc="合同", confirm=_boom)
        self.assertEqual(res.rc, 1)

    def test_10_dry_run_short_circuit(self):
        res = core.ask(self.vault, "罚金多少", doc="合同", dry_run=True)
        self.assertEqual(res.rc, 0)
        self.assertIn("(dry run \u2014 nothing was sent)", res.lines)

    def test_11_ask_via_channel_captures_pre_lines(self):
        """channel_job 包 core.ask：拒绝路径 chunks = 完整前置段 + 放弃行。"""
        h = J.submit(core.channel_job(
            "ask", core.ask, self.vault, "罚金多少", doc="合同",
            confirm=lambda n: False))
        printed = []
        st = J.run_cli(h, printed.append, poll=0.01, timeout=10)
        self.assertEqual(st.state, J.DONE)
        self.assertEqual(st.cost["calls"], 1)   # est 映射进通道 cost
        self.assertIn("[cost] documents  : 1", printed)
        self.assertIn("aborted (nothing spent)", printed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
