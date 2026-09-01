# AkShare 的 A 股接口全景与量化价值排序（scratch）

> **日期**：2026-08-25 ｜ **核验日期**：2026-08-25
> **本机版本**：akshare **1.18.56**（`importlib.metadata`，PyPI 上传时间 2026-04-20）；**PyPI 最新 1.18.94**（2026-08-21）→ **本仓落后 38 个版本 / 4 个月**
> **用途**：回答用户诉求「引入的 AkShare 数据该用的没用起来」。给出**按数据语义**的接口全景、**对短线 A 股量化的价值排序**，以及本仓两个已知硬伤（`delist_date` 全空、无 point-in-time 财务）能否用 AkShare 补齐。
> **范围**：**只读**。除本文件外未改仓库任何文件，未 commit / push，未写库。**未联网真实调用任何 AkShare 数据接口**（不消耗第三方配额、不触发封 IP）。
> **证据分级**：
> - `E1` **本机源码**：`.venv/Lib/site-packages/akshare/**` 逐函数 `inspect.getsource` / `inspect.signature` / `inspect.getdoc`，列名取自源码里的 `temp_df.columns = [...]` / `temp_df[[...]]` / `rename(columns={...})`——**这就是生成 DataFrame 的那几行代码，比文档更硬**。
> - `E2` **官方文档**：<https://akshare.akfamily.xyz/data/stock/stock.html>（完整 HTML 3,053,635 字节全量下载后本地解析，29 个接口锚点逐一校验；reader-mode 会在 612 KB 处静默截断，本轮未用）。
> - `E3` **官方 changelog**：<https://raw.githubusercontent.com/akfamily/akshare/main/docs/changelog.md>（229,118 字节，2,842 个版本条目）+ PyPI 发布时间。
> - `E4` **本仓实测**：主 agent 2026-08-25 dbstat 实测（真实数据目录 `E:\entertainment_software\Loci\data`）与子 agent 只读代码审计（给到 `path:line`）。
> - ✗ 未取到一手来源，明确标注。
> **与既有文档的关系**：`2026-08-dragon-survivorship-and-portfolio-fragility.md` 记录了存活偏差不可测的**症状**，本文给**药方与代价**；`2026-08-ths-heat-tail-close-picker.md` 记录了 `stock_hot_rank_wc` 被静默移除，本文用 changelog 逐条**证实了「静默移除」这件事 changelog 里一个字都没有**；`src/market/README.md` 记录了 `stock_info_a_code_name` 的 py_mini_racer 崩溃，本文核对到**该函数在 1.18.56 已不再用 py_mini_racer**（见 §6.2）。

---

## 0. 一句话结论

**「该用的没用起来」这句话是对的，但真正的损失不在「少调了几个接口」，而在「有一批数据只有当天快照、你不每天存下来就永远拿不到历史」——而本仓从未存过其中任何一个。**

三条硬结论：

1. **AkShare 本机 1.18.56 暴露 403 个 `stock_*` 接口，本仓实际接入 2 个**（`stock_zh_a_hist` 日线兜底、`stock_individual_fund_flow` 资金流），且日线主源已换成通达信本地二进制。403 个里对短线真正有价值的约 70 个，其中 **21 个属于「只有当天快照、AkShare 不提供历史」**——这 21 个是本篇最重要的产出（§4）。
2. **两个已知硬伤，AkShare 能补一个半**：存活偏差**能补**（`stock_info_sh_delist` + `stock_info_sz_delist` + 退市股专用财报三接口，代价：一次性 264 只票 + 每日增量），point-in-time 财务**能补到「公告日级」而非「盘中可见时点级」**（`stock_yjbb_em.最新公告日期`、`stock_yysj_em.实际披露时间`、`stock_lrb_em/zcfz_em/xjll_em.公告日期`）。
3. **现有防线（`check_akshare_version` + `source_contract`）对 AkShare 的真实破坏模式覆盖率约 1/4**。近 12 个月 AkShare 发了 **273 个版本**（平均 1.32 天一版），**268 个是 `fix:`**，**132 个版本的标题直接点名某个 `stock_*` 接口**，涉及 **76 个不同接口**——而这一年 A 股接口**正式更名 0 次**、changelog 里**正式删除 0 次**。也就是说：**真正的破坏是「悄悄修好」与「悄悄删掉」，不是改名。**契约层只在必填列整列消失时抛错，且这个错会被 router 的 `except Exception` 吞成静默降源（`router.py:204-207`，`E4`）。

---

## 1. 方法与证据边界

| 步骤 | 做法 | 产出 |
|---|---|---|
| 接口清点 | `vars(akshare)` 全量 + `__module__.startswith("akshare")` 过滤 | 1,093 个 callable，其中 `stock_*` **403**、`index_*` 79、`macro_*` 226 |
| 签名/文档 | 逐条 `inspect.signature` + `inspect.getdoc` | 全量落 `.tmp_ak_surface.json`（临时文件，未入库） |
| **列名** | 176 个重点接口逐条 `inspect.getsource`，正则抽 `columns = [...]` / `temp_df[[...]]` / `rename(columns={…})` | 本文所有列名都来自这一步，**没有一个是猜的** |
| 引擎特征 | 全 403 个函数扫 `pageSize` / 分页循环 / `tqdm` / `time.sleep` / `requests.post` / 模块级 `py_mini_racer` | §6 的调用模式分类 |
| 文档交叉核对 | 完整 HTML 下载 + 自建 `<table>` 结构化还原，29 个接口逐字抄「限量」原文 | §2/§3 的「有无历史」列 |
| changelog | 2,842 版本条目 × PyPI 上传时间 join，取 2025-08-25 ~ 2026-08-21 窗口 | §7 的统计 |

**三条边界**：

1. **本轮零真实调用**。凡是「实际返回多少行、历史到底多深」这类只能实测的问题，本文一律标 `未实测`，不编数字。文档写了的按文档逐字引；文档没写的写「文档未见」。
2. **本机装的是 1.18.56，不是最新的 1.18.94**。§2/§3 的列名以 **1.18.56 源码**为准（这是本仓实际会跑的代码）；§7 会指出 1.18.56 → 1.18.94 之间已知会影响我们的变更。
3. 官方文档本身有 9 处自相矛盾（列数与示例对不上、目标地址复制错、默认值不在 choice 集合内），逐条列在 §7.4，遇到冲突时**以源码为准**。

---

## 2. 接口全景：按数据语义分族

> 说明：族内只列**对 A 股短线有实际意义**的接口；`_hk` / `_us` / `esg` / `macro` 等一律不列。「历史」列的口径见 §3 图例。

### 2.1 行情族

| 接口 | 语义 | 上游 | 历史深度 | 更新频率 | 反爬/限流 |
|---|---|---|---|---|---|
| `stock_zh_a_hist(symbol, period, start_date, end_date, adjust)` | 日/周/月 K + 三种复权 | 东财 `push2his…/stock/kline/get`，`ut=7eea3edc…` | 全历史（`beg`/`end` 自由） | 收盘后 | 中。逐票循环，需自行限速 |
| `stock_zh_a_daily(symbol, adjust)` | 新浪日 K + **复权因子** | 新浪 | 全历史 | 收盘后 | **高**。docstring 自带「大量抓取容易封 IP」；依赖 `py_mini_racer` |
| `stock_zh_a_hist_tx` | 腾讯日 K | `web.ifzq.gtimg.cn` | 文档写「20200101 起」 | 收盘后 | 中。1.18.73 刚修过成交量/换手率/成交额**字段语义** |
| `stock_zh_a_hist_min_em(period="1")` | **1 分钟** K | 东财 `trends2/get` | **硬上限 `ndays=5`，只有最近 5 个交易日**（`E1`，源码写死） | 盘中 | 中 |
| `stock_zh_a_hist_min_em(period="5/15/30/60")` | 5/15/30/60 分 K | 东财 `kline/get`，`beg=0&end=20500000` | 请求侧不设限，实际深度由东财服务端截断（未实测） | 盘中 | 中 |
| `stock_zh_a_hist_pre_min_em(symbol, start_time, end_time)` | **含盘前 09:00 起**的当日分时 | 东财 `push2…/trends2/get` | **只有当天** | 盘中 | 中 |
| `stock_zh_a_minute(symbol, period, adjust)` | 新浪分钟 | 新浪 | 滚动窗口 | 盘中 | **高**，`py_mini_racer`；近 12 月被修 9 次（最高频之一） |
| `stock_zh_a_spot_em()` | **全市场 A 股快照 23 列** | 东财 `clist/get`，`fs=m:0 t:6,…` | **只有当下** | 秒级 | 中。分页 `pn/pz`，akshare 自带 `sleep(0.5~1.5)` |
| `stock_bid_ask_em(symbol)` | **五档盘口**（`item`/`value` 长表） | 东财 `qt/stock/get` | **只有当下** | 秒级 | 中，逐票 |
| `stock_intraday_em(symbol)` | 当日**逐笔**（时间/成交价/手数/买卖盘性质） | 东财 `stock/details/sse` | **只有当天** | 秒级 | 中，逐票 |
| `stock_zh_a_tick_tx_js(symbol)` | 腾讯分笔 | `stock.gtimg.cn/data/index.php` | 名义历史分笔，实际只回当日 | 盘中 | 中 |
| `stock_changes_em(symbol)` | **盘口异动 22 类**（含「竞价上涨」「竞价下跌」「封涨停板」「打开涨停板」） | 东财 `push2ex/getAllStockChanges` | **只有当天** | 盘中实时 | 中 |
| `stock_cyq_em(symbol, adjust)` | 筹码分布（获利比例/平均成本/90-70 成本区间与集中度） | 东财日 K `lmt=210` + **本地 MiniRacer 跑 JS 重算** | **固定最后 90 行**（`E1`：`temp_df.iloc[-90:]`） | 收盘后 | 中 + **强制 py_mini_racer** |
| `stock_zh_index_daily_em(symbol, start, end)` | 指数日 K | 东财 | 全历史 | 收盘后 | 低 |
| `stock_zh_index_spot_em(symbol)` | 指数快照 | 东财 | 只有当下 | 秒级 | 低 |

**集合竞价：AkShare 没有专用接口。** 全包 grep「集合竞价」命中 0（`E1`）。能拿到竞价信息的只有两条：`stock_changes_em(symbol="竞价上涨"/"竞价下跌")`（东财异动分类码 `8207`/`8208`，**只有当天**）与 `stock_zh_a_hist_pre_min_em`（09:00 起的盘前分时，**只有当天**）。**竞价数据在 AkShare 侧不存在任何历史接口**——这是 §4 的第一梯队。

### 2.2 资金族

| 接口 | 语义 | 上游 | 历史深度 | 反爬/限流 |
|---|---|---|---|---|
| `stock_individual_fund_flow(stock, market)` | 个股日频主力/超大/大/中/小单净额与净占比 | 东财 `fflow/daykline/get`，`lmt=0`，**第三个 `ut=b2884a39…`** | `lmt=0` = 不限条数，实际深度由东财决定（未实测） | 中，**逐票循环** |
| `stock_individual_fund_flow_rank(indicator)` | 全市场资金流排名（今日/3/5/10 日） | 东财 `clist/get` | **只有当下** | 中 |
| `stock_market_fund_flow()` | 大盘资金流日序列（含上证/深证收盘与涨跌幅） | 东财 `fflow/daykline` | 有历史 | 低 |
| `stock_sector_fund_flow_rank(indicator, sector_type)` | 行业/概念/地域资金流排名 | 东财 | **只有当下** | 中 |
| `stock_sector_fund_flow_hist(symbol)` | 单行业历史资金流日序列 | 东财 `fflow/daykline` | 有历史 | 中，逐板块循环 |
| `stock_concept_fund_flow_hist(symbol)` | 单概念历史资金流日序列 | 东财 | 有历史 | 中，逐板块循环 |
| `stock_sector_fund_flow_summary(symbol, indicator)` | 某行业下的个股资金流 | 东财 | **只有当下** | 中 |
| `stock_main_fund_flow(symbol)` | 主力净流入排名（今日/5 日/10 日**排名值**） | 东财 | **只有当下** | 中 |
| `stock_fund_flow_individual / _concept / _industry / _big_deal` | 同花顺口径资金流 | 同花顺 | 只有当下 | **高**，`py_mini_racer` 造 `v` cookie |
| `stock_hsgt_hist_em(symbol)` | 沪深港通历史日序列（当日成交净买额/买入/卖出/累计净买/持股市值/领涨股） | 东财 datacenter | 文档示例 2014-11-17 ~ **2024-04-12** | 低 |
| `stock_hsgt_individual_em(symbol)` | **个股北向持股日序列** | 东财 | **文档逐字：「截至 20240816 的数据」——已冻结**（`E2`） | 低 |
| `stock_hsgt_stock_statistics_em(symbol, start_date, end_date)` | 每日个股北向持股统计（可指定日期区间） | 东财 datacenter | 有历史，文档标「只能获取近期的数据」 | 中 |
| `stock_hsgt_hold_stock_em(market, indicator)` | 北向持股个股排行 | 东财 | **只有当下**（列名随 `indicator` 动态变） | 中 |
| `stock_hsgt_board_rank_em(symbol, indicator)` | 北向增持板块排行 | 东财 | **只有当下** | 中 |
| `stock_hsgt_fund_min_em(symbol)` | 北向分时资金 | 东财 `kamtbs.rtmin` | **只有当天** | 中 |
| `stock_margin_detail_sse(date)` | 上交所融资融券**个股明细** | 上交所 `query.sse.com.cn` | 按日可回溯 | 低（交易所官方） |
| `stock_margin_detail_szse(date)` | 深交所两融个股明细 | 深交所 `ShowReport`（xlsx） | 按日可回溯 | 低 |
| `stock_margin_sse(start_date, end_date)` | 上交所两融汇总（区间） | 上交所 | 2001-01-06 起 | 低 |
| `stock_margin_szse(date)` | 深交所两融汇总 | 深交所 | 按日 | 低 |
| `stock_margin_account_info()` | 两融账户统计（投资者数/担保物/平均维持担保比例） | 东财 | 有历史日序列 | 低 |
| `stock_margin_ratio_pa(symbol, date)` | 两融标的名单 + 保证金比例 | **平安证券** | 按日 | 中，第三方券商站 |

