"""cenhua_service — CENHUA service 层（契约登记制，见 docs/service-contract.md）。

service 纪律（test_70_service_no_print 全量生效）：
  * 本包内函数禁止 print / exit / sys.exit。
  * 所有输出由 CLI 层（m_cenhua.py 或 m_*.py）负责。
  * 新函数必须先登记进 docs/service-contract.md 再实现。

M1a 交付：pricing/换算/ledger/cost/bench/verify_citation。
"""

from . import cost  # noqa: F401
from . import verify  # noqa: F401
from . import bench  # noqa: F401
from . import jobs  # noqa: F401  (M3a 任务通道)
from . import core  # noqa: F401  (M3a 六核心函数)

__all__ = ["cost", "verify", "bench", "jobs", "core"]
