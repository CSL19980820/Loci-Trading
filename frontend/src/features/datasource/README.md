# datasource

数据源控制台：本机行情源（适配器线路）+ AkShare 接口目录，一处启停线路、一处浏览/全测接口。

- **入口**：工坊 Tab「数据源」（`/quant?tab=sources`）；运维旧 `?tab=lanes`、`?tab=akshare` 都重定向到这里（后者直落「按接口」）
- Tab 角标与页首读数**只数数据源家数**，不数线路条数、也不数接口数
- 三种视图（`SegmentSwitch`，本地状态；`initial-view` 支持深链）：
  - **按数据源** `SourceCardGrid` — 一源一卡：线路带、线路/启用/停用条数、接口数、中位耗时、探测与详情。只在 AkShare 目录里出现的上游（同花顺 / 雪球 / akshare 自身…）也是一张卡，打「接口源」标，没有总开关
  - **按用途** `LanePurposeBoard` — 一条线路一卡：自动/手选 + 失败回退即改即存、逐源快捷启停、顺位、探测；历史日 K 额外有下载测速；卡片高于视口时在面板 body 内滚
- **按接口** `AkshareToolTable` — `BasicTable` 占满高度；标题右侧「一键全测 / 停止 / 检查版本更新」；点全测弹出进度面板（通/败/跳过 + 响应时间）
- 顶栏「探测线路」只在按数据源/按用途出现（测行情适配器连通性）；按接口视图不再显示，避免和「一键全测」混淆。全量探测按线路逐个请求并即时回填；单源后端有墙钟超时，避免卡死页面。
- 类目/来源展示中文（`category_label` / `provider`），筛选用英文 id
- `SourceDetailDrawer`：单源详情；接口数可点，跳「按接口」并预选来源
- `McpToolListDrawer`：页首「MCP 工具清单」——线路工具 + 单一 `akshare_call`
- `LatencyMeter`：耗时读数条（慢用琥珀、失败用危险色）

## 两套机制，两种口径

| 对象 | 开关落点 | 效果 |
|---|---|---|
| 线路（日 K / 快照 / 分钟 / 资金流 / 证券列表…） | `patchLaneProvider`（带 `lane` 即逐工具） | 影响同步与选股选源；某条线路没有可用源时，对应 MCP 工具也不再出现 |
| AkShare 接口 | **无启停**；`probeAkshareCatalog` / `probeAkshareCatalogBatch` / `getAkshareVersion` | 浏览、试跑、一键全测、版本核对；MCP 经 `akshare_call` 按名调用 |

- 线路停用仍是两级：源总开关 / 逐 lane
- 默认适配器顺序：**东财（AkShare）优先**，新浪/腾讯直连作备源
- 必需线路被关空后端不拦，由本面板红字警告；必需线路只剩 1 个生效源时卡片打「仅 1 个源」。历史日 K 启用源全灭时，同步会把已关闭的日 K 源当最后回退，不把单源抖动写成整票失败

## 编排

- `composables/useDataSources.ts`：线路侧
- `composables/useAkshareTools.ts`：接口侧（进「按接口」才拉目录；`probeAll` 分页续跑；`checkVersion`）

## 相关测试

- `composables/useDataSources.test.ts`
- `components/LanePurposeBoard.test.ts`
- `components/AkshareToolTable.test.ts`：筛选/分页/全测与版本按钮/探测结果筛选/试跑表单