> **北向资金的真实状态（`E2` + 官方文档逐字）**：全站只有 `stock_hsgt_individual_em` 一处反映了停更，限量原文「单次获取指定 symbol 的**截至 20240816** 的数据」，数据示例末行 `2024-08-16`。`stock_hsgt_hist_em` 与 `stock_hsgt_hold_stock_em` 的限量仍写「所有数据」，**文档未同步更新，具有误导性**。→ 北向在本仓的量化价值应按「**2024-08-16 之后基本失效**」计，不要当活数据源排 P0。

### 2.3 情绪与题材族

| 接口 | 语义 | 上游 | 历史深度（文档逐字） | 反爬 |
|---|---|---|---|---|
| `stock_zt_pool_em(date)` | **涨停股池** 16 列（含连板数/首末封板时间/封板资金/炸板次数/涨停统计） | 东财 `push2ex/getTopicZTPool`，`pagesize=10000` | 「单次返回指定 date 的涨停股池数据；**该接口只能获取近期的数据**」 | 中 |
| `stock_zt_pool_zbgc_em(date)` | 炸板股池 | `getTopicZBPool` | 同上「只能获取近期的数据」 | 中 |
| `stock_zt_pool_dtgc_em(date)` | 跌停股池 | `getTopicDTPool` | 同上 | 中 |
| `stock_zt_pool_strong_em(date)` | 强势股池（含「入选理由」「是否新高」） | `getTopicQSPool` | 同上 | 中 |
| `stock_zt_pool_sub_new_em(date)` | 次新股池（含开板几日/开板日期/上市日期） | `getTopicCXPool` | 同上 | 中 |
| `stock_zt_pool_previous_em(date)` | 昨日涨停股池 | `getYesterdayZTPool` | 同上 | 中 |
| `stock_lhb_detail_em(start_date, end_date)` | **龙虎榜详情**（区间查询） | 东财 datacenter `RPT_DAILYBILLBOARD_DETAILSNEW` | 有历史，区间自由 | 低 |
| `stock_lhb_stock_detail_em(symbol, date, flag)` | 个股龙虎榜买卖席位明细 | 东财 | 需先用 `stock_lhb_stock_detail_date_em` 拿有效日期 | 中，**逐票×逐日** |
| `stock_lhb_stock_detail_date_em(symbol)` | 某票所有上榜日期 | 东财 | 全历史 | 中，逐票 |
| `stock_lhb_jgmmtj_em(start_date, end_date)` | 机构买卖每日统计 | 东财 | 有历史 | 低 |
| `stock_lhb_hyyyb_em(start_date, end_date)` | 每日活跃营业部 | 东财 | 有历史 | 低 |
| `stock_lhb_stock_statistic_em(symbol)` | 个股上榜统计（近一月/三月/六月/一年） | 东财 | **只有当下的滚动统计** | 低 |
| `stock_lhb_jgstatistic_em` / `stock_lhb_traderstatistic_em` / `stock_lhb_yybph_em` / `stock_lhb_yyb_detail_em` | 机构/营业部统计与排行 | 东财 | 滚动统计 | 低 |
| `stock_lhb_*_sina`（5 个） | 新浪口径龙虎榜 | 新浪 | 有历史 | 中 |
| `stock_hot_rank_em()` | **东财人气榜 Top100** | `emappdata…/getAllCurrentList`（**POST**） | 「单次返回**当前交易日**前 100 个股票」→ **无历史** | **高**，App 私有接口 |
| `stock_hot_rank_detail_em(symbol)` | **个股人气排名历史序列**（时间/排名/证券代码/新晋粉丝/铁杆粉丝） | `getHisList` + `getHisProfileList`（POST，`yearType:"5"`） | **有历史**；文档示例 `[366 rows × 5 columns]`，2024-07-24 ~ 2025-07-24 ≈ **1 年、按自然日** | **高**，逐票 POST |
| `stock_hot_up_em()` | 飙升榜（含「排名较昨日变动」） | 东财 App | **只有当下** | 高 |
| `stock_hot_rank_detail_realtime_em(symbol)` | 个股当日排名分时变动 | 东财 App | **只有当天** | 高 |
| `stock_hot_keyword_em(symbol)` | 个股热门关键词 + 热度值 | 东财 App | **只有当下** | 高 |
| `stock_hot_search_baidu(symbol, date, time)` | 百度股市通热搜（名称/代码、涨跌幅、综合热度） | 百度 | 有 `date` 参数，深度未实测 | 中 |
| `stock_hot_follow_xq / _deal_xq / _tweet_xq` | 雪球关注/交易/讨论排行 | 雪球 | **只有当下** | 中；同族 `_xq` 接口近 12 月被修 **43 次**（见 §7） |
| `stock_comment_em()` | **千股千评全市场表**（机构参与度/综合得分/上升/目前排名/关注指数/主力成本） | 东财 datacenter | **只有当天截面** | 低 |
| `stock_comment_detail_scrd_focus_em(symbol)` | 个股「用户关注指数」日序列 | 东财 | **`pageSize=30` 且无分页循环 → 只有 30 条**（`E1`） | 低，逐票 |
| `stock_comment_detail_zlkp_jgcyd_em` / `_scrd_desire_em` / `_zhpj_lspf_em` | 机构参与度 / 市场参与意愿 / 综合评价历史评分 | 东财 | 短窗口 | 低，逐票 |
| `stock_board_concept_name_em()` | **概念板块名录 + 快照**（板块代码/涨跌幅/上涨家数/领涨股） | 东财 | **只有当下** | 低 |
| `stock_board_concept_cons_em(symbol)` | 概念板块**成分股** | 东财 | **只有当下成分**（无历史成分） | 中，逐板块 |
| `stock_board_concept_hist_em(symbol, period, start, end, adjust)` | 概念板块历史 K | 东财 | 有历史 | 中，逐板块 |
| `stock_board_industry_name_em / _cons_em / _hist_em` | 行业板块三件套 | 东财 | 同概念族 | 中 |
| `stock_board_change_em()` | **当日板块异动详情**（板块异动总次数 + 具体异动类型列表） | `push2ex/getAllBKChanges` | **只有当天** | 中 |
| `stock_board_concept_name_ths / _cons / _info / _index / _summary` | 同花顺概念族 | 同花顺 | 部分有历史 | **高**，`py_mini_racer` |
| `stock_rank_cxg_ths / cxd / lxsz / lxxd / xstp / xxtp / ljqs / ljqd / xzjp / cxfl / cxsl` | 同花顺技术选股榜（创新高/创新低/连涨/连跌/向上突破/…） | 同花顺 | **只有当下** | **高**，`py_mini_racer` |
| `stock_market_activity_legu()` | 赚钱效应分析（涨停/跌停/上涨/下跌/活跃度） | 乐咕 | **只有当下** | 中，第三方站，近 12 月修 3 次 |
| `stock_a_high_low_statistics(symbol)` | 创新高/新低股票数量 | 乐咕 | 有历史 | 中，近 12 月修 6 次 |
| `stock_a_congestion_lg()` | 大盘拥挤度 | 乐咕 | 有历史 | 中 |

### 2.4 基本面族

| 接口 | 语义 | 上游 | 历史 | 关键列（`E1` 真实列名） |
|---|---|---|---|---|
| `stock_zcfz_em(date)` / `stock_lrb_em(date)` / `stock_xjll_em(date)` | **全市场按报告期的三表精简版** | 东财 datacenter | 从 20100331 起 | 三个都含 **`公告日期`** ← PIT 的关键 |
| `stock_balance_sheet_by_report_em(symbol)` / `stock_profit_sheet_by_report_em` / `stock_cash_flow_sheet_by_report_em` | 个股三表完整版（按报告期） | 东财 F10 | 全历史 | 英文字段码，数百列 |
| `stock_*_by_yearly_em` / `_by_quarterly_em` | 按年度 / 按单季 | 东财 | 全历史 | 同上 |
| `stock_financial_abstract(symbol)` | 新浪关键指标 | 新浪 | 全历史 | 逐票 |
| `stock_financial_analysis_indicator(symbol, start_year)` | 财务分析指标 | 新浪 | 全历史 | 逐票 |
| `stock_yjbb_em(date)` | **业绩报表**（全市场按报告期） | 东财 | **从 20100331 开始**（文档逐字） | 16 列，含 **`最新公告日期`** |
| `stock_yjkb_em(date)` | 业绩快报 | 东财 | 从 20100331 开始 | 含 **`公告日期`** |
| `stock_yjyg_em(date)` | **业绩预告** | 东财 | **从 20081231 开始** | 含 `公告日期` + `报告日期` + `预告类型` + `业绩变动幅度` |
| `stock_yysj_em(symbol, date)` | **预约披露时间** | 东财 | **从 20081231 开始** | 8 列：`首次预约时间`/`一次变更日期`/`二次变更日期`/`三次变更日期`/**`实际披露时间`** |
| `stock_report_disclosure(market, period)` | 巨潮预约披露 | 巨潮 | **仅近四期**（文档逐字） | `首次预约`/`初次变更`/`二次变更`/`三次变更`/`实际披露` |
| `stock_fhps_em(date)` | **分红送配**（全市场按报告期） | 东财 | 有历史 | `送转股份-送转总比例`/`现金分红-现金分红比例`/`预案公告日`/**`股权登记日`**/**`除权除息日`**/`方案进度`/`最新公告日期`/`现金分红-股息率` |
| `stock_fhps_detail_em(symbol)` / `stock_dividend_cninfo(symbol)` | 个股分红明细 | 东财 / 巨潮 | 全历史 | 巨潮版依赖 `py_mini_racer` |
| `stock_zh_a_gdhs(symbol)` | **股东户数**（全市场，`symbol` 传季度末如 `20230930`） | 东财 | 按季度可回溯 | 16 列，含 `股东户数-增减比例`/`户均持股市值`/`公告日期` |
| `stock_zh_a_gdhs_detail_em(symbol)` | 个股股东户数全序列 | 东财 | 全历史 | 15 列，含 `股本变动`/`股本变动原因` |
| `stock_gdfx_free_top_10_em(symbol, date)` | **十大流通股东** | 东财 F10 | 按报告期 | `名次`/`股东名称`/`股东性质`/`股份类型`/`持股数`/`占总流通股本持股比例`/`增减`/`变动比率` |
| `stock_gdfx_top_10_em` / `stock_gdfx_free_holding_*_em`（10 个） | 十大股东 / 股东持股分析、变动、统计、协同 | 东财 | 按报告期 | — |
| `stock_jgdy_tj_em(date)` | **机构调研统计** | 东财 | 按日回溯 | `公告日期`/`接待日期`/`接待地点`/`接待方式`/`接待人员`/`接待机构数量` |
| `stock_jgdy_detail_em(date)` | 机构调研详细 | 东财 | 按日回溯 | `调研日期`/`调研机构`/`机构类型`/`调研人员` |
| `stock_restricted_release_detail_em(start_date, end_date)` | **限售解禁明细** | 东财 | 区间自由，**含未来解禁** | `解禁时间`/`实际解禁数量`/`占解禁前流通市值比例`/`解禁前一交易日收盘价`/`解禁前20日涨跌幅`/**`解禁后20日涨跌幅`**/`限售股类型` |
| `stock_restricted_release_queue_em(symbol)` | 个股解禁批次 | 东财 | 全历史 + 未来 | `pageSize=500` 无分页循环 |
| `stock_repurchase_em()` | **股票回购** | 东财 | 全量（有分页循环） | `计划回购价格区间`/`计划回购数量区间-下限/上限`/`占公告前一日总股本比例-下限/上限`/`回购起始时间`/`实施进度`/`已回购股份数量`/`已回购金额`/`最新公告日期` |
| `stock_dzjy_mrmx(symbol, start_date, end_date)` | **大宗交易每日明细** | 东财 | 区间自由 | `成交价`/**`折溢率`**/`成交额/流通市值`/**`买方营业部`**/**`卖方营业部`** |
| `stock_dzjy_mrtj(start_date, end_date)` | 大宗交易每日统计 | 东财 | 区间自由 | `成交笔数`/`成交总额/流通市值` |
| `stock_ggcg_em(symbol)` | 高管/股东增减持 | 东财 | 有历史 | `持股变动信息-变动数量`/`变动开始日`/`变动截止日`/`变动后持股情况-*` |
| `stock_share_hold_change_sse / _szse / _bse` | 董监高股份变动（交易所口径） | 三所 | 有历史 | `变动日期`/`本次变动平均价格`/`变动原因` |
| `stock_zh_a_gbjg_em(symbol)` | **股本结构变更史** | 东财 F10 | 全历史 | `变更日期`/`总股本`/`已流通股份`/`已上市流通A股`/`变动原因` |
| `stock_value_em(symbol)` | 个股估值日序列 | 东财 | 有历史 | `PE(TTM)`/`PE(静)`/`市净率`/`PEG值`/`市现率`/`市销率` |
| `stock_profit_forecast_em / _ths` | 盈利预测 | 东财 / 同花顺 | 滚动 | — |
| `stock_research_report_em(symbol)` | 个股研报 | 东财 | 有历史 | `机构`/`日期`/`东财评级` |
| `stock_notice_report(symbol, date)` / `stock_zh_a_disclosure_report_cninfo(...)` | 公告大全 / 巨潮信息披露 | 东财 / 巨潮 | 按日/区间 | 巨潮版列：`代码`/`简称`/`公告标题`/`公告时间` |

