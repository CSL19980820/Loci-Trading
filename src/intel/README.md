# 情报（intel）

## 职责
MCP/外部情报接入与限流；补本地行情仓算不出的数据。

## 边界
配置 mcp.json；大批量量价仍走 market。

## 关键入口
`McpClient` / registry / builtin_market_mcp；HTTP：`/api/mcp/*`

## 如何扩展
新 MCP server：写入 mcp.json 或 registry API。


## 给 Agent 的用法
- MCP：`from src.intel import McpClient, McpTool, build_client, collect_tools, list_effective_mcp_servers`
- 配置读写：`load_mcp_json_raw` / `upsert_mcp_server_json`；文件 `data/mcp.json`
- 内置行情工具见 `builtin_market_mcp`（经包根 registry 导出）
- 大批量量价仍走 market，不走 MCP 扫全市场
- 禁忌：跨上下文深掏 `src.intel.infrastructure.*`

## README 维护
改 MCP 契约、限流、内置工具时必须更新本文。

## 相关测试
`tests/intel/`
