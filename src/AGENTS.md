# 后端 Agent 手册 · 代码规范（DDD）

> 上级：[`AGENTS.md`](../AGENTS.md)。编辑 `src/**`、`cli/**`、`tests/**` 时以本文件为准。  
> 借鉴（改编到本仓）：  
> - [miguelgrubin/fastapi-boilerplate AGENTS.md](https://github.com/miguelgrubin/fastapi-boilerplate/blob/master/AGENTS.md)（六边形 + DDD）  
> - [zhanymkanov/fastapi-best-practices AGENTS.md](https://github.com/zhanymkanov/fastapi-best-practices/blob/master/AGENTS.md)（Do/Don't + 反模式表）  
> - DDD/Hexagonal agent 规则实践（领域无外依、用例编排、适配器实现端口）

## 1. 形态与目录

**按限界上下文分包，不按技术分层横切整个仓库。**

```
src/<context>/
  README.md
  domain/           # 实体协议、值对象、领域错误；无 FastAPI / 无 sqlite3 / 无 httpx
  application/      # 用例编排（选股、同步、复盘计算…）
  infrastructure/   # SQLite、行情适配器、加密、调度持久化
  api/              # FastAPI 路由 + 请求/响应模型；只调 application
src/shared/         # 横切（paths…）；禁止塞业务规则
src/app/            # 组合根：鉴权、挂载、SPA
```

地图：[`docs/architecture/bounded-contexts.md`](../docs/architecture/bounded-contexts.md)。

### 架构铁律（抄自六边形/DDD，落到本仓）

1. **Domain 零外部框架依赖** — 仅标准库 + typing + 必要的纯计算（pandas 仅当该域本身就是面板计算，如 formula）。
2. **Application 依赖领域接口/公开类型** — 不直接 `import` 兄弟上下文的 `infrastructure.*`。
3. **Infrastructure 实现细节** — Store / Adapter / Client；可依赖第三方。
4. **API（入站适配器）薄** — 校验入参、调 application、映射错误为 HTTP；禁止在路由里写业务公式。
5. **组合根装配** — `src/app/main.py` 挂路由与依赖；业务不回流到组合根。

### 跨上下文导入

```python
# DO
from src.ledger import PalaceStore
from src.market import MarketStore, sync_quotes
from src.strategy import screen

# DON'T — 深耦合、难重构
from src.market.infrastructure.store import MarketStore  # 仅本域内部或测试可用
from src.ledger.infrastructure.store import _loads       # 禁止掏私有
```

公开符号放在 `<context>/__init__.py`；外部只从包根导入。

## 2. Python 代码风格

| 项 | 约定 |
|---|---|
| 版本 | Python 3.11+（`X \| Y`、`list[str]`） |
| 类型 | **函数必须有返回类型注解**；公开 API 参数全标注 |
| 命名 | 类 PascalCase；函数/变量 snake_case；常量 UPPER_SNAKE；私有 `_leading` |
| 字符串 | 与文件现有风格一致（本仓多为双引号 docstring + 普通字符串） |
| 导入 | `from __future__ import annotations` 可保留；禁止 `import *` |
| 行宽 | 尽量 ≤ 100；不为此做无意义换行秀 |

### Do / Don't（类型与模型）

```python
# DO — Pydantic v2
from pydantic import BaseModel, ConfigDict, Field

class TradeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    price: float = Field(gt=0)

# DON'T — 过时 API
# model.dict() / json_encoders=...
```

领域错误放 `domain`（或现有错误类旁）；在 `api` 映射为 `HTTPException`，**不要**在路由里 `except Exception: pass`。

## 3. FastAPI 规范（适配本仓：多为同步 SQLite）

本仓行情/账本大量 **同步阻塞 IO（SQLite）**，规则与纯 async 教程略有不同：

| 场景 | 做法 |
|---|---|
| 路由内主要是 SQLite / 同步 pandas | 优先 **`def`**（跑在 threadpool），避免在 `async def` 里直接堵事件循环 |
| 真正的 await（httpx AsyncClient 等） | `async def` + `await` |
| 已在 `async def` 必须调同步重活 | `await run_in_threadpool(fn, ...)` |
| CPU 重（全市场大回测） | 走 ops Job / 后台任务，不要卡死请求线程 |

```python
# DON'T — async 路由里同步睡死/堵库
@router.get("/bad")
async def bad():
    time.sleep(1)
    store.query(...)  # 同步 sqlite
    return {}

# DO — 同步路由交给 threadpool
@router.get("/ok")
def ok():
    return store.query(...)
```

### 依赖注入

- 优先 `Annotated[T, Depends(...)]`（本仓若历史写法是默认参 `Depends`，改存量时逐步统一，**新代码用 Annotated**）。
- 写操作统一走已有 `write_dependency`（会话 / Bearer），禁止旁路写接口。

### 请求模型

- `extra="forbid"`（账本写入已如此）；量化侧新模型保持严格。
- 路径/查询参数命名稳定；**禁止无故改 URL 或 JSON 字段名**。

## 4. DDD 落地清单（按层）

### domain/

- Protocol / `@dataclass` 值对象 / 领域错误
- **禁止**：`fastapi`、`sqlite3`、`httpx`、读环境变量做 IO
- 策略示例：`strategy/domain/base.py` 的 `StrategyEngine`

### application/

- 一个用例一个清晰入口函数或小类；编排多个 infrastructure 调用
- 可依赖 **本域** domain + 其他域**公开 API**
- 示例：`review/application/equity.py`、`ops/application/jobs.py`

### infrastructure/

- `*Store`、adapters、client；DDL 与 SQL 只出现在这里
- 适配器模式：行情源走 `market/infrastructure/adapters` 注册表，**禁止**在 sync 里堆厂商 if-else

### api/

- 只做：解析 → 调 application → 返回 DTO
- 过渡期路由仍可能在 `src/app/legacy/quant_router.py`：**只允许搬迁或最小修补，禁止继续堆业务**；归属写在本域 `api/README.md`

## 5. 本仓业务红线

| 域 | 可写库 | 红线 |
|---|---|---|
| ledger | palace.db | 不可被 market 写入 |
| market | market.db | 可重建；禁止当账本 |
| ops | ops.db | 技能在 `data/skills` |
| review | 只读(+可选缓存) | 禁止 AI 冒充复盘数字 |
| strategy | — | 必须 `entry_timing`；禁止前视 |
| ai | — | 不产出权威行情/盈亏 |

## 5.1 是否入库（持久化决策）

先问：**丢了可不可以重建？丢了会不会否认账？**

| 数据类型 | 是否入库 | 放哪 | 说明 |
|---|---|---|---|
| 成交 / 候选 / 预案 / 复盘记录 / 持仓事实 | **必须** | `palace.db`（ledger） | 不可变审计；禁止用行情库「顶替」 |
| 日 K / 标的列表 / 复权因子 | **必须**（可重建） | `market.db` | 缓存；丢了可同步回来 |
| Job 定义、运行历史、LLM 供应商密文索引 | **必须** | `ops.db` | 运维状态 |
| 技能包正文 / MCP 配置 | **文件**为主 | `data/skills/`、`data/mcp.json` | 不进 SQLite 大字段塞全文 |
| 复盘曲线、候选 T+N、临时面板 | **默认不落库**；重算贵再缓存 | 可放 `market.db` 缓存表 | 缓存必须可整表删除重建 |
| AI 对话全文 | 慎入；可清理 | 若存则独立/可删策略 | 不得当账本 |
| UI 筛选条件、Tab、弹窗开关 | **不入库** | 前端本地 / 路由 query | |
| 适配器探测结果、粘性路由 | 内存或短缓存 | 勿当业务事实 | |
| 能从已有事实 **推导** 的指标 | **不入库** | application 即时算 | 避免双真相 |

**禁止**：

- 把「展示用聚合」写成第二套权威表却不声明可重建。
- 在 `palace.db` 存可从外部行情重新拉的全市场 K 线。
- 前端 localStorage 充当成交账本。

**新增写入前清单**：属于哪个库？主键是什么？能否幂等重放？删库/清缓存的影响？

## 5.2 表设计（SQLite）

本仓三库物理隔离；DDL 只写在对应上下文 `infrastructure/*store*.py`（或迁移逻辑旁），**禁止**在路由里 `CREATE TABLE`。

### 归属

| 库 | 表语义 | 演进态度 |
|---|---|---|
| `palace.db` | 账本事实、事件、人工记录 | **保守**；加列要兼容；尽量追加表而非改语义 |
| `market.db` | 行情与可重建缓存 | 可迁移、可清空重拉 |
| `ops.db` | 任务/供应商/运维配置 | 可清；勿放成交 |

### 命名与类型

| 规则 | 约定 | 例 |
|---|---|---|
| 表名 | snake_case，复数或领域习惯名词 | `position_events`、`quotes_daily` |
| 主键 | 优先 `TEXT` 业务 id / 自然键；或文档化的复合主键 | `id TEXT PRIMARY KEY`；`(code, trade_date)` |
| 时间 | 日用 `TEXT` ISO `YYYY-MM-DD`；时刻用 ISO 字符串 | `occurred_on`、`created_at` |
| 金额数量 | 用数值类型；展示格式化留给前端 | `REAL` / `INTEGER` |
| JSON 扩展 | `*_json TEXT`，读写经 `_dumps`/`_loads` | `metadata_json`、`evidence` |
| 布尔 | `INTEGER` 0/1 或与现表一致 | |
| 外键 | 账本内可 `REFERENCES`；**禁止跨 db 文件外键** | |

### 索引

- 高频过滤列建索引：`(code, occurred_on)`、`(entity_type, entity_id)` 等。
- 与现有查询一致；不盲目给每列建索引。
- 新索引：`CREATE INDEX IF NOT EXISTS idx_<table>_<cols>`。

### 演进（无 Alembic 的现状）

- 用 `CREATE TABLE IF NOT EXISTS` + 显式「补列/补表」函数（见 ledger store 的迁移段落）。
- **加列**：`ALTER TABLE ... ADD COLUMN` 必须可重复执行（先查 `pragma`/`IF NOT EXISTS` 逻辑）。
- **禁止**静默改列含义（同名列改口径）；应新列或新表并写 README/ADR。
- `palace` 删除数据视为审计事件；不要 `DELETE` 假装没发生，除非用户明确要「清除演示数据」类接口。

### 行情表额外约束（market）

- 存 **原始价 + 复权因子**，不存「固化复权价」当唯一真相（除权后会静默错）。
- 同步范围含账本出现过的代码（含否决候选），避免复盘缺数据。

### Schema 变更 DoD

- [ ] 表落在正确的 db 文件
- [ ] 主键/索引与查询匹配
- [ ] 兼容旧库启动（IF NOT EXISTS / 补丁）
- [ ] 模块 `README.md` 写清新表职责与是否可重建
- [ ] 有测试覆盖读写路径（可用临时 db）

## 6. 反模式表（Agent 自查）

| 反模式 | 为何错 | 改法 |
|---|---|---|
| 在 `domain/` import FastAPI/SQLite | 污染领域 | 下沉 infrastructure / api |
| `from src.x.infrastructure.y import` 跨域乱用 | 紧耦合 | 经 `src.x` 导出 |
| async 路由里同步阻塞 | 堵事件循环 | 改 `def` 或 `run_in_threadpool` |
| 路由里写选股/复盘公式 | 层次倒挂 | 挪到 application |
| 宽 `except Exception` 吞掉 | 难排查、假成功 | 捕获具体错误并转 HTTP |
| 继续膨胀 `quant_router.py` / `PalaceStore` | 违反 600 行 | 拆文件或下沉 |
| 前视用当日 high/low 做「当日 open 成交」 | 虚高收益 | 遵守策略 `entry_timing` |
| 测试读写真实 `data/` | 污染用户账本 | 依赖 `tests/conftest.py` |
| 假造 K 线凑测试 | 破坏信任 | mock 适配器或夹具行情 |
| 推导指标落成「权威表」且不可重建 | 双真相 | 即时算或标明缓存可删 |
| 跨 `palace.db`/`market.db` 外键 | SQLite 不支持跨文件 FK | 应用层关联 |
| 在 API 里临时 `CREATE TABLE` | 躲过审查 | 只在 store 初始化/迁移 |

## 7. 测试规范

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=line
.\.venv\Scripts\python.exe -m pytest tests/market -q
```

- 目录镜像：`tests/<context>/`
- 外部 HTTP **必须 mock**
- 全局隔离与清理：`tests/conftest.py`
- 命名：`test_*.py` / `test_should_*` 或 `test_<behavior>`

## 8. 模块 README（强制）

模板段落不可缺：`职责 / 边界 / 关键入口 / 如何扩展 / 给 Agent 的用法 / README 维护 / 相关测试`。  
**公开行为变更 → 同批更新 README**，否则 DoD 失败。

## 9. 改完自检

- [ ] 分层与导入合法；`lint-imports` 绿；无超 600 行新增膨胀
- [ ] 相关 pytest 绿；无真实 data 污染
- [ ] README / api README 已同步
- [ ] 无前视、无 AI 造数、无跨库乱写
