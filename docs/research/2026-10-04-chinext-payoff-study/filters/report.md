# 创业板信号过滤隔离研究

原系统策略、原评分与出口均未修改。固定出口为次日开盘入场、含买入日第4日/-6%止损，无止盈；经济复权、T+1和严格涨跌停约束，单笔费用0.21%，双倍费用0.42%。所有方案及对照统一20交易日成熟缓冲，实际入场/退出也在对应段内；data_end与跨界不计已平仓。

过滤作用于完整形态候选后重新评分排序，最多每日2只。宽度仅固定50%，未搜索阈值；没有将只过滤原前2后的空缺伪装为完整候选排名。

2024年1月至2025年6月只开启训练。每策略按预注册资格与payoff/PF/mean排序冻结最多3个方案，然后才开启2025下半年留出期和2026已观察后验检验；不按后两段结果重选或调参。新策略原四项等权是历史已看过的固定对照。

2026年9月案例和该年回测已参与当前五权重评分设计，因此2026不能称完全未见样本外；2025下半年仅对本次过滤选择留出，基底策略本身并非2024年事前冻结。当前证券目录、名称/状态有历史成员与幸存者偏差。

|段|策略|方案|平仓|胜率%|平均盈亏比|利润因子|平均净收益%|双费用PF|去最大赢单PF|候选通过/原候选|替补原第3+|
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|train|contraction-rebreakout-v1|baseline|213|44.60|1.501|1.208|0.6011|1.130|1.154|407/407|0|
|train|contraction-rebreakout-v1|index_ma20|105|39.05|1.674|1.073|0.2380|1.008|0.986|214/407|0|
|train|contraction-rebreakout-v1|breadth_50|127|47.24|1.742|1.560|1.3959|1.456|1.466|290/407|0|
|train|contraction-rebreakout-v1|stock_ma20_rising|178|38.20|1.631|1.008|0.0249|0.943|0.931|274/407|13|
|train|contraction-rebreakout-v1|momentum_0_30|192|43.23|1.551|1.181|0.5246|1.104|1.110|327/407|6|
|train|contraction-rebreakout-v1|breakout_volume_le3|159|42.14|1.844|1.343|1.0160|1.261|1.177|277/407|26|
|train|contraction-rebreakout-v1|relative_volume_le2_5|198|43.94|1.421|1.114|0.3253|1.039|1.061|382/407|2|
|train|contraction-rebreakout-v1|clv_ge0_75|152|42.11|1.695|1.233|0.6899|1.155|1.158|259/407|14|
|train|contraction-rebreakout-v1|prior_extreme_lt15|201|45.77|1.413|1.192|0.5404|1.113|1.133|376/407|8|
|train|contraction-rebreakout-v1|historical_equal_four|213|46.01|1.405|1.197|0.5455|1.116|1.124|407/407|34|
|train|impulse-inside-breakout-v1|baseline|156|37.82|1.772|1.078|0.2430|1.010|0.948|219/219|0|
|train|impulse-inside-breakout-v1|index_ma20|94|42.55|2.030|1.504|1.4537|1.414|1.270|150/219|0|
|train|impulse-inside-breakout-v1|breadth_50|95|37.89|2.092|1.276|0.8589|1.200|1.062|147/219|0|
|train|impulse-inside-breakout-v1|stock_ma20_rising|140|32.86|2.066|1.011|0.0373|0.950|0.875|191/219|6|
|train|impulse-inside-breakout-v1|momentum_0_30|143|37.76|1.838|1.115|0.3579|1.046|0.972|186/219|7|
|train|impulse-inside-breakout-v1|breakout_volume_le3|142|37.32|1.810|1.078|0.2456|1.011|0.936|196/219|7|
|train|impulse-inside-breakout-v1|relative_volume_le2_5|153|37.91|1.760|1.075|0.2349|1.008|0.943|214/219|2|
|train|impulse-inside-breakout-v1|clv_ge0_75|96|40.62|1.524|1.043|0.1321|0.976|0.829|123/219|9|
|train|impulse-inside-breakout-v1|prior_extreme_lt15|141|37.59|1.721|1.036|0.1108|0.969|0.889|192/219|1|
|validation_2025h2|contraction-rebreakout-v1|baseline|103|38.83|1.285|0.816|-0.5216|0.753|0.732|166/166|0|
|validation_2025h2|contraction-rebreakout-v1|breakout_volume_le3|86|31.40|1.432|0.655|-1.0261|0.604|0.559|128/166|10|
|validation_2025h2|contraction-rebreakout-v1|breadth_50|66|34.85|1.341|0.717|-0.8485|0.663|0.593|124/166|0|
|validation_2025h2|contraction-rebreakout-v1|clv_ge0_75|80|40.00|1.368|0.912|-0.2455|0.844|0.801|112/166|7|
|validation_2025h2|contraction-rebreakout-v1|historical_equal_four|103|41.75|1.242|0.890|-0.2759|0.816|0.806|166/166|20|
|validation_2025h2|impulse-inside-breakout-v1|baseline|98|38.78|1.400|0.887|-0.2877|0.814|0.771|132/132|0|
|validation_2025h2|impulse-inside-breakout-v1|breadth_50|56|41.07|1.325|0.924|-0.1886|0.846|0.714|80/132|0|
|validation_2025h2|impulse-inside-breakout-v1|stock_ma20_rising|91|40.66|1.389|0.952|-0.1164|0.871|0.819|119/132|2|
|validation_2025h2|impulse-inside-breakout-v1|index_ma20|88|39.77|1.366|0.902|-0.2484|0.828|0.772|120/132|0|
|observed_2026|contraction-rebreakout-v1|baseline|167|37.72|1.427|0.864|-0.4538|0.809|0.810|283/283|0|
|observed_2026|contraction-rebreakout-v1|breakout_volume_le3|144|41.67|1.510|1.079|0.2500|1.012|1.012|221/283|19|
|observed_2026|contraction-rebreakout-v1|breadth_50|105|40.95|1.332|0.924|-0.2590|0.867|0.839|206/283|0|
|observed_2026|contraction-rebreakout-v1|clv_ge0_75|135|37.04|1.366|0.803|-0.6794|0.752|0.738|212/283|10|
|observed_2026|contraction-rebreakout-v1|historical_equal_four|167|40.72|1.440|0.989|-0.0340|0.923|0.898|283/283|33|
|observed_2026|impulse-inside-breakout-v1|baseline|111|44.14|1.542|1.218|0.6045|1.137|1.019|160/160|0|
|observed_2026|impulse-inside-breakout-v1|breadth_50|59|50.85|1.383|1.430|0.9528|1.321|1.250|101/160|0|
|observed_2026|impulse-inside-breakout-v1|stock_ma20_rising|99|45.45|1.599|1.333|0.9007|1.245|1.104|139/160|3|
|observed_2026|impulse-inside-breakout-v1|index_ma20|81|46.91|1.734|1.532|1.3569|1.431|1.235|121/160|0|

冻结方案：

- contraction-rebreakout-v1：breakout_volume_le3, breadth_50, clv_ge0_75。
- impulse-inside-breakout-v1：breadth_50, stock_ma20_rising, index_ma20。

胜率、平均盈亏比与利润因子分开记录；有限历史事件回测不等同于组合年化收益。双成本诊断只将相同成交的总费率翻倍，未模拟盘口冲击；最大赢家剔除是单笔依赖诊断，不用于验证后的模型选择。各信号/交易CSV、skip守恒、按信号月统计及冻结源SHA可复核。
