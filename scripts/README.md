# 脚本

## 职责
构建与一次性迁移 / 文档辅助脚本。非运行时依赖。

## 关键入口
- `build-loci.ps1` — 打 Loci.exe
- `upsert_agent_readme_sections.py` — 给模块 README 补 Agent 段落
- `migrate_imports.py` / `rewrite_frontend_imports.py` / `write_module_readmes.py` — 历史迁移辅助

## 如何扩展
临时脚本用完可删；长期脚本在本 README 登记。

## 相关测试
—
