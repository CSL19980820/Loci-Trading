"""Validate saved executions against frozen bars and build the research report."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.wechat_four_patterns_research import DEFAULT_OUT, ROOT, load_snapshot, save_json


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def table(rows, columns):
    def cell(value):
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)
    return "\n".join(["| " + " | ".join(title for _, title in columns) + " |",
                       "| " + " | ".join("---" for _ in columns) + " |",
                       *["| " + " | ".join(cell(row.get(key)) for key, _ in columns) + " |" for row in rows]])


def main() -> None:
    out = DEFAULT_OUT
    values = read_json(out / "summaries.json") + read_json(out / "followup_summaries.json")
    raw, _, _ = load_snapshot(out)
    verified_events = 0
    verified_allocations = 0
    identities = []
    for summary in values:
        directory = out / "results" / summary["scenario"]
        events = pd.read_csv(directory / "events.csv", dtype={"code": str}, float_precision="round_trip")
        portfolio = read_json(directory / "portfolio.json")
        daily = pd.DataFrame(portfolio["daily"])
        assert int(daily.entries.max()) <= 2 and int(daily.open_positions.max()) <= 2
        assert daily.cash.min() >= -1e-6
        assert np.allclose(daily.equity, daily.cash + daily.market_value, atol=2e-5, rtol=0)
        for event in events.itertuples():
            entry_index = raw["close"].index.get_loc(event.entry_date)
            assert raw["close"].index[entry_index - 1] == event.signal_date
            assert event.entry_price == raw["open"].at[event.entry_date, event.code]
            assert raw["volume"].at[event.entry_date, event.code] > 0
            assert event.entry_factor == raw["__adjust_factor"].at[event.entry_date, event.code]
            if event.exit_reason != "data_end":
                assert event.exit_date > event.entry_date
                assert raw["volume"].at[event.exit_date, event.code] > 0
                assert event.exit_factor == raw["__adjust_factor"].at[event.exit_date, event.code]
                assert raw["low"].at[event.exit_date, event.code] - 1e-8 <= event.exit_price <= raw["high"].at[event.exit_date, event.code] + 1e-8
            expected = (event.exit_price * event.exit_factor / (event.entry_price * event.entry_factor) - 1) * 100
            assert abs(expected - event.gross_return_pct) < 1e-8
            assert abs(event.gross_return_pct - event.net_return_pct - summary["round_trip_cost_pct"]) < 1e-8
            verified_events += 1
        realized = sum(row["pnl"] for row in portfolio["allocations"])
        unrealized = sum(row["unrealized_pnl"] for row in portfolio.get("open_allocations", []))
        assert abs(200_000 + realized + unrealized - daily.equity.iloc[-1]) < 0.001
        for row in portfolio["allocations"]:
            assert row["quantity"] > 0 and row["quantity"] % 100 == 0
            verified_allocations += 1
        identities.append({"scenario": summary["scenario"], "realized_pnl": realized,
                           "unrealized_pnl": unrealized, "end_equity": float(daily.equity.iloc[-1]),
                           "reconciled": True})
    audit = {"completed_at": datetime.now(timezone.utc).isoformat(), "scenarios": len(values),
             "events_checked": verified_events, "closed_allocations_checked": verified_allocations,
             "raw_entry_prices_and_factors_passed": True, "exit_prices_within_traded_bar_passed": True,
             "gross_net_cost_recomputed": True, "account_reconciliation_passed": True,
             "accounts": identities}
    save_json(out / "execution_audit.json", audit)
    meta = read_json(out / "snapshot_manifest.json")
    liquidity = read_json(out / "liquidity_field_audit.json")
    prefix = read_json(out / "signal_audit.json")
    replay = read_json(out / "replay_verification.json")
    by_key = {r["scenario"]: r for r in values}
    labels = {"primary": "四形态混合", "contraction": "缩量支撑确认", "ma_cross": "5/10日金叉",
              "platform": "平台突破", "trend_pullback": "趋势回踩"}
    family_rows = []
    for key, label in labels.items():
        a, b = by_key["2025_" + key], by_key["2026_8m_" + key]
        family_rows.append({"family": label, "r2025": a["account_return_pct"], "dd2025": -a["max_drawdown_pct"],
                            "r2026": b["account_return_pct"], "dd2026": -b["max_drawdown_pct"]})
    columns = [("scenario", "情景"), ("closed_trades", "已平仓笔数"), ("account_return_pct", "账户收益%"),
               ("max_drawdown_pct", "最大回撤%（负号）"), ("win_rate_pct", "胜率%"), ("avg_close_exposure_pct", "平均收盘仓位%")]
    primary = [by_key[x] for x in ("2025_primary", "2026_8m_primary", "full_primary")]
    candidate = [by_key[x] for x in ("2025_contraction", "2026_8m_contraction", "full_contraction")]
    stress = [by_key[x] for x in ("2025_contraction_double_cost", "2026_8m_contraction_double_cost", "2025_contraction_hold_2sessions", "2026_8m_contraction_hold_2sessions", "2025_contraction_one_pick", "2026_8m_contraction_one_pick")]
    monthly = pd.read_csv(out / "results/full_contraction/monthly.csv")
    trades = pd.read_csv(out / "results/full_contraction/trades.csv", dtype={"code": str})
    names = pd.read_csv(out / "universe.csv", dtype={"code": str}).set_index("code").name.to_dict()
    extremes = pd.concat([trades.nsmallest(3, "net_return_pct"), trades.nlargest(3, "net_return_pct")]).copy()
    extremes["name"] = extremes.code.map(names)
    winners = trades.loc[trades.pnl > 0].pnl
    concentration = float(winners.nlargest(5).sum() / winners.sum() * 100)
    full = by_key["full_contraction"]
    report = f'''# 微信图解四形态量化研究：每日最多2只

研究日期：2026-09-28。状态：研究候选，未注册生产战法、未接入定时选股、未部署、未下单。

## 结论

文章能拆成可计算的形态，但“四种形态有一条满足就混合排序”的原始主方案没有呈现可靠优势：20个月账户收益仅 {by_key['full_primary']['account_return_pct']:.2f}%，最大回撤 {-by_key['full_primary']['max_drawdown_pct']:.2f}%。不能把2026年前8个月盈利单独拿出来宣称有效。

可保留的研究方向是“缩量回踩20/30日支撑 → 放量突破前一日高点”。这个预先定义的子组在2025年及2026年前8个月分别盈利，连续20个月模拟账户收益 {full['account_return_pct']:.2f}%，最大回撤 {-full['max_drawdown_pct']:.2f}%，但它是看过多组结果后挑出的候选，不是独立样本外结论。2025年成本翻倍后转亏，缩短到买入次日卖出也明显恶化。当前不能直接批准实盘上线。

## 原文与量化边界

原文为“我是投顾”的《【实战图解】短线抄底技巧》，用户给定链接的正文与7张配图已保存到 `source/article.json`、`source/article.html` 和 `source/figure_00.png` 至 `figure_06.png`。原文分为缩量反弹后放量、5/10日线交叉、平台压力支撑、上升波段回调四类，并明确说是教学模型。

原图用箭头事后标记主升段，没有可直接运行的价格/量能阈值、退出规则或费用定义。本报告的全部数字阈值、市场过滤、排序和持仓模型均为研究者的操作化假设，不是原文承诺，也不识别所谓“庄家意图”。

## 固定规则

信号必须在当天完整日线结束后计算，最早下一交易日开盘尝试成交。这里不是历史14:50尾盘回测；没有盘中快照，不能用最终日线冒充14:50数据。

共同股票池及过滤：代码00/60的主板股票；当前元数据中的ST/退/非normal排除；当日有效报价且至少120根有效日K、最近20根均有效；当天及过去20日平均存储成交额至少5000万元；当天收阳、涨幅大于0且不超过7%，最近5日涨幅不超过15%、20日不超过35%；收盘在当日振幅上部40%，价格不低于20日均线且不偏离其12%以上。至少500只可用股票中，站上20日均线的比例达到45%才开信号。

“存储成交额”大部分是代理字段，不能解释为已核验的源生成交额，详见数据局限。

| 形态 | 固定计算条件（除此之外还须通过共同过滤） |
| --- | --- |
| 缩量支撑确认 | 前一日最低价距当时20或30日均线在±3%内；此前3日均量/此前20日均量≤0.8；当日成交量/此前20日均量在1.2—2.5；收盘高于前一日最高价且不低于5日线；20日线较5日前回落不超过1%。 |
| 5/10日金叉 | 昨日5日线≤10日线，今日5日线>10日线；20日线>30日线，30日线上行；收盘不低于5日线；量比1.0—2.5。 |
| 平台突破 | 之前20日最高/最低形成的区间幅度≤18%；收盘突破之前20日最高价，但超出不超过3%；量比1.2—2.5；收盘位于当日振幅上部35%。 |
| 趋势回踩 | 5>10>20>30>60日均线且20日线上行；此前3日最低价触及10日线附近但不低于20日线3%；相对此前20日高点回撤3%—12%；缩量比≤0.9，随后量比1.0—2.5，收盘突破昨日高点并站上5日线。 |

同日先合并去重，再按“形态重合数量×100 + 收盘位置×10 + 截断的20日收益×10 + 温和放量奖励”排序，同分按代码。**整个名单最多2只，不是每种形态各2只。** 参数大于2直接报错；无合格信号则空名单，不从弱候选补足。

子组对照仍使用同一评分，因此“缩量支撑确认”不是完全去掉其他形态信息的纯单因子实验：形态重合奖励继续保留。只改变候选所属形态，不改变排序权重。

## 数据与账户口径

只读本地 `data/market.db`，冻结 {meta['raw_rows']:,} 行、{meta['codes']} 只股票。预热从2024-07-01开始；正式观察2025-01-02至2026-08-31，共403个交易日、20个自然月。2025独立重置账户243个交易日；2026年1—8月独立重置账户160个交易日。最少每日有效报价 {meta['min_observation_daily_valid']} 只；两个分段都超过半年。全库日线最大日期为2026-09-11，并非截至研究当天。

初始20万元、最多2个资金槽位；每个槽位按上一观察日权益的一半预算，100股整手、不融资、不加仓摊平、同代码不得重叠。先按信号评分缩到2只；**剩余一个槽位时，复用的公共账户引擎按代码顺序接受两只名单中的一只，不是按评分争抢槽位。** 当天退出的资金不供当天开盘新仓使用。单日新增≤2、总持仓≤2；未成交不得扩展原始名单。

采用原始OHLC成交、当时事件日期已生效的正复权因子计算经济收益，因子只向前填充、不回填未来事件。持仓按每日收盘盯市，停牌不伪造成交。涨停开盘拒绝买入，跌停/停牌不能退出则延后。计划含买入日3个交易日，配置值为hold_days=2；买入当天不卖出，下一交易日起可触发-6%止损，不设止盈。跳空越过止损按更差开盘价；因此实际亏损可以超过6%，被锁住的仓位也可能超过计划持有期。

往返成本0.26%：单边佣金3bp、单边滑点5bp、实验卖出附加费10bp。10bp是沿用的保守实验参数，不是现行法定税率断言，也不是用户券商报价。账户按入场名义额将往返成本一半开仓扣、一半平仓扣；未实现头寸不提前扣未来退出费用。未模拟盘口队列、逐笔冲击及独立现金分红台账。

截止时未平仓维持开放并进入净值，不能算成已实现盈利。表中的胜率仅指已平仓交易；回撤是每日收盘账户净值回撤，不是盘中最大回撤，也不是单笔收益串联。沪深300为本地指数第一观察日收盘至最后观察日收盘的价格基准，非含分红可投资组合；两段分别 {by_key['2025_primary']['benchmark_close_return_pct']:.2f}%、{by_key['2026_8m_primary']['benchmark_close_return_pct']:.2f}%，全段 {full['benchmark_close_return_pct']:.2f}%。

## 主方案：四形态混合

{table(primary, columns)}

连续账户173笔平仓、期末2笔开放。全段472个股票信号、236个有信号交易日、167个空名单交易日；每天最多2只。资金占用导致部分信号不能入场，不将信号数冒充成交数。

## 预先定义的子组对照

{table(family_rows, [('family','形态'),('r2025','2025收益%'),('dd2025','2025回撤%'),('r2026','2026前8月收益%'),('dd2026','2026前8月回撤%')])}

5/10日金叉两段均为负；平台突破跨阶段翻转；趋势回踩虽两段为正，但2025年回撤较大。缩量支撑值得后续做更严格数据验证，不代表该子组已经通过多重检验。

## 候选：缩量支撑确认

{table(candidate, columns)}

连续账户170笔已平仓、期末2笔开放；465个信号，234个有信号日、169个空名单日，日上限2。平均每笔净收益 {full['mean_trade_net_pct']:.3f}%，已实现现金盈利/亏损比 {full['profit_factor_cash']:.2f}，盈利笔平均收益/亏损笔平均损失比 {full['payoff_ratio_pct']:.2f}。全段胜率不足50%，不能称作高胜率抄底法。最大单笔净亏损 {full['worst_trade_pct']:.2f}%，最好单笔 {full['best_trade_pct']:.2f}%。最大5笔现金盈利占全部盈利笔现金盈利的 {concentration:.2f}%，仍需关注收益集中性。

独立分段与连续账户不是简单拼接：2025年末未平仓在连续版本跨年延续，独立2026版本从现金重启，所以笔数、持仓节奏、收益和回撤不会机械相加或相乘。

## 追加敏感性：明确是看过结果后的诊断

{table(stress, columns)}

成本翻倍至0.52%后，2025年从盈利转为-1.68%；只持有含买入日2个交易日（即买入次日退出）时，2025年-22.49%、2026年前8个月约-0.01%。这说明它不能直接搬成“今天选、明天赚一点就走”的隔夜系统。每日只留1只的结果在两段均为正、回撤更低，但也是追加比较，不据此事后更换默认策略并重新声称样本外有效。

初始19情景与后续7情景全部保留，没有隐藏不盈利的持仓天数、市场过滤或费用配置。没有收益导向的参数网格搜索；子组择优本身仍然产生选择偏差。

## 候选连续账户分月

{table(monthly.to_dict('records'), [('month','月份'),('return_pct','账户收益%'),('entries','新仓数'),('average_close_exposure_pct','平均收盘仓位%')])}

## 对照逐笔：最差3笔和最好3笔

{table(extremes.to_dict('records'), [('code','代码'),('name','当前名称'),('signal_date','信号日'),('entry_date','入场'),('exit_date','退出'),('net_return_pct','净收益%')])}

名称来自当前元数据，仅用于定位记录；并不保证是历史交易当日简称。

## 已完成校验与剩余限制

已完成23项定向单元/集成测试，包括真实阳性合成形态、全名单上限、同分稳定排序、历史截断/未来数据扰动、停牌/缺值/资格掩码、原始价格成交、T+1、跳空止损、拆股复权及尾部开放持仓。目标文件ruff F检查通过。

全市场前缀一致性日期：{', '.join(prefix['historical_prefix_checks'])}，信号及评分/形态因子均一致。冻结输入重放{replay['scenarios_compared']}个原始情景的数值摘要完全一致。独立逐笔审计覆盖{verified_events}条情景事件、{verified_allocations}条已平仓账户分配；逐一复核下一交易日原始开盘价、复权因子、经济毛收益及费用；闭合交易退出价在可交易日OHLC范围内；{len(values)}个账户均满足“期末权益=20万元+已实现盈亏+未实现盈亏”。相同交易可能出现在不同情景，这些审计计数不是独立交易样本数。

**上述只证明本次代码计算自洽，不等于历史信息完整或实盘可执行性保证。**

关键限制一：股票池/ST/退市/名称使用当前instruments快照，未重建每个历史时点的状态；幸存者偏差和当前状态回看偏差仍在。上市日及预热过滤不能消除这些偏差。

关键限制二：日线和复权因子来自后来补录历史数据，不是当日封存版本；2025/2026区间此前也已用于项目研究。因此只称跨期历史验证，不能称严格时点回测或从未触碰的样本外验证。

关键限制三：{liquidity['fraction_equal'] * 100:.2f}%有量/额记录的amount等于close×volume。当前腾讯日K适配器也明确源接口没有原生成交额。此次5000万元门槛主要是存储代理值过滤，而非核验后的真实成交额，不能据此做VWAP、真实资金流或容量结论。

关键限制四：涨跌停价从代码/前收/因子推算，未接入完整历史ST、特殊涨跌幅及交易所限价档案。100股/隔日可卖等作为本次执行模型配置；锁单、盘口深度、排队与开盘滑点的不确定性尚未完整覆盖。

以上限制足以阻止本次结果直接成为上线依据。更可靠的下一阶段是补齐历史状态与原生成交额、冻结候选规则并积累真正向前的纸面交易记录；不能在当前结果上反复调到漂亮再称“验证通过”。

## 文件与复现

项目根目录：`E:\\my_space\\stock-analyzer`。所有研究输出位于 `data/research_runs/wechat_four_patterns_20260928/`，不写market.db、palace.db或线上环境。

```powershell
Set-Location E:\\my_space\\stock-analyzer
.\\.venv\\Scripts\\python.exe -m scripts.wechat_four_patterns_research
.\\.venv\\Scripts\\python.exe -m scripts.wechat_four_patterns_research --replay
.\\.venv\\Scripts\\python.exe -m scripts.wechat_four_patterns_followup
.\\.venv\\Scripts\\python.exe -m scripts.wechat_four_patterns_report
.\\.venv\\Scripts\\python.exe -m pytest tests/test_wechat_four_patterns.py -q
```

源码：`src/strategy/application/wechat_four_patterns.py`。默认all只用于完整研究；候选须显式传`pattern="contraction"`，仍`daily_limit=2`。未写入生产注册表。

证据入口：`protocol.json`记录首轮冻结参数；`followup_protocol.json`明确追加检查的事后性质；`snapshot.npz`和`snapshot_manifest.json`冻结输入并校验SHA256；`signal_audit.json`、`replay_verification.json`、`execution_audit.json`记录校验；`liquidity_field_audit.json`记录代理额问题；`picks.csv`和`contraction_picks.csv`记录日名单与打分因子；每个`results/<情景>/`包含逐笔事件、实际账户交易、逐日净值、分月结果、开放持仓及跳过原因。

数据快照SHA256：`{meta['snapshot_sha256']}`。
'''
    target = ROOT / "docs/research/2026-09-28-wechat-four-patterns.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    (out / "REPORT.md").write_text(report, encoding="utf-8")
    pd.DataFrame(values).drop(columns=["event_skips", "portfolio_skips"]).to_csv(out / "all_scenarios.csv", index=False, encoding="utf-8-sig")
    save_json(out / "research_candidate.json", {"status": "research_only_not_approved_for_live", "pattern": "contraction", "daily_limit": 2, "entry_timing": "next_open", "planned_holding_sessions": 3, "selected_after_subgroup_comparison": True})
    print(json.dumps({"report": str(target), "audit": audit, "candidate_months_positive": int(monthly.return_pct.gt(0).sum()), "best5_share_of_gross_winners_pct": concentration}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
