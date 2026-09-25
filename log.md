# 改动日志

## 2026-09-10 · 胜率屏重做（去装饰、拿回垂直空间）

### 用户反馈

「胜率界面做的太差了，无法全部展示还非常浓的 AI 味各种线条，我是希望能很好的阅读性美观性」。

### 诊断

拿用户截图逐处点数，这一屏有 **14 条纯装饰线 + 4 个 emoji**，垂直空间被它们吃掉，
两张真正要读的表（各持有期表现、样本明细）只露出表头。

| 装饰 | 位置 | 为什么是装饰 |
|---|---|---|
| 3px 渐变顶条 ×3 | `.wr-hero::before` / `.period-studio::before` / `.deck-card::before` | 不承载状态，纯色块 |
| 卡片顶部色条 ×3 | `.wr-card--best/worst/horizon::before` | 卡内数字已是涨跌色，色条第二遍说同一件事 |
| 胜率进度条 ×7 | hero 一条 + 持有期表每行一条 + 三张对比卡各一条 + 对比表每行一条 | 同一格里已经写了「50.0%」和「3/9」，条形不增加信息 |
| 最佳行左侧色条 | `:deep(.is-best-horizon td:first-child)::before` | 行内已有「最佳」文字标签 |
| 无条件渲染的红圆点 ×2 | `.deck-card__indicator` / `.cmp-tag-indicator` | 三张卡/每一行都有，不区分任何状态 |
| emoji | 🚀 🛡️ ⭐ 📈 | 金融工作台不用 emoji；标签文字已说清是什么 |
| 柱子渐变 + 彩色投影 | `.chart-bar--up/down` | 柱子表达「涨跌 + 幅度」，渐变与投影不承载信息 |
| 卡片 hover 抬起 | `.wr-card:hover { transform }` | 洞察卡不可点，抬起是假的可交互暗示 |
| `box-shadow` ×6 | hero / card / block / studio / deck-card | 违反 D3：业务卡片不挂阴影 |
| 硬编码 `rgba(0,0,0,.0x)` ×4 | `.filter-pill.is-active` 等 | 写死的黑在 night/ink 完全不可见，选中态在深色下等于没反馈 |

另有两处「KPI 卡片化」：结论注脚（计算口径 / 结算进分母 / 盈利样本 / 窗口观察中）与
周期速览各四项，每项带一圈边框，两行格子吃掉两行高度。它们是**胜率的注脚**，不是
八个独立 KPI —— business-ui 那条「不要加只重复表格计数的 KPI 卡」正指这个。
还有一个卡内嵌套盒子（`.deck-card__info-box` 灰底 + 边框）：卡片本身已是容器。

### 改法

装饰全删，层次改由排版承担：字号（`--fs-micro` 标签 → `--fs-title` 标的 →
34px 结论数字）、字重、颜色、留白。涨跌语义只由数字自己的颜色表达（D1）。

| 文件 | 改动 |
|---|---|
| `WinRateStrategyPanel.vue/.css` | hero 大卡 + 4 个 KPI 格 + 公式条 → 一行结论；三张卡去 emoji/色条/hover/数字色底；表格内进度条与最佳行色条删除 |
| `WinRatePeriodTable.vue/.css` | 去 📈 与渐变顶条；4 个 KPI 格 → 注脚行；柱子改纯色；`flex: 0 1 6.5rem` 让少数据时柱子靠左而不是各占半屏 |
| `WinRateCompareTable.vue/.css` | 卡片去渐变顶条/抬起/发光圆点/阴影（保留 hover 边框+底色——它是可点的）；删卡内嵌套盒子、两处装饰圆点、三处进度条、重复的「点击查看样本证据」 |
| `features/review/README.md` | 新增「胜率屏的装饰禁令」一节，逐条列出删了什么与为什么，附一条判断准则 |

改动中引入并自查出一个回归：用 `text.index()` 整段替换 KPI 样式时，把恰好落在两个
锚点之间的图例样式（`.period-studio__legend` 等四条）一起删了，真机截图里
「正收益负收益胜率胶囊」挤成一串。已原样补回并复验 gap 12px。

### 验证

- 真机 Chromium 1568×900，代表性 fixture（3 个战法、9 条样本、含长中文名「中芯国际集成
  电路制造」、观察中样本、负均收益 + 正胜率、4 个月份趋势）。本机 palace.db 是空库，
  用户截图那份数据在线上，按仓库规矩不碰线上，所以走 fetch 桩注入。
