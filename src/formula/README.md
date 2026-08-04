# 公式（formula）

## 职责
通达信向量化函数、筹码、板块涨跌停、潜龙指标，以及 Screen Skill 的 P0 公式编译/求值内核。

## 边界
纯计算，无 IO、无包发现、无数据库、无 LLM。

## 关键入口
`MA`/`REF`/…；`compile_screen_formula()` / `evaluate_screen_formula()`；`src.formula.domain.qianlong`

## 如何扩展
新函数保持面板/Series 同构；Screen Formula 只扩显式注册表；补 `tests/formula/`。


## 给 Agent 的用法
- `from src.formula import MA, REF, COST, ...`
- `from src.formula import compile_screen_formula, evaluate_screen_formula`
- `ScreenFormulaManifest` / `ScreenFormulaParam` 描述 `screen.yaml` 语义字段
- 潜龙指标：`from src.formula.domain.qianlong import ...`
- 面板 DataFrame 与单票 Series 同构实现
- Screen Formula P0 字段：`OPEN/HIGH/LOW/CLOSE/VOL/AMOUNT/HSL`，其中 `HSL` 运行时映射 `turnover * 100`
- Screen Formula 公开目录：`screen_skill_catalog()`；编辑器只能展示该目录内的函数和日线字段
- `COST/WINNER` 已实现为 Python 公式 API，但暂不进入 Screen Formula 目录；它们依赖跨全历史的筹码递推，短窗口求值会产生伪精确结果。
- 已开放：`REF MA EMA SMA WMA DMA SUM HHV LLV STD AVEDEV COUNT EVERY EXIST FILTER BARSLAST BARSSINCE BARSCOUNT HHVBARS LLVBARS IF ABS MAX MIN CROSS ZTPRICE TR ATR RSI ROC WR CCI OBV MACD_DIF MACD_DEA MACD BOLL_MID BOLL_UPPER BOLL_LOWER`
- 技术指标口径：`RSI` 使用通达信 `SMA` 递推；`ATR` 使用真实波幅的 `MA`；`WR` 返回 -100 到 0；`BOLL_*` 使用样本标准差；`MACD` 返回 `(DIF-DEA)*2`，并可分别取 `MACD_DIF` / `MACD_DEA`。
- `HHVBARS/LLVBARS` 遇到相同最值时取离当前最近的一根；筹码函数的价格档位按截至当前日的已见高低价动态扩展，扩展时重映射存量筹码，不读取未来价格范围；遇到可观察的行情/换手缺失会从该日后返回空值，不用旧状态冒充准确成本
- `build_formula_explanation()` 从编译 IR 确定性生成中文步骤，不依赖 LLM
- `dialect=tdx/ths` 表示导入原稿的方言元数据；当前只兼容上述公共子集，不承诺通达信或同花顺全函数、画线指标、专家系统或五彩 K 线等价
- Screen Formula 的 `entry_timing` 支持 `next_dip`：信号日收盘后按 `dip_pct` 生成次日预挂价，具体成交由 backtest 统一判断

## README 维护
新增公式函数、改 P0 注册表或改通达信语义对齐时必须更新本文。

## 相关测试
`tests/formula/`
