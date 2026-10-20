"""任务通道（M3a · 契约见 docs/service-contract.md §3.5）。

ADR-001（docs/architecture.md §2.20，2026-10-16 拍板）：持久化边界 =
**重启后标废**。任务通道纯内存态（进程内 job 表 + daemon 线程执行），
不做任何磁盘/sqlite 持久化；进程重启后旧 handle 查询一律返回
aborted(stale) 终态，不抛错、不续跑。

纪律：service 层禁 print/exit（test_70 全量管辖）；CLI 只做薄包装。
CLI/Web/API 三形态共用同一进度协议：轮询/推送的都是 job_status 的
增量 chunks（cursor 之后新增），M3b 的 SSE 只是本协议的薄适配。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# ---- 状态常量（JobStatus.state 取值域） ----
QUEUED = "queued"      # 已登记待执行
RUNNING = "running"    # 执行中
DONE = "done"          # 终态：成功
FAILED = "failed"      # 终态：执行体抛异常
ABORTED = "aborted"    # 终态：中止（reason="stale" 即 ADR-001 重启标废）

TERMINAL = (DONE, FAILED, ABORTED)


class JobError(Exception):
    """任务通道异常基类。"""


class JobStale(JobError):
    """handle 属于已消失的进程（重启/清理），任务不可恢复（ADR-001）。"""


class JobFailed(JobError):
    """任务终态为失败，携带用户可读错误文本。"""


class JobNotDone(JobError):
    """任务仍在排队/执行中，结果尚不可取。"""


@dataclass
class JobSpec:
    """提交物：kind + 可执行体 + 元信息。

    run 在 daemon 线程中执行，经 JobRuntime 回调上报进度/输出/cost；
    run 的返回值即 job_result 的结果（AskResult/QueryResult/DigestResult 等）。
    """
    kind: str                                    # "ask"|"query"|"digest"|"ingest"...
    run: Callable[["JobRuntime"], Any]
    meta: dict = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True)
class JobHandle:
    """不透明句柄；跨形态（CLI→API）传递用 to_dict/from_dict。"""
    job_id: str
    kind: str
    schema_version: int = 1

    def to_dict(self) -> dict:
        return {"job_id": self.job_id, "kind": self.kind,
                "schema_version": self.schema_version}

    @classmethod
    def from_dict(cls, d: dict) -> "JobHandle":
        return cls(job_id=d["job_id"], kind=d.get("kind", ""))


@dataclass
class JobStatus:
    """job_status(handle, cursor) 的返回值（增量协议）。"""
    state: str                                   # QUEUED|RUNNING|DONE|FAILED|ABORTED
    progress: float                              # 0.0-1.0
    chunks: List[str]                            # 仅 cursor 之后的新输出
    cursor: int                                  # 已产出 chunk 总数
    cost: dict                                   # {"calls","cost","currency"[,"note"]} 累计
    error: str = ""                              # failed 时用户可读错误
    reason: str = ""                             # aborted 原因："stale"=ADR-001
    schema_version: int = 1


class JobRuntime:
    """执行体回调面（线程安全）：progress / emit / add_cost。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.progress_value = 0.0
        self.chunks: List[str] = []
        self.cost = {"calls": 0, "cost": 0.0, "currency": ""}

    def progress(self, fraction: float) -> None:
        """上报进度（0.0-1.0，越界钳制；单调不减，防回退抖动）。"""
        with self._lock:
            f = max(0.0, min(1.0, float(fraction)))
            if f > self.progress_value:
                self.progress_value = f

    def emit(self, chunk: str) -> None:
        """追加一段增量输出（CLI 打印 / SSE 推送共用同一序列）。"""
        with self._lock:
            self.chunks.append(str(chunk))

    def add_cost(self, calls: int = 0, cost: float = 0.0,
                 currency: str = "") -> None:
        """累计 LLM 调用与成本；混合货币只标注不折算（与 cost.py 口径一致）。"""
        with self._lock:
            self.cost["calls"] += int(calls)
            self.cost["cost"] += float(cost)
            if currency:
                cur = self.cost.get("currency", "")
                if not cur:
                    self.cost["currency"] = currency
                elif cur != currency:
                    self.cost["note"] = "混合货币，未折算"


class _Job:
    """进程内任务记录（内部类型，不出模块）。"""

    def __init__(self, handle: JobHandle, spec: JobSpec) -> None:
        self.handle = handle
        self.spec = spec
        self.runtime = JobRuntime()
        self.state = QUEUED
        self.reason = ""
        self.error = ""
        self.result: Any = None
        self.thread: Optional[threading.Thread] = None
        self.ts = time.time()


# ---- 进程内 job 表（ADR-001：唯一存储，进程退出即全部消失） ----
_LOCK = threading.Lock()
_JOBS: Dict[str, _Job] = {}