- 装饰元素计数：`document.querySelectorAll('.wr-mini-meter, .wr-hero__meter-track, .deck-card__bar, .cmp-meter__track').length` = **0**。
- 明暗两档取 computed 值核对：全部走令牌、零硬编码色值，两档同时成立
  （深色档实测 `--n-2 = oklch(0.232 0.021 258)` 深底、边框 `oklch(0.33)` 可见、
  涨 `rgb(246,113,104)` / 跌 `rgb(87,195,123)`）。
- `bun run typecheck` 通过；`bunx vitest run src/features/review` 39 用例全绿；
  `bun run test` 154 文件 / 766 用例全绿；`bun run build` 通过。
- 四个文件全部 ≤600 行（499 / 495 / 403 / 430 / 274）。

### 没做的

这一屏仍需滚动才能读完两张表——内容量本来就大于一屏（结论 + 三张卡 + 两张表 + 分周期）。
把「分周期」挪进独立 Tab 能解决，但那是改信息架构与用户已有操作习惯，超出本次范围。
当前状态下滚动前能看到结论、三张卡、两张表的表头与前两行；改前是表头都露一半。

## 2026-09-10 · 安全审查与修复（一条 critical、一条 high）

派只读安全审查过了一遍多租户边界。**租户隔离本身的设计质量高于文档自述**：
任务书给的四个「库路径 import 期固化」候选逐个核过真实消费路径，全部只是兼容
常量、无消费方；`src/ai/README.md` 里那份「已知未修」清单已经过时。鉴权侧
`compare_digest` 恒时间比较、Cookie httponly+samesite、口令 scrypt+dummy-verify、
community 的 owner 校验、identity 的 user_id 作用域 SQL 均已核过，无绕过。

**未发现任何一个租户能通过传 id / slug / 路径参数直接读到另一个租户的资源**
（跨租户共享的 identity.db / community.db 每一条读写都带 user_id 或 require_owner；
租户私有数据物理分库，ID 天然不跨库）。S608 报的 99 处 SQL 拼接分类核完：真参数
拼接 5 处、全部不可被攻击者控制，其余是表名/占位符/白名单片段。

### critical：技能包 = 任意代码执行，而上传只需 write 权限

完整链条（五步全经公开 HTTP 接口）：任意已登录租户（含最低权限 member）
→ `POST /api/skills` 上传 zip → `POST /api/skills/{slug}/runs` 启动
→ `drive_skill_run(run_subagents_first=True)` 在**调用 LLM 之前**无条件跑完
frontmatter 里 `agents[]` 声明的 CLI 子任务 → 容器内 root 执行 → 读取全部租户的
palace.db / ops.db / identity.db（含明文 LLM/MCP API Key）。

不需要说服模型、不需要有效 API Key——`run_subagents_first` 是硬编码 True。

两侧都修了：

1. **argv 白名单**（`skill_cli.build_command`）。旧实现靠「像不像路径」决定要不要
   jail：`bash` / `sh` / `curl` / `node` 既没有路径分隔符也没有
   后缀，于是原样入 argv 交给 subprocess 经 PATH 解析——**文件 docstring 声称的「可执行
   路径必须落在 skill 根内」在实现里根本不成立**。现在反过来：argv[0] 只认白名单解释器
   或技能包内**确实存在**的文件，其余一律拒；`python -c` / `-m` 也拒（否则
   SKILL.md 本身就是可执行载荷）。
2. **上传/卸载改管理员专属**（用户决策）。白名单只挡「跑包外的东西」；包内的 `.py`
   是上传者自己写的，拦不住也不该拦——所以边界必须挪到「谁能上传」。三个装/卸端点
   （`POST /api/skills`、`POST /api/skills/sync-templates`、`DELETE /api/skills/{slug}`）
   加 `require_admin_context`。桌面单机不注入身份依赖 → 只剩写鉴权（本机单用户，
   种子账号本身就是管理员），行为不变。

两条测试各自做了变异验证：去掉 `is_file()` 白名单 → 6 failed（bash/sh/curl/node/
powershell 全部不再被拒）；删掉上传端点的守卫调用 → 上传从 403 变 422（说明授权闸门
真的没了，包校验才是第二道）。

### high：平台级配置端点缺授权 + 任意路径写

