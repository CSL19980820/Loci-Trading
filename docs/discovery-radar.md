# 提前发现雷达

本功能用于把“提前发现好股”的方法沉淀成可运行流程：先维护行业/公司观察池，再用真实 K 线、资金流、财务前置信号和反证规则筛出观察对象。它不是自动荐股器，也不输出买卖建议。

## 使用方式

准备 watchlist CSV：

```csv
code,name,theme,sector_rank,sector_position,chain_depth,industry_signal,evidence_score,notes
002460,赣锋锂业,锂电材料,6,8,2,3,2,示例行
```

运行：

```powershell
.\.venv\Scripts\python.exe discover.py --watchlist examples\discovery_watchlist.sample.csv --formats all
```

离线 K 线：

```powershell
.\.venv\Scripts\python.exe discover.py --watchlist watchlist.csv --kline-dir data\kline --offline --formats all
```

`--kline-dir` 内文件名支持 `000001.csv` 或 `000001*.csv`，列名需包含 `日期,开盘,收盘,最高,最低,成交量,涨跌幅`。

## Watchlist 字段

| 字段 | 含义 |
|---|---|
| `code` | 6 位股票代码，必填 |
| `name` | 股票名称 |
| `theme` | 行业/题材 |
| `sector_rank` | 行业/题材强度排名，越小越强 |
| `sector_position` | 个股在同板块中的位置，3-20 更符合提前观察区 |
| `chain_depth` | 产业链层级，2/3 代表二三层环节 |
| `industry_signal` | 产业先行信号手工分，0-6 |
| `evidence_score` | 公告、互动、业绩说明会等公开证据手工分，0-6 |
| `notes` | 备注 |

## 评分结构

| 维度 | 分值 | 说明 |
|---|---:|---|
| 产业证据 | 25 | 题材强度、同板块位置、二三层环节、公开证据 |
| 趋势位置 | 25 | MA20/MA60、近 10 日涨幅、距 60 日高点 |
| 量价形态 | 25 | 温和量比、T-1 形态、放量滞涨反证 |
| 资金财务 | 25 | 近 3/5 日主力净流入、财务改善项 |

分层：

- `重点观察`：得分 >= 75，且无硬剔除。
- `观察`：65-74，且无硬剔除。
- `待证据`：55-64，说明产业或公开证据仍需补齐。
- `剔除`：命中硬反证，如放量滞涨、续涨透支、龙一龙二。
- `不纳入`：得分不足。

## 反证规则

硬剔除包括：

- 最新日线 T-1 形态为 D：涨幅已进入续涨动量区。
- 最新日线 T-1 形态为 E：量比高且涨幅很小，放量滞涨。
- 三日堆量不涨、高振幅收平、长上影、OBV proxy 下行。
- `sector_position <= 2`，即龙一/龙二，不属于提前潜伏区。

## 每日流程

1. 早上或盘后维护行业池，只保留有景气变化的方向。
2. 给公司池补 `sector_rank`、`sector_position`、`chain_depth`、`industry_signal`、`evidence_score`。
3. 收盘后运行 `discover.py`，只看真实 K 线和真实资金流。
4. 对 `重点观察/观察/待证据` 再去巨潮资讯、交易所公告、上证 e 互动、深交所互动易核验。
5. 命中反证的票直接从提前观察池移除。

以上仅为公开信息整理与观察框架，不构成投资建议。
