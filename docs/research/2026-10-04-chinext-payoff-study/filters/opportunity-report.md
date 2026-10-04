# 固定原基准机会的净收益诊断

本诊断在名单冻结后追加，不改变训练名单或择参。每个原始成熟baseline的日期+代码为一笔等名义金额机会。未参加/明确未成交计已实现0；data_end、跨界等未知标NA；段末未成熟机会被剔除，绝不填0。个股过滤替补原第3+代码的收益另列，不能误归原股票。

同原代码机会均值包含不参与的0，解释对原股票机会的筛选；全部方案净收益/原基准机会数同时计入替补贡献，解释相同机会预算下的变化。只要涉及未知持仓，完整均值为NA，另列已知子集及计数。这些百分比按独立事件相加，不能解释为账户或组合收益。

|段|策略|方案|原成熟机会|成交|跳过|data_end|边界|每成交净期望%|同原代码机会均值%|含补位/原机会%|补位数|补位净和%|
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|train|contraction-rebreakout-v1|baseline|213|213|0|0|0|0.6011|0.6011|0.6011|0|0.0000|
|train|contraction-rebreakout-v1|index_ma20|213|105|0|0|0|0.2380|0.1173|0.1173|0|0.0000|
|train|contraction-rebreakout-v1|breadth_50|213|127|0|0|0|1.3959|0.8323|0.8323|0|0.0000|
|train|contraction-rebreakout-v1|stock_ma20_rising|213|178|0|0|0|0.0249|-0.2239|0.0208|13|52.1318|
|train|contraction-rebreakout-v1|momentum_0_30|213|192|0|0|0|0.5246|0.2907|0.4729|6|38.8162|
|train|contraction-rebreakout-v1|breakout_volume_le3|213|159|0|0|0|1.0160|0.6274|0.7584|26|27.9112|
|train|contraction-rebreakout-v1|relative_volume_le2_5|213|198|0|0|0|0.3253|0.3048|0.3024|2|-0.5087|
|train|contraction-rebreakout-v1|clv_ge0_75|213|152|0|0|0|0.6899|0.5392|0.4923|14|-9.9774|
|train|contraction-rebreakout-v1|prior_extreme_lt15|213|201|0|0|0|0.5404|0.4755|0.5100|8|7.3520|
|train|contraction-rebreakout-v1|historical_equal_four|213|213|0|0|0|0.5455|0.3536|0.5455|34|40.8848|
|train|impulse-inside-breakout-v1|baseline|156|156|0|0|0|0.2430|0.2430|0.2430|0|0.0000|
|train|impulse-inside-breakout-v1|index_ma20|156|94|0|0|0|1.4537|0.8760|0.8760|0|0.0000|
|train|impulse-inside-breakout-v1|breadth_50|156|95|0|0|0|0.8589|0.5230|0.5230|0|0.0000|
|train|impulse-inside-breakout-v1|stock_ma20_rising|156|140|0|0|0|0.0373|-0.1062|0.0334|6|21.7893|
|train|impulse-inside-breakout-v1|momentum_0_30|156|143|0|0|0|0.3579|0.3821|0.3280|7|-8.4318|
|train|impulse-inside-breakout-v1|breakout_volume_le3|156|142|0|0|0|0.2456|0.1670|0.2236|7|8.8190|
|train|impulse-inside-breakout-v1|relative_volume_le2_5|156|153|0|0|0|0.2349|0.2690|0.2303|2|-6.0294|
|train|impulse-inside-breakout-v1|clv_ge0_75|156|96|0|0|0|0.1321|0.1829|0.0813|9|-15.8572|
|train|impulse-inside-breakout-v1|prior_extreme_lt15|156|141|0|0|0|0.1108|0.0643|0.1002|1|5.5924|
|validation_2025h2|contraction-rebreakout-v1|baseline|103|103|0|0|0|-0.5216|-0.5216|-0.5216|0|0.0000|
|validation_2025h2|contraction-rebreakout-v1|breakout_volume_le3|103|86|0|0|0|-1.0261|-0.5664|-0.8567|10|-29.9014|
|validation_2025h2|contraction-rebreakout-v1|breadth_50|103|66|0|0|0|-0.8485|-0.5437|-0.5437|0|0.0000|
|validation_2025h2|contraction-rebreakout-v1|clv_ge0_75|103|80|0|0|0|-0.2455|0.0720|-0.1907|7|-27.0557|
|validation_2025h2|contraction-rebreakout-v1|historical_equal_four|103|103|0|0|0|-0.2759|-0.2811|-0.2759|20|0.5304|
|validation_2025h2|impulse-inside-breakout-v1|baseline|98|98|0|0|0|-0.2877|-0.2877|-0.2877|0|0.0000|
|validation_2025h2|impulse-inside-breakout-v1|breadth_50|98|56|0|0|0|-0.1886|-0.1078|-0.1078|0|0.0000|
|validation_2025h2|impulse-inside-breakout-v1|stock_ma20_rising|98|91|0|0|0|-0.1164|-0.0762|-0.1081|2|-3.1208|
|validation_2025h2|impulse-inside-breakout-v1|index_ma20|98|88|0|0|0|-0.2484|-0.2230|-0.2230|0|0.0000|
|observed_2026|contraction-rebreakout-v1|baseline|167|167|0|0|0|-0.4538|-0.4538|-0.4538|0|0.0000|
|observed_2026|contraction-rebreakout-v1|breakout_volume_le3|167|144|0|0|0|0.2500|0.0449|0.2156|19|28.5015|
|observed_2026|contraction-rebreakout-v1|breadth_50|167|105|0|0|0|-0.2590|-0.1629|-0.1629|0|0.0000|
|observed_2026|contraction-rebreakout-v1|clv_ge0_75|167|135|0|0|0|-0.6794|-0.5805|-0.5492|10|5.2304|
|observed_2026|contraction-rebreakout-v1|historical_equal_four|167|167|0|0|0|-0.0340|-0.2316|-0.0340|33|32.9983|
|observed_2026|impulse-inside-breakout-v1|baseline|111|111|0|0|0|0.6045|0.6045|0.6045|0|0.0000|
|observed_2026|impulse-inside-breakout-v1|breadth_50|111|59|0|0|0|0.9528|0.5064|0.5064|0|0.0000|
|observed_2026|impulse-inside-breakout-v1|stock_ma20_rising|111|99|0|0|0|0.9007|0.9336|0.8033|3|-14.4640|
|observed_2026|impulse-inside-breakout-v1|index_ma20|111|81|0|0|0|1.3569|0.9901|0.9901|0|0.0000|

所有模型均使用相同原基准成熟机会集合；原基准未成熟剔除数量及完整closed/skip/data_end/boundary守恒记录在JSON中，逐机会与补位CSV可核查。
