# Loci GitHub 开源技术雷达（项目级）

> **调研日**：2026-08-08（UTC+8）  
> **覆盖**：197 个不同 GitHub 仓库；按数据/存储、Python/API、量化、前端、构建/桌面、任务可靠性、可观测/测试/安全、AI/MCP/RAG、架构/开发工具分组。  
> **结论性质**：候选 ≠ 建议。项目清单用于建立可复核的技术雷达，优先级还要经过本仓 POC、性能基线、许可证复核和回滚演练。

## 1. 方法、证据与限制

1. 先确认 `gh`：本机未安装 GitHub CLI；随后检查公共 REST API，匿名 core 配额为 0，因此没有把 API 取不到的字段猜成事实。
2. 改用 GitHub 官方仓库页面（`https://github.com/{owner}/{repo}`）逐项核验。页面元数据中的 `stargazerCount`、`forksCount`、许可证和仓库描述作为快照；每一行都保留 GitHub 一手链接。
3. 页面中可稳定取到的 stars/forks/许可证写入清单；**最近更新字段统一标为“未核验”**（页面最新提交区是懒加载，匿名 API 又已耗尽）。许可证未稳定暴露的项目写“未核验”，不据此推断许可兼容性。
4. GitHub stars/forks 是 2026-08-08 的观测值，不是质量、活跃度或安全性的证明；许可证仍须在采用前阅读仓库 LICENSE、依赖许可证和商业条款。清单中原先 10 个失效/错误归属的候选已替换为正确官方仓库（例如 `simonw/sqlite-utils`、`giampaolo/psutil`、`r0x0r/pywebview`、`weaviate/weaviate`）。
5. 现状反向映射只引用本仓在本次调研日读取到的 README、CI、依赖和源码；“风险”表示结构性待测项，不等于已发生事故。旧报告 [`2026-07-loci-tech-radar.md`](./2026-07-loci-tech-radar.md) 已覆盖大量官方文档，本报告刻意改为**GitHub 项目级**证据，不复制其文献索引。

## 2. 先给结论

- 不换 Vue/FastAPI、不整库换 Element Plus、不把 `palace.db` 迁走；最确定的收益来自**现有旁路的基线化**：Polars/DuckDB 读侧、候选池/行情表虚拟化、后台任务指标、依赖供应链扫描。
- 当前已有不少候选的依赖或 POC：DuckDB、vectorbt、Pinia Colada、Comlink、rolldown-vite、Vitest、Playwright、Monaco。它们应进入“验证/治理”而不是再次盲目引入。
- 单机桌面边界下，Redis/Celery/Kafka/RabbitMQ/Temporal/ClickHouse/大型向量库都不是近期默认答案；它们可作为多进程/多用户阶段的观察样本。
- 数据质量优先于模型数量：所有行情、复盘、回测数字仍由 `market`/`review`/`strategy`/`research` 产生；AI/MCP 只能消费有来源、时间和 hash 的证据，不能把检索结果提升为权威事实。
- 量化项目大多是“借鉴测试、执行时点、组合分析”的来源，不是把外部交易引擎直接接入 Loci；A 股、`entry_timing`、禁止前视和三库隔离是硬闸门。

## 3. 从本仓反向映射出的实际问题

证据时间均为 2026-08-08；文件路径是仓内可核查的一手证据。

| 领域 | 已确认事实 | 风险/机会（标明推断） |
|---|---|---|
| 性能与大数据 | `requirements.txt` 已有 DuckDB、vectorbt；`src/market/README.md` 记录 `market_hot.db` 700 交易日只读镜像和 DuckDB 旁路；研究/因子执行器分别有单线程池。 | **待测**：全市场面板、研究回测和 1000 行候选池仍需 wall-time、内存和尾延迟基线；Polars/Arrow/DuckDB 只能读 `market`/缓存，不能成为账本真相。 |
| SQLite/线程 | 三个 Store 使用 WAL、`busy_timeout`（market 60s、ledger 30s、ops 30s）；行情适配器和同步使用线程池；`src/ops/infrastructure/scheduler.py` 明确 APScheduler 是进程内单例且多 worker 会重复触发。 | **结构性风险**：长同步、研究读、spot 写和桌面/CLI 并行时仍需锁等待、重试、连接数、`database is locked` 计数；不要靠引入 broker 掩盖未测的 SQLite 事务边界。 |
| 重任务 | 研究 factor/backtest 使用受限线程池；Job 通过 ops.db 认领、回收 stale run 和记录终态；现有 APScheduler 适合单机。 | **待测**：进程崩溃、桌面休眠、任务超时、重复触发和取消语义应有可观测指标；Taskiq 仅在“必须隔离 worker”时做 POC。 |
| 数据质量 | `src/market/README.md` 已有 provider lane、source receipt、OHLC 拒绝、watermark、健康门禁和热库；`src/research/README.md` 要求 frozen input、PIT、hash、`not_observed` 缺口。 | **机会**：把供应商字段契约、回执完整率、覆盖率、坏 OHLC 比、可重放性做成 CI/Job 指标；不要用 AI 或第三方回测库补齐缺失历史。 |
| 前端大表/包体 | `frontend/package.json` 已锁定 Bun、Vue 3.5、Vite 7、Element Plus、ECharts 6、Pinia Colada、Comlink、Monaco、Vitest、Playwright 和 rolldown-vite；`PoolView.vue` 请求 `limit: 1000`，多数业务表是 Element Plus 表格。 | **待测**：1000+ 行、筛选、实时叠价、K 线重绘和桌面 WebView2 的 INP/内存/包体需基线；优先 TanStack Virtual 或现有 EP 虚拟表的局部验证，不换 UI 库。 |
| AI/MCP 治理 | `src/ai` 有固定 System ToolBus、`ExecutionGrant`、MCP 最大 48 工具、参数 clamp，明确禁止 shell/raw SQL/真实下单；富状态事件和 SSE 已持久化。 | **机会**：补 MCP schema/权限/超时/配额/证据回执契约测试；FastMCP/官方 SDK 只作为适配器和测试样本，不绕过 `intel`、`ops`、`market` 边界。 |
| CI/可观测 | `.github/workflows/ci.yml` 已跑 pytest、import-linter、前端 typecheck/test/build 和 Playwright e2e。 | **缺口（基于该 CI 文件未见）**：没有覆盖率/基准门禁、OTel trace、SBOM/依赖漏洞扫描、Python 静态类型和构建签名证据；可增量加，不阻断本地桌面离线运行。 |
| 供应链/交付 | Python 依赖以多个 `>=` 下限为主，前端使用 Bun lockfile 且 CI `--frozen-lockfile`；PyInstaller 仍是注释可选依赖，桌面主线是 pywebview。 | **结构性风险**：Python 可复现安装、依赖漏洞、许可证和 Windows 打包产物尚未在 CI 中形成证据链；先试 uv lock/pip-audit/SBOM，再决定是否改默认工具链。 |
| 架构治理 | `docs/architecture/bounded-contexts.md` 明确跨 BC 经包根、market 不写 palace；同时记录 cli 未纳入 import-linter、review 仍有部分 SQL 直连等债务。 | **机会**：扩大边界测试和 benchmark，而非全仓重构；所有新适配器放所属 `infrastructure`，文件继续 ≤600 行。 |

## 4. 优先级矩阵

| 优先级 | 项目/组合 | 近期动作与闸门 |
|---|---|---|
| **P0** | `pola-rs/polars`、`duckdb/duckdb`、`TanStack/virtual`、`ionelmc/pytest-benchmark`、`open-telemetry/opentelemetry-python`、`pypa/pip-audit`、`astral-sh/ruff`/`astral-sh/uv` | 4 周内做只读/开发工具 POC；有基线、有回退、有审计字段才进入默认 CI 或热路径。 |
| **P1** | `tradingview/lightweight-charts`、`TanStack/query`/`table`、`taskiq-python/taskiq`、`jlowin/fastmcp` + MCP SDK、`pydantic/pydantic-ai`、`testcontainers/testcontainers-python`、`microsoft/qlib`、`simonw/sqlite-utils`、`giampaolo/psutil` | 需要页面/任务/AI/研究专项 POC；不得改账本语义、不得让外部引擎绕过 `entry_timing`/PIT。 |
| **P2** | Arrow/DataFusion/Ibis、Litestream/rqlite/libSQL、Dask/Modin/Vaex、Qdrant/Chroma/LanceDB、Sentry/Grafana、Nuitka/Briefcase、NATS/Redis 客户端 | 只做方案储备或故障演练；等数据量、多用户、跨进程或离线模型需求出现再评估。 |
| **Reject（当前边界）** | ClickHouse、Kafka/RabbitMQ、Celery/Prefect/Dagster/Temporal、Milvus/Weaviate/RAGFlow、Electron/Tauri 替换 pywebview、AG Grid、Freqtrade/CCXT/Alpaca、FastAPI React/PostgreSQL 模板 | 引入面大于单机收益，或与 A 股/三库/单 worker/不换 UI 约束冲突；可阅读其设计，暂不接入生产。 |

