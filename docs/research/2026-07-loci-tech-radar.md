# Loci 量化工作台 · 2026-07 技术雷达与选型报告

> **读者**：Loci / stock-analyzer 维护者与 Agent  
> **类型**：Explanation（选型与技术雷达）  
> **调研日**：2026-07-28  
> **范围**：对照当前栈（Vue3.5 / Vite7 / Pinia3 / Element Plus / ECharts6 / Tailwind4 / bun；FastAPI / pandas / SQLite / APScheduler / akshare / pywebview）检索公开技术文档，给出**可落地、不推翻现有架构**的后续选项。  
> **文献量**：前端 **55** 篇、后端 **55** 篇（见附录；含官方文档、迁移指南、量化同业实践）。  
> **修订（2026-07-28）**：P0 POC 已落地 — LwKline 开关 / Pool `el-table-v2` / Pinia Colada quotes / DuckDB `LOCI_MARKET_DUCKDB` / [async 审计](./2026-07-async-route-audit.md)。  
> **地基（同日）**：ADR-002、`lint-imports` 护栏、Vitest 烟雾、VueUse 持久化 LW 偏好。  
> **下一批（同日）**：指标 Worker+Comlink、Colada 扩 candidates/equity、`LOCI_BACKTEST_FAST`、Playwright 烟雾、rolldown 试构建、import-linter 扩至 9 合约 — 见 [foundation-next](./2026-07-foundation-next.md)。

---

## 0. 一句话结论

你们已经站在 **2025–2026 主流正确位置**（Vue3 Composition + Vite7 + Pinia setup store + FastAPI DDD + 三库 SQLite）。后续不该换框架，而应在三条线上**补刀**：

1. **金融图表专业化**（ECharts 保留总览，K 线主图考虑 Lightweight Charts）  
2. **分析引擎加速**（全市场/参数扫描用 DuckDB 或 Polars，pandas 继续做业务胶水）  
3. **服务端状态与重任务**（Pinia Colada / TanStack Query 管缓存；回测/同步继续进 ops Job，必要时 Taskiq）

**明确不建议**：为追新引入 Nuxt/React、把 palace 迁到 PostgreSQL、用 AI 产出权威行情数字、用第二套 UI 库替换 Element Plus。

---

## 1. 现状快照（对齐代码）

| 层 | 现状 | 痛点（从架构与依赖推断） |
|---|---|---|
| 前端壳 | Vue 3.5、Vite 7、TS 5.8、bun、Tailwind 4、Element Plus 2.14、Pinia 3 | 候选池/账本大表依赖 el-table；服务端缓存层偏薄 |
| 图表 | ECharts 6 自研 `KlineChart`（candlestick + MACD/KDJ） | 金融交互（十字线、多 pane、实时 update）不如专用库 |
| 后端 | FastAPI、同步 SQLite、pandas/numpy、APScheduler、akshare | 全市场面板/重算易堵；无 OLAP 旁路 |
| 架构 | DDD 限界上下文 + 三库隔离（palace/market/ops） | 已正确；任何新技术须服从「market 不写 palace、AI 不造数」 |
| 桌面 | pywebview + 托盘 | 与 SPA 同栈，前端包体积与构建速度直接影响体验 |

产品地图（摘自 `docs/architecture/bounded-contexts.md`）：ledger / market / review / strategy / backtest / ops / ai / intel / formula。

---

## 2. 前端雷达（按优先级）

### P0 · 建议 1–2 个迭代内评估

| 技术 | 与 Loci 的关系 | 动作建议 |
|---|---|---|
| **TradingView Lightweight Charts v5** | 官方 Vue wrapper 教程完备；同业量化 UI（FreqUI、Kainex 类）普遍用它做 K 线 | 新建 `shared/components/charts/LwKlineChart.vue` 做 **A/B**：主图 LW、副图指标仍可 ECharts；数字仍以后端/`formula` 为准 |
| **Pinia Colada 或 TanStack Vue Query** | 候选池、行情、复盘接口重复拉取；适合缓存/去重/后台刷新 | 先在 `market`/`review` 一页试点；**不要**把盈亏公式塞进 query 层 |
| **TanStack Vue Table（v9 beta）** | 候选池、成交、Job 历史列多、排序过滤重 | 与 Element Plus 并存：复杂表格用 headless + 现有 token；简单表继续 el-table |
| **VueUse** | WebSocket/SSE、本地偏好、节流、`useEventSource` | 渐进引入 composable，禁止再手写一套清理不全的监听 |

