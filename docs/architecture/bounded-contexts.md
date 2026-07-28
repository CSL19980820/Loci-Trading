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
