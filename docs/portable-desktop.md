# Loci 桌面便携版

## 打包形态（onedir）

产物是文件夹，不是单文件超级 exe：

```
Loci/
  Loci.exe          # 入口（启动快）
  _internal/        # 依赖、松散 src/、前端静态资源
    src/            # 业务代码（可 -SrcOnly 覆盖）
    frontend/dist/  # 前端产物（可 -Mode frontend 覆盖）
  data/             # 运行时数据（与 exe 同级，首次自动建）
```

- **为何不用 onefile**：单文件每次启动都要解压到临时目录，体积大时会明显拖慢（尤其含 pandas/numpy）。
- **体积**：打包已排除未使用的 `scipy` / `numba` / `llvmlite` / `vectorbt` / `plotly` 等（venv 研究残留，业务未 import）；主体积仍来自 pandas/numpy/akshare（行情必需）。
- **akshare 数据文件**：`loci.spec` 用 `collect_data_files("akshare")` 打进 `_internal/akshare/`（含 `file_fold/calendar.json`）。缺此文件时交易所列表会 `FileNotFoundError`。
- **py_mini_racer**：新浪历史日 K 需 `mini_racer.dll` + `icudtl.dat`；`loci.spec` 已 `collect_all("py_mini_racer")`。缺库时会报 `LibNotFoundError` /「解码库不可用」，须 `-Mode full` 重打。
- **增量更新**：无新 pip 依赖时不要每次 `full`。见下方模式表。

默认数据目录：`{exe 所在目录}/data/`。首次可改路径；运维页「数据目录」可再改（需重启）。

完整复制给另一台机器时，把 `data/` 与程序目录一起复制即可，不要把 `loci.config.json` 里的机器绝对路径当成数据位置。启动时相对 `data_dir` 会相对 exe 目录解析；旧配置若仍指向已失效或空的绝对目录，而 exe 旁有完整 `data/market.db`，Loci 会自动改用便携数据目录。

**LLM / MCP Key**：本机明文保存（`ops.db` / `mcp.json`）。无主密钥文件。旧加密残留启动时清除，需在运维页重录。

## 前端缓存

- 每次启动会清理 `data/webview` 下的 HTTP/代码/GPU 缓存（保留 Cookie / LocalStorage），并给 `index.html` 与路由壳加 `Cache-Control: no-store`，避免增量部署后仍打开旧 SPA。需要保留磁盘缓存排障时设 `LOCI_SKIP_WEBVIEW_CACHE_PURGE=1`。
- WebView2 若出现「此页存在问题 / STATUS_BREAKPOINT」：多为渲染进程（常与 GPU）崩溃。打包默认 `LOCI_WEBVIEW_DISABLE_GPU=1`（软渲染）；要开硬件加速设 `LOCI_WEBVIEW_DISABLE_GPU=0`。仍崩时可退出后删 `data/webview/EBWebView` 下缓存子目录再启动。

## 构建与更新

```powershell
# 首次 / 加依赖 / 改 loci.py 或 loci.spec
.\scripts\build-loci.ps1 -Mode full -DeployDir "E:\entertainment_software\Loci"

# 只改前端
.\scripts\build-loci.ps1 -Mode frontend -DeployDir "E:\entertainment_software\Loci"

# 只改 src/**（秒级）
.\scripts\build-loci.ps1 -Mode app -SrcOnly -DeployDir "E:\entertainment_software\Loci"

# 前后端都改，但依赖未变
.\scripts\build-loci.ps1 -Mode app+frontend -DeployDir "E:\entertainment_software\Loci"
```

手工等价（全量）：

```powershell
cd frontend; bun install; bun run build; cd ..
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean loci.spec
```

`loci.spec` 把业务 `src/` 打进 `_internal/src`（不进 PYZ），因此 `app -SrcOnly` 只需覆盖该目录。改入口 `loci.py`、加 pip 包、改 spec 仍必须 `-Mode full`。

