归属：`/api/strategies*` `/api/backtest` `/api/analysis/*` `/api/screen/*` `/api/insights/*`。

`POST /api/analysis/{kind}` 返回 `job_id` 与本次真实 `run_id`；即时分析按请求快照执行，轮询可使用返回的 `poll`（`run_id` 精确过滤）。
说明：`/api/screen-skills*` 虽服务于公式工坊，但契约与包读写编排归 `src.app.screen_skills_api`；本域只负责编译后的 `StrategyEngine` 与选股执行。

回测：
- `POST /api/backtest` — `mode=trade`（默认，成交回测）或 `mode=horizon`（T+1/T+3，标记日最高/选股日收盘；须 start/end，跨度 ≤186 天）

版本：
- `GET /api/strategies/{slug}/versions` 与 `POST /api/strategies/{slug}/rollback` 供策略详情页统一使用；Screen Skill 按包归档 SHA 回滚，旧 Python 自定义策略继续按整数版本回滚。回滚请求写入前受统一写权限保护；当前修订不会同时出现在历史列表，回滚前 active 修订保留为唯一历史快照。

洞察：
- `GET /api/insights/decay` — 战法复盘胜率衰减（选股目录消费）
- `GET /api/insights/overlap` — 选股信号重叠（Jaccard + 常撞代码；非持仓风险）
- `GET /api/strategies/{slug}/audit` — 前视静态审计（生成链/测试用，体检页不挂）

挂载：
- `src.strategy.api.router.build_strategy_router`
- `src.strategy.api.convert.build_strategy_convert_router`（转换器 / 自定义策略）

策略目录返回 `entry_instructions` 时，前端战法详情以“买入说明”展示；内置战法首次读取目录时会将默认简述写入 `ops.db.strategy_docs`，已有非空人工内容优先保留。该字段只描述执行预案，不改变 `entry_timing` 或回测成交逻辑。

战法定时（工坊详情保存）：
- `GET|PUT|DELETE /api/strategies/{slug}/job` — 绑定 `screen:{slug}`；`schedule_mode` 合成交易日 cron；`universe` 写入 config 供选股 Job 消费；`next_runs` 为完整 `YYYY-MM-DD HH:MM`。`interval` 的 cron 按小时粗触发，执行前会按配置的起止分钟再次闸门，预览只显示窗口内可执行时刻。
- 盘后默认点：`once` @ **15:30**（`run_hour=15`/`run_minute=30` → cron `30 15 * * 1-5`）；战法可声明托管时点与输出上限，`qianlong-tail-v1` 为 14:50、最多 1 只，`sanyuan-tail-v1`（当前运行版本 V2）为 15:30、最多 2 只；lifespan 启动与 screen-skill 变更时经 `ensure_managed_screen_jobs` 对齐全部引擎战法（已存在任务仅合并配置，保留用户自定义键）
- `schedule_mode=off`：**剔除**绑定（DELETE 等价），不留 `enabled=false` 尸位；工坊「定时」台对 `screen:*` 只读，改配置只走战法详情

由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。