### 2.5 指数与基准族

| 接口 | 语义 | 上游 | 历史 | 备注 |
|---|---|---|---|---|
| `stock_zh_index_daily_em(symbol, start, end)` | 指数日 K（`sh`/`sz`/`csi` 前缀） | 东财 | 全历史 | 列名是**英文** `date/open/close/high/low/volume/amount` |
| `stock_zh_index_daily(symbol)` | 新浪指数日 K | 新浪 | 全历史 | `py_mini_racer` |
| `stock_zh_index_spot_em(symbol)` | 指数快照 | 东财 | 当下 | — |
| `stock_zh_index_hist_csindex(symbol, start, end)` | 中证指数历史 | 中证 | 有历史 | docstring 自注「**只有收盘价，正常情况下不应使用该接口**」 |
| `stock_zh_index_value_csindex(symbol)` | 指数估值（市盈率 1/2、股息率 1/2） | 中证 | 有历史 | — |
| `index_stock_cons_csindex(symbol)` | 指数成分（中证 oss） | 中证 | **只有最新** | — |
| `index_stock_cons_weight_csindex(symbol)` | **指数成分权重** | 中证 | **只有最新一期** | 列含 `日期`/`成分券代码`/`权重` |
| `index_stock_cons(symbol)` | 指数成分（新浪） | 新浪 | 只有最新 | — |
| `index_stock_info()` | 指数列表 | 聚宽字典页 | 静态 | `index_code`/`display_name`/`publish_date` |
| **`stock_industry_clf_hist_sw()`** | **申万个股行业分类变动历史** | 申万 `StockClassifyUse_stock.xls` | **全历史，带 `start_date`（计入日期）** | **这是唯一 PIT 友好的行业分类**；列：`symbol`/`start_date`/`industry_code`/`update_time` |
| `index_component_sw(symbol)` | 申万指数成分 + **`计入日期`** | 申万 | 带计入日期 | 可近似 PIT 成分 |
| `index_hist_sw(symbol, period)` | 申万指数历史 | 申万 | 全历史 | — |
| `sw_index_first_info()` / `sw_index_second_info` / `_third_info` | 申万一/二/三级分类 + 估值 | 乐咕 | 当下 | — |
| **`stock_industry_change_cninfo(symbol, start_date, end_date)`** | **行业分类变更历史（多标准）** | 巨潮 | **带 `变更日期`** | 列：`机构名称`/`证券代码`/`新证券简称`/**`变更日期`**/`分类标准编码`/`分类标准`/`行业编码`/`行业门类`/`行业次类`/`行业大类`/`行业中类`；**`py_mini_racer`** |
| `stock_industry_category_cninfo(symbol)` | 8 种行业分类标准（证监会/巨潮/申万/新财富/国资委/…） | 巨潮 | 当下 | `py_mini_racer` |
| `stock_board_industry_name_em()` | 东财行业分类 + 快照 | 东财 | 当下 | — |
| `stock_classify_sina(symbol)` / `stock_sector_detail(sector)` | 新浪申万/概念/地域分类 | 新浪 | 当下 | — |

### 2.6 元数据族