`POST /api/ops/data-location` 写的是**进程级全局**的 `loci.config.json` 的
`data_dir`，却只挂 write guard；除写配置外还会在请求给的任意绝对路径上 `mkdir(parents=True)`、
写探针、建三个 SQLite 库——生产容器以 root 跑。

减损项（审查自己核证的，不能算在攻击者头上但必须写清）：`data_dir()` 的取值顺序是
`LOCI_DATA_DIR` → `PALACE_DATA_DIR` → 配置文件，而生产镜像里
`ENV LOCI_DATA_DIR=/app/data` 是硬编码的，所以写进配置文件的值**不会生效**。

修法：环境变量已钉住数据目录时**直接 409 拒绝**（连同 `POST /api/ops/desktop-shortcut`，
服务端没有桌面）。把「静默无效 + 真实副作用」换成「明确拒绝」；桌面单机不设这两个
环境变量，行为不变。

### 纵深：容器非 root（已写改动，**未部署**）

`deploy/Dockerfile` 建 `loci(10001)` 用户并装 `gosu`；
`docker-entrypoint.sh` 保持 root 起步、先 `chown` 数据卷再 `gosu` 降权
——已有卷里的库文件都是 root 所有，直接加 `USER` 会让容器写不了库。这是
postgres / redis 官方镜像的通行形状。三条兜底：已是非 root 则跳过、没有 gosu 则告警但
仍启动、`LOCI_SKIP_PRIVDROP=1` 逃生开关。

**按用户决策不部署**：需要在服务器上起一次性容器确认能写库、能起服务后再滚正式版。
步骤见 `deploy/README.md` 的「非 root 验证」一节。

### 记录但未改：会话 Cookie 不带 Secure

`deploy/.env.example` 给生产默认写死 `PALACE_INSECURE_HTTP=1`，会话 Cookie
不带 Secure，而站点同时提供 http:// 与 https:// 且未强制跳转——中间人能直接拿到 30 天
有效的会话令牌（该 token 不绑 IP、不绑 UA）。正确顺序在模板注释里已经写了：先
`patch-nginx-site.py --redirect-http` 开 301 + HSTS，再把开关改 0，顺序不能反。
**按用户决策只记录，线上操作由用户执行。**

## 2026-09-09 · 全面优化一轮（性能 / 架构 / 结构 / 缺陷 / 静态门禁）

### 实测性能收益

| 路径 | 改前 | 改后 | 倍数 | 依据 |
|---|---|---|---|---|
| 实时信号引擎 `evaluate()`（500 票 × 6 规则 / tick） | 766 ms | 219 ms | 3.5× | 微基准，3 秒 tick 下 CPU 占用 25% → 7% |
| ├ `_tail_series`（每 tick 1000 次） | 317 ms | 24 ms | 13× | numpy 直拼 + RangeIndex，去掉 `pd.concat` 的索引对齐 |
| └ MACD 规则 | — | — | — | `MACD_DEA` 内部重算 `MACD_DIF`，改直接 `EMA(dif, n)`，每票省两次 EMA |
| 候选跟踪 `_series_from_panel`（500 票 × 3 字段） | 202 ms | 67 ms | 3× | `searchsorted` 二分定位取代全 index 字符串掩码 |
| 前端 dist JS 总量 | 16.57 MB | 7.34 MB | −55.7% | Monaco 从 `editor.main` barrel 换 `editor.api` + 按需语言；ts/css/html worker 三个分片（8.7 MB）整体消失 |
| 大屏 SSE 每帧（400 行 / 3 秒） | 4 次全排序 + 2 次 Map 全复制 | 单趟部分选择 + 原地 `set` | ~9× 比较次数 | 指数点列从每帧 3400 次数字拷贝降到 7 次 push |

### 修掉的真实缺陷（不是重构，是本来就坏的）

