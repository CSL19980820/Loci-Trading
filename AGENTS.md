# Loci / stock-analyzer · 项目导览

本文提供项目地图、数据契约与环境事实；按任务读取相关分册，设计与架构可随实际需求调整。

## 项目地图

Loci v2「群龙」是包含行情、账本、策略工坊、研究、智能体和运维的多租户量化平台。
后端主要是 Python / FastAPI 的模块化单体，前端是 Vue / TypeScript。
具体业务和菜单以当前源码为准；历史 ADR 描述的是当时的决策，不代表永久限制。

- `src/`：后端上下文、共享基础设施和应用装配。
- `frontend/src/features/`：前端业务；`frontend/src/shared/`：共享组件、API、状态和工具。
- `tests/`、`frontend/src/**/*.test.ts`、`frontend/e2e/`：不同层次的验证材料。
- 相关时再看 `src/AGENTS.md`、`frontend/AGENTS.md`、`frontend/docs/ui-spec.md`。

## 数据与环境事实

当前多租户实现通过 `src/shared/tenancy.py` 的 ContextVar 和 `src/shared/paths.py` 解析数据根。
每租户拥有 `palace.db`、`ops.db`、`skills/`、`research_runs/`；行情库 `market.db` / `market_hot.db` 和身份、社区库全局共享。
主租户 `__primary__` 使用原 `data/`。导入时缓存租户路径可能串租户，存储改动需要考虑这一点。
行情、交易和回测的可核实事实与模型分析、假设应当区分。

线上环境是 `ssh my-debian` 的 `/srv/qianlong-loci`。本地源码可用于开发和隔离测试，本地结果不等于生产验证。
用户已停用 `E:\entertainment_software\Loci` 便携版；它不是本项目此次开发、取数或部署的目标。
部署入口为 `pwsh .\deploy\deploy.ps1`，详见 `deploy/README.md`。是否部署、提交或推送依当前任务授权。

真实数据库、密钥及其他人的未提交修改需要保留；涉及数据变更时选择可回退的方法。
`.local/` 和 `deploy/.release/` 中的历史快照不是当前源码或日常指导文件。

## 常用验证入口（按改动选择）

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=line
.\.venv\Scripts\python.exe -m ruff check --select F src cli tests
.\.venv\Scripts\python.exe tools\import_smoke.py
.\.venv\Scripts\lint-imports.exe
cd frontend
bun install
bun run typecheck
bun run test
bun run build
bun run test:e2e
```

这些是工具入口，不是每次任务必须串行执行的固定流程。可按风险选择局部测试、静态检查、性能分析或浏览器验证；说明实际验证范围及未验证部分即可。
