# 龙头回撤低吸 / 龙回头 / 首阴反包 / N 字 / 二波：可编程实现与回测证据调研

> 调研日：2026-08-11
> 范围：只调研这一族 A 股短线形态的**可编程实现（代码/公式原文）**与**公开可核验的回测证据**。本文不运行本仓库回测，不改动任何策略、参数或默认值。
> 纪律：所有数字与公式都给出来源 URL；找不到就写「未找到可靠来源」。凡是我自己的推断，都显式标注为「本文推断」。**未编造任何回测数字或 URL。**
>
> 相关文档：[`2026-08-dragon-return-playbook.md`](2026-08-dragon-return-playbook.md) 从**交易者规则**角度调研同一形态（同日、独立检索）。两份文档独立得出同一条负面结论：**不存在公开、可复现的龙回头回测**。本文侧重**可编程实现、回测证据核验与工程陷阱**，与之互补而非重复。

---

## 0. 核心结论（先看这段）

1. **公式好找，回测证据极缺。** 「龙回头 / 二波 / 首阴反包」在通达信/同花顺公式论坛有大量**可直接抄的源码**，但这些帖子**几乎全部没有回测**——只有截图案例和「高胜率」自述。找到的所有带净值曲线/年化/回撤的公开回测，标的形态**都是「打板/接力」（买涨停），不是「回撤低吸」**。也就是说：**本文没有找到任何一份公开、可复现、含样本外检验的「龙回头低吸」回测。** 这是本次调研最重要的负面结论。

2. **能拿来直接用的只有「因子」，不是「策略」。** 连板计数、区间回撤率、缩量比、均线支撑、反包判定这些都有可靠实现（§1），但把它们组合成的策略必须由本仓库自己回测，外部数字不能借用。

3. **这一族形态的前视偏差风险高于普通因子策略**，因为它同时踩三个雷：涨停价不可成交、封板/龙虎榜数据的可见时点、以及「用当日最低价当买入价」。**一个真实的开源项目（`dragon-quant`）就在回测里用「断板日最低价买入」**——这是教科书级前视（§3）。

4. **涨跌停价必须数据驱动，不能硬编码比例。** 交易所原文只规定「前收盘价×(1±比例)、四舍五入到最小变动单位、差额不足一分时用前收±0.01」，但比例本身随板块、风险警示状态、退市整理状态、上市天数变化，且**有变更历史**（§4.1）。Python 内置 `round()` 是银行家舍入，直接用会算错涨停价。

5. **参数敏感性：这一族形态的参数几乎全是「调出来的」。** 回撤阈值 38.2%/50%、调整天数 3–10 天、缩量比 0.5/0.6/1/3 这些数字在各家公式里互相矛盾，且**没有任何一家给出扫描证据**（§5）。斐波那契 38.2%/61.8% 属于典型的「先有数字后有理由」。

---

## 证据分级说明

| 级别 | 含义 |
|---|---|
| **高** | 交易所/监管原文、券商正式研报原件、附完整可运行代码且作者主动披露局限 |
| **中** | 有源码 + 明确样本区间 + 明确样本量，但口径有瑕疵或只覆盖单一窗口 |
| **低** | 有数字但无代码/无样本量/无区间，或平台自动跑出未披露成交假设 |
| **存疑** | 内部自相矛盾、疑似 AI 生成、或与更可靠来源直接冲突 |

---

## 1. 已有的可复用因子与公式（原始代码/公式原文）

### 1.1 涨停判定与连板高度

#### （a）pandas 分段累加法（推荐，最干净）

