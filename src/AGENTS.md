# 后端手册 · Loci / stock-analyzer（DDD）

> **导览与经验笔记，不是法规。** 写的是这个仓库通常怎么分层、哪些决定当初为什么这么做、
> 哪里踩过坑。具体取舍按当轮任务判断；**用户的当轮指令优先于本文件**。
>
> 上级导览见 [`AGENTS.md`](../AGENTS.md)。编辑 `src/**`、`cli/**`、`tests/**` 时读这份。
> 架构地图见 [`docs/architecture/bounded-contexts.md`](../docs/architecture/bounded-contexts.md)。

## 1. 形态

**按限界上下文分包，不按技术分层横切整个仓库。**

```
src/<context>/
  README.md
  domain/           # 实体协议、值对象、领域错误
  application/      # 用例编排（选股、同步、复盘计算…）
  infrastructure/   # SQLite、行情适配器、加密、调度持久化
  api/              # FastAPI 路由 + 请求/响应模型
src/shared/         # 横切工具（paths…），不放业务规则
src/app/            # 组合根：鉴权、挂载、SPA
```

分层方向 `api → application → domain`，infrastructure 实现细节被上面依赖。

这套分层在实践里主要换来三件事，改动时值得先想清楚会不会破坏它们：

1. **domain 干净** —— 只有标准库 + typing + 纯计算（pandas 仅当该域本身就是面板计算，如 formula）。
   没有 FastAPI、没有 sqlite3、没有 httpx，所以业务规则可以脱离框架测试。
2. **application 编排用例** —— 依赖本域 domain 与其他域的**包公开 API**，不深掏兄弟上下文的
   `infrastructure.*`（例如 `from src.ledger import PalaceStore` 可以，
   `from src.ledger.infrastructure.store import _loads` 不行——后者把重构自由度和私有边界一起卖掉了）。
3. **api 薄** —— 解析入参 → 调 application → 映射错误为 HTTP。业务公式放这里会让它无法被
   用例和测试复用。

公开符号放在 `<context>/__init__.py`，外部从包根导入。

## 2. Python 风格

| 项 | 约定 |
|---|---|
| 版本 | Python 3.11+（`X \| Y`、`list[str]`） |
| 类型 | 函数带返回类型注解；公开 API 参数标注 |
| 命名 | 类 PascalCase；函数/变量 snake_case；常量 UPPER_SNAKE；私有 `_leading` |
| 导入 | 不用 `import *` |
| 行宽 | 尽量 ≤ 100 |

Pydantic 用 v2：`model_config = ConfigDict(...)`，不用 `model.dict()` / `json_encoders`。

领域错误放 `domain`（或现有错误类旁），在 `api` 映射成 `HTTPException`；
宽 `except Exception: pass` 会制造「假成功」，排查时很贵。

## 3. FastAPI（本仓多为同步 SQLite）

本仓行情 / 账本大量是**同步阻塞 IO**，所以和纯 async 教程的规则略有不同：

| 场景 | 做法 |
|---|---|
| 路由内主要是 SQLite / 同步 pandas | 用 `def`（跑在 threadpool），别在 `async def` 里堵事件循环 |
| 真有 await（httpx AsyncClient 等） | `async def` + `await` |
| 已在 `async def` 且必须调同步重活 | `await run_in_threadpool(fn, ...)` |
| CPU 重（全市场大回测） | 走 ops Job，别卡死请求线程 |

写操作走已有的 `write_dependency`（会话 / Bearer）。请求模型倾向 `extra="forbid"`。
URL 与 JSON 字段名一旦有消费方就当作契约，改要前后端一起改。

## 4. 是否入库（新增写入前先问这两个问题）

> **丢了可不可以重建？丢了会不会否认账？**

| 数据类型 | 入库 | 放哪 | 说明 |
|---|---|---|---|
| 成交 / 候选 / 预案 / 复盘记录 / 持仓事实 | 是 | `palace.db`（ledger） | 不可变审计 |
| 日 K / 标的列表 / 复权因子 | 是（可重建） | `market.db` | 缓存，丢了可同步回来 |
| Job 定义、运行历史、LLM 供应商密文索引 | 是 | `ops.db` | 运维状态 |
| 技能包正文 / MCP 配置 | 文件为主 | `data/skills/`、`data/mcp.json` | 不塞进 SQLite 大字段 |
| 复盘曲线、候选 T+N、临时面板 | 默认不入库 | 可放 `market.db` 缓存表 | 缓存要能整表删除重建 |
| AI 对话全文 | 慎入 | 独立 / 可删策略 | 不当账本 |
| UI 筛选条件、Tab、弹窗开关 | 否 | 前端本地 / 路由 query | |
| 适配器探测结果、粘性路由 | 否 | 内存或短缓存 | 不是业务事实 |
| 能从已有事实推导的指标 | 否 | application 即时算 | 存两份就是双真相 |