| 缺陷 | 位置 | 后果 |
|---|---|---|
| 未定义的 `logger` | `src/ops/application/paper_eod_bars.py:75` | 面板批量取数失败时降级路径当场 `NameError`，把一次可恢复的查询失败升级成日终回看任务崩溃。ruff F821 抓到 |
| 整个测试函数体缩进错位 | `tests/strategy/test_screen_run_cancel.py` | 函数体全部落在 `return` 之后，**0 个断言在跑**。已重建并用变异验证（改坏被测代码后确实变红） |
| 时间炸弹测试 | `tests/review/test_insights.py` `OverlapTests` | 数据写死 `2026-06-01`，而 `compute_overlap` 的 cutoff 是 `today - 90 天`；2026-08-30 之后整组恒红 |
| `__all__` 里躺着 7 个不存在的名字 | `src/ai/application/assistant_rich_state.py:379` | `*_RICH_KEYS` splat 的是载荷字段名不是模块符号，`import *` 会 AttributeError |
| ContextVar 可变默认值 | `src/shared/observability.py:44` | `default={}` 在所有上下文共享；任何一处原地写入会永久污染全部未 set 的上下文（多租户下 = trace_id 跨用户泄漏）。改 `MappingProxyType({})` 让这种写法当场报错 |
| `.tape__row` 缺 `display` | `PulseIndexStrip.vue` | 裸 `span` 上的 `align-items`/`gap` 完全不生效，静默失效 |
| 登录页定时器泄漏 | `LoginView.vue:70` | 无卸载钩子，登录成功跳转后 `resendTimer` 继续对已卸载组件的 ref 写满 60 次 |
| 主色上的白字对比度不足 | `AppSidebar` / `HeaderActions` / `DataQueryDetailPanel.css` | amber 主色实测 2.53:1（明档）/ 2.03:1（暗档），改 `var(--on-primary)` 后 7.05:1 / 8.74:1 |
| 东财分钟线整列静默判 NaT | `src/market/infrastructure/eastmoney_minute.py:239` | trends2 与 kline 两个接口的时间戳宽度不一（`09:31` / `09:31:00`）。`pd.to_datetime` 不指定 format 时按**首值**定格式，混排里第二种被 `errors="coerce"` 静默变 NaT 后 dropna 丢掉。改 `format="ISO8601"` 两种都吃 |

### 架构

补齐 2026-09-09 架构复审遗留的两条缺口：

1. **进程级选股容量许可统一到五类入口**。新建 `src/shared/screen_capacity.py`（FIFO 公平 +
   可取消 + 状态快照），原来只有 Job 执行器有闸门，HTTP 异步/同步选股、`/api/screen/today`、
   AI 助手工具三类入口完全裸奔——而「三档并发触发 memcg OOM 打掉整个容器」是实测事故。
   `market_gate.screen_memory_slot` 退化为纯适配器，不再是第二份真相。
   两档排队策略的分界是**调用方能不能等**：后台任务与异步执行体排队（可取消），
   同步 HTTP 与模型回合 `wait_sec=0` 直接返回忙。
2. **热库选择判据收口**。`hot_fallback_reason` 成为唯一判据并从 `src.market` 导出，
   原来四处手抄版只有异步选股那份带预热日历校验，其余三处查历史日会**静默丢票**
   （`screener._resolve_start` 的 `max(0, len(days) - bars)` 无声钳位 + `load_panel(min_bars)` 丢票）。

行为变化：多战法从「真并行」变成「槽仍是多个、真正开面板的同时只有一个」。
`test_second_strategy_queues_instead_of_doubling_memory` 钉死这条，并已验证移除闸门后它会红。

### 结构

| 文件 | 改前 | 改后 |
|---|---|---|
| `src/market/application/realtime_signals.py` | 899 | 460 + `realtime_rules.py` 389 + `realtime_rule_config.py` 143 |
| `src/shared/boot_splash.py` | 703 | 25（门面）+ assets 336 + handoff 321 + markup 81 |
| `src/intel/application/brief.py` | 602 | 188 + `brief_payload.py` 155 + `brief_sections.py` 310 |

对外契约零变更：原模块重导出全部公开符号，调用方不必知道拆过。

前端（7 个超限文件全部拆完，对外契约零变更）：

| 文件 | 改前 | 改后 |
|---|---|---|
| `shared/components/layout/AppSidebar.vue` | 747 | 188 + `AppSidebar.css` 397 + `useSidebarNav` 140 + `useRoutePrefetch` 66 + `sidebarHelp` 35 |
| `shared/components/ui/BasicTable.vue` | 607 | 402 + `BasicTableToolbar.vue` 131 + `useBasicTableSource` 124 + `useBasicTableEdit` 44 + `useBasicTableHeight` 43 |
| `shared/types/screenSkill.ts` | 627 | 19（聚合入口）+ 10 个领域文件，最大 131 |
| `features/ops/components/PaperQuantPanel.vue` | 633 | 47 + 4 张卡片组件 + 3 个 composable |
| `features/ops/components/JobsTab.vue` | 607 | 478 + `jobPresentation` + `useJobsCatalog` |
| `features/ledger/PoolView.vue` | 613 | 444 + `PoolCandidateDialog.vue` + `usePoolFilters` + `poolLabels` |
| `features/research/components/ResearchBacktestPanel.vue` | 607 | 390 + `useResearchBacktestJob` + `researchBacktestStatus` |
| `features/review/components/WinRateStrategyPanel.vue` | 738 | 357 + `WinRateStrategyPanel.css` 389 |

