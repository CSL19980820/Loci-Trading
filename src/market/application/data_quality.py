r"""行情库数据体检：换源之后「数据到底到位没有」要能天天自动答。

背景：把主源换成通达信只改变「以后写进来的数据」。一次性重同步之后没人盯着，
库就会慢慢漂回去——回退源写进来的合成成交额、spot 落的无回执行、退市票的
陈旧水位，都是安静累积的。所以体检必须是**日常任务**，不是一次性脚本。

本模块只读、只判、只出中文告警，**不改库**：修复动作有自己的入口
（``scripts/resync_market_authoritative.py`` / ``repair/turnover``），
体检擅自动手会让「谁改的库」这件事说不清。
"""
from __future__ import annotations

import sqlite3

from datetime import datetime
from typing import Any

from src.market.application.data_quality_thresholds import (  # noqa: F401 - 兼容 re-export
    AUTHORITATIVE_PREFIX,
    FABRICATING_SOURCES,
    PROVISIONAL_SUFFIX,
    Finding,
    QualityThresholds,
    _SYNTH_EPSILON,
)


def _scalar(store: Any, sql: str, params: tuple = ()) -> Any:
    row = store.conn.execute(sql, params).fetchone()
    return row[0] if row else None


def _scalar_optional(store: Any, sql: str, params: tuple = ()) -> Any:
    """可选探测:表/列不存在时返回 None,而不是让整张体检表崩掉。

    体检是换源之后的最后一道防线。判据依赖的**辅助**信息(这里是证券列表的
    规模)取不到时,正确的行为是退化成更弱的判据并说清楚,而不是抛
    OperationalError 把任务刷红——那会让真正的数据问题被一条 schema 噪音盖住。
    只用于辅助信息;主判据仍走严格的 ``_scalar``,读不到就该炸。
    """
    try:
        row = store.conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def _source_mix(store: Any) -> list[tuple[str, int]]:
    rows = store.conn.execute(
        "SELECT source, COUNT(*) FROM quotes_daily GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    return [(str(source or ""), int(count)) for source, count in rows]


def _check_authoritative(mix: list[tuple[str, int]], limits: QualityThresholds) -> Finding:
    total = sum(count for _s, count in mix) or 1
    authoritative = sum(
        count for source, count in mix if source.startswith(AUTHORITATIVE_PREFIX)
    )
    ratio = authoritative / total
    observed = {
        "authoritative_rows": authoritative,
        "total_rows": total,
        "ratio": round(ratio, 4),
        "top_sources": mix[:5],
    }
    if ratio >= limits.min_authoritative_ratio:
        return Finding(
            "authoritative_ratio",
            "ok",
            "权威源（通达信）占比 %.1f%%" % (ratio * 100),
            observed,
        )
    return Finding(
        "authoritative_ratio",
        "block",
        "权威源（通达信）占比只有 %.1f%%，低于 %.0f%% 下限——主源可能长期失联，"
        "库在靠回退源续命，而回退源的成交额是 close×volume 合成的假值。"
        % (ratio * 100, limits.min_authoritative_ratio * 100),
        observed,
        remediation="先查通达信连通性（scripts/check_lane_readiness.py），"
        "恢复后跑 scripts/resync_market_authoritative.py 重写",
    )


def _last_day_source_mix(store: Any, day: str) -> list[tuple[str, int]]:
    """最后一个交易日的分源行数。走 ``trade_date`` 等值，不扫全表。"""
    rows = store.conn.execute(
        "SELECT source, COUNT(*) FROM quotes_daily WHERE trade_date = ?"
        " GROUP BY 1 ORDER BY 2 DESC",
        (day,),
    ).fetchall()
    return [(str(source or ""), int(count)) for source, count in rows]


def _last_day_settled(day: str, now: datetime, limits: QualityThresholds) -> bool:
    """这一天是否已经过了日终定稿窗口。

    ``day`` 早于今天 → 早就该定稿了。等于今天 → 看有没有到
    ``last_day_settle_hour``。晚于今天（时钟错乱或写进了假交易日）→ 不拿今天的
    钟去判它，按「还没定稿」处理，宁可漏报也不误报。
    """
    today = now.strftime("%Y-%m-%d")
    if day < today:
        return True
    if day > today:
        return False
    return now.hour >= limits.last_day_settle_hour


def _check_last_day_authoritative(
    store: Any, limits: QualityThresholds, now: datetime
) -> Finding:
    r"""**最后一个交易日**的权威源占比。抓的是「主源从今天开始退化」。

    **为什么 `_check_authoritative` 顶不上**：它的分母是全部历史。一次全量重灌
    能把它顶到 96%，此后每天只新增约 5500 行，「今天主源一行没写」这件事被十六
    年历史稀释到看不见。**开发机**只读实测（2026-08-26，该机通达信自 07-28 起被
    限流）：全库 16,966,403 行里 tdx 占 16,376,434 行 = **96.5%**，判绿；同一时刻
    最后一个交易日的 5542 行里 tdx **0 行**。要把全库压到 95% 以下还得再灌
    271,948 行非权威数据，按每天 5542 行算是 **49 个交易日**——等全库判据开口，
    主源已经断了两个半月；那台机器从 07-28 起当日占比就从 ~98% 掉到 ~20.7%，
    20 个交易日过去，全库口径一声没吭。

    同一天的**生产库是健康的**（全库 97.1%、逐日 99.9%~100%），所以这条判据不是
    为了修某次事故,而是补一个**算术上必然存在**的盲区:分母是十六年、分子是一天,
 比值天生对单天不敏感。取证时务必分清测的是哪台机器——这两台当天一好一坏,
    把开发机的数字写成「生产实测」会让后来人照着一个不存在的故障去排查。

    **为什么 spot 行必须单独归一类**（这条是本判据不误报的关键）：盘中 spot 落
    的是临时行，source 带 ``_spot`` 后缀（``tencent_spot`` / ``tdx_spot``），日
    终同步再用正式日 K 覆盖。体检虽然托管在 16:30（盘后），但人随时会手动点一
    下——11 点跑一次，当天本来就是满屏 spot，「非 tdx 就报警」当场误报。于是：

    1. ``_spot`` 行归为**临时**，既不算权威源已经写进来，也不算主源失联退到了
        回退源；占比只在**已定稿**的行之间算。``tdx_spot`` 同样是临时行，不能拿
        它把占比洗绿——盘中 spot 走通达信、日终正式日 K 根本没落，正是要抓的形态。
    2. 临时行占比超过 ``max_last_day_provisional_ratio`` 时当天视为**还没定稿**，
        此时**不判**权威源占比，结论里写明「尚未定稿」。
    3. 但这个豁免带时限（``last_day_settle_hour``）：过了日终定稿窗口还满屏 spot，
        说明日终同步压根没把当日改写成正式日 K，那是真问题，照报。没有这道时限
        就等于给「日终同步整个失败」发了免死金牌，而那恰恰最该当天知道。

    **为什么是 warn 不是 block**：本模块的 block 表示「库整体不可信」——全库权
    威源塌了、基准指数串成同号个股，两者会让**每一次**回测与选股的结论都跟着
    错。单独一天走了回退源不是这个量级：历史仍然是权威源的，一次定点重灌就能补
    回来，而且它可能只是一次下午连不上通达信。更实际的一点是：``warn`` 一样进
    ``build_alert``，而企微推送的判据是「``blocked`` 或有 ``alert``」，所以定成
    warn **不会少通知一个人**，只是不去把「库不能用」那面旗插上。级别要留给真该
    拦人的事，否则 block 也会通胀成又一种噪音。
    """
    last_day = _scalar(store, "SELECT MAX(trade_date) FROM trading_calendar")
    if not last_day:
        # 日历为空由 `last_day_rows` 判据负责报（block），这里不重复刷一条同因告警。
        return Finding(
            "last_day_authoritative",
            "ok",
            "交易日历为空，当日权威源占比无从判起（由 last_day_rows 判据负责报）",
            {},
        )
    day = str(last_day)
    mix = _last_day_source_mix(store, day)
    provisional_rows_list = [(s, c) for s, c in mix if s.endswith(PROVISIONAL_SUFFIX)]
    provisional = sum(count for _s, count in provisional_rows_list)
    # 临时行还要再分一刀:内容是不是权威源给的。``tdx_spot`` 的来路是
    # ``TdxAdapter.fetch_spot`` = 「每只票日线的最后一根」(``fetch_daily_many(bars=1)``),
    # 即通达信自己的当日 bar —— 成交额是真值、回执照写、换手照算,只有 source 上
    # 的定稿标记没落。``tencent_spot`` 就完全是另一回事:那一档的 ``amount`` 是
    # ``close×volume`` 合成的假值(见 ``FABRICATING_SOURCES``)。
    #
    # 两者都算「没定稿」是对的(占比判据仍只在已定稿的行之间算),但**后果差一个
    # 量级**,告警必须分开说:前者当天的数值可用、缺的是定稿这一步;后者当天吃
    # 成交额/量比的战法会真的算错。混成一句「临时行没有正式日 K 的成交额与复权
    # 口径」在 tdx_spot 的场景下是**假话**,而假话会让人开始整体不信这张表。
    provisional_authoritative = sum(
        count
        for source, count in provisional_rows_list
        if source.startswith(AUTHORITATIVE_PREFIX)
    )
    provisional_fallback = provisional - provisional_authoritative
    settled = [(s, c) for s, c in mix if not s.endswith(PROVISIONAL_SUFFIX)]
    settled_rows = sum(count for _s, count in settled)
    authoritative = sum(
        count for source, count in settled if source.startswith(AUTHORITATIVE_PREFIX)
    )
    total = settled_rows + provisional
    observed: dict[str, Any] = {
        "trade_date": day,
        "authoritative_rows": authoritative,
        "settled_rows": settled_rows,
        "provisional_rows": provisional,
        "total_rows": total,
        "limit": limits.min_last_day_authoritative_ratio,
        "sources": mix[:5],
        "provisional_authoritative_rows": provisional_authoritative,
        "provisional_fallback_rows": provisional_fallback,
    }
    if total <= 0:
        return Finding(
            "last_day_authoritative",
            "ok",
            "最后交易日 %s 没有任何日 K，当日权威源占比无从判起"
            "（由 last_day_rows 判据负责报）" % day,
            observed,
        )
    provisional_ratio = provisional / total
    observed["provisional_ratio"] = round(provisional_ratio, 4)
    observed["ratio"] = round(authoritative / settled_rows, 4) if settled_rows else None
    settled_deadline_passed = _last_day_settled(day, now, limits)
    observed["settled_deadline_passed"] = settled_deadline_passed
    # settled_rows <= 0 也走这条:阈值被配成 1.0 时占比不会超,但分母是 0,
    # 再往下算就是 ZeroDivisionError——体检自己崩掉比漏报还糟。
    if provisional_ratio > limits.max_last_day_provisional_ratio or settled_rows <= 0:
        if not settled_deadline_passed:
            return Finding(
                "last_day_authoritative",
                "ok",
                "最后交易日 %s 尚未定稿（%d / %d 行还是 spot 临时行），"
                "当日权威源占比等日终同步（15:10）之后再判"
                % (day, provisional, total),
                observed,
            )
        # 后果分两档:全是权威源内容 → 数值可用,只缺定稿这一步;掺了回退源 →
        # 那部分的成交额是合成假值,当天吃成交额/量比的战法真会算错。
        if provisional_fallback:
            impact = (
                "其中 %d 行来自回退源(``%s`` 这类),它们的成交额是 close×volume 合成的"
                "假值——当天吃成交额/量比/换手的战法会算错;另 %d 行是权威源的当日 bar,"
                "数值本身可用。"
                % (provisional_fallback, "tencent_spot", provisional_authoritative)
            )
        else:
            impact = (
                "这些行的内容是权威源(通达信)自己的当日 bar——成交额是真值、回执与换手"
                "齐全,所以**当天的选股/回测读到的数字是对的**;缺的是日终定稿这一步:"
                "source 停在临时标记上,严格 PIT 与逐日溯源会把这一天认成未定稿。"
            )
        return Finding(
            "last_day_authoritative",
            "warn",
            "最后交易日 %s 到 %d 点仍未定稿：%d / %d 行（%.1f%%）还是 spot 临时行——"
            "日终同步没把当日 spot 改写成正式日 K。%s"
            % (
                day,
                limits.last_day_settle_hour,
                provisional,
                total,
                provisional_ratio * 100,
                impact,
            ),
            observed,
            remediation="看运维「执行历史」里当天的「行情日终重刷」是否失败或被跳过"
            "（最常见的是被选股/同步占着 market.db 写锁）；重跑该任务即可，它会在 spot"
            "之后用权威源把当日重写成正式日 K。不要上来就跑 --force：那是忽略 watermark"
            "全量重灌三十年历史（实测约 50 分钟），补当天用不上",
        )
    ratio = authoritative / settled_rows
    if ratio >= limits.min_last_day_authoritative_ratio:
        return Finding(
            "last_day_authoritative",
            "ok",
            "最后交易日 %s 权威源（通达信）占比 %.1f%%（%d / %d 行已定稿，"
            "另有 %d 行 spot 临时行）"
            % (day, ratio * 100, authoritative, settled_rows, provisional),
            observed,
        )
    return Finding(
        "last_day_authoritative",
        "warn",
        "最后交易日 %s 的权威源（通达信）占比只有 %.1f%%（%d / %d 行已定稿），"
        "低于 %.0f%% 下限——主源当天基本没写进来，这一天是回退源记的，而回退源的"
        "成交额是 close×volume 合成的假值。全库占比看不见这种单天回落：十六年历史"
        "会把它整个稀释掉，等全库跌破下限已经是几十个交易日之后。"
        % (
            day,
            ratio * 100,
            authoritative,
            settled_rows,
            limits.min_last_day_authoritative_ratio * 100,
        ),
        observed,
        remediation="先查通达信连通性（scripts/check_lane_readiness.py），恢复后跑 "
        "scripts/resync_market_authoritative.py 重写该交易日",
    )


def _check_fabricated(store: Any, limits: QualityThresholds) -> Finding:
    """合成成交额判据。两道排除,都是为了不把**真数据**报成假值。

    1. **只在会合成的源上算**(``FABRICATING_SOURCES``)。通达信给的是真实
        成交额,数值恰好相等也不算合成。
    2. **跳过单一价格成交日**(``high == low``)。整天只成交在一个价位时,
        ``amount = close × volume`` 是**算术恒等**,不是谁算出来的。

    第 2 条是 2026-08-25 加的。此前生产库报「合成成交额 8128 行」,实测其中
    **7721 行(95%)当日 high == low**——1990 年代涨跌停加薄成交、以及北交所/
    新三板低流动性个股,整日一价成交是常态。反向验证:通达信自己的单一价格日
    (53176 行)里也有 33% 满足该等式,可见这是**物理规律,不是某个源在造假**。

    这条误报还特别难缠:它给的处置建议是「跑 resync 用通达信重写」,而那 8128
    行里 98.4% 的日期通达信**根本够不到**(实测对 97 只定点重灌,修正 0 行)。
    一条天天响、照着做又没用的告警,会把整张体检表训练成噪音。
    """
    placeholders = ",".join("?" * len(FABRICATING_SOURCES))
    count = int(
        _scalar(
            store,
            "SELECT COUNT(*) FROM quotes_daily WHERE source IN (%s)" % placeholders
            + " AND amount IS NOT NULL AND volume > 0 AND close > 0"
            "   AND high <> low"
            "   AND ABS(amount - close*volume) < ?",
            tuple(FABRICATING_SOURCES) + (_SYNTH_EPSILON,),
        )
        or 0
    )
    observed = {"rows": count, "limit": limits.max_fabricated_rows}
    if count <= limits.max_fabricated_rows:
        return Finding("fabricated_amount", "ok", "合成成交额 %d 行" % count, observed)
    return Finding(
        "fabricated_amount",
        "warn",
        "合成成交额 %d 行，超过 %d 行上限。这些行的 amount 是 close×volume 算出来的，"
        "不是真实成交额；任何按成交额筛选/排序的策略都会被它带偏。"
        % (count, limits.max_fabricated_rows),
        observed,
        remediation="跑 scripts/resync_market_authoritative.py 用通达信重写",
    )


def _check_receipts(store: Any, limits: QualityThresholds) -> Finding:
    count = int(
        _scalar(
            store,
            "SELECT COUNT(*) FROM quotes_daily"
            " WHERE trade_date >= date('now', ?) AND receipt_id IS NULL",
            ("-%d day" % limits.lookback_days,),
        )
        or 0
    )
    observed = {
        "rows": count,
        "limit": limits.max_missing_receipts,
        "lookback_days": limits.lookback_days,
    }
    if count <= limits.max_missing_receipts:
        return Finding(
            "missing_receipts", "ok", "近 %d 日缺回执 %d 行" % (limits.lookback_days, count), observed
        )
    return Finding(
        "missing_receipts",
        "warn",
        "近 %d 日有 %d 行日 K 没有来源回执，超过 %d 行上限。回执是研究输入证据，"
        "缺回执的行会被严格 PIT 研究直接拒绝。"
        % (limits.lookback_days, count, limits.max_missing_receipts),
        observed,
        remediation="这些多是 spot 落的临时行；等日终同步重写，或跑一次 force 同步补齐",
    )


def _check_last_day(store: Any, limits: QualityThresholds) -> Finding:
    last_day = _scalar(store, "SELECT MAX(trade_date) FROM trading_calendar")
    if not last_day:
        return Finding(
            "last_day_rows", "block", "交易日历为空，无法判断当日覆盖", dict()
        )
    count = int(
        _scalar(
            store,
            "SELECT COUNT(*) FROM quotes_daily WHERE trade_date = ?",
            (str(last_day),),
        )
        or 0
    )
    universe = int(
        _scalar_optional(
            store,
            "SELECT COUNT(*) FROM instruments WHERE instrument_type = 'STOCK'",
        )
        or 0
    )
    # instruments 还没同步过时比率无意义，退回绝对地板，别把空库判成通过。
    if universe <= 0:
        observed = dict(
            trade_date=str(last_day),
            rows=count,
            universe=0,
            limit=limits.min_last_day_rows_floor,
        )
        if count >= limits.min_last_day_rows_floor:
            return Finding(
                "last_day_rows",
                "ok",
                "最后交易日 %s 覆盖 %d 只（证券列表为空，仅按地板判）"
                % (last_day, count),
                observed,
            )
        return Finding(
            "last_day_rows",
            "warn",
            "最后交易日 %s 只覆盖 %d 只，低于 %d 行地板，且证券列表为空。"
            % (last_day, count, limits.min_last_day_rows_floor),
            observed,
            remediation="先跑证券列表同步，再看当天的行情同步任务",
        )
    # 指数等非 STOCK 也落在 quotes_daily 里，覆盖率可略超 100%，属正常。
    ratio = count / universe
    observed = dict(
        trade_date=str(last_day),
        rows=count,
        universe=universe,
        coverage=round(ratio, 4),
        limit=limits.min_last_day_coverage,
    )
    if ratio >= limits.min_last_day_coverage:
        return Finding(
            "last_day_rows",
            "ok",
            "最后交易日 %s 覆盖 %d / %d 只（%.1f%%）"
            % (last_day, count, universe, ratio * 100),
            observed,
        )
    return Finding(
        "last_day_rows",
        "warn",
        "最后交易日 %s 只覆盖 %d / %d 只（%.1f%%），低于 %.0f%% 下限——当日同步可能没跑完。"
        % (last_day, count, universe, ratio * 100, limits.min_last_day_coverage * 100),
        observed,
        remediation="看运维「执行历史」里当天的行情同步任务是否失败或被跳过",
    )


def _check_index_sanity(store: Any, limits: QualityThresholds) -> Finding:
    """基准指数串成同号个股是真出过的事故：中证 500 该 7717，串回来 8.54。"""
    placeholders = ",".join("?" * len(limits.index_codes))
    rows = store.conn.execute(
        "SELECT code, trade_date, close FROM quotes_daily"
        " WHERE code IN (%s)" % placeholders
        + "   AND trade_date >= (SELECT MIN(trade_date) FROM (SELECT trade_date"
        "       FROM trading_calendar ORDER BY trade_date DESC LIMIT 5))"
        "   AND close < ?",
        tuple(limits.index_codes) + (limits.min_index_close,),
    ).fetchall()
    observed = {"bad_rows": [tuple(r) for r in rows[:10]], "count": len(rows)}
    if not rows:
        return Finding("index_sanity", "ok", "基准指数近 5 日收盘量级正常", observed)
    return Finding(
        "index_sanity",
        "block",
        "基准指数近 5 日有 %d 行收盘价低于 %.0f——几乎肯定是串成了同号个股"
        "（通达信指数要走 get_index_bars，用 get_security_bars 会安静地返回深市同号股票）。"
        "基准一歪，复盘里每一条相对收益都跟着错。"
        % (len(rows), limits.min_index_close),
        observed,
        remediation="用 instrument_type='INDEX' 重同步这三只，并清掉指数发布日之前的残留行",
    )


def _check_watermarks(store: Any) -> Finding:
    """非权威源的水位要能说清原因——退市票取不到是正常的，其它就不是。"""
    rows = store.conn.execute(
        "SELECT w.code, w.source, w.status, w.last_trade_date,"
        "       COALESCE(i.status, '') FROM ingest_watermark w"
        " LEFT JOIN instruments i ON i.code = w.code"
        " WHERE w.source NOT LIKE 'tdx%'"
    ).fetchall()
    unexplained = [
        tuple(row) for row in rows if str(row[4] or "") not in ("delisted", "suspended")
    ]
    observed = {"non_authoritative": len(rows), "unexplained": unexplained[:10]}
    if not unexplained:
        return Finding(
            "watermark_source",
            "ok",
            "非权威源水位 %d 条，全部可解释（退市/停牌）" % len(rows),
            observed,
        )
    return Finding(
        "watermark_source",
        "warn",
        "有 %d 只票的水位来自非权威源且不是退市/停牌——说明通达信取不到它们，"
        "但原因不明。" % len(unexplained),
        observed,
        remediation="逐票用 tdx_daily.fetch_daily_bars 手工试一次，确认是代码段不支持还是别的",
    )


def inspect_market_data(
    store: Any,
    *,
    thresholds: QualityThresholds | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    r"""跑一遍全部体检项，返回可直接进 job payload 的结构。

    只读；发现问题只报不改。``blocked`` 为真表示有 block 级问题。

    ``now`` 只服务「最后一个交易日是不是已经日终定稿」那条判据（见
    ``_check_last_day_authoritative``）。做成参数是为了让它可被确定性地测试：
    拿真实墙钟去测「盘中不误报」的用例，会在每天 16:00 之后自己变红。
    """
    limits = thresholds or QualityThresholds()
    mix = _source_mix(store)
    findings = [
        _check_authoritative(mix, limits),
        _check_last_day_authoritative(store, limits, now or datetime.now()),
        _check_fabricated(store, limits),
        _check_receipts(store, limits),
        _check_last_day(store, limits),
        _check_index_sanity(store, limits),
        _check_watermarks(store),
    ]
    blocked = [f for f in findings if f.level == "block"]
    warned = [f for f in findings if f.level == "warn"]
    return {
        "blocked": bool(blocked),
        "block_count": len(blocked),
        "warn_count": len(warned),
        "findings": [f.to_dict() for f in findings],
        "alert": build_alert(findings),
    }


def build_alert(findings: list[Finding]) -> str:
    """中文告警文案。全绿返回空串——没事就别打扰人。"""
    bad = [f for f in findings if f.level in ("block", "warn")]
    if not bad:
        return ""
    lines = ["行情库体检发现 %d 项问题：" % len(bad)]
    for item in bad:
        tag = "【阻断】" if item.level == "block" else "【提醒】"
        lines.append("%s%s" % (tag, item.message))
        if item.remediation:
            lines.append("   处理：%s" % item.remediation)
    return "\n".join(lines)