### P1 · 中期增强

| 技术 | 说明 |
|---|---|
| **vue-echarts / ECharts 按需** | 已用 `echarts/core` 按需，可再抽公共 option 工厂，避免每个 View 复制 |
| **虚拟列表**（vue-virtual-scroller / TanStack Virtual） | 候选池上千行时必用 |
| **Web Worker + Comlink** | 前端本地指标（你们已有 `@/shared/lib/indicators`）可下沉 Worker，避免卡 UI |
| **Vitest + Playwright** | 前端目前偏 typecheck/build；图表与路由级 smoke 值得补 |
| **rolldown-vite** | Vite 7 可 drop-in 试；加速 `bun run build`，桌面打包前收益明显 |
| **Monaco Editor** | ops 技能 YAML / 策略参数编辑（FreqUI 已用） |

### P2 · 观察，不急迁

| 技术 | 为何只观察 |
|---|---|
| Vue Vapor Mode | 仍偏实验；Composition API 已对齐，等稳定再谈 |
| shadcn-vue | 与「禁止再引入另一套组件库」冲突；仅可借无障碍层思路，**不整库替换 Element Plus** |
| Nuxt 4/5 | 桌面 SPA + FastAPI 静态托管模型下无必要 SSR |
| AG Grid / Highcharts | 商业授权与体积；单机工作台 ROI 低 |

### 前端「不要做」

- 不要为图表换 React。  
- 不要在前端重算权威胜率/总资产。  
- 不要把 localStorage 当成交账本。

---

## 3. 后端雷达（按优先级）

### P0 · 建议评估

| 技术 | 与 Loci 的关系 | 动作建议 |
|---|---|---|
| **DuckDB** | 同业量化仓（DuckDB quant engine、Kainex）用它做 OHLCV 分析；可直连 Parquet/Arrow；**不替代 palace.db** | 在 `market`/`review`/`backtest` 做只读分析附件或缓存旁路；账本事实仍 SQLite |
| **Polars** | 全市场筛选、因子面板比 pandas 省内存 | formula/选股热路径试点；对外 API DTO 仍用 list/dict |
| **Pydantic v2 边界纪律强化** | 你们已用 FastAPI≥0.115；继续 `extra=forbid`、Create/Read 分离 | 对照官方与生产指南扫一遍路由模型 |
| **sync `def` + threadpool 纪律** | 官方与生产文一致：SQLite 同步阻塞勿塞 `async def` | 与现有 AGENTS.md 一致，做一次路由审计 |

### P1 · 中期

| 技术 | 说明 |
|---|---|
| **vectorbt / Backtesting.py** | 参数扫描、策略可行性；**须遵守 entry_timing、禁止前视**；结果进 review 口径 |
| **pandas-ta / 自研 formula** | 指标进 `formula` 域，避免在路由堆 TA |
| **import-linter** | 六边形模板常用；CI 卡住「跨上下文掏 infrastructure」 |
| **OpenTelemetry（opt-in）** | Job/同步/AI 调用链路；桌面单机可先结构化日志 |
| **Taskiq / 现有 APScheduler 增强** | 重回测出进程；无 broker 时可继续 APScheduler，变重再上 Taskiq |
| **FastMCP / MCP 适配** | 与现有 `data/mcp.json`、skills 对齐；工具只读行情/复盘，禁止写 palace 旁路 |
| **uv + ruff** | 与 bun 对仗的 Python 工具链；不强制换，可并行试用 |

### P2 · 观察

