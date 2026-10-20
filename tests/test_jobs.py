#!/usr/bin/env python3
"""test_jobs.py — M3a 任务通道离线单测（契约 service-contract.md §3.5）。

覆盖：submit/job_status/job_result 三接口、增量 chunks 协议（cursor 语义）、
进度单调、cost 累计与混合货币标注、失败隔离、wait 轮询/超时、
ADR-001 stale 语义（未知 handle 恒 aborted/stale 不抛错）。
纯离线零 LLM 零 vault。
"""

import os
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from cenhua_service import jobs  # noqa: E402


def _drain(handle):
    """按游标拉全量 chunks（模拟 CLI 轮询消费）。"""
    out, cur = [], 0
    while True:
        st = jobs.job_status(handle, cur)
        out.extend(st.chunks)
        cur = st.cursor
        if st.state in jobs.TERMINAL:
            return out, st


class JobsTest(unittest.TestCase):
    def setUp(self):
        jobs.reset()

    # ------------------------------------------------------------ 成功路径 ----
    def test_01_submit_done_result(self):
        def run(rt):
            rt.emit("a")
            rt.progress(0.5)
            rt.add_cost(calls=2, cost=0.1, currency="CNY")
            rt.emit("b")
            return {"answer": "ok"}
        h = jobs.submit(jobs.JobSpec(kind="ask", run=run))
        st = jobs.wait(h, poll=0.01, timeout=5)
        self.assertEqual(st.state, jobs.DONE)
        self.assertEqual(jobs.job_result(h), {"answer": "ok"})
        # 终态进度补满 1.0
        self.assertEqual(jobs.job_status(h).progress, 1.0)

    def test_02_incremental_chunks_cursor(self):
        def run(rt):
            for i in range(5):
                rt.emit("c%d" % i)
            return 1
        h = jobs.submit(jobs.JobSpec(kind="digest", run=run))
        jobs.wait(h, poll=0.01, timeout=5)
        st0 = jobs.job_status(h, 0)
        self.assertEqual(st0.chunks, ["c0", "c1", "c2", "c3", "c4"])
        self.assertEqual(st0.cursor, 5)
        # cursor 之后只回增量
        st2 = jobs.job_status(h, 2)
        self.assertEqual(st2.chunks, ["c2", "c3", "c4"])
        st5 = jobs.job_status(h, 5)
        self.assertEqual(st5.chunks, [])
        self.assertEqual(st5.cursor, 5)

    def test_03_progress_monotonic_clamped(self):
        rt = jobs.JobRuntime()
        rt.progress(0.6)
        rt.progress(0.3)          # 回退忽略
        self.assertEqual(rt.progress_value, 0.6)
        rt.progress(1.5)          # 越界钳到 1.0
        self.assertEqual(rt.progress_value, 1.0)
        rt.progress(-2)
        self.assertEqual(rt.progress_value, 1.0)

    def test_04_cost_accumulate(self):
        rt = jobs.JobRuntime()
        rt.add_cost(calls=1, cost=0.5, currency="CNY")
        rt.add_cost(calls=2, cost=0.25, currency="CNY")
        self.assertEqual(rt.cost["calls"], 3)
        self.assertAlmostEqual(rt.cost["cost"], 0.75)
        self.assertEqual(rt.cost["currency"], "CNY")
        self.assertNotIn("note", rt.cost)
        # 混合货币：不折算，只标注（与 cost.py F9 口径一致）
        rt.add_cost(calls=1, cost=1.0, currency="USD")
        self.assertEqual(rt.cost.get("note"), "混合货币，未折算")

    # ------------------------------------------------------------ 失败隔离 ----
    def test_05_failure_captured(self):
        def boom(rt):
            raise ValueError("网关不可达")
        h = jobs.submit(jobs.JobSpec(kind="query", run=boom))
        st = jobs.wait(h, poll=0.01, timeout=5)
        self.assertEqual(st.state, jobs.FAILED)
        self.assertIn("ValueError", st.error)
        self.assertIn("网关不可达", st.error)
        with self.assertRaises(jobs.JobFailed):
            jobs.job_result(h)

    def test_06_not_done_raises(self):
        ev = threading.Event()
        h = jobs.submit(jobs.JobSpec(kind="ask", run=lambda rt: ev.wait(5)))
        # 未终态取结果 → JobNotDone（竞态：极少数已 queued 前读到 running 也算未终态）
        try:
            jobs.job_result(h)
            self.fail("未终态不应返回结果")
        except jobs.JobNotDone:
            pass
        ev.set()

    # ------------------------------------------------------------ ADR-001 ----
    def test_07_stale_handle_no_raise(self):
        ghost = jobs.JobHandle(job_id="ffffffffffff", kind="ask")
        st = jobs.job_status(ghost, cursor=7)
        self.assertEqual(st.state, jobs.ABORTED)
        self.assertEqual(st.reason, "stale")
        self.assertEqual(st.cursor, 7)       # cursor 原样回传，客户端续拉不重置
        self.assertEqual(st.chunks, [])
        with self.assertRaises(jobs.JobStale):
            jobs.job_result(ghost)

    def test_08_reset_makes_running_job_stale(self):
        """模拟进程重启：reset 后旧 handle 立即 stale（ADR-001）。"""
        h = jobs.submit(jobs.JobSpec(kind="digest",
                                     run=lambda rt: (time.sleep(0.05), 42)[1]))
        self.assertNotEqual(jobs.job_status(h).state, jobs.ABORTED)
        jobs.reset()
        st = jobs.job_status(h)
        self.assertEqual(st.state, jobs.ABORTED)
        self.assertEqual(st.reason, "stale")

    # ------------------------------------------------------------ wait ----
    def test_09_wait_timeout_returns_running(self):
        ev = threading.Event()
        h = jobs.submit(jobs.JobSpec(kind="ask", run=lambda rt: ev.wait(5)))
        st = jobs.wait(h, poll=0.01, timeout=0.1)
        self.assertIn(st.state, (jobs.QUEUED, jobs.RUNNING))
        ev.set()

    def test_10_handle_roundtrip(self):
        h = jobs.JobHandle(job_id="abc123def456", kind="digest")
        self.assertEqual(h.to_dict()["job_id"], "abc123def456")
        h2 = jobs.JobHandle.from_dict(h.to_dict())
        self.assertEqual(h2, h)


if __name__ == "__main__":
    unittest.main(verbosity=2)
