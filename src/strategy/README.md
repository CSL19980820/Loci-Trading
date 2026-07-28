# 策略（strategy）

## 职责
战法协议、内置/自定义选股、审计与 AI 转换。

## 边界
依赖 market 面板与 formula；不写账本。

## 关键入口
`StrategyEngine`（domain/base）；`screen`；HTTP：`/api/strategies/*` `/api/screen/*`

## 如何扩展
新战法：实现 Protocol，放 application/，在包 __init__ 侧效 import 注册；声明 entry_timing。


## 给 Agent 的用法
- 注册战法：实现 `StrategyEngine`，放 `application/`，在包 init 侧效 import
- 选股：`from src.strategy import screen, get`
- 必须声明 `entry_timing`；补前视审计测试
- 自定义策略目录：`infrastructure/custom/`

## README 维护
新增/下线战法、改 Protocol 或选股入口时必须更新本文。

## 相关测试
`tests/strategy/`
