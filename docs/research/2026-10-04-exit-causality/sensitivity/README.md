# 固定开盘缺口敏感性

按[唯一冻结合同](../SENSITIVITY-PLAN.md)完成，限于 11 组既有订单：12 个政策订单采用首次止损触发日的原开盘代理退出，2,010 个其余订单逐字段保持不变。12 个政策订单对应 11 个独立入场 basis；没有重新排序、补位或资金重跑。

12 笔净值均改善，但二次突破早买训练组、倍量阴 B 的两个后段全部不变，旧严格失败不变。这是执行模型的有限敏感性，不是新 alpha 或现实可成交证明。2 条原 unknown 与 8 条取消完整保留；未知组的完整名额统计仍为 null。

- [结果说明](REPORT.md)：五个变化组和六个不变组的旧/新指标及边界。
- [逐笔变化](changed-orders.csv)、[11 组汇总](summary.json)、[完整日历](daily-budget.csv)：原分母及费用不变。
- [计算前冻结回执](freeze-receipt.json)、[SQL 事实核对](sql-validation.csv)、[核心产物回执](completion-receipt.json)：保存源和产物哈希。
- [根代理独立复核](../root-sensitivity-check.json)：独立重建 11 组来源、直接 SQL 核验 12 个新 O/因子、2,010 个未变订单、毛净收益/PF/胜率/四项压力及每日预算，结果通过。

本次工具 `tools/research_exit_gap_sensitivity.py` 的 F 级静态检查通过；这不代表整个研究目录均无静态检查告警。未修改任何冻结脚本来消除既有告警。研究至此结束，不追加其他卖点或参数实验。
