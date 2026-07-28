# CLI

## 职责
薄命令行入口，转发到各限界上下文。

## 边界
无业务逻辑。

## 关键入口
`python -m cli.ledger|market|ops|review|serve`

## 如何扩展
新命令：加 cli/<name>.py，内部调 src.<context>。

## 相关测试
手工 / 对应上下文单测
