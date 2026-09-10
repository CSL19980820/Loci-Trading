归属：`/api/strategies*` `/api/backtest` `/api/analysis/*` `/api/screen/*` `/api/insights/*`。

`POST /api/analysis/{kind}` 返回 `job_id` 与本次真实 `run_id`；即时分析按请求快照执行，轮询可使用返回的 `poll`（`run_id` 精确过滤）。
`compare` / `optimize` 默认以 `execution_mode=process` 交给受控 `spawn` worker，避免大面板计算占满 API 进程；调试或小样本可在请求体中显式传 `execution_mode=thread`。
说明：`/api/screen-skills*` 的 HTTP 契约在本域 `api/screen_skills_router.py`，编排在 `application/screen_skills.py`（2026-08 从组合根搬入）；包读写经 `src.ops` 包根，公式编译与选股执行也在本域。

选股响应：
- `picks` 是沿用战法 `entry_timing` 与正式回测口径的精选；`watch_picks` 是弱市降级的低吸观察，形状与 `picks` 一致并带 `intent=observe`。观察票可用 `decision=观察` 留档，但不计正式胜率、不进入自动次日开盘预案。

回测：
- `POST /api/backtest` — `mode=trade`（默认，成交回测）或 `mode=horizon`（T+1/T+3，标记日最高/选股日收盘；须 start/end，跨度 ≤186 天）
- `mode=trade` 响应新增 `performance`（顺序复利诊断曲线；见 `src/backtest/README.md`）；`metrics` 仅追加字段
- `mode=trade` 请求可传 `commission_bps` / `stamp_duty_bps` / `slippage_bps`（默认 3 / 10 / 5）
- `mode=horizon` 的 `horizons.t*` 追加 median/std/分位数/收盘口径/分月等，不造资金曲线

版本：
- `GET /api/strategies/{slug}/versions` 与 `POST /api/strategies/{slug}/rollback` 供策略详情页统一使用；Screen Skill 按包归档 SHA 回滚，旧 Python 自定义策略继续按整数版本回滚。回滚请求写入前受统一写权限保护；当前修订不会同时出现在历史列表，回滚前 active 修订保留为唯一历史快照。

洞察：
- `GET /api/insights/decay` — 战法复盘胜率衰减（选股目录消费）
- `GET /api/insights/overlap` — 选股信号重叠（Jaccard + 常撞代码；非持仓风险）
- `GET /api/strategies/{slug}/audit` — 前视静态审计（生成链/测试用，体检页不挂）

挂载与文件清单：
- `router.py` → `build_strategy_router`：聚合入口。自留 `POST /api/strategies/screen`（同步单日）、`POST /api/analysis/{kind}`、`GET|PUT|DELETE /api/strategies/{slug}/job`、`/api/strategies/{slug}/doc`、`/api/insights/*`、`/api/strategies/{slug}/audit`；并 `include_router` 下面这几个子 router
- `screen_today_router.py` → `build_screen_today_router`：`GET /api/screen/today`；可选轻量同步与热库镜像，选股阶段与其他入口共用进程级容量许可，容量已满快速返回 429
- `screen_run_router.py` → `build_screen_run_router`：异步即时选股三端点，**都以 `strategy` 为轴**（进度槽按「租户 × 战法」分片，一个人可以同时跑多个战法）：
  - `GET /api/screen/run`：不带参 → 聚合快照（顶层是「当前这一个」槽，兼容老客户端；`runs` 是 slug → 槽，`running_strategies` 是正在跑的 slug，`max_concurrent_runs` 是并发上限）；带 `?strategy=` → 只要那一个槽（不存在返回 idle，不建槽）
  - `POST /api/screen/run`（202 受理）：返回**这个战法**的槽快照；占不到槽时带 `busy_reason`（`same_strategy` = 它自己在跑，防重复入库；`tenant_limit` = 并发到顶）。别的战法在跑不算占用
  - `POST /api/screen/run/cancel?strategy=`（202 受理，协作式取消）：点名停一个；**省略 `strategy` 停全部**（老客户端语义），返回 `cancelled_strategies`
- `screen_history_router.py` → `build_screen_history_router`：`GET /api/screen/history` 与 `/batch`
- `version_router.py` → `build_strategy_version_router`：`/api/strategies/{slug}/versions`、`/rollback`
- `screen_skills_router.py`：`/api/screen-skills*`
- `screen_universe.py` → `effective_screen_universe`（**非路由**）：同步 `/api/strategies/screen` 与异步 `POST /api/screen/run` 共用的行情范围口径。两端必须给出同一个 universe，拷两份必然漂移，所以只留一份
- `src.strategy.api.convert.build_strategy_convert_router`（转换器 / 自定义策略）

本域 router 一律用 `_write: None = write_guard` 默认参数风格声明写权限依赖，**不要**改成 `Annotated[..., Depends(...)]`——那是 community 两个 router 为了绕开 `from __future__ import annotations` 才用的写法，本域各文件都带该 future 导入。

策略目录返回 `entry_instructions` 时，前端战法详情以“买入说明”展示；内置战法首次读取目录时会将默认简述写入 `ops.db.strategy_docs`，已有非空人工内容优先保留。该字段只描述执行预案，不改变 `entry_timing` 或回测成交逻辑。

战法定时（工坊详情保存）：
- `GET|PUT|DELETE /api/strategies/{slug}/job` — 绑定 `screen:{slug}`；`schedule_mode` 合成交易日 cron；`universe` 写入 config 供选股 Job 消费；`next_runs` 为完整 `YYYY-MM-DD HH:MM`。`interval` 的 cron 按小时粗触发，执行前会按配置的起止分钟再次闸门，预览只显示窗口内可执行时刻。
- 盘后默认点：`once` @ **15:30**（`run_hour=15`/`run_minute=30` → cron `30 15 * * 1-5`）；战法可声明托管时点与输出上限。三源 / 杨氏收盘档：`sanyuan-tail-v1` / `yangshi-tail-v1` 为 15:30（最多 2 / 1 只）。14:50 两档（`sanyuan-tail-1450` / `yangshi-tail-1450`）已删除，启动时删旧 `screen:*-1450`；`qianlong-tail-v1` 已下线，启动时 `ensure_managed_screen_jobs` 会删掉旧的 `screen:qianlong-tail-v1`；lifespan 启动与 screen-skill 变更时对齐全部引擎战法（已存在任务仅合并配置，保留用户自定义键）
- `schedule_mode=off`：**剔除**绑定（DELETE 等价），不留 `enabled=false` 尸位；工坊「定时」台对 `screen:*` 只读，改配置只走战法详情

由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。