| 接口 | 语义 | 上游 | 历史 | 真实列名（`E1`/`E2`） |
|---|---|---|---|---|
| `stock_info_sh_name_code(symbol)` | 上交所股票列表 | 上交所 | 当下 | `证券代码`/`证券简称`/`证券全称`/`公司简称`/`公司全称`/**`上市日期`** |
| `stock_info_sz_name_code(symbol)` | 深交所股票列表 | 深交所 xlsx | 当下 | `板块`/`A股代码`/`A股简称`/**`A股上市日期`**/`A股总股本`/`A股流通股本`/`所属行业` |
| `stock_info_bj_name_code()` | 北交所股票列表 | 北交所 | 当下 | `证券代码`/`证券简称`/**`上市日期`**/`总股本`/`流通股本`/`所属行业`/`地区`/`券商`/`报告日期` |
| `stock_info_a_code_name()` | 沪深京 A 股列表（**1.18.56 已改为拼上面三个所**，`@lru_cache`） | 三所 | 当下 | `code`/`name` |
| **`stock_info_sh_delist(symbol)`** | **上交所终止上市公司** | 上交所 `COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L`，`COMPANY_STATUS=3` | 全量 | `公司代码`/`公司简称`/`上市日期`/**`暂停上市日期`**（源码把 `DELIST_DATE` 重命名成「暂停上市日期」，**名字是错的，值是退市日**）。文档示例 `[114 rows × 4 columns]` |
| **`stock_info_sz_delist(symbol)`** | **深交所终止/暂停上市公司** | 深交所 `ShowReport` xlsx | 全量 | `证券代码`/`证券简称`/`上市日期`/**`终止上市日期`**。文档示例 `[150 rows × 4 columns]` |
| `stock_info_change_name(symbol)` | 新浪曾用名 | 新浪 | 全历史 | **英文列 `index`/`name`，无日期** |
| `stock_info_sz_change_name(symbol)` | **深交所名称变更（带日期）** | 深交所 | 全历史，示例 1992-02-28 起 `[1619 rows × 5]` | `变更日期`/`证券代码`/`证券简称`/`变更前全称`/`变更后全称`。**只有深市，沪市无对应接口** |
| `stock_zh_a_st_em()` | **风险警示板快照** | 东财 `clist` | **只有当天** | 17 列行情 |
| `stock_zh_a_stop_em()` | **两网及退市板快照**（⚠ 名字像「停牌」，实为老三板） | 东财 `clist` | **只有当天** | 17 列行情 |
| `stock_staq_net_stop()` | 两网及退市**名录** | 东财 | 只有当下 | 仅 `序号`/`代码`/`名称`，**无退市日期**，示例 204 行 |
| **`stock_tfp_em(date)`** | **停复牌信息（按日）** | 东财 datacenter `RPT_CUSTOM_SUSPEND_DATA_INTERFACE` | **按日可回溯** | `序号`/`代码`/`名称`/`停牌时间`/`停牌截止时间`/`停牌期限`/`停牌原因`/`所属市场`/`预计复牌时间`（源码另抓了 `停牌开始日期` 但在 select 里被丢掉） |
| `stock_new_a_spot_em()` | 新股快照（含 `上市日期`） | 东财 | 当下 | 24 列 |
| `stock_zh_a_new_em()` / `stock_zh_a_new()` | 新股行情 | 东财 / 新浪 | 当下 | — |
| `stock_xgsglb_em(symbol)` | **新股申购与中签** | 东财 | 有历史 | `申购代码`/`发行价格`/`发行市盈率`/`申购日`/`上市首日-上市日`/`中签率` |
| `stock_ipo_summary_cninfo(symbol)` | IPO 概况 | 巨潮 | 有历史 | `py_mini_racer` |
| `stock_dxsyl_em()` | 打新收益率 | 东财 | 有历史 | `网上-发行中签率`/`超额认购倍数`/`开盘溢价`/`首日涨幅` |
| `tool_trade_date_hist_sina()` | **交易日历** | 新浪 `klc_td_sh.txt` | 全历史 | **依赖 `py_mini_racer`**（`E1`：`tool/trade_date_hist.py:28`） |

---

## 3. 对短线 A 股量化的价值排序（穷举表）

**「有无历史」列图例（这是本表最重要的一列）**：

| 代码 | 含义 |
|---|---|
| `H全` | 接口自带 `date`/`start_date`，可任意回溯，历史可回测 |
| `H窗` | 有历史但只有**固定滚动窗口**（条数/天数写死在源码或文档里） |
| `H近` | 官方文档逐字写「只能获取近期的数据」，**深度无承诺、可能随时缩短** |
| `H冻` | 有历史但**已停止更新** |
| `S今` | **只有当天/当下快照，AkShare 不提供任何历史 → 不自己存就永远拿不到** |
| `S期` | 只有最新一期截面（成分/权重/名录），无历史版本 |

**优先级口径**：P0 = 短线策略/风控直接依赖，缺了会做错决策；P1 = 显著增益但可延后；P2 = 有用但边际低或有更好替代。

| # | 接口 | 数据语义 | 能支撑什么因子 / 什么风控 | **有无历史** | 稳定性风险 | 优先级 |
|---:|---|---|---|:---:|---|:---:|
| 1 | `stock_zt_pool_em` | 涨停股池（连板数/首末封板时间/封板资金/炸板次数） | **连板高度、首板时点、封单强度、龙头识别**；风控：涨停不可买入判定 | **`H近`** | 中；`data=None` 时**静默返回空 DF**，取不到旧日期不会报错 | **P0** |
| 2 | `stock_zt_pool_zbgc_em` | 炸板股池 | **炸板率（情绪温度核心指标）**、炸板后次日反包 | **`H近`** | 同上 | **P0** |
| 3 | `stock_zt_pool_previous_em` | 昨日涨停池（昨日连板数/昨日封板时间） | **昨涨停今日溢价（情绪最直接的读数）** | **`H近`** | 同上 | **P0** |
| 4 | `stock_zt_pool_dtgc_em` | 跌停股池（封单资金/连续跌停/开板次数） | 恐慌度、连续跌停出逃风控 | **`H近`** | 同上 | **P0** |
| 5 | `stock_zt_pool_strong_em` | 强势股池（入选理由/是否新高/量比） | 准涨停梯队、强势股扩散 | **`H近`** | 同上 | P1 |
| 6 | `stock_zt_pool_sub_new_em` | 次新股池（开板几日/开板日期/上市日期） | 次新炒作强度、开板后节奏 | **`H近`** | 同上 | P1 |
| 7 | `stock_changes_em` | 盘口异动 22 类（含竞价上涨/下跌、封涨停板、打开涨停板） | **盘中触发信号、竞价异动、炸板实时捕捉** | **`S今`** | 中 | **P0** |
| 8 | `stock_zh_a_hist_pre_min_em` | 含 09:00 起盘前分时（**竞价唯一入口**） | **集合竞价量价、高开缺口、竞价抢筹** | **`S今`** | 中 | **P0** |
| 9 | `stock_zh_a_spot_em` | 全市场快照 23 列（含量比/涨速/5 分钟涨跌/换手/市值） | **盘中排序、涨速榜、量比筛选**；风控：市值/换手门槛 | **`S今`** | 中 | **P0** |
| 10 | `stock_comment_em` | 千股千评（机构参与度/综合得分/目前排名/关注指数/主力成本） | **注意力代理、机构参与度因子** | **`S今`** | 低 | **P0** |
| 11 | `stock_hot_rank_em` | 东财人气榜 Top100 | 注意力峰值、散户拥挤 | **`S今`**（文档：当前交易日前 100） | **高**，App 私有 POST | **P0** |
| 12 | `stock_hot_rank_detail_em` | 个股人气排名历史 + 新晋/铁杆粉丝占比 | **注意力趋势、粉丝结构变化** | **`H窗`**（示例 366 自然日 ≈ 1 年） | **高**，逐票 POST | **P0** |
| 13 | `stock_hot_up_em` | 飙升榜（排名较昨日变动） | **注意力斜率（比绝对排名更有效）** | **`S今`** | 高 | P1 |
| 14 | `stock_lhb_detail_em` | 龙虎榜详情（区间） | **游资参与度、席位净买、上榜原因分类** | **`H全`** | 低 | **P0** |
| 15 | `stock_lhb_stock_detail_em` | 个股席位买卖明细 | **游资身份识别、一日游 vs 接力** | **`H全`**（需先取日期表） | 中，逐票×逐日 | P1 |
| 16 | `stock_lhb_jgmmtj_em` | 机构买卖每日统计 | 机构专用席位净买 | **`H全`** | 低 | P1 |
| 17 | `stock_lhb_hyyyb_em` | 每日活跃营业部 | 知名游资营业部活跃度 | **`H全`** | 低 | P1 |
| 18 | `stock_lhb_stock_statistic_em` | 个股上榜统计（滚动） | 上榜频次 | **`S今`**（滚动统计） | 低 | P2 |
| 19 | `stock_individual_fund_flow` | 个股日频五档资金流 | **主力净流入因子、超大单占比** | **`H全`**（`lmt=0`） | 中，**逐票循环** | **P0**（已接入） |
| 20 | `stock_individual_fund_flow_rank` | 全市场资金流排名 | 当日主力流入排序 | **`S今`** | 中 | P1 |
| 21 | `stock_market_fund_flow` | 大盘资金流日序列 | 市场级择时、仓位控制 | **`H全`** | 低 | P1 |
| 22 | `stock_sector_fund_flow_rank` | 行业/概念/地域资金流排名 | **板块轮动、题材资金聚集** | **`S今`** | 中 | **P0** |
| 23 | `stock_sector_fund_flow_hist` | 单行业历史资金流 | 板块资金持续性 | **`H全`** | 中，逐板块 | P1 |
| 24 | `stock_concept_fund_flow_hist` | 单概念历史资金流 | 题材资金持续性 | **`H全`** | 中，逐板块 | P1 |
| 25 | `stock_main_fund_flow` | 主力净流入**排名值**（今日/5/10 日） | 排名变化率 | **`S今`** | 中 | P2 |
| 26 | `stock_hsgt_hist_em` | 北向历史日序列 | 外资择时 | **`H冻`**（文档示例止于 2024-04-12） | 低 | P2 |
| 27 | `stock_hsgt_individual_em` | 个股北向持股日序列 | 外资个股持仓变动 | **`H冻`**（文档逐字「截至 20240816」） | 低 | P2 |
| 28 | `stock_hsgt_stock_statistics_em` | 每日个股北向统计（区间） | 同上 | **`H近`** | 中 | P2 |
| 29 | `stock_hsgt_hold_stock_em` | 北向持股排行 | — | **`S今`**（列名随 `indicator` 变） | 中 | P2 |
| 30 | `stock_hsgt_fund_min_em` | 北向分时 | 盘中外资流向 | **`S今`** | 中 | P2 |
| 31 | `stock_margin_detail_sse` | 上交所两融个股明细（按日） | **融资余额变动、杠杆拥挤** | **`H全`** | 低（交易所官方） | **P0** |
| 32 | `stock_margin_detail_szse` | 深交所两融个股明细（按日） | 同上 | **`H全`** | 低 | **P0** |
| 33 | `stock_margin_sse` / `stock_margin_szse` | 两融市场汇总 | 市场杠杆水位 | **`H全`**（沪市 2001-01-06 起） | 低 | P1 |
| 34 | `stock_margin_account_info` | 两融账户统计（平均维持担保比例） | **系统性去杠杆风控** | **`H全`** | 低 | P1 |
| 35 | `stock_margin_ratio_pa` | 两融标的名单 + 保证金比例 | 可融标的过滤 | **`H全`**（按日） | 中，平安证券站 | P2 |
| 36 | `stock_zh_a_hist` | 日/周/月 K + 复权 | 全部量价因子基座 | **`H全`** | 中 | **P0**（已接入，降级源） |
| 37 | `stock_zh_a_hist_min_em(period="1")` | 1 分钟 K | 分钟级择时、尾盘 14:50 判定 | **`H窗`：`ndays=5` 写死** | 中 | **P0** |
| 38 | `stock_zh_a_hist_min_em(period="5")` | 5 分钟 K | 同上 | **`H窗`**（服务端截断，未实测） | 中 | P1 |
| 39 | `stock_bid_ask_em` | 五档盘口 | **委比、买卖压力、封单厚度** | **`S今`** | 中，逐票 | **P0** |
| 40 | `stock_intraday_em` | 当日逐笔（含买卖盘性质） | **主动买卖比、大单拆分** | **`S今`** | 中，逐票 | P1 |
| 41 | `stock_cyq_em` | 筹码分布（获利比例/平均成本/90-70 集中度） | **套牢盘、筹码集中度、成本支撑** | **`H窗`：固定最后 90 行** | 中 + **强制 `py_mini_racer`** | **P0** |
| 42 | `stock_board_concept_name_em` | 概念板块名录 + 快照 | 题材涨幅排序 | **`S今`** | 低 | **P0** |
| 43 | `stock_board_concept_cons_em` | 概念板块成分股 | **股→题材映射（做题材因子的前提）** | **`S期`**（无历史成分） | 中，逐板块 | **P0** |
| 44 | `stock_board_concept_hist_em` | 概念板块历史 K | 题材动量 | **`H全`** | 中 | P1 |
| 45 | `stock_board_industry_name_em` | 行业板块名录 + 快照 | 行业轮动 | **`S今`** | 低 | P1 |
| 46 | `stock_board_industry_cons_em` | 行业成分 | 行业中性化 | **`S期`** | 中 | P1 |
| 47 | `stock_board_industry_hist_em` | 行业板块历史 K | 行业动量 | **`H全`** | 中 | P1 |
| 48 | `stock_board_change_em` | 当日板块异动详情 | **题材盘中发酵监测** | **`S今`** | 中 | P1 |
| 49 | `stock_comment_detail_scrd_focus_em` | 个股用户关注指数序列 | 注意力时序 | **`H窗`：`pageSize=30` 无分页 → 30 条** | 低，逐票 | P1 |
| 50 | `stock_rank_cxg_ths` 等 11 个 | 同花顺技术选股榜 | 创新高/连涨/突破 等形态池 | **`S今`** | **高**，`py_mini_racer` | P2（本地 K 线可自算） |
| 51 | `stock_market_activity_legu` | 赚钱效应（涨停/跌停/活跃度） | **市场宽度、情绪总温度** | **`S今`** | 中，第三方站，近 12 月修 3 次 | P1 |
| 52 | `stock_a_high_low_statistics` | 创新高/新低数量 | 市场宽度 | **`H全`** | 中，近 12 月修 6 次 | P1 |
| 53 | `stock_a_congestion_lg` | 大盘拥挤度 | 顶部风控 | **`H全`** | 中 | P2 |
| 54 | `stock_yjyg_em` | 业绩预告 | **预增/预亏事件、爆雷风控** | **`H全`（20081231 起）** | 低 | **P0** |
| 55 | `stock_yjbb_em` | 业绩报表 + **`最新公告日期`** | **PIT 财务的公告日锚点** | **`H全`（20100331 起）** | 低 | **P0** |
| 56 | `stock_yysj_em` | 预约披露 + **`实际披露时间`** | **PIT 可见性时点（本篇最关键的一列）** | **`H全`（20081231 起）** | 低；1.18.66 刚修过 | **P0** |
| 57 | `stock_zcfz_em` / `stock_lrb_em` / `stock_xjll_em` | 全市场三表精简版 + **`公告日期`** | **全市场 PIT 财务基座** | **`H全`（20100331 起）** | 低 | **P0** |
| 58 | `stock_balance_sheet_by_report_em` 等 3 个 | 个股三表完整版 | 精细基本面 | **`H全`** | 中，逐票，数百英文列 | P1 |
| 59 | `stock_fhps_em` | 分红送配（含股权登记日/除权除息日） | **除权日风控、复权校验** | **`H全`** | 低 | **P0** |
| 60 | `stock_zh_a_gdhs` | 全市场股东户数（按季） | **筹码集中度（户数减少 = 集中）** | **`H全`（按季度末）** | 低 | P1 |
| 61 | `stock_zh_a_gdhs_detail_em` | 个股股东户数全序列 | 同上，时序更细 | **`H全`** | 低，逐票 | P1 |
| 62 | `stock_gdfx_free_top_10_em` | 十大流通股东 | 机构/游资持仓、席位穿透 | **`H全`（按报告期）** | 中，逐票×逐期 | P1 |
| 63 | `stock_jgdy_tj_em` | 机构调研统计（接待机构数量） | **调研热度事件因子** | **`H全`（按日）** | 低 | P1 |
| 64 | `stock_jgdy_detail_em` | 机构调研详细 | 调研机构身份 | **`H全`（按日）** | 低 | P2 |
| 65 | `stock_restricted_release_detail_em` | 限售解禁明细（**含未来**） | **解禁前后风控（`解禁后20日涨跌幅` 是未来函数，回测必须剔除）** | **`H全` + 未来** | 低 | **P0** |
| 66 | `stock_repurchase_em` | 股票回购（实施进度/已回购金额） | 回购托底事件 | **`H全`**（有分页循环） | 低 | P1 |
| 67 | `stock_dzjy_mrmx` | 大宗交易明细（折溢率/买卖营业部） | **折价大宗 = 减持信号；机构专用席位承接** | **`H全`** | 低；`pageSize=5000` **无分页循环** | **P0** |
| 68 | `stock_dzjy_mrtj` | 大宗交易每日统计 | 大宗成交总额/流通市值 | **`H全`** | 低；同样无分页 | P1 |
| 69 | `stock_ggcg_em` | 高管/股东增减持 | **减持事件风控** | **`H全`** | 低 | P1 |
| 70 | `stock_zh_a_gbjg_em` | 股本结构变更史 | **流通股本时序（算换手率的正确分母）** | **`H全`** | 中；1.18.56 有**分页截断 bug**，1.18.73 才修（`pageSize=20` 无循环） | P1 |
| 71 | `stock_value_em` | 个股估值日序列（PE/PB/PEG/PS/PCF） | 估值因子 | **`H全`** | 低，逐票 | P1 |
| 72 | `stock_zh_index_daily_em` | 指数日 K | **基准、超额收益、市场状态** | **`H全`** | 低 | **P0** |
| 73 | `stock_zh_index_spot_em` | 指数快照 | 盘中市场状态 | **`S今`** | 低 | P1 |
| 74 | `index_stock_cons_weight_csindex` | 指数成分权重 | 基准复制、成分内选股 | **`S期`（只有最新一期）** | 中 | P1 |
| 75 | **`stock_industry_clf_hist_sw`** | **申万个股行业分类变动史（带计入日期）** | **PIT 行业中性化（唯一正解）** | **`H全`** | 中（申万站 xls 直下） | **P0** |
| 76 | `stock_industry_change_cninfo` | 行业分类变更史（多标准，带变更日期） | PIT 行业（多口径） | **`H全`** | 中 + **`py_mini_racer`** | P1 |
| 77 | `index_component_sw` | 申万指数成分 + 计入日期 | 近似 PIT 成分 | **`H全`（带计入日期）** | 中 | P1 |
| 78 | `stock_info_sh_name_code` / `_sz_` / `_bj_` | 三所股票列表 + 上市日期 | 股票池、上市日过滤 | **`S今`** | 低（交易所官方）；`_sh_` 近 12 月修 6 次 | **P0**（已接入） |
| 79 | **`stock_info_sh_delist`** | **上交所终止上市名单 + 退市日** | **存活偏差修复（沪市）** | **`H全`（全量名录）** | 低；`pageHelp.pageSize=500` 单页 | **P0** |
| 80 | **`stock_info_sz_delist`** | **深交所终止上市名单 + 终止上市日期** | **存活偏差修复（深市）** | **`H全`** | 低 | **P0** |
| 81 | `stock_info_sz_change_name` | 深交所名称变更（带日期） | **历史 ST 状态还原（深市）** | **`H全`（1992 起）** | 低 | **P0** |
| 82 | `stock_info_change_name` | 新浪曾用名（**无日期**） | 只能判「曾经叫过什么」 | **`H全` 但无时间戳** | 中 | P2 |
| 83 | `stock_zh_a_st_em` | 风险警示板快照 | **当日 ST 名单** | **`S今`** | 中 | **P0** |
| 84 | `stock_tfp_em` | 停复牌信息（按日） | **停牌风控、复牌套利** | **`H全`（按日）** | 低 | **P0** |
| 85 | `stock_staq_net_stop` / `stock_zh_a_stop_em` | 两网及退市名录/行情 | 退市后交易状态 | **`S今`**，且**无退市日期** | 中 | P2 |
| 86 | `stock_xgsglb_em` | 新股申购与中签 | 打新、次新股票池 | **`H全`** | 低 | P1 |
| 87 | `stock_new_a_spot_em` | 新股快照（含上市日期） | 次新池 | **`S今`** | 中 | P1 |
| 88 | `tool_trade_date_hist_sina` | 交易日历 | **一切时序对齐的前提** | **`H全`** | 中 + **`py_mini_racer`** | **P0** |
| 89 | `stock_balance_sheet_by_report_delisted_em` 等 3 个 | **已退市股票三表** | **存活偏差下的基本面补齐** | **`H全`（逐票）** | 中，逐票，**319/203/252 列全英文** | P1 |
| 90 | `stock_zh_a_daily` | 新浪日 K + 复权因子 | 复权因子交叉校验 | **`H全`** | **高**（自注「容易封 IP」）+ `py_mini_racer` | P2 |

**统计**：`H全` 45 项、`H窗` 6 项、`H近` 7 项、`H冻` 2 项、`S今` **21 项**、`S期` 3 项。**没有一行留空。**

---

## 4. ★ 必须自己天天留存，否则永远拿不到历史（本篇核心）

**判定标准**：AkShare 侧**没有任何参数能取到过去某一天的这份数据**（或官方文档明写「只能获取近期」、深度无承诺）。这批数据的历史**只能由我们自己每天落盘产生**——这正好接上用户诉求 3「加密留存 30-60 天」。

**本仓当前的留存能力（`E4`，主 agent 2026-08-25 dbstat 实测）**：
- `market.db` **5,740.2 MB**，`quotes_daily` 16,966,403 行（1990-12-19 ~ 2026-08-25）——**只有日 K**。
- **分钟线不落库**（`GET /api/market/minute/{code}` 明确不写 `market.db`），live 只有进程内 3-5 秒 TTL 缓存 → **实时/盘中数据留存能力为零**。
- `intel_snapshots` 仅 15.1 MB（热度榜快照，是目前**唯一**在做快照留存的东西）。
- 溯源审计（`receipts` + `attempts` + 其索引 + `idx_quotes_receipt`）合计 **2,569 MB = 全库 44.8%**——**近一半磁盘花在证明「我什么时候抓的」，却一天都没存过下面这 21 类不可回溯的数据**。这是本仓当前最不划算的存储配置。
- 依赖里有 **`pyzipper`**（AES 加密 zip），没有 `scipy`/`statsmodels`/`sklearn`——**加密留存的技术前提已具备，缺的是决定存什么**。

### 4.1 第一梯队：不存 = 该类策略永久不可回测（P0，必须今天就开始存）

| 排序 | 接口 | 为什么不可替代 | 建议留存粒度 | 日增量量级（估） |
|---:|---|---|---|---|
| **1** | `stock_zh_a_hist_pre_min_em`（09:00–09:30 段） | **集合竞价在 AkShare 全库没有第二个入口**（全包 grep「集合竞价」= 0）。竞价量、竞价高开、竞价撤单形态是短线最强的隔夜信息载体，一旦当天没抓，**任何数据源都补不回来**（东财 `trends2` 的 `ndays` 上限是 5） | 每交易日 09:25 与 09:30 各一次，全市场或自选池 | 全市场逐票 → 配额敏感，先存自选池 + 涨停池成员 |
| **2** | `stock_changes_em`（22 类，重点 `竞价上涨`/`竞价下跌`/`封涨停板`/`打开涨停板`/`火箭发射`/`大笔买入`） | **盘口异动是唯一的免费「盘中事件流」**。炸板的**发生时刻**、封板的**反复次数**，日 K 完全看不见 | 盘中每 1–3 分钟轮询全部 22 类（**单次全市场，不逐票**） | 单类几百行，22 类合计每日数万行，压缩后极小 |
| **3** | `stock_zh_a_spot_em` | 23 列全市场截面（量比/涨速/5 分钟涨跌/振幅/换手/双市值）。**日 K 无法还原盘中任一时刻的横截面排序**；尾盘策略（本仓已有多篇 14:50 研究）没有它就只能拿收盘价代理 | 每日至少 09:35 / 11:30 / 14:00 / **14:50** / 14:57 五个断面 | 5,500 行 × 23 列 × 5 次 ≈ 每日 2–3 MB 原始，压缩后 < 500 KB |
| **4** | `stock_hot_rank_em` + `stock_hot_up_em` | 文档逐字「**当前交易日**前 100 个」。`stock_hot_rank_detail_em` 虽有约 1 年历史，但**只有排名、没有榜单构成**，也**没有飙升榜的「排名较昨日变动」**。本仓 `intel_snapshots` 已在存热度榜——**这是唯一做对的一件事，应扩展而不是缩减** | 每日 open/close 两档（现状）→ 建议加 14:50 一档 | 每次 100 行，可忽略 |
| **5** | `stock_comment_em` | 千股千评是**全市场级**的 `机构参与度` + `综合得分` + `目前排名` + `关注指数` + `主力成本`，东财**不提供任何历史查询**。`stock_comment_detail_scrd_focus_em` 只能逐票取 30 条且只有「用户关注指数」一列 | 每日收盘后 1 次（全市场单表） | 5,500 行 × 十几列，压缩后约 200 KB/日 |
| **6** | `stock_bid_ask_em` | 五档盘口的**封单厚度/委比**是判断「封板是否真实」的核心，`stock_zt_pool_em` 的 `封板资金` 只是聚合值 | 盘中对涨停池 + 自选池逐票（**配额敏感，不要全市场**） | 与池子大小成正比 |
| **7** | `stock_sector_fund_flow_rank` + `stock_board_concept_name_em` + `stock_board_change_em` | 板块/概念的**当日**资金流排名与异动次数。虽然 `stock_sector_fund_flow_hist` 有历史，但它是**逐板块**取，且**没有「排名」这个横截面信息**；概念板块的**成分与名录本身也会变**，不存就无法还原「当时这个概念里有哪些票」 | 每日收盘后各 1 次 | 几百行，极小 |

### 4.2 第二梯队：不存会显著削弱（P1）

| 排序 | 接口 | 说明 |
|---:|---|---|
| 8 | `stock_board_concept_cons_em` / `stock_board_industry_cons_em` | **概念/行业成分只有当下**。做题材因子必须知道「2024 年 3 月这个概念里有哪些票」，东财不提供。每周存一次全量成分即可（约 400 概念 × 逐板块调用，配额敏感） |
| 9 | `stock_zh_a_st_em` | ST 名单只有当天。历史 ST 状态目前只能靠 `stock_info_sz_change_name`（**仅深市**）反推——沪市**无解**，只能自己每天存。这直接关系到本仓已确认的「按当前名称排除 ST 是剔掉赚钱的票」这个结论能否被正确重做 |
| 10 | `stock_individual_fund_flow_rank` / `stock_main_fund_flow` | 资金流的**横截面排名**只有当下；逐票历史虽有，但每天对 5,500 只票循环取历史是不现实的配额消耗，存排名表是更经济的方案 |
| 11 | `stock_hsgt_hold_stock_em` / `stock_hsgt_board_rank_em` | 北向持股排行只有当下（且北向本身已在 2024-08 后基本失效，优先级下调） |
| 12 | `index_stock_cons_weight_csindex` | 指数成分权重只有最新一期。做基准复制或成分内选股必须有历史成分，中证不提供 |
| 13 | `stock_market_activity_legu` | 赚钱效应只有当下。可用 `stock_zt_pool_*` 自算替代一部分，但「活跃度」这个乐咕自有口径无法复现 |
| 14 | `stock_rank_*_ths`（11 个） | 同花顺技术选股榜只有当下。**但本地有全量日 K，绝大部分形态可自算**——因此排在末位，除非要复现同花顺口径 |

### 4.3 「看起来有历史、其实是滚动窗口」的陷阱清单（同样需要自存）

| 接口 | 表面 | 实际（`E1`/`E2` 硬证据） | 后果 |
|---|---|---|---|
| `stock_zt_pool_em` 及 5 个兄弟 | 有 `date` 参数，像是全历史 | 文档逐字「**该接口只能获取近期的数据**」；**全站 grep「历史数据从」= 0 次、「20200101」7 次全部属于别的接口** | **不要假设能回溯到 2020**。取不到时 `data_json["data"] is None` → **静默返回空 DataFrame**，回测会以为「那天没有涨停股」。**这是最危险的一条** |
| `stock_zh_a_hist_min_em(period="1")` | 有 `start_date`/`end_date` | 源码 `"ndays": "5"` 写死，start/end 只是**本地过滤** | 传 2024 年的日期不会报错，只会返回空或最近 5 天 |
| `stock_cyq_em` | 像是全历史筹码 | 源码 `lmt=210` + `temp_df.iloc[-90:]` | **固定 90 行**，且是**本地 MiniRacer 跑 JS 算出来的**，不是东财官方值 |
| `stock_comment_detail_scrd_focus_em` | 像是全序列 | `pageSize=30` 且**无分页循环** | 只有 30 条 |
| `stock_hot_rank_detail_em` | `yearType:"5"` 像是 5 年 | 文档示例 `[366 rows × 5]`，2024-07-24 ~ 2025-07-24 | 实际约 1 年，且按**自然日**不是交易日 |
| `stock_hsgt_individual_em` | 限量写「所有数据」 | 文档另一处逐字「**截至 20240816**」 | 已冻结，不是活数据 |
| `stock_report_disclosure` | 像是全历史预约披露 | 文档逐字「**近四期**的财务报告」 | 想要 2015 年的披露计划只能用 `stock_yysj_em` |
| `stock_dzjy_mrmx` / `stock_gsrl_gsdt_em` / `stock_lhb_stock_statistic_em` 等 **40 个接口** | — | `pageSize` 设了值但**没有分页循环**（`E1` 全量扫描，清单见 §6.4） | 超过 `pageSize` 的部分**静默丢失**，不报错 |

### 4.4 留存方案建议（只给结论，不改代码）

1. **存原始 DataFrame，不存归一后的结果**。理由：`pipeline.normalize` 对选填列缺席是**静默丢列**（`pipeline.py:72`，`E4`），对无法解析的值是 `to_numeric(errors="coerce")` **静默变 NaN**（`pipeline.py:52`）。快照的价值在于「当时上游到底返回了什么」，归一会把证据抹掉。
2. **快照独立于 `market.db`**。当前 `market.db` 已 5.7 GB，其中 44.8% 是溯源审计。快照走单独文件（`pyzipper` AES + 按日分片 parquet/jsonl），30–60 天滚动，与 `market.db` 解耦。
3. **每份快照带三个元数据**：`akshare.__version__`、抓取时刻、**本次返回的列名列表**。第三项是 §7 的漂移基线——本仓目前唯一记过「本次实际列」的地方是 `sync.py:414-419` 的回执 `fields`，但**无人拿它做比对**（`E4`，`store_provenance_query.py:399-402` 的 `field_coverage` 只统计仓内已有列的非空率）。
4. **优先级即上表顺序**。若只能做三件事：`stock_changes_em` 盘中轮询 + `stock_zh_a_spot_em` 五断面 + `stock_comment_em` 收盘一次。三者合计每日压缩后 < 2 MB，60 天 < 120 MB，相对 5.7 GB 的库可以忽略。

---

## 5. 补齐 Loci 已知硬伤

### 5.1 硬伤 A：`delist_date` 全空、退市股行情未同步 → 存活偏差不可测

**问题复核（`E4`）**：
- `instruments.delist_date` 填充数 **0**；`status` 分布 `delisted=1` / `normal=5546`（主 agent dbstat 2026-08-25）。
- **根因不是「没抓到」，是「根本没构造这个字段」**：唯一写入点 `store_rw.py:43` 取 `row.get("delist_date", "")`，而唯一生产者 `sync.py:203-215` 构造的 dict 只有 `code/name/market/board/industry/list_date/instrument_type` **七个 key**，压根没有 `delist_date`。更糟的是 `store_rw.py:63` 是 `delist_date=excluded.delist_date` **无条件覆盖**（`list_date` 有 `CASE WHEN <> ''` 保护，`delist_date` 没有）——就算将来有人写进去，下一次同步会把它刷回空串。
- 行情侧：`ops/application/jobs/sync.py:221` 是 `store.list_instruments()` **无参调用**，吃 `store_rw.py:389` 的默认 `status="normal"` → **`delisted` 的票被结构性排除出日 K 同步**。而且退市名**从未进过 `instruments`**（列表源是三所的**在市**列表），所以它们的历史行情**一次都没抓过**。

**AkShare 能不能解决：能，且代价不大。** 四步：

| 步骤 | 接口 | **真实返回列名（`E1` 源码 + `E2` 文档双证）** | 代价 |
|---|---|---|---|
| ① 拿沪市退市名单与日期 | `stock_info_sh_delist(symbol="全部"/"沪市"/"科创板")` | `公司代码`、`公司简称`、`上市日期`、**`暂停上市日期`** | 1 次调用。文档示例 `[114 rows × 4 columns]`。**两个坑**：(a) 源码把上游 `DELIST_DATE` 重命名成「暂停上市日期」，**列名是错的、值是退市日**（`stock_info.py` 的 `rename` 里 `"DELIST_DATE": "暂停上市日期"`，且 `COMPANY_STATUS=3` 就是「终止上市」）；(b) `pageHelp.pageSize=500` **单页无分页循环**，当前 114 行安全，超 500 会静默截断 |
| ② 拿深市退市名单与日期 | `stock_info_sz_delist(symbol="终止上市公司")` | `证券代码`、`证券简称`、`上市日期`、**`终止上市日期`** | 1 次调用。文档示例 `[150 rows × 4 columns]`。源码只对这三列做类型转换，其余列原样透传自深交所 xlsx |
| ③ 回补退市股日 K | `stock_zh_a_hist(symbol=退市代码, start_date=上市日, end_date=退市日, adjust="hfq")` | `日期`/`股票代码`/`开盘`/`收盘`/`最高`/`最低`/`成交量`/`成交额`/`振幅`/`涨跌幅`/`涨跌额`/`换手率` | **264 只 × 1 次**（沪 114 + 深 150）。**未实测东财是否保留退市股 K 线**——这是本方案唯一的不确定点，落地前必须先对 3–5 只已退市代码单点验证。备选：通达信本地 `vipdoc` 里退市股的 `.day` 文件通常**保留**（本仓日线主源就是通达信二进制，`tdxpy` 已在依赖里）——**这条路比 AkShare 更可靠且零配额** |
| ④ 补退市股基本面 | `stock_balance_sheet_by_report_delisted_em(symbol="SZ000013")` / `stock_profit_sheet_by_report_delisted_em` / `stock_cash_flow_sheet_by_report_delisted_em` | **文档明确不列列名**（原文逐字 `| - | - | 319项，不逐一列出 |` / `203 项` / `252 项`），实际是**英文东财字段码**：`SECUCODE`、`SECURITY_CODE`、…、`OPINION_TYPE`（值为中文「标准无保留意见」/「无法表示意见」/「未经审计」）、`LISTING_STATE`。三表期数不齐（同一只 SZ000013：资产负债表 38 期、利润表 39 期、现金流量表 21 期） | 264 × 3 = 792 次逐票调用，一次性 |

**关于 `stock_zh_a_stop_em`：任务书里提到的这个接口不能用来做这件事。** 它的真实语义是**东财「两网及退市」板块的当日行情**（`quote.eastmoney.com/center/gridlist.html#staq_net_board`），返回 17 列**当日行情**，文档限量逐字「单次返回**当前交易日**两网及退市的所有股票的行情数据」。同族的 `stock_staq_net_stop()` 只有 `序号`/`代码`/`名称` 三列、**没有退市日期**（文档示例 204 行）。**两者都解决不了存活偏差**，只能告诉你「现在有哪些票在老三板」。真正管停牌的是 `stock_tfp_em(date)`（按日可回溯，列见 §2.6）。

**代价总结**：一次性 ≈ 264 次列表相关调用 + 264 次日 K + 792 次财报（可分批，无时效性）；日常增量为**每月 1 次**跑两个 delist 接口做 diff。**相对「组合层收益数字全部不可信」这个代价，这是极高性价比的修复。**

**修完之后还差什么（AkShare 解决不了的）**：
- **历史 ST 状态**。`stock_zh_a_st_em` 只有当天；`stock_info_sz_change_name` 有日期但**只有深市**（示例 1,619 行，1992 起）；`stock_info_change_name` 有沪深全量但**输出是英文列 `index`/`name`、没有日期**。→ **沪市的历史 ST 挂牌/摘帽时间点在 AkShare 里无解，只能从今天起每天存 `stock_zh_a_st_em`**（已列入 §4.2 第 9 位）。

### 5.2 硬伤 B：无 point-in-time 财务

**问题复核（`E4`）**：`sync.py:444-450` 与 `sync_spot_receipts.py:72-75` **恒定写** `published_at=""` / `publication_status="not_observed"` / `available_at=""` / `availability_status="not_observed"`，`store_provenance.py:185-196` 再做一次归一（status≠observed 或值为空 → 一律回落 `not_observed`）。下游 `backtest_support.py:328-336` 的 `strict_pit=true` 会**全量拒绝**行情证据。仓内注释写得很清楚且是对的：「适配器只观测到本次拉取，证明不了供应商历史发布时间」。

**AkShare 能不能解决：能解决「公告日级 PIT」，解决不了「盘中可见时点级 PIT」。**

| 需要的东西 | 接口 | **真实列名（`E1`+`E2`）** | 覆盖 | 代价 | 局限 |
|---|---|---|---|---|---|
| **实际披露日**（最硬的锚点） | `stock_yysj_em(symbol="沪深A股", date="YYYYMMDD")` | `序号`/`股票代码`/`股票简称`/`首次预约时间`/`一次变更日期`/`二次变更日期`/`三次变更日期`/**`实际披露时间`** | **从 20081231 开始**（文档逐字），按报告期 | 每报告期 1 次，`(2026-2008)×4 ≈ 72` 次一次性 + 每季 1 次 | 是**日期**不是时刻。当天 08:00 披露还是 21:00 披露分不出来 → **T 日财报只能假设 T+1 才可用** |
| **公告日 + 主要指标**（一步到位） | `stock_yjbb_em(date)` | 16 列：`序号`/`股票代码`/`股票简称`/`每股收益`/`营业总收入-营业总收入`/`营业总收入-同比增长`/`营业总收入-季度环比增长`/`净利润-净利润`/`净利润-同比增长`/`净利润-季度环比增长`/`每股净资产`/`净资产收益率`/`每股经营现金流量`/`销售毛利率`/`所处行业`/**`最新公告日期`** | **从 20100331 开始** | 约 66 次一次性 | ⚠ **`最新公告日期` 是「最新」不是「首次」**——发生更正/重述时这个日期会**前移到重述日**，用它做 PIT 会**低估**当时的可见性。严格做法：`stock_yysj_em.实际披露时间` 为主锚，`stock_yjbb_em.最新公告日期` 只作交叉校验 |
| **全市场三表 + 公告日** | `stock_zcfz_em(date)` / `stock_lrb_em(date)` / `stock_xjll_em(date)` | 三个都含 **`公告日期`**。`stock_lrb_em`：`净利润`/`营业总收入`/`营业总支出-*`/`营业利润`/`利润总额`/`营业总收入同比`/`净利润同比`；`stock_zcfz_em`：`资产-总资产`/`资产-货币资金`/`资产-应收账款`/`资产-存货`/`负债-总负债`/`股东权益合计`/`资产负债率`/`资产-总资产同比`/`负债-总负债同比`；`stock_xjll_em`：`经营性现金流-现金流量净额`/`投资性现金流-*`/`融资性现金流-*`/`净现金流-*` | **从 20100331 开始** | 3 × 66 ≈ 200 次一次性 | 是精简版（每表十几列），不是完整三表。要完整三表得逐票调 `stock_*_by_report_em`（数百英文列），且**那些接口不带公告日** |
| **业绩预告**（比正式财报早，短线更关键） | `stock_yjyg_em(date)` | 11 列：`序号`/`股票代码`/`股票简称`/`预测指标`/`业绩变动`/`预测数值`/`业绩变动幅度`/`业绩变动原因`/`预告类型`/`上年同期值`/**`公告日期`** | **从 20081231 开始** | 约 70 次一次性 | 文档把 5 个中文列标成 float64，是**文档类型标注错误**，列名本身正确 |
| **业绩快报** | `stock_yjkb_em(date)` | 含 **`公告日期`**、`市场板块`、`证券类型` | 从 20100331 开始 | 约 66 次 | ⚠ 文档输出表列 **18 列**、数据示例写 `16 columns`，**自相矛盾**，`市场板块`/`证券类型` 是否真存在需实测 |
| 巨潮口径交叉验证 | `stock_report_disclosure(market, period)` | `股票代码`/`股票简称`/`首次预约`/`初次变更`/`二次变更`/`三次变更`/`实际披露` | **仅近四期**（文档逐字） | 4 次 | 只能校验最近一年，**不能做历史 PIT** |
| **PIT 行业**（做行业中性化必须） | `stock_industry_clf_hist_sw()` | `symbol`/**`start_date`（计入日期）**/`industry_code`/`update_time` | 全历史 | **1 次调用**（申万一个 xls 全量） | **性价比最高的一项**。另有 `stock_industry_change_cninfo`（列含 `变更日期`/`分类标准`/`行业门类`/`行业次类`/`行业大类`/`行业中类`）作多口径交叉，但需 `py_mini_racer` |