两条踩过的坑写进了代码注释：

1. **抽 SFC 样式要用 `<style scoped src="./x.css">`，不能用 `@import`**——`@import` 进来的规则
   拿不到 scope id，选择器会漏到全站（本仓 `live-theme.css` / `pulseSkin.css` 因此是刻意不 scoped 的）。
   已在 build 产物里核实：`.wr-panel[data-v-8855a3cb]`、`.side-menu[data-v-119460a3] .el-menu-item`。
2. **拆出来的新组件一个都没有单测**。script setup 的模板引用的是 setup 里的变量本身，漏一个
   destructure 不会被 `vue-tsc` 抓到，只在 render 时抛 ReferenceError。新增
   `features/ops/components/splitRenderContracts.test.ts` 真挂载它们跑一遍（7 个用例），
   并做了变异验证：把模板里的 `strategyText` 改成错名字，它会红。
   顺带修掉这条测试自己的两处假绿——`vi.mock` 工厂被提升到 import 之前会撞 TDZ；
   三个断言文案原来互相含子串，漏渲染一个会被另一个掩盖。

### 静态门禁

- `ruff --select F` 从 report-only 变成**硬门禁**，存量 150 条清到 0。其中 F401 有 12 条是真重导出，
  改成 `X as X` 显式标记而不是删——**2 条是靠 grep 字符串引用（`mock.patch("模块.符号")`）捞回来的**，
  静态 from-import 扫描看不见。
- gitleaks 密钥扫描从 report-only 变成**硬门禁**（去掉 `continue-on-error` 与末尾 `exit 0`）。
- pip-audit / zizmor 保持 report-only，但结果写进 `$GITHUB_STEP_SUMMARY`，不再是无人读取的 artifact。
- `tests/conftest.py` 补三处环境隔离缺口：`LOCI_BACKTEST_EXECUTION`（决定回测走线程还是子进程）、
  `LOCI_SCREEN_JOB_CONCURRENCY` / `LOCI_SCREEN_QUEUE_WAIT_SEC`，以及选股许可的进程级全局重置
  （默认排队上限 20 分钟，一个漏掉许可的用例会让整套测试静默挂 20 分钟而不是失败）。

### 测试套件

`pytest --durations=40` 排出来最慢的两条是 `tests/ops/test_sync_jobs.py` 的两个
失败报告用例，21.25s + 18.43s，占全套 450s 的 9%。**它们在真的出网**——用一次性 socket
探针实测：同一个文件跑一遍产生 **117 次真实 connect**，目标是通达信服务器（端口 7709，
49 台轮询）与 `data.gtimg.cn:443`。

根因：`today_refresh` 模式会走 `_finalize_today_with_authoritative` →
`sync_quotes`，而这两条用例 patch 了 `MarketStore` / `sync_instruments` /
`apply_today_spot` / `refresh_adjust_factors` / `backfill_missing_turnover` /
`mirror_recent_to_hot` 六个，**唯独漏了 `sync_quotes`**。同文件第一条用例
（定稿顺序）反而 patch 了它——是疏漏不是设计。

这违反 AGENTS.md §3.4 的「测试不许出网」，代价不只是 40 秒：CI 上打中国的行情服务器
大概率超时，而两条用例断言的恰好是「失败被报告在结果里」，**超时也能让它们绿**——
于是这条铁律被破了很久都没人发现。

修法两步：

1. 补上 `patch("src.market.sync_quotes", ...)`，并在旁边写清为什么必须 patch 它。
   5 条用例 **28.31s → 0.80s（35×）**。
2. 给该文件加**文件级出网守卫**：记账 + teardown 断言，守 `socket.socket.connect`
   而不是 `urlopen`（通达信走裸 socket，urlopen 拦不到）。为什么不当场抛：行情适配器
   的契约就是「吞掉一切网络异常、回退下一个源」，在 connect 里抛错会被它自己接住翻译成
   「这个源不通」，用例照样绿——`tests/ops/test_notify_channels.py` 的注释里已经
   记过同一个教训。

