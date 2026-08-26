# 同花顺热度 + 尾盘选股器：数据源与证据一手调研（2026-08-12）

> **类型**：Explanation（外部数据源尽调 + 学术证据核验 + 本仓落点评估）  
> **调研日**：2026-08-12  
> **需求原话**：用同花顺「热度板块」+「热度个股前 50」，过滤市值 ≤200 亿，挑尾盘买入、次日冲高的票。来源是微信群经验说法。  
> **范围**：只读。核验同花顺热度接口、开源库源码、学术原文、本仓 `src/market` / `src/strategy` / `src/intel` 与本机 `market_hot.db`。**未改任何代码**，未写爬虫，未批量请求，未注册账号，未使用任何凭据。  
> **证据分级**：`V` 本轮实际发请求并记录了真实返回；`E1` 源码/PDF 全文已读；`E2` 摘要/元数据/检索片段；`E3` 官方或平台文档正文；`E4` 经验主张（不可当收益承诺）。

---

## 0. 诚实边界（先读这一节）

### 0.1 本机网络环境会伪造「接口挂了」的假象

本工作站的 DNS 被本地隧道客户端劫持成 Fake-IP：`q.10jqka.com.cn` → `198.18.0.196`、`data.10jqka.com.cn` → `198.18.0.197`、`dq.10jqka.com.cn` → `198.18.0.198`。TCP 443 能连上，TLS 握手拿到 `SSLEOFError: [SSL: UNEXPECTED_EOF_WHILE_READING]`；`curl --noproxy` 同样是 `schannel: failed to receive handshake` / `Empty reply from server`；走本地代理 `127.0.0.1:17891` 则是 `ReadTimeout` 或同一个 TLS EOF。

**关键对照**：同一轮里 `push2.eastmoney.com` 也 TLS 失败，而 `www.iwencai.com` TLS 成功（TLSv1.3）。所以这不是同花顺在封我们——**是本机出站链路的问题**。`V`

本仓 `src/intel/README.md` 第 36 行已经写过这个坑并给了对策：主机名解析到 `198.18.0.0/15` 时打开 `trust_env` 走系统代理出站，「否则直连 198.18 必挂」。任何「同花顺连不上」的结论都必须先排除这一层，否则会把环境问题写成供应商封禁。

### 0.2 我验证过什么 / 我没验证到什么

| 事项 | 状态 |
|---|---|
| 同花顺个股热榜 JSON 接口 | **已验证**，见 [A1]，从异地只读通道单次 GET，返回 100 行真实数据 `V` |
| 同花顺概念板块热榜 JSON 接口 | **已验证**，见 [A2]，单次 GET，返回 20 行 `V` |
| `www.iwencai.com/robots.txt` | **已验证**，200，正文见 [A6] `V` |
| `q.10jqka.com.cn/robots.txt` | **已验证不存在**：异地通道返回 `404 Not Found` `V` |
| `data.10jqka.com.cn` / `www.10jqka.com.cn` 的 robots.txt | **未能验证**（本机链路挂，异地通道未再发请求以免变成扫站） |
| 同花顺热榜官方规则页 `t.10jqka.com.cn/pid_304819259.shtml` | **未能验证**：异地通道返回 `401 Unauthorized`（需登录）。热度口径只有检索摘要级证据 `E2` |
| 同花顺 App 榜与网页榜是否同源 | **未能验证**：无 App 抓包，不做推断 |
| akshare 1.18.56 的同花顺函数全表 | **已验证**：本机安装包内省 + 源码逐个读 `E1` |
| 东财 / 雪球 / 百度热榜的真实返回 | **未验证**：本机 TLS 到 `push2.eastmoney.com` 就挂，只读了 akshare 源码里的 URL 与列名 `E1` |

**没有验证到的一律不写字段名，也不写「文档声称」之外的话。**

---

## 结论摘要

| 问题 | 结论 |
|---|---|
| 同花顺热度能不能稳定拿 | **勉强能**。存在一个零鉴权、零 cookie、零 `hexin-v` 的 JSON 接口，本轮实测可用；但它是 App 前端私有接口，无官方文档、无 SLA、无版本承诺，参数与字段随时可改，`robots.txt` 在该域名下不存在（404，等于既没允许也没禁止） |
| 最推荐的数据方案 | **不新建同花顺直连适配器**。第一步把已在跑的 `intel_fetch` 配方里的 `smart_hotlist` 加一个 `platform="ths"` 参数（一行），热度即落进可重建缓存 `market.db.intel_snapshots`；第二步若研究证明热度真有增量，再按 ADR-009 加第 7 条 tape lane，`ths_hot` 直连做 provider、悟道 MCP 做另一个 provider，first-healthy-wins |
| 学术证据对「热度前 50 尾盘买入」的态度 | **在 T+1 到 T+20 这个尺度上偏证伪**。注意力冲击的正向部分基本发生在「被关注的当天」，之后是反转：Robinhood 每日买入榜前列股票 20 日异常收益 **−4.7%**；A 股百度指数研究直接报「关注度高的次日跌、关注度低的次日涨」。「尾盘」那条一手证据（Gao et al. 2018）是**指数级别时序**结论，不是「挑最热的 50 只票」的横截面结论，不能拿来支撑本设想 |
| 报告路径 | `docs/research/2026-08-ths-heat-tail-close-picker.md`（本文） |

**一句话**：数据比想象的好拿，逻辑比想象的差。

---

## A. 同花顺热度数据到底怎么拿

### A1. 个股热度榜（已验证，零鉴权）

```
GET https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock
    ?stock_type=a&type=hour&list_type=normal
```

本轮从异地只读通道发了**一次** GET，**不带任何 cookie、不带 `hexin-v`、不带 Referer**，返回 `200` + 27,972 字节 JSON。`V`

顶层结构 `{"status_code":0, "data":{"stock_list":[…]}, "status_msg":"success"}`，`stock_list` 长度 **100**。字段全集（对 100 行取并集，实测）：

| 字段 | 实测值示例 | 说明 |
|---|---|---|
| `order` | `1`…`100` | 热度排名，升序 |
| `code` | `"600664"` | 6 位代码，**不带市场后缀** |
| `name` | `"哈药股份"` | |
| `rate` | `"760487.0"` | **热度值，字符串**（不是 float），口径未公开 |
| `rise_and_fall` | `6.5296` | 涨跌幅，百分数数值（不是小数） |
| `hot_rank_chg` | `0` | 排名变化 |
| `market` | `17` / `33` | 内部市场枚举（实测 17=沪、33=深） |
| `tag.concept_tag` | `["流感","医药电商"]` | **同花顺概念标签数组**——「同板块找热度高的」所需的板块归属就在这里 |
| `tag.popularity_tag` | `"持续上榜"` / `"2天1板"` | 文案标签，非结构化 |
| `topic` | `null` | 实测全为 null |
| `analyse` / `analyse_title` | 部分行才有 | 上榜解读文本 |

实测前 5 行（2026-08-12 约 17:00 的 hour 榜）：