**能做到什么程度**：接上 `stock_yysj_em.实际披露时间` 之后，可以把 `source_route_receipts.published_at` 从恒空改成「有外部证据支撑的公告日」，并把 `publication_status` 置为 `observed`——这正是 `store_provenance.py:185-196` 预留的口子（「只有外部证据显式给 observed 且值非空才保留」）。**`available_at`（盘中可见时点）仍然拿不到**，只能用「披露日 T → `available_at = T+1 09:30`」这个保守规则，并把这个规则本身写进证据链。

**做不到什么**：
- **重述/更正的原始版本**。AkShare 给的永远是**当前**的财务数字，不是「2021 年 4 月当时看到的那个版本」。真正的 PIT 数据库（Wind/Choice PIT）会保留每个版本，AkShare 不会。→ 结论：**AkShare 能做到「时点正确的日期」，做不到「时点正确的数值」**。这个边界必须写进任何用它做 PIT 回测的文档里。
- **停牌/ST 的历史时点**（见 §5.1 末）。

---

## 6. 稳定性与工程约束

### 6.1 调用模式分类（全 403 个 `stock_*` 接口，按签名机器分类）

| 模式 | 判据 | 数量 | 同步任务应该怎么排 |
|---|---|---:|---|
| **全市场单次（大表）** | 无 `symbol`/`stock`/`code` 且无 `date` | **126** | **一次调用拿全市场** → 强缓存、日内复用、**绝不放进逐票循环里**。典型：`stock_zh_a_spot_em`、`stock_comment_em`、`stock_individual_fund_flow_rank`、`stock_board_concept_name_em` |
| **逐票循环** | 有 `symbol`/`stock`/`code`，无日期 | **183** | **配额敏感**。必须限速 + 断点续跑 + 只对候选池跑，不对 5,500 只全量跑。典型：`stock_individual_fund_flow`、`stock_bid_ask_em`、`stock_hot_rank_detail_em`、`stock_cyq_em` |
| **逐票 + 按日/区间** | 两者都有 | **43** | 最贵。典型：`stock_zh_a_hist`、`stock_lhb_stock_detail_em`、`stock_gdfx_free_top_10_em`。`stock_zh_a_hist` 之所以能换成通达信本地二进制，正因为它是这一类里量最大的 |
| **按日 / 事件驱动** | 只有 `date`/`start_date` | **51** | **一天一次或事件触发**，最适合做增量任务。典型：`stock_zt_pool_*`、`stock_lhb_detail_em`、`stock_tfp_em`、`stock_yjbb_em`、`stock_margin_detail_sse`、`stock_dzjy_mrmx` |