变异验证：去掉其中一个 `sync_quotes` patch，守卫立刻报
`AssertionError: 用例试图真的出网（行情源必须 mock）`，恢复后 5 passed / 0.82s。

### 样式

- 文档与实现对齐：`frontend/AGENTS.md` §3.9 与 `frontend/docs/ui-spec.md` 共 31 项令牌数值向
  `style.base.css` 对齐（`--fs-hero` 文档 17px / 实际 20px、`--radius` 3px / 6px、`--row-h` 28 / 32……），
  并立硬规则：**令牌真值只在 CSS，文档只是副本；`var()` 不写 fallback**。
- 7 个文件清掉 44 处死 fallback（`:root` 无条件定义，fallback 分支永不进入，只会误导下一个照抄的人）。
- 7 个助手卡片逐字重复的外壳收成一份 `assistant-card.css`；`DataQueryDetailPanel.css` 删 30 行纯重复。

### 验证

- `pytest tests/ -q`：**2710 passed, 464 subtests passed**（基线 2392 passed + 1 failed）
- `ruff check --select F src cli tests`：All checks passed
- `tools/import_smoke.py`：imported 585 modules, 0 failed
- `lint-imports`：14 条契约全 KEPT
- `bun run typecheck`：通过；`bun run build`：通过（5.2s）
- `bun run test`：**154 个文件 / 766 个用例全绿**（基线 150 / 735）
- 生产代码**零**超 600 行文件（改前 15 个，其中 9 个是生产代码）

**未做**：线上部署与线上核验。本轮改动量大（182 文件、净减 1524 行），且触及实时链路与选股并发语义，
应先在服务器起一次性容器验完再决定是否部署。

## 2026-08-29 · 登录页重做（双栏门面）

### 背景

旧版 `LoginView` 是一个 700px 宽的卡片浮在 `--paper` 平色里，内容只占 1440×900 视口的
18%。真正的病根不是配色而是对比度：底色 `#f4f6f9` 与卡片 `#fbfcfe` 只差 2% 亮度，
边框又只有 1px 淡灰，整块看着像还没加载完。

参照 GitHub / Vercel / Grok、Microsoft / SpaceX、Meta / Google / Stripe 出了三稿，
选定 **Meta / Google / Stripe 一路的满高双栏**。

### 改动文件

| 文件 | 改动 |
|---|---|
| `frontend/src/features/ledger/LoginView.vue` | 重写 template 与 style，改成满高双栏骨架；登录表单抽成子组件；612 → 489 行 |
| `frontend/src/features/auth/LoginBrandSide.vue` | **新增**：左侧深色品牌侧（暖冷双光晕 + 点阵 + 抽象曲线 + 能力卡） |
| `frontend/src/features/auth/SigninForm.vue` | **新增**：登录表单态抽成组件，与另外四态对齐 |
| `frontend/src/features/auth/README.md` | 新增 §1.0 骨架与尺度，写清三条改动前必读约定 |

其余四个表单态（`SignupForm` / `VerifyEmailForm` / `ForgotPasswordForm` /
`ResetPasswordForm`）与 `QrLoginPanel` **未改**，靠容器变量与 `:deep` 统一尺度。

### 关键决策

1. **门面页尺度放大一档**：`.auth-panel` 局部覆写 `--ctl-h: 52px`、`--radius: 10px`
   （工作台内部仍是 30px / 6px）。覆写密度令牌本身而不是 EP 桥接变量——
   `style.components.css` 的 `.el-button--small { height: var(--ctl-h) }` 直接读它，
   只设 `--el-component-size-small` 会出现输入框 52px 而按钮停在 30px。
2. **品牌侧固定深色**，不跟随四档外观：四档令牌里没有这么深的层级，且它是门面画面
   不是工作面。表单侧走 `--surface`，四档都成立。
3. **两侧之间加 `rgba(255,255,255,.07)` 分隔线**：ink 档表单侧 `#1c1c1c` 与品牌侧
   `#0b0d12` 几乎同色，没这条线分不开；day / paper 档表单侧接近白，这条线自然隐形。
4. **不放任何编造的行情数字**：品牌侧玻璃卡是抽象曲线 + 三条能力说明。要显示
   「覆盖标的 5,542」这类统计得先有免鉴权的公开快照端点。
