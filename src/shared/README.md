# 共享内核（shared）

## 职责
跨限界上下文的横切能力：数据根路径、桌面快捷方式。不含业务规则。

## 边界
- 可被所有上下文依赖
- 禁止依赖 ledger / market / review 等业务包（paths 内延迟 import 建库除外）

## 关键入口
- `src.shared.paths` — `data_dir` / 三库路径 / `ensure_data_dir`
- `src.shared.desktop_shortcut` — 创建桌面快捷方式
- `src.shared.desktop_prefs` — 桌面壳偏好（`data/desktop.json`：最小化到托盘、行情窗贴边等）
- `src.shared.webview_ui` — WinForms/`BeginInvoke` UI 线程投递；`hide_peek_from_taskbar`；`desktop_shell` 主窗导航与 Peek 延后创建共用
- `src.shared.peek_dock` — 行情小窗磁吸几何 + `PeekDockController`；托盘「行情」首次按需创建第二 WebView2（启动期不预建），失败才回退浏览器
- `src.shared.single_instance` — Windows 桌面单实例（二次启动前置已有窗口）
- `src.shared.webview_cache` — 启动时清理 WebView2 HTTP/代码缓存（保留登录态）

## 如何扩展
新增真正横切的工具放这里；一旦带业务语义，改放到对应上下文。


## 给 Agent 的用法
- 路径唯一入口：`from src.shared.paths import data_dir, palace_db, market_db, ops_db`
- 禁止在业务里硬编码 `data/palace.db`
- 打包运行时默认使用 `{exe}/data`；`loci.config.json` 中的相对 `data_dir` 也相对安装目录解析。若配置保留了移动前的绝对路径，且该路径失效或为空、`{exe}/data/market.db` 已有完整数据，会自动使用便携目录；`LOCI_DATA_DIR` / `PALACE_DATA_DIR` 等显式环境变量仍优先。
- 桌面缓存：打包默认 `purge_webview_http_cache_on_boot()`；`LOCI_SKIP_WEBVIEW_CACHE_PURGE=1` 可关

## README 维护
改路径解析优先级或布局约定时必须更新本文。

## 相关测试
`tests/shared/`（`test_paths.py`、`test_single_instance.py`、`test_webview_cache.py`、`test_desktop_prefs.py`、`test_peek_dock.py`）