**排任务的三条推论**：
1. **126 个全市场单次接口应该做成「一天一张表」的快照任务**，而不是按需调用。它们大多是 `S今`（§4），存下来就是资产。
2. **183 个逐票接口不能进日常全量同步**。本仓已经踩过这个坑（日线主源换通达信）。资金流 `stock_individual_fund_flow` 目前是唯一接入的逐票 AkShare 接口，应当只对候选池跑。
3. **51 个按日接口是接入成本最低、收益最高的一批**——`stock_zt_pool_*`（6 个）、`stock_lhb_detail_em`、`stock_tfp_em`、`stock_margin_detail_sse/szse`、`stock_dzjy_mrmx` 全在这一类，且全是 P0。**「该用的没用起来」主要指的就是这 51 个。**

### 6.2 `py_mini_racer` 依赖清单（`E1`，全包 grep，精确到模块）

| 模块 | 受影响的 `stock_*`/工具接口 | 用途 |
|---|---|---|
| `stock/stock_zh_a_sina.py` | `stock_zh_a_daily`、`stock_zh_a_minute`、`stock_zh_a_cdr_daily`、`stock_zh_a_spot` | 新浪 K 线 `d()` 解密 |
| `index/index_stock_zh.py` | `stock_zh_index_daily`（同模块的 `_em`/`_tx` 变体不用，但**导入模块就要求装库**） | 同上 |
| **`tool/trade_date_hist.py`** | **`tool_trade_date_hist_sina`（交易日历）** | 同上。**一切时序对齐的前提竟然挂在 JS 引擎上** |
| `stock_feature/stock_fund_flow.py` | `stock_fund_flow_individual`、`_concept`、`_industry`、`_big_deal` | 同花顺 `v` cookie 签名 |
| `stock_feature/stock_board_concept_ths.py` | `stock_board_concept_name_ths`、`_cons`、`_info`、`_index`、`_summary` | 同上 |
| `stock_feature/stock_board_industry_ths.py` | `stock_board_industry_*_ths`、`stock_ipo_benefit_ths`、`stock_xgsr_ths` | 同上 |
| `stock_feature/stock_technology_ths.py` | `stock_rank_cxg_ths` 等 **11 个技术选股榜** | 同上 |
| **`stock_feature/stock_cyq_em.py`** | **`stock_cyq_em`（筹码分布）** | ⚠ **不是解密，是在本地 MiniRacer 里跑一段 JS 重算筹码分布**——返回值是 akshare 自己算的，不是东财官方值 |
| `stock_feature/stock_a_pe_and_pb.py` | `stock_index_pe_lg`、`stock_index_pb_lg`、`stock_market_pe_lg`、`stock_market_pb_lg` | 乐咕解密 |
| `stock/*_cninfo.py`（14 个模块） | `stock_dividend_cninfo`、`stock_hold_num_cninfo`、`stock_industry_category_cninfo`、`stock_industry_change_cninfo`、`stock_ipo_summary_cninfo`、`stock_new_ipo_cninfo`、`stock_profile_cninfo`、`stock_share_change_cninfo`、`stock_allotment_cninfo`、`stock_cg_*_cninfo`、`stock_hold_control_cninfo`、`stock_rank_forecast_cninfo` 等 | 巨潮 `mcode` 生成 |

**⚠ 与仓内文档的偏差（必须更正）**：`docs/quant-toolkit.md:499-501` 写「`ak.stock_info_a_code_name()` 不可用：它依赖 py_mini_racer 执行 JS，在多线程同步下会触发原生崩溃」。**在 1.18.56 里这句话已经不成立**——该函数的源码（`E1`）现在是：`stock_info_sh_name_code("主板A股") + stock_info_sz_name_code("A股列表") + stock_info_sh_name_code("科创板") + stock_info_bj_name_code()` 拼接，**全程 HTTP，无 `py_mini_racer`**，且带 `@lru_cache()`。**上游已经采用了本仓当年的绕行方案。** 仓内文档应加一条时间戳限定，避免后人以为这个坑还在。