def _stale_status(cursor: int = 0) -> JobStatus:
    """未知 handle 的恒定回答：aborted/stale，绝不抛错（ADR-001）。"""
    return JobStatus(state=ABORTED, progress=0.0, chunks=[], cursor=cursor,
                     cost={"calls": 0, "cost": 0.0, "currency": ""},
                     reason="stale")


def _run_body(job: _Job) -> None:
    """daemon 线程执行体：异常隔离，单任务失败不伤通道。"""
    with _LOCK:
        job.state = RUNNING
    try:
        result = job.spec.run(job.runtime)
    except Exception as exc:            # 执行体任何异常 -> failed 终态
        with _LOCK:
            job.state = FAILED
            job.error = "%s: %s" % (type(exc).__name__, exc)
    else:
        with _LOCK:
            job.result = result
            job.state = DONE
            job.runtime.progress_value = 1.0


def submit(spec: JobSpec) -> JobHandle:
    """登记任务并启动 daemon 线程执行，立即返回句柄。"""
    handle = JobHandle(job_id=uuid.uuid4().hex[:12], kind=spec.kind)
    job = _Job(handle, spec)
    with _LOCK:
        _JOBS[handle.job_id] = job
    t = threading.Thread(target=_run_body, args=(job,), daemon=True,
                         name="cenhua-job-%s" % handle.job_id)
    job.thread = t
    t.start()
    return handle


def job_status(handle: JobHandle, cursor: int = 0) -> JobStatus:
    """查询状态与增量输出。未知 handle（进程重启后的旧 handle）恒返回
    aborted/stale 终态（ADR-001），不抛错。"""
    with _LOCK:
        job = _JOBS.get(handle.job_id)
        if job is None:
            return _stale_status(cursor=max(0, int(cursor)))
        rt = job.runtime
        cur = max(0, int(cursor))
        return JobStatus(
            state=job.state,
            progress=rt.progress_value,
            chunks=list(rt.chunks[cur:]),
            cursor=len(rt.chunks),
            cost=dict(rt.cost),
            error=job.error,
            reason=job.reason,
        )


def job_result(handle: JobHandle) -> Any:
    """取终态结果：done -> 结果对象；其余按原因抛对应异常。"""
    with _LOCK:
        job = _JOBS.get(handle.job_id)
        if job is None:
            raise JobStale("任务已随进程结束（ADR-001），请重新发起")
        if job.state == DONE:
            return job.result
        if job.state == FAILED:
            raise JobFailed(job.error or "任务执行失败")
        raise JobNotDone("任务未结束（state=%s）" % job.state)


def wait(handle: JobHandle, poll: float = 0.2,
         timeout: Optional[float] = None) -> JobStatus:
    """CLI 轮询便捷器：阻塞至终态或超时。

    timeout 到期未终态：返回当前状态（state 仍为 running），不抛错。
    CLI 进度打印走 submit -> 循环 job_status -> 打印 -> wait -> job_result。
    """
    t0 = time.time()
    cursor = 0
    while True:
        st = job_status(handle, cursor)
        cursor = st.cursor
        if st.state in TERMINAL:
            return st
        if timeout is not None and time.time() - t0 >= timeout:
            return st
        time.sleep(max(0.01, float(poll)))


def run_cli(handle: JobHandle, printer: Callable[[str], None],
            poll: float = 0.2, timeout: Optional[float] = None,
            heartbeat: float = 10.0) -> JobStatus:
    """CLI 轮询打印器（M3a 任务 4）：增量 chunks 逐行 printer + 进度行。

    printer 由 CLI 注入（service 层禁 print）；无进展每 heartbeat 秒补一行
    心跳，长任务静默期用户可见。返回终态（或超时时的当前）状态。
    """
    t0 = time.time()
    cursor = 0
    last_print = t0
    last_progress = -1.0
    while True:
        st = job_status(handle, cursor)
        for chunk in st.chunks:
            for line in str(chunk).splitlines() or [""]:
                printer(line)
        cursor = st.cursor
        if st.state in TERMINAL:
            return st
        if st.progress != last_progress:
            printer("[进度] %3.0f%%" % (st.progress * 100.0))
            last_progress = st.progress
            last_print = time.time()
        elif time.time() - last_print >= heartbeat:
            printer("[心跳] 任务运行中… %ds" % int(time.time() - t0))
            last_print = time.time()
        if timeout is not None and time.time() - t0 >= timeout:
            return st
        time.sleep(max(0.01, float(poll)))


def reset() -> None:
    """清空进程内 job 表（仅供测试使用；生产代码禁止调用）。"""
    with _LOCK:
        _JOBS.clear()
