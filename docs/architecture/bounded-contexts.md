# 限界上下文地图

```
app (组合根)
 ├── ledger ──► shared
 ├── market ──► shared
 ├── review ──► ledger, market
 ├── strategy ──► market, formula
 ├── backtest ──► strategy, market
 ├── ops ──► market, ai(调用), shared
 ├── ai ──► ops(密钥/技能), intel(可选)
 ├── intel ──► market(可选), ops
 └── formula (纯计算)
```

| 上下文 | 可写库 | 禁止 |
|---|---|---|
| ledger | palace.db | 依赖行情写账本 |
| market | market.db | 写 palace.db |
| review | market 缓存（可选） | 伪造成交 |
| ops | ops.db | 改账本事实 |
| ai / intel | 配置/对话 | 产出权威数字 |

产品名仍为 Loci / 潜龙记忆宫殿；代码包名 ledger 表示账本限界上下文。

数据源路由的归属：`market` 负责 adapter 注册、同类 lane 路由与 AkShare 运行时能力目录；`ops` 只提供设置/测速 HTTP 工作台。用户的 lane 偏好写本机配置、由 market 在每次路由时读取，不能把测速结果或临时粘性写成行情/账本事实。AkShare 目录与单项试跑是按需能力检查，只有经 adapter 契约接入的字段才进入同步和 `market.db`。
