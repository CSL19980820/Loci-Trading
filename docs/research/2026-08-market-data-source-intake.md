# 候选行情数据项目接入尽调

> **类型**：Explanation（外部数据源预研）  
> **调研日**：2026-08-04  
> **范围**：只核验 `unameyang/pysnowball`、`TickDB/tickdb-unified-realtime-marketdata-api`、`zhangxianglian/stocks-auto`、`RomelTorres/alpha_vantage` 的公开一手资料；没有注册账号、写入密钥或拉取行情。仅对 TickDB 做了一次无鉴权、无副作用的身份验证探测。链接均于调研日访问。

## 结论

| 项目 | 接入建议 | 可带来的独特价值 | 决定性约束 |
|---|---|---|---|
| `unameyang/pysnowball`（原指定 URL） | **不接** | 当前无法验证。 | 指定 GitHub URL 与 GitHub REST 仓库端点均为 `404`，无从审计代码、许可证、维护状态或数据授权。 |
| `uname-yang/pysnowball`（疑似拼写修正） | **研究型 POC，不作核心行情源** | 若需要雪球组合/Cube、基金、北向持股、资金流等资料，能力有增量。 | 依赖用户手工获取雪球 `xq_a_token`/`u`，属于非官方 token 接口封装；需先确认账号/平台条款、限流、字段时效和凭据安全。 |
| TickDB | **不采纳** | 覆盖和实时能力具备增量。 | 付费套餐才能获得可用额度，当前不符合本项目的免费数据源策略。 |
| `zhangxianglian/stocks-auto` | **不接** | 当前无法验证。 | 与 `pysnowball` 相同：指定 URL 与 API 均为 `404`，不能以不可复现的项目承载行情依赖。 |
| `alpha_vantage` | **只作海外/宏观研究备源，不增加 wrapper 依赖** | 官方 API 覆盖全球证券、外汇、数字货币、商品、经济指标和技术指标；文档给出上交所、深交所日线/报价示例，适合小批量交叉核验与海外研究。 | 免费 key 仅 25 次/日，无法承担全市场同步；实时/延迟美股及多项高频能力为付费，Python wrapper 的发布与现代 Python 元数据维护偏弱。 |

结论中的“备接”是数据能力判断，不等同于允许把任一来源直接纳入生产。行情供应商的代码 MIT 许可证不等于其上游行情数据可商用、转售或长期留存。

## 1. `unameyang/pysnowball`

### 可核验事实