几个具体结论：把「展示用聚合」写成第二套权威表却不声明可重建，会让后来的人不知道该信谁；
在 `palace.db` 存可从外部重新拉的全市场 K 线，会把账本变成缓存；
前端 localStorage 不能充当成交账本。

**新增写入前清单**：属于哪个库？主键是什么？能否幂等重放？删库 / 清缓存的影响？

## 5. 表设计（SQLite）

三库物理隔离，DDL 写在对应上下文的 `infrastructure/*store*.py`（或迁移逻辑旁）
——写在路由里会躲过审查。

| 库 | 表语义 | 演进态度 |
|---|---|---|
| `palace.db` | 账本事实、事件、人工记录 | 保守；加列要兼容；倾向追加表而不是改语义 |
| `market.db` | 行情与可重建缓存 | 可迁移、可清空重拉 |
| `ops.db` | 任务 / 供应商 / 运维配置 | 可清；不放成交 |

命名与类型：表名 snake_case（`position_events`、`quotes_daily`）；主键优先 `TEXT` 业务 id 或
文档化的复合主键（`(code, trade_date)`）；日用 ISO `YYYY-MM-DD` 文本、时刻用 ISO 字符串；
金额数量用数值类型，格式化留给前端；JSON 扩展用 `*_json TEXT` 并读写经 `_dumps` / `_loads`；
布尔 `INTEGER` 0/1；**SQLite 不支持跨 db 文件外键**，跨库关联在应用层做。

索引按实际过滤列建（`(code, occurred_on)`、`(entity_type, entity_id)` 这类），
`CREATE INDEX IF NOT EXISTS idx_<table>_<cols>`；不盲目给每列建。

### 演进（没有 Alembic）

- `CREATE TABLE IF NOT EXISTS` + 显式「补列 / 补表」函数（参考 ledger store 的迁移段落）
- `ALTER TABLE ... ADD COLUMN` 要可重复执行（先查 `pragma`）
- 同名列改口径会让存量数据静默变味——应开新列或新表，并写进 README / ADR
- `palace` 里删数据视为审计事件，别用 `DELETE` 假装没发生（除非用户明确要清演示数据）

### 行情表额外注意

存**原始价 + 复权因子**，不存「固化复权价」当唯一真相——除权之后会静默错。
同步范围要含账本出现过的代码（含被否决的候选），否则复盘缺数据。

### Schema 变更自检

- 表落在正确的 db 文件；主键 / 索引与查询匹配
- 兼容旧库启动（IF NOT EXISTS / 补丁）
- 模块 `README.md` 写清新表职责与是否可重建
- 有测试覆盖读写路径（临时 db）

## 6. 本仓业务边界

| 域 | 可写库 | 边界 |
|---|---|---|
| ledger | palace.db | 不被 market 写入 |
| market | market.db | 可重建；不当账本 |
| ops | ops.db | 技能在 `data/skills` |
| review | 只读（+可选缓存） | 复盘数字不由 AI 冒充 |
| strategy | — | 遵守 `entry_timing`；不看未来数据 |
| ai | — | 不产出权威行情 / 盈亏 |

两个容易犯的具体错：用当日 high/low 做「当日 open 成交」会让回测收益虚高（要守策略的
`entry_timing`）；测试读写真实 `data/` 会污染用户账本（用 `tests/conftest.py` 的隔离）。

## 7. 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=line
.\.venv\Scripts\python.exe -m pytest tests/market -q
```

目录镜像 `tests/<context>/`；外部 HTTP 必须 mock。

**注意 mock 的朴素写法可能无效**：不少通道 / 适配器按契约吞异常，在 `urlopen` 里抛错的守卫
会被它自己接住，用例照样绿。可靠做法是「记账 + teardown 断言」，并注入一次真泄漏验证守卫
确实会红（实测抓到过一个真打 `open.feishu.cn` 的用例）。

新增测试值得做一次变异验证：把被测代码改坏，确认测试变红，再恢复。这条抓到过两处假绿——
一处整个函数体缩进错位到 `return` 之后（0 断言在跑），一处三个断言文案互为子串
（漏渲染一个被另一个掩盖）。

## 8. 模块 README

`src/<context>/README.md` 建议包含：职责 / 边界 / 关键入口 / 如何扩展 / 给 Agent 的用法 /
相关测试。公开行为变了就顺手更新——不然下一个人（或 agent）会按过期的描述动手。

## 9. 改完自检

- 分层与导入合法；`lint-imports` 通过
- 相关 pytest 通过；没有真实 data 污染
- README / api README 同步
- 没有前视、没有 AI 造数、没有跨库乱写
- 新增 Python 文件 `python -m compileall -q` 通过