| order | code | name | rate | rise_and_fall |
|---|---|---|---|---|
| 1 | 600664 | 哈药股份 | 760487.0 | 6.5296 |
| 2 | 600667 | 太极实业 | 711814.0 | 7.1226 |
| 3 | 600721 | 百花医药 | 667685.0 | 10.0392 |
| 4 | 000636 | 风华高科 | 562802.0 | 1.0023 |
| 5 | 002428 | 云南锗业 | 428474.0 | 5.6841 |

**没有市值字段**。`市值 ≤200 亿` 必须用本仓 `market.db` 自己算，见 [C3]。

参数空间只有社区级证据（`E1`，读的是调用方源码，不是同花顺文档）：`type` ∈ `hour|day|week`（见 [A5] 悟道 schema 的 `thsType` 枚举与 adata 实现互相印证）、`list_type` ∈ `normal|detail`、`stock_type` ∈ `a|hk|us`。本轮只实测了 `type=hour`；`type=day` 那一次 WebFetch 超时，**未验证**。

### A2. 板块热度榜（已验证，零鉴权）

```
GET https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/plate?type=concept
```

同样单次无凭据 GET，`200`，`{"status_code":0,"data":{"plate_list":[…20 项…]},"status_msg":"success"}`。`V`

| 字段 | 实测值示例 | 说明 |
|---|---|---|
| `order` | `1`…`20` | 只有 **20** 条 |
| `code` | `"886033"` | 同花顺概念指数代码（886xxx / 885xxx） |
| `name` | `"共封装光学(CPO)"` | |
| `rate` | `"289779.5"` | 板块热度值，字符串 |
| `rise_and_fall` | `2.9823` | 板块涨跌幅 |
| `hot_rank_chg` | `0` | |
| `hot_tag` | `"连续268天上榜"` / `"首次上榜"` / `"10天8次上榜"` | 上榜持续性文案 |
| `tag` | `"6家涨停"` | 板内涨停家数文案 |
| `market_id` | `48` | |
| `etf_product_id` / `etf_name` / `etf_rise_and_fall` / `etf_market_id` | `"159363"` / `"创业板人工智能ETF"` / `2.2023` / `36` | 关联 ETF，部分行缺失 |

`type=industry` 取行业板块热榜（`E1`，来自 adata 源码；本轮**未实测**）。

**注意口径断层**：板块榜的 `code` 是同花顺概念指数代码（`886033`），个股榜的 `tag.concept_tag` 是**中文概念名**（`"共封装光学(CPO)"`）。两者要靠**名称字符串**关联，没有共同 id。要做「同板块找热度高的个股」必须先建一张名称映射，或者改用 `stock_board_concept_name_ths()`（见 [A5]）拿 name→code 表——那条路要 `v` cookie。

### A3. 热度口径：官方规则页拿不到

同花顺官方在圈子里挂了《同花顺热榜规则介绍》，URL `http://t.10jqka.com.cn/pid_304819259.shtml`。本轮请求返回 **`401 Unauthorized`**，需要登录，**全文未读到**。`V`

检索摘要引述该页正文：「同花顺热榜根据同花顺端内海量用户的真实行为进行计算，实时展示现在同花顺端内用户广泛关注的标的」。这只有 `E2` 级别——**转述，不是原文**。

第三方官方文档对 `rate` 的描述是「热度值」，无公式（见 [A5] Tushare 文档 `E3`）。

**结论**：`rate` 的确切构成（搜索量？点击？自选？成交？加权系数？）在本轮**未能从一手来源确认**。做因子时必须把它当「不可解释的黑箱分数」，不能声称它是搜索热度或自选热度。

### A4. 问财（iwencai）能不能查「热度排名前 50」

**技术上能问，工程上不建议。**

问财是自然语言选股，社区教程用 `pywencai.get(query='热门个股排名', loop=True)` 拿榜（`E2`，腾讯云社区文章，二手；原始出处是 pywencai README 的 API 用法 `E1`）。但：

