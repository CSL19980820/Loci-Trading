# 公式（formula）

## 职责
通达信向量化函数、筹码、板块涨跌停、潜龙指标。

## 边界
纯计算，无 IO。

## 关键入口
`MA`/`REF`/…；`src.formula.domain.qianlong`

## 如何扩展
新函数保持面板/Series 同构；补 tests/formula。


## 给 Agent 的用法
- `from src.formula import MA, REF, COST, ...`
- 潜龙指标：`from src.formula.domain.qianlong import ...`
- 面板 DataFrame 与单票 Series 同构实现

## README 维护
新增公式函数或改通达信语义对齐时必须更新本文。

## 相关测试
`tests/formula/`
