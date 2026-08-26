# 测试

## 职责
与 `src/<context>` 镜像的 pytest 用例；全局隔离与清理。

## 边界
不依赖真实公网；不读写用户真实 `data/`（由 `conftest.py` 注入临时目录）。

## 关键入口
```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=line
```

## 清理约定
- **每个用例**：`conftest.py` 的 autouse fixture 创建独立 `LOCI_DATA_DIR`，结束后删除临时树并还原相关环境变量。
- **会话结束**：清理仓库内误留的 `.coverage` / `htmlcov` / 测试命名残留。
- 用例内若再设 `PALACE_*`，请在 `tearDown` 清理；优先依赖全局 fixture，避免指向真实路径。
- 禁止把测试产物提交进 Git（见根 `.gitignore`：`.pytest_cache/`、`*.db`、`data/`）。

## 如何扩展
新上下文测试放 `tests/<context>/`；外部 IO 必须 mock。
- 单个回归点优先并入同一生产入口的主题测试文件；只有需要独立夹具或独立边界时才新建文件。
- 删除旧用例前先确认生产入口已移除，或已有更强断言覆盖；不要仅因数量多而降低关键契约覆盖。

## 相关文档
- 根 [`AGENTS.md`](../AGENTS.md)
- [`src/AGENTS.md`](../src/AGENTS.md)
