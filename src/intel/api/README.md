归属：`/api/mcp*`。

挂载：`src.intel.api.router.build_intel_router`，由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。

- `GET /api/mcp`：有效清单（含内置 `loci-market`，含 `tools_catalog`）
- `POST /api/mcp`：注册/更新（可握手校验）
- `POST /api/mcp/{name}/refresh`：重新发现工具；外部 MCP 暂不可用时返回 `503`
- `POST /api/mcp/{name}/probe`：服务级连通性；不接受工具或参数，不执行第三方工具；成功会刷新工具清单
- `PATCH /api/mcp/{name}` / `DELETE /api/mcp/{name}`：启停 / 删除（内置不可）
