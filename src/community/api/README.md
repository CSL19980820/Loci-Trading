# 社区 HTTP API

工厂：`build_community_router(*, write_dependency, auth_dependency, community_db=None)`
（内部拆成 `strategies_router` + `social_router` 两张表，避免单文件过 600 行）。
所有路径前缀 `/api/community`。

## 依赖契约

| 参数 | 约定 |
|---|---|
| `write_dependency` | 组合根的写权限依赖（会话 / Bearer）。**所有写接口都挂它**，被拒即 401/403 |
| `auth_dependency` | 返回「当前用户」。**匿名必须返回 `None` 或 `user` 为空的上下文，不要抛 401**——广场 / 榜单 / 动态要能匿名浏览；写接口自己用 `require_actor` 卡 401 |
| `community_db` | 覆盖库路径（测试用）；缺省走 `src.shared.paths.community_db()` |

`auth_dependency` 的返回值形状随意：`Actor` / identity 的 `AuthContext` / 用户对象 / 字典 /
用户 id 字符串，统一由 `deps.py::coerce_actor` 收敛。社区刻意不 import identity。

## 端点

### 广场与发布

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/strategies` | 广场列表。`sort=hot\|new\|score\|stars`、`kind`、`tag`、`keyword`、`page`、`page_size`；登录后每条附 `starred`。每条带最近一期绩效：`latest_score` / `metrics_date`（既有字段）+ 可为 `null` 的 `metrics` 对象 |
| GET | `/strategies/mine` | 我的发布（含 private / unlisted / 已下架） |
| GET | `/strategies/{publish_id}` | 详情 + 当前版本 + 最新绩效 + 观察者视角；`count_view=false` 可不计浏览 |
| GET | `/strategies/{publish_id}/versions` | 版本列表（倒序）。非作者只看得到当前版正文 |
| POST | `/strategies` | 发布（201）。先跑上架清单，不过不落库 |
| POST | `/strategies/preflight` | 发布前预检，只回清单结果，不写库 |
| POST | `/strategies/{publish_id}/versions` | 发新版（201）。旧版冻结，不可改不可删 |
| PATCH | `/strategies/{publish_id}` | 改标题 / 摘要 / 标签（仍过引流检查），不碰版本内容 |
| POST | `/strategies/{publish_id}/delist` | 下架（可逆，数据不删） |
| POST | `/strategies/{publish_id}/relist` | 重新上架 |
| POST | `/strategies/{publish_id}/visibility` | 改可见性 `public\|unlisted\|private` |

### 互动

| 方法 | 路径 | 说明 |
|---|---|---|
| POST / DELETE | `/strategies/{publish_id}/star` | 收藏 / 取消（幂等，回最新计数） |
| POST | `/strategies/{publish_id}/clone` | 返回可导入 bundle + 计数 +1。**不写调用方的租户库** |
| GET / POST | `/strategies/{publish_id}/comments` | 评论列表 / 发评论（201，支持 `parent_id`） |
| DELETE | `/comments/{comment_id}` | 软删（作者本人 / 发布物主人 / admin） |
| GET | `/me/stars` | 我收藏的策略。`limit`（<=100）/ `offset`；条目与广场列表**同形状**（含 `metrics`），另有 `starred_at`。未登录 401 |
| GET | `/tags` | 标签直方图 |

### 跟单订阅（只推信号，不自动下单）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/strategies/{publish_id}/subscribe` | 订阅（201）。请求体只有 `notify_channels`，**没有 mode 字段** |
| DELETE | `/strategies/{publish_id}/subscribe` | 退订 |
| GET | `/subscriptions` | 我的订阅（带标题 / 作者 / 状态） |
| GET | `/subscriptions/signals` | 拉订阅策略的信号；`trade_date` 为空取各自最新一期 |
| POST | `/strategies/{publish_id}/signals` | 作者发当日信号快照（一天一条，重发覆盖；仅作者 / admin） |

响应里的 `notice` 字段固定写着「只推信号，不自动下单」，前端应原样展示，不要吞掉。

### 榜单、动态与用户

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/leaderboard` | 读榜快照。`board=overall\|sharpe\|return\|rookie`、`as_of`、`limit`；每条含 `sort_value`（本榜排序键值，主榜等于 `score`） |
| GET | `/leaderboard/boards` | 各榜口径与门槛 |
| POST | `/leaderboard/rebuild` | 重算并落快照（**仅 admin**） |
| POST | `/strategies/{publish_id}/metrics` | 写一期绩效切片（作者 / admin）。`score` 服务端现算 |
| GET | `/feed` | 动态流。`scope=all\|following\|mine` |
| GET | `/users/{user_id}/profile` | 公开主页：作品、关注数、累计收藏 |
| POST / DELETE | `/users/{user_id}/follow` | 关注 / 取关 |

### 净值曲线契约

绩效切片的标量之外，净值曲线**只有一个位置、一种形状**（前端不用再在
`metrics_json` / `manifest.backtest` 里按 `equity` / `equity_curve` / `nav` / `curve`
四个名字猜）：

```json
POST /strategies/{publish_id}/metrics
{
  "as_of": "2026-08-27",
  "sharpe_1y": 1.8,
  "metrics": { "equity_curve": [{"d": "2024-01-02", "v": 1.0}, {"d": "2024-01-03", "v": 1.0234}] }
}
```

- `d` = `YYYY-MM-DD`，`v` = **归一化净值（起点 1.0）**，不是金额。
- 点数建议 <= 750（约三年日频），超了服务端等距降采样，首尾必留。
- 写入时服务端归一一次：历史别名（`equity` / `nav` / `curve`）、`{"date","value"}`
  近义键、`[date, value]` 二元组都认，**落库只写 `equity_curve`**；形状认不出来时
  曲线为空，其余标量照常落库，不会 4xx/5xx。
- 读的一方（`GET /strategies/{id}` 的 `metrics.metrics`）拿到的一定是契约形状。

## 约定

- 读接口全部匿名可用（private / 已下架的除外）；写接口 = `write_dependency` + 当前用户，
  且**只能改自己的发布物**，admin 例外。
- 路由层只做「解析 → 调 application → 映射错误」。业务公式一律不在这里，
  上架清单与评分在 `domain/`。
- 领域错误经 `deps.py::domain_errors()` 映射：
  `validation_error` 422、`publish_rules_failed` 422（带逐条 `violations`）、
  `not_found` 404、`forbidden` 403、`conflict` / `version_frozen` 409。
  **看不见的东西一律 404**，不用 403——403 会泄露「这个 id 确实存在」。
- 写入模型全部 `extra="forbid"`：拼错字段直接 422，不静默丢。
- 端点全是同步 `def`（跑 threadpool），因为下面是同步 SQLite；不要改成 `async def` 再堵事件循环。
- 本层两个 router 文件**不使用** `from __future__ import annotations`：工厂内的
  `Annotated[..., Depends(...)]` 别名必须在 `def` 时求值成实体，否则 FastAPI 会把
  `store` / 写依赖 / 当前用户误判成 query 参数。

## 测试

`tests/community/test_square_metrics.py`：广场卡片的 `metrics`、净值曲线归一、`GET /me/stars`
的登录/未登录两条路径。

`tests/community/test_api_router.py`：工厂契约、401/403/422 映射、`auth_dependency` 的四种形状、
`mode=auto_trade` 被 schema 拒绝、写依赖被拒时读接口仍可用。用临时库，不碰真实 `data/`。
