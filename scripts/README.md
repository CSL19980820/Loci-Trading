# 脚本

## 职责
构建与一次性迁移 / 文档辅助脚本。非运行时依赖。

## 关键入口
- `build-loci.ps1` — 打 / 增量更新 Loci 便携版
- `upsert_agent_readme_sections.py` — 给模块 README 补 Agent 段落
- `migrate_imports.py` / `rewrite_frontend_imports.py` / `write_module_readmes.py` — 历史迁移辅助
- `legacy_strategy_combination_backtest.py` — 海底捞月、筹码峰突破、三外有三老版本的多条件组合回测
- `qianlong_v1_combination_backtest.py` / `qianlong_v1_backtest_report.py` — 潜龙老版本多条件组合回测
- `qianlong_structure_backtest.py` / `qianlong_structure_report.py` — 潜龙 v1/v2/v3 粗对比（旧）
- `qianlong_structure_research.py` — 潜龙 v1/v2/v3 结构研究（对齐三元报告标准：成本/盈亏比/组合回撤/分层），产出 `output/qianlong-structure-*`
- `qianlong_tail_rank_research.py` — 潜龙尾盘 V1 排分×TopN 对照（≥10 组），产出 `output/qianlong-tail-rank-*`
- `cleanup_stale_candidate_versions.py` — 清理 palace 中已归档战法（qianlong-close / lugw-sanwai* 等）重复精选；默认 dry-run，`--apply` 才删

### build-loci.ps1 模式

| Mode | 场景 | 耗时量级 |
|------|------|----------|
| `full`（默认） | 首次打包、加/改 pip 依赖、改 `loci.py` / `loci.spec` | 全量（前端 + clean PyInstaller + 整包覆盖） |
| `frontend` | 只改前端 | 秒～分钟（bun build + 覆盖 `_internal/frontend/dist`） |
| `app` | 改后端 / 入口产物 | 无 clean 的 PyInstaller + 覆盖 exe/`src`/assets |
| `app -SrcOnly` | 只改了 `src/` 下业务代码 | 秒级（只同步 `_internal/src`） |
| `app+frontend` | 前后端都改、无新依赖 | 前端 + 无 clean PyInstaller + 增量覆盖 |

```powershell
.\scripts\build-loci.ps1 -Mode frontend -DeployDir "E:\entertainment_software\Loci"
.\scripts\build-loci.ps1 -Mode app -SrcOnly -DeployDir "E:\entertainment_software\Loci"
.\scripts\build-loci.ps1 -Mode app+frontend -DeployDir "E:\entertainment_software\Loci"
.\scripts\build-loci.ps1 -Mode full -DeployDir "E:\entertainment_software\Loci"
```

增量模式要求目标已有安装，且 `app` / `SrcOnly` 需要 `_internal/src`（松散业务代码）。旧安装先跑一次 `full`。`-SrcOnly` 仅能与 `-Mode app` 联用，不覆盖 `loci.py` 入口变更。

## 如何扩展
临时脚本用完可删；长期脚本在本 README 登记。

## 相关测试
—