- [项目 URL](https://github.com/unameyang/pysnowball) 和 [GitHub REST 仓库端点](https://api.github.com/repos/unameyang/pysnowball) 在 **2026-08-04** 均返回 `404 Not Found`。GitHub 对已删除、改名、私有或不存在的仓库不会给出足以区分原因的公开详情。
- 因而未能取得 README、源码、`LICENSE`、release、commit 或 issue 的一手资料；不能对雪球数据覆盖、Cookie/认证方式、频率限制、数据权利或安全性作正面判断。

### 建议

**不接入，也不以第三方 fork 替代。** 若后续能提供可公开访问的、与该项目同一权利主体的仓库或官方 API/条款，需重新尽调：最小项包括认证凭据保存方式、实时与历史字段、限流、商用/展示/再分发权限及连续性。

### 疑似用户意图的拼写修正：`uname-yang/pysnowball`

原链接的 owner 是 `unameyang`，但 [同名项目的拼写修正仓库](https://github.com/uname-yang/pysnowball)（访问：**2026-08-04**）可通过 Git 远端读取；其 [README](https://github.com/uname-yang/pysnowball/blob/master/README.md) 明确写明“雪球 APP Python API（需要自取 token）”，示例要求设置 `xq_a_token` 与 `u` 两个 token。

- **覆盖与增量**：README 列出实时报价 `quotec`、盘口/分笔 `pankou`、日/周/月/60m/30m/1m K 线、业绩/三大报表、资金流向、融资融券、大宗交易、机构评级、基金资料、指数成分/收益、沪深港股通北向持股，以及 Cube 组合净值/持仓/交易等。对本系统最可能的不可替代价值是雪球组合与社区/持仓类资料，而不是基础 OHLCV 主链。
- **认证与安全**：README 要求人工从雪球获取并设置 Cookie/token，已核阅材料没有提供官方 OAuth、服务账号、稳定配额或 SLA 的证据。凭据一旦进入日志、配置或共享进程会导致账号风险；必须通过运行时秘密注入、最小权限和轮换管理。
- **许可与合规**：[仓库 LICENSE](https://github.com/uname-yang/pysnowball/blob/master/LICENSE)（访问：**2026-08-04**）是 Apache-2.0，许可的是封装代码，不是雪球返回的数据。自动化抓取、保存、展示或再分发雪球数据需另行核对雪球条款与业务授权，不能以 Apache-2.0 作为数据授权依据。
- **维护迹象**：[GitHub 提交 Atom](https://github.com/uname-yang/pysnowball/commits/master.atom) 显示最近提交为 **2025-09-21**；[tags 页面](https://github.com/uname-yang/pysnowball/tags) 可见 `0.1.8` 标签。该仓库仍可复现，但维护历史和上游接口稳定性不等于生产 SLA。

**建议**：仅当业务明确需要 Cube/基金/北向等雪球特有资料时做研究型 POC；对少量标的验证 token 生命周期、HTTP 状态、字段语义、时效和限流，并保留原始响应时间。不得把它接成核心 A 股行情源，不得把 token 写入仓库或文档，也不得在未完成条款审查前开启自动化批量抓取。

## 2. `TickDB/tickdb-unified-realtime-marketdata-api`

### 覆盖与不可替代能力

- 项目 [README](https://github.com/TickDB/tickdb-unified-realtime-marketdata-api/blob/main/README.md)（访问：**2026-08-04**）声明一个接口覆盖 A 股、港/美股、外汇、贵金属、指数和加密资产，提供历史 K 线、实时 ticker、深度、最近成交、可用品种查询；A 股示例为 `600519.SH`。
- 同一 README 给出 REST 与 WebSocket：WebSocket 可订阅 `ticker`、`depth`、`trade`。这比仅有轮询日线/报价的候选多出实时盘口与逐笔能力。
- [官网与定价页](https://tickdb.ai/#pricing)（访问：**2026-08-04**）自述 36,000+ 品种、6 类市场，并列出免费 7 天试用（5 并发订阅、30 次/分钟），以及 $99/月（1 年历史、60 次/分钟）、$299/月（3 年、600 次/分钟）、$899/月（10 年、1,800+ 次/分钟）套餐。上述覆盖、时延和可用性均为供应商自述，不是独立实测结论。

### 认证、成本与许可

- [README](https://github.com/TickDB/tickdb-unified-realtime-marketdata-api/blob/main/README.md) 要求 `X-API-Key`；[MCP 配置源码](https://github.com/TickDB/tickdb-unified-realtime-marketdata-api/blob/main/mcp/tickdb_mcp/config.py) 与 [`.env.example`](https://github.com/TickDB/tickdb-unified-realtime-marketdata-api/blob/main/mcp/.env.example) 也确认 `TICKDB_API_KEY` 或逐请求 `X-TickDB-Key`。
- 对 `GET /v1/market/ticker?symbols=600519.SH` 的无鉴权只读探测返回 `401 Unauthorized`，未返回行情；这与文档的鉴权要求一致，但不构成可用性或数据质量验证。
- 代码 [LICENSE](https://github.com/TickDB/tickdb-unified-realtime-marketdata-api/blob/main/LICENSE) 是 MIT（访问：**2026-08-04**），但仓库开源的是 Skill/CLI/MCP 接入层；实际行情仍由 `api.tickdb.ai` 托管并以 key/套餐使用。已核阅材料未给出上游交易所授权、再分发权限或可执行 SLA，采购前必须向供应商索取这些条款。

### 稳定性与维护迹象

- [仓库元数据](https://api.github.com/repos/TickDB/tickdb-unified-realtime-marketdata-api) 显示仓库创建于 **2026-01-11**、默认分支最近提交为 **2026-06-20**；最近公开 release 是 [MCP v0.1.3](https://github.com/TickDB/tickdb-unified-realtime-marketdata-api/releases/tag/mcp/v0.1.3)（2026-06-20），此前仅 v0.1.2。这说明接入层有近期维护，但可观察历史短。
- [MCP CI](https://github.com/TickDB/tickdb-unified-realtime-marketdata-api/blob/main/.github/workflows/mcp-ci.yml)（访问：**2026-08-04**）运行 Ruff、Python 3.11/3.12 测试与 Docker build，是接入代码的正向工程信号；它不验证托管行情的准确性、连续性或授权。

### 决定

**不接入。** TickDB 需要付费套餐才能满足行情使用量，本项目不再进行 POC 或保留适配器。本节仅保留公开资料尽调证据。

## 3. `zhangxianglian/stocks-auto`

### 可核验事实与建议

- [项目 URL](https://github.com/zhangxianglian/stocks-auto) 和 [GitHub REST 仓库端点](https://api.github.com/repos/zhangxianglian/stocks-auto) 在 **2026-08-04** 均为 `404 Not Found`。
- 因此无法确认它究竟是数据采集器、自动交易脚本还是其它用途，也无法取得授权和安全边界证据。

**不接入。** 尤其不应因名称包含 `stocks`/`auto` 而假定其有可用行情能力或可接受的自动化权限。

## 4. `RomelTorres/alpha_vantage`

### 覆盖与不可替代能力

- [wrapper README](https://github.com/RomelTorres/alpha_vantage/blob/develop/README.md)（访问：**2026-08-04**）说明它是 Alpha Vantage HTTP API 的 Python 封装，支持 JSON/pandas/CSV，含时间序列、技术指标、外汇和数字货币；源码目录还包含 fundamentals、options、commodities 与 economic indicators 模块。
- [Alpha Vantage 官方 API 文档](https://www.alphavantage.co/documentation/)（访问：**2026-08-04**）给出 `600104.SHH`（上海）和 `000002.SHZ`（深圳）的日线/复权日线示例，以及 `300135.SHZ` 的报价示例。因此它对 A 股的可验证增量是小批量日线/报价校验，不是独有的 A 股实时能力。
- 官方文档同时提供美国期权、全球指数、外汇、加密货币、商品和宏观经济指标；这些跨资产研究字段是其相对纯 A 股数据源的主要价值。

### 认证、成本与许可

- README 和 [基础类源码](https://github.com/RomelTorres/alpha_vantage/blob/develop/alpha_vantage/alphavantage.py) 要求传入 key 或设置 `ALPHAVANTAGE_API_KEY`；可选 RapidAPI 通道不改变该项目只是远端 API wrapper 的事实。
- [Alpha Vantage 支持页](https://www.alphavantage.co/support/#api-key)（访问：**2026-08-04**）称免费服务为大多数数据集提供 **25 次/日**，经验证的开源或教育项目可获无限日调用；更高调用量转 premium。该免费额度不足以全市场同步，也不能据此推定商业产品的使用权。
- 官方 [API 文档](https://www.alphavantage.co/documentation/) 明示实时和 15 分钟延迟的美股数据、批量实时报价/买卖价等为 premium，商业使用应联系销售。项目 [LICENSE.txt](https://github.com/RomelTorres/alpha_vantage/blob/develop/LICENSE.txt) 是 MIT（访问：**2026-08-04**），仅覆盖 wrapper，不覆盖远端数据许可。

### 稳定性与维护迹象

- [最新 release](https://github.com/RomelTorres/alpha_vantage/releases/tag/v3.0.0) 为 **v3.0.0（2024-07-17）**；[最新 commit](https://github.com/RomelTorres/alpha_vantage/commit/abbbe09583abbe64e204052b225b59ece82c7113) 是 **2026-07-26** 的 README 单行修改。仓库不是废弃状态，但近期没有可见的功能发布信号。
- [setup.py](https://github.com/RomelTorres/alpha_vantage/blob/develop/setup.py) 的 Python classifier 最高到 3.8，测试仍列 `nose`/Travis；这不证明在当前 Python 不可用，但说明不宜为它增加不可替换的运行时依赖。

### 建议

**可作海外/宏观研究备源，不建议作为 A 股实时主源，也不建议直接引入该 wrapper。** 若业务决定使用，优先按官方 HTTP 文档实现一个很小的适配层，并在调用前执行额度、数据日期、延迟与交易所代码映射校验；付费或商用前先完成供应商条款审查。

## 统一准入门槛

任何候选要从“POC”升为“生产备源”，至少需要：

1. 对应业务形态的书面数据许可（展示、存储、研究、商用及再分发边界）。
2. 不含密钥的最小只读接入；密钥从运行时环境注入，不写入源码、文档或配置样例。
3. 同标的、同交易日、同字段口径的对账记录，覆盖开盘、盘中、收盘、停牌和断线恢复。
4. 明确每个数据通道的配额、成本、超限响应、历史深度、时间戳/复权语义和故障降级策略。

本报告只对公开资料作技术与可采购性初筛，不能替代行情数据法律审查、供应商资质审查或实际延迟/完整性验收。
