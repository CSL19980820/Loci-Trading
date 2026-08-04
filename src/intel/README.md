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
- 内置行情工具见 `builtin_market_mcp`（经包根 registry 导出）；日线、分钟线、资金流都只经 `src.market` 的公开 routed API 取数，必须尊重 lane 启停与用户的 auto/manual/fallback 策略，返回实际 source。
- **内置清单跟着数据源启停走**：`list_builtin_tools()` 先按 `_LANE_BY_TOOL` 用 `enabled_adapter_ids(lane)` 过滤（该 lane 没有可用源就不给模型这个工具），再追加已上桌的 AkShare 接口。`instruments_search`（本地 market.db 检索）与 `lanes_catalog`（元信息）不依赖线路，始终在清单里。
- **UI 全量目录**：`builtin_server_record()["tools_catalog"]` 含全部内置行情工具（`group=lane`，无源标 `available=false`）+ 已上桌 AkShare（`group=akshare`）。运维 MCP 详情读这个字段；`tools` 仍只给 AI/兼容用的生效清单，勿把 catalog 塞进 `collect_tools`。
- **连通性探测**：`probe_mcp(name)` / `POST /api/mcp/{name}/probe` 只做握手、工具发现与清单刷新，绝不执行第三方工具；请求体不接受 `tool` 或 `arguments`。
- **外部 HTTP MCP**：仅允许直连公网 HTTPS，客户端不读取系统代理；本地 HTTP 仅在 `PALACE_MCP_LOOPBACK_HTTP_HOSTS` 明确列出回环主机时可用。首次发现工具或调用工具前会先完成 `initialize` 握手并复用会话 ID；`mcp.json` 的自定义 `headers` 原样传递。工具分页拒绝重复游标和超过 50 页的响应，响应、schema 与工具参数都有上限；刷新遇到外部服务不可用时接口返回 `503`，整服探测返回 `ok=false`。
- AkShare 接口工具：`builtin_akshare_tools.py`，固定工具名 `akshare_call`（兼容旧 `ak_<接口名>`），经 `probe_stock_capability` 受控执行；**不再维护上桌名单**。目录浏览 / 一键全测 / 版本检查在工坊「数据源」→「按接口」。
- 大批量量价仍走 market，不走 MCP 扫全市场
- 禁忌：跨上下文深掏 `src.intel.infrastructure.*`；也不要从 intel 深掏 `src.market.infrastructure.*`

## README 维护
改 MCP 契约、限流、内置工具时必须更新本文。

## 相关测试
`tests/intel/`