| 技术 | 说明 |
|---|---|
| SQLAlchemy / SQLModel | 现手写 SQLite Store 清晰；全仓 ORM 迁移成本高，**不值得** |
| Litestar / Granian | FastAPI 已够；仅作对照阅读 |
| NautilusTrader | 事件驱动撮合过重；单机选股/复盘工作台过杀 |
| Redis / Timescale | 单机桌面默认不要上；除非以后多端协作 |

### 后端「不要做」

- 不要用 DuckDB/Polars 存成交权威事实。  
- 不要恢复已删除的 analyze/fetcher/reporter 旧报告链。  
- 不要让 AI 上下文产出「权威盈亏」。

---

## 4. 针对页面/上下文的落点映射

| 上下文 / 页面 | 可试点技术 | 价值 |
|---|---|---|
| market 行情 / K 线 | Lightweight Charts、Worker 指标 | 交互与流畅度 |
| strategy / pool 候选池 | TanStack Table、虚拟列表、Pinia Colada | 大表与重复请求 |
| review 复盘曲线 | ECharts 保留 + DuckDB 缓存查询 | 重算加速 |
| backtest | vectorbt/Backtesting.py + ops Job | 参数扫描不卡 UI |
| ops Job / 技能 | Monaco、APScheduler/Taskiq、OTel | 可观测与编辑体验 |
| ai / intel | MCP、LangGraph（可选） | 工具治理；数字仍来自引擎 |
| ledger 账本 | 保持 PalaceStore；表格增强即可 | 稳定性优先 |

---

## 5. 90 天建议路线（可裁剪）

```text
第 1–30 天
  - 路由 async/sync 审计 + 1 个 Pinia Colada 试点页
  - LwKlineChart POC（只读 market bars）
  - DuckDB 只读：对 market 导出的日 K 做聚合查询 POC

第 31–60 天
  - 候选池 TanStack Table 或虚拟列表二选一落地
  - backtest 参数扫描：vectorbt 或自研向量化，结果经 review API
  - import-linter 进 CI（可选）

第 61–90 天
  - rolldown-vite 试构建；Vitest 烟雾测试
  - MCP 工具权限表（只读域清单）
  - 写 ADR：DuckDB 旁路是否入库、可否整表删除
```

---

## 6. 与仓库硬规则的对齐检查

| 规则 | 本报告立场 |
|---|---|
| 单文件 ≤600 行 | 新图表/表格组件独立文件，禁止堆进巨型 View |
| 跨上下文不掏 infrastructure | DuckDB/Polars 适配器放本域 infrastructure，经包根导出 |
| market 不写 palace | OLAP 只碰 market/缓存 |
| 策略必须 entry_timing | 引入任何回测库时写验收用例防前视 |
| 不换另一 UI 库 | Element Plus 保留；新能力用 headless/专用图表 |
| README 同步 | 任一公开行为变更同批更新模块 README |

---

## 附录 A · 前端文献索引（55）

> 编号仅便于引用；优先读「官方 / 迁移指南」。

### A1 核心框架与构建（1–15）

