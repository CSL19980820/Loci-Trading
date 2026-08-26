r"""作业结果瘦身:ops 侧入口。

实现搬到 ``src.shared.evidence_compact``——同一个根因在 ops / palace 两个库
各犯过一次,压缩器不能只住在 ops 里。这里保留再导出,既有 import 不用改。
"""
from __future__ import annotations

from src.shared.evidence_compact import (
    RECEIPT_LIMIT,
    RECEIPT_SOURCE,
    SAMPLE_LIMIT,
    compact_job_result,
    compact_source_evidence,
)

__all__ = [
    "RECEIPT_LIMIT",
    "RECEIPT_SOURCE",
    "SAMPLE_LIMIT",
    "compact_job_result",
    "compact_source_evidence",
]
