# 共享内核（shared）

## 职责
跨限界上下文的横切能力：数据根路径、桌面快捷方式。不含业务规则。

## 边界
- 可被所有上下文依赖
- 禁止依赖 ledger / market / review 等业务包（paths 内延迟 import 建库除外）

## 关键入口
- `src.shared.paths` — `data_dir` / 三库路径 / `ensure_data_dir`
- `src.shared.desktop_shortcut` — 创建桌面快捷方式

## 如何扩展
新增真正横切的工具放这里；一旦带业务语义，改放到对应上下文。


## 给 Agent 的用法
- 路径唯一入口：`from src.shared.paths import data_dir, palace_db, market_db, ops_db`
- 禁止在业务里硬编码 `data/palace.db`

## README 维护
改路径解析优先级或布局约定时必须更新本文。

## 相关测试
`tests/shared/`（如有）
