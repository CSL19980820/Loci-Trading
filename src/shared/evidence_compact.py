r"""证据瘦身:逐票证据落库之前先砍掉。

为什么需要:`store.data_snapshot()` 不带 codes/窗口时会做全库证据扫描,
返回十几万条逐票回执。这份东西的**权威副本在 `market.db.source_route_receipts`**,
运维库再存一份既无意义又致命——实测单条 screen 运行的 `result_json` 达 257 MB,
694 行 job_runs 把 ops.db 撑到 5.67 GB,`GET /api/jobs/runs`(默认 limit=50)
一次返回 1.5 GB、耗时 97 秒。

同一个根因**已经在三个地方各犯一次**:

1. `ops.db.job_runs.result_json` —— screen 作业单条 257 MB,库涨到 5.67 GB。
2. `palace.db.candidate_reviews.evidence_json` —— 每条候选各存一份完整快照,
   227 行占了全库的 99%(58.3 MB),`GET /api/candidates/list` 一次回 58 MB。
3. `sync` 作业当年单独修过一次,但补丁只打在 sync 自己身上。

所以这个模块放在 `shared`:**谁要往库里写证据,谁在写之前调一次**。
指望每个作者都记得这件事,已经被证明行不通了。

**原地压缩,不做深拷贝**:被压的结构动辄几百 MB,`deepcopy` 会让内存翻倍。
而且执行器把同一份 result 直接当 HTTP 响应返回——那条路也不该发 257 MB,
所以「顺带把内存里那份也压了」是想要的效果,不是副作用。
"""
from __future__ import annotations

from typing import Any

#: 逐票回执只留失败样本,且最多这么多条。
RECEIPT_LIMIT = 50

#: 其它逐票大数组只留这么多条样本。实测 attempts 能到 18.8 万条 / 89 MB,
#: 和 receipts 是同一类东西,当初只压 receipts 是漏网。
SAMPLE_LIMIT = 50

#: 逐票证据的权威出处,压缩后写进 payload 让人知道去哪查完整版。
RECEIPT_SOURCE = "market.db:source_route_receipts"

#: 压过的标记键。存在即表示这份证据已经瘦过身,别再压第二遍。
RECEIPT_SOURCE_KEY = "receipts_source"

#: 会被压的逐票数组。``receipts`` 另有「只留失败」的规则,单独处理。
_BULK_ARRAYS = (
    "attempts",
    "observed_codes",
    "unresolved_receipt_codes",
    "attempts_not_observed_codes",
    "missing_codes",
    "rejected_codes",
)

#: 递归深度上限。作业结果是自造的嵌套 dict,不会太深;设上限是防环/防病态输入
#: 把收尾流程拖垮——收尾失败会让运行卡在 running,比丢一点证据严重得多。
_MAX_DEPTH = 8


def compact_source_evidence(evidence: dict[str, Any]) -> bool:
    """就地压缩一份 ``source_evidence``;返回是否真的改动过。

    **幂等**:压过的不再压。这不是洁癖——调用方常常拿的是浅拷贝,同一份
    ``source_evidence`` 会被同一轮里的多个写入点反复传进来(例如逐条候选各存
    一份快照)。第二次再压,``receipts_total`` 就会被写成上一次留下的样本数
    (50),真实总数 133640 当场丢失——比不压还糟,因为它看起来是对的。
    """
    if evidence.get(RECEIPT_SOURCE_KEY):
        return False
    changed = False
    receipts = evidence.get("receipts")
    if isinstance(receipts, list) and receipts:
        failed = [
            item
            for item in receipts
            if isinstance(item, dict)
            and (item.get("unresolved") or str(item.get("state") or "") == "failed")
        ]
        evidence["receipts"] = failed[:RECEIPT_LIMIT]
        evidence["receipts_total"] = len(receipts)
        evidence["receipts_failed"] = len(failed)
        evidence["receipts_source"] = RECEIPT_SOURCE
        changed = True
    for key in _BULK_ARRAYS:
        value = evidence.get(key)
        if isinstance(value, list) and len(value) > SAMPLE_LIMIT:
            evidence[key] = value[:SAMPLE_LIMIT]
            evidence["%s_total" % key] = len(value)
            changed = True
    return changed


def compact_job_result(result: Any, *, _depth: int = 0) -> int:
    """递归找出 result 里所有 ``source_evidence`` 并**就地**压缩,返回压了几处。

    容错优先:遇到任何意外结构都跳过而不抛错。收尾流程失败会让运行卡在
    ``running`` 占着槽,比少压一份证据严重得多。
    """
    if _depth > _MAX_DEPTH:
        return 0
    compacted = 0
    if isinstance(result, dict):
        for key, value in result.items():
            if key == "source_evidence" and isinstance(value, dict):
                compacted += 1 if compact_source_evidence(value) else 0
            else:
                compacted += compact_job_result(value, _depth=_depth + 1)
    elif isinstance(result, list):
        for item in result:
            compacted += compact_job_result(item, _depth=_depth + 1)
    return compacted
