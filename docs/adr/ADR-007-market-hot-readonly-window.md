# ADR-007：market 读写双库与热读窗口

**状态**：已采纳  
**日期**：2026-08-06  
**相关**：[`src/market/infrastructure/store_hot.py`](../../src/market/infrastructure/store_hot.py)、[`src/ops/application/jobs/hot_rebuild.py`](../../src/ops/application/jobs/hot_rebuild.py)、ADR-002（DuckDB 只读旁路）

## 背景

全量 `market.db` 体量大，尾盘选股与同步写锁同文件争用时易出现 disk I/O / 超时。选股与行情面板通常只需近若干年日 K（覆盖 MA250 等），不必每次扫全历史。账本 `palace.db` 与行情权威库语义不变；需要一层可重建、与写库物理隔离的只读窗口。

## 决策

1. **权威仍在 `market.db`（SQLite）**：同步、spot、bootstrap、证券列表刷新等写路径只写全量库。  
2. **热读库 `market_hot.db`**：近 `HOT_WINDOW_TRADING_DAYS`（默认 **700** 交易日）窗口镜像；schema 与 `MarketStore` 一致；日 K / 日历只留窗口，`instruments` / `adjust_factors` 全量复制，回执仅保留窗口内日 K 关联行。路径：`paths.market_hot_db()`（`PALACE_MARKET_HOT_DB` 可覆盖）。  
3. **增量 / 重建**：`mirror_recent_to_hot`（sync / spot 写全量成功后）、`mirror_to_hot`（`kind=hot_rebuild` 全量重灌）。复制后按当前窗口起点 **裁掉窗外**（`trade_date < keep_from`）并清理孤儿回执。  
4. **镜像失败不阻断 sync**：热库是派生缓存；失败只记 warning / payload 字段，同步结果仍成功。  
5. **选股默认读热库**：`requires_full_history` 的策略、未配置热库、镜像失败或热库末日落后于全量时，**回退全量库**选股（不以「哨兵」假装修好热库）。  
6. **禁止**把热库当第二套权威事实；损坏可删库 + `hot_rebuild` 重建，零双真相。

## 后果

- 优点：选股 / 行情 HTTP 读与全量写锁物理隔离；热库体量约为全量的一小截。  
- 约束：触价提醒、MCP `instruments_search`、行情面板读端走热库；复盘资金曲线 / 往返 / 候选 T+N 等长窗仍读全量库。长历史公式必须声明 `requires_full_history`。  
- 测试：`tests/market/test_hot_window.py`、`tests/ops/test_hot_rebuild.py`、`tests/strategy/test_screen_run_hot.py`。