来源：[使用 Pandas 分析 A 股连板数量的分布 - ellendan](https://ellendan.com/2025/01/07/shi-yong-pandas-fen-xi-a-gu-lian-ban-shu-liang-de-fen-bu/)

```python
def prepare_features(source_data_frame, last_n_days=400):
    source_data_frame = source_data_frame.iloc[-last_n_days:]
    # ① 收盘价 == 涨停限价 且 非 ST
    is_high_limit = (source_data_frame['close'] == source_data_frame['high_limit']) * 1 * ((source_data_frame['is_st'] < 1) * 1)

    if is_high_limit[is_high_limit > 0].empty:
        return pd.DataFrame()

    source_data_frame['is_high_limit'] = is_high_limit
    # ② 与前一日不同 => 新段起点
    is_segment_start = (is_high_limit.diff() != 0) * 1
    source_data_frame['segment_start'] = is_segment_start
    # ③ 段索引
    source_data_frame['segment_index'] = is_segment_start.cumsum()
    # ④ 段内累计 = 连续涨停第几天
    serie_high_limit = source_data_frame.groupby(by='segment_index').apply(
        lambda x: pd.DataFrame({
            'date': x.index.get_level_values("date"),
            'high_limit_days': x['is_high_limit'].cumsum()
        }),
        include_groups=False
    )
    # ⑤ 每段只保留最大连板那一天
    serie_high_limit = serie_high_limit.groupby(by='segment_index').agg(
        max_high_limit_days=('high_limit_days', 'max'),
        date=("high_limit_days", lambda x: x.idxmax()[2])
    )
    return serie_high_limit
```

**要点**：它直接用数据源给的 `high_limit` 字段判涨停，**不自己算涨停价**——这是最稳的做法（见 §4.1）。缺点是把 ST 整段剔除（`is_st < 1`），而不是给 ST 用 5% 阈值。

#### （b）不复权 + 涨幅阈值法（有陷阱，但常见）

来源：[我回测了 A 股 10 年的追涨停策略 - 同花顺量化社区](https://quant.10jqka.com.cn/view/article/4Z81JJGR1F1581529UVWQAK744)

```python
klines = af.klines.batch(
    symbols, period="1d", count=5000,
    adjust="none",   # 用不复权数据，否则涨跌幅会被复权扭曲
    to_dataframe=True, show_progress=True,
)
# ...
if df["ret"].iloc[i] >= 0.095:  # 涨停（含误差）
```

原文明确指出的两点是对的：**必须用不复权数据判涨停**；以及「实际因为四舍五入，涨幅在 9.5%–10.5% 之间就可以算涨停」。但 `>= 0.095` 这个单阈值**无法区分 20cm 板与 10cm 板**，也会把创业板 9.5% 的非涨停误判成涨停。**本文推断：单阈值法只适合快速原型，生产必须走 `high_limit` 字段或板块化的比例表。**

#### （c）平台字段法（BigQuant）

来源：[概念热度驱动的打板追涨停量化策略【分钟频】 - BigQuant](https://bigquant.com/wiki/doc/4PEdjWUGUf)

```sql
qualify
    price_limit_status = 3                    -- 当日涨停
    and (m_lag(price_limit_status, 1) = 3     -- 近 1-4 日内曾涨停
      or m_lag(price_limit_status, 2) = 3
      or m_lag(price_limit_status, 3) = 3
      or m_lag(price_limit_status, 4) = 3)
    and instrument[:2] != '68'                -- 剔除科创板
    and instrument[-2] != 'B'                 -- 剔除 B 股
    and st_status = 0                         -- 剔除 ST 股票
    and (upper_limit - high)/upper_limit <= 0.03  -- 封板有效（距涨停价≤3%）
    and amount >= 5000000                     -- 成交额≥500万（流动性保障）
    and total_market_cap >= 2000000000        -- 市值≥20亿（规避小盘风险）
```

**注意这里 `(upper_limit - high)/upper_limit <= 0.03` 的注释写的是「封板有效」，但它实际判的是「最高价接近涨停价」，即"曾摸板"，不是"封住"。** 这类命名与语义不一致的写法在打板代码里非常常见，会直接污染因子含义。

#### （d）通达信：板块差异化的涨停价（`ZTPRICE`）

来源：[【通达信指标】大阴反包指标公式 - 万物公式网](https://gsw007.com/post/74892.html)

```
DYFB1:=IF(NAMELIKE(ST) OR NAMELIKE(*ST), 0.05, IF(CODELIKE(688) OR CODELIKE(30), 0.2, IF(CODELIKE(8), 0.3, 0.1)));
DYFB2:=REF(C,1);
DYFB3:=ZTPRICE(DYFB2, DYFB1);
DYFB10:=C>=DYFB3;
```

这是通达信里少见的**正确处理板块差异**的写法：ST 用 5%、688/30 开头用 20%、8 开头用 30%、其余 10%，再交给 `ZTPRICE()` 按交易所规则舍入。是 §4.1 的公式版对照。

---

### 1.2 区间涨幅 / 距 N 日高点位置 / 回撤率

#### 通达信原文（完整龙回头选股公式）

来源：[龙回头战法深度解析与选股公式实现](http://set.baidu.com/view/4226dc333569a45177232f60ddccda38376be1c3.html)（**注意：该页为内容农场聚合页，无作者、无回测、无数据来源，可信度「低」；此处仅作为公式文本引用**）

```
INPUT:N1(5,3,10),N2(20,10,30);   //N1为连板统计周期, N2为涨幅统计周期
涨停:=C/REF(C,1)>1.095 AND C=H;   //排除炸板情况
连板天数:=COUNT(涨停,N1)>=2;
最高价:=HHV(H,N2);
回调幅度:=(最高价-L)/最高价<0.382;
调整天数:=BARSLAST(涨停) BETWEEN 3 AND 10;
量能比:=V/MA(V,5)<0.6 AND V<REF(V,BARSLAST(涨停));
均线支撑:=C>MA(C,10) AND L<MA(C,10)*1.02;
XG:连板天数 AND 回调幅度 AND 调整天数 AND 量能比 AND 均线支撑;
```

这份公式**已经覆盖了本次任务问的全部五类因子**（连板计数、区间高点回撤、调整天数、缩量比、均线支撑），是最完整的一份可抄文本。三个值得抄的细节（原文自述）：

- `涨停:=... AND C=H` 用「收盘=最高」过滤炸板；
- 量能比用 5 日均量做基准而不是单日；
- 均线支撑允许 2% 下影穿透（`L<MA(C,10)*1.02`），避免机械判断漏掉插针。

**但它的问题也很明显（本文推断）**：`C/REF(C,1)>1.095` 是 10cm 假设，20cm 板会漏；`HHV(H,N2)` 的窗口 N2=20 与「第一波起点」无关，是拍脑袋；`回调幅度<0.382` 用的是「距 20 日高点的回撤 < 38.2%」，而不是「回撤 / 第一波涨幅」，两者语义不同。

#### 「距 N 日高点位置」的连续型写法

`Close / rolling_max(High, N)`——本仓库已有 `PTH252` 走同一形式，其学术源头（52 周高点，George & Hwang 2004）与局限已在 [`2026-08-pth252-primary-source-validation.md`](2026-08-pth252-primary-source-validation.md) 核验过，此处不重复。**短线版把 N 从 252 换成 20/60 即可，但要注意这是换了一个完全不同的现象，不能继承 52 周高点的文献背书。**

#### 二值突破因子（现成宽表）

来源：[henrylin99/screener-offline-data · SKILL.md](https://github.com/henrylin99/screener-offline-data/blob/main/SKILL.md)

该仓库落盘的 parquet 宽表内置 `break_high_20/60/120/250`（突破 N 日新高）、`consec_up_3/5`、`consec_up_days`、`vol_ratio_5`，以及 125 个 `pattern_*` 二值列，含 `pattern_first_limit`（首板）、`pattern_multi_limit`（连板）、`pattern_one_word_limit`（一字板）、`pattern_bullish_engulfing`（阳包阴）。README 明确给出的用法：

```python
df = load_day("20260519")
df[(df.pattern_first_limit == 1) & (df.pe < 20)].sort_values("pe")
```

以及信号回测口径（原文）：「取某个 `pattern_*` 或 `break_high_*` 信号当天命中的股票，用次日起 N 日的复权价 `close_qfq` 算前瞻收益（`groupby('ts_code')` 后 shift）」。**注意它用的是 `close_qfq`（前复权），这在跨日期重跑时会漂移，见 §4.2。**

---

### 1.3 缩量判定

现有实现按严格程度从松到紧：

| 写法 | 原文 | 出处 |
|---|---|---|
| 双条件缩量 | `缩量:=V<REF(V,1) AND V<MA(V,5);` | [分析家/通达信 龙回头选股](https://www.gspt.com/gs/16044)（搜索摘要给出的通用逻辑） |
| 均量比 + 对比涨停日 | `量能比:=V/MA(V,5)<0.6 AND V<REF(V,BARSLAST(涨停));` | [同上龙回头公式页](http://set.baidu.com/view/4226dc333569a45177232f60ddccda38376be1c3.html) |
| 缩至第一波均量 1/3 | 「回调期间成交量需大幅萎缩，最好能缩减至第一波上涨时平均成交量的三分之一以下」 | [【真龙第二波】- 好公式网](https://www.goodgongshi.com/tongdaxingongshi/119584.html) |
| 缩至 50% 以下 | 「缩减至首波平均量能的 50% 以下」 | [龙回头战法源码视频精讲 - 夜雨聆风](https://www.yeyulingfeng.com/493875.html) |
| 20 日均额比 | `vol_ratio = amount / prev_20d_mean_amount`，分组 `<1.5 / 1.5-3 / >3` | [同花顺量化社区](https://quant.10jqka.com.cn/view/article/4Z81JJGR1F1581529UVWQAK744) |

**这里就是参数分歧最严重的地方：同一个「缩量」，阈值从 0.33 到 0.6 到 1.0 都有人写，没有任何一家给出扫描依据。** 见 §5。

一个值得抄的相关写法（换手率分档，来自实盘系统而非公式论坛）：

来源：[ainstainst/limit-up-sniper README](https://github.com/ainstainst/limit-up-sniper)（同一项目另一镜像 [guoyaohua/limit-up-sniper](https://github.com/guoyaohua/limit-up-sniper)）

| 过滤层 | 规则 | 不通过时 |
|---|---|---|
| 换手率 | 低于 3% | 跳过 |
| 换手率 | 15%–25% | 进入观察名单，仓位减半 |
| 换手率 | 不低于 25% | 当日黑名单 |
| 时段量比 | 按连续竞价**已交易分钟归一化**后低于 0.7 | 跳过 |

「按已交易分钟归一化的时段量比」这个细节很关键：盘中直接拿累计量除以昨日全天量是错的，必须按已过去的交易分钟数折算。

---

### 1.4 均线支撑判定

```
{回踩不破 MA10，允许 2% 下影穿透}
均线支撑:=C>MA(C,10) AND L<MA(C,10)*1.02;
```
出处同 §1.2。

「回踩后二次站上」的事件式写法（原文思路）：

来源：[通达信"龙回头战法"指标源码视频精讲 - 夜雨聆风](https://www.yeyulingfeng.com/493875.html)

> 1. 识别强势连板：在最近一段时间内（如 8 天），出现多次涨停（如 5 次以上）
> 2. 等待回调：连板后股价自然回落，但不破关键均线（如 10 日均线）
> 3. 买入信号：当某日**开盘价在 10 日均线下方、收盘价站上 10 日均线**时，视为回调结束、二次启动

```
MA10:=MA(CLOSE, 10);
{成交量放大验证}量能验证:=VOL > MA(VOL, 5);
{换手率过滤}换手率:=VOL/CAPITAL*100; 活跃度:=换手率 > 3;
{波动率未急剧扩大}波动率:=STD(CLOSE, 10); 流畅度:=波动率 < REF(波动率, 5)*1.2;
最终信号:=龙回头信号 AND 量能验证 AND 活跃度 AND 流畅度;
```

**「开盘在 MA10 下、收盘在 MA10 上」是一个只有收盘后才成立的条件——这本身不是前视（收盘后选股次日买是合法的），但如果回测里当天收盘价成交，就是前视。** 见 §3。

对「回踩到哪条均线」，几家说法冲突且都无数据支撑：

- 「股价回落必须要有 **10 日线**的支撑」——[天下第一龙回头 - cfchi](https://m.cfchi.com/formula/futuzhibiao/17465.html)
- 「正常情况下看 **20 日均线**支撑和 **60 日均线**支撑……20 日和 60 均线处企稳的概率最大」——[龙头二波选股方法 - 拾荒网](http://www.10huang.cn/buy/53273.html)（原文自称"经过团队的深入研究和众多案例的走势数据分析得出"，但**未给出任何样本量或统计表**）
- 「**8 日均线**在灵敏度与稳定性之间取得了更好的平衡」——[龙回头吃肉 - 擒牛指标公式网](https://www.cjm99.com/zb/148032.html)

**结论：均线周期选择目前无可靠外部依据，属于必须自己扫描的参数。**

---

### 1.5 反包 / 首阴反包的形态判定

#### （a）基础阳包阴

来源：[反包龙选股 - 通达信指标网](https://www.tdxzb.com/?id=11305)

```
{原版}
昨日阴线:=REF(C,1)<REF(O,1);
今日阳线:=C>O;
反包:=C>REF(O,1) AND O<REF(C,1);
量能:=V>REF(V,1)*1.5;
选股: 反包 AND 量能 AND 非ST;

{修复版}
量能:=V>REF(V,1)*2.0;
站上:=C>MA(C,20);
非ST:=NOT(NAMELIKE('ST')) AND NOT(NAMELIKE('*ST'));
OLD:=BARSCOUNT(C)>120;
选股: 反包 AND 量能 AND 站上 AND 非ST AND OLD;
```

原文声称「原版量能 1.5 倍太松+不要求站线。选 B+B（量 2 倍+站 MA20），**胜率从 45.5%→54.5%**」。**这两个数字没有样本量、没有区间、没有代码、没有收益口径，可信度「存疑」，不应引用。** 但 `BARSCOUNT(C)>120`（上市满 120 根 K 线）这个次新股过滤是对的（§4.4）。

#### （b）大阴反包（带涨停价计算，质量较高）

来源：[【通达信指标】大阴反包指标公式 - 万物公式网](https://gsw007.com/post/74892.html)

```
DYX1:=IF(NAMELIKE(ST) OR NAMELIKE(*ST), 0.05, IF(CODELIKE(688) OR CODELIKE(30), 0.2, IF(CODELIKE(8),0.3,0.1)));
DYX2:=REF(C,1);
DYX3:=ZTPRICE(DYX2, DYX1);
DYX10:=C>=DYX3;                                  {今日涨停}
DYX11:=V/REF(V,1)>2 AND C<O;                     {放量阴线（量翻倍 + 收阴）}
DYX12:=REF(DYX10,1) AND DYX11;                   {前一日涨停 + 当日放量阴 => 首阴日}
DYX13:=BARSLAST(DYX12);                          {距首阴日过去几天}
DYX14:=V/REF(V,1)>1.5 AND C>REF(C,1) AND C>O;
DYX15:=COUNT(DYX14,DYX13)>=2;
大阴反包:CROSS(C,REF(O,DYX13)) AND REF(HHV(C,DYX13)<REF(O,DYX13),1) AND DYX15 AND DYX13<100;
```

这份的可抄点：**用 `BARSLAST` 定位「首阴日」再用 `REF(O, DYX13)` 回取那一天的开盘价做反包基准**，比固定 `REF(O,1)` 泛化性强得多（首阴之后可以隔几天再反包）。且它声称「无未来函数，信号不漂移」。

#### （c）龙头首阴反包（参数化连板数 + 史上天量）

来源：[龙头首阴反包战法 - 好公式网](https://www.goodgongshi.com/tongdaxingongshi/113252.html)、[智尊版 - 通达信指标网](https://www.tdxzb.com/?id=7466)

作者原文给出的定义（源码本身需下载，两页均未在网页正文贴出完整源码，仅贴出参数说明）：

> 首先，首阴前面必须有涨停板…… 在代码中我将放开权限让大家灵活设置是至少多少连板（参数 `LBS`）。
> 其次是首阴，首阴定义为**涨停板之后的第一根阴 K 线**，且当天成交量必须是**史上天量**，也就是**上市以来最高成交量柱子**……
> 智尊版选股器**不要求当天能完全反包前一天天量阴 K 线实体**，只反包实体一半以上即可。

作者自己指出的两个实操约束（值得记）：

> 「龙头首阴反包战法，只有等反包了前阴才具有确定性，**不要想着去尝试龙头首阴当天低吸**，那样确定性不高，很容易被 A 杀」
> 「（大众交通）7 月 10 号这票**一字涨停板，你很难买进**」——作者本人承认信号命中但不可成交。

**「史上天量」这个条件在 pandas 里最容易写成前视**：`df['vol'].max()` 是全样本最大值，必须写成 `df['vol'].expanding().max().shift(1)`。通达信的 `HHV(V, 0)` 语义是「到当前 bar 为止」，天然安全；移植到 Python 时这个语义会丢。**这是本次调研发现的一个高危移植陷阱。**

---

### 1.6 人气 / 热度的量化代理变量

#### （a）「涨停基因」五因子（可信度较高：来自实盘工程项目，且显式声明防泄漏）

来源：[ainstainst/limit-up-sniper README](https://github.com/ainstainst/limit-up-sniper)

对最近 250 个交易日计算，各因子转横截面百分位后加权：

| 因子 | 权重 | 想回答的问题 |
|---|---:|---|
| 涨停次日收盘溢价超过 5% 的比例 | 25% | 封板后是否常有强溢价 |
| 首板次日收盘红盘率 | 25% | 首板次日是否容易维持正收益 |
| 首板封板率 | 25% | 触板后是否容易封住 |
| 首板涨停/炸板后的次日开盘平均溢价 | 15% | 次日是否有可兑现空间 |
| 近 250 日涨停次数 | 10% | 股性是否活跃 |

排除规则（原文）：首板封板率不高于 70%、近一年没有涨停、历史涨停后开盘和收盘平均溢价均低于 1% 的股票，按综合分降序保留最多 1000 只。

**关键一句（原文）：「所有"次日"统计只在结果已经可见后进入特征，避免把未来数据泄漏进当日选股。」** 这是本次调研看到的**唯一一个主动声明这一点的开源项目**。

#### （b）龙头识别五维评分

来源：[sunshanggege/dragon-quant](https://github.com/sunshanggege/dragon-quant)（同项目镜像 [edgarlxy](https://github.com/edgarlxy/dragon-quant) / [gitBingxu](https://github.com/gitBingxu/dragon-quant)，PyPI：[dragon-quant](https://pypi.org/project/dragon-quant/)）

| 维度 | 权重 | 门槛 | 衡量 |
|---|---|---|---|
| 带动性 | 30% | 40 | 封板最早 + 带动板块（脉冲-跟随因果检测）+ 板块共鸣 |
| 领涨性 | 25% | 40 | 连板最多 + 5 日涨幅在板块内分位 |
| 抗跌性 | 15% | 35 | 大盘 + 板块双基准横盘稳住 + 率先起飞 |
| 流动性 | 20% | 35 | 换手充沛度 + 封板质量（封单/开板次数，一字不罚） |
| 资金承接 | 10% | — | 跨板块虹吸 |

聚合方式：**四大特征任一 < 门槛 → 一票否决**；通过者按综合分降序。「门槛 + 加权」两段式比纯加权更抗单维度刷分，这个结构本身值得借鉴。

#### （c）龙虎榜作为「被市场关注」的硬阈值代理

**上榜条件本身就是一组现成的、交易所定义的人气阈值**，比自己拍换手率分位更客观。深交所原文（[深交所交易规则 2023 年修订征求意见稿](https://docs.static.szse.cn/www/aboutus/trends/news/W020230201595730281095.pdf)，第 5 章）：

- 当日收盘价涨跌幅偏离值达到 ±7% 的各前五只主板股票；创业板为收盘价涨跌幅 ±15% 的前五只
- 当日价格振幅达到 15% 的各前五只主板股票；创业板为振幅 30% 的前五只
- 当日换手率达到 20% 的各前五只主板股票；创业板为换手率 30% 的前五只
- 连续三个交易日内日收盘价涨跌幅偏离值累计达到 ±20%（创业板 ±30%）；**ST 和 \*ST 主板股票为 ±12%**

上交所科创板对应条款（[上交所交易规则（券商站点托管 PDF）](https://zxyoss.csc108.com/csc108-istp/istp/doc/unknown/e6c32c60f61c4bbd9d1d0a359e39ad5d.pdf) §6.9）：日收盘价格涨跌幅达到 ±15% 的各前 5 只、日价格振幅达到 30% 的前 5 只、日换手率达到 30% 的前 5 只。

**可信度：高（交易所原文）。** 注意深交所那份是 **2023 年修订征求意见稿**，不是终稿，落地前需与现行规则再核一次。

#### （d）龙虎榜因子的公开回测数字

来源：[中泰证券-金融工程专题报告：基于龙虎榜的 A 股资金结构分析与应用-241210](https://www.nxny.com/report/view_5830698.html)（**注意：本次只核到第三方研报聚合站的转载页，未取得中泰官方 PDF，可信度降为「中」**）

- 全 A 择时：判别条件 `p < MA(p) and q > MA(q) + STD(q)*1.5`，2018 年至今共 12 次交易，其中 10 次正收益
- 龙虎榜优质游资席位驱动的一级行业轮动：**2020 年至今年化 20.7%，Sharpe 0.81**；2024 年 9 月至该报告日胜率 71.4%、收益率 31.1%、相对上证超额 11.8%

同时必须记住这份对龙虎榜因子的方法论警告（[约投顾](https://ag.yueniuzq.com/qa/long-hu-bang-shu-ju-xian-shi-ji-gou-mai-r-s2-60613/)，可信度低，但论点成立）：**龙虎榜仅披露异常波动或换手率异常的股票，因子天然带选择性偏差**；控制市值、市净率、6 个月动量、换手率、波动率之后若不再显著，说明它只是这些因子的代理变量。

---

## 2. 回测证据汇总表

> **重要前提：下表中没有任何一行是「龙回头/回撤低吸」形态的回测。** 全部是打板/接力/涨停后持有类。这一族形态的公开回测证据，本次调研**未找到可靠来源**。

| # | 来源 | 形态/策略 | 区间 | 样本量 | 关键结果 | 可信度 | 主要问题 |
|---|---|---|---|---|---|---|---|
| 1 | [百果量化：首板及炸板数据统计](http://100apple.net/article/detail.html?id=534&sort=new) | 首板打板，按首次封板时间分组，看次日开盘溢价 | 2024-01-01 ~ 2025-01-22 | 25,019 条记录（涨停 16,043 / 炸板 8,976），总体炸板率 35.88% | 14:00–15:00 组次日均溢价 **+0.91%**（n=7364，成功率 50.60%，炸板率 35.21%）；9:30–10:00 组 **−0.75%**（n=11036，成功率 44.28%，炸板率 37.37%）；15 分钟粒度最优为 14:00–14:15 **+2.57%**（n=787，成功率 59.34%） | **中** | 溢价分母用当日收盘价而非涨停价（口径不自洽）；炸板样本也按"买在涨停价"计成本；**未扣手续费/印花税**；未处理一字板买不进；只有 1 年多、单一市场阶段 |
| 2 | [ellendan：连板数量分布](https://ellendan.com/2025/01/07/shi-yong-pandas-fen-xi-a-gu-lian-ban-shu-liang-de-fen-bu/) | 连板高度分布（非策略） | 近 400 个交易日（截至 2024-12-31） | 全 A，止步于 2 连板的机会 2,214 次 | **「路过 2 连板、顺利达成 6 连板的股票机会只有 3.1%」** | **中** | 只覆盖 2024-10 之后转暖的单一窗口，作者自己指出这段"4 连板以上出现频率增多"；用 `close == high_limit` 判涨停，ST 整段剔除 |
| 3 | [中泰证券（转载页）](https://www.nxny.com/report/view_5830698.html) | 龙虎榜优质游资席位 → 行业轮动 | 2020 年至 2024-12 | 未披露 | 年化 **20.7%**，Sharpe **0.81** | **中** | 未取得官方 PDF 原件；未披露成本假设与换手 |
| 4 | [BigQuant：概念热度驱动的打板追涨停【分钟频】](https://bigquant.com/wiki/doc/4PEdjWUGUf) | 概念热度 + 连续涨停 + 开盘涨幅≥2% 入场，持仓≥1 天且浮盈≥5% 止盈 | 2024-09 ~ 2025-03 | 未披露交易笔数 | 年化 **82.43%**，最大回撤 **−20.74%** | **低** | **仅 6 个月**、单一牛市窗口；未披露滑点/成交假设/胜率；策略要求"当日涨停"才进候选，次日以开盘后涨幅确认买入，存在成交可行性问题 |
| 5 | [HiRenyi/EasyQuant](https://github.com/HiRenyi/EasyQuant) | 「首板高开-低开-弱转强」（聚宽网页自动化回测） | **未披露** | 未披露 | 年化 **158.72%**，最大回撤 **43.97%**，Sharpe **2.62** | **低** | 无区间、无成本、无成交假设；README 表格是 28 个策略按 Sharpe 排序的排行榜，属于典型的多重检验挑选（§5） |
| 6 | [pandaaiquant：打板策略优化路径的实证研究](https://www.pandaaiquant.com/community/article/874) | 策略一"闪电出击首板" vs 策略二"龙头战法二板" | 自述 2015-01-01 ~ 2025-01-01 | 策略一 150 次交易 | 策略二：总收益 755.20%、年化 **24.71%**、最大回撤 **−13.43%**、Sharpe **1.546**、日胜率 **0.771**、盈亏比 **3.904** | **存疑** | ①§3.2 写回测期 2015-01-01~2025-01-01，§5 又写"2016 年 1 月 1 日至 2025 年 12 月 31 日"，**自相矛盾**；②称策略一日胜率 0.503，却又写"盈利次数 122 远多于亏损次数 28"（122/150=81%），**自相矛盾**；③正文反复用"推演""推测""可以推断"等词，疑似由代码逻辑反推出的生成式数字；④策略一自身代码用 `LimitOrderStyle(high_limit)` 涨停价限价单成交，作者自己也承认"回测中的涨停价成交假设过于乐观" |
| 7 | [同花顺量化社区：我回测了 A 股 10 年的追涨停策略](https://quant.10jqka.com.cn/view/article/4Z81JJGR1F1581529UVWQAK744) | 涨停次日开盘买入 | 名义 10 年，仅 16–20 只大盘活跃股 | 未披露 | **文章只给了代码和"你可能会看到的结果"，没有贴出任何一次真实运行输出**；文中"胜率 40%–50%""连板率 10%–20%"是描述性区间而非实测值 | **低** | 属于工具软文模板；但代码本身与 `adjust="none"` 的提醒是对的；股票池只有大盘股，与打板真实标的池完全不符 |
| 8 | [ainstainst/limit-up-sniper](https://github.com/ainstainst/limit-up-sniper) | 首板排板/扫板实盘系统 | 12 个交易日 | — | **README 顶部警告原文：「现有迁移数据只有 12 个交易日，且缺少完整买卖配对与连续净值，尚不能证明本轮升级提高了封板率或收益率。」** | **高（作为负面证据）** | 这是本次调研看到的最诚实的一份说明 |
| 9 | [反包龙选股 - 通达信指标网](https://www.tdxzb.com/?id=11305) | 阳包阴反包 | 未披露 | 未披露 | 「胜率从 45.5%→54.5%」 | **存疑** | 无样本量、无区间、无代码、无收益口径 |
| 10 | [首版打二版模式胜率统计 - 今日头条](https://www.toutiao.com/article/7485538804267401780/) | 首板打二板 | 2021–2023 沪深 | 自述 12,138 次 | 「10:00 前封板晋级概率 63.7%，10:00–14:00 为 41.5%，14:00 后 28.4%」 | **存疑** | 数字过于整齐；**与来源 #1（有源码、有样本量）的结论方向完全相反**——#1 显示 9:30–10:00 组次日溢价最差（−0.75%）、14:00–15:00 最好（+0.91%）。两者口径不同（晋级率 vs 次日开盘溢价），但仍需警惕 #10 无从核验 |

### 明确的「未找到可靠来源」清单

- **龙回头 / 二波 / 缩量回踩低吸形态的公开回测**（含区间、样本量、胜率、盈亏比、年化、回撤）：未找到。所有找到的相关页面（分析家公式网、公式平台网、掌心公式、cfchi、擒牛指标网、夜雨聆风、拾荒网）**均为公式分享/教学页，无回测**。
- **首阴反包形态的公开回测**：未找到。相关页面均为通达信指标下载页，仅有个案截图。
- **针对上述形态参数（回撤阈值 / 调整天数 / 缩量比 / 均线周期）的公开敏感性扫描**：未找到。
- **对这类策略过拟合/幸存者偏差的专门批评文献**：未找到形态专属的；只找到通用的回测陷阱文献（见 §3、§5），其结论适用但非针对性证据。

---

## 3. 前视偏差（look-ahead bias）检查清单

### 3.1 这一族形态的专属高危项

| # | 陷阱 | 为什么这一族特别容易踩 | 规避写法 |
|---|---|---|---|
| **L1** | **用当日最低价/最高价当买入价** | **有真实开源项目这么做**：`dragon-quant` 回测流程原文为「找入选后第一个非一字板日（`high != low`）**以最低价买入**」（[README](https://github.com/sunshanggege/dragon-quant)、[PyPI](https://pypi.org/project/dragon-quant/)）。"回撤低吸"这个策略名本身就在诱导人写 `if low <= target: buy(low)` | 只允许 `T` 日收盘后出信号、`T+1` 开盘价成交；或用 `T+1` 的限价单 + 「当日 `low <= 限价`」才算成交，且成交价取 `min(限价, T+1 open)`。同花顺社区那篇也点到了：「不要编写类似 `if price <= low: buy` 的逻辑」（[QMT 回测教程](https://easyquant.ai/e/qmt/avoid-lookahead-bias-in-backtest)） |
| **L2** | **涨停价买入被当作必成交** | 打板/反包类策略的入场点就是涨停价。`pandaaiquant` 报告里的策略一直接 `order_value(stock, v, LimitOrderStyle(high_limit))`，作者自己承认"在实盘中可能无法成交，尤其在'秒板'或排单很厚的情况下"（[出处](https://www.pandaaiquant.com/community/article/874)） | 用队列穿越模型。`limit-up-sniper` 的写法（原文）：只有满足 `下单后新增累计成交手数 ≥ 下单时前方队列手数 + 本单手数` 且确认 Tick 仍处封板状态，才确认整单成交；「封单减少可能只是撤单，因此不算成交」（[README](https://github.com/ainstainst/limit-up-sniper)） |
| **L3** | **一字板买不进** | 龙回头/首阴反包的信号日经常就是一字板。首阴反包公式作者自己承认「7 月 10 号这票一字涨停板，**你很难买进**」（[好公式网](https://www.goodgongshi.com/tongdaxingongshi/113252.html)） | 显式判 `open == high == low == high_limit` 或 `high == low` 并强制不成交；参考 `screener-offline-data` 的 `pattern_one_word_limit` 列 |
| **L4** | **封单额、首次封板时间、龙虎榜的可见时点** | 「封单金额/成交额」「首次封板时间」这类因子是**盘中逐 Tick 变化**的；日线复盘表里的"封单额"通常是收盘快照。龙虎榜是**收盘后**才公布 | 盘中因子只能用「决策时刻之前」的快照；龙虎榜因子的 `effective_from` 必须是 **T 日收盘后**，用于 T+1 决策。参照 PIT 库的 `as_of(t)` 语义（[quant67](https://quant67.com/post/quant/06-survivorship-bias/06-survivorship-bias.html)） |
| **L5** | **「史上天量」写成全样本 max** | 首阴反包公式的核心条件之一。通达信 `HHV` 语义天然是「到当前 bar」，移植成 pandas 的 `df.vol.max()` 就是全样本泄漏 | `df['vol'].expanding().max().shift(1)`；并在 CI 里加断言（见下 L11） |
| **L6** | **「收盘站上 MA10」当天成交** | §1.4 那条信号的定义就依赖收盘价 | 信号日 = T，成交日 = T+1 开盘 |
| **L7** | **涨停确认用了当天收盘价** | `close == high_limit` 只有收盘后才知道 | 同 L6；若要盘中确认，只能用「当前价 == 涨停价 且已封 N 秒」的实时口径 |

### 3.2 通用项（同样适用）

| # | 陷阱 | 规避 | 出处 |
|---|---|---|---|
| L8 | 复权口径混用 | 回测标记价用**后复权**，下单价用**不复权 + 复权因子转换**，看图用前复权；字段名强制带口径后缀 `close_raw` / `close_fwd` / `close_bwd` | [quant67](https://quant67.com/post/quant/06-survivorship-bias/06-survivorship-bias.html) §5.6、§8.2 |
| L9 | 幸存者偏差 | 建 `securities_master`（含 `inception_date` / `delisting_date` / `delisting_reason` / `successor_id`），每日生成 `tradable_universe(t)`，调仓步只接受它作候选集 | 同上 §1.4 |
| L10 | 全样本归一化 / `rolling(center=True)` / `shift(-1)` 混进特征 | `expanding(min_periods=...)` 或滚动窗口；`center=False`；任何 `shift(负数)` 列打 `TARGET-ONLY` 标签 | 同上 §3.2–3.4 |
| L11 | 无法靠人眼发现的未来函数 | **CI 断言**（原文）：`out = feature(view_at(t))`；`out_extended = feature(view_at(t, extended_with=future_data))`；`assert (out == out_extended).all()` | 同上 §8.3 第 6 条 |
| L12 | 判断不出「是真 alpha 还是泄漏」 | **单 K 线位移测试**：把每一次成交都向后挪一根 K 线，如果表现崩溃，说明你一直在过去做交易 | [前视偏差：一根 K 线的错误如何从纯噪声中凭空制造出 15 的夏普比率](https://marketmaker.cc/zh/blog/post/look-ahead-bias-taxonomy/)（该文报告：仅同 K 线成交就能从纯噪声造出 +14.79 的年化夏普，把 −0.74 变成 +14.79；仅捕获信号 K 线四分之一就能从 −0.74 拉到 +3.90） |
| L13 | ST 标记 / 行业分类 / 指数成分用了当前快照 | 全部走 `as_of` 区间表 | [quant67](https://quant67.com/post/quant/06-survivorship-bias/06-survivorship-bias.html) §2.4 |
| L14 | 停牌期"按收盘价成交" | `tradable_universe(t)` 剔除停牌；复牌首日单独判断（部分情况只允许集合竞价） | 同上 §6.1 |
| L15 | 擦边价格触发幻影信号 | 1 股成交把价格瞬间打到涨停又回落，会进日线 `high`。若策略用 `high` 做触发条件就会产生幻影信号 | 同上 §6.4 |
| L16 | 流动性假设 | 单标的单日交易额 ≤ 当日成交额 × 5%~10% | 同上 §6.5、§8.2 |

---

## 4. A 股工程细节 gotcha 清单

### 4.1 涨跌停价计算

#### 交易所原文（可信度：高）

**计算公式与舍入规则**（上交所交易规则 §3.3.13、§3.3.17，[券商站点托管 PDF](https://zxyoss.csc108.com/csc108-istp/istp/doc/unknown/e6c32c60f61c4bbd9d1d0a359e39ad5d.pdf)；深交所 §3.3.14、§3.3.19，[深交所 2023 年修订征求意见稿](https://docs.static.szse.cn/www/aboutus/trends/news/W020230201595730281095.pdf)，两份措辞一致，可互相交叉验证）：

> 涨跌幅限制价格的计算公式为：**涨跌幅限制价格 = 前收盘价 ×（1 ± 涨跌幅限制比例）**
> 涨跌幅限制价格、有效申报价格范围的计算结果按照**四舍五入原则取至申报价格最小变动单位**。
> **涨跌幅限制价格与前收盘价之差……的绝对值低于申报价格最小变动单位的，以前收盘价……增减一个申报价格最小变动单位计算相应价格。**

**比例表**（各条原文出处如下）：

| 品种 | 比例 | 出处 |
|---|---|---|
| 沪深主板股票 | 10% | 上交所 §3.3.13；深交所 §3.3.13 |
| 创业板股票 | 20% | 深交所 §3.3.13 |
| 科创板股票 | 20% | 上交所交易规则第 6 章（科创板专章） |
| **主板风险警示股票（ST/\*ST）** | **5%** | 深交所 §4.5.5 |
| **主板退市整理股票** | **10%**（不是 5%！） | 深交所 §4.5.5 |
| **创业板风险警示股票、退市整理股票** | **20%** | 深交所 §4.5.5 |
| 北交所股票 | 30% | 二手来源：[叩富网](https://licai.jiantou8.com/ask/qa_6446884.html)、[新浪财经](https://finance.sina.com.cn/roll/2025-07-21/doc-infhfmip3240076.shtml?froms=ggmp)。**未取得北交所交易规则原件，可信度「中」** |

**不设涨跌幅限制的情形**（上交所 §3.3.13 原文）：
> （一）首次公开发行上市的股票上市后的**前 5 个交易日**；（二）进入退市整理期交易的退市整理股票**首个交易日**；（三）退市后重新上市的股票**首个交易日**。

#### ⚠️ 一个必须自行核验的冲突

一篇低可信度技术站文章称「已被实施风险警示的主板股票（含 ST、\*ST），**自 2025 年 7 月起，涨跌幅限制已由 ±5% 调整为 ±10%**」（[Golang 学习网](https://17golang.com/article/592422.html)）。**该说法与本文取得的交易所原文（主板 ST = 5%）直接冲突，且该文未给出任何监管文件编号。本文不采纳，标记为「存疑，需以现行交易所规则原件核验」。**

**这个冲突恰恰说明了下面这条工程结论。**

#### 工程结论（本文推断，但由上述原文支撑）

1. **不要在代码里硬编码涨跌幅比例。** 优先直接读数据源的 `high_limit` / `low_limit` / `upper_limit` 字段（聚宽、BigQuant、多数商业数据源都提供）。ellendan 与 BigQuant 的代码都是这么做的。
2. 若必须自算，比例表必须是**带生效日期的版本化表**（`rate_table(code, as_of_date) -> rate`），而不是一个常量字典——ST 比例、创业板/科创板注册制、北交所都发生过制度变更。
3. **不能用 `round()`。** Python 内置 `round()` 是银行家舍入（四舍六入五成双）：`round(0.125, 2)` 不等于 `0.13`。正确写法（[Python 官方 decimal 文档](https://docs.python.org/zh-cn/3.7/library/decimal.html)）：

```python
from decimal import Decimal, ROUND_HALF_UP

def limit_price(pre_close: str, rate: str) -> Decimal:
    """pre_close / rate 必须用字符串构造 Decimal，避免二进制浮点误差。
    交易所规则：前收盘价×(1±比例)，四舍五入至最小变动单位(0.01)；
    若与前收盘价之差不足一个最小变动单位，则用 前收盘价±0.01。
    """
    prev = Decimal(pre_close)
    tick = Decimal('0.01')
    raw = prev * (Decimal('1') + Decimal(rate))
    px = raw.quantize(tick, rounding=ROUND_HALF_UP)
    if abs(px - prev) < tick:
        px = prev + tick
    return px
```

必须用字符串构造 `Decimal`：`Decimal(2.675)` 拿到的其实是 `2.67499999…`（[官方文档](https://docs.python.org/zh-cn/3.7/library/decimal.html)）。

4. **判涨停时留容差。** 即使算对了，浮点比较仍应写成 `abs(close - high_limit) < 0.005`，而不是 `close == high_limit`。腾讯云那篇给的写法是 `(df["最高"] >= df["涨停价"] - 0.01)`（[出处](https://cloud.tencent.com/developer/article/2659338)）。

5. **别忘了 `1.095` 阈值的板块盲区。** `C/REF(C,1)>1.095` 在创业板/科创板上会把 9.5%~19.9% 的普通上涨误判成涨停——本文§1.2 那份最完整的龙回头公式就有这个 bug。

### 4.2 复权处理

| 口径 | 适用 | 对本形态的具体影响 |
|---|---|---|
| 不复权 | 实盘下单、**判涨停** | 判涨停必须用它；用复权价算涨跌幅会被扭曲（[同花顺社区](https://quant.10jqka.com.cn/view/article/4Z81JJGR1F1581529UVWQAK744) 代码注释） |
| 前复权 | 看图、形态识别 | **「区间涨幅」「距 N 日高点回撤率」「跌破启动位」用前复权会漂移**：前复权以"今天"为基准，历史每发生一次新分红/送转，整段历史被重写一次。同一段「第一波涨幅 55%」明天重跑可能变成 54.2% |
| 后复权 | **回测收益率、因子计算** | 基准点固定在上市日，历史一旦确定不再变化 |

原文（[quant67 §5.3](https://quant67.com/post/quant/06-survivorship-bias/06-survivorship-bias.html)）：
> 用前复权计算长期年化收益……如果你昨天的回测结果是 12.3%，今天因为某只股票分红，重新跑得到 12.1%，差距来源不是 alpha 变了，是基准变了。

**对本族形态的具体后果（本文推断）**：
- 「跌破启动位止损」若用前复权，回测复现性会失效；
- 「回撤率 = (HHV(High,N) - Low) / HHV(High,N)」在**除权日附近**会出现虚假的巨大回撤（若用不复权）或虚假的平滑（若口径混用）；
- **`screener-offline-data` 的信号回测用的是 `close_qfq`（前复权）**（[SKILL.md](https://github.com/henrylin99/screener-offline-data/blob/main/SKILL.md)），复用其结论时要意识到这一点。

后复权因子公式（[quant67 §5.4](https://quant67.com/post/quant/06-survivorship-bias/06-survivorship-bias.html)），与深交所除权参考价公式（[深交所 §4.4.2](https://docs.static.szse.cn/www/aboutus/trends/news/W020230201595730281095.pdf)：`除权(息)参考价 =〔(前收盘价-现金红利) + 配股价格×股份变动比例〕÷(1+股份变动比例)`）一致：

```python
def back_adjust(prices: pd.Series, events: pd.DataFrame) -> pd.Series:
    """events: columns = ['date','div','send','rights','rights_price']"""
    factor = pd.Series(1.0, index=prices.index)
    for _, e in events.sort_values("date").iterrows():
        d = e["date"]
        if d not in prices.index:
            continue
        prev_idx = prices.index.get_loc(d) - 1
        if prev_idx < 0:
            continue
        p_prev = prices.iloc[prev_idx]
        p_adj = (p_prev - e["div"] + e["rights_price"] * e["rights"]) \
                / (1 + e["send"] + e["rights"])
        factor.loc[d:] *= p_prev / p_adj
    return prices * factor
```

### 4.3 一字板 / 无法成交的过滤

- **判定**：`high == low`（`dragon-quant` 用的就是这个：「找入选后第一个非一字板日（`high != low`）」，[README](https://github.com/sunshanggege/dragon-quant)），更严格是 `open == high == low == close == high_limit`。
- **现成字段**：`screener-offline-data` 提供 `pattern_one_word_limit`。
- **回测默认应保守**：涨跌停时封单不成交（[quant67 §8.2](https://quant67.com/post/quant/06-survivorship-bias/06-survivorship-bias.html)：「涨跌停、停牌的成交模拟必须显式开关，默认'保守'——封单不成交、停牌期不能交易」）。
- 若要给"能挤进封单"留概率，quant67 给的示意是乘一个折扣系数（示例用 `0.1`），并建议用 L2 数据统计校准，或直接做 0 成交的悲观假设。

### 4.4 新股 / 次新股

| 做法 | 阈值 | 出处 |
|---|---|---|
| 剔除上市不足 100 天 | 100 自然日 | [limit-up-sniper](https://github.com/ainstainst/limit-up-sniper) |
| 剔除上市后 30 个交易日内 | 30 交易日 | [quant67 §1.5](https://quant67.com/post/quant/06-survivorship-bias/06-survivorship-bias.html)（理由：新股上市后第一个月有特殊交易制度，"如果回测引擎按'普通股'来模拟新股，成交假设会全错"） |
| 通达信 `BARSCOUNT(C)>120` | 120 根 K 线 | [反包龙选股](https://www.tdxzb.com/?id=11305) |

**必须处理的制度事实**：IPO 后前 5 个交易日不设涨跌幅（上交所 §3.3.13）。这意味着这段时间 `high_limit` 字段可能为空/异常，涨停因子会产生垃圾值。

### 4.5 停牌 / 退市 / 借壳

- 停牌：`tradable_universe(t)` 剔除；复牌首日单独判断。
- 退市整理期：涨跌幅比例特殊（主板 10%、创业板 20%、首日不设限，深交所 §4.5.5），且主板风险警示股票**单日累计买入不得超过 50 万股**（深交所 §4.5.4）——对组合级仓位是硬约束。
- 借壳重组：同一代码不同实体，`entity_id` 与 `code` 分开维护（[quant67 §1.6](https://quant67.com/post/quant/06-survivorship-bias/06-survivorship-bias.html)）。对短线形态影响相对小，但「近 250 日涨停次数」这类股性因子会跨越借壳日，含义失真。

---

## 5. 参数敏感性

### 5.1 通用方法论（有可靠来源）

**参数平原 vs 参数尖峰**（[AKQuant 第 11 章](https://akquant.akfamily.xyz/textbook/11_optimization/)，原文）：

> 优秀的策略应该落在参数平原 (Parameter Plateau) 上，而不是参数尖峰 (Parameter Peak) 上……参数平原，是指参数发生微小变化（如均线从 20 变 21）时，绩效指标仍保持稳定；而参数尖峰则相反，参数微小变化就会引起绩效断崖式下跌，这通常意味着过拟合。

**量化判据**（[marketmaker：平台分析](https://marketmaker.cc/zh/blog/post/plateau-analysis-overfitting/)，原文）：
- 「如果 10% 的参数偏移导致不到 10% 的 PnL 下降——参数是稳健的。如果更多——要谨慎。」（敏感度比率 < 1）
- 稳健性得分 R > 0.1；并且必须叠加 Walk-Forward：`PnL_OOS > 50% × PnL_IS`
- 该文还给出一个反直觉但重要的结论：「PnL +300% 的策略 C 具有最差的稳健性得分。'谦虚'的 +55% 策略 A 是最稳健的。」

**Pardo 标准**：「参数在合理范围内变动 20 到 30%，绩效变化不应超过 15 到 20%」；以及 Aronson 2007「参数稳健的策略样本外表现衰减平均只有 25%，而参数敏感的策略衰减超过 60%」——**这两条来自一条社交媒体转述**（[Threads @little_algo_trader](https://www.threads.com/@little_algo_trader/post/DSwpVozEvOX/)），**未核到 Pardo《Design, Testing, and Optimization of Trading Systems》与 Aronson《Evidence-Based Technical Analysis》原书页码，可信度「低」，仅作为量级参考。**

**多重检验**（[quant67 §4.2–4.4](https://quant67.com/post/quant/06-survivorship-bias/06-survivorship-bias.html)）：
> 5 × 4 × 3 = 60 组合，期望里大约会有 3 组靠运气拿到 5% 显著的 Sharpe。挑 best 出来，等于挑出"最幸运的一次"。

对应到本调研的具体现象：**`HiRenyi/EasyQuant` 的 README 就是一张 28 个策略按 Sharpe 降序的排行榜**——这本身是多重检验的教科书案例，第 1 名的 158.72% 年化不能按面值采信。

**参数平原的实操示例**（[BigQuant：用参数平原找到稳健的参数组合](https://bigquant.com/wiki/doc/ck6eowsSL0)）：以低估值+小市值双因子为例，网格扫「持股数 × 持仓天数」，找到「持股 2–4 只、持仓 10–20 天」的连续高收益区间，最终取平原核心（持股 3 只、持仓 15 天，收益 57.5%）而非单点最优。**这是一份可以照抄的扫描工作流，虽然标的策略不是本形态。**

### 5.2 具体到本形态的参数（**无扫描证据，全部为本文判断**）

> ⚠️ 下表右两列是**本文基于来源间一致性做的判断，不是文献结论**。凡是「多家一致」的，说明至少有跨来源共识；凡是「各家冲突」的，说明大概率是各自调出来的。

| 参数 | 各家取值 | 跨来源一致性 | 本文判断 |
|---|---|---|---|
| 前置连板数 | ≥2（[龙回头公式](http://set.baidu.com/view/4226dc333569a45177232f60ddccda38376be1c3.html)）；2–3 个（[cfchi](https://m.cfchi.com/formula/futuzhibiao/17465.html)、[拾荒网](http://www.10huang.cn/buy/53273.html)）；15 日内 ≥1 次（[gspt](https://www.gspt.com/gs/16044)）；可配置 `LBS`（[好公式网](https://www.goodgongshi.com/tongdaxingongshi/113252.html)） | **较一致（2–3）** | 相对稳健，但 ≥2 与 ≥3 的样本量差一个数量级，必须扫 |
| 调整天数 | 3–10 天，理想 5–7（[6o7o](https://www.6o7o.com/?id=3813)、[龙回头公式](http://set.baidu.com/view/4226dc333569a45177232f60ddccda38376be1c3.html)）；3–8 天（[真龙第二波](https://www.goodgongshi.com/tongdaxingongshi/119584.html)） | **较一致** | 3–10 是宽区间，可能是平原；「理想 5–7」是典型的无依据窄化 |
| 回撤阈值 | <38.2%（龙回头公式，且是「距 20 日高点」）；38.2%–61.8% 黄金分割、50% 附近尤为关键（真龙第二波）；「幅度不超过前期涨幅的 38.2%」 | **冲突（口径都不一样）** | **典型的"调出来的"**。斐波那契数字缺乏机制解释；且"距 N 日高点回撤"与"回撤/第一波涨幅"是两个不同的量，各家混用 |
| 缩量比 | `<MA(V,5)`；`V/MA(V,5)<0.6`；「缩至首波均量 50% 以下」；「1/3 以下」 | **严重冲突（0.33 / 0.5 / 0.6 / 1.0）** | **必须扫描**。这是本族形态最不确定的参数 |
| 支撑均线 | MA5 / MA8 / MA10 / MA20 / MA30 / MA60 各有主张（§1.4） | **严重冲突** | 必须扫描；且很可能与市场阶段交互（拾荒网原文就说牛市看 15 日线、震荡市 20–30、熊市 60），若真如此，固定单一均线本身就是错的建模 |
| 下影穿透容差 | `L < MA(C,10)*1.02` | 单一来源 | 2% 无依据，但方向对（避免机械判断），扫 0%~3% |
| 首次封板时间窗口 | 「14:00–14:15 最优」（来源 #1，有 787 样本）vs「10:00 前最优」（来源 #10，无从核验） | **两个来源结论相反** | 不可采信任何一个；若要用，必须自己用本仓库数据重算 |

### 5.3 最低限度的扫描协议（建议）

综合 [AKQuant 第 11 章](https://akquant.akfamily.xyz/textbook/11_optimization/) 与 [marketmaker](https://marketmaker.cc/zh/blog/post/plateau-analysis-overfitting/)：

1. 先按时间切开发集 60% / 验证集 20% / 保留集 20%（[quant67 §4.5](https://quant67.com/post/quant/06-survivorship-bias/06-survivorship-bias.html)）；
2. 只在开发集上做二维网格 + 热力图，找**连续平原**而不是单点最优；
3. 验证集上要求 IR 衰减 ≤ 30%；
4. Walk-Forward 要求 `PnL_OOS > 50% × PnL_IS`；
5. 保留集只看一次，结果就是结果；
6. 记录尝试次数 N，按 Bonferroni（`α' = α/N`）或 Deflated Sharpe 折扣；
7. **每一次扫描完再跑一遍单 K 线位移测试**（L12），确认平原不是泄漏造出来的。

---

## 6. 【产出 a】可直接落地的因子计算函数清单

> 全部按「T 日收盘后可计算，T+1 开盘可执行」设计。输入统一为**不复权 OHLCV + `high_limit` / `low_limit` / `is_st` / `paused` / `list_date`**，收益计算另用后复权序列。

### 6.1 基础层

| 函数名 | 输入 | 输出 | 算法 | 注意事项 |
|---|---|---|---|---|
| `limit_price(pre_close, rate)` | 前收盘（str/Decimal）、比例（str） | `Decimal` 涨/跌停价 | `quantize(0.01, ROUND_HALF_UP)`；差额 < 0.01 时用 `pre_close ± 0.01` | **不得用 `round()`**；`Decimal` 必须字符串构造。优先直接用数据源 `high_limit` 字段 |
| `limit_rate(code, name, as_of)` | 代码、名称、日期 | `Decimal` 比例 | 版本化查表：主板 0.10 / 创业板·科创板 0.20 / 北交所 0.30 / 主板 ST 0.05 / 主板退市整理 0.10 / 创业板 ST·退市整理 0.20 | **必须带 `as_of`**（ST 比例有变更传闻，见 §4.1）；IPO 前 5 日、退市整理首日、重新上市首日**返回 None（不设限）** |
| `is_limit_up(row)` | 单日行情 | bool | `abs(close - high_limit) < 0.005` | 不要用 `==`；不要用 `pct_chg > 0.095` 单阈值 |
| `is_touched_limit(row)` | 单日行情 | bool | `abs(high - high_limit) < 0.005` | 与 `is_limit_up` 区分开，不要混用命名 |
| `is_broken_limit(row, prev)` | 当日 + 昨日 | bool | `is_touched_limit(row) and not is_limit_up(row)` | 炸板 |
| `is_one_word(row)` | 单日行情 | bool | `high == low`（严格版再加 `== high_limit`） | 回测中该日强制不可成交 |
| `is_tradable(code, t, ctx)` | 代码、日期、上下文 | bool | 未停牌 ∧ 已上市满 N 交易日 ∧ 未退市 ∧ 非一字 ∧ 非涨跌停封死 | 默认保守：`limit-up-sniper` 用 100 天、`quant67` 用 30 交易日 |

### 6.2 涨停/连板层

| 函数名 | 输入 | 输出 | 算法 | 注意事项 |
|---|---|---|---|---|
| `consec_limit_days(df)` | 单票日线序列 | `Series[int]` 当日连板数 | ellendan 分段法：`is_lu.diff()!=0` → `cumsum()` 作段索引 → 段内 `cumsum()` | 断板当日归 0；一字板是否计入需显式决定 |
| `limit_count(df, n)` | 序列、窗口 | `Series[int]` | `is_lu.rolling(n).sum()` | 窗口 n 与「第一波」长度耦合，需扫描 |
| `max_board_height(df, n)` | 序列、窗口 | `Series[int]` | `consec_limit_days.rolling(n).max()` | 用于"是否曾经是龙头" |
| `first_seal_minute(min_df, high_limit)` | 分钟线、涨停价 | int（距 9:30 分钟数） | `min_df[min_df.high >= high_limit].index.min()` | 分钟 bar 时间戳是**区间结束**还是**开始**必须确认，否则整体位移 1 分钟；来源 #1 的代码用 `high >= high_limit` |
| `seal_amount_ratio(seal_amt, float_mv)` | 封单额、流通市值 | float | `seal_amt / float_mv` | **盘中变量**，回测只能用决策时刻之前的快照 |

### 6.3 位置 / 回撤层

| 函数名 | 输入 | 输出 | 算法 | 注意事项 |
|---|---|---|---|---|
| `pos_to_high(df, n)` | 序列、窗口 | `Series[float]` ∈(0,1] | `close / high.rolling(n).max()` | 用**后复权**；n=20/60 需扫描；等价于 `PTH252` 的短周期版，但**不能继承 52 周高点的文献背书** |
| `drawdown_from_high(df, n)` | 序列、窗口 | `Series[float]` | `(high.rolling(n).max() - low) / high.rolling(n).max()` | 通达信同款；**注意这是"距 N 日高点"，不是"回撤/第一波涨幅"** |
| `wave1_retrace(df, start_idx, peak_idx)` | 序列、起点、峰值 | float | `(peak_high - cur_low) / (peak_high - start_low)` | **这才是各家嘴里说的"回撤 38.2%"**。起点定义（第一个涨停的开盘价？涨停前一日收盘？）必须写死并记录 |
| `range_return(df, n)` | 序列、窗口 | `Series[float]` | `close / close.shift(n) - 1` | 后复权 |
| `days_since_last_limit(df)` | 序列 | `Series[int]` | 等价通达信 `BARSLAST(涨停)` | 用于"调整天数 3–10" |

### 6.4 量能层

| 函数名 | 输入 | 输出 | 算法 | 注意事项 |
|---|---|---|---|---|
| `vol_ratio_ma(df, n)` | 序列、窗口 | `Series[float]` | `volume / volume.rolling(n).mean()` | 通达信 `V/MA(V,5)`；阈值 0.33/0.5/0.6 各家冲突，**必扫** |
| `vol_vs_launch(df)` | 序列 | `Series[float]` | `volume / volume.shift(days_since_last_limit)` | 通达信 `V<REF(V,BARSLAST(涨停))` |
| `is_record_volume(df)` | 序列 | `Series[bool]` | `volume >= volume.expanding().max().shift(1)` | **首阴反包的"史上天量"。绝不能写 `volume.max()`** |
| `intraday_vol_ratio(cum_vol, elapsed_min, prev_full_vol)` | 盘中累计量、已交易分钟、昨日全天量 | float | 按**已交易分钟数归一化**后再比 | `limit-up-sniper` 的做法；直接除昨日全天量是错的 |
| `turnover_bucket(turnover)` | 换手率 | enum | `<3%` 跳过 / `15–25%` 减半 / `≥25%` 黑名单 | `limit-up-sniper` 分档，可作先验起点 |

### 6.5 形态层

| 函数名 | 输入 | 输出 | 算法 | 注意事项 |
|---|---|---|---|---|
| `ma_support(df, n, tol)` | 序列、均线周期、容差 | `Series[bool]` | `close > ma(n) and low < ma(n)*(1+tol)` | tol 默认 0.02（通达信同款，无依据） |
| `ma_recross_up(df, n)` | 序列、周期 | `Series[bool]` | `open < ma(n) and close > ma(n)` | **信号日 T，成交日 T+1** |
| `bullish_engulf(df)` | 序列 | `Series[bool]` | `ref(close,1)<ref(open,1) and close>open and close>ref(open,1) and open<ref(close,1)` | 基础阳包阴 |
| `first_yin_day(df)` | 序列 | `Series[bool]` | `is_limit_up.shift(1) and volume/volume.shift(1)>2 and close<open` | 「大阴反包」的首阴定义（放量阴，量翻倍） |
| `engulf_first_yin(df, mode)` | 序列、`full`/`half` | `Series[bool]` | 用 `BARSLAST(首阴日)` 回取 `open`/实体中点作基准，`cross(close, base)` | 「智尊版」允许只反包实体一半以上；`mode` 应作为参数扫描 |
| `dragon_return_signal(df, params)` | 序列 + 参数字典 | `Series[bool]` | `limit_count ≥ k` ∧ `days_since_last_limit ∈ [a,b]` ∧ `drawdown_from_high < d` ∧ `vol_ratio_ma < v` ∧ `ma_support` | **组合信号；参数全部外置，禁止硬编码** |

### 6.6 人气层

| 函数名 | 输入 | 输出 | 算法 | 注意事项 |
|---|---|---|---|---|
| `limit_gene_score(df, lookback=250)` | 单票 250 日历史 | float ∈[0,1] | 五因子横截面百分位加权（25/25/25/15/10，见 §1.6a） | **所有"次日"统计只在结果已可见后进入特征** |
| `lhb_eligible(row)` | 单日行情 | bool | 按交易所上榜条件判定（偏离值/振幅/换手率阈值，见 §1.6c） | 主板 vs 创业板/科创板阈值不同；ST 连续三日 ±12% |
| `amount_rank_pct(cross_section)` | 当日全市场 | `Series[float]` | 成交额横截面百分位 | 纯截面、同一时间戳，**不跨时间**，安全 |
| `sector_limit_count(cross_section, sector_map)` | 当日全市场 + 板块映射 | `Series[int]` | 同板块涨停家数 | **板块映射必须 PIT**（`as_of`），否则通过分类引入未来 |

---

## 7. 【产出 b】前视偏差检查清单（可直接贴进 PR 模板）

```text
[ ] 涨停判定用不复权价，且用数据源 high_limit 字段（不是 pct_chg > 0.095）
[ ] 涨跌幅比例是带 as_of 的版本化查表，不是常量；IPO 前 5 日 / 退市整理首日返回"不设限"
[ ] 涨停价计算用 Decimal + ROUND_HALF_UP，不是 round()
[ ] 信号日 = T（收盘后），成交日 = T+1；没有任何一笔成交发生在信号 K 线上
[ ] 买入价不是当日 low / high；限价单成交价 = min(限价, T+1 open)
[ ] 一字板（high == low）强制不可成交
[ ] 涨停封单不假设必成交（默认 0 成交，或有 L2 校准的队列穿越模型）
[ ] 跌停日不假设能卖出
[ ] 封单额 / 首次封板时间只用决策时刻之前的盘中快照
[ ] 龙虎榜因子的 effective_from = T 日收盘后，用于 T+1
[ ] "史上天量"用 expanding().max().shift(1)，不是全序列 max()
[ ] ST 标记、行业/概念分类、指数成分全部走 as_of 区间表
[ ] 停牌标的从 tradable_universe(t) 剔除；复牌首日单独判断
[ ] 标的池含已退市代码（securities_master 有 delisting_date）；组合历史持有过退市股的次数 > 0
[ ] 上市不足 N 交易日的标的已剔除（N ≥ 30，建议 100 自然日）
[ ] 收益/因子用后复权；下单价用不复权；字段名带 _raw / _fwd / _bwd 后缀
[ ] 所有 rolling 是 center=False；没有 shift(负数) 列进入特征
[ ] z-score / winsorize 是同一时间戳的横截面，或 expanding 窗口，不是全样本
[ ] 单标的单日交易额 ≤ 当日成交额 × 5%
[ ] 已计入佣金 + 印花税 + 过户费 + 滑点，且做过费率翻倍的敏感性
[ ] CI 断言：feature(view_at(t)) == feature(view_at(t, extended_with=future_data))
[ ] 单 K 线位移测试：所有成交后移一根 K 线后，绩效没有崩溃
[ ] 参数尝试次数 N 已记录；显著性按 Bonferroni / Deflated Sharpe 折扣
[ ] 开发集 / 验证集 / 保留集按时间切分；保留集只看一次
```

---

## 8. 【产出 c】A 股工程 gotcha 清单（速查）

| # | Gotcha | 后果 | 处理 |
|---|---|---|---|
| G1 | Python `round()` 是银行家舍入 | 涨停价差一分，涨停判定整体错位 | `Decimal(...).quantize(Decimal('0.01'), ROUND_HALF_UP)`，字符串构造 |
| G2 | 涨跌幅比例硬编码 | ST/退市整理/北交所/制度变更全错 | 版本化 `rate_table(code, as_of)`；优先直接读 `high_limit` |
| G3 | 主板**退市整理**股票是 10% 不是 5% | 判涨停时把退市整理股当 ST 处理 → 全错 | 风险警示 ≠ 退市整理，分开建标记 |
| G4 | 创业板 ST / 退市整理是 20% | 同上 | 同上 |
| G5 | IPO 前 5 日、退市整理首日、重新上市首日**不设涨跌幅** | `high_limit` 字段为空或异常值，涨停因子产生垃圾 | 这些日子直接从标的池剔除 |
| G6 | `C/REF(C,1)>1.095` 在 20cm 板上误判 | 创业板 9.5%~19.9% 的涨幅被当涨停 | 用 `high_limit` 或板块化比例 |
| G7 | 用复权价判涨停 | 除权日附近误判 | 判涨停必须不复权 |
| G8 | 前复权用于「区间涨幅/跌破启动位」 | 每次重跑历史值都变，回测不可复现 | 因子与收益用后复权 |
| G9 | 一字板买不进 | 回测收益虚高（首阴反包/龙回头信号日常见一字） | `high == low` 强制不成交 |
| G10 | 涨停价限价单被当必成交 | 打板类回测最大的虚高来源 | 队列穿越模型或 0 成交 |
| G11 | 「史上天量」写成 `df.vol.max()` | 全样本泄漏 | `expanding().max().shift(1)` |
| G12 | 分钟 bar 时间戳语义（区间开始 vs 结束） | 首次封板时间整体偏 1 分钟，"14:00 组最优"这种结论直接失效 | 落库时显式记录语义并写测试 |
| G13 | 「封板有效」被写成「最高价接近涨停价」 | 因子名与语义不符，下游全错（BigQuant 那段就是） | 命名区分 `touched` / `sealed` / `sealed_at_close` |
| G14 | 主板风险警示股票单日累计买入 ≤ 50 万股 | 组合级仓位在 ST 上不可实现 | 建模为硬约束 |
| G15 | 龙虎榜因子的选择性披露 | 因子天然只覆盖异动股，分组回测结论有偏 | 控制市值/换手/波动后再看增量；或用逆概率加权 |
| G16 | 擦边成交进日线 high/low | 幻影突破信号 | 清洗层过滤瞬时异常 tick 后重算 OHLC |
| G17 | 单一策略排行榜挑第一名 | 多重检验（`EasyQuant` README 就是 28 个排行） | Bonferroni / Deflated Sharpe |
| G18 | 打板策略在下午 14:50 后仍下单 | 无法在当日兑现 | `limit-up-sniper`：14:50 后不再新买；首次触板 ≥14:30 不买 |

---

## 9. 对本仓库的落地建议

1. **把 §6 的函数清单落到 `src/strategy`，参数全部外置**。`entry_timing` 一律 `T+1 open`（符合仓库既有红线：`strategy` 必须 `entry_timing`、禁止前视）。
2. **`limit_rate` 与 `limit_price` 属于横切基础设施**，但它们是市场规则而非账本规则，应落在 `src/market`（`market.db` 可重建），不进 `src/shared`。比例表建议落成 `market.db` 里的一张**带生效区间的小表**（`limit_rate_rules(board, flag, start_date, end_date, rate)`），可整表删除重建。
3. **不要把本文表 2 里的任何数字写进产品文案或 AI 输出**。可信度「中」及以下的数字只能用于「有人这么统计过」的语境。
4. **先做一件事：用本仓库自己的 `market.db` 复现来源 #1（首次封板时间 → 次日溢价）**。这是唯一一份有完整源码 + 明确样本量 + 明确区间的统计，且能直接检验我们的涨停判定、分钟时间戳语义和复权口径是否正确。**如果复现不出 35.88% 的总体炸板率量级，说明我们的基础层有 bug，后面所有形态因子都不用做了。**
5. **龙回头/首阴反包只当研究候选**，在拿到本地严格 PIT 的样本外结果之前，README 与 AI 层的允许表述是「公式有社区实现、无公开回测证据的待检验形态」；**不允许**表述为「已验证的低吸策略」。

---

## 附录：全部来源清单

### 交易所 / 官方（可信度：高）
- [上海证券交易所交易规则（券商站点托管 PDF）](https://zxyoss.csc108.com/csc108-istp/istp/doc/unknown/e6c32c60f61c4bbd9d1d0a359e39ad5d.pdf) — §3.3.13 涨跌幅公式与不设限情形、§3.3.17 四舍五入规则、§6 科创板
- [深圳证券交易所交易规则（2023 年修订征求意见稿）](https://docs.static.szse.cn/www/aboutus/trends/news/W020230201595730281095.pdf) — §3.3.13/14/19、§4.4.2 除权参考价、§4.5.4/5 风险警示与退市整理、第 5 章 龙虎榜上榜条件
- [Python 官方 decimal 文档](https://docs.python.org/zh-cn/3.7/library/decimal.html) — `quantize` / `ROUND_HALF_UP`

### 开源项目（可信度：中–高）
- [ainstainst/limit-up-sniper](https://github.com/ainstainst/limit-up-sniper) / [guoyaohua/limit-up-sniper](https://github.com/guoyaohua/limit-up-sniper) — 涨停基因五因子、队列穿越成交模型、诚实的负面证据
- [sunshanggege/dragon-quant](https://github.com/sunshanggege/dragon-quant) / [PyPI dragon-quant](https://pypi.org/project/dragon-quant/) / [v0.2.2](https://pypi.org/project/dragon-quant/0.2.2/) — 五维龙头评分；**回测用"断板日最低价买入"（前视反面教材）**
- [henrylin99/screener-offline-data · SKILL.md](https://github.com/henrylin99/screener-offline-data/blob/main/SKILL.md) — 125 个 `pattern_*` 二值列与 `break_high_*`
- [HiRenyi/EasyQuant](https://github.com/HiRenyi/EasyQuant) — 28 策略聚宽回测排行榜（多重检验反面教材）
- [hugo2046/QuantsPlaybook](https://github.com/hugo2046/QuantsPlaybook) — 100+ 券商研报策略复现（未针对本形态）
- [zer0quant/zer0factor](https://github.com/zer0quant/zer0factor) — 因子标准化/中性化/Alphalens 评估流水线；README 自述「`FactorFrame` 还没有暴露 ST、停牌、上市天数、精确涨停等字段」

### 回测/统计（各自可信度见 §2）
- [百果量化：首板客必看的反常识结论](http://100apple.net/article/detail.html?id=534&sort=new)
- [ellendan：使用 Pandas 分析 A 股连板数量的分布](https://ellendan.com/2025/01/07/shi-yong-pandas-fen-xi-a-gu-lian-ban-shu-liang-de-fen-bu/)
- [BigQuant：概念热度驱动的打板追涨停量化策略【分钟频】](https://bigquant.com/wiki/doc/4PEdjWUGUf)
- [pandaaiquant：打板策略优化路径的实证研究](https://www.pandaaiquant.com/community/article/874)（存疑）
- [同花顺量化社区：我回测了 A 股 10 年的追涨停策略](https://quant.10jqka.com.cn/view/article/4Z81JJGR1F1581529UVWQAK744)
- [中泰证券-基于龙虎榜的 A 股资金结构分析与应用（第三方转载）](https://www.nxny.com/report/view_5830698.html)
- [开源证券：量化私募交易行为识别—龙虎榜营业部的新视角](http://pdf.dfcfw.com/pdf/H301_AP202110311526206229_1.pdf)
- [今日头条：首版打二版模式胜率统计](https://www.toutiao.com/article/7485538804267401780/)（存疑）

### 回测陷阱与参数稳健性
- [quant67：数据陷阱—幸存者偏差、复权、前视、未来函数](https://quant67.com/post/quant/06-survivorship-bias/06-survivorship-bias.html)（含 PIT 库最小实现、复权公式、CI 断言、自检清单）
- [marketmaker：前视偏差—一根 K 线的错误如何从纯噪声中凭空制造出 15 的夏普比率](https://marketmaker.cc/zh/blog/post/look-ahead-bias-taxonomy/)
- [marketmaker：平台分析—如何区分稳健最优与过拟合](https://marketmaker.cc/zh/blog/post/plateau-analysis-overfitting/)
- [AKQuant 第 11 章：参数优化与稳健性检验](https://akquant.akfamily.xyz/textbook/11_optimization/)
- [BigQuant：用参数平原找到稳健的参数组合](https://bigquant.com/wiki/doc/ck6eowsSL0)
- [EasyQuant：QMT 回测教程—如何识别并避免未来函数](https://easyquant.ai/e/qmt/avoid-lookahead-bias-in-backtest)
- [Coriva：量化回测陷阱大全](https://coriva.eu.org/backtesting-pitfalls/)
- [Threads @little_algo_trader：参数敏感度分析](https://www.threads.com/@little_algo_trader/post/DSwpVozEvOX/)（Pardo / Aronson 数字的**二手转述**，未核到原书）

### 通达信 / 同花顺公式（有源码，无回测）
- [龙回头战法深度解析与选股公式实现](http://set.baidu.com/view/4226dc333569a45177232f60ddccda38376be1c3.html) — 最完整的龙回头选股公式（内容农场页，可信度低）
- [万物公式网：大阴反包指标公式](https://gsw007.com/post/74892.html) — `ZTPRICE` + 板块差异化比例
- [通达信指标网：反包龙选股](https://www.tdxzb.com/?id=11305) — 阳包阴原版/修复版
- [通达信指标网：智尊版龙头首阴反包战法](https://www.tdxzb.com/?id=7466)
- [好公式网：龙头首阴反包战法](https://www.goodgongshi.com/tongdaxingongshi/113252.html) — `LBS` 连板参数、史上天量定义
- [好公式网：真龙第二波](https://www.goodgongshi.com/tongdaxingongshi/119584.html) — 黄金分割回撤区间
- [公式平台网：龙回头缩量回踩企稳套装](https://www.gspt.com/gs/16044) — 副图源码
- [掌心公式：龙回头 2 代](https://www.6o7o.com/?id=3813) — 调整天数 3–10 天
- [cfchi：天下第一龙回头](https://m.cfchi.com/formula/futuzhibiao/17465.html) — MA10 支撑主张
- [夜雨聆风：龙回头战法指标源码视频精讲](https://www.yeyulingfeng.com/493875.html) — `ma_recross_up` 思路
- [擒牛指标公式网：龙回头吃肉](https://www.cjm99.com/zb/148032.html) — MA8 止损主张
- [拾荒网：龙头二波选股方法](http://www.10huang.cn/buy/53273.html) — 均线随市场阶段变化的主张
- [股旁网：通达信阴线反包选股指标公式](https://www.gupang.com/202307/64966.html)

### Python 涨停数据处理
- [腾讯云：统计个股股性包括涨停次数、首次涨停溢价率、高开低走次数](https://cloud.tencent.com/developer/article/2659338) — `calculate_limit_price` 参考实现（注意它用了 `round()`）
- [CSDN：python 评估今日股票涨停质量并打分](https://blog.csdn.net/lianquant/article/details/147653203) — 封单强度 = 封单金额/流通市值
- [CSDN：Akshare 涨停板分析](https://blog.csdn.net/myqijin/article/details/144425164) — `ak.stock_zt_pool_em`
- [CSDN：7.2 常见陷阱—前视偏差、幸存者偏差、手续费低估](https://blog.csdn.net/wayz11/article/details/160258909) — **该文的"实证分析"量化表（前视 +3.5% 年化等）无数据来源与代码，本文不采信**

### 未能访问
- 聚宽社区（[龙回头 5.0](https://www.joinquant.com/community/post/detailMobile?page=2&postId=30071)、[连板龙头策略 wywy1995](https://www.joinquant.com/community/post/detailMobile?postId=44926)、[WY 大神龙头打板小改](https://www.joinquant.com/community/post/detailMobile?postId=46331)）：站点返回「当前地区暂不支持访问 / Service Unavailable in Your Region」，本次**无法核验其源码与回测截图**。搜索摘要中的策略描述（"始终买最近连续涨停且涨停次数最多的股票，持有两天"）来自二手转述，未采信任何数字。
- [掘金量化：龙头战法实盘版](https://jishu.proginn.com/doc/61116475b0da79768)：两次抓取超时，未取得源码。
- 米筐 RiceQuant、优矿 Uqer：本次搜索**未找到与本形态相关的公开策略帖**。

---

## 风险提示

本文只梳理公开资料中的公式、代码与统计口径，不构成投资建议，也不代表任何一条被引用的策略在未来有效。文中所有回测数字均来自第三方，本文未复现其中任何一条；可信度「低」与「存疑」的数字不应用于任何决策。这一族形态的公开证据基础远弱于其在社区中的流行程度——**在本仓库拿到自己的严格 PIT 样本外结果之前，它只是一个待检验假设。**
