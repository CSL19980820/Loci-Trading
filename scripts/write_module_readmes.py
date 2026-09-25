from pathlib import Path

TEMPLATE = """# {title}

## 职责
{duty}

## 边界
{boundary}

## 关键入口
{entries}

## 如何扩展
{extend}

## 相关测试
{tests}
"""

docs = {
    "src/ledger/README.md": dict(
        title="账本（ledger）",
        duty="成交、候选、预案、复盘记录与持仓投影的单一事实源。对外保留 PalaceStore 类名。",
        boundary="写 palace.db。行情/复盘可读本上下文，但不可反向写入账本事实。",
        entries="`PalaceStore`（infrastructure/store.py）；HTTP 账本路由在 src.app.main；CLI：`python -m cli.ledger`",
        extend="新账本实体：改 infrastructure/store DDL + 写入方法，并补 tests/ledger。",
        tests="`tests/ledger/`",
    ),
    "src/market/README.md": dict(
        title="行情（market）",
        duty="标的、日 K、同步编排、数据线路适配器、股票池。",
        boundary="只写 market.db；禁止写 palace.db。",
        entries="`MarketStore` / `sync_quotes`；HTTP：`/api/market/*` `/api/universe/*`（现由 app.legacy.quant_router 挂载）；CLI：`python -m cli.market`",
        extend="新行情源：在 infrastructure/adapters 实现并注册到 lane。",
        tests="`tests/market/`",
    ),
    "src/review/README.md": dict(
        title="复盘（review）",
        duty="资金曲线、持仓归因、候选 T+N、预案兑现等确定性计算。",
        boundary="只读 ledger + market；可写 market 侧缓存表。AI 不得替代本模块出数。",
        entries="`build_equity_curve` / `evaluate_candidates`；HTTP：`/api/review/*` `/api/winrate/*` `/api/insights/*`",
        extend="新指标放 application/，经 API 暴露；补 tests/review。",
        tests="`tests/review/`",
    ),
    "src/strategy/README.md": dict(
        title="策略（strategy）",
        duty="战法协议、内置/自定义选股、审计与 AI 转换。",
        boundary="依赖 market 面板与 formula；不写账本。",
        entries="`StrategyEngine`（domain/base）；`screen`；HTTP：`/api/strategies/*` `/api/screen/*`",
        extend="新战法：实现 Protocol，放 application/，在包 __init__ 侧效 import 注册；声明 entry_timing。",
        tests="`tests/strategy/`",
    ),
    "src/backtest/README.md": dict(
        title="回测（backtest）",
        duty="把策略信号变成可比较绩效（事件驱动、尊重入场时点）。",
        boundary="读 market + strategy；不写 palace。",
        entries="`run_backtest` / `backtest_strategy`；HTTP：`/api/backtest`",
        extend="改成交假设须同步策略 entry_timing 语义与测试。",
        tests="`tests/backtest/`",
    ),
    "src/ops/README.md": dict(
        title="运维（ops）",
        duty="定时任务、技能包、通知、调度器、运维配置。",
        boundary="写 ops.db；技能文件在 data/skills。",
        entries="`OpsStore` / `run_job` / `discover_skills`；HTTP：`/api/jobs/*` `/api/skills/*` `/api/ops/*`；CLI：`python -m cli.ops`",
        extend="新 Job kind：在 application/jobs EXECUTORS 注册。",
        tests="`tests/ops/`",
    ),
    "src/ai/README.md": dict(
        title="AI（ai）",
        duty="通用 LLM 供应商、对话、Agent / toolbus。不发明数字。",
        boundary="密钥经 ops 存储加密；计算结论以 review/strategy 为准。",
        entries="`chat` / `run_agent` / `build_toolbus`；HTTP：`/api/providers/*` `/api/ai/*`",
        extend="新工具挂 toolbus；新协议扩展 infrastructure/client。",
        tests="`tests/ai/`",
    ),
    "src/intel/README.md": dict(
        title="情报（intel）",
        duty="MCP/外部情报接入与限流；补本地行情仓算不出的数据。",
        boundary="配置 mcp.json；大批量量价仍走 market。",
        entries="`McpClient` / registry / builtin_market_mcp；HTTP：`/api/mcp/*`",
        extend="新 MCP server：写入 mcp.json 或 registry API。",
        tests="`tests/intel/`",
    ),
    "src/formula/README.md": dict(
        title="公式（formula）",
        duty="通达信向量化函数、筹码、板块涨跌停。",
        boundary="纯计算，无 IO。",
        entries="`MA`/`REF`/…",
        extend="新函数保持面板/Series 同构；补 tests/formula。",
        tests="`tests/formula/`",
    ),
    "cli/README.md": dict(
        title="CLI",
        duty="薄命令行入口，转发到各限界上下文。",
        boundary="无业务逻辑。",
        entries="`python -m cli.ledger|market|ops|review|serve`",
        extend="新命令：加 cli/<name>.py，内部调 src.<context>。",
        tests="手工 / 对应上下文单测",
    ),
    "tests/README.md": dict(
        title="测试",
        duty="与 src 限界上下文镜像的 pytest 用例。",
        boundary="不依赖真实公网（适配器用 mock）。",
        entries="`pytest tests/ -q`",
        extend="新上下文测试放 tests/<context>/。",
        tests="本目录",
    ),
    "docs/README.md": dict(
        title="文档",
        duty="产品说明、ADR、架构约定（Diátaxis）。",
        boundary="实现细节以代码与模块 README 为准。",
        entries="architecture/ · adr/ · master-plan · quant-toolkit",
        extend="重大决策追加 ADR；结构变更改 architecture。",
        tests="—",
    ),
    "scripts/README.md": dict(
        title="脚本",
        duty="构建与一次性迁移脚本。",
        boundary="非运行时依赖。",
        entries="`build-loci.ps1`",
        extend="临时脚本用完可删。",
        tests="—",
    ),
}

root = Path(r"E:\my_space\stock-analyzer")
for rel, kw in docs.items():
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(**kw), encoding="utf-8")
    print("wrote", rel)

api_notes = {
    "src/ledger/api/README.md": "账本 HTTP 目前主要在 `src.app.main`（与鉴权耦合）。后续下沉到本目录。\n",
    "src/market/api/README.md": "归属 URL：`/api/market/*` `/api/universe/*`。当前由 `src.app.legacy.quant_router` 挂载。\n",
    "src/review/api/README.md": "归属：`/api/review/*` `/api/winrate/*` `/api/insights/*`。当前由 quant_router 挂载。\n",
    "src/strategy/api/README.md": "归属：`/api/strategies/*` `/api/screen/*` `/api/backtest`。当前由 quant_router 挂载。\n",
    "src/ops/api/README.md": "归属：`/api/jobs/*` `/api/skills/*` `/api/ops/*`。当前由 quant_router 挂载。\n",
    "src/ai/api/README.md": "归属：`/api/providers/*` `/api/ai/*`。当前由 quant_router 挂载。\n",
    "src/intel/api/README.md": "归属：`/api/mcp/*`。当前由 quant_router 挂载。\n",
    "src/backtest/api/README.md": "回测 HTTP 挂在 `/api/backtest`；本目录预留下沉。\n",
    "src/formula/api/README.md": "公式层无独立 HTTP。\n",
}
for rel, text in api_notes.items():
    path = root / rel
    path.write_text(text, encoding="utf-8")
    print("wrote", rel)
