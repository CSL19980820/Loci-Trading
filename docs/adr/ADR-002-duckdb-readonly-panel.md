# ADR-002：market 面板 DuckDB 只读旁路

**状态**：已采纳  
**日期**：2026-07-28  
**相关**：[`src/market/infrastructure/duckdb_panel.py`](../../src/market/infrastructure/duckdb_panel.py)、技术雷达 P0

## 背景

全市场 `load_panel` 是选股/回测热路径，现用 SQLite + pandas pivot。数据量上来后内存与耗时压力会增大；社区同业常用 DuckDB 做嵌入式 OLAP。账本 `palace.db` 必须保持不可变审计，不能被分析引擎「顶替」。

## 决策

1. **权威仍在 `market.db`（SQLite）`quotes_daily` / 复权因子**；DuckDB 只做只读加速旁路。  
2. **默认关闭**：环境变量 `LOCI_MARKET_DUCKDB=1|true|yes|on` 才启用。  
3. **失败必须回退** pandas/`pd.read_sql_query`，公开 HTTP 字段与 URL 不变。  
4. **禁止** DuckDB 写 `palace.db`、禁止把推导指标固化成第二套权威表。  
5. 旁路可整段删除而不影响账本语义（可重建缓存哲学）。

## 后果

- 优点：可渐进加压测；单机桌面无额外部署。  
- 约束：Windows 路径/扩展加载异常时走回退；性能收益需实盘数据验证后再考虑默认开启。  
- 测试：`tests/market/test_duckdb_panel.py` 对齐开关开/关结果。