桌面端窗口菜单 / 侧栏底部「帮助」可创建桌面快捷方式。

## 分享打包（设置 → 一键打包）

在已有编译产物（`Loci.exe` + `_internal`）上，可从运维页勾选内置算法 / 账本 / 行情 / 运维库 / MCP / 技能 / 本机配置，生成顶层为 `Loci/` 的加密 zip。解压密码固定在服务端（`SHARE_PACK_PASSWORD`），前端不展示；打包时需输入正确密码。开发态会在仓库旁 `.\Loci\` 查找产物。

## 安全边界（桌面默认）

- 默认只监听 `127.0.0.1` + 系统分配空闲端口；局域网其它机器碰不到。
- 桌面托盘**不再**提供「在浏览器中打开」；工作台只在 WebView 窗内。排障仍可用 `--browser`。
- 托盘**左键**打开隐藏的行情小窗（`/peek`，指数横轨 + 持仓今日涨跌）；右键菜单「打开工作台」唤回主窗，「退出」结束进程。悬停文案为等宽短摘要（系统气泡无涨跌色）。
- 行情小窗支持**四边磁吸**：拖到屏幕边松手即贴边对齐（仍是自由浮窗）；鼠标移开且仍贴边 → 缩成约 36–40px 圆形应用图标（可拖改位置，写入 `desktop.json`）；拖出贴边范围 → 保持自由不缩。滑过图标即恢复自由窗。偏好记在 `data/desktop.json`（`peek_edge` / `peek_collapsed` / `peek_y`）。
- 行情小窗显示后**尽量不占任务栏**（延后设置 `ShowInTaskbar=False` + 工具窗样式）。改 `ShowInTaskbar` / `Handle` / resize·move / `load_url` / `load_html` 必须经 UI 线程（`run_on_ui_thread`）；托盘回调、`Timer`、以及 `loci-navigate` 后台线程直接碰 native 会抛 WebView2「only be accessed from the UI thread」，或卡死闪屏「未响应」。后台导航用 `wait=False`（`BeginInvoke`），避免同步 `Invoke` 死锁。**禁止**对 Peek 使用 `transparent=True`。启动时**只建主窗**；Peek 窗体与 `load_url` 都延到首次托盘打开（启动期双 WebView2 会卡死「启动中」）；创建失败才回退系统浏览器。
- 主窗**最小化**：默认隐藏主窗（任务栏无条目），仅留系统托盘；用托盘「打开工作台」唤回。可在 **设置 → 数据目录 → 窗口** 关闭「最小化到托盘」，改为缩回任务栏。点 **×** 仍走退出流程。`--no-tray` 或缺托盘时，最小化仍落在任务栏。偏好写入 `data/desktop.json`（可删重建）。
- `PALACE_ENV=local`（打包默认）不强制登录——威胁面是「本机其它进程/页面」，不是公网。
- 若以后把服务挂到公网或 `0.0.0.0`：必须 `PALACE_ENV=production` + 账号口令 + `PALACE_SESSION_SECRET` + `PALACE_ALLOWED_HOSTS`，并走 HTTPS。
- **Agent Bearer（`PALACE_WRITE_TOKEN`）**：长期静态密钥、无内置过期；生产优先浏览器会话。生产环境若配置则长度须 ≥32（否则拒绝启动）。轮换：生成新高熵随机串 → 更新环境变量 → 设/刷新 `PALACE_WRITE_TOKEN_ISSUED_AT=YYYY-MM-DD` → 重启（旧令牌立即失效）。超约 90 天未轮换时启动告警。本地桌面（`PALACE_ENV=local`）不配也可写；对网临时强制写鉴权可另设 `PALACE_REQUIRE_WRITE_AUTH=1`。
- 后续「行情走远程服务器」属于**出站**请求：在适配器里白名单域名、超时、不把账本密钥塞进查询参数；与本机 API 入站鉴权分开设计。
