# AI（ai）

## 职责
通用 LLM 供应商、对话、Agent / toolbus。不发明数字。

## 边界
密钥经 ops 存储加密；计算结论以 review/strategy 为准。

## 关键入口
`chat` / `run_agent` / `build_toolbus`；HTTP：`/api/providers/*` `/api/ai/*`

## 如何扩展
新工具挂 toolbus；新协议扩展 infrastructure/client。


## 给 Agent 的用法
- 对话：`from src.ai import chat, ChatMessage, ToolCall, resolve_config`
- Agent/工具：`application/agent.py`、`application/toolbus.py`（本域也可 `from src.ai import ...`）
- 禁忌：生成权威行情/盈亏数字；跨上下文深掏兄弟域 `infrastructure`

## README 维护
改协议、工具清单、密钥处理时必须更新本文。

## 相关测试
`tests/ai/`