5. **右上角放外观切换**（`el-segmented`）而不是「帮助 / English」这类不存在的链接。

### 验证

- `bun run typecheck` 通过
- `bun run test` 通过：150 个文件 / 735 个用例
- `bun run build` 通过
- 本地浏览器实测四档外观（day / paper / night / ink）与 820px 窄屏折叠，逐档截图确认
- 无新增超 600 行文件（`LoginView` 489 / `LoginBrandSide` 246 / `SigninForm` 127）

### 线上部署（2026-08-29 21:08）

`pwsh .\deploy\deploy.ps1` 全量部署，耗时约 16 分钟（服务器装配镜像，pip 拉包约 200KB/s）。

| 项 | 值 |
|---|---|
| 镜像 | `loci-qianlong:2.0.0-20260829-205221` |
| 上一版（可回滚） | `loci-qianlong:2.0.0-20260829-204833` |
| 容器状态 | `healthy` |

线上核验（不以「部署成功」代替「修复生效」）：

- `docker inspect` → `healthy`，镜像标签为本次新标签
- `curl -H 'Host: qianlong.chenkit.cloud' http://127.0.0.1/login` → 200，`/api/health` → `{"status":"ok"}`
- 浏览器打开 <http://qianlong.chenkit.cloud/login>，DOM 里 `.auth-shell` / `.brand-side` /
  `.el-segmented` 均存在，输入框实测 52px（新尺度已生效），截图存档

生产配置下 `email_signup` 关闭且未配第三方 provider，所以线上不渲染「注册」与扫码按钮——
这是 `GET /api/auth/options` 的正常表现，不是回归。副作用是表单更短、垂直居中后上下留白
比本地多一档。

### 上线后的三处微调（依据：17 个大厂登录页的 computed CSS 实测）

部署完成后拿到两份实测调研（Playwright 抓 GitHub / Google / Stripe / Claude / Vercel /
Linear / Facebook 等 17 站的真实 CSS 值），对照发现三处偏差，已改但**尚未部署**：

| 改动 | 依据 |
|---|---|
| 品牌陈述字距 `+0.02em` → `-0.01em` | 大字必须负字距（x.ai 60px 配 −0.025em、Vercel 32px 配 −0.03em、Meta 130px 配 −0.05em）。`ui-spec` 的 `+0.03em` 是给 14px 密排中文的，48px 以上再撑开会散架；中文不能负到西文那个量级，−0.01em 是上限 |
| 点阵底纹加径向遮罩 | 「一个你能注意到的底纹，就是一个正在和文字竞争的底纹」。原先点阵在整幅均匀铺开，会和 52px 标题抢注意力 |
| 表单区 `padding-bottom` 48 → 64px | 内容中心比视口中心上移约 4%。Google 卡中心 y=418 / Stripe y=481 / Microsoft y=422（视口中心 450），精确居中会把表单读成孤岛 |

验证：`typecheck` 通过，`bun run test` 150 文件 / 737 用例全绿（首跑 4 个 flaky，是 dev server
与假后端同时占端口所致，重跑两次均全绿）。

**已于 2026-08-29 22:05 部署上线**，镜像 `loci-qianlong:2.0.0-20260829-220425`。这次只用
64 秒（首次 16 分钟）——`requirements-server.lock.txt` 没变，Docker 把 `pip install` 那层
整个缓存命中了。线上核验：`letter-spacing: -0.52px`、点阵 mask 为 `radial-gradient`、
`padding-bottom: 64px`，三处都已生效。

### 还没做的两条（依据同上，属于取舍不是缺陷）

1. **视觉侧应该放真实产品界面而不是抽象图形。** 这是 2026 年的明确转向（Figma 放会动的
   画布、Linear 全站不用抽象插画），也是两份调研共同的第一建议。对本产品最自然的填充物是
   `TickerTape` / `IndexBar` / `HeatStrip` 喂上一交易日收盘快照——**前提是先有一个免鉴权的
   公开快照端点**，登录前拿不到鉴权会话。
2. **金融类偏好暖近黑而非冷蓝黑**（Ramp `#1C1B17` / Retool `#151515` / Mercury 终端
   `#1A1917`）。当前品牌侧 `#0b0d12` 是冷蓝的，但本版有意做了「朱红暖光 + 靛蓝冷光」的
   冷暖对比，换暖底要连两枚光晕一起重调，不是改一个色值的事。