**工程含义**：真正需要防「多线程原生崩溃」的是上表这 30+ 个接口，尤其是 **`tool_trade_date_hist_sina`（交易日历）** 和 **`stock_cyq_em`（筹码，P0）**。如果要用它们，必须：单线程调用 / 或每进程只初始化一次 MiniRacer / 或用交易所日历替代新浪日历。

### 6.3 一次返回全市场大表（适合缓存、不适合循环）

这批接口一次调用就是全市场，**放进逐票循环里就是 5,500 倍的浪费**：
`stock_zh_a_spot_em`、`stock_sh_a_spot_em`/`sz`/`bj`/`kc`/`cy`、`stock_new_a_spot_em`、`stock_zh_a_st_em`、`stock_zh_a_stop_em`、`stock_comment_em`、`stock_individual_fund_flow_rank`、`stock_main_fund_flow`、`stock_sector_fund_flow_rank`、`stock_board_concept_name_em`、`stock_board_industry_name_em`、`stock_zt_pool_*`（6 个，`pagesize=10000` 一次到底）、`stock_zh_a_gdhs`、`stock_yjbb_em`/`yjkb`/`yjyg`/`yysj`、`stock_zcfz_em`/`lrb`/`xjll`、`stock_fhps_em`、`stock_repurchase_em`、`stock_margin_detail_sse`/`szse`、`stock_lhb_detail_em`、`stock_tfp_em`、`stock_staq_net_stop`、`stock_info_*_name_code`、`stock_info_*_delist`、`stock_industry_clf_hist_sw`。

其中 `stock_zh_a_spot_em`、`stock_zh_a_st_em`、`stock_new_a_spot_em` 等走 `fetch_paginated_data`：**先读 `data.total` 反算总页数，再逐页 `pn` 递增，页间 `time.sleep(random.uniform(0.5, 1.5))`**（`E1`，`akshare/utils/func.py`）。→ 全市场一次约 55 页 × 1 秒 ≈ **单次调用就要 1 分钟**，不能当作低延迟接口用。

### 6.4 分页 / 日期窗口的硬限制

**（a）设了 `pageSize` 但没有分页循环的 40 个接口**（`E1`，全量扫描）——超出部分**静默丢失，不报错**：

`stock_dzjy_mrmx`(5000)、`stock_dzjy_mrtj`(5000)、`stock_gsrl_gsdt_em`(5000)、`stock_hold_management_person_em`(5000)、`stock_lhb_stock_statistic_em`(5000)、`stock_sy_profile_em`(5000)、`stock_value_em`(5000)、`stock_margin_ratio_pa`(50000)、`stock_hsgt_fund_flow_summary_em`(2000)、`stock_analyst_detail_em`(1000)、`stock_lhb_stock_detail_date_em`(1000)、`stock_account_statistics_em`(500)、`stock_gpzy_*`(500×3)、`stock_lhb_stock_detail_em`(500)、`stock_qsjy_em`(500)、`stock_report_fund_hold_detail`(500)、`stock_restricted_release_queue_em`(500)、`stock_restricted_release_stockholder_em`(500)、`stock_restricted_release_summary_em`(500)、`stock_financial_analysis_indicator_em`(200)、`stock_info_global_em`(200)、`stock_hot_rank_em`(100)、`stock_hot_up_em`(100)、`stock_news_main_cx`(100)、`stock_sns_sseinfo`(100)、`stock_info_global_futu`(50)、**`stock_comment_detail_scrd_focus_em`(30)**、**`stock_comment_detail_scrd_desire_em`(30)**、`stock_news_em`(10)、**`stock_zh_a_gbjg_em`(20)**、`stock_zh_scale_comparison_em`(5)、`stock_financial_hk_analysis_indicator_em`(9) 等。

> `stock_zh_a_gbjg_em`（股本结构，`pageSize=20` 无循环）在 **1.18.73 才被标记为「修复分页截断问题」**——**本机 1.18.56 带着这个 bug**。任何用它算历史流通股本的结果都要重跑。

**（b）明确的日期/条数窗口**：

| 接口 | 硬限制 | 出处 |
|---|---|---|
| `stock_zh_a_hist_min_em(period="1")` | `ndays=5`，**最近 5 个交易日** | `E1` 源码 |
| `stock_cyq_em` | `lmt=210` 拉 K，输出 `iloc[-90:]` → **恰好 90 行** | `E1` 源码 |
| `stock_hot_rank_detail_em` | `yearType="5"`，实际示例 366 自然日 | `E1`+`E2` |
| `stock_zt_pool_*`（6 个） | 文档「只能获取近期的数据」，无起始日承诺 | `E2` 逐字 |
| `stock_hsgt_stock_statistics_em` / `stock_hsgt_institution_statistics_em` / `stock_intraday_sina` / `stock_industry_pe_ratio_cninfo` | 同上「只能获取近期的数据」 | `E2` 逐字 |
| `stock_report_disclosure` | **仅近四期** | `E2` 逐字 |
| `stock_yjbb_em` / `stock_yjkb_em` / `stock_zcfz_em` / `stock_lrb_em` / `stock_xjll_em` | **从 20100331 开始** | `E2` 逐字 |
| `stock_yjyg_em` / `stock_yysj_em` | **从 20081231 开始** | `E2` 逐字 |
| `stock_hsgt_individual_em` | **截至 20240816**（已冻结） | `E2` 逐字 |
| `stock_hot_rank_em` | 当前交易日**前 100** | `E2` 逐字 |
| `stock_info_sh_delist` | `pageHelp.pageSize=500`，单页 | `E1` 源码 |

**（c）静默空返回**：`stock_zt_pool_em` 在 `data_json["data"] is None` 或 `pool` 为空时**返回空 DataFrame**（`E1`）。日期越界与「当天真没涨停股」**无法区分**。任何基于它的回测都必须对「空日」单独计数并人工核对。

---

## 7. 版本与破坏性变更

### 7.1 发版节奏（`E3`，PyPI 上传时间 join changelog）

| 指标 | 近 12 个月（2025-08-25 ~ 2026-08-21） | 近 6 个月 |
|---|---:|---:|
| PyPI 发版数 | **273** | **101** |
| 平均间隔 | **1.32 天/版** | ≈1.8 天/版 |
| commit 前缀 `fix:` | **268 / 273（98.2%）** | — |
| 前缀 `add` / `feat` / `docs` / `build` | 2 / 1 / 1 / 1 | — |
| **标题直接点名某个 `stock_*` 接口的版本** | **132（48.4%）** | — |
| 被动过的**不同** `stock_*` 接口 | **76** | — |
| **A 股接口正式更名** | **0**（更名表里最近的 `stock_*` 更名是 1.12.91 `stock_telegraph_cls`→`stock_info_global_cls`，2024-03-13） | 0 |
| **changelog 里写明删除 A 股接口** | **0** | 0 |

被修最频繁的 A 股相关接口（近 12 月提及次数）：`stock_individual_spot_xq` **38**、`stock_news_em` 10、`stock_zh_a_minute` 9、`stock_zh_a_hist_tx` 6、`stock_a_high_low_statistics` 6、`stock_info_sh_name_code` **6**、`stock_individual_basic_info_xq` 5、`stock_buffett_index_lg` 5、`stock_zh_a_daily` 4、`stock_a_ttm_lyr` 4。

> `stock_info_sh_name_code` 一年被修 6 次值得警惕——**它是本仓 `instruments` 同步的直接依赖**。

### 7.2 真正的破坏模式（不是改名）

**① 静默删除。** `stock_hot_rank_wc`（问财热度榜）在 changelog 里被「修复」了 **6 次**（1.8.53 / 1.9.12 / 1.9.77 / 1.10.85 / 1.12.72 / 1.14.80），然后**消失了——changelog 里关于它的删除记录是 0 条**（`E3`，全文 grep）。本仓在 `2026-08-ths-heat-tail-close-picker.md:427` 记录过「`stock_hot_rank_wc` 已被静默移除」，本轮从 changelog 侧**证实了这不是疏忽而是常态**：**AkShare 删接口不写 changelog。**

**② 值语义变更（列名不动、数字变了）。** 1.18.73（2026-07-22）第 14 条逐字：「**修复 `stock_zh_a_hist_tx` 接口的成交量、换手率和成交额字段语义**」。列名一个没改，数值口径全变。**这是本仓契约层 100% 抓不到的一类变更**——`FieldSpec` 只声明「目标列 ← 候选源列 + 单位」，源列名匹配上了就通过。

**③ 静默截断修复。** 1.18.73 第 13 条：「修复 `stock_zh_a_gbjg_em` 接口分页截断问题」。意思是**在 1.18.73 之前它一直在悄悄丢数据**——包括本机的 1.18.56。

**④ 参数清理。** 1.18.73 第 10–12 条：「清理 `stock_hot_rank_em` / `stock_hk_hot_rank_em` / `stock_hot_up_em` 接口 `secids` 参数中的无效后缀」。上游 App 接口在变，akshare 追着改。

**⑤ 上游鉴权收紧。** 1.18.92（2026-08-18）：`stock_individual_basic_info_xq` 系列在雪球返回 `400016` 时提示「匿名访问当前受限，需通过 `token=` 传入有效 `xq_a_token`」。→ **雪球系接口（含 `stock_hot_follow_xq`/`_deal_xq`/`_tweet_xq`）正在从「免费匿名」滑向「需要登录态」。**

**⑥ 1.18.56 → 1.18.94 我们会拿到的新接口**：`stock_margin_bse` / `stock_margin_detail_bse` / `stock_margin_underlying_info_bse`（北交所两融，1.18.73 新增）、`stock_zh_a_spot_tx`（腾讯全市场快照）。**这 4 个在本机都不存在**（`hasattr` 实测 False）。

### 7.3 现有防线够不够（`E4`，逐项评估）

| 破坏模式 | `check_akshare_version` | `source_contract` + `pipeline.normalize` | 录制夹具 `tests/market/fixtures` | 覆盖判定 |
|---|---|---|---|---|
| **接口被静默删除** | ❌ 只比版本号字符串，`installed != latest` 就报 `update_available`（`akshare_tools.py:89-91`，连大小都不比，PyPI 回退版本会误报） | ❌ 契约不含函数名存在性 | ❌ | **完全裸奔**。唯一的运行时门禁是 `sentinel_extended.py:146-147` 的 `import akshare` 能否成功 |
| **接口改名** | ❌ | ❌ | ❌ | 裸奔（但近 12 月 A 股侧发生率 0，风险低） |
| **必填列消失** | ❌ | ⚠ `pipeline.py:65-67` 抛 `NormalizeError` —— **但 `router.py:204-207` 的 `except Exception` 会把它吞成「换下一个源」**，上层拿到数据、看不到告警 | ✅ 夹具能测，但夹具是**离线静态快照**，上游真改了夹具不会自己变，CI 依旧全绿 | **半覆盖，且失效方式最危险**（静默降源） |
| **选填列改名/消失** | ❌ | ❌ **完全静默丢列**（`pipeline.py:72`：`keep = [name for name in output_columns() if name in out.columns]`，无日志无告警） | ❌ | **裸奔** |
| **列名微调**（`换手率`→`换手率(%)`） | ❌ | ❌ `_first_present` 是**精确字符串相等**（`pipeline.py:82-85`），直接失配 | ❌ | 裸奔 |
| **值语义变更**（1.18.73 的 `stock_zh_a_hist_tx`） | ❌ | ❌ `pd.to_numeric(errors="coerce")` 静默变 NaN 或直接接受错值 | ❌ | **完全裸奔，且最难发现** |
| **分页静默截断** | ❌ | ❌ 行数不在契约里 | ❌ | 裸奔 |
| 版本落后 | ✅ 唯一覆盖到的 | — | — | ✅ 但**没有任何门禁**：全仓只有一个调用点 `api/akshare.py:208-214`，是给前端看的只读端点，`src/ops`、调度器、`execute_sync` 里 grep 不到 |

**结论：8 种破坏模式，现有防线完整覆盖 1 种、半覆盖 1 种。契约层本身设计是对的（`FieldSpec` 的 `unit_by_source` 处理东财百分数 vs 新浪小数差 100 倍这类问题很到位），问题在于它的失败被 router 吞掉，且它管不到「列还在但值变了」和「行数少了」。**

另外两个具体缺口：
- **契约无版本号**。`parser_revision` 是硬编码常量 `"market-quote-normalizer-v1"`（`store_provenance.py:23`），**与 `source_contract.py` 的内容零绑定**——改了契约不改它，历史回执无法区分「用哪版解析器解出来的」。
- **探测结果零持久化**。`akshare_catalog` 的反射与试跑结果只在进程内 `_CATALOG_CACHE`，`akshare_probe_worker.py` 全文件无任何写盘/写库（`E4`）→ **没有任何列漂移基线**。`columns_detail` 的中英对照来自 `column_glossary.CN_TO_EN` 的 **54 条手写表**，akshare 新出的列一律 `en:""`，**不报错也不记录**（`tests/market/test_akshare_catalog.py:119-123` 明确固化了这个语义）。

### 7.4 建议怎么防（按性价比排序，只给方案不改代码）

