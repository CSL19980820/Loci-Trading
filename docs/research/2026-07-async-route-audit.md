# FastAPI sync/async 路由审计（2026-07 P0 速通）

> 依据：`src/AGENTS.md` — SQLite / 同步 pandas 路由优先 `def`；真 await 才 `async def`。  
> 范围：`src/*/api/*.py`、`src/app/main.py`、`src/app/legacy/quant_router.py`。

## 结论

现网业务路由几乎全部已是同步 `def`，与 AGENTS 纪律一致。本波**无需批量改签名**；仅记录合理 `async` 例外与后续注意点。

## 扫描摘要

| 区域 | 形态 | 判定 |
|---|---|---|
| `src/market/api/router.py` | 同步 `def` | 合规（SQLite） |
| `src/review/api/router.py` | 同步 `def` | 合规 |
| `src/ledger/api/*` | 同步 `def` | 合规 |
| `src/strategy/api/*` | 同步 `def` | 合规 |
| `src/ops/api/jobs.py` | 同步 `def` | 合规；重活走 Job 执行器 |
| `src/ops/api/settings.py` | 同步 `def` | 合规 |
| `src/ai/api/router.py` | 同步 `def`（若有 await 需个案） | 保持；流式接口另议 |
| `src/intel/api/router.py` | 同步 `def` | 合规 |
| `src/app/legacy/quant_router.py` | 挂载组装，无业务公式堆叠 | 合规；禁止继续堆业务 |
| `src/app/main.py` | `async` lifespan / 中间件 / 异常处理 | **合理**：ASGI 边界 |
| `src/ops/api/skills.py` → `install_skill_api` | `async def` + `await file.read` | **合理**：真 I/O await |

## 已修项

本波无强制签名变更（未发现「`async def` 内直接同步 sqlite/pandas 堵事件循环」的新增违规）。

## 记入清单（本波不搬业务）

1. 若未来在 `async def` 路由内调用 `MarketStore` / `PalaceStore`，必须 `run_in_threadpool` 或改回 `def`。
2. 全市场 `load_panel` / 回测 / 选股继续走 `ops` Job，不塞进请求线程。
3. 技能安装保持 `async`（上传流）；其余 skills CRUD 已是 `def`。

## 给 Agent

- 新路由默认 `def`，除非文档级 await。
- 不要为了「看起来现代」把 SQLite 路由改成 `async def`。
