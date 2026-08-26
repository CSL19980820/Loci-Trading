# 共享内核（shared）

## 职责
跨限界上下文的横切能力：数据根路径、桌面快捷方式、请求/任务/工具相关性。不含业务规则。

## 边界
- 可被所有上下文依赖
- 禁止依赖 ledger / market / review 等业务包（paths 内延迟 import 建库除外）

## 关键入口
- `src.shared.boot_splash` — 全屏分时启动页（enter：0→缓爬，服务就绪后原生页约 1s 拉到 100% 再交接 SPA；SPA 不重复开幕；exit/error 安静落章）
- `src.shared.paths` — `data_dir` / 三库路径 / `ensure_data_dir`
- `src.shared.api_deps` — HTTP 入站共用：`missing_dependency`（缺依赖 → 503 而非 500）、`market_store` / `market_hot_store` / `ops_store` / `palace_store` 打开器、`MAX_UPLOAD_BYTES`。对各上下文一律函数内懒导入，本模块因此不静态依赖任何限界上下文
- `src.shared.api_models` — 请求模型基类 `QuantModel`（`extra="forbid"`）与 `UniverseSpecModel`。各上下文 `api/schemas.py` 从这里继承；**不要**把具体业务 DTO 放进来
- `src.shared.clock` — `utc_now()`：审计链统一的 ISO-8601 UTC 秒级时间戳。run card / artifact / 供应商记录 / 技能运行 / 行情回执都按它写库并互相比对，此前 14 个模块各写一份，任一处改 `timespec` 都会让记录静默错位。**不含** ledger 的时间戳——那里刻意用本地时区 + 微秒以保证同秒可排序
- `src.shared.desktop_shortcut` — 创建桌面快捷方式
- `src.shared.desktop_prefs` — 桌面壳偏好（`data/desktop.json`：最小化到托盘、行情窗贴边等）
- `src.shared.webview_ui` — WinForms/`BeginInvoke` UI 线程投递；`hide_peek_from_taskbar`；`desktop_shell` 主窗导航与 Peek 延后创建共用
- `src.shared.peek_dock` — 行情小窗磁吸控制器；几何常量/吸附矩形在 `peek_dock_geometry`（可单独测）；托盘「行情」首次按需创建第二 WebView2（启动期不预建），失败才回退浏览器
- `src.shared.single_instance` — Windows 桌面单实例（二次启动前置已有窗口）
- `src.shared.webview_cache` — 启动时清理 WebView2 HTTP/代码/GPU 缓存（保留登录态）；根目录 `GrShaderCache` 等一并清
- `src.shared.evidence_compact` — 逐票证据落库前瘦身(`compact_job_result` / `compact_source_evidence`)。**同一个根因在三处各犯过一次**:`ops.db.job_runs.result_json` 单条 257 MB、库涨到 5.67 GB;`palace.db.candidate_reviews.evidence_json` 227 行占全库 99%;`sync` 作业当年单独修过但补丁只打在自己身上。逐票回执的权威副本在 `market.db.source_route_receipts`,别处只留失败样本 + 计数 + 出处。**幂等**——调用方常传浅拷贝、同一份证据会被反复压,不幂等会把 `receipts_total` 写成上一遍的样本数(50),真实总数当场丢失且看起来是对的。历史存量用 `scripts/compact_evidence_blobs.py` 清
- `src.shared.observability` — opt-in correlation scope、低基数内存 metrics 与结构化日志；默认不输出、不发外部网络
- `src.shared.desktop_shell.apply_webview2_browser_arguments` — 默认 `LOCI_WEBVIEW_DISABLE_GPU=1` 缓解 `STATUS_BREAKPOINT`
- `src.shared.desktop_shell.run_desktop_shell` — 主窗导航等待 `/api/health`；若 uvicorn 线程已退出则立刻失败（不再干等 90s）

## 如何扩展
新增真正横切的工具放这里；一旦带业务语义，改放到对应上下文。
可观测性只允许承载 `trace_id/run_id/job_id/source_id/tool_receipt_id` 等关联字段，
不得把请求参数、股票代码、URL 或密钥写入日志/metrics；外部 exporter 必须由宿主显式配置。


## 给 Agent 的用法
- 路径唯一入口：`from src.shared.paths import data_dir, palace_db, market_db, ops_db`
- 禁止在业务里硬编码 `data/palace.db`
- 打包运行时默认使用 `{exe}/data`；`loci.config.json` 中的相对 `data_dir` 也相对安装目录解析。若配置保留了移动前的绝对路径，且该路径失效或为空、`{exe}/data/market.db` 已有完整数据，会自动使用便携目录；`LOCI_DATA_DIR` / `PALACE_DATA_DIR` 等显式环境变量仍优先。
- 配置文件位置由 `config_path()` 决定，可用 `LOCI_CONFIG_JSON` 覆盖（测试隔离靠它：这份文件存着 `data_dir` 与线路策略，不覆盖就会读到开发机真实配置、也可能被忘了 mock 的 `save_config` 改写）。`save_config` 先写 `.tmp` 再 `os.replace` 原子替换——原地截断覆盖崩在中途会留下半截 JSON，`load_config` 捕获解析错误后静默返回 `{}`，用户看到的是「设置怎么回到默认了」。
- 新增 `LOCI_*` / `PALACE_*` 运行开关时**必须**同步加进 `tests/conftest.py` 的 `_ENV_KEYS`；`tests/shared/test_config_isolation.py` 会扫 `src/**` 比对，漏了就红。
- 桌面缓存：打包默认 `purge_webview_http_cache_on_boot()`；`LOCI_SKIP_WEBVIEW_CACHE_PURGE=1` 可关
- 可观测性：设置 `LOCI_OBSERVABILITY=1` 才启用本地 JSON 日志与内存 metrics；再设置
  `LOCI_OBSERVABILITY_OTEL=1` 才桥接宿主已安装的 OpenTelemetry tracer，仓库不配置 exporter；
  `LOCI_OBSERVABILITY_EXPOSE=1` 才在 HTTP 响应显式返回 `X-Loci-Trace-ID`。

## README 维护
改路径解析优先级或布局约定时必须更新本文。

## 相关测试
`tests/shared/`（含 `test_boot_splash.py`、`test_observability.py`，以及 `test_paths.py`、`test_single_instance.py`、`test_webview_cache.py`、`test_desktop_prefs.py`、`test_peek_dock.py`）
