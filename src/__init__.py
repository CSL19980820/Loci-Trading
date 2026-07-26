"""stock-analyzer: A 股个股持仓分析工具

模块划分:
- fetcher:   数据采集(行情/K线/资金流/财务/研报/股东/龙虎榜)
- indicators: 技术指标(MA/MACD/RSI/BOLL) + VWAP + 筹码 + 波动率 + 概率
- strategy:  持仓诊断 + 三档情景观察规则引擎
- discovery: 提前发现雷达(产业证据/量价资金/反证剔除)
- reporter:  报告渲染
- toolbox:   买入检查/风险雷达/组合分析/多格式导出
"""
__version__ = "0.1.0"
