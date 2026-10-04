# 二次突破前瞻验证：最小实际缺口

2026-10-04，仅核对当前源码、只读快照和已有研究产物；未再查生产状态、取实时行情、计算新收益、部署或创建任务。

**已完成有增量价值的最小工件：把9月30日闭市数据变成10月8日计划目标日的完整T−1必要池及不可变manifest。** 旧预池最新目标日为9月30日，`prepare()`实际只读取到9月29日（`dates[:-1]` / `end=dates[-2]`），因此没有等价完成这份下一日准备。新[`本地准备器`](../../../tools/research_contraction_forward_prepare.py)直接复用已验证的[`past_features`](../../../tools/research_contraction_intraday_prepool.py#L48)、直接因子读取和经济坐标规范化，未改冻结旧脚本。

结果见[`contraction-prepared/manifest.json`](contraction-prepared/manifest.json)：实际准备时间2026-10-04 18:34:23+08:00，1,408只完整目录，98只纯必要池；其中96只当前身份标记通过，300290、300352两只ST标记股票仍纳入完整后续观测清单，待T日复核。1,310只未通过过去条件或质量门槛，逐只保留原因；其中两只新股只有6/2条历史，不能满足至少30根。另存最近13市场日共18,304行原始OHLCV/amount/来源及逐行直接因子出处。前缀19字段、上一目标日112个池键和完整工件重放均通过；无T日输入或排名。10月8日由[官方日程证据](exchange-session-evidence.json)及已有年度日程交叉确认，仅作计划日期，不放宽现场日历闸门。

可在项目根目录只读重放：`.\.venv\Scripts\python.exe tools/isolated_check.py tools/research_contraction_forward_prepare.py verify`。manifest的`candidate_codes`就是98只完整必要池，不能用`current_static_clean`先减成96只。

另经[独立复核](method-decision.md#本地成品的独立复核)：未导入准备器，直接SQL逐项核对18,304行原值及因子出处，从1,408只全目录独立重建相同98码，并核对1,078个候选特征值；全部数据库、源码和产物hash相符。

这份工件确定了下一次需要观察的股票、数量和过去输入，绑定现有只读快照、原始数据/源码hash及实际取得时间。当前名称/状态只按实际可见版本留存，不能冒称9月30日历史PIT身份；T日身份、T日权益因子和原价前收桥接均明确待补，没有把9月30日因子前推为已知未来因子。

## 可以复用什么，仍缺什么

| 环节 | 当前能力与具体缺口 |
|---|---|
| T−1完整必要池 | 上述纯函数已经证明历史前缀因果性及原日线候选覆盖。生产[`screen_prepare`](../../../src/ops/application/jobs/screen_prepare.py#L19)只接收`requires_realtime_inputs`，且调用double-yin准备；contraction现役仍是[`next_open`日K策略](../../../src/strategy/application/contraction_rebreakout.py#L55)，不能称其已接通这条准备任务。 |
| 现场可见输入 | [`fetch_live_hq`](../../../src/market/infrastructure/sina.py#L251)能批量给O/H/L、现价、累计量额、源日期/时间；仓内日K和直接因子已经可读。还需按**冻结必要池全部代码**保存原始响应、accepted/rejected、请求/接收时钟、单位、源日期时间及输入hash。解析器会回填非正现价/前收，须保留原字段或回填标志；不能把回填事实当原生报价。 |
| 完整性 | [`fetch_cross_section`](../../../src/market/application/cross_section.py#L60)以90%有效覆盖即可返回，并跳过缺项、允许15秒缓存；不等价于研究完整池。未来要逐只对账，缺一项不能把残池当完整Top2。各源时点和批次跨度也须保留，不能把先后收到的报价宣称同一秒。 |
| 不可变留存 | 可复用[`CaptureSpec/capture_snapshots`](../../../src/market/application/intraday.py#L22)及存储格式；当前默认只有`spot_close`。[`write_snapshot`](../../../src/market/infrastructure/intraday_archive.py#L120)同日同dataset覆盖，不能直接当不可变多时点证据。后续若采集，要用独立研究目录、唯一阶段/请求标识和拒绝覆盖的回执，并显式记录空池及失败；不必新建服务或改生产定时任务。 |
| 决策后价格 | 现有[`fetch_minute_bars`](../../../src/market/application/minute.py#L125)可读分钟来源；历史TDX240点没有原生时间的限制已确认。未来应另外记录决策完成之后取得的源报价/时间和成交量状态，不能用决定形成前已经发生的同一价格充当成交。没有订单回报或盘口路径时，只能标为价格代理。 |

## 外部条件与停止边界

下一目标日预池已用现有快照离线准备；真正的前瞻决策和后续价格必须等目标交易窗口、可用上游、完整报价覆盖及当时可见因子/身份。这些未来事实不能靠本地脚本现在完成。代码存在也不等于本次已现场验证其覆盖和时效；本支线不启动网络采集。

现有文档已经覆盖完整池、原始报价和决策后证据的总体要求，见[已有可行性结论](../2026-10-04-contraction-intraday-feasibility/report.md)。不需要泛化采集框架；根研究另行准备的**手动单次现场封存入口**只需消费这份manifest，按固定完整代码留存现场输入并区分决策后输入。它的验收是可重放和缺项不隐匿，不是收益通过；本支线仅交付离线准备器与工件，没有实现或运行现场采集。

结构、learned-rank、VWAP及本次sampled_early均没有通过各自冻结验收；其中[sampled_early训练净均值为负](../2026-10-04-contraction-sampled-entry/report.md)。准备未来输入既不会推翻这些结果，也不会自动产生一个值得提名的增强机制。前瞻若继续，须在未来数据出现之前固定要检验的政策、执行/费用、比较日历和结束判据，再积累未见样本。**封存一次完整预池或成功采到报价，只能完成证据准备；用户要的策略增强仍要由完整交易机会、成本和后续独立表现证明。**