## 5. 最值得实际评估的 14 个项目

| 项目 | 落点与适配器边界 | POC、回滚与验收 |
|---|---|---|
| `pola-rs/polars` | `src/market`/`formula`/`review` 的只读面板适配器；输入来自已有 DTO/market snapshot，输出仍映射既有接口。 | 用同一冻结样本对比 pandas：p95 时间、峰值 RSS、行数/关键数值 hash；失败切回 pandas，禁止写 palace。 |
| `duckdb/duckdb` | 延续现有 `duckdb_panel.py`，查询 market hot/export，不替代三库和 Store。 | classic vs DuckDB 行数/关键价/错误率一致；关闭 `LOCI_MARKET_DUCKDB` 即回滚，记录查询耗时和临时文件。 |
| `tradingview/lightweight-charts` | `frontend/src/shared/components/charts` 做 K 线 A/B；ECharts 继续承担非金融图和副图，后端数字不变。 | 同一 bars 的十字线/缩放/60 根初始视图；INP、帧耗时、内存和可访问性达标，否则保留 ECharts。 |
| `TanStack/virtual` | 仅用于 `PoolView`/Job 历史等长列表的局部渲染层，保留 Element Plus 表单和 token。 | 1000/5000 行滚动 p95、筛选响应、键盘焦点测试；回滚到 BasicTable/EP 表格，不引入第二套 UI。 |
| `ionelmc/pytest-benchmark` | `tests/benchmarks` 测 market panel、指标、receipt 查询和锁等待；不进入运行时。 | 建立冷/热缓存基线和 10% 回归阈值；基准只读临时库，CI 超阈值先告警再逐步阻断。 |
| `open-telemetry/opentelemetry-python` | 在 FastAPI request、ops Job、market adapter、AI run 建 span；导出默认关闭或本机 OTLP。 | trace_id 能串起 run_id/source receipt/tool receipt；关环境变量后零网络副作用、日志和功能不变。 |
| `pypa/pip-audit` + `ossf/scorecard` | CI 供应链检查；报告依赖树、漏洞、仓库工作流健康，不改运行时。 | 对现有 lock/requirements 产生可归档 SARIF/JSON；误报有豁免期限，不能把开发机秘密上传。 |
| `astral-sh/uv` + `astral-sh/ruff` | 先作为本地/CI 辅助工具；Python 包与 Bun 分工不变。 | 在干净 Windows/Ubuntu 环境安装、lint/format 时间和结果可复现；失败保持现有 pip/pytest。 |
| `taskiq-python/taskiq` | 只在 research/backtest 必须与 API/桌面进程隔离时试用，worker 通过现有 JobContext 访问公开 API。 | 崩溃恢复、幂等 run、取消、SQLite 连接隔离可证明；没有 broker 时不引入 Redis，POC 失败继续 APScheduler。 |
| `jlowin/fastmcp` + 官方 MCP SDK | `src/intel` 的 server/client 契约和测试夹具；System ToolBus 仍是唯一授权壳。 | schema、超时、arg clamp、只读/写边界、证据 hash 和最大工具数测试；无授权或不可用 MCP 只能 degraded。 |
| `pydantic/pydantic-ai` | AI application 的结构化编排候选；工具结果必须回到 market/review/strategy 的权威 DTO。 | 用固定 mock 工具验证 typed output、重试和取消；模型不能写数字、不能绕 ExecutionGrant，失败回现有 agent。 |
| `testcontainers/testcontainers-python` | CI/integration profile 的 Redis/NATS/OTel/MCP 依赖测试，不进入桌面运行包。 | 容器不可用时单元测试仍绿；服务契约和清理可重复，不把真实 data/*.db 挂入容器。 |
| `microsoft/qlib` | research 私有实验区，仅导入冻结 OHLCV/PIT 输入；不注册活动 strategy。 | 同一 train/OOS、entry price、survivorship/PIT 审计；结果只能 awaiting human review，无法通过即删实验适配器。 |
| `simonw/sqlite-utils` | 仅 CLI/诊断/导入导出工具层，不能取代 Store DDL、事务和三库边界。 | 临时库 schema/receipt 检查脚本；生产代码不新增依赖，发现写错库立即删除 POC。 |

## 6. 30/60/90 天落地路线与决策闸门

**0–30 天：测量和低风险治理**

- 建立 market panel、研究回测、候选池 1000/5000 行、K 线重绘、Job 锁等待和 AI 工具调用的基线；将 p50/p95、峰值 RSS、错误率、数据库 busy 次数写入结果。
- POC Polars/DuckDB 只读旁路、`pytest-benchmark`、pip-audit、ruff/uv；加 OTel opt-in 的 request/job/run/source/tool correlation。
- 闸门 A：数字 hash/行数/entry timing 与经典实现一致；闸门 B：关闭 feature flag 能完全回退；闸门 C：无真实 `data/` 污染、无跨 BC 深导入。

**31–60 天：局部体验和任务隔离**

- 对候选池/Job 历史做 TanStack Virtual 或 EP 虚拟表二选一；对 K 线做 Lightweight Charts A/B；不整库换 Element Plus。
- 对 research/backtest 做 Taskiq 单 worker POC；对 MCP 做 FastMCP/官方 SDK schema contract test；对 AI 做 PydanticAI typed-output 对照。
- 闸门：长任务可取消/恢复/幂等，`job_runs` 有终态；MCP 只读工具不可越权；回测有 PIT/`entry_timing`/control group 证据；e2e 与桌面 WebView2 烟雾不回归。

**61–90 天：决定是否默认化**

- 选择一个数据引擎旁路、一个长表渲染方案、一个任务方案；补 SBOM/依赖许可证/漏洞归档、Windows 打包验收和最小 trace dashboard。
- 只有 POC 指标稳定两周、回滚开关可用、README/ADR/测试同步，才将 feature flag 默认开启；否则留在 P1/P2。
- 90 天否决条件：需要迁移 `palace.db`、改变 market/review 真相、增加不可删的第二份权威指标、引入 React/Nuxt/第二 UI、或把 AI 结果当成交/行情数字。

## 7. 可核查 GitHub 项目清单（197）

清单中的成熟度格式为 `stars★ / forks⑂ / 许可证 / 最近更新`。所有行的最近更新均为 `未核验`；许可证 `未核验` 表示官方页面字段未稳定暴露，不表示无许可证。`P0/P1/P2/维持/拒绝` 是对 Loci 当前边界的动作，不是对项目本身的评价。

### 7.1 数据与存储（1–20）

| # | 项目 | 能力与本仓契合点 | 成熟度（页面快照） | 成本/风险 | 建议 |
|---:|---|---|---|---|---|
|1|[duckdb/duckdb](https://github.com/duckdb/duckdb)|嵌入式 OLAP SQL；延续 market 只读面板/热库查询|40,078★ / 3,530⑂ / MIT / 未核验|已有依赖；不能写 palace|P0|
|2|[pola-rs/polars](https://github.com/pola-rs/polars)|Rust DataFrame；替换 formula/panel 热路径的候选|39,301★ / 3,006⑂ / MIT / 未核验|API/表达式迁移，需数值等价|P0|
|3|[apache/arrow](https://github.com/apache/arrow)|列式内存/跨语言交换；连接 pandas、Polars、DuckDB|16,993★ / 4,213⑂ / Apache-2.0 / 未核验|引入 Arrow schema 与内存占用|P1|
|4|[apache/datafusion](https://github.com/apache/datafusion)|Rust SQL 查询引擎；大面板设计参考|9,101★ / 2,282⑂ / Apache-2.0 / 未核验|Rust/FFI 复杂，单机暂不必要|P2|
|5|[ClickHouse/ClickHouse](https://github.com/ClickHouse/ClickHouse)|列式分析数据库；多用户/海量行情阶段参考|49,117★ / 8,755⑂ / Apache-2.0 / 未核验|服务化运维、迁移和资源成本大|拒绝|
|6|[pandas-dev/pandas](https://github.com/pandas-dev/pandas)|现有业务胶水和 DTO 前的数据整形|49,494★ / 20,248⑂ / 未核验 / 未核验|维持现状，关注版本兼容|维持|
|7|[numpy/numpy](https://github.com/numpy/numpy)|指标/数值数组基础；formula 计算依赖|32,521★ / 12,620⑂ / Other / 未核验|维持，不把数组直接暴露为权威 DTO|维持|
|8|[dask/dask](https://github.com/dask/dask)|任务图/并行 DataFrame；大规模研究参考|13,883★ / 1,923⑂ / 未核验 / 未核验|线程/进程和调度复杂度高|P2|
|9|[ibis-project/ibis](https://github.com/ibis-project/ibis)|可移植 DataFrame/SQL；抽象多后端研究查询|6,622★ / 751⑂ / Apache-2.0 / 未核验|再加一层查询抽象，收益待测|P2|
|10|[modin-project/modin](https://github.com/modin-project/modin)|以少量改动扩展 pandas；压力测试对照|10,391★ / 678⑂ / Apache-2.0 / 未核验|隐藏调度与兼容成本|P2|
|11|[vaexio/vaex](https://github.com/vaexio/vaex)|Arrow/NumPy out-of-core 表格；大历史探索参考|8,509★ / 603⑂ / MIT / 未核验|生态/维护和交互集成风险|P2|
|12|[sqlite/sqlite](https://github.com/sqlite/sqlite)|SQLite 官方 Git 镜像；核对 WAL/事务语义|10,188★ / 1,614⑂ / Other / 未核验|不是替换项目，作为一手规范|维持|
|13|[sqlitebrowser/sqlitebrowser](https://github.com/sqlitebrowser/sqlitebrowser)|SQLite 人工诊断桌面工具；开发排障|24,411★ / 2,361⑂ / Other / 未核验|不进产品运行时|借鉴|
|14|[simonw/sqlite-utils](https://github.com/simonw/sqlite-utils)|SQLite CLI/库；临时检查、导入导出脚本|2,143★ / 164⑂ / Apache-2.0 / 未核验|不得绕过 Store/DDL/事务|P1|
|15|[benbjohnson/litestream](https://github.com/benbjohnson/litestream)|SQLite 流式复制；灾备/备份设计参考|14,211★ / 389⑂ / Apache-2.0 / 未核验|后台复制与 Windows 部署需验证|P2|
|16|[rqlite/rqlite](https://github.com/rqlite/rqlite)|SQLite 高可用集群；多节点未来参考|17,670★ / 799⑂ / MIT / 未核验|改变单机写入和一致性模型|拒绝|
|17|[tursodatabase/libsql](https://github.com/tursodatabase/libsql)|SQLite 分支/远程同步；多端场景参考|17,109★ / 524⑂ / MIT / 未核验|迁移/兼容和网络依赖|P2|
|18|[lancedb/lancedb](https://github.com/lancedb/lancedb)|嵌入式向量/多模态检索；AI 记忆可删缓存|11,089★ / 993⑂ / Apache-2.0 / 未核验|不能代替 ops 记忆事实，schema 尚需审计|P2|
|19|[qdrant/qdrant](https://github.com/qdrant/qdrant)|向量搜索服务；研究/AI 语义检索候选|33,837★ / 2,562⑂ / Apache-2.0 / 未核验|另起服务，单机部署成本高|P2|
|20|[chroma-core/chroma](https://github.com/chroma-core/chroma)|AI 搜索基础设施；小规模本地 RAG 对照|28,978★ / 2,425⑂ / Apache-2.0 / 未核验|持久化/版本和检索真相边界|P2|

### 7.2 Python、FastAPI 与并发（21–40）

| # | 项目 | 能力与本仓契合点 | 成熟度（页面快照） | 成本/风险 | 建议 |
|---:|---|---|---|---|---|
|21|[fastapi/fastapi](https://github.com/fastapi/fastapi)|现有 API 框架；异步/依赖/测试边界的一手参考|101,397★ / 9,754⑂ / MIT / 未核验|维持，继续遵守同步 SQLite 路由纪律|维持|
|22|[pydantic/pydantic](https://github.com/pydantic/pydantic)|请求/响应和配置校验；`extra=forbid` 契约|28,494★ / 2,852⑂ / MIT / 未核验|维持，升级需扫 DTO 兼容|维持|
|23|[encode/starlette](https://github.com/encode/starlette)|FastAPI 底层 ASGI 工具、lifespan、middleware|12,529★ / 1,256⑂ / 未核验 / 未核验|只按底层 API 排障，不直接替换 FastAPI|借鉴|
|24|[encode/uvicorn](https://github.com/encode/uvicorn)|现有单 worker ASGI 运行器；启动参数和生命周期|10,888★ / 1,000⑂ / 未核验 / 未核验|多 worker 会触发 APScheduler 重复风险|维持|
|25|[encode/httpx](https://github.com/encode/httpx)|同步/异步 HTTP client；AI/MCP/行情适配器参考|15,397★ / 1,240⑂ / 未核验 / 未核验|仓库依赖写 `httpx2`，需先核对实际包名/兼容|P1|
|26|[agronholm/anyio](https://github.com/agronholm/anyio)|统一 asyncio/Trio 并发抽象；测试异步边界|2,521★ / 235⑂ / MIT / 未核验|避免在同步 SQLite 热路径盲目 async 化|P1|
|27|[emmett-framework/granian](https://github.com/emmett-framework/granian)|Rust HTTP server；吞吐/启动对照|5,537★ / 168⑂ / 未核验 / 未核验|与现有 Uvicorn、桌面启动和 scheduler 语义需对比|P2|
|28|[agronholm/apscheduler](https://github.com/agronholm/apscheduler)|现有进程内调度器；时区、misfire、coalesce 参考|7,596★ / 770⑂ / MIT / 未核验|先补指标和单 worker 护栏，不急换|维持|
|29|[astral-sh/uv](https://github.com/astral-sh/uv)|快速 Python 项目/依赖管理；可复现安装 POC|88,496★ / 3,453⑂ / Apache-2.0 / 未核验|改安装链需 Windows/CI/离线回滚|P0|
|30|[astral-sh/ruff](https://github.com/astral-sh/ruff)|Rust lint/format；低成本 CI 质量门|49,100★ / 2,307⑂ / MIT / 未核验|规则集迁移和自动格式化要分批|P0|
|31|[pytest-dev/pytest](https://github.com/pytest-dev/pytest)|现有测试基础；fixture/插件/隔离|14,396★ / 3,276⑂ / MIT / 未核验|维持，重点补锁、PIT、MCP contract|维持|
|32|[hypothesisworks/hypothesis](https://github.com/HypothesisWorks/hypothesis)|属性测试；OHLC、entry timing、参数 clamp|8,850★ / 663⑂ / Other / 未核验|生成数据需遵守真实语义，不能假造行情证据|P1|
|33|[seddonym/import-linter](https://github.com/seddonym/import-linter)|架构边界 lint；保护四层/跨 BC 包根|1,128★ / 83⑂ / 未核验 / 未核验|现有规则需覆盖 cli/review 债务|P0|
|34|[jcrist/msgspec](https://github.com/jcrist/msgspec)|高速序列化/校验；SSE/内部 DTO 性能对照|3,987★ / 167⑂ / 未核验 / 未核验|不替换所有 Pydantic 边界，避免双模型|P1|
|35|[ijl/orjson](https://github.com/ijl/orjson)|高性能 JSON；事件流/大表响应对照|8,191★ / 319⑂ / Apache-2.0 / 未核验|datetime/bytes/Decimal 语义需逐接口验收|P1|
|36|[python-attrs/attrs](https://github.com/python-attrs/attrs)|轻量数据类；domain 值对象设计参考|5,826★ / 461⑂ / MIT / 未核验|已有 dataclass/Pydantic，不引入第三种模型风格|借鉴|
|37|[tiangolo/typer](https://github.com/tiangolo/typer)|类型驱动 CLI；统一 market/ops/review 命令体验|19,877★ / 967⑂ / MIT / 未核验|只从公开包根导入，不扩大 cli 深路径|P1|
|38|[sysid/sse-starlette](https://github.com/sysid/sse-starlette)|SSE 响应适配；AI 事件流连接管理参考|846★ / 67⑂ / 未核验 / 未核验|现有轮询兼容、Last-Event-ID、取消语义不能回退|P1|
|39|[python-websockets/websockets](https://github.com/python-websockets/websockets)|WebSocket 协议库；实时行情替代通道研究|5,708★ / 603⑂ / 未核验 / 未核验|行情当前 HTTP/轮询已够，增加连接生命周期成本|P2|
|40|[benoitc/gunicorn](https://github.com/benoitc/gunicorn)|进程管理/WSGI server；生产部署对照|10,640★ / 1,852⑂ / Other / 未核验|Windows 桌面与 APScheduler 单例不适合直接替换|P2|

### 7.3 量化、行情与回测（41–65）

| # | 项目 | 能力与本仓契合点 | 成熟度（页面快照） | 成本/风险 | 建议 |
|---:|---|---|---|---|---|
|41|[akfamily/akshare](https://github.com/akfamily/akshare)|A 股/金融数据接口；现有 market provider 目录|21,864★ / 3,426⑂ / MIT / 未核验|供应商字段/限流/许可需 receipt 与健康门禁|维持|
|42|[ranaroussi/yfinance](https://github.com/ranaroussi/yfinance)|Yahoo Finance 下载器；跨市场测试/对照数据|24,916★ / 3,391⑂ / Apache-2.0 / 未核验|不是 A 股权威源，不能混入 production truth|P2|
|43|[polakowo/vectorbt](https://github.com/polakowo/vectorbt)|向量化回测/参数扫描；现有可选 fast path|8,606★ / 1,108⑂ / Other / 未核验|执行时点/前视和内存必须由 research 冻结输入约束|P1|
|44|[kernc/backtesting.py](https://github.com/kernc/backtesting.py)|轻量策略回测；entry timing 对照实现|8,763★ / 1,505⑂ / AGPL-3.0 / 未核验|AGPL 和成交模型需审计，不直接替换引擎|P1|
|45|[mementum/backtrader](https://github.com/mementum/backtrader)|事件式 Python 回测；策略 API 设计参考|22,761★ / 5,229⑂ / GPL-3.0 / 未核验|维护/许可证/前视风险，借鉴多于接入|P2|
|46|[freqtrade/freqtrade](https://github.com/freqtrade/freqtrade)|成熟加密交易 bot；风控、回测、Job 参考|53,062★ / 11,027⑂ / GPL-3.0 / 未核验|加密交易和实盘执行边界与 Loci 冲突|拒绝|
|47|[nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader)|Rust 原生事件驱动交易引擎；确定性架构参考|25,348★ / 3,308⑂ / LGPL-3.0 / 未核验|体量/撮合/实时系统远超单机复盘需求|P2|
|48|[QuantConnect/Lean](https://github.com/QuantConnect/Lean)|Python/C# 算法交易引擎；研究执行分层参考|21,117★ / 5,146⑂ / Apache-2.0 / 未核验|跨语言、数据供应商和运行模型成本高|P2|
|49|[vnpy/vnpy](https://github.com/vnpy/vnpy)|Python 量化交易平台；事件总线/网关参考|44,315★ / 12,328⑂ / MIT / 未核验|经纪/实时交易面过重，Loci 不接实盘下单|P2|
|50|[ricequant/rqalpha](https://github.com/ricequant/rqalpha)|可扩展多证券回测交易框架；佣金/滑点建模参考|6,652★ / 1,772⑂ / Other / 未核验|数据和执行模型与本仓要做 contract 对齐|P1|
|51|[shinnytech/tqsdk-python](https://github.com/shinnytech/tqsdk-python)|行情/交易/回测 SDK；期货实时能力参考|4,930★ / 772⑂ / Apache-2.0 / 未核验|期货和账户交易边界不适合当前产品|拒绝|
|52|[TA-Lib/ta-lib-python](https://github.com/TA-Lib/ta-lib-python)|TA-Lib Python wrapper；指标交叉校验|12,178★ / 1,995⑂ / 未核验 / 未核验|原生库/指标口径和许可证要核对|P1|
|53|[bukosabino/ta](https://github.com/bukosabino/ta)|pandas/numpy 技术指标；formula 对照|5,140★ / 1,144⑂ / MIT / 未核验|不把第三方指标直接变成权威复盘口径|P1|
|54|[microsoft/qlib](https://github.com/microsoft/qlib)|AI-oriented quant research；研究 sandbox 对照|47,146★ / 7,495⑂ / MIT / 未核验|PIT/生存者偏差/执行 OHLCV 需 Loci 门禁|P1|
|55|[ranaroussi/quantstats](https://github.com/ranaroussi/quantstats)|组合分析/绩效报告；review 指标交叉校验|7,530★ / 1,225⑂ / Apache-2.0 / 未核验|公式口径需和 review API 对齐，不能双真相|P1|
|56|[AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL)|金融强化学习研究；实验方法参考|15,946★ / 3,455⑂ / MIT / 未核验|样本/奖励/前视和训练成本高，不接生产策略|P2|
|57|[AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT)|金融 LLM；情报摘要和评估参考|21,058★ / 2,986⑂ / MIT / 未核验|模型不产出权威行情/盈亏，数据许可要审|P2|
|58|[jesse-ai/jesse](https://github.com/jesse-ai/jesse)|Python 加密交易 bot；策略 DSL/回测 UX 参考|8,300★ / 1,195⑂ / MIT / 未核验|加密/实盘边界和数据模型不匹配|拒绝|
|59|[mhallsmoore/qstrader](https://github.com/mhallsmoore/qstrader)|回测仿真引擎；组合/事件模型参考|3,430★ / 927⑂ / MIT / 未核验|研究适配成本，优先读测试和执行语义|P2|
|60|[quantopian/zipline](https://github.com/quantopian/zipline)|Python 算法交易库；历史执行设计参考|20,030★ / 5,024⑂ / Apache-2.0 / 未核验|项目生态和数据接口老化风险|P2|
|61|[stefan-jansen/zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded)|Zipline 维护分支；研究复现参考|1,864★ / 317⑂ / Apache-2.0 / 未核验|仍需验证 Python/数据/许可证组合|P2|
|62|[gbeced/pyalgotrade](https://github.com/gbeced/pyalgotrade)|Python algorithmic trading library；简化回测参考|4,664★ / 1,387⑂ / Other / 未核验|维护度和前视保护不足以直接采用|P2|
|63|[pydata/pandas-datareader](https://github.com/pydata/pandas-datareader)|从多源读入 DataFrame；数据适配测试参考|3,227★ / 691⑂ / Other / 未核验|外部源不稳定，不能取代 market receipt|P2|
|64|[alpacahq/alpaca-py](https://github.com/alpacahq/alpaca-py)|Alpaca 官方 Python SDK；API 设计/纸面交易对照|1,450★ / 387⑂ / Apache-2.0 / 未核验|美股/券商账户边界，当前不接入|拒绝|
|65|[ccxt/ccxt](https://github.com/ccxt/ccxt)|多交易所统一交易 API；provider registry 参考|43,559★ / 8,797⑂ / MIT / 未核验|加密实盘面与 Loci 只读 A 股目标冲突|拒绝|

### 7.4 Vue、表格与图表（66–90）

| # | 项目 | 能力与本仓契合点 | 成熟度（页面快照） | 成本/风险 | 建议 |
|---:|---|---|---|---|---|
|66|[vuejs/core](https://github.com/vuejs/core)|现有 Vue 3.5 Composition API 基座|54,159★ / 9,173⑂ / MIT / 未核验|维持，不因雷达换框架|维持|
|67|[vuejs/router](https://github.com/vuejs/router)|现有 Vue Router；页面/查询参数导航|4,666★ / 1,291⑂ / MIT / 未核验|维持，路由页保持 page-fill|维持|
|68|[vuejs/pinia](https://github.com/vuejs/pinia)|现有 setup store；跨页状态与 DevTools|14,686★ / 1,200⑂ / MIT / 未核验|不把一次性 UI 状态塞入 store|维持|
|69|[vitejs/vite](https://github.com/vitejs/vite)|现有 Vite 7；开发/构建主线|82,255★ / 8,613⑂ / MIT / 未核验|维持，rolldown 用独立 config|维持|
|70|[element-plus/element-plus](https://github.com/element-plus/element-plus)|现有 UI 库；表格/表单/对话框/a11y|27,662★ / 19,845⑂ / MIT / 未核验|不引入第二 UI 库，关注按需与表格性能|维持|
|71|[apache/echarts](https://github.com/apache/echarts)|现有总览/K 线图表基础；多轴/副图|67,003★ / 19,812⑂ / Apache-2.0 / 未核验|继续按需引入，避免重复 option|维持|
|72|[ecomfe/vue-echarts](https://github.com/ecomfe/vue-echarts)|Vue ECharts 封装；通用图表组件参考|10,732★ / 1,496⑂ / MIT / 未核验|与现有手写 core 选一种，不能双重封装|P1|
|73|[tradingview/lightweight-charts](https://github.com/tradingview/lightweight-charts)|高性能金融 canvas；K 线 A/B|16,896★ / 2,563⑂ / Apache-2.0 / 未核验|副图/标注/交互需适配；不改变后端真相|P1|
|74|[VisActor/VTable](https://github.com/VisActor/VTable)|高性能多维表格/grid；长表对照|3,636★ / 482⑂ / MIT / 未核验|与 EP 表格并存会增加包体和样式适配|P2|
|75|[VisActor/VChart](https://github.com/VisActor/VChart)|跨平台图表/数据叙事；图表架构参考|1,826★ / 216⑂ / MIT / 未核验|和 ECharts 重叠，当前不引入|P2|
|76|[TanStack/query](https://github.com/TanStack/query)|Vue Query 服务端状态、缓存、去重|50,085★ / 4,159⑂ / MIT / 未核验|已有 Pinia Colada，二选一试点|P1|
|77|[TanStack/table](https://github.com/TanStack/table)|headless 表格；复杂筛选/排序列模型|28,291★ / 3,564⑂ / MIT / 未核验|需自行接 EP token/a11y，不能替换所有表|P1|
|78|[TanStack/virtual](https://github.com/TanStack/virtual)|Vue/TS 虚拟长列表；候选池/Job history|7,047★ / 454⑂ / MIT / 未核验|滚动、焦点、动态行高和表头同步需测|P0|
|79|[vueuse/vueuse](https://github.com/vueuse/vueuse)|Vue Composition utilities；SSE、持久化、节流|22,322★ / 2,925⑂ / MIT / 未核验|已有封装先复用，避免无边界引入|维持|
|80|[Akryum/vue-virtual-scroller](https://github.com/Akryum/vue-virtual-scroller)|Vue 虚拟滚动；长列表替代方案|10,789★ / 972⑂ / 未核验 / 未核验|与 TanStack Virtual 二选一，不并用|P1|
|81|[vuejs/language-tools](https://github.com/vuejs/language-tools)|Volar/vetur 类型和模板工具；typecheck|6,704★ / 555⑂ / MIT / 未核验|维持，升级需核对 vue-tsc|维持|
|82|[unplugin/unplugin-vue-components](https://github.com/unplugin/unplugin-vue-components)|按需自动导入 Vue 组件；包体优化|4,295★ / 383⑂ / MIT / 未核验|Element Plus resolver 配置需可审计|P1|
|83|[unplugin/unplugin-auto-import](https://github.com/unplugin/unplugin-auto-import)|Vite/Webpack/Rollup API 自动导入；构建便利|3,790★ / 217⑂ / MIT / 未核验|会降低显式依赖可读性，当前手动 import 更稳|P2|
|84|[microsoft/monaco-editor](https://github.com/microsoft/monaco-editor)|浏览器代码编辑器；ops 技能/策略配置|46,514★ / 4,100⑂ / MIT / 未核验|已有依赖；需懒加载/worker 分包|维持|
|85|[antvis/G2](https://github.com/antvis/G2)|声明式可视化 grammar；非 K 线图表参考|12,581★ / 1,659⑂ / MIT / 未核验|与 ECharts 重叠，借鉴语法即可|P2|
|86|[ag-grid/ag-grid](https://github.com/ag-grid/ag-grid)|企业级数据表；复杂表能力对照|15,527★ / 2,078⑂ / Other / 未核验|许可/体积/第二表格体系成本高|拒绝|
|87|[floating-ui/floating-ui](https://github.com/floating-ui/floating-ui)|浮层定位与交互；Popover/贴边浮球参考|32,693★ / 1,694⑂ / MIT / 未核验|Element Plus 已覆盖大部分场景|借鉴|
|88|[formkit/auto-animate](https://github.com/formkit/auto-animate)|零配置过渡动画；助手/面板体验|13,889★ / 258⑂ / MIT / 未核验|动画不能影响可访问性和实时数据|P2|
|89|[tailwindlabs/tailwindcss](https://github.com/tailwindlabs/tailwindcss)|utility CSS；现有 token/布局辅助|97,105★ / 5,568⑂ / MIT / 未核验|维持，避免与 EP 变量重复造皮肤|维持|
|90|[vuejs/devtools](https://github.com/vuejs/devtools)|Vue 调试/Pinia 状态检查；开发诊断|2,882★ / 268⑂ / MIT / 未核验|仅开发工具，不进桌面产物|维持|

### 7.5 Worker、构建与桌面（91–110）

| # | 项目 | 能力与本仓契合点 | 成熟度（页面快照） | 成本/风险 | 建议 |
|---:|---|---|---|---|---|
|91|[oven-sh/bun](https://github.com/oven-sh/bun)|现有 JS runtime/package/test；CI 已固定 Bun|95,323★ / 4,941⑂ / Other / 未核验|维持，锁文件和平台差异要测|维持|
|92|[vitejs/rolldown-vite](https://github.com/vitejs/rolldown-vite)|Vite 的 Rolldown 构建试验；已有脚本|1,269★ / 18⑂ / MIT / 未核验|WIP，产物差异需可回退|P1|
|93|[rolldown/rolldown](https://github.com/rolldown/rolldown)|Rust bundler；构建速度/包体对照|13,865★ / 1,013⑂ / MIT / 未核验|插件兼容和 sourcemap 风险|P1|
|94|[evanw/esbuild](https://github.com/evanw/esbuild)|高速 bundler；构建基线参考|40,008★ / 1,331⑂ / MIT / 未核验|不替换 Vite 默认链，比较即可|P2|
|95|[web-infra-dev/rspack](https://github.com/web-infra-dev/rspack)|Rust bundler/webpack API；大型前端参考|12,849★ / 834⑂ / MIT / 未核验|Vue/Vite 迁移面大|拒绝|
|96|[swc-project/swc](https://github.com/swc-project/swc)|Rust Web 平台；转译性能参考|34,172★ / 1,535⑂ / Apache-2.0 / 未核验|Vite/Rolldown 已覆盖主要需求|P2|
|97|[vitest-dev/vitest](https://github.com/vitest-dev/vitest)|现有 Vite-native unit test；前端回归基础|16,930★ / 1,907⑂ / MIT / 未核验|维持，补 browser/e2e 关键路径|维持|
|98|[microsoft/playwright](https://github.com/microsoft/playwright)|现有 Chromium e2e；桌面/页面烟雾|94,182★ / 6,239⑂ / Apache-2.0 / 未核验|维持，控制浏览器安装和 CI 时间|维持|
|99|[GoogleChromeLabs/comlink](https://github.com/GoogleChromeLabs/comlink)|WebWorker RPC；现有指标 off-thread|12,764★ / 431⑂ / Apache-2.0 / 未核验|worker 生命周期/异常需测试|维持|
|100|[r0x0r/pywebview](https://github.com/r0x0r/pywebview)|Python + HTML/CSS 桌面壳；现有 WebView2|5,980★ / 632⑂ / 未核验 / 未核验|维持，关注第二 WebView2/托盘/打包|维持|
|101|[tauri-apps/tauri](https://github.com/tauri-apps/tauri)|Rust 原生桌面壳；轻量桌面对照|110,004★ / 3,846⑂ / Apache-2.0 / 未核验|重写 Python bridge/打包，不符合近期边界|拒绝|
|102|[electron/electron](https://github.com/electron/electron)|跨平台 JS 桌面壳；产品方案对照|122,384★ / 17,389⑂ / MIT / 未核验|体积/内存和替换 pywebview 成本高|拒绝|
|103|[electron-userland/electron-builder](https://github.com/electron-userland/electron-builder)|Electron 分发/自动更新；桌面交付参考|14,641★ / 1,861⑂ / MIT / 未核验|仅在选择 Electron 时有意义|拒绝|
|104|[pyinstaller/pyinstaller](https://github.com/pyinstaller/pyinstaller)|Python 冻结为 exe；现有桌面交付候选|13,053★ / 2,025⑂ / Other / 未核验|hooks/原生库/体积需 Windows matrix|P1|
|105|[Nuitka/Nuitka](https://github.com/Nuitka/Nuitka)|Python 编译器/打包；启动/体积对照|15,067★ / 790⑂ / AGPL-3.0 / 未核验|编译兼容和许可证审查|P2|
|106|[beeware/briefcase](https://github.com/beeware/briefcase)|Python 项目原生应用打包；替代路径参考|3,327★ / 535⑂ / 未核验 / 未核验|平台支持/依赖集成待测|P2|
|107|[indygreg/python-build-standalone](https://github.com/indygreg/python-build-standalone)|可分发 Python runtime；Windows portable 交付|4,326★ / 303⑂ / MPL-2.0 / 未核验|runtime 许可、补丁和体积需锁定|P1|
|108|[python/cpython](https://github.com/python/cpython)|Python 解释器源码；版本/线程/性能一手参考|74,241★ / 35,167⑂ / Other / 未核验|不直接 fork/编译，升级按兼容矩阵|借鉴|
|109|[marcelotduarte/cx_Freeze](https://github.com/marcelotduarte/cx_Freeze)|跨平台 Python executable；打包对照|1,559★ / 241⑂ / Other / 未核验|与 PyInstaller 二选一验证|P2|
|110|[samuelcolvin/watchfiles](https://github.com/samuelcolvin/watchfiles)|Rust 文件监控/热重载；开发体验|2,521★ / 141⑂ / MIT / 未核验|开发依赖，不进入生产桌面包|P2|

### 7.6 任务调度、消息与可靠性（111–128）

| # | 项目 | 能力与本仓契合点 | 成熟度（页面快照） | 成本/风险 | 建议 |
|---:|---|---|---|---|---|
|111|[celery/celery](https://github.com/celery/celery)|经典分布式任务队列；重任务架构参考|28,774★ / 5,123⑂ / Other / 未核验|broker/worker/部署复杂，单机不划算|拒绝|
|112|[rq/rq](https://github.com/rq/rq)|Redis job queue；简单 worker 语义参考|10,667★ / 1,485⑂ / Other / 未核验|引入 Redis 与进程运维|拒绝|
|113|[Bogdanp/dramatiq](https://github.com/Bogdanp/dramatiq)|Python 后台任务处理；可靠性设计参考|5,302★ / 376⑂ / LGPL-3.0 / 未核验|broker/worker 生命周期仍增加故障面|P2|
|114|[taskiq-python/taskiq](https://github.com/taskiq-python/taskiq)|async-first 分布式任务队列；research worker POC|2,281★ / 137⑂ / MIT / 未核验|先证明进程隔离收益，不默认引 broker|P1|
|115|[temporalio/sdk-python](https://github.com/temporalio/sdk-python)|持久化 workflow/重试/恢复；长研究任务参考|1,158★ / 217⑂ / MIT / 未核验|需 Temporal server，远超桌面边界|拒绝|
|116|[prefecthq/prefect](https://github.com/prefecthq/prefect)|Python workflow orchestration；数据管道治理参考|23,573★ / 2,447⑂ / Apache-2.0 / 未核验|服务/编排面过大，单机 Job 已有审计|拒绝|
|117|[dagster-io/dagster](https://github.com/dagster-io/dagster)|数据资产 orchestration/observation；研究流水线参考|15,942★ / 2,232⑂ / Apache-2.0 / 未核验|资产平台和 UI 引入成本大|拒绝|
|118|[redis/redis](https://github.com/redis/redis)|缓存/队列/实时数据结构；多进程阶段参考|75,928★ / 24,752⑂ / Other / 未核验|服务化依赖、持久化和许可证需审|P2|
|119|[redis/redis-py](https://github.com/redis/redis-py)|Redis Python client；未来 worker/缓存适配器|13,609★ / 2,711⑂ / MIT / 未核验|没有 Redis 服务器就不引入|P2|
|120|[nats-io/nats-server](https://github.com/nats-io/nats-server)|轻量消息/边缘系统；事件通知参考|20,407★ / 1,894⑂ / Apache-2.0 / 未核验|消息一致性、运维和桌面离线不匹配|P2|
|121|[nats-io/nats.py](https://github.com/nats-io/nats.py)|NATS Python client；worker 事件适配器|1,241★ / 257⑂ / Apache-2.0 / 未核验|只有多进程需求出现才 POC|P2|
|122|[confluentinc/confluent-kafka-python](https://github.com/confluentinc/confluent-kafka-python)|Kafka Python client；高吞吐事件参考|500★ / 955⑂ / Other / 未核验|Kafka 集群与消息回放不适合当前规模|拒绝|
|123|[rabbitmq/rabbitmq-server](https://github.com/rabbitmq/rabbitmq-server)|AMQP broker；可靠任务消息参考|13,774★ / 4,020⑂ / Other / 未核验|服务/监控/升级成本，已有 ops.db 认领|拒绝|
|124|[pika/pika](https://github.com/pika/pika)|纯 Python AMQP client；RabbitMQ 适配参考|3,875★ / 852⑂ / 未核验 / 未核验|仅随 RabbitMQ POC 引入|P2|
|125|[jd/tenacity](https://github.com/jd/tenacity)|重试/退避库；外部行情/MCP 网络边界|8,741★ / 338⑂ / Apache-2.0 / 未核验|必须按错误类型和总预算设上限|P1|
|126|[grantjenks/python-diskcache](https://github.com/grantjenks/python-diskcache)|磁盘缓存；单机可重建缓存候选|2,902★ / 177⑂ / Other / 未核验|缓存失效/并发语义需不影响权威库|P2|
|127|[tkem/cachetools](https://github.com/tkem/cachetools)|内存 memoizing cache；短 TTL/去重参考|2,776★ / 202⑂ / MIT / 未核验|不缓存需实时/审计的行情真相|P1|
|128|[python-trio/trio](https://github.com/python-trio/trio)|结构化异步并发；并发测试/设计参考|7,306★ / 412⑂ / Other / 未核验|现有同步 SQLite/FastAPI 栈不宜整体迁移|P2|

### 7.7 可观测、测试、安全与供应链（129–156）

| # | 项目 | 能力与本仓契合点 | 成熟度（页面快照） | 成本/风险 | 建议 |
|---:|---|---|---|---|---|
|129|[open-telemetry/opentelemetry-python](https://github.com/open-telemetry/opentelemetry-python)|Python traces/metrics/logs；串 request/job/run/receipt|2,577★ / 962⑂ / Apache-2.0 / 未核验|默认关闭 exporter，防桌面网络副作用|P0|
|130|[open-telemetry/opentelemetry-collector](https://github.com/open-telemetry/opentelemetry-collector)|统一采集/转发；本机或 CI 观测管道|7,359★ / 2,196⑂ / Apache-2.0 / 未核验|额外进程；先用本地 exporter|P2|
|131|[prometheus/prometheus](https://github.com/prometheus/prometheus)|metrics/time-series；Job/锁/数据质量指标|65,617★ / 10,743⑂ / Apache-2.0 / 未核验|长期服务化存储不适合桌面默认|P2|
|132|[prometheus/client_python](https://github.com/prometheus/client_python)|Python metrics instrumentation；低成本 counters/histograms|4,355★ / 869⑂ / Apache-2.0 / 未核验|指标命名/高基数和退出落盘需约束|P1|
|133|[grafana/grafana](https://github.com/grafana/grafana)|metrics/logs/traces dashboard；运维设计参考|76,153★ / 14,517⑂ / AGPL-3.0 / 未核验|服务与许可证成本高，先输出 JSON|P2|
|134|[getsentry/sentry-python](https://github.com/getsentry/sentry-python)|Python exception/performance SDK；崩溃诊断|2,204★ / 647⑂ / MIT / 未核验|外发数据/隐私需显式 opt-in|P1|
|135|[getsentry/sentry-javascript](https://github.com/getsentry/sentry-javascript)|JS/Vue error/performance SDK；前端桌面错误|8,716★ / 1,816⑂ / MIT / 未核验|网络、PII 和桌面离线需治理|P2|
|136|[hynek/structlog](https://github.com/hynek/structlog)|结构化 Python 日志；source/run/tool correlation|4,912★ / 297⑂ / Other / 未核验|与 stdlib logging 集成，避免双套 logger|P1|
|137|[giampaolo/psutil](https://github.com/giampaolo/psutil)|跨平台 CPU/RSS/进程指标；桌面/Job 观测|11,258★ / 1,507⑂ / 未核验 / 未核验|Windows 权限和采样开销需控|P1|
|138|[pytest-dev/pytest-cov](https://github.com/pytest-dev/pytest-cov)|pytest coverage 插件；CI 缺口补齐|2,054★ / 241⑂ / MIT / 未核验|覆盖率不等于行为质量，先设报告不设硬阈|P0|
|139|[pytest-dev/pytest-xdist](https://github.com/pytest-dev/pytest-xdist)|并行测试；缩短 CI 时间|1,892★ / 276⑂ / MIT / 未核验|SQLite/全局环境测试要标记隔离|P1|
|140|[pytest-dev/pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio)|asyncio pytest 支持；SSE/MCP/异步边界|1,654★ / 199⑂ / Apache-2.0 / 未核验|同步路由仍需同步测试，避免虚假 async 覆盖|P1|
|141|[testcontainers/testcontainers-python](https://github.com/testcontainers/testcontainers-python)|临时容器集成测试；未来 broker/OTel 契约|2,268★ / 377⑂ / Apache-2.0 / 未核验|CI Docker 可用性；不挂真实 data|P1|
|142|[allure-framework/allure-python](https://github.com/allure-framework/allure-python)|测试报告集成；e2e/数据质量证据|811★ / 257⑂ / Apache-2.0 / 未核验|增加报告平台，先用 CI artifact|P2|
|143|[PyCQA/bandit](https://github.com/PyCQA/bandit)|Python 常见安全问题扫描；CI 静态门|8,200★ / 808⑂ / Apache-2.0 / 未核验|误报/规则版本需豁免台账|P1|
|144|[pypa/pip-audit](https://github.com/pypa/pip-audit)|Python 依赖漏洞审计和修复；供应链|1,346★ / 119⑂ / Apache-2.0 / 未核验|网络/漏洞数据库可用性，归档结果|P0|
|145|[aquasecurity/trivy](https://github.com/aquasecurity/trivy)|漏洞、配置、secret、SBOM 扫描；交付门|37,298★ / 576⑂ / Apache-2.0 / 未核验|扫描 scope 和误报要固定|P1|
|146|[ossf/scorecard](https://github.com/ossf/scorecard)|开源仓库安全健康评分；依赖选择|5,622★ / 694⑂ / Apache-2.0 / 未核验|仅作信号，不替代代码审计|P1|
|147|[sigstore/cosign](https://github.com/sigstore/cosign)|容器/二进制签名与透明日志；Windows 产物|6,194★ / 784⑂ / Apache-2.0 / 未核验|密钥/身份/离线验证流程需设计|P2|
|148|[renovatebot/renovate](https://github.com/renovatebot/renovate)|依赖自动更新；Bun/Python 周期维护|22,204★ / 3,222⑂ / AGPL-3.0 / 未核验|自动 PR 必须分组、锁版本、可回滚|P1|
|149|[pre-commit/pre-commit](https://github.com/pre-commit/pre-commit)|多语言 hooks；ruff/安全/格式统一入口|15,490★ / 997⑂ / MIT / 未核验|Windows hook 时间和离线缓存需控制|P1|
|150|[semgrep/semgrep](https://github.com/semgrep/semgrep)|模式静态分析；禁止 raw SQL/shell/跨层规则|16,146★ / 1,016⑂ / LGPL-2.1 / 未核验|规则维护和误报成本|P1|
|151|[microsoft/pyright](https://github.com/microsoft/pyright)|Python 静态类型检查；补齐现有 pytest/import 边界|15,574★ / 1,801⑂ / Other / 未核验|与 mypy 二选一，先增量 strict|P1|
|152|[python/mypy](https://github.com/python/mypy)|Python 可选静态类型；domain/application 契约|20,583★ / 3,270⑂ / Other / 未核验|全仓 strict 迁移面大|P2|
|153|[pylint-dev/pylint](https://github.com/pylint-dev/pylint)|Python lint/质量规则；代码坏味道补充|5,709★ / 1,292⑂ / GPL-2.0 / 未核验|规则与 ruff 重叠，许可证和噪声|P2|
|154|[sqlfluff/sqlfluff](https://github.com/sqlfluff/sqlfluff)|多方言 SQL lint/format；Store SQL 审查|9,851★ / 1,082⑂ / MIT / 未核验|SQLite 方言/动态 SQL 需校准|P1|
|155|[fpgmaas/deptry](https://github.com/fpgmaas/deptry)|未使用/缺失 Python 依赖检查；requirements 治理|1,455★ / 47⑂ / MIT / 未核验|动态导入/脚本需配置豁免|P1|
|156|[ionelmc/pytest-benchmark](https://github.com/ionelmc/pytest-benchmark)|pytest 基准插件；热路径回归门|1,443★ / 136⑂ / 未核验 / 未核验|基准环境漂移，结果只作同机比较|P0|

### 7.8 AI Agent、MCP 与 RAG（157–181）

| # | 项目 | 能力与本仓契合点 | 成熟度（页面快照） | 成本/风险 | 建议 |
|---:|---|---|---|---|---|
|157|[modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)|官方 MCP Python SDK；intel server/client 契约|23,928★ / 3,758⑂ / MIT / 未核验|版本快速演进；需 pin 和 schema contract|P1|
|158|[modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)|官方 MCP server 示例；工具权限/返回设计|89,335★ / 11,403⑂ / Other / 未核验|示例不等于生产安全，逐工具审|借鉴|
|159|[modelcontextprotocol/typescript-sdk](https://github.com/modelcontextprotocol/typescript-sdk)|官方 TS SDK；前端/跨进程 MCP 对照|13,096★ / 2,058⑂ / Other / 未核验|不在前端直连敏感 MCP|P2|
|160|[jlowin/fastmcp](https://github.com/jlowin/fastmcp)|Pythonic MCP server/client；快速写测试 server|27,113★ / 2,233⑂ / Apache-2.0 / 未核验|与官方 SDK 版本/抽象重叠|P1|
|161|[langchain-ai/langgraph](https://github.com/langchain-ai/langgraph)|可恢复 agent graph；复杂助手流程参考|39,165★ / 6,584⑂ / MIT / 未核验|引入状态图不应替代现有 run/event/Grant|P1|
|162|[langchain-ai/langchain](https://github.com/langchain-ai/langchain)|agent engineering platform；provider/tool 抽象参考|143,664★ / 23,933⑂ / MIT / 未核验|抽象层大、升级快，避免全量迁移|P2|
|163|[run-llama/llama_index](https://github.com/run-llama/llama_index)|文档 agent/OCR/RAG；研究资料检索参考|51,450★ / 7,886⑂ / MIT / 未核验|证据 provenance 和本地数据边界需自建|P2|
|164|[deepset-ai/haystack](https://github.com/deepset-ai/haystack)|生产 RAG pipeline/agent；检索/路由显式控制|26,142★ / 2,980⑂ / Apache-2.0 / 未核验|服务化/模型供应商复杂度|P2|
|165|[pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai)|typed AI Agent；结构化 tool output|19,136★ / 2,490⑂ / MIT / 未核验|不能产生权威行情/盈亏，需 mock contract|P1|
|166|[instructor-ai/instructor](https://github.com/instructor-ai/instructor)|LLM structured outputs；DTO/JSON 校验|13,697★ / 1,179⑂ / MIT / 未核验|与 PydanticAI/现有 schema 重叠|P2|
|167|[microsoft/semantic-kernel](https://github.com/microsoft/semantic-kernel)|多语言 AI orchestration；插件/记忆设计参考|28,429★ / 4,709⑂ / MIT / 未核验|跨语言生态过重，工具治理要自行保留|P2|
|168|[BerriAI/litellm](https://github.com/BerriAI/litellm)|多供应商 AI gateway；成本/重试/路由参考|55,845★ / 10,407⑂ / Other / 未核验|引入代理层和数据外发风险|P2|
|169|[dottxt-ai/outlines](https://github.com/dottxt-ai/outlines)|结构化生成/约束输出；无效 JSON 降低|15,535★ / 841⑂ / Apache-2.0 / 未核验|模型/provider 支持矩阵需测|P2|
|170|[ollama/ollama](https://github.com/ollama/ollama)|本地模型运行器；离线 AI/隐私 POC|178,027★ / 17,298⑂ / MIT / 未核验|模型内存、Windows GPU/CPU 和答案质量|P2|
|171|[vllm-project/vllm](https://github.com/vllm-project/vllm)|高吞吐 LLM serving；未来多用户服务参考|88,487★ / 20,422⑂ / Apache-2.0 / 未核验|GPU/Linux 服务化，单机桌面不适合|拒绝|
|172|[ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)|C/C++ 本地 LLM inference；轻量运行时参考|123,040★ / 21,441⑂ / MIT / 未核验|模型许可/量化/内存需单独审|P2|
|173|[weaviate/weaviate](https://github.com/weaviate/weaviate)|云原生向量数据库；RAG 服务架构参考|16,704★ / 1,358⑂ / 未核验 / 未核验|服务/数据迁移与当前单机冲突|拒绝|
|174|[milvus-io/milvus](https://github.com/milvus-io/milvus)|高性能云原生向量库；规模化检索参考|45,556★ / 4,170⑂ / Apache-2.0 / 未核验|多组件部署过重，AI 记忆可用本地方案|拒绝|
|175|[crewAIInc/crewAI](https://github.com/crewAIInc/crewAI)|角色式多 Agent 编排；证据子 Agent 参考|56,763★ / 8,093⑂ / MIT / 未核验|多 Agent 成本/不可预测性；现有 read_only lane 已足够|P2|
|176|[infiniflow/ragflow](https://github.com/infiniflow/ragflow)|RAG + Agent engine；文档检索产品参考|87,060★ / 10,231⑂ / Apache-2.0 / 未核验|部署和数据边界远超桌面需求|拒绝|
|177|[ag2ai/ag2](https://github.com/ag2ai/ag2)|原 AutoGen 的 AgentOS；协作 Agent 参考|4,839★ / 695⑂ / Apache-2.0 / 未核验|与现有 assistant manager/事件模型重叠|P2|
|178|[openai/openai-python](https://github.com/openai/openai-python)|官方 OpenAI Python SDK；provider API 一手实现|31,318★ / 5,116⑂ / Apache-2.0 / 未核验|密钥/模型能力必须进 ops catalog 和审计|维持|
|179|[anthropics/anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python)|官方 Anthropic Python SDK；provider 对照|3,800★ / 799⑂ / MIT / 未核验|同上，不能把模型数字当系统事实|维持|
|180|[googleapis/python-genai](https://github.com/googleapis/python-genai)|官方 Google GenAI Python SDK；provider 对照|3,904★ / 971⑂ / Apache-2.0 / 未核验|模型/region/计费和密钥治理|P2|
|181|[pydantic/logfire](https://github.com/pydantic/logfire)|AI/应用可观测；Pydantic 生态 trace 参考|4,416★ / 271⑂ / MIT / 未核验|外部 SaaS/PII 与 OTel 自托管选择|P2|

### 7.9 架构、开发工具与研究工作台（182–197）

| # | 项目 | 能力与本仓契合点 | 成熟度（页面快照） | 成本/风险 | 建议 |
|---:|---|---|---|---|---|
|182|[cosmicpython/book](https://github.com/cosmicpython/book)|Python 应用架构/领域建模；DDD/端口适配器参考|3,836★ / 569⑂ / Other / 未核验|借鉴，不照搬交易领域示例|借鉴|
|183|[fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template)|FastAPI 全栈模板；CI/部署清单参考|44,666★ / 8,894⑂ / MIT / 未核验|模板是 React/SQLModel/Postgres，违反当前约束|拒绝|
|184|[zhanymkanov/fastapi-best-practices](https://github.com/zhanymkanov/fastapi-best-practices)|FastAPI 分层/实践清单；API 薄层参考|17,854★ / 1,307⑂ / 未核验 / 未核验|按本仓 DDD/同步 SQLite 规则取舍|借鉴|
|185|[cookiecutter/cookiecutter](https://github.com/cookiecutter/cookiecutter)|项目模板生成；新 BC/测试骨架|25,049★ / 2,275⑂ / 未核验 / 未核验|模板不能覆盖实际边界和 README 义务|P2|
|186|[PyCQA/flake8](https://github.com/PyCQA/flake8)|Python lint/插件生态；规则迁移参考|3,810★ / 354⑂ / Other / 未核验|与 ruff 重叠，不并行设为主 lint|P2|
|187|[wemake-services/wemake-python-styleguide](https://github.com/wemake-services/wemake-python-styleguide)|严格 Python 风格规则；坏味道参考|2,885★ / 427⑂ / MIT / 未核验|噪声/迁移成本，选规则借鉴|P2|
|188|[asottile/pyupgrade](https://github.com/asottile/pyupgrade)|自动升级 Python 语法；维护工具|4,110★ / 216⑂ / MIT / 未核验|只在格式/版本升级批次使用|P1|
|189|[asottile/reorder_python_imports](https://github.com/asottile/reorder-python-imports)|自动整理 import；降低跨层漂移|784★ / 62⑂ / MIT / 未核验|自动修改需独立提交/审查|P2|
|190|[pytest-dev/pytest-mock](https://github.com/pytest-dev/pytest-mock)|pytest mock wrapper；adapter/LLM/网络隔离|2,036★ / 166⑂ / MIT / 未核验|优先真实纯函数，避免过度 mock|P1|
|191|[python-poetry/poetry](https://github.com/python-poetry/poetry)|Python 依赖/发布管理；lock 方案对照|34,291★ / 2,471⑂ / MIT / 未核验|与 uv/pip 选择其一，不改 Bun|P2|
|192|[pdm-project/pdm](https://github.com/pdm-project/pdm)|PEP 标准项目/依赖管理；lock 方案对照|8,674★ / 481⑂ / MIT / 未核验|与 uv/Poetry 三选一|P2|
|193|[jupyter/notebook](https://github.com/jupyter/notebook)|交互式 Notebook；研究探索/复现实验|13,286★ / 5,731⑂ / 未核验 / 未核验|不作为产品 UI，注意真实数据泄露|P2|
|194|[marimo-team/marimo](https://github.com/marimo-team/marimo)|可复现 Python reactive notebook/SQL；研究工作台|22,263★ / 1,217⑂ / Apache-2.0 / 未核验|适合实验，不绕 research run 冻结与审核|P1|
|195|[sphinx-doc/sphinx](https://github.com/sphinx-doc/sphinx)|Python 文档生成器；API/架构文档|7,960★ / 2,505⑂ / Other / 未核验|仓库已有 Markdown，需评估维护收益|P2|
|196|[mkdocs/mkdocs](https://github.com/mkdocs/mkdocs)|Markdown 文档站；研究/模块文档导航|22,317★ / 2,638⑂ / 未核验 / 未核验|静态产物，不改变应用运行时|P2|
|197|[pycqa/pyflakes](https://github.com/PyCQA/pyflakes)|轻量 Python 错误检查；ruff 规则来源/对照|1,454★ / 186⑂ / MIT / 未核验|不和 ruff 重复作为主门|借鉴|

## 8. 关键一手资料索引

以下链接用于核对清单之外的架构事实；项目级结论以第 7 节 GitHub 仓库链接为主。

- [SQLite WAL](https://sqlite.org/wal.html)、[SQLite threading](https://sqlite.org/threadsafe.html)：解释 WAL、连接和并发限制；本仓仍须以实际锁指标验收。
- [DuckDB 文档](https://duckdb.org/docs/)、[Polars 文档](https://docs.pola.rs/)、[Apache Arrow 文档](https://arrow.apache.org/docs/)：只读 OLAP/列式 POC 的 API 一手来源。
- [FastAPI async/concurrency](https://fastapi.tiangolo.com/async/)、[Uvicorn settings](https://www.uvicorn.org/settings/)、[APScheduler user guide](https://apscheduler.readthedocs.io/en/latest/userguide.html)：同步 SQLite 路由、单 worker 和调度语义。
- [Lightweight Charts 文档](https://tradingview.github.io/lightweight-charts/)、[TanStack Query Vue](https://tanstack.com/query/latest/docs/framework/vue/overview)、[TanStack Virtual Vue](https://tanstack.com/virtual/latest/docs/framework/vue/virtualizer)：前端 A/B 与长表 POC。
- [Playwright 文档](https://playwright.dev/docs/intro)、[Vitest 文档](https://vitest.dev/guide/)、[OpenTelemetry Python 文档](https://opentelemetry.io/docs/languages/python/)、[pip-audit 文档](https://pip-audit.readthedocs.io/)：CI/e2e/观测/供应链验收。
- [MCP specification](https://modelcontextprotocol.io/specification/latest)、[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)、[FastMCP](https://github.com/jlowin/fastmcp)：工具协议和 server/client POC；权限仍由本仓 ToolBus 决定。

## 9. 最终决策规则

每个候选进入默认依赖前必须有：一手 LICENSE/依赖许可证记录、POC 输入快照、性能与行为基线、错误/取消/重试语义、回滚开关、README/ADR、相关测试和 `lint-imports` 结果。任何候选若要求恢复旧 analyze/fetcher/reporter 链、跨上下文深掏 infrastructure、写入错误数据库、使用前视数据、让 AI 发明权威数字，立即归入 Reject。