| # | 建议 | 针对的破坏模式 | 代价 |
|---:|---|---|---|
| 1 | **把「本次返回的列名列表 + 行数 + 3 行抽样值」随每次快照一起落盘**（§4.4 第 3 点），下次抓取时与上一次做差集比对，有差异就告警而不是静默通过 | 覆盖 ②③④⑤：选填列改名、值语义变更、分页截断、上游鉴权收紧 | 低。`sync.py:414-419` 已经在回执里记 `fields`，只差一个比对函数 |
| 2 | **给契约加内容 hash，写进 `parser_revision`** | 让历史回执可区分解析器版本 | 极低。`_PARSER_REVISION` 换成 `f"market-quote-normalizer-{sha256(contract_repr)[:8]}"` |
| 3 | **`router` 对 `NormalizeError` 与「网络失败」分开处理**：网络失败可静默降源，**契约失败必须 WARN 级日志 + 计入健康度** | 覆盖 ①：静默降源掩盖列变更 | 低。`router.py:204-207` 多一个 `except NormalizeError` 分支 |
| 4 | **接口存在性冒烟**：把实际会用到的接口名列成清单，`import akshare` 后逐个 `hasattr` + `inspect.signature` 比对，挂进 `sentinel_extended` 的体检链 | 覆盖「接口被静默删除」「签名变更」 | 低。不联网，纯反射，毫秒级 |
| 5 | **升级策略改为「锁版本 + 季度评估」**，不要跟 `latest`。理由：268/273 是 `fix:`，跟最新等于每 1.3 天引入一次未验证变更；但**也不能不升**（1.18.56 带着 `stock_zh_a_gbjg_em` 分页 bug）。建议：锁定版本 + 每季度读一次 changelog diff，只在「修的正是我们用的接口」时升 | 平衡 | 中。需要人读 changelog |
| 6 | **把 `check_akshare_version` 从「字符串不等」改成语义化版本比较**，并在同步任务启动时记一条 INFO（不阻断） | 消除误报 | 极低 |
| 7 | **对 `stock_zt_pool_*` 的空返回单独计数**：空日数 / 交易日数 应该是个稳定的低值，突然升高就是接口窗口缩短了 | 覆盖「静默空返回」 | 低 |

---

## 8. 替代与互补（每个 P0 数据族的第二条腿）

> 数据来自子 agent 逐接口读官方文档 / 拆 wheel 读源码（未注册账号、未批量拉数）。

### 8.1 逐族对照

| P0 数据族 | AkShare 现状 | 最佳替代 | 何时该绕开 AkShare 直连上游 |
|---|---|---|---|
| **日 K** | `stock_zh_a_hist`，逐票 `H全` | **通达信本地 `.day` 二进制（本仓已采用，主源）** > baostock（免费，1990-12-19 起） > Tushare `daily`（120 积分） | **已经绕开了，这是对的。** 通达信本地零网络零配额；`.day` 格式 `struct '<IIIIIfII'` 32 字节/记录，⚠ **价格系数按品种不同**（A 股 0.01，B 股/基金/债券 0.001），不查 `SECURITY_COEFFICIENT` 会错 10 倍 |
| **分钟 K 历史** | `period="1"` 只有 5 天；5/15/30/60 深度未知 | **baostock 免费提供 5/15/30/60 分钟，且不需注册** | **应该立刻绕开。**⚠ baostock `start_date` 留空会**静默取 2015-01-01** 而非全历史；分钟线**不含指数**；分页 2000 条/页；走自研 TCP `public-api.baostock.com:10030` 不是 HTTP。1 分钟历史**任何免费源都没有**（东财 `ndays≤5`），只能自存 |
| **涨停板池** | `stock_zt_pool_*` 6 个，`H近` | **东财 `push2ex` 直连**（`getTopicZTPool` 等，`ut=7eea3edc…`，`pagesize=10000`，免费）；Tushare `limit_list_d` 需 **5000 积分（≈500 元/年）且只到 2020 年、不含 ST** | **不该绕开 akshare，但该自存。** akshare 已经把 6 个端点封装好了，直连的边际收益只有「自己控限速」。真正的问题是**历史窗口**，直连也解决不了 → 回到 §4 |
| **龙虎榜** | `stock_lhb_*`，`H全`，稳定 | adata 免费；Tushare `top_list` 2000 积分、2005 年起 | **不用绕。** akshare 的 `stock_lhb_detail_em` 区间查询已经够用 |
| **游资明细** | ❌ AkShare 没有 | **Tushare `hm_detail`，10000 积分（≈1000 元/年），数据自 2022 年 8 月** | **没有免费替代。** 要做游资身份识别只能付费。`stock_lhb_hyyyb_em`（每日活跃营业部）+ `stock_lhb_stock_detail_em`（席位明细）可以自建一个粗糙的游资库，代价是自己维护营业部→游资的映射 |
| **资金流** | `stock_individual_fund_flow` 逐票 `H全`（已接入） | adata 免费；Tushare `moneyflow` 2000 积分、2010 年起 | **可作第二条腿。** adata 显式多源切换（同花顺/东财/百度/腾讯/新浪）+ 内置代理开关，是 akshare 没有的抗封能力 |
| **逐笔 / 历史分时** | `stock_intraday_em` 只有当天 | **`mootdx` / `tdxpy`（pytdx 的活跃 fork）—— 唯一能取历史逐笔的免费源** | **应该绕开。**⚠ `pytdx` 本体已 archived（最后 commit 2020-03-02，作者声明「请不要用于任何商业目的」），必须走 fork。本仓依赖里已有 `tdxpy`。限制：K 线单次 ≤800 条、逐笔单次 ≤2000 条 |
| **PIT 财务** | `stock_yysj_em` 等（§5.2） | Tushare `disclosure_date` 2000 积分 | **不用绕。** akshare 免费且 20081231 起，覆盖比 Tushare 好 |
| **行业分类（PIT）** | `stock_industry_clf_hist_sw` 一次调用全历史 | baostock `query_stock_industry`（每周一更新，无历史变更记录） | **不用绕。** 申万 xls 是最好的免费 PIT 行业源 |
| **热度/注意力** | 东财人气榜（`S今`）+ `stock_hot_rank_detail_em`（约 1 年） | 同花顺直连（需 `py_mini_racer` 造 `v` cookie，本仓已有运行时）；adata `sentiment.hot` | **看诉求。** 本仓 `2026-08-ths-heat-tail-close-picker.md` 已详细论证过，结论是扩展现有 lane 而非新建直连。**本文补充一条：东财人气榜的历史只能自存，这一点没变** |

### 8.2 各替代源的硬约束速查

| 源 | 免费程度 | 历史起点 | 硬限制 | 维护活跃度 |
|---|---|---|---|---|
| **Tushare Pro** | 积分制。120 分只能取非复权日线 | 因接口而异 | `limit_list_d` **5000 分**（2020 起、不含 ST）；`hm_detail` **10000 分**（2022-08 起）；`moneyflow` 2000 分（2010 起）；`fina_indicator` 单次仅 100 条，全市场需 `_vip` 5000 分；**历史分钟线不在积分体系内，单独 2000 元/年**。积分/权限均 **1 年有效、不退款** | 活跃 |
| **baostock** | **完全免费、匿名无注册** | **1990-12-19** | 无涨停板 / 无资金流 / 无龙虎榜 / 无北向 / 无两融（源码全量导出核实）；`start_date` 空默认 2015-01-01；分钟线不含指数；自研 TCP 协议 | 活跃（0.9.3 @ 2026-07-10）。⚠ 老 MediaWiki 文档地址已全部失效，新址 `https://www.baostock.com/helpDocsHome`；0.9.3 已埋 `set_API_key` 与 `BSERR_LOGIN_COUNT_LIMIT` 等错误码——**「永久免费无限制」不宜作长期假设** |
| **pytdx / mootdx / tdxpy** | 免费 | 取决于本地 vipdoc | K 线 ≤800/次、逐笔 ≤2000/次；`pytdx` 本体 **archived** | `mootdx` 0.11.7 @2024-05-04；`tdxpy` 0.2.7 @2024-03-10 |
| **adata** | 完全免费 | — | **无涨停板池**（v2.9.5 全包 grep「涨停」命中 0）；三大报表不提供，只有 `get_core_index()` | 最后 commit 2025-12-26；5.1k stars。⚠ v2.9.0 后不再打 GitHub Release，只看 releases 会低估 8 个月 |
| **东财直连** | 免费无鉴权 | — | **3 个不同的硬编码 `ut` token 按端点族绑定**；`fields` 的 f 编号**无任何官方文档**、akshare 按**位置**硬编码中文列名 → **东财增删字段会静默列错位（不报错）**；`fs` 市场过滤 DSL 无文档；两套完全不同的参数范式（`push2` 的 `fs/fid/fields/pn/pz` vs `datacenter-web` 的 `reportName/columns/filter`）；需自己做 `{7,28,72,81,82}.push2` 轮询与限速 | 无 SLA、无版本、无公告 |

### 8.3 一句话取舍

> **日 K 走通达信本地（已做对）；分钟 K 历史走 baostock（应该做）；逐笔走 tdxpy（应该做）；涨停板/龙虎榜/两融/PIT 财务留在 AkShare（够用且免费）；游资明细要么付 Tushare 1000 元/年、要么放弃；而所有 `S今` 的数据——竞价、异动、盘口、快照、千股千评、人气榜——不管走哪个源都得自己每天存。**

---

## 9. 直接回答用户：「引入的 AkShare 数据该用的没用起来」

**是的，而且损失可以量化。** 按「今天就能做、收益最高」排序：

| 优先级 | 做什么 | 为什么现在做 | 代价 |
|---|---|---|---|
| **今天** | 开始**每日快照** §4.1 的 7 类（`stock_changes_em`、`stock_zh_a_hist_pre_min_em`、`stock_zh_a_spot_em`、人气榜、`stock_comment_em`、`stock_bid_ask_em`、板块三件套） | **每拖一天就永久少一天历史。** 本仓已有 `pyzipper`，`intel_snapshots` 已证明快照留存这条路能跑通 | 压缩后 < 2 MB/日；60 天 < 120 MB（对比 `market.db` 5.7 GB） |
| **本周** | 接 §6.1 的「按日/事件驱动」51 个接口里的 8 个 P0：`stock_zt_pool_em`/`zbgc`/`previous`/`dtgc`、`stock_lhb_detail_em`、`stock_tfp_em`、`stock_margin_detail_sse`/`szse` | 这批**接入成本最低**（一天一次、全市场单表、无 py_mini_racer、稳定性风险低），且直接支撑本仓已有的龙头/涨停研究 | 每日 8 次调用 |
| **本月** | 修存活偏差（§5.1 四步） | 在此之前**任何组合层收益数字都不可信**（本仓已有文档明说） | 一次性约 1,300 次调用，可分批 |
| **本月** | 接 `stock_yysj_em` + `stock_zcfz/lrb/xjll_em`，把 `published_at` 从恒空改成公告日（§5.2） | 让 `strict_pit=true` 的回测从「全量拒绝」变成「日级 PIT 可用」 | 一次性约 270 次调用 |
| **本季** | 上 §7.4 的第 1、3、4 条防线（列名基线比对、契约失败不静默降源、接口存在性冒烟） | 近 12 月 273 个版本、76 个接口被动过、删接口不写 changelog | 三个小函数 |

**唯一不建议做的**：不要为了「用起来」去接那 183 个逐票接口里的大部分。它们是配额陷阱，本仓在日线上已经付过一次学费。

---

## 10. 本轮没做什么

- **未联网调用任何 AkShare 数据接口**。所有「实际返回多少行/历史多深」的问题一律标注为文档口径或未实测。
- 未改仓库任何其它文件（含 `docs/research/INDEX.md`）、未 commit、未 push、未写任何数据库。
- 反射与源码解析产生的临时文件（`.tmp_ak_*.json` / `.tmp_ak_*.py` / `.tmp_targets.txt` / `.tmp_ak_changelog.md`）为一次性中间产物，**不入库**。
- 未验证的三处，落地前必须实测：(a) 东财是否保留**退市股**的日 K（§5.1 步骤③）；(b) `stock_zh_a_hist_min_em` 5/15/30/60 分钟的**实际历史深度**；(c) `stock_yjkb_em` 的 `市场板块`/`证券类型` 两列是否真实存在（文档自相矛盾）。
- 未评估 AkShare 的非 A 股接口（港股 / 美股 / 期货 / 期权 / 宏观 / ESG，合计约 690 个）。

---

## 摘要（≤300 字）

akshare 1.18.56 有 **403 个 `stock_*` 接口，本仓只接了 2 个**。核心发现是**「有无历史」这一列**：90 个价值接口中 **21 个只有当天快照**（竞价、异动、盘口、截面、人气榜、千股千评），无参数可回溯，**不自存就永久丢失**；另 6 个是伪历史（1 分钟仅 5 天、筹码固定 90 行），涨停池只承诺「近期」，越界时静默返空表。

存活偏差**能修**（`stock_info_sh_delist` 与 `stock_info_sz_delist` 的退市日期列）；PIT 只到公告日级（`stock_yysj_em`），到不了盘中时点。

近 12 月发版 **273 次、98% fix、动过 76 个接口、更名 0 次、删接口不写 changelog**；八种破坏模式现有防线只覆盖一种。