1. **必须带 cookie**。pywencai README 头部原文：「⚠️注意：由于问财登录策略调整，目前**必填cookie参数**才能使用」，并附 `cookie.png` 教人从浏览器请求头里复制。`E1`
2. **必须装 Node.js v16+**。README「环境依赖」：「由于程序中执行了js代码，请先保证已安装了 Node.js，需要版本 v16+」。`E1` 实现处 [`pywencai/headers.py`](https://github.com/zsrl/pywencai/blob/main/pywencai/headers.py) 用 `subprocess.run(['node', …'hexin-v.bundle.js'])` 生成 `hexin-v` 头。
3. **`robots.txt` 明确 Disallow**。见 [A6]。
4. **返回列名不稳定**。问财按问句动态出列，同一问句换天可能换列；本仓 `domain/source_contract.py` 的 `FieldSpec` 契约模型要求「目标列 + 候选源列 + 单位」是稳定声明，动态列直接冲突。

问财在这件事上的**唯一不可替代能力**是「热度 + 市值 + 涨幅」一句话联合过滤（省掉本地 join）。但本仓已经有全量 `market.db`，join 是零成本的，这个能力没有价值。

**判定：问财不进本项目。**

### A5. 开源库支持情况（逐个读源码）

#### akshare 1.18.56（本机安装包全表核验）

对本机 `akshare` 做完整内省：**52 个** callable 的 docstring 命中 `10jqka` 或「同花顺」。`E1`

**关键否定结论：52 个里没有任何一个是同花顺热度/人气榜。** 本机 `dir(akshare)` 里所有 `*hot*` 函数是：

```
stock_hot_rank_em / stock_hot_rank_detail_em / stock_hot_rank_detail_realtime_em
stock_hot_rank_latest_em / stock_hot_rank_relate_em / stock_hot_keyword_em / stock_hot_up_em
stock_hk_hot_rank_em / stock_hk_hot_rank_detail_em / stock_hk_hot_rank_latest_em / stock_hk_hot_rank_detail_realtime_em
stock_hot_follow_xq / stock_hot_tweet_xq / stock_hot_deal_xq
stock_hot_search_baidu
```

全是**东财 / 雪球 / 百度**，没有同花顺。

**曾经有过**：`akshare/__init__.py` 的 changelog 里 `stock_hot_rank_wc`（`wc` = 问财）出现 15 次，从 `0.9.5: add` 一路 fix 到 `1.14.80 fix`，然后**消失**。`E1` 本机 1.18.56 既没有该函数、也没有 `*wc*` 文件，changelog 里**没有任何删除记录**（搜 `del:` / `delete` / `deprecat` / `下线` 均无命中）。上游 `raw.githubusercontent.com/akfamily/akshare/main/akshare/stock/stock_hot_rank_wc.py` 返回 `404`。`V`

> 这是一条重要信号：**akshare 维护者把同花顺热度接口静默下掉了**，且发生在长期反复修补之后。这条链路的历史稳定性有据可查地差。

akshare 里与本设想相关的同花顺函数（URL 均取自源码 docstring，`E1`）：

| 函数 | 真实请求 URL | 需要 `v` / `hexin-v` | 与本设想的关系 |
|---|---|---|---|
| `stock_fund_flow_concept` | `http://data.10jqka.com.cn/funds/gnzjl/…/ajax/1/free/1/` | **需要 `hexin-v` 头** | 概念**资金流**，不是热度。且 akshare 把返回列命名成 `行业/行业指数/行业-涨跌幅`（源码 210–222 行），概念榜复用了行业榜的列名 —— 属 akshare 侧标签错误，别照抄 |
| `stock_fund_flow_industry` | `http://data.10jqka.com.cn/funds/hyzjl/…` | 需要 `hexin-v` | 行业资金流 |
| `stock_fund_flow_individual` | `http://data.10jqka.com.cn/funds/ggzjl/…` | 需要 `hexin-v` | 个股资金流；`即时` 档返回 `流入资金/流出资金/净额/成交额/换手率` |
| `stock_board_concept_name_ths` | `https://q.10jqka.com.cn/gn/detail/code/307822/` + `q.10jqka.com.cn/gn/index/field/addtime/…` | **需要 `v` cookie** | 概念 name↔code 映射，[A2] 的口径断层要靠它补 |
| `stock_board_concept_index_ths` | `https://d.10jqka.com.cn/v4/line/bk_{clid}/01/{year}.js` | 需要 `v` cookie | 概念指数日线，可做板块热度的价格侧对照 |
| `stock_rank_cxg_ths` / `cxd` / `cxfl` / `cxsl` / `lxsz` / `lxxd` / `ljqd` / `ljqs` / `xstp` / `xxtp` / `xzjp` | `https://data.10jqka.com.cn/rank/<code>/` | 见源码 | 同花顺技术选股榜（创新高/创新低/连续放量/量价齐升/向上突破…），**不是热度**。列名本轮未逐一核验 |

`v` / `hexin-v` 的生成方式（`E1`，[`stock_board_concept_ths.py:38-68`](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_board_concept_ths.py)、[`stock_fund_flow.py:50-67`](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_fund_flow.py)）：akshare 自带一个 `ths.js`（`akshare.datasets.get_ths_js`），用 **`py_mini_racer`** 在进程内 `eval` 后 `call("v")`，再把结果塞进 `Cookie: v=…`（q 域名）或 `hexin-v: …` 头（data 域名）。

> **本仓已经付过这笔成本**：`loci.spec` 第 66–69 行 `collect_all("py_mini_racer")`，`docs/portable-desktop.md` 第 19 行写明「新浪历史日 K 需 `mini_racer.dll` + `icudtl.dat`」。也就是说**同花顺 `v` cookie 这条路的运行时依赖已经在包里了**，边际成本接近零。反过来，pywencai 需要的 `node` 可执行文件**没有**、也不适合塞进便携桌面包。

#### pywencai（`zsrl/pywencai`）

| 项 | 值 | 来源 |
|---|---|---|
| License | **MIT** | GitHub API `V` |
| Star / Fork | **880 / 244** | GitHub API `V` |
| 主语言 | **JavaScript**（因为 5MB 的 JS bundle 比 Python 代码大得多） | GitHub API `V` |
| 创建 / 最后 push | 2022-09-17 / **2025-05-07** | GitHub API `V` |
| Open issues | 29，未 archive | GitHub API `V` |
| 版本 | 0.13.1 | [`pyproject.toml`](https://github.com/zsrl/pywencai/blob/main/pyproject.toml) `E1` |

实现要点（`E1`）：

- [`pywencai/hexin-v.bundle.js`](https://github.com/zsrl/pywencai/blob/main/pywencai/hexin-v.bundle.js) **5,171,806 字节**的 webpack 产物，专门用来算 `hexin-v` 反爬 token；另有 52KB 的 `hexin-v.js`。
- [`headers.py`](https://github.com/zsrl/pywencai/blob/main/pywencai/headers.py)：`subprocess.run(['node', …])` 起外部进程算 token；`fake_useragent` 随机 UA。**每次请求 fork 一个 node 进程 + 随机化 UA**，这是反检测模式，不是普通客户端行为。
- [`wencai.py`](https://github.com/zsrl/pywencai/blob/main/pywencai/wencai.py)：三个 POST 端点 `www.iwencai.com/customized/chart/get-robot-data`、`/gateway/urp/v7/landing/getDataList`、`/unifiedwap/unified-wap/v2/stock-pick/find`；内建 `while_do(retry=10)` 裸 `except:` 重试。
- 依赖：`PyExecJS`、`requests`、`pandas>=1.5`、`fake-useragent`、`pydash`、**`ipykernel`**（一个数据库依赖里带 Jupyter 内核，是个信号）。

README 的作者自述（`E1`，原文）：「并非同花顺官方提供的工具」「建议低频使用，反对高频调用，高频调用会被问财屏蔽，请自行评估技术和法律风险」「项目代码遵循MIT开源协议，但**不赞成商用**，商用请自行评估法律风险」。

**判定：不接。** 需要 node 运行时（便携包做不到）、需要人工 cookie（本仓无「用户手动贴 cookie」的运维位）、作者本人反对高频与商用。

#### adata（`1nchaos/adata`）—— 唯一实现了同花顺热榜的可读源码

| 项 | 值 | 来源 |
|---|---|---|
| License | **Apache-2.0** | GitHub API `V` |
| Star / Fork | **5,083 / 683** | GitHub API `V` |
| 创建 / 最后 push | 2023-05-23 / **2025-12-26** | GitHub API `V` |
| `sentiment/hot.py` 最后提交 | `55647e06`，**2025-12-26** | GitHub API `V` |

[`adata/sentiment/hot.py`](https://github.com/1nchaos/adata/blob/main/adata/sentiment/hot.py) `E1`：

- `hot_rank_100_ths()` → 打的就是 [A1] 那个 URL，重命名为 `rank/stock_code/short_name/change_pct/hot_value/pop_tag/concept_tag`。
- `hot_concept_20_ths(plate_type=1|2)` → `…/hot_list/v1/plate?type=concept|industry`，重命名为 `rank/concept_code/concept_name/change_pct/hot_value/hot_tag`。**这是我确认板块端点路径的来源**（我一开始猜 `/block` 是错的，超时；`/plate` 才对）。
- `pop_rank_100_east()` → 东财 `emappdata.eastmoney.com/stockrank/getAllCurrentList`。

**但 adata 有一个必须点名的问题**：[`adata/common/headers/ths_headers.py`](https://github.com/1nchaos/adata/blob/main/adata/common/headers/ths_headers.py) 把一份**真实抓包 cookie 硬编码进源码**——`v=AzCSZkis…`、`FPTOKEN=…`、`Hm_lvt_…=1680163246`（该时间戳是 **2023-03-30**）。也就是说 adata 至今在用一份三年前的 cookie 去请求同花顺。`E1`

对我们的意义有两面：一是**别抄它的 header 层**（抄了就是把别人的会话凭据写进我们的仓）；二是**我本轮不带任何 cookie 也拿到了 200**，说明 `dq.10jqka.com.cn/fuyao/*` 今天不校验 cookie，adata 那份陈旧 cookie 大概是无害的历史包袱而不是必需品。

#### qstock / efinance / Ashare

| 库 | 同花顺热度支持 | 证据 |
|---|---|---|
| `tkfy920/qstock` | **无独立热度接口**。有同花顺概念板块 `ths_index_*`、同花顺资金流、同花顺技术选股 RPS/MM；热度类需求靠 `qstock.wencai()` 转给 pywencai，README 明确要求「下载安装 node.js，在界面输入 `npm install jsdom`」，且「部分策略选股和回测功能仅供知识星球会员使用」 | 仓库 README `E2`（页面正文已读，非源码逐行） |
| `efinance` | 本轮未在其能力表中发现同花顺热度实现；qstock README 自述其爬虫「参考了 tushare、akshare 和 efinance」，暗示 efinance 也是东财系为主。**未逐行核验源码，标未验证** | `E2` |
| `Ashare` | 极小体量的日 K/分钟 K 单文件库，与热度无关。**未核验** | — |

#### Tushare `ths_hot`（付费积分路线，有官方文档）

[Tushare 文档 doc_id=320](https://tushare.pro/document/2?doc_id=320) `E3`，正文已读：

- 接口 `ths_hot`，「获取热榜数据，包括热股、概念板块、ETF、可转债、港美股等等，**每日盘中提取4次，收盘后4次，最晚22点提取一次**」。
- 限量单次 2000 条；**需 6000 积分**。
- 入参 `trade_date` / `ts_code` / `market`（热股、ETF、可转债、行业板块、**概念板块**、期货、港股、热基、美股）/ `is_new`（`Y`=22:30 定稿，`N`=盘中盘后采集，看 `rank_time`）。
- 出参 `trade_date / data_type / ts_code / ts_name / rank / pct_change / current_price / concept / rank_reason / hot / rank_time`。文档示例数据里 `hot=214462.0`、`concept=["钠离子电池","同花顺漂亮100"]`。

> 这是**唯一带官方字段文档 + 历史回溯 + 采集时点标注**的同花顺热度通路。它的 `hot` 与 `concept` 和 [A1] 实测的 `rate` / `tag.concept_tag` 数量级、形态一致，可互为交叉验证。代价是积分门槛（≈付费）。
>
> **对回测的意义最大**：[A1] 的直连接口**只有当前快照，没有历史**。没有历史就没法回测「热度前 50 尾盘买」。要么长期自采落库（几个月起），要么走 `ths_hot` 这种有 `trade_date` 的历史源。**这是整件事最大的工程瓶颈，比取数难得多。**

#### 库对照汇总

| 库 | License | Star | 最后 push | 维护 | 同花顺热度 | 判定 |
|---|---|---|---|---|---|---|
| `akfamily/akshare` | MIT | 21,971 | 2026-08-10 | **活跃** | **无**（`stock_hot_rank_wc` 已静默移除） | 已在仓内；热度用不上，`v` cookie 机制可复用 |
| `zsrl/pywencai` | MIT | 880 | 2025-05-07 | 半停滞 | 间接（问财问句） | **不接**：需 node、需人工 cookie、作者反对商用 |
| `1nchaos/adata` | Apache-2.0 | 5,083 | 2025-12-26 | 活跃 | **有**（个股 100 + 板块 20） | **不加依赖，只读它的 URL 与解析口径**；header 层不可抄 |
| `tkfy920/qstock` | 见仓库 | — | — | — | 无（转 pywencai） | 不接 |
| Tushare `ths_hot` | 商业平台 | — | — | 商业 | **有 + 有历史 + 有文档** | **回测阶段的唯一现实历史源**，需 6000 积分 |

Star / push 数据均来自 GitHub REST API，取数日 2026-08-12。`V`

### A6. 反爬与合规

| 项 | 事实 | 证据 |
|---|---|---|
| `q.10jqka.com.cn/robots.txt` | **404 Not Found**——该主机没有 robots.txt。既未授权也未禁止 | `V` |
| `www.iwencai.com/robots.txt` | **200**，正文：`User-agent: *` / `Disallow: /ajax/stock` / `Disallow: /snapshot/news/` / `Disallow: /snapshot/forum/` / `Disallow: /snapshot/blog/` / `Disallow: /cluster/news/` / **`Disallow: /search`** / `Disallow: /channel/weibo/` / **`Crawl-delay: 10`** | `V` |
| `data.10jqka.com.cn` robots | **未验证** | — |
| `dq.10jqka.com.cn/fuyao/*` 是否需要凭据 | **实测不需要**：无 cookie、无 `hexin-v`、无 Referer，`200` | `V` |
| `data.10jqka.com.cn/funds/*` 是否需要凭据 | akshare 每一页请求都重算 `hexin-v` 并逐页附带 | `E1` |
| `q.10jqka.com.cn/gn/*` 是否需要凭据 | akshare 附 `Cookie: v=<mini_racer 算出的值>` | `E1` |
| 问财频控 | pywencai README：「反对高频调用，高频调用会被问财屏蔽」 | `E1` |

**合规判读**（工程判断，不是法律意见）：

1. `Crawl-delay: 10` 是问财自己声明的礼貌下限。本仓 `market.db` 全市场同步是几千次请求量级——**问财这条路在 robots 语义下就不可能合规地承担全市场任务**，而且 `Disallow: /search` 覆盖的正是问财的查询路径族。
2. `dq.10jqka.com.cn/fuyao/*` 每天**一到几次**请求（个股榜 1 次拿 100 行、板块榜 1 次拿 20 行）就够，量级与「个人打开一次 App」同阶。这是本次唯一在频次上说得过去的同花顺通路。
3. 代码 License（akshare MIT / adata Apache-2.0）**只授权代码，不授权同花顺返回的数据**。本仓 `docs/research/2026-08-market-data-source-intake.md` 已经立过这条规矩（结论表下方原文）：「行情供应商的代码 MIT 许可证不等于其上游行情数据可商用、转售或长期留存」；同文末「统一准入门槛」第 1 条进一步要求书面数据许可才能从 POC 升为生产备源。同花顺热度同理——**自用研究可以，不得再分发**。
4. 明确禁止：`fake_useragent` 那种随机 UA 轮换、多 IP 轮转、绕过 `hexin-v` 之外的任何反检测手段。本仓 `AGENTS.md` 的工程卫生条款不给这类代码留位置。

**结论**：`dq.10jqka.com.cn/fuyao/*` 在「每天几次、单机自用、不再分发」的约束下现实可行。成本不在取数，**成本在没有历史数据、没有 SLA、没有字段承诺**——它是 App 私有接口，同花顺任何一次前端改版都可能让它换路径、加签名或直接下线，而且不会有公告。

### A7. 替代 / 兜底源与「热度」口径对齐表

| 源 | 取数入口 | 「热度」到底是什么 | 行数 | 历史 | 可否替代同花顺 |
|---|---|---|---|---|---|
| **同花顺热榜** | `dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock` | `rate`，同花顺端内用户行为综合分。**口径未公开**（官方规则页 401 未读到） | 100 | 无（仅当前快照） | 基准 |
| **同花顺板块热榜** | 同上 `/plate?type=concept\|industry` | `rate`，板块热度 | **20** | 无 | 基准 |
| **东财人气榜** | `stock_hot_rank_em` → POST `emappdata.eastmoney.com/stockrank/getAllCurrentList`，再用 `push2.eastmoney.com/api/qt/ulist.np/get` 补价 | 返回列 `当前排名/代码/股票名称/最新价/涨跌额/涨跌幅`。**只给排名，不给热度值**。`stock_hot_rank_detail_em` 额外给 `新晋粉丝` / `铁杆粉丝` 比例（`newUidRate`/`oldUidRate`），说明底层是股吧/App 的用户关注结构 | 100 | `getHisList` 有 5 年排名史 | **最接近**，但只有 rank 没有 value，且是东财用户群不是同花顺用户群 |
| 东财飙升榜 | `stock_hot_up_em` → `emappdata.eastmoney.com/stockrank/getAllHisRcList` | 排名飙升，对应 `hot_rank_chg` | — | — | 只做变化量补充 |
| **百度股市通热搜** | `stock_hot_search_baidu` → `finance.pae.baidu.com/selfselect/listsugrecomm` | 列 `名称/代码 / 涨跌幅 / 综合热度`。是**搜索**热度 | **12**（源码 `rn: "12"` 硬编码） | 参数有 `day`/`hour` | **不能**：12 行凑不出「前 50」 |
| **雪球热度** | `stock_hot_follow_xq` / `_tweet_xq` / `_deal_xq` → `xueqiu.com/service/v5/stock/screener/screen`，`order_by` 分别为 `follow`/`tweet`/`deal`（`*7d` 为本周新增） | 关注数 / 讨论数 / 交易数，三个**不同**口径。⚠️ akshare 把三者的值列**都命名为 `关注`**（源码三处 `columns` 完全一致），照抄会把讨论量当关注量 | 200/页 | 无 | 口径最清晰但用户群偏机构/长线，与短线热度不同 |
| 开盘啦 / 淘股吧人气 | 悟道 MCP `smart_hotlist(platform="kaipanla"\|"tgb")` | 各平台自有口径 | ≤100 | — | 短线味最正，但同样是黑箱分 |
| **同花顺概念资金流** | `stock_fund_flow_concept` | `流入资金/流出资金/净额`。**这是资金不是热度** | 全量分页 | 有 3/5/10/20 日档 | 不是替代品，是**另一个维度** |

**能不能互换？不能。** 「热度」在每个平台是不同人群的不同行为的不同加权。同花顺热度换成东财人气榜，等于把「同花顺 App 用户在看什么」换成「东财股吧用户在关注什么」——两个榜的重叠度本轮**未测**，不做估计。如果策略对热度源敏感，换源就是换策略；如果不敏感，那热度大概本来就不是有效因子。

**唯一诚实的用法**：把热度当**分类特征而不是连续因子**——「在不在 App 首屏榜上」这件事本身有行为学含义（见 [B2] Robinhood 那篇的机制），而 `rate=760487` 比 `rate=428474` 高多少并没有可解释的意义。

---

## B. 「热度前 50 + 市值<200 亿 + 尾盘买入」的证据

### B1. 注意力因子：一手文献说了什么

| 论文 | 原文入口 | 结论方向 | 时间尺度 |
|---|---|---|---|
| **Barber & Odean (2008)**, "All That Glitters", *RFS* 21(2):785-818 | [作者主页 PDF](http://faculty.haas.berkeley.edu/odean/papers%20current%20versions/allthatglitters_rfs_2008.pdf)、[Haas PDF](https://haas.berkeley.edu/wp-content/uploads/glitters.pdf)、[SSRN 460660](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=460660) `E1` | 散户**净买入**高注意力股（异常成交量、极端日收益、上新闻）；机构相反。原文：「preferences determine choices after attention has determined the choice set」。**这篇讲的是「谁在买」，不是「买了会涨」** | 日频行为，不给收益预测 |
| **Da, Engelberg & Gao (2011)**, "In Search of Attention", *JF* 66(5):1461-1499 | [作者主页 PDF](https://www3.nd.edu/~zda/Google.pdf)、[SSRN 1364209](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1364209)、DOI [10.1111/j.1540-6261.2011.01679.x](https://doi.org/10.1111/j.1540-6261.2011.01679.x) `E1` | 摘要原文：「An increase in SVI predicts higher stock prices in the **next 2 weeks** and an eventual price **reversal within the year**」 | **正向部分是「两周」，不是「次日」**；一年内反转 |
| **Shen, Zhang, Xiong et al. (2017)**, "Baidu index and predictability of Chinese stock returns", *Financial Innovation* 3:4，开放获取 | DOI [10.1186/s40854-017-0053-1](https://doi.org/10.1186/s40854-017-0053-1) `E1` | 摘要原文：「the stock prices **go up when individual investors pay less attention** to the stocks and **go down when individual investors pay more attention** to the stocks」；据此构造的策略是**做空高搜索量、做多低搜索量** | **次日**。方向对本设想是**反的** |
| Yang, Ma, Wang & Wang (2021), *Journal of Behavioral Finance* 22(4):368-381 | [RePEc 条目](https://ideas.repec.org/a/taf/hbhfxx/v22y2021i4p368-381.html) `E2` | 890,840 个「公司-周」样本（2011-2018）：百度 ASVI 与**同期**收益正相关，「with a **complete reversal** in the subsequent period」；创业板更明显 | 周频，下一期完全反转 |
| Xiong, Zhang & Gao (2026), 《管理科学学报》35(2):525-542 | [期刊页](https://xtglxb.sjtu.edu.cn/EN/10.3969/j.issn.2097-4558.2026.02.016) `E2` | 市场/行业/个股三层散户关注度都与**当日**收益正相关；**行业层与个股层存在长期反转**，只有市场层无显著反转 | 当日正、长期反转 |
| 早期中国证据（Emerging Markets Finance and Trade 2015, 51(3)） | DOI [10.1080/1540496X.2015.1046339](https://doi.org/10.1080/1540496X.2015.1046339) `E2` | 「significant and positive effect on the stock return **within a week**… reversed **from the second week on**」 | 一周内正，第二周起反转 |

**归纳**：注意力的正向段在美股是「两周」，在 A 股被压缩到「当日到一周」，而且中国样本里至少有一篇（Shen et al. 2017）直接测出**次日方向为负**。

### B2. 反面证据（必须单列）

**Barber, Huang, Odean & Schwarz (2022)**, "Attention-Induced Trading and Returns: Evidence from Robinhood Users", *JF* 77(6):3141-3190。[SSRN 3715077](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=3715077)、DOI [10.1111/jofi.13183](https://doi.org/10.1111/jofi.13183)。`E1`（摘要与正文片段已读）

摘要原文：

> Consistent with models of attention-induced trading, intense buying by Robinhood users forecasts negative returns. **Average 20-day abnormal returns are −4.7% for the top stocks purchased each day.**

作者还写：「We systematically identify the Robinhood herding episodes and document that these episodes are followed by **abnormal negative returns**」，且「Robinhood herding is influenced by information that is **prominently displayed on the Robinhood app**」。

**为什么这篇是对本设想最直接的打击**：Robinhood 的「Top Movers」榜与同花顺热榜是同一类东西——**App 首屏显著位置展示的排行榜**。这篇论文测的正是「每天榜单前列的票，之后 20 天表现如何」，答案是 −4.7%。同花顺热榜前 50 与之的结构对应关系比任何一篇 SVI 论文都近。

另一条：`docs/research/2026-08-loci-weipan-overnight-formula.md` 已经记过 Berkman et al. (JFQA 2012) 的结论——**高注意力股开盘买更贵**（`E2`）。这条对「尾盘买」是**弱支持**（收盘侧执行比开盘侧便宜），但它支持的是「执行时点」，不支持「选高注意力的票」。

### B3. 尾盘 / 收盘效应：一手证据在讲什么，不在讲什么

**Gao, Han, Li & Zhou (2018)**, "Market intraday momentum", *JFE* 129(2)。[SSRN 2440866](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2440866)、[SSRN 2552752](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2552752)、DOI [10.1016/j.jfineco.2018.05.009](https://doi.org/10.1016/j.jfineco.2018.05.009)。`E1`（工作论文 PDF 全文与出版摘要均已读；本仓 `2026-08-tail-close-indicator-source-review.md` 第 15 行已收录为 E1）

摘要原文：「the **first half-hour return on the market** as measured from the previous day's market close **predicts the last half-hour return**… stronger on more volatile days, on higher volume days, on recession days, and on major macroeconomic news release days」。

**必须讲清楚的三点**：

1. 这是 **market-level 时序**结论，标的是 **SPY 等 ETF**，不是个股横截面。它说的是「今天早盘强 → 今天尾盘也强」，**完全没有说「挑最热的 50 只票在尾盘买」**。拿它给热度选股背书是偷换命题。
2. 它甚至不是一个「买入」信号——是一个**当日择时**信号（早盘定方向，尾盘执行），持有期以**分钟**计，收盘平。
3. A 股复现版本（Chu, Gu & Zhou 2019，本仓已收录为 `E2`）的结论是「A 股**同时**存在日内动量与反转，交易成本阻止套利」，且本仓那份审阅明确写下「`first_30m_return` **不能直接外推** 14:50」。

另一条本仓已确立的硬约束（`2026-08-loci-weipan-overnight-formula.md` 第 13 行）：**A 股平均隔夜收益（收盘→次日开盘）显著为负**（T+1 流动性折扣）。所以「尾盘买、次日冲高卖」赌的是**次日盘中的路径**，不是隔夜跳空。这与用户的「次日冲高」表述其实是一致的——但它意味着**出场必须是次日盘中止盈或收盘，不能默认开盘卖**。

### B4. 小市值：200 亿是个什么档位的过滤器

**Liu, Stambaugh & Yuan (2019)**, "Size and value in China", *JFE* 134(1)。DOI [10.1016/j.jfineco.2019.03.008](https://doi.org/10.1016/j.jfineco.2019.03.008)。`E1`（出版摘要与正文片段已读）

摘要原文：「The size factor **excludes the smallest 30% of firms**, which are companies valued significantly as potential **shells** in reverse mergers that circumvent tight IPO constraints.」正文：「a size premium that includes shell stocks is **distorted upward by the shell premium**」；不剔壳时月度规模溢价从基准升到 **1.36%**。

其他证据（`E2`，二手但可追溯）：多份研究与券商报告一致指出 A 股规模溢价「**2017 年后逐渐减弱**」，机制是 IPO 常态化 + 注册制 + 重组监管收紧削弱壳价值。这条链的原始学术锚点就是上面 CH-3 的「壳价值」机制。

**对本设想的直接含义**：`市值 ≤200 亿` 在 A 股**根本不是小市值筛选**。本机实测（见 [C3]）全市场 83.8% 的股票流通市值都在 200 亿以下。这个阈值真正的作用是**剔掉巨头**——它在热榜这个特定样本上确实很有杀伤力（热榜被万亿级龙头占据），但它带来的不是「规模溢价」，而是「**把样本从大盘股换成中小盘**」这个风格暴露。要主张规模收益，得往 CH-3 剔壳后的口径去，跟 200 亿没关系。

### B5. 直接回答：支持还是证伪

| 设想的三个组件 | 一手证据的态度 |
|---|---|
| 「挑热度前 50」 | **证伪（T+1~T+20 尺度）**。App 显著榜单前列 → 20 日异常收益 −4.7%（Barber et al. 2022）；A 股次日方向为负（Shen et al. 2017）；周频完全反转（Yang et al. 2021）。注意力的正向段在 A 股最多到「当日」，而热榜是**盘中实时更新**的——你在 14:50 看到的高热度，正向部分基本已经体现在当天那根 K 线里了 |
| 「尾盘买入」 | **中性偏支持执行侧**。Berkman et al. 2012：高注意力股开盘买更贵 → 收盘侧执行更便宜。但 Gao et al. 2018 那条「尾盘可预测」是**指数时序**，不是选股依据 |
| 「市值 ≤200 亿」 | **不构成 alpha**。它不是小市值因子（覆盖 83.8% 的票），只是一个风格/流动性截断。CH-3 明确要剔掉最小 30% 而不是保留小票 |
| 「次日冲高」 | **出场设计对了，入场方向错了**。A 股隔夜为负，所以赌次日盘中路径是对的；但入场信号选「最热」正好站在反转的错误一侧 |

**结论**：这套组合的逻辑是「**在注意力冲击的正向段已经耗尽、反转段即将开始的时点入场**」。它更像在接飞刀，而不是骑动量。

**如果一定要做，唯一有理论支撑的改法是把符号翻过来**：把「热度高」当**排除条件**（veto）而不是选择条件——即「在热榜前列 = 今天已经被充分定价 + 明天有反转压力 = 不买」，用热度**变化率**（`hot_rank_chg`）而不是热度水平，或者用「刚进榜」（`popularity_tag="首次上榜"`）这种**注意力冲击刚开始**的状态。这三条都是可以在本仓回测框架里做成开关的假设，但都需要历史热度数据，见 [A5] Tushare 那一段的瓶颈说明。

---

## C. 落到本仓库

### C1. 现有能力盘点（只读核对）

| 能力 | 现状 | 位置 |
|---|---|---|
| `entry_timing="close"` 尾盘入场 | **已支持**，且有前视审计：`close` 档「收盘价已定型可用，裸用当日 `high`/`low` → **block**」 | `src/strategy/README.md` 第 24 行、`src/strategy/application/audit.py` |
| 现有尾盘战法 | `sanyuan-tail-v1`（三源尾盘共振，15:30 计算），但 `tail_resonance.py:47` 声明的是 `entry_timing = "next_open"`——**现有「尾盘」战法实际是次日开盘买**，不是尾盘买 | `src/strategy/application/tail_resonance.py` |
| 全市场市值 | **已有**：`quotes_daily` 有 `outstanding_share` + `close`，可算流通市值 | `src/market/infrastructure/store_schema.py` |
| 盘口情报 tape lane | **已有 6 条**：`market_emotion` / `limit_up_pool` / `broken_limit_up` / `theme_board` / `theme_members` / `auction_snapshot`。router first-healthy-wins，缺数返回 `degraded` | [ADR-009](../adr/ADR-009-market-tape-provider-lanes.md)、`src/market/infrastructure/tape/` |
| 热度采集 | **已在跑**：`intel_fetch` 配方 open 档 `("smart_hotlist", {"limit": 50})`、close 档 `{"limit": 60}`，结果落 `market.db.intel_snapshots`（可整表重建） | `src/intel/application/daily_recipe.py:25,52` |
| 同花顺 `v` cookie 运行时 | **已在包里**：`loci.spec:66-69` `collect_all("py_mini_racer")` | `loci.spec`、`docs/portable-desktop.md:19` |
| Node.js 运行时 | **没有，且不该有**（便携桌面包） | — |
| Fake-IP 出站修正 | **已有**：解析到 `198.18.0.0/15` 时开 `trust_env` 走系统代理 | `src/intel/README.md:36` |

**一个高价值发现**：悟道 MCP 的 `smart_hotlist` 工具 schema 里，`platform` 枚举含 **`ths`**，且另有 `thsType` ∈ `hour|day|week`、`stockType` ∈ `a|hk|us`、`listType` ∈ `normal|detail`、`marketType`。这组参数名与 [A1] 实测端点的 `type` / `stock_type` / `list_type` **一一对应**。`E3`（工具 schema 原文）

但本仓当前调用只传了 `{"limit": …}`，落到默认 `platform="combined"`（多平台综合榜）。**也就是说：本仓每天已经在采热度了，只是采的不是同花顺口径。加一个参数就能改。**

同时要说清 `smart_hotlist` **拿不到的东西**：没有市值字段，没有板块热度。板块侧只有 `theme_intraday_capital` / `sector_analysis`，那是开盘啦（KPL）口径，**不是同花顺板块热度**。要同花顺板块热度只有 [A2] 直连一条路。

### C2. MCP 是对话期工具，不等于运行时数据源

这个区分在本仓已经写死，不能含糊：

| 维度 | MCP（悟道） | 运行时数据源（market lane / adapter） |
|---|---|---|
| 配额 | 日总 5000、structured 3000、close 档配方本身就占几百次 | 无外部配额 |
| 可用性 | 未配 Key / 过期 / 停用 / 未同步工具 = 不可用；**免费 Key 在北京时间 09:15–10:30 暂停服务** | 由 lane 启停与熔断管理 |
| 缺失时的后果 | 「**不得影响**盘面、账本、本地选股、行情同步等主体功能」，`intel_fetch` 记 `skipped` | 全灭才 `degraded` |
| 数据地位 | 情报缓存，`intel_snapshots` **可整表删除重建** | 亦为缓存，但有 lane 契约与回执 |

来源：`src/intel/README.md` 第 25、38、42 行；悟道 MCP server instructions（`FREE_TIER_MARKET_OPEN_RESTRICTED`）。`E3`

**推论**：一个 14:50 触发的尾盘选股器，如果它的入场信号硬依赖 MCP 热度，那么「MCP 不可用 = 今天不选股」。按本仓的「可选依赖铁律」，这是**不允许**的架构。所以热度只能是：

- **加分项 / veto 项**，缺失时战法降级为不带热度的版本；或者
- **走 lane**（有 provider 降级与熔断），不走 MCP 配额池。

### C3. 本机实测：这个漏斗到底剩几只票

用 [A1] 实测那份 100 行热榜的前 50，join 本机 `market_hot.db`（`trade_date=2026-08-12`，只读连接）：`V`

| 步骤 | 剩余 | 说明 |
|---|---|---|
| 同花顺热度榜 | 100 | 接口固定返回 100 |
| 取前 50 | 50 | 用户口径 |
| 能在本地 `quotes_daily` join 到 | **49** | `688825`（长鑫科技）**本地没有**——新上市标的还没进 `instruments`/`quotes_daily`。这是必须处理的常态缺口，不是偶发 |
| 流通市值 ≤200 亿 | **17** | 热榜被巨头占据：工业富联 13,018 亿、中际旭创 10,223 亿、紫金矿业 6,918 亿、新易盛 5,371 亿、药明康德 3,934 亿 |

同一日全市场对照：5,535 只 `instrument_type='STOCK'`，其中 **4,639 只（83.8%）**流通市值 ≤200 亿，12 只缺 `outstanding_share`。

**三条工程结论**：

1. **200 亿这道闸在热榜样本上砍掉了 2/3**（50→17），但在全市场只砍掉 16%。所以它不是「小市值因子」，而是「**把热榜从龙头股改成跟风股**」——这恰好是 [B2] 反转效应最强的那一类样本。
2. 用的是 `close × outstanding_share` = **流通市值**。用户说的「市值」如果指总市值，口径会更宽松（通过的票更多）。**这个歧义必须在需求侧先定死**，不能让实现自己猜。
3. 新股 join 不上是结构性的。热榜天然偏爱新股次新股，而它们恰恰是本地行情仓最晚补齐的。任何实现都必须显式产出「热榜有 N 只、本地能定价 M 只、被市值闸门拒 K 只」的口径回执，而不是静默丢弃——`src/intel/README.md` 第 20 行「裁剪要留痕」讲的就是这个道理。

> 单日单快照，不是分布。上面 17/49 这个比例**不能**当作长期均值使用。

### C4. 四条方案对比

| 方案 | 做什么 | 工作量 | 风险 | 历史数据 |
|---|---|---|---|---|
| **① 同花顺直连（新 adapter/lane）** | 新 fetcher 打 `dq.10jqka.com.cn/fuyao/*`，在 `domain/source_contract.py` 声明 `FieldSpec`，注册进新 lane | 中：fetcher + 契约 + 归一 + provider + 缓存 + 录制夹具 + README/ADR。参考 `src/market/README.md` 第 15–17 行的扩展规程 | **中高**：App 私有接口，无文档无 SLA，改版即挂且无公告。`rate` 是字符串要转数值；概念只有中文名没有 code（[A2] 口径断层）；`type=day` 未验证 | **无**。只有当前快照，要自采几个月才够回测 |
| **② akshare 转发** | 用现成 akshare 同花顺函数 | 低 | **不可行**：akshare 1.18.56 **没有**同花顺热度函数，`stock_hot_rank_wc` 已被静默移除。能拿到的只有概念资金流与技术选股榜，都不是热度 | — |
| **③ 扩展已有 lane / 改配方** | (a) 配方里 `smart_hotlist` 加 `platform="ths"`（一行）；(b) 若要 provider 降级，按 ADR-009 加第 7 条 lane，同花顺直连与悟道 MCP 各做一个 provider | (a) 极低；(b) 中，但完全走既有骨架（`TapeRequest`/`TapeResult`/`TapeProvenance`/`cache.py`），不新建 SQLite 表 | 低：MCP 侧有配额与 09:15–10:30 停服，但 tape 天然支持 `degraded`；(b) 还能在 MCP 挂时回落直连 | (a) 从改配方那天起自然积累（`intel_snapshots` 有 `fetched_at`）；(b) 同 |
| **④ 兜底东财** | `stock_hot_rank_em` + `stock_hot_rank_detail_em` | 低（akshare 现成，且已是仓内依赖） | 低。但**只有排名没有热度值**，且是东财用户群 | **有**：`getHisList` 声称 5 年排名史——**这是唯一免费的历史注意力数据** |

### C5. 推荐路线

**不新建同花顺直连适配器作为第一步。** 按下面的顺序走，每一步都能独立停下来：

**第 0 步（先做，成本最低，收益最高）：先证伪再取数。**
用方案 ④ 的东财历史排名（`stock_hot_rank_detail_em`，5 年史）做一次回测：「每日人气榜前 50 ∩ 流通市值 ≤200 亿，尾盘等权买入，次日盘中止盈 / 收盘退出」。
- 这份数据**已经在仓内依赖里**，不需要任何新适配器、新 lane、新 ADR。
- 如果东财口径下这个逻辑是负期望（[B2] 强烈预示如此），**整件事到此为止**，省掉后面全部工作量。
- 如果为正，再讨论「换成同花顺口径能不能更好」——那时候取数投入才有依据。
- 唯一要注意：东财榜是**排名**不是热度值，且需要逐票取历史（`srcSecurityCode` 单票一请求），全市场不可行。**只能对候选池做**，且必须尊重本仓的礼貌频控。

**第 1 步（并行，一行改动）：把 `platform="ths"` 加进 `intel_fetch` 配方。**
`src/intel/application/daily_recipe.py` 的 open / close 两处 `smart_hotlist` 各加一个参数。当天起 `intel_snapshots` 就开始积累同花顺口径热度快照，为将来的同源回测攒历史。零风险（配方已有配额预算，`smart_hotlist` 本来就在跑），可随时回滚。

**第 2 步（只有第 0 步为正才做）：按 ADR-009 加第 7 条 tape lane。**
lane 名如 `hot_rank`，两个 provider：同花顺直连（[A1]/[A2]）+ 悟道 `smart_hotlist(platform="ths")`。走既有 `TapeRequest`/`TapeProvenance` 契约、既有 `intel_snapshots` 缓存，**不新建表**。这样：
- MCP 不可用（未配 Key / 09:15–10:30 / 配额耗尽）→ 回落直连；
- 直连挂（同花顺改版）→ 回落 MCP；
- 全挂 → `degraded`，战法降级为不带热度的版本，**不阻断选股**。

**第 3 步：板块热度单独决策。**
同花顺板块热榜只有 20 条且**只能直连**（悟道无此口径）。「同板块找热度高的」这个需求，用个股榜自带的 `tag.concept_tag` 就能在本地做同板块聚合，**不一定需要板块榜**。先用 `concept_tag` 做，需要板块级 `rate` 再说。

### C6. 如果要做，必须先立的闸门

1. **`entry_timing="close"` 且必须过前视审计。** 尾盘信号只能用当日 `close`（14:50 已定型），**不得裸用当日 `high`/`low`**——`audit.py` 会 block，这是对的。
2. **热度快照必须自报时刻。** 热榜是 hour 榜，14:50 的信号如果用了 09:31 的快照就是拿早盘冒充实时。`src/intel/README.md` 第 24 行的 `cache_fetched_at` / `cache_age_minutes` 机制必须透传到战法证据里。
3. **不许把热度写成权威表。** 按 `src/AGENTS.md` 的「是否入库」清单，热度属于「可重建缓存」→ `market.db.intel_snapshots`，可整表删除重建。**不进 `palace.db`。**
4. **口径先定死再实现**：市值是流通还是总；前 50 按 `order` 还是按 `rate` 阈值；「同板块」按 `concept_tag` 第一个还是全部命中。
5. **回执必须显式报缺口**：热榜 N 只 / 本地可定价 M 只 / 市值拒 K 只 / 停牌 ST 涨停拒 J 只。不许静默丢票。
6. **成交可行性**：14:50 信号不等于按收盘价成交。涨停、封板、停牌、价格笼子拒单、收盘竞价成交概率都要 veto——本仓 `2026-08-tail-close-indicator-source-review.md` 的第 3/4/5 条交易所规则页（`E3`）已经把规矩写清了。
7. **热度榜前列本身可能是 veto 而不是信号**（见 [B5]）。回测**必须同时跑正反两个方向**，否则等于只找支持性证据。

---

## 附：本轮实际发出的请求

只读、无凭据、每个 URL 单次，不构成爬取。

| # | 请求 | 结果 |
|---|---|---|
| 1 | `GET https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock?stock_type=a&type=hour&list_type=normal` | `200`，`status_code:0`，`stock_list` 100 行 |
| 2 | `GET https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/plate?type=concept` | `200`，`status_code:0`，`plate_list` 20 行 |
| 3 | `GET https://q.10jqka.com.cn/robots.txt` | `404 Not Found` |
| 4 | `GET http://t.10jqka.com.cn/pid_304819259.shtml`（官方热榜规则） | `401 Unauthorized` |
| 5 | `GET https://dq.10jqka.com.cn/fuyao/…/stock?…type=day…` | 超时，未验证 |
| 6 | `GET https://dq.10jqka.com.cn/fuyao/…/block?type=concept`（路径猜错） | 超时；正确路径是 `/plate`，由 adata 源码确认 |
| 7 | `GET https://www.iwencai.com/robots.txt` | `200`，正文见 [A6] |
| 8 | 本机 TLS/TCP/DNS 探测：`q./data./dq.10jqka.com.cn`、`www.iwencai.com`、`push2.eastmoney.com` | 见 [0.1]，全部 DNS→`198.18.0.x` |
| 9 | GitHub REST：`akfamily/akshare`、`zsrl/pywencai`、`1nchaos/adata` 仓库元数据与文件树 | `200` |
| 10 | `raw.githubusercontent.com`：pywencai `wencai.py`/`headers.py`/`pyproject.toml`/`README.md`、adata `hot.py`/`ths_headers.py` | `200` |
| 11 | `GET https://tushare.pro/document/2?doc_id=320` | `200`，`ths_hot` 文档正文 |
| 12 | 本机只读：`akshare` 1.18.56 包内省 + 源码；`market_hot.db` 只读查询（`file:…?mode=ro`） | 见 [A5]、[C3] |

**未做**：批量抓取、带凭据请求、注册账号、写入任何数据库、修改除本文与 `INDEX.md` 之外的任何文件。

## 未解决的问题

1. **`rate` 的口径**：官方规则页 401，无法从一手来源确认热度公式。做因子只能当黑箱分。
2. **同花顺 App 榜与网页/接口榜是否同源**：无抓包证据，不做推断。
3. **`type=day` / `type=week` 的返回形态**：未实测。
4. **各热度源的重叠度**：同花顺榜 vs 东财人气榜 vs 开盘啦人气的交集比例未测，因此「换源」的代价无法量化。
5. **历史热度**：免费路径下同花顺热度**没有历史**。这是「热度前 50 尾盘买」能否被回测的**决定性瓶颈**——比取数难得多。要么长期自采（第 1 步开始攒），要么走 Tushare 6000 积分，要么先用东财历史排名代理（第 0 步）。
6. **本机出站链路**：本工作站无法直连 `10jqka.com.cn` 与 `push2.eastmoney.com`。真要做直连方案，必须先按 `src/intel/README.md` 第 36 行那套 Fake-IP 修正验证出站可达，否则实现完了在本机也跑不起来。