1. [Vue.js 官网](https://vuejs.org/)  
2. [Announcing Vue 3.5](https://blog.vuejs.org/posts/vue-3-5)  
3. [Vue 3.5 Changelog](https://github.com/vuejs/core/blob/main/CHANGELOG.md)  
4. [Vue Composition API · Lifecycle](https://vuejs.org/api/composition-api-lifecycle.html)  
5. [Vue Router 官方](https://router.vuejs.org/)  
6. [Pinia 官方](https://pinia.vuejs.org/)  
7. [Pinia · Outside component / SSR 注意](https://pinia.vuejs.org/core-concepts/outside-component-usage.html)  
8. [Vite 官网](https://vite.dev/)  
9. [Vite 7 发布公告](https://vite.dev/blog/announcing-vite7)  
10. [Vite 7 Migration Guide](https://vite.dev/guide/migration.html)  
11. [Rolldown 集成说明（rolldown-vite）](https://github.com/vitejs/rolldown-vite/blob/main/docs/guide/rolldown.md)  
12. [Rolldown 官网](https://rolldown.rs/)  
13. [What’s next for Vue in 2025? · Vue Mastery](https://www.vuemastery.com/blog/whats-next-for-vue-in-2025/)  
14. [Vue.js 2026 生态综述 · Zignuts](https://zignuts.com/blog/vue-js-2025-nuxt4-vite6-pinia-guide)  
15. [Vue 完整 2026 指南 · Articsledge](https://www.articsledge.com/post/vuejs)

### A2 UI、样式、状态与表格（16–30）

16. [Element Plus 文档](https://element-plus.org/)  
17. [Tailwind CSS 文档](https://tailwindcss.com/docs)  
18. [Tailwind CSS v4 · Vite 插件](https://tailwindcss.com/docs/installation/using-vite)  
19. [Vue 3 + Tailwind 管理后台教程 · Djamware](https://www.djamware.com/post/vue-3-tailwind-css-build-a-responsive-admin-dashboard)  
20. [Vue + Pinia 全栈教程 2026 · Tech Insider](https://tech-insider.org/vuejs-tutorial-full-stack-app-pinia-2026/)  
21. [TanStack Table · Vue Quick Start](https://tanstack.com/table/latest/docs/framework/vue/quick-start)  
22. [TanStack Table Vue v9 beta Quick Start](https://tanstack.com/table/beta/docs/framework/vue/quick-start)  
23. [TanStack Query · Vue](https://tanstack.com/query/latest/docs/framework/vue/overview)  
24. [Pinia Colada（服务端状态）](https://pinia-colada.esm.dev/)  
25. [VueUse 文档](https://vueuse.org/)  
26. [shadcn-vue 官网](https://www.shadcn-vue.com/)（对照用，非整库替换）  
27. [shadcn-vue Nuxt 安装指南](https://www.shadcn-vue.com/docs/installation/nuxt)  
28. [unplugin-vue-components](https://github.com/unplugin/unplugin-vue-components)  
29. [TypeScript Handbook](https://www.typescriptlang.org/docs/)  
30. [vue-tsc / Volar 工具链说明](https://github.com/vuejs/language-tools)

### A3 图表与量化前端（31–42）

31. [Apache ECharts 官网](https://echarts.apache.org/)  
32. [ECharts · Candlestick 示例](https://echarts.apache.org/examples/en/editor.html?c=candlestick-simple)  
33. [vue-echarts](https://github.com/ecomfe/vue-echarts)  
34. [Cube · Vue3 + ECharts Dashboard](https://cube.dev/blog/building-an-apache-echarts-dashboard-with-vue-3-and-cube)  
35. [Best Vue Chart Library 2026 · FusionCharts 对比文](https://www.fusioncharts.com/blog/best-vue-chart-library/)  
36. [TradingView Lightweight Charts 产品页](https://www.tradingview.com/lightweight-charts/)  
37. [Lightweight Charts 入门文档](https://tradingview.github.io/lightweight-charts/docs)  
38. [Lightweight Charts · Vue Wrapper 教程](https://tradingview.github.io/lightweight-charts/tutorials/vuejs/wrapper)  
39. [lightweight-charts GitHub](https://github.com/tradingview/lightweight-charts)  
40. [TradingView 免费图表库对比](https://www.tradingview.com/free-charting-libraries/)  
41. [KLineChart 文档](https://klinecharts.com/)（备选）  
42. [FreqUI Ultimate（Vue3+ECharts 量化看板实践）](https://github.com/titouannwtt/frequi-ultimate)

### A4 工程、测试、性能、桌面相关（43–55）

43. [Bun 文档](https://bun.com/docs)  
44. [Vitest 文档](https://vitest.dev/)  
45. [Vitest 3.2 / Browser Mode](https://vitest.dev/guide/browser.html)  
46. [Vitest Browser Mode vs Playwright · Epic Web](https://www.epicweb.dev/vitest-browser-mode-vs-playwright)  
47. [Playwright 文档](https://playwright.dev/)  
48. [Component Testing with Playwright and Vitest](https://www.thecandidstartup.org/2025/01/06/component-test-playwright-vitest.html)  
49. [@vitest/web-worker](https://www.npmjs.com/package/@vitest/web-worker)  
50. [Comlink](https://github.com/GoogleChromeLabs/comlink)  
51. [vue-virtual-scroller](https://github.com/Akryum/vue-virtual-scroller)  
52. [MDN · EventSource (SSE)](https://developer.mozilla.org/en-US/docs/Web/API/EventSource)  
53. [MDN · Web Workers](https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API)  
54. [Monaco Editor](https://microsoft.github.io/monaco-editor/)  
55. [quant-platform（Vue3+Element+ECharts 量化前端参考）](https://github.com/wu-shaobing/quant-platform)

---

## 附录 B · 后端文献索引（55）

### B1 FastAPI / Pydantic / ASGI（1–15）

1. [FastAPI 官方文档](https://fastapi.tiangolo.com/)  
2. [FastAPI Reference](https://fastapi.tiangolo.com/reference/)  
3. [FastAPI · Concurrency and async/await](https://fastapi.tiangolo.com/async/)  
4. [FastAPI · Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)  
5. [FastAPI · Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)  
6. [FastAPI · Testing](https://fastapi.tiangolo.com/tutorial/testing/)  
7. [Starlette 文档](https://www.starlette.io/)  
8. [Uvicorn 文档](https://www.uvicorn.org/)  
9. [Pydantic v2 文档](https://docs.pydantic.dev/latest/)  
10. [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic-settings/)  
11. [FastAPI Production · async/Pydantic/OTel 指南](https://tomodahinata.com/en/blog/fastapi-production-async-pydantic-observability-guide)  
12. [FastAPI in Production · Async SQLAlchemy & Pydantic V2](https://ilirivezaj.com/guides/fastapi-production-guide)  
13. [FastAPI Best Practices 2026 · Pratik Pathak](https://pratikpathak.com/fastapi-best-practices-building-production-ready-python-apis-in-2026/)  
14. [FastAPI · Pydantic v2 Models · llmbestpractices](https://llmbestpractices.com/backend/fastapi-pydantic)  
15. [FastAPI Best Practices · Medium](https://medium.com/@abipoongodi1211/fastapi-best-practices-a-complete-guide-for-building-production-ready-apis-bb27062d7617)

### B2 数据引擎：pandas / Polars / DuckDB / SQLite（16–28）

16. [pandas 用户指南](https://pandas.pydata.org/docs/user_guide/index.html)  
17. [NumPy 文档](https://numpy.org/doc/stable/)  
18. [SciPy 文档](https://docs.scipy.org/doc/scipy/)  
19. [Polars 文档首页](https://docs.pola.rs/)  
20. [Polars Python API Reference](https://docs.pola.rs/api/python/stable/reference/)  
21. [Polars DataFrame.filter](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.filter.html)  
22. [DuckDB 文档](https://duckdb.org/docs/)  
23. [DuckDB · Python API](https://duckdb.org/docs/stable/clients/python/overview)  
24. [Modern DataFrames · Polars + DuckDB · Towards Data Science](https://towardsdatascience.com/modern-dataframes-in-python-a-hands-on-tutorial-with-polars-and-duckdb/)  
25. [Pandas vs Polars vs DuckDB 2026 · FastAPI 场景实测](https://medium.com/@rameshkannanyt0078/pandas-vs-polars-vs-duckdb-2026-i-processed-1-million-rows-in-fastapi-pandas-crashed-my-ram-c3f908546a2e)  
26. [SQLite 官方文档](https://www.sqlite.org/docs.html)  
27. [SQLite · WAL mode](https://www.sqlite.org/wal.html)  
28. [Python sqlite3](https://docs.python.org/3/library/sqlite3.html)

### B3 量化、回测、行情（29–40）

29. [AKShare 文档](https://akshare.akfamily.xyz/)  
30. [AKShare GitHub](https://github.com/akfamily/akshare)  
31. [AKShare · Backtrader 集成说明](https://deepwiki.com/akfamily/akshare/7.2-backtrader-integration)  
32. [Backtesting.py 官网](https://kernc.github.io/backtesting.py/)  
33. [Backtesting.py 入门 · IBKR Quant](https://www.interactivebrokers.com/campus/ibkr-quant-news/backtesting-py-an-introductory-guide-to-backtesting-with-python/)  
34. [VectorBT 文档](https://vectorbt.dev/)  
35. [pandas-ta](https://github.com/twopirllc/pandas-ta)  
36. [TA-Lib Python](https://ta-lib.github.io/ta-lib-python/)  
37. [duckdb-quant-engine（DuckDB+FastAPI 量化仓参考）](https://github.com/King0508/duckdb-quant-engine)  
38. [Kainex（DuckDB+SQLite+FastAPI 量化平台参考）](https://github.com/francismiko/kainex)  
39. [Freqtrade 文档](https://www.freqtrade.io/en/stable/)  
40. [NautilusTrader 文档](https://nautilustrader.io/docs/)（对照用，过重）

### B4 架构、调度、可观测、AI 工具（41–55）

41. [APScheduler 文档](https://apscheduler.readthedocs.io/)  
42. [httpx 文档](https://www.python-httpx.org/)  
43. [cryptography 文档](https://cryptography.io/)  
44. [pywebview 文档](https://pywebview.flowrl.com/)  
45. [SQLAlchemy 2.0 Overview](https://docs.sqlalchemy.org/en/20/intro.html)（对照，非迁移目标）  
46. [SQLAlchemy 2.0 Migration Guide](https://docs.sqlalchemy.org/en/20/changelog/migration_20.html)  
47. [import-linter](https://import-linter.readthedocs.io/)  
48. [Hexagonal FastAPI template（边界强制）](https://github.com/MatthiasEg/python-hexagonal-architecture-template)  
49. [FastAPI Hexagonal / DDD 模板](https://github.com/agustinrbeltran/fastapi-hexagonal-template)  
50. [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)  
51. [MCP Specification](https://modelcontextprotocol.io/)  
52. [FastMCP](https://gofastmcp.com/)  
53. [LangGraph 文档](https://langchain-ai.github.io/langgraph/)  
54. [Building Agents with MCP + LangGraph + FastAPI](https://sgino209.medium.com/building-smart-web-ai-agents-with-mcp-langgraph-fastapi-da2734fe5256)  
55. [uv 文档 · Astral](https://docs.astral.sh/uv/) · [Ruff](https://docs.astral.sh/ruff/)

---

## 附录 C · 同业栈对照（一眼）

| 项目 | 前端 | 后端分析 | 存储 | 对 Loci 启示 |
|---|---|---|---|---|
| Loci（本仓） | Vue3 + EP + ECharts | pandas + FastAPI | SQLite×3 | 保持；补图表与 OLAP 旁路 |
| FreqUI Ultimate | Vue3.5 + ECharts + Monaco | Freqtrade | — | 看板组件与技能编辑可借鉴 |
| Kainex | React + LW Charts + ECharts | FastAPI + Nautilus | DuckDB + SQLite | **双库分工**与你们三库同构 |
| duckdb-quant-engine | — | FastAPI + DuckDB | DuckDB | 行情分析仓参考 |
| quant-platform | Vue3 + EP + ECharts | FastAPI | — | 栈几乎同构，证伪「必须换框架」 |

---

## 维护

- 公开选型落地或否决时，请追加 ADR（如 `docs/adr/ADR-00x-…`）并在本文件顶部改「修订记录」。  
- 文献链接以官方为准；社区文仅作实践佐证，实施前再核版本。

**修订记录**

| 日期 | 说明 |
|---|---|
| 2026-07-28 | 初稿：前后端各 55 篇文献 + Loci 定制优先级 |
