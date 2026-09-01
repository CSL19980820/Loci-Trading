# 因子研究与验证的工业流水线（scratch）

> **日期**：2026-08-25 ｜ **检索日期**：2026-08-25
> **用途**：供上层综述引用。回答「从『想到一个信号』到『敢用它』，主流在中间补了哪些环节，哪些该抄到 Loci，哪些明确不抄」。
> **范围**：只读。除本文件外未改任何仓库文件，未 commit / push，未写库，未装任何新依赖。本轮跑的基准是纯内存合成面板，不读 `data/`。
> **证据分级**：`P1` 一手原文已读（仓库源码逐行 / 论文全文 PDF / 官方 README 与 config 原文）；`P2` 仅读到摘要或第三方转述；`M` 本轮本机实测；`M*` 主 agent dbstat 实测（2026-08-25）；`✗` 未取到一手来源。
> **与既有文档的关系**：`2026-08-github-open-source-technology-radar.md` 收过其中几个仓库的星标与许可，本文**不重复选型清单**，只做「工序」拆解。单因子九篇（PTH252 / TVOL / 12-1 / REV21）给的是**结论**（全部拒绝），本文给的是**产生那些结论所缺的流水线**。`2026-08-incumbent-strategy-full-sample-benchmark.md` 与 `-rank-levers.md` 是 §1 清单的现成反例来源。`2026-08-dragon-survivorship-and-portfolio-fragility.md` 的存活偏差判定在 §7 被主 agent 的 dbstat 实测**升级为硬数字**。

---

## 0. 一句话结论

**主流补的不是「更好的因子」，是四道工序**：①把因子和未来收益对齐成一张 `(date, asset)` 面板并强制声明丢弃率；②在这张面板上算三组固定统计量（IC / 分组 / 换手）；③把「试了多少次」记成台账并按次数抬高显著性门槛；④把「选出来的东西」和「随便选一个」做对照。**Loci 缺的是第 ①③④ 道，第 ② 道只差六七个算子。**

**最便宜、收益最大的一块是算子**：把 `Rank`（截面）、`Corr`、`Slope/Rsquare/Resi`、`Quantile`、`TsRank`、`Skew/Kurt` 补进 `src/formula/domain/functions.py`，可覆盖 Alpha158 目前算不出来的 11 个特征族，以及 WQ101 里现在一条都写不出的那部分。本机在 **700×5547 面板**（≈ `market_hot.db` 的实际形状）上实测：截面 rank **311 ms / 峰值 +97 MB**，滚动 Slope 闭式卷积 **414 ms**（与 `np.polyfit` 逐位相等），IdxMax 分块滑窗 **222 ms**。在 1.1 GB 预算里这些**全都不构成问题**（`M`，§2.4）。

**必须先纠正的三个误解**：`HHVBARS`/`LLVBARS` **已经就是** `IdxMax`/`IdxMin`，只差 `N-1-x` 的方向约定（本机验证，§2.3）；`WMA` **已经就是** WQ101 的 `decay_linear`；`AVEDEV` **已经就是** Qlib 的 `Mad`。任务书列的「缺 IdxMax/IdxMin」不成立，真正缺的是另外六族。

**两个明确的否定**：

- **ML 层（LightGBM / 深度模型）：不碰。** Qlib 官方 benchmark 一手数字——CSI300 + Alpha158 上 Linear 的 IC 0.0397 / IR 0.9209，LightGBM 0.0448 / 1.0164，**线性模型拿到了 GBDT 90.6% 的 IR**；换到人工特征更少的 Alpha360，MLP 年化 **0.29%**、Transformer **−2.70%**、TabNet **−3.69%**、KRNN **−4.65%**。模型不是瓶颈。加上 `lightgbm` 不在 `requirements.txt`、`ops.db.strategy_backtests` **0 行**（试验次数 M 无从统计）、`instruments.delist_date` **填充 0 条**（训练集是幸存者），此时上 GBDT 是在三重不利条件下扩大过拟合面。§5 给可审计的解锁条件。
- **组合优化（MVO / 风险平价 / HRP）：不碰。** DeMiguel-Garlappi-Uppal (2009, RFS 22(5)) 一手结论：样本 MVO 要跑赢 1/N，25 只票需要 **3000 个月**估计窗口、50 只票需要 **6000 个月**（250 年 / 500 年）。Loci 持 3–10 只、持有 1–5 天，协方差矩阵的估计窗口比持有期长一到两个数量级。§6 给替代方案，落点在仓内已有。

---

## 1. 因子评估的标准动作

### 1.1 alphalens 到底算哪三张

`stefan-jansen/alphalens-reloaded`（633★ / 144⑂ / Apache-2.0，`P1`，本轮读了 `src/alphalens/utils.py` 1052 行与 `performance.py` 1197 行的相关段落）。README 自述四类产出：Returns Analysis、Information Coefficient Analysis、Turnover Analysis、Grouped Analysis。核心是三张，第四张是前三张按行业再切一遍。

**入口只有一个**：`get_clean_factor_and_forward_returns(factor, prices, ...)` → 一张 MultiIndex `(date, asset)` 的 `factor_data`，列 = 各持有期的前瞻收益 + `factor` + `factor_quantile`（+ 可选 `group`）。**后面所有函数都只吃这张表**——这是整个库唯一的耦合点，也是抄进 Loci 时唯一需要照抄的数据契约。

#### ① IC 分析 — `factor_information_coefficient`

```python
def src_ic(group):
    f = group["factor"]
_ic = group[utils.get_forward_returns_columns(factor_data.columns)].apply(
    lambda x: stats.spearmanr(x, f)[0])
    return _ic
ic = factor_data.groupby(grouper, observed=True).apply(src_ic)
```
（`performance.py` L33–L78，`P1`）

三个要点，抄的时候不要抄错：

1. **alphalens 的 IC 只有 Spearman，没有 Pearson。** `stats.spearmanr` 写死。Qlib 两个都给（§1.2）。用 Spearman 的直接后果是：**因子做任何单调变换 IC 都不变**，所以「要不要对因子取 log / 开方 / 去极值」这个问题在 IC 这一关上根本不存在。
2. **按日分组**，一天一个 IC 值，得到一条长度 = 交易日数的时间序列。ICIR = `mean(IC)/std(IC)`，t 值 = `ICIR × √n`。三个数都出自同一条序列。
3. `group_adjust=True` 时先 `demean_forward_returns` 再算 IC —— 这是「行业中性后因子还有没有用」，和「因子是不是只是行业轮动的影子」是同一个问题。A 股上这一关经常直接判死刑。

#### ② 分组收益 — `mean_return_by_quantile` + `compute_mean_returns_spread`

```python
if group_adjust: ...  elif demeaned: factor_data = utils.demean_forward_returns(factor_data)
grouper = ["factor_quantile", factor_data.index.get_level_values("date")]
group_stats = factor_data.groupby(grouper, observed=True)[fwd_cols].agg(["mean","std","count"])
std_error_ret = group_stats.T.xs("std",level=1).T / np.sqrt(group_stats.T.xs("count",level=1).T)
```
（`performance.py` L459–L525，`P1`）

- **默认 `demeaned=True`**，分组收益是**相对当日全宇宙均值的超额**，不是绝对收益。这条最容易看错：牛市里五组全正的因子，demean 之后可能五组全平。判断单调性必须看 demean 后的版本。
- 同时返回 `std_error_ret = std/√count`。**多空价差的联合标准误是 `sqrt(std1² + std2²)`**（`compute_mean_returns_spread`），不是简单相减 —— 报「Q5−Q1 = 1.2%」而不报这个误差等于没报。

#### ③ 换手与自相关 — `quantile_turnover` + `factor_rank_autocorrelation`

```python
# quantile_turnover: 今天在第 q 组、period 天前不在第 q 组的比例
new_names = (quant_name_sets - name_shifted).dropna()
quant_turnover = new_names.apply(f) / quant_name_sets.apply(g)

# factor_rank_autocorrelation: 逐日截面 rank -> 透视成 (date x asset) -> 与自身滞后逐行相关
asset_ranks_by_day = factor_data.groupby(level="date")["factor"].rank() \
    .reset_index().pivot(index="date", columns="asset", values="factor").asfreq(freq)
return asset_ranks_by_day.corrwith(asset_ranks_by_day.shift(period), axis=1)
```
（`performance.py` L571–L650，`P1`）

**为什么必须看 `factor_rank_autocorrelation` 而不是只看换手率**，文档字符串自己写了原因：

> We must compare period to period factor ranks rather than factor values **to account for systematic shifts in the factor values of all names or names within a group**. … If the value of a factor for each name changes randomly from period to period, we would expect an autocorrelation of 0.

翻成能用的话：

- **它先 rank 再算相关，所以对「全市场同时平移」免疫。** 一个 `close/MA20` 类因子在指数大涨那天所有票的原始值一起抬升，用原始值算自相关会虚高到 0.99，而实际排名可能已经重排了一半。Loci 的战法评分（如 `qianlong.score_signals` 的 100 分制）正是这种「全市场同涨同跌时数值一起漂」的结构，**用原始分算稳定性会系统性骗自己**。
- **它是换手率的先行指标，比换手率更早暴露问题。** 换手率只看 Q5 组的进出，自相关看整个排序的稳定性。一个因子可以 Q5 换手不高（头部几只很稳）但中间段每天乱翻 —— 这种因子一旦把 Top-N 从 3 改成 5 就崩，本仓 `dragon-survivorship-and-portfolio-fragility.md` 实测过同一现象（信号数差 3.4% → 组合全期收益差 187%）。
- **它给出换手成本的下界**：ρ 与单期换手大致有 `turnover ≈ 1 − ρ` 的量级关系，在还没跑回测之前就能估出「每天要换掉多少仓位」，从而估出成本吃不吃得下。

#### ④ 分行业 — `by_group=True`

前三张都带 `by_group` 开关，走 `groupby([date, "group"])`，要求 `get_clean_factor` 时传 `groupby=`。Loci 有 KPL 主类题材可直接当 group（与 `limit_up_ladder` 的 `primaryThemeStats` 同口径），这一关基本零成本。

### 1.2 Qlib `SigAnaRecord`：同一件事的极简版

`qlib/workflow/record_temp.py` L280–L355（`P1`）：

```python
class SigAnaRecord(ACRecordTemp):
    artifact_path = "sig_analysis"; depend_cls = SignalRecord
    def __init__(self, recorder, ana_long_short=False, ann_scaler=252, label_col=0, skip_existing=False)
    def _generate(self, label=None, **kwargs):
    ic, ric = calc_ic(pred.iloc[:,0], label.iloc[:, self.label_col])
        metrics = {"IC": ic.mean(),"ICIR":      ic.mean()/ic.std(),
         "Rank IC": ric.mean(), "Rank ICIR": ric.mean()/ric.std()}
      if self.ana_long_short:
         long_short_r, long_avg_r = calc_long_short_return(...)
            metrics.update({
                "Long-Short Ann Return": long_short_r.mean()*self.ann_scaler,
     "Long-Short Ann Sharpe": long_short_r.mean()/long_short_r.std()*self.ann_scaler**0.5})
```

`calc_ic`（`qlib/contrib/eva/alpha.py`，`P1`）：

```python
ic  = df.groupby(date_col).apply(lambda d: d["pred"].corr(d["label"])) # Pearson
ric = df.groupby(date_col).apply(lambda d: d["pred"].corr(d["label"], method="spearman"))  # Spearman
```

`calc_long_short_return`：`quantile=0.2`，返回 **`(r_long − r_short) / 2`**。那个 `/2` 是每腿口径，直接拿去和别处的多空收益比会差一倍。

| 项 | alphalens | Qlib `SigAnaRecord` |
|---|---|---|
| IC 定义 | 只有 Spearman | Pearson (`IC`) + Spearman (`Rank IC`) 两套 |
| 分组 | `pd.qcut` 5 组（可配），逐日 | 不分组，只有 top/bottom 20% |
| 多空 | `factor_weights` 因子值加权、去均值、gross=1 | `nlargest/nsmallest` 等权，且 `/2` |
| 换手 / 自相关 | `quantile_turnover` + `factor_rank_autocorrelation` | **没有**（`pred_autocorr` 在 `eva/alpha.py` 但不进 `SigAnaRecord`） |
| 默认开关 | 全开 | **`ana_long_short=False` —— 默认连多空都不算** |
| 依赖 | scipy + statsmodels + empyrical + matplotlib + seaborn + IPython | pandas 自带 `.corr()` |

**结论：Qlib 版是 alphalens 的真子集，但它的 IC/ICIR 四元组只用 `pandas.Series.corr`，零额外依赖。** 对 Loci：Qlib 版可以照抄实现，alphalens 版要照抄**口径**但自己写（原因见 §1.5）。

**另一条要照抄的是 Qlib 的标签定义**（`qlib/contrib/data/handler.py`，Alpha158 与 Alpha360 共用，`P1`）：

```python
def get_label_config(self):
    return ["Ref($close, -2)/Ref($close, -1) - 1"], ["LABEL0"]
```

即 **`close(t+2) / close(t+1) − 1`：T 日出信号，T+1 收盘买，T+2 收盘卖，故意跳过 T→T+1 那一段**。跳过的正是「信号当天你其实没法在收盘价成交」的那一段。这与 Loci 现役的 `entry_timing=next_open` 是同一个思想的两种实现；本仓 `tail-1450-next-day-touch-evidence.md` 也记过「qlib 官方 label 一个 `$high` 都不用」。**做 IC 时若用 `close(t+1)/close(t) − 1` 当标签，就等于假设信号日收盘可成交，IC 会系统性虚高。**

### 1.3 `get_clean_factor_and_forward_returns` 的分组与「去极值」口径

签名（`utils.py` L676–L855，`P1`）：

```python
get_clean_factor_and_forward_returns(
    factor, prices, groupby=None, binning_by_group=False,
    quantiles=5, bins=None, periods=(1,5,10),
    filter_zscore=20, groupby_labels=None, max_loss=0.35, zero_aware=False,
    cumulative_returns=True)
```

**分组口径**（`quantize_factor`，L88–L180）：

| 参数 | 行为 | 什么时候用 |
|---|---|---|
| `quantiles=5`（默认） | `pd.qcut(x, 5, labels=False) + 1`，**逐日**做，每组样本数相等 | 默认；因子分布逐日漂移时唯一正确的选择 |
| `bins=N` | `pd.cut`，**等宽**分桶，每组样本数不等 | 因子是离散值（如「连板数」）时；`qcut` 会因重复值报错 |
| `binning_by_group=True` | `grouper.append("group")`，**在每个行业内部**分位 | 因子量纲跨行业差异大时 |
| `zero_aware=True` | 正负分别 `qcut(quantiles//2)` 再拼 | 因子以 0 为多空分界时（要求 quantiles 为整数） |

分组失败的兜底：`no_raise = False if max_loss == 0 else True`。即**只要 `max_loss ≠ 0`，`pd.qcut` 抛的异常就被静默吞掉**、那些行变 NaN 后被 drop。`max_loss=0` 是唯一能看到真实异常的方式，文档字符串明说 “Set max_loss=0 to avoid Exceptions suppression”。

#### ⚠ 「去极值」口径 —— 纠正一个流传很广的说法

**alphalens 不对因子做任何去极值 / winsorize / clip。** 全文件搜 `winsor` / `clip` 零命中（`P1`，本轮 grep 验证）。唯一的异常值处理是 `filter_zscore=20`，而它：

1. **作用在前瞻收益上，不是因子上**（`compute_forward_returns` L313–L317）：

```python
if filter_zscore is not None:
    mask = abs(forward_returns - forward_returns.mean()) > (filter_zscore * forward_returns.std())
    forward_returns[mask] = np.nan
```

2. **默认阈值是 20 个标准差**，实际上等于不过滤（只砍数据错误级别的离群）。
3. **文档字符串自己警告它引入前视偏差**：「Caution: this outlier filtering incorporates lookahead bias.」—— 因为 `.mean()` / `.std()` 是全样本统计量。

alphalens 敢不去极值，是因为它的两个核心统计量本身就是**秩统计量**：Spearman IC 和 `pd.qcut` 分组都只看排序。**这条对 Loci 直接可用：只要评估层走 rank 口径，因子端就不需要引入去极值这个额外的、有前视风险的步骤。** 需要数值口径（比如线性加权合成）时再单独做 MAD-clip，且只许用截止当日的信息。

对照 Qlib：去极值在 **handler processors** 里，不在评估里。`workflow_config_linear_Alpha158.yaml`（`P1`）：

```yaml
infer_processors:
  - class: RobustZScoreNorm   {fields_group: feature, clip_outlier: true}
  - class: Fillna      {fields_group: feature}
learn_processors:
  - class: DropnaLabel
  - class: CSRankNorm         {fields_group: label}
```

即：**特征做 robust z-score + clip（在训练段 `fit_start_time..fit_end_time` 上拟合），标签做截面 rank 归一化**。Alpha158/Alpha360 类的默认值是 `ZScoreNorm` + `CSZScoreNorm(label)`（`handler.py` L35–L43）。注意 **`RobustZScoreNorm` 只在训练段拟合**——这是不引入前视的关键，也是 alphalens 的 `filter_zscore` 做不到的那一点。

**`max_loss=0.35` 是这个库最被低估的设计。** 它强制你面对「这张表丢了多少行、丢在哪一步」：

```python
tot_loss    = (initial_amount - binning_amount) / initial_amount
fwdret_loss = (initial_amount - fwdret_amount)  / initial_amount
bin_loss    = tot_loss - fwdret_loss
if tot_loss > max_loss: raise MaxLossExceededError(...)
```

丢在「前瞻收益」阶段 = 停牌 / 新股 / 退市；丢在「分桶」阶段 = 因子值重复太多（一字板、封死涨停那批票的很多因子会完全相同）。**A 股上这两个数都会很大，而且第二个数会在极端行情日暴涨** —— 这正是「因子在最需要它的那天失效」的机制。Loci 现在没有任何地方在统计这两个数。

### 1.4 一个因子要过哪几关才算「有」

阈值在 §4.3 变成 CI 门禁的具体数值，这里先定义关卡与口径。

| # | 关卡 | 口径（必须这么算） | 不过关意味着 |
|---|---|---|---|
| 1 | **数据完整性** | `tot_loss` / `fwdret_loss` / `bin_loss` 三个数分别报出 | 后面所有数字都建在一个你不知道形状的样本上 |
| 2 | **Rank IC 均值** | 逐日 Spearman(factor, fwd_ret) 取均值。**必须是 Rank IC，不是 IC** | 因子与未来收益的单调关系不存在 |
| 3 | **ICIR** | `mean(IC)/std(IC)`，同一条逐日序列 | 因子有效但不稳定，无法定仓位 |
| 4 | **t 值** | `ICIR × √n_eff`；**重叠持有期必须 Newey-West 修正**，滞后阶 = 持有期 | 上面两个数是噪声 |
| 5 | **分组单调性** | `mean_return_by_quantile(demeaned=True)` 的 5 组均值对组号的 Spearman | 因子只在尾部有效 = 只在少数票上有效 = 不可扩容 |
| 6 | **多空夏普** | Q5−Q1 等权日频，年化 = `mean/std×√252`，**扣双边成本后** | 分组单调但价差吃不下成本 |
| 7 | **换手与成本后收益** | `quantile_turnover(Q5,1)` + `factor_rank_autocorrelation(1)`；成本档 ≥ 单边 10bp | 纸面 alpha，实盘负期望 |
| 8 | **逐年稳定性** | 按自然年切，逐年 Rank IC 与逐年多空收益 | 全样本正数由一两年贡献 —— 本仓 `incumbent-rank-levers.md` 的 14 组**无一通过逐年全正** |
| 9 | **样本外** | 时间切分（不是随机切分），OOS 段在建因子时物理不可见 | 见 §4.2：holdout 用多了就不是 OOS |
| 10 | **多重检验后仍显著** | 从 trial 台账读 M，做 Bonferroni / DSR | 前九关全过也可能只是第 47 次尝试的运气 |

**第 10 关是 Loci 目前唯一一关连「能不能算」都做不到的**（`ops.db.strategy_backtests` 0 行，§7.2）。

### 1.5 alphalens 能不能直接 `pip install`

**不能，且不建议。** 理由是依赖，不是质量：

- alphalens-reloaded 声明依赖 matplotlib / numpy / pandas / scipy / seaborn / statsmodels，代码里还 `import empyrical` 与 `from IPython.display import display`（`P1`，`performance.py` L17–L24）。
- Loci 的 `requirements.txt`（`P1`，本轮读）**没有 scipy、没有 statsmodels、没有 sklearn、没有 matplotlib**。本机 `.venv` 里 scipy/sklearn/matplotlib 确实 import 得到，但追依赖树发现它们只出现在 `pandas[computation]` / `pandas[plot]` 这类 **optional extra** 里（`M`，`importlib.metadata` 扫描）—— 也就是说它们是**未声明依赖**，比声明了的依赖更糟：PyInstaller 打包（`loci.spec`）与 `deploy.ps1` 都以 `requirements.txt` 为准。
- 更重要的：alphalens 吃 MultiIndex `(date, asset)` 长表，而 Loci 全栈是 `index=交易日 / columns=股票代码` 的**宽面板**（`functions.py` 模块 docstring 明写）。为它先 `stack()`，700×5547 会变成 388 万行长表 —— 在 1.1 GB 预算里可以做，但没必要。

**建议：抄口径，不抄库。** 三张分析在宽面板上的实现总共不到 60 行，**只用 pandas 自带算子**：

```python
# f = 因子面板, r = 前瞻收益面板（同 index/columns；r 已对齐成「今天的因子 -> 未来的收益」）
rank_ic  = f.rank(axis=1).corrwith(r.rank(axis=1), axis=1)            # 逐日 Spearman IC
icir     = rank_ic.mean() / rank_ic.std()
q        = f.rank(axis=1, pct=True).mul(5).apply(np.ceil).clip(1, 5)  # 逐日 5 分位
excess   = r.sub(r.mean(axis=1), axis=0)      # demean，对齐 demeaned=True
grp      = {k: excess.where(q == k).mean(axis=1) for k in range(1, 6)}
ls       = grp[5] - grp[1]         # 多空
autocorr = f.rank(axis=1).corrwith(f.rank(axis=1).shift(1), axis=1)   # factor_rank_autocorrelation
top    = q.eq(5)
turnover = (top & ~top.shift(1)).sum(axis=1) / top.sum(axis=1)        # quantile_turnover(Q5, 1)
```

**这七行覆盖了 alphalens 三张核心分析的全部数值输出**，零新依赖，直接吃 Loci 现有的面板形状。缺的只有画图 —— 而前端本来就是 ECharts，Python 侧不需要 matplotlib。

---

## 2. Alpha158 / Alpha360 / WQ101 的算子共性，以及我们缺什么

### 2.1 三套体系拆成六个基础算子族

把 Qlib `Alpha158`（`qlib/contrib/data/loader.py`，`P1`）、`Alpha360`（同文件，纯滚动 `Ref` 堆叠）与 WQ101（arXiv:1601.00991 附录 A.1，`P1`）三套放在一起，去掉命名差异，只剩六族：

| 族 | 内容 | Alpha158 里的代表 | WQ101 里的代表 |
|---|---|---|---|
| **A 价量比值 / K 线几何** | 同一根 K 线内各价位的比值、影线长度、量价比 | `KMID` `KLEN` `KUP` `KLOW` `KSFT` `RSV` `VMA` | `Alpha#101 = (close-open)/((high-low)+0.001)` |
| **B 滚动统计** | 均值 / 求和 / 标准差 / 极值 / 计数 | `MA` `STD` `MAX` `MIN` `SUMP/SUMN/SUMD` `CNTP/CNTN/CNTD` `VSTD` `WVMA` | `sum` `stddev` `ts_min` `ts_max` `product` |
| **C 排序 / 分位** | 截面排序、时序分位、滚动百分位 | `RANK`（**时序**）`QTLU` `QTLD` | `rank`（**截面**）`ts_rank` `scale` `indneutralize` |
| **D 相关性** | 两条序列的滚动相关 / 协方差 | `CORR`（close × log volume）`CORD`（收益率 × 量变化率） | `correlation(x,y,d)` `covariance(x,y,d)`，101 条里约四成用到 |
| **E 时序回归斜率** | 对时间下标做 OLS 的斜率 / R² / 残差 | `BETA`(=`Slope`) `RSQR` `RESI` | 无直接对应（用 `delta` + `decay_linear` 近似） |
| **F 极值位置** | 窗口内最高/最低发生在第几根 | `IMAX` `IMIN` `IMXD`（Aroon 家族） | `ts_argmax` `ts_argmin` |

两条**必须点破的差异**：

1. **Qlib 的 `Rank` 是时序的，不是截面的。** `loader.py` L191–L195 原文注释：「Get the percentile of current close price in past d day’s close price.」实现是 `series.rolling(N).rank(pct=True)`（`ops.py` L1088–L1128）。`Quantile` 同理。**Alpha158 的 158 个特征里没有一个是截面算子** —— 截面只在 handler 的 processors（`CSZScoreNorm` / `CSRankNorm`，作用于 label）和 IC 的逐日分组里出现。WQ101 的 `rank(x)` 才是真截面（A.1 原文：「rank(x) = cross-sectional rank」）。抄的时候两个 `Rank` 不能混。
2. **`Corr` 在 Qlib 里带一个静默守卫**（`ops.py` L1413–L1444）：当任一边的滚动 std 接近 0（`atol=2e-05`）时结果置 NaN。A 股上这条极其重要 —— 一字板、停牌补全、连续涨停会让窗口内价格恒定，不置 NaN 会算出伪相关。`Rsquare` 有同样的守卫。**自己实现时必须照抄这个守卫，否则涨停票的相关性因子全是垃圾。**

### 2.2 WQ101 的算子表（A.1 原文，`P1`）

| 算子 | 原文定义 | 类型 |
|---|---|---|
| `rank(x)` | cross-sectional rank | **截面** |
| `scale(x, a)` | rescaled x such that `sum(abs(x)) = a`（默认 a=1） | **截面** |
| `indneutralize(x, g)` | x cross-sectionally demeaned within each group g | **截面** |
| `delay(x, d)` | value of x d days ago | 时序 |
| `delta(x, d)` | today’s value minus value d days ago | 时序 |
| `correlation(x,y,d)` / `covariance(x,y,d)` | time-serial corr / cov over past d days | 时序 |
| `decay_linear(x, d)` | 线性衰减加权均值，权重 d, d−1, …, 1，归一化到和为 1 | 时序 |
| `ts_min/ts_max(x,d)` | 滚动极值 | 时序 |
| `ts_argmax/ts_argmin(x,d)` | which day ts_max/ts_min occurred on | 时序 |
| `ts_rank(x, d)` | time-series rank in the past d days | 时序 |
| `stddev` / `sum` / `product` | 滚动标准差 / 求和 / 连乘 | 时序 |
| `signedpower(x, a)` | `x^a` | 逐元素 |
| 输入变量 | `returns` `vwap` `cap` `adv{d}`（d 日平均成交额）`IndClass.{sector,industry,subindustry}` | — |

论文自报的三个数（摘要原文，`P1`）：**平均持有期 0.6–6.4 天；101 条之间的平均两两相关只有 15.9%；收益与波动率强相关，与换手率无显著关系。** 第一个数直接对上 Loci 的 1–5 天持有期 —— **WQ101 是这批公开材料里唯一一个持有期与 Loci 同量级的**，Alpha158/Alpha360 的标签是 T+1→T+2 单日。

### 2.3 我们已经有的：先纠正三处「以为缺其实不缺」

`src/formula/domain/functions.py` 的 `__all__` 共 27 个：`ABS AVEDEV BARSCOUNT BARSLAST BARSSINCE COUNT CROSS DMA EMA EVERY EXIST FILTER HHV HHVBARS IF LLV LLVBARS MA MAX MIN REF SMA STD SUM WMA ZTPRICE weighted_ref_sum`；`indicators.py` 再加 13 个：`ATR BOLL_LOWER BOLL_MID BOLL_UPPER CCI MACD MACD_DEA MACD_DIF OBV ROC RSI TR WR`；`chips.py` 另有 `COST` / `WINNER`（未进 Screen Formula 目录）。（`P1`，本轮逐行读）

| 以为缺的 | 实际上 | 证据 |
|---|---|---|
| `IdxMax` / `IdxMin` | **`HHVBARS` / `LLVBARS` 就是**，只差方向约定 `HHVBARS = N-1-IdxMax` | `M`：700×5547、N=20 实测 `int(N-1-idxmax) == 19`，与 `HHVBARS` 语义一致 |
| `decay_linear` | **`WMA` 就是**。`functions.py` L68–L95 权重 `arange(1, N+1)/sum`，当期最大 —— 与 A.1 的「权重 d, d−1, …, 1 归一化到 1」逐位相同 | `P1` |
| `Mad`（Qlib 滚动平均绝对偏差） | **`AVEDEV` 就是** | `P1`，两边都是 `mean(abs(x - mean(x)))` |
| `delta(x,d)` | `x - REF(x,d)`，一行可组合，不必新增算子 | `P1` |
| `adv{d}` | `MA(AMOUNT, d)`。`quotes_daily` 有 `amount` 列 | `M*` |
| `vwap` | **`AMOUNT / VOL` 可直接派生**，`quotes_daily` 两列都在 | `M*`（列清单：trade_date/code/open/high/low/close/volume/amount/outstanding_share/turnover/source/fetched_at/receipt_id） |

> ⚠ `vwap` 这条要加一句限制：日线 `amount/volume` 得到的是**全日均价**，不是 WQ101 语境下的 intraday VWAP；而且本机**分钟线不落库**（`GET /api/market/minute/{code}` 明确不写 `market.db`，live 只有 3–5 秒 TTL 进程内缓存，`M*`），所以真正的日内 VWAP 在本仓不可得，也不可回补。用日均价代 vwap 是可接受的近似，但要在因子元数据里标注。

### 2.4 缺失算子清单表

下表是**要补的全部**。「pandas 面板实现」一列可直接落进 `src/formula/domain/functions.py`，全部保持 Series/DataFrame 同构（该模块的既有硬约束）。`x` / `y` 为面板（`index=交易日, columns=代码`），`n` 为窗口。

| 算子 | 语义 | pandas 面板实现（一行） | 用在哪类因子 | 内存注意 |
|---|---|---|---|---|
| **`CSRANK(x)`** | **截面**百分位排序，逐日在全市场内排，输出 0–1 | `x.rank(axis=1, pct=True)` | WQ101 的 `rank`；一切「今天全市场谁最强」；Top-N 打分的归一化底座 | 311 ms / +97 MB（`M`） |
| **`CSZSCORE(x)`** | 截面标准化，逐日去均值除以截面标准差 | `x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)` | 多因子线性合成前的量纲统一；Qlib `CSZScoreNorm` 同口径 | 112 ms / +159 MB（`M`） |
| **`CSDEMEAN(x)`** | 截面去均值（不除标准差） | `x.sub(x.mean(axis=1), axis=0)` | alphalens `demean_forward_returns`；分组超额收益的分母 | 36 ms / +62 MB（`M`） |
| **`CSSCALE(x, a=1)`** | 截面缩放到 `sum(abs)=a` | `x.div(x.abs().sum(axis=1), axis=0).mul(a)` | WQ101 `scale`；多空组合权重（gross leverage=1） | 与 CSDEMEAN 同量级 |
| **`CSNEUTRALIZE(x, g)`** | 在分组 `g` 内截面去均值（g 为 code→题材/行业 的映射） | `x.sub(x.T.groupby(g).transform("mean").T)` | WQ101 `indneutralize`；剥离题材轮动后看因子还剩什么 | 需 groupby，比 CSDEMEAN 慢一个量级 |
| **`CORR(x, y, n)`** | 两面板逐列滚动 Pearson 相关 | `x.rolling(n).corr(y)` | Alpha158 `CORR`/`CORD`；量价背离；WQ101 约四成条目 | 3130 ms / +138 MB（`M`），最贵的一个 |
| **`COV(x, y, n)`** | 滚动协方差 | `x.rolling(n).cov(y)` | 同上；也是 `Slope(x,y,n)` 的分子 | 同 CORR 量级 |
| **`SLOPE(x, n)`** | 对时间下标 0..n−1 做 OLS 的斜率 | 闭式卷积：`w = arange(n) - (n-1)/2`，`Σ w_k · x_{t-n+1+k} / Σ w_k²`（复用 `WMA` 的权重累加骨架） | Alpha158 `BETA`；趋势斜率；比 `MA` 差分更抗噪 | 414 ms（`M`），与 `np.polyfit` **逐位相等** |
| **`RSQUARE(x, n)`** | 同一回归的 R²，衡量趋势的「直不直」 | `CORR(x, 时间下标, n) ** 2`（时间下标是常量列向量，可广播） | Alpha158 `RSQR`；区分「涨得稳」与「涨得毛」 | 同 CORR |
| **`RESI(x, n)`** | 同一回归在当期的残差 | `x - (SLOPE(x,n) * (n-1)/2 + MA(x,n))`（截距 = 均值 − 斜率×下标均值） | Alpha158 `RESI`；偏离自身趋势线的幅度 | 复用 SLOPE，几乎零增量 |
| **`QUANTILE(x, n, q)`** | 滚动分位数 | `x.rolling(n).quantile(q)` | Alpha158 `QTLU`(0.8) / `QTLD`(0.2)；比 HHV/LLV 抗单根毛刺 | 1636 ms / +64 MB（`M`） |
| **`TSRANK(x, n)`** | **时序**滚动百分位（当期值在过去 n 天里的分位） | `x.rolling(n).rank(pct=True)` | Qlib `RANK`、WQ101 `ts_rank`；「现在贵不贵（相对自己）」 | 1834 ms / +69 MB（`M`） |
| **`SKEW(x, n)`** | 滚动偏度 | `x.rolling(n).skew()` | 收益分布的不对称；「阴跌 vs 急拉」判别 | 544 ms / +64 MB（`M`） |
| **`KURT(x, n)`** | 滚动峰度 | `x.rolling(n).kurt()` | 尾部风险；配合 DSR 的 γ₄ 输入（§4.1） | 529 ms / +64 MB（`M`） |
| **`MED(x, n)`** | 滚动中位数 | `x.rolling(n).median()` | 抗极值的中枢；MAD-clip 的基准 | 与 QUANTILE 同量级 |
| **`PRODUCT(x, n)`** | 滚动连乘 | `np.exp(np.log(x).rolling(n).sum())`（x>0 时；否则走 `rolling.apply(np.prod)`） | WQ101 `product`；复利型累积 | log 变换后等价于 SUM，很快 |
| **`LOG/SIGN/POWER`** | 逐元素 | `np.log(x)` / `np.sign(x)` / `x ** a` | WQ101 `signedpower`；`Corr(close, Log(volume+1), d)` 的必需件 | 忽略不计 |

**总计 16 个，其中 5 个是截面算子、11 个是时序算子。** 全部只用 pandas/numpy 现有能力，**零新依赖**。

#### 实现要点（不照做会踩的坑）

1. **`CORR` / `RSQUARE` 必须抄 Qlib 的零方差守卫。** 窗口内任一边 `std ≈ 0`（`atol=2e-05`）时置 NaN。A 股一字板 / 停牌补全会造出大量恒定窗口，不置 NaN 就是伪相关。
2. **`SLOPE` 不要用 `rolling.apply(polyfit)`。** 固定时间下标下斜率有闭式解，且分子是一次**固定权重卷积** —— 与 `functions.py` 里 `WMA` L86–L95 的「按权重逐位累加平移矩阵」是同一段骨架，可以直接复用。本机实测 414 ms 且与 `np.polyfit` 逐位相等（`M`）；`rolling.apply` 会退化成逐窗口 Python 回调，慢两到三个数量级。
3. **`QUANTILE` / `TSRANK` / `SKEW` / `KURT` 走 pandas 原生 `rolling.*`，不要自己写滑窗。** 实测峰值都在 +70 MB 以内，因为 pandas 内部是流式的，不会物化 `(rows-n+1, cols, n)`。**只有需要 `argmax` 这类必须看整窗的算子才走 `_rolling_column_chunks`**（`functions.py` 已有的 256 列分块），原因见该文件 L389–L396 的注释：一旦物化三维窗口，250 天 × 5500 只 × N=60 就是 1.5 GB、700 天 4.3 GB，而服务器可用内存只有 1.1 G。
4. **`CSRANK` 的 NaN 语义要定死。** `rank(axis=1, pct=True)` 对 NaN 返回 NaN（不参与排名），这正是想要的：停牌票不该占一个名次。但要注意**分母是当日非 NaN 的数量**，所以 pct 值在停牌多的日子会整体漂移 —— 做时序比较时必须先 `CSRANK` 再比，不能反过来。
5. **截面算子必须在「同一天所有票都可见」的前提下算，这是新的前视风险面。** 现有 `guard_strategy` 的前视审计（`src/strategy/application/audit.py`）是按**列截断一致性**做的（小宇宙全列、大宇宙分片）—— 截面算子**天然违反列截断一致性**（少一只票，所有票的 rank 都变）。**上截面算子之前必须先给 audit 加一条「截面算子豁免 + 改判为行截断一致性」的规则**，否则要么审计误报、要么被迫关掉审计。这是本节唯一有架构成本的一条。

#### 本机基准（`M`，700×5547 float64 面板 ≈ `market_hot.db` 实际形状）

```text
panel (700, 5547)  mem 31.1 MB/field
  CSRank   df.rank(axis=1, pct=True)     311.5 ms   peak +  97.2 MB
  CSZScore (x-mean)/std  axis=1           112.4 ms   peak + 159.2 MB
  CSDemean x-mean(axis=1)    35.8 ms   peak +  62.2 MB
  Corr     rolling(20).corr(other)   3130.2 ms   peak + 138.0 MB
  Skew     rolling(20).skew()       543.6 ms   peak +  63.7 MB
  Kurt rolling(20).kurt()       528.8 ms   peak +  63.7 MB
  Quantile rolling(20).quantile(0.8)1635.6 ms   peak +  63.7 MB
  TsRank   rolling(20).rank(pct=True)       1833.7 ms   peak +  69.3 MB
  Slope    闭式卷积（parity vs polyfit: True） 414.4 ms
  IdxMax   sliding_window_view 分块 256       222.1 ms
```

**回归三件套的正确性核对（`M`）**：上表的 `SLOPE` / `RESI` / `RSQUARE` 三个闭式实现，在同一窗口上与真实 OLS（`np.polyfit` / `np.corrcoef`）逐位相等——`SLOPE 0.1323488218`、`RESI −0.8808418077`、`RSQUARE 0.3001834512`，三项 `np.isclose` 全 True。**即这三行可以直接抄进 `functions.py`，不需要再推导。**

把 16 个算子各跑一遍 N=20 的窗口，总耗时量级 **10 秒以内、峰值增量 < 200 MB**。对照：`market_hot.db` 本身 1,022.1 MB（`M*`），面板一次只加载需要的字段。**结论：算子这块没有性能或内存障碍，只有「没人写」这一个障碍。**

### 2.5 `ta-lib` / `pandas-ta` / `ta`：要不要引

| 库 | 规模 | 形态 | 判断 |
|---|---|---|---|
| `TA-Lib/ta-lib-python` | 12,203★ / 2,000⑂ / BSD-2（`P1`） | Cython 绑定，**依赖 TA-Lib C 库**（0.6.5 起有 wheel，但 PyInstaller 打包要另外处理二进制）。150+ 指标 + K 线形态识别 | **不引**。它给的是 §2.1 的 A/B 两族（我们已有 40 个同类函数），**不给 C/D/E/F 四族**——没有截面 rank、没有 pairwise Corr、没有 Slope/Resi。用编译依赖换我们不缺的东西 |
| `bukosabino/ta` | 5,180★ / 1,153⑂ / MIT（`P1`） | 纯 pandas + numpy，**43 个指标** | **不引，但可当抄写对照**。Aroon / Donchian / Ulcer / KAMA / Vortex 这几个本仓没有，若哪天要补，照它的实现改成面板版即可（它是单票 Series 口径） |
| `pandas-ta` | — | — | **`twopirllc/pandas-ta` 本轮取回 HTTP 404**（`P1` 负面观察，2026-08-25）。原仓库已不可达。**这本身就是不引的充分理由**：一个会 404 的上游不能进 `requirements.txt` |

**统一结论**：三个 TA 库解决的都是「指标不够多」，而 Loci 的问题是「**算子族不齐**」。40 个技术指标全是 A/B 两族的排列组合，再加 150 个还是 A/B 族。**补 §2.4 那 16 个算子的边际收益远高于引任何一个 TA 库**，而且成本是负的（不新增依赖）。

---

## 3. 截面 vs 时序：范式差异与最小改造路径

### 3.1 差异是什么

| | 通达信 / Loci 现状 | 主流因子体系 |
|---|---|---|
| 每只票看什么 | **只看自己的历史**。`CROSS(MA5, MA10)` 对每列独立求值 | **看今天全市场的相对位置**。`rank(x)` 的值取决于别的票 |
| 输出 | **布尔信号**：满足 / 不满足 | **实数分数**：排第几 |
| 选多少只 | 满足条件的都算「命中」，数量随行情波动（大涨那天几百只） | 永远是 Top-N，数量恒定 |
| 可比性 | 不同票之间的信号强弱**无法比较**（都是 True） | 天然可比、可排序、可加权 |
| 择时耦合 | **强耦合**。整个市场都涨时命中数暴涨，等于自动加仓 | **解耦**。截面排序对市场整体涨跌免疫，择时是另一个独立决策 |
| 评估工具 | 只能算「每笔均净 / 胜率 / 盈亏比」 | 能算 IC / ICIR / 分组单调性 / 自相关 |

### 3.2 后果：这不是审美差异，是三个具体的坏结果

**后果一：命中数不可控，导致组合层极度脆弱。** 布尔信号在极端行情日命中数会翻几倍，而资金是固定的。本仓 `2026-08-dragon-survivorship-and-portfolio-fragility.md` 实测出这个机制的量级：**信号数只差 3.4%，组合全期收益差 187%（34.09% vs 97.80%），而逐笔只差 4.5%**。截面 Top-N 从定义上消除这个自由度。

**后果二：无法区分「因子有效」和「大盘在涨」。** 时序信号的收益里混着 beta。`2026-08-tail-1450-next-day-touch-backtest.md` 已经撞上过这堵墙：带 `breadth≥55`（市场宽度）的组合**日内截面中性化后一律转负** —— 那是择时不是选股。截面体系里这个诊断是免费的（`demeaned=True` 一开关就有）。

**后果三：拿不到 IC，就没法做 §1.4 那十关里的前四关。** 布尔信号只有 0/1，Spearman IC 退化成点二列相关，ICIR 无意义，分组单调性无从谈起。**这是为什么本仓九篇单因子研究只能给出「每笔均净 / 胜率 / 盈亏比」而给不出 IC** —— 不是没做，是当前范式下算不了。

### 3.3 代价其实极低：面板结构已经是对的

`src/formula/domain/functions.py` 模块 docstring 原文（`P1`）：

> 每个函数都同时接受 `pd.Series`（单票）与 `pd.DataFrame`（全市场面板，**index=交易日 / columns=股票代码**）… 约定：时间轴永远是 `axis=0`。

**`columns=股票代码` 意味着截面就是 `axis=1`，而 `axis=1` 的算子 pandas 全都自带。** 上一节实测：`df.rank(axis=1, pct=True)` 在 700×5547 上 **311 ms / 峰值 +97 MB**。对照 `AVEDEV` 这种已经在跑的滚动算子（要分块滑窗才不 OOM），截面 rank **便宜得多**。

换句话说：**范式差异是概念上的，不是工程上的。** 工程上要动的只有三处：

1. `functions.py` 加 5 个截面算子（§2.4 前五行）；
2. `screen_formula_evaluator.py` 的 `apply_formula_call` 注册表加 5 个 `if`（该文件就是一串 `if name == ...`，扩展成本恒定）；
3. `audit.py` 的前视闸门加一条截面算子规则（§2.4 要点 5，唯一有架构成本的一处）。

### 3.4 把「战法」升级成「因子 + 打分排序 + Top-N」的最小路径

**好消息：排序与 Top-N 的钩子已经存在。** `src/strategy/application/screener.py` L263–L270（`P1`）：

```python
rank_by = str(getattr(engine, "screen_rank_factor", "") or "").strip() or None
pick_codes = result.picks_on(target_date, rank_by=rank_by)
watch_codes = [c for c in result.watch_picks_on(target_date, rank_by=rank_by) if c not in picked]
```

即：策略引擎只要声明 `screen_rank_factor = "<某个因子名>"`，`picks_on` 就会按该因子排序取 Top-N。**这条路已经通了，缺的只是「有没有一个值得排序的因子」。**

#### 五步改造（每步独立可回滚，不推倒任何现役战法）

| 步 | 做什么 | 改动面 | 验收 |
|---|---|---|---|
| **S1** | `functions.py` 补 `CSRANK` / `CSZSCORE` / `CSDEMEAN`（先只补这三个），`tests/formula/` 补面板/单票同构与 NaN 语义用例 | 1 源文件 + 1 测试文件 | 面板与单票结果一致；停牌列不占名次 |
| **S2** | `audit.py` 加截面算子规则：声明了截面算子的策略改用**行截断一致性**（截掉最早若干天，结果对齐）而非列截断 | 1 源文件 | `guard_strategy` 对截面策略不再误报 block |
| **S3** | 新增 `src/strategy/application/factor_report.py`（**只读、不入库**）：吃 `(因子面板, 前瞻收益面板)`，吐 §1.5 那七行的产物 + `tot_loss/fwdret_loss/bin_loss` | 1 新文件 ≤ 200 行 | 对一个已知无效因子（如随机数）输出 IC≈0；对 `REF(close,1)/close` 这种未来函数输出 IC≈1（自检） |
| **S4** | 把**现役战法的评分改造成因子**：`qianlong.score_signals` 的 100 分制**本来就是一个因子**，只是权重是手拍的（35/20/15/12/8/8/10/10/15/15）。把它接进 S3 出报告，**先不改权重** | 0 行业务改动（只是接一个 report 调用） | 拿到潜龙评分的 IC / ICIR / 分组单调性 —— **这是本仓第一次能回答「这个评分到底有没有排序能力」** |
| **S5** | 战法声明 `screen_rank_factor = "score"`，Top-N 由排序产生而非「命中即入」 | 每个战法 1 行 | 命中数从随行情波动变为恒定 N；与旧口径做 A/B |

**S4 是整条路径的关键。** 它不改任何业务逻辑、不动线上参数，却第一次让「潜龙/三源的评分排序到底有没有信息」变成一个有数字的问题。而 `2026-08-incumbent-rank-levers.md` 已经用**回测**间接回答过一次（「三源现行评分已是对照里最好的排序」），S4 让同一问题**在因子层直接可测**，代价从「跑一轮全样本回测」降到「跑一次面板相关」。

> **不做的事**：不引入 MultiIndex 长表、不引入 alphalens、不改 `SignalResult` 的现有契约（`picks_on(rank_by=)` 已经够用）、不动 `entry_timing`。

---

## 4. 过拟合防线

### 4.1 Deflated Sharpe Ratio（Bailey & López de Prado, JPM 40(5) 94-107, 2014，`P1` 全文读）

论文最狠的一句在正文第 3 页：

> **a backtest where the researcher has not controlled for the extent of the search involved in his or her finding is worthless, regardless of how excellent the reported performance might be.**

两步公式（附录 1 与正文 Eq.1/Eq.2，含论文自带的 Python 片段）：

**第一步：N 次独立试验下夏普最大值的期望**

```python
emc = 0.5772156649             # Euler-Mascheroni
maxZ = (1-emc)*norm.ppf(1 - 1./N) + emc*norm.ppf(1 - 1./(N*e))
SR0  = E[{SR}] + sqrt(V[{SR}]) * maxZ    # 零假设下取 E[{SR}] = 0
```

**第二步：把 SR0 当成 PSR 的拒绝门槛**

```text
DSR = Z[ ( (SR_hat - SR0) * sqrt(T-1) ) / sqrt(1 - γ3*SR_hat + ((γ4-1)/4)*SR_hat^2) ]
```

`γ3`/`γ4` = 所选策略收益的偏度/峰度，`T` = 样本长度，`V[{SR}]` = **所有试过的策略的夏普的方差**。

论文自带的算例（`P1`）：某人在国债拍卖季节性上试出年化 `SR_hat = 2.5`、`T=1250`（5 年日频），投资人算出 **DSR = 0.90**，低于 95% 门槛 → 拒绝。**若他只做了 N=46 次独立试验，DSR 会是 0.9505，就通过了**；若收益是正态的（γ3=0, γ4=3），N=88 仍可通过。**同一个 2.5 的夏普，是「重大发现」还是「垃圾」，完全由 N 决定。**

**本机按论文公式算出的 `E[max SR]` 表（单位 = 试验间夏普的标准差，`M`）：**

| N | 2 | 5 | 10 | 20 | 50 | 100 | 200 | 500 | 1000 | 5000 | 20000 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E[max SR] | 0.52 | 1.19 | 1.57 | 1.90 | 2.28 | 2.53 | 2.77 | 3.05 | 3.26 | 3.69 | 4.03 |

读法：如果你的候选因子之间夏普的标准差是 0.5，试了 100 次，那么**即使全都没有 alpha**，最好的那个也会有 `0.5 × 2.53 ≈ 1.27` 的样本内年化夏普。**看到 1.27 就上线 = 上线一个纯噪声。**

**从 M 个相关试验反推独立试验数 N̂**（附录 3）：论文给的是按平均相关 ρ̄ 在两端之间插值（ρ̄=0 → N̂=M；ρ̄=1 → N̂=1），本文取线性形式 `N̂ = 1 + (M-1)(1-ρ̄)`。论文同时警告：**当 M > T 时相关矩阵病态、ρ̄ 本身就是过拟合的**，此时应降维或改用信息论方法。对 Loci：网格搜索的参数组合数很容易超过交易日数，**这条警告直接命中**，所以下面的门禁**同时要求 Bonferroni（不需要 ρ̄）与 DSR（需要 ρ̄）两条都过**。

### 4.2 Holdout 与 PBO：为什么「留个样本外」不够

同一篇论文（`P1`）：

> Holdout assesses the generality of a model **as if a single trial had taken place**, again ignoring the rise in false positives as more trials occur. **If we apply the holdout method enough times (say 20 times for a 95% confidence level), false positives are no longer unlikely: They are expected.**

即：**样本外不是免死金牌，它只是又一次试验。** 你在 OOS 上试 20 次，就必然有一次「OOS 也通过」。这直接否定了「我留了 2023 年之后当 OOS 所以没过拟合」这种说法 —— 除非**每个因子只碰 OOS 一次，且这一次记进台账**。

另一条更严重的（正文「BACKTEST OVERFITTING UNDER MEMORY EFFECTS」节，`P1`）：

> Backtest overfitting tends to identify the trading rules that would profit from the most extreme random patterns in sample. **In presence of memory effects, those extreme patterns must be undone, which means that backtest overfitting will lead to loss maximization.**

**在有均值回复的市场里，过拟合的结果不是「样本外收益归零」，是「样本外系统性亏钱」。** A 股短线的反转效应很强（本仓 `short-term-reversal-*` 两篇），这条警告完全适用。

**PBO（Probability of Backtest Overfitting）**：Bailey / Borwein / López de Prado / Zhu 提出的 CSCV（组合对称交叉验证）。DSR 原文的定义（`P1`）：

> PBO assesses whether the strategy selection process has been conducive to overfitting, **in the sense that selected strategies tend to underperform the median of trials out of sample**. PBO is non-parametric and can be applied to any performance statistic, however it requires a large amount of information.

算法：把样本切成 S 份（论文用 S=16），穷举所有「一半当 IS、一半当 OOS」的组合，每次记录「IS 最优的那个策略在 OOS 里排第几分位」，PBO = 「排在中位数以下」的概率。**逻辑推论（本文推导，非原文直述）：PBO ≥ 0.5 意味着你的选择流程比随机挑一个还差。**

关联方法论文：Bailey/Borwein/López de Prado/Zhu, *Pseudo-mathematics and financial charlatanism: The effects of backtest overfitting on out-of-sample performance*, Notices of the AMS, May 2014, 458–471（`P2`，本轮只从 DSR 原文的引用与作者论文目录确认了出处与页码，未读全文）。

**论文还给了一个「什么时候停」的答案**（正文「WHEN SHOULD WE STOP TESTING?」，`P1`）：套用秘书问题 / 1-e 法则 —— **从理论上站得住的参数组合里先随机试约 37%（1/e）只记录不采用，之后逐个试，遇到第一个超过前面全部的就停。** 这给出了一个可执行的搜索预算纪律，而不是「跑到满意为止」。

### 4.3 多重检验校正：Harvey-Liu-Zhu 的 t > 3.0

Harvey, Liu & Zhu, *… and the Cross-Section of Expected Returns*, RFS 29(1) 5–68, 2016（`P1`，Duke 官方 PDF 全文读）。摘要原文：

> We begin with 313 papers … A new factor needs to clear a much higher hurdle, with a **t-statistic greater than 3.0**. We argue that most claimed research findings in financial economics are likely false.

论文给出的**逐个方法的具体门槛**（正文 §3.6–§4.2，`P1`）：

| 方法 | 控制目标 | 门槛 t 值 |
|---|---|---|
| 单次检验（传统） | α=5% | 1.96 |
| **Bonferroni** | FWER 5% | 1.96（1967 起点）→ **3.78（2012）** → 4.00（2032 外推） |
| Holm | FWER 5% | 略低于 Bonferroni，「tracks Bonferroni closely」 |
| **BHY** | **FDR 1%** | 2010 后稳定在 **3.39**（p=0.07%） |
| BHY | FDR 5% | 2.78（2012）→ 2.81（2032） |
| 相关性 + 贝叶斯框架 | FWER 5% / FDR 1% | **3.9 / 3.0** |
| 论文总结 | — | 「the minimum threshold t-statistic for 5% significance is **about 2.8**」；「a newly discovered factor today should have a t-statistic that **exceeds 3.0**」 |

两条容易被忽略的配套数字（`P1`）：

- **71% 的已试因子从未被观察到**（未发表），论文据此估算总试验数约 **820**。所以 3.0 是**下界**，不是安全边际。
- 论文估计「真正显著」的因子平均月均值 0.55% → **年化 6.6%，在 15% 年化波动下年化夏普只有 0.44**。**真因子的夏普期望是 0.44，不是 2.0。** 任何声称样本内夏普 2+ 的短线因子，第一反应应该是数 N，不是庆祝。

**本机交叉验证（`M`）**：按 Bonferroni 双侧 α=0.05 反算门槛 t，`M=316` 时得 **3.778** —— 与论文表中的 3.78 完全吻合，说明公式与口径对齐。完整表：

| M（试验数） | 1 | 10 | 50 | 100 | 316 | 820 | 1000 | 4479 | 20000 |
|---|---|---|---|---|---|---|---|---|---|
| Bonferroni t | 1.960 | 2.807 | 3.291 | 3.481 | **3.778** | 4.009 | 4.056 | 4.393 | 4.708 |

最后两列不是凑数：**4,479 是本仓 `tail-1450-next-day-touch-backtest.md` 实际跑过的过滤组合数**（那篇的门槛用的是「两段皆正」，若换成统计显著性口径，门槛 t 应是 **4.393**）；**20,000 是 gplearn 默认配置一次搜索的程序数**（§4.5）。

#### ✅ CI 门禁：可执行的数值标准

下表**每一行都是一个可以写进 `tests/` 或 CI job 的断言**。红 = 阻断合并；黄 = 允许进候选池但禁止上线。

**Tier 0 — 数据前置（不过就不许算后面任何数）**

| 门禁 | 阈值 | 失败动作 |
|---|---|---|
| 样本交易日数 | `≥ 750`（3 年） | 红 |
| 每日截面有效标的数（中位数） | `≥ 300` | 红 |
| `tot_loss`（对齐 alphalens `max_loss`） | `≤ 0.35` | 红 |
| `bin_loss`（分桶阶段丢弃率） | `≤ 0.10`，且**单日峰值 ≤ 0.30** | 黄（单日峰值超标 → 红） |
| 退市票覆盖：`instruments.delist_date` 非空比例 | `≥ 0.95` | **红 —— 当前实测 0.00%（`M*`），本门禁现在必然红。见 §7.1** |
| 标签口径 | 必须是 `close(t+2)/close(t+1)-1` 或等价的「T+1 建仓」口径；出现 `close(t+1)/close(t)` 直接判失败 | 红 |

**Tier 1 — 单因子（候选池准入）**

| 门禁 | 阈值 | 口径 |
|---|---|---|
| 绝对 Rank IC 均值 | `≥ 0.020` | 逐日 Spearman，全样本 |
| Rank ICIR | `≥ 0.15`（候选） / `≥ 0.30`（可作排序主键） | `mean/std`。0.30 的来源：Qlib CSI300+Alpha158 的 **Linear 基线 ICIR 恰好 0.3000**，即「一个 158 特征 OLS 的水平」 |
| IC 的 Newey-West t 值 | `≥ 3.0` | HLZ 门槛。滞后阶 = 持有期（重叠窗口必须修正）。`n=750, k=5` 时等价于 ICIR ≥ 0.246 |
| 分组单调性 | 5 组 demean 后均值对组号的 Spearman `≥ 0.9`（允许一次相邻反转） | `demeaned=True` |
| Q5−Q1 年化夏普（扣费后） | `≥ 0.5`（候选） / `≥ 1.0`（上线） | 0.5 的来源：**HLZ 估计的真因子平均年化夏普 0.44** |
| 成本档 | **单边 10 bp / 双边 20 bp** 下达标 | 20 bp 双边对齐 Qlib 官方 config（`open_cost 0.0005 + close_cost 0.0015`）；本仓 `incumbent-rank-levers` 用 3/5/10 bp 三档，取最严那档 |
| `factor_rank_autocorrelation(1)` | `0.60 ≤ ρ ≤ 0.99` | 低于 0.60 → 每天重排，换手必爆；高于 0.99 → 排序几乎不动，多半是市值/价格的影子 |
| `quantile_turnover(Q5, 1)` | `≤ 0.50` | 与上一条互为交叉验证 |
| 逐年 Rank IC | 覆盖 `≥ 5` 个自然年；其中为正的 `≥ 80%`；且**没有任何一年 < −0.01** | 本仓 `incumbent-rank-levers` 的 14 组无一通过逐年全正，这条会拦下大部分候选 |
| 样本外 | 时间切分（禁止随机切分）；OOS `≥ 2` 年；`OOS Rank IC ≥ 0.5 × IS Rank IC` 且**同号** | OOS 段在因子定型前物理不可读 |

**Tier 2 — 多重检验（上线准入，需 trial 台账）**

| 门禁 | 阈值 | 说明 |
|---|---|---|
| trial 台账存在且 append-only | 每行链式 hash 校验通过 | **M 必须从台账读，不许人工填**。这是整个 Tier 2 的前提 |
| Bonferroni | `t ≥ Z⁻¹(1 − 0.025/M)`，M = 台账里该因子族的累计试验数 | 查 §4.3 表；M=100 → 3.481，M=1000 → 4.056 |
| DSR | `≥ 0.95` | `SR0 = sqrt(V[{SR}]) × maxZ(N̂)`，`N̂ = 1 + (M−1)(1−ρ̄)`；γ3/γ4 取该策略日收益的偏峰度 |
| PBO（CSCV, S=16） | `≤ 0.25` 上线 / `> 0.50` 红 | `> 0.5` = 选择流程比随机差 |
| 预注册 | 跑之前写入台账：表达式 hash + 参数网格基数 + 持有期 + 成本档 + 预设阈值；**跑完只许 append 结果，不许改预注册行** | CI 校验 hash 链 |
| 搜索预算 | 单个因子族一次立项的参数组合数 `≤ 200`；超出必须拆成独立立项并各自计 M | 对齐 1/e 法则的「有限候选集」前提 |

**零依赖实现说明**：上面唯一需要「统计库」的是 `Z` 与 `Z⁻¹`（正态 CDF 与分位）。**Python 标准库 `statistics.NormalDist()` 直接提供 `.cdf()` 与 `.inv_cdf()`**（本机 3.12.13 实测 `NormalDist().inv_cdf(0.975) = 1.959964`，`M`）。**Bonferroni、DSR、PSR 全套可以零新依赖实现。** PBO 只需要 `itertools.combinations` + 排序。

### 4.4 现在就能算的一件事

把 §4.3 的 Tier 1 套到本仓已有的数字上：`2026-08-incumbent-strategy-full-sample-benchmark.md` 报的潜龙/三源全样本每笔均净 **+0.55% / +0.46%**、胜率双双 **< 50%**、中位数转负、潜龙回撤 **−41.3%**。这些数**连 Tier 1 的第一关（Rank IC）都还没算过** —— 因为布尔信号算不出来（§3.2 后果三）。**S1+S3+S4（§3.4）跑完的第一天，就能第一次给这两个战法一个 IC 数字。**

### 4.5 gplearn 与遗传算法挖因子：为什么它是过拟合的放大器

`trevorstephens/gplearn`（1,879★ / 326⑂ / BSD-3，`P1`，读了 `functions.py` 与 `genetic.py`）。

**第一个硬事实：它的内置算子集只有 15 个，全是逐元素的。**

```python
add2 sub2 mul2 div2 sqrt1 log1 neg1 inv1 abs1 max2 min2 sin1 cos1 tan1 sig1
```

（`functions.py` L145–L159）**没有一个时序算子，没有一个截面算子。** 要做因子挖掘必须自己 `make_function` 注册；而 `make_function` 拿到的是**裸 numpy 一维数组，没有 index、没有分组信息** —— 也就是说你在自定义算子里**无法知道哪一段属于哪只票、哪一天**。把面板 `ravel()` 喂进去，`rolling` 会跨股票边界；按股票循环，又失去截面。**「用 gplearn 挖因子」的公开实现里，绝大多数在这一点上是错的。**

**第二个硬事实：默认配置一次搜索评估 20,000 个程序。**

`SymbolicTransformer` 默认（`genetic.py` L1403–L1414，`P1`）：`population_size=1000`、`generations=20`、`hall_of_fame=100`、`n_components=10`、`metric="pearson"`、`parsimony_coefficient=0.001`。

`1000 × 20 = 20,000` 次评估 → **M = 20,000**。查 §4.3 表：Bonferroni 门槛 **t ≥ 4.708**；查 §4.1 表：即使全部无 alpha，最好那个的样本内夏普期望也有 `sqrt(V[{SR}]) × 4.03`。

**第三个事实（这个是它做对的）**：它自带去相关。选完 `hall_of_fame` 后：

```python
# Iteratively remove least fit individual of most correlated pair
while len(components) > self.n_components:
    most_correlated = np.unravel_index(np.argmax(correlations), correlations.shape)
```

即在 100 个最优里反复剔除「最相关那一对中较差的那个」直到剩 10 个。**这正是 §4.1 里 `N̂` 修正想解决的问题的一个工程近似** —— 但它只降低了输出的冗余，**没有降低 M**。DSR 里的 N 仍然是 20,000。

**判断：不引 gplearn。** 三条理由，按重要性排序：

1. **它把 M 从个位数推到万级，而我们连 M=1 的台账都没有。** 在 `ops.db.strategy_backtests` 是 0 行的前提下引入一个每次跑出 20,000 次试验的工具，等于主动把「无法计算 DSR」这个问题放大四个数量级。
2. **它的算子集对我们没用。** 15 个逐元素函数，我们缺的是 §2.4 那 16 个时序/截面算子。要用 gplearn 挖因子，得先把那 16 个算子写出来再 `make_function` 包一遍 —— **先做 §2.4 才有 gplearn 可谈，顺序不能反**。
3. **依赖**：gplearn 依赖 scikit-learn，同样不在 `requirements.txt`。

**如果将来要做符号回归**：正确顺序是 ①§2.4 算子 → ②§3.4 的 S1–S5 → ③trial 台账 → ④才谈 GP。而且**必须把面板按「每天一个截面」组织，fitness 用逐日 Rank IC 的均值而不是全样本 Pearson**（gplearn 的 `metric="pearson"` 是把整个矩阵拉平算一个相关，在面板数据上这个数由跨股票的量纲差异主导，不是 alpha）。这一条是 gplearn 用在因子挖掘上最常见的静默错误。

---

## 5. 机器学习那一层要不要碰

### 5.1 Qlib benchmark 的一手数字

`examples/benchmarks/README.md`（`P1`）。口径：CSI300，训练 2008-01-01–2014-12-31 / 验证 2015–2016 / **测试 2017-01-01–2020-08-01**，每格是 **20 个随机种子**的均值±标准差；组合层为 `TopkDropoutStrategy(topk=50, n_drop=5)`，`open_cost 0.0005 + close_cost 0.0015`（**双边 20 bp**），`limit_threshold 0.095`，`deal_price=close`。

**Alpha158（人工特征）· CSI300**

| 模型 | IC | ICIR | Rank IC | Rank ICIR | 年化收益 | IR | 最大回撤 |
|---|---|---|---|---|---|---|---|
| TabNet | 0.0204 | 0.1554 | 0.0333 | 0.2552 | 0.0227 | 0.3676 | −0.1089 |
| TCN | 0.0279 | 0.2181 | 0.0421 | 0.3429 | 0.0262 | 0.4133 | −0.1090 |
| **Linear** | **0.0397** | **0.3000** | 0.0472 | 0.3531 | **0.0692** | **0.9209** | −0.1509 |
| MLP | 0.0376 | 0.2846 | 0.0429 | 0.3220 | 0.0895 | 1.1408 | −0.1103 |
| XGBoost | 0.0498 | 0.3779 | 0.0505 | 0.4131 | 0.0780 | 0.9070 | −0.1168 |
| CatBoost | 0.0481 | 0.3366 | 0.0454 | 0.3311 | 0.0765 | 0.8032 | −0.1092 |
| **LightGBM** | **0.0448** | **0.3660** | 0.0469 | 0.3877 | **0.0901** | **1.0164** | −0.1038 |
| DoubleEnsemble（榜首） | 0.0521 | 0.4223 | 0.0502 | 0.4117 | 0.1158 | 1.3432 | −0.0920 |

**Alpha360（原始量价，人工特征少）· CSI300**

| 模型 | IC | 年化收益 | IR |
|---|---|---|---|
| Transformer | 0.0114 | **−0.0270** | −0.3378 |
| TabNet | 0.0099 | **−0.0369** | −0.3892 |
| KRNN | 0.0173 | **−0.0465** | −0.5415 |
| MLP | 0.0273 | **0.0029** | 0.0274 |
| Sandwich | 0.0258 | 0.0005 | 0.0001 |
| LightGBM | 0.0400 | 0.0558 | 0.7632 |
| HIST（榜首） | 0.0522 | 0.0987 | 1.3726 |

**CSI500 · Alpha158**：LightGBM IC 0.0399 / IR **1.5650** / 回撤 −0.0635；Linear IC 0.0332 / IR 0.1723 / 回撤 **−0.4876**。

### 5.2 从这些数字能读出什么

1. **整个 SOTA 的 IC 都在 0.02–0.05 这个带里。** 从最差的 TabNet(0.0204) 到榜首 DoubleEnsemble(0.0521)，跨度不到 3 倍。**IC 0.05 就是天花板附近**，不存在「换个模型 IC 翻倍」。
2. **线性模型拿到了 GBDT 90.6% 的 IR**（0.9209 / 1.0164），IC 差 0.005。**模型复杂度的边际收益极小。**
3. **特征比模型重要得多。** 同一个 LightGBM：Alpha158 年化 9.01% / IR 1.0164，Alpha360 年化 5.58% / IR 0.7632。同一个 MLP：Alpha158 年化 8.95%，Alpha360 年化 **0.29%**。**换特征的影响 (8.66 pp) 远大于换模型的影响 (2.09 pp)。**
4. **深度模型在弱特征上会变成负的。** Alpha360 上 Transformer −2.70%、TabNet −3.69%、KRNN −4.65%。这不是调参问题，是 20 个种子的均值。
5. **同一个模型换个宇宙，稳定性差异巨大。** Linear 在 CSI300 回撤 −15.1%，在 CSI500 回撤 **−48.8%**。
6. **别忘了这些数字的组合口径是持 50 只。** Loci 是 3–10 只。本仓 `dragon-survivorship-and-portfolio-fragility.md` 实测：信号数差 3.4% → 组合收益差 187%。**把 topk 从 50 压到 3，IR 1.0164 这个数没有任何参考价值。**

### 5.3 特征泄漏的常见坑（对照 Loci 的现状逐条）

| 坑 | 表现 | Loci 现状 |
|---|---|---|
| **标签用了当日可成交价** | `close(t+1)/close(t)-1` 当标签，隐含「信号日收盘能成交」 | 已规避：`entry_timing=next_open` 是策略声明的、`guard_strategy` 静态闸门会拦 `entry_timing=open` 裸用盘中字段 |
| **归一化在全样本上拟合** | `ZScoreNorm` 用了 OOS 段的均值方差 | **有风险**：目前没有「训练段拟合」的概念。Qlib 用 `fit_start_time/fit_end_time` 划死；alphalens 的 `filter_zscore` 就是反面教材（文档自认前视） |
| **去极值 / 缺失填充用未来信息** | `fillna(mean)` 的 mean 来自全样本 | **有风险**：同上 |
| **复权因子用了当下的最新值** | 前复权面板隐含「未来的除权都已知」 | **已识别但未解决**：`market/README.md` 记「因子表是同步时一次性拉的…历史价格会全部错位…前复权面板整列失真」，`sentinel` 有 `factor_age` / `factor_coverage` 体检 |
| **存活偏差** | 训练集只有活到今天的票 | **未解决，且是硬伤**：`delist_date` 填充 **0 条**，`status` 分布 delisted=1 / normal=5546（`M*`）。见 §7.1 |
| **成分股用了当下成分表** | 用今天的沪深300成分回测2018 | 未核实（本轮未读 `universe` 解析逻辑） |
| **交叉验证随机切分** | 时序数据用 KFold，未来样本进训练集 | 尚未涉及（还没有 ML），但一旦上必踩 |
| **重叠标签** | 持有 5 天的标签逐日滚动，相邻样本 80% 重叠，t 值虚高 √5 倍 | 尚未涉及。§4.3 的 Newey-West 要求就是为这条准备的 |

### 5.4 明确结论：**不碰 ML 模型层，改为「线性打分 + 截面排序」**

**判断：在 1.1 GB 内存 + 单机 + 用户是短线交易者（持 3–10 只、1–5 天）的前提下，不引入 LightGBM 及任何深度模型。**

四条理由：

| # | 理由 | 支撑 |
|---|---|---|
| 1 | **收益极小**：Linear 拿到 GBDT 90.6% 的 IR，而 Alpha158→Alpha360 的特征差异造成 8.66 pp 年化差 | §5.1 一手表 |
| 2 | **我们缺的正是特征侧**：§2.4 的 16 个算子没补之前，能喂给模型的特征还不到 Alpha158 的一半 | §2.1 六族对照 |
| 3 | **M 不可数 → DSR 无法计算 → 按 Bailey 的原话该结果 “worthless”**：`ops.db.strategy_backtests` **0 行**、`strategy_versions` **0 行**（`M*`），回测结果零持久化 | §4.1 + §7.2 |
| 4 | **三重数据缺陷叠加**：存活偏差（`delist_date` 0 条）+ 归一化无训练段划分 + 无重叠标签修正。GBDT 比线性模型**更擅长**去拟合这三类泄漏 | §5.3 |
| 5 | **依赖与打包**：`lightgbm` / `sklearn` 都不在 `requirements.txt`；lightgbm 是编译产物，PyInstaller 单文件打包要额外处理 | `P1` requirements.txt |

**推荐做的（同一个位置，十分之一的成本）**：把 §3.4 的 S4 做出来 —— 现役战法评分（`qianlong.score_signals` 那套手拍权重）**本来就是一个线性打分模型**，只是权重没经过任何拟合与检验。先给它一个 IC 数字，再谈要不要让权重由数据决定。**从「手拍权重的线性模型」到「拟合权重的线性模型」这一步的收益，大概率高于从「线性」到「GBDT」那一步**（Qlib 的表就是证据：Linear 0.9209 vs LightGBM 1.0164）。

#### 解锁条件（可审计，全部满足才重新评估）

1. `instruments.delist_date` 非空覆盖 `≥ 95%`，且 `quotes_daily` 含已退市代码的历史行情；
2. trial 台账落库并 append-only 运行 `≥ 3` 个月，累计 `≥ 200` 条带 OOS 结果的记录；
3. §2.4 的 16 个算子全部落地并通过面板/单票同构测试；
4. 至少 3 个单因子通过 §4.3 的 Tier 1 全部门禁；
5. 归一化/填充改造为「训练段拟合、推理段应用」。

**这五条没有全绿之前，任何「上个 LightGBM 试试」的提议直接驳回，不需要再讨论。**

---

## 6. 组合优化要不要碰

### 6.1 两个库的实际形态

| 库 | 规模 | 依赖 | 提供什么 |
|---|---|---|---|
| `dcajasn/Riskfolio-Lib` | 4,456★ / 704⑂ / BSD-3（`P1`） | **建在 CVXPY 上**，仓库主语言标 C++（打包编译求解器） | 均值-风险优化 **26 种凸风险度量**、风险平价 **22 种**、HRP/HERC **37 种**、NCO、Worst-Case MVO、Relaxed RP |
| `robertmartin8/PyPortfolioOpt` | 5,979★ / 1,171⑂ / MIT（`P1`） | cvxpy + scipy | EfficientFrontier（含 CVaR/CDaR/半方差）、Black-Litterman、HRP、CLA、DiscreteAllocation |

两者都要 **cvxpy**（带编译求解器 ECOS/OSQP/SCS）。**都不在 `requirements.txt`。**

### 6.2 为什么在 3–10 只 / 1–5 天的场景下不成立

**理由一（决定性）：估计误差。** DeMiguel, Garlappi & Uppal, *Optimal Versus Naive Diversification: How Inefficient is the 1/N Portfolio Strategy?*, RFS 22(5) 1915–1953, 2009（`P2`，读到 JSTOR/SSRN 摘要原文，未读全文）。摘要原文：

> Based on parameters calibrated to US stock-market data, we find that the critical length of the estimation window is **3000 months for a portfolio with only 25 assets**, and **more than 6000 months for a portfolio with 50 assets**.

即 **250 年 / 500 年**。他们比较了 14 种优化方法（含各类收缩估计），没有一种在合理样本长度下稳定跑赢 1/N。

**理由二：参数数远超可用信息。** N=10 时 MVO 要估 10 个期望收益 + 55 个协方差 = **65 个参数**。而持有期是 1–5 天，你要预测的是这 10 只票未来 3 天的联合分布。**参数数比你的持有期长度还多一个数量级。**

**理由三：HRP 解决的问题我们没有。** HRP 的卖点是 N 很大时样本协方差矩阵病态、求逆放大误差，所以改用层次聚类 + 递归二分避免求逆。**N=3–10 时协方差矩阵不病态**（T ≫ N 轻易满足），聚类树在 3–10 个叶子上退化成近乎任意的二分。**它绕开的那个困难在我们这里不存在，剩下的只有它引入的随意性。**

**理由四：风险平价会偷偷塞进一个已被本仓拒绝的因子。** 风险平价按波动率倒数配权，等价于**系统性超配低波票**。而 `2026-08-low-tvol-streaming-exploration.md` 已判定 **TVOL 低波因子不进候选池、也不进函数目录**。在组合层用风险平价 = 在选股层拒绝了低波、又在配权层把它加回来。

**理由五：期望收益的估计误差主导一切。** Markowitz 优化对 μ 的估计误差极度敏感（"error maximization"）。而 §4.3 引的 HLZ 估计：**真因子的年化夏普期望只有 0.44**。用一个信噪比 0.44 的 μ 去驱动一个 65 参数的二次规划，输出的是噪声的最优组合。

**理由六：工程成本为负。** 为 3–10 只票的权重引入 cvxpy + 编译求解器，在 1.1 GB 内存 + PyInstaller 单文件 + 单机桌面应用的约束下，增加的打包体积、启动时间与失败模式，全部换不来任何可测收益。

### 6.3 明确结论：**不引入任何组合优化库。** 替代方案如下

| 层 | 做法 | 为什么够 | 落点 |
|---|---|---|---|
| **权重** | **等权 1/N**，N = Top-N 的 N | DGU2009 的结论就是「在可得样本长度下 1/N 打赢 14 种优化」。等权同时天然满足单票上限 = 1/N，不需要额外约束 | 现有回测引擎已是等权口径 |
| **选几只** | Top-N 固定（3–10），由 §3.4 的截面排序产生，**不是「命中即入」** | 消除「命中数随行情波动」这个自由度，即 §3.2 后果一 | `screener.picks_on(rank_by=)` 已有 |
| **单票上限** | 等权时自动 = 1/N；若将来做信号强度加权，硬上限 `min(1.5/N, 25%)` | 上限的作用是防单点，不是优化 | 组合约束在本仓已有落点 `src/review/application/portfolio_guard.py::check_portfolio_limits`（本轮只确认符号存在，未读实现） |
| **行业/题材分散** | 同一 KPL 主类题材 **≤ 2 只** 且 **≤ 40% 仓位** | 题材同涨同跌是 A 股短线最大的隐性集中度。用硬上限比用协方差矩阵可靠得多，因为题材归属是**可观测**的，相关性是**估计**的 | KPL 主类口径与 `limit_up_ladder.primaryThemeStats` 一致 |
| **相关性闸门** | 候选池内两只票近 20 日收益相关 `> 0.8` 时只留排序高的那只 | **这是 §2.4 `CORR` 算子的又一个用途，一行 pandas**：`ret.tail(20).corr()`。比全协方差优化便宜三个数量级，且解决同一个问题的 90% | 需 §2.4 的 `CORR` |
| **总仓位** | 市场宽度不足时线性缩仓（如 `breadth < 55%` 起按线性降至 0） | 择时应该是显式的一条规则，不是优化器的副产品。§3.2 后果二说明混在一起会看错归因 | 现有 `market_overview` 宽度指标 |
| **尾部风险** | **单笔止损**。这才是真正控制尾部的东西 | 协方差矩阵管的是二阶矩，A 股短线的尾部由跌停/一字/停牌决定，那是二阶矩描述不了的 | 回测引擎已有止损/止盈与一字板方向处理 |

**一句话**：**组合层要的是「约束」，不是「优化」。** 约束可以用可观测量（题材归属、单票上限、宽度）写死，优化必须用估计量（μ、Σ）驱动，而在 3–10 只 / 1–5 天的尺度上估计量全是噪声。

### 6.4 quantstats：可以用，但要知道它不给什么

`ranaroussi/quantstats`（7,584★ / 1,229⑂ / Apache-2.0，`P1`）。约 60 个统计函数，含 `sharpe(smart=True)`（自相关惩罚）、`sortino`、`calmar`、`ulcer_index`、`kelly_criterion`、`risk_of_ruin`、`montecarlo_sharpe`，以及 **`probabilistic_sharpe_ratio`（PSR）**。

**它给的**：一张很全的绩效报表 + PSR（DSR 的前半截）。

**它不给的（关键）**：

1. **没有 Deflated Sharpe**。有 PSR 但没有把 `SR0` 设成 `E[max SR]` 的那一步 —— 也就是**没有 N**。§4.1 的整个论点它接不上。
2. **没有 PBO、没有任何多重检验校正**。
3. **它的所有指标都是「按周期」不是「按笔」**，README 自己写了：

> Win Rate = percentage of **periods** with positive returns … A single 5-day trade might span 3 positive days and 2 negative days - QuantStats would count these as 3 “wins” and 2 “losses” at the daily level.

   **这与本仓全部研究文档的「每笔胜率 / 盈亏比 / 每笔均净」口径直接冲突。** 拿 quantstats 的 win_rate 和 `incumbent-strategy-full-sample-benchmark.md` 的胜率并列会得到两个不可比的数。
4. 依赖 scipy / matplotlib / seaborn / yfinance，同样不在 `requirements.txt`。

**判断**：**不引库，但抄两个指标** —— `probabilistic_sharpe_ratio` 的实现思路（它已经是 Bailey-López de Prado 的 PSR）和 `sharpe(smart=True)` 的自相关惩罚。两个都是十几行，用 `statistics.NormalDist` 就能写完。**报表本身用现有前端 ECharts 出，不需要它。**

---

## 7. 本仓的三个前置阻断项（做上面任何一件事之前先看这里）

> 本节数字来自**主 agent dbstat 实测 2026-08-25**（`M*`），真实数据目录 `E:\entertainment_software\Loci\data`（不是仓库里那个空的 `data/`）。

### 7.1 存活偏差：`delist_date` 填充 0 条 —— 硬伤实锤

`instruments.delist_date` **非空计数 = 0**；`status` 分布 **delisted=1 / normal=5546**。`quotes_daily` 覆盖 5,547 只 / 16,966,403 行 / 1990-12-19 – 2026-08-25。

这条**在 §1.4 的十关里同时污染第 1、5、6、8、9 关**：

- 分组收益的 Q1（最差组）里，那些真正跌到退市的票**从来就不在样本里** → Q5−Q1 价差被系统性低估？不 —— 是 **Q1 被系统性抬高，多空价差被低估，而多头组合的收益被高估**（因为整个宇宙都是幸存者）。
- 逐年稳定性：越早的年份幸存者偏差越重。逐年行数 2010 年前累计 3,305,994 行（19.5%），2021 起 6,833,221 行（40.3%）—— **早期样本又少又是幸存者**。
- 本仓 `2026-08-dragon-survivorship-and-portfolio-fragility.md` 早已写明「退市存活偏差**本地不可测**」，主 agent 的 dbstat 把它从「不可测」升级为「已确认为 0」。

**这是 §4.3 Tier 0 里唯一一条现在必然红的门禁。** 在它变绿之前，所有 IC / 分组 / 多空数字都必须带一句「样本为幸存者，方向乐观」。

### 7.2 没有 trial 台账：`strategy_backtests` 0 行 / `strategy_versions` 0 行

`ops.db` 13.8 MB，其中 `job_runs` 11.36 MB / 706 行（≈16 KB/行），而 **`strategy_backtests` 与 `strategy_versions` 都是 0 行 —— 回测结果零持久化**。

后果链条：**没有台账 → 数不出 M → 算不了 Bonferroni 门槛、算不了 DSR、算不了 PBO → §4.3 的整个 Tier 2 不可执行 → 按 Bailey 的原话，任何回测结果 “worthless… regardless of how excellent the reported performance might be”。**

**这是整份文档里性价比最高的一个改动**：一张 append-only 的表，字段不超过 15 个（`trial_id / registered_at / factor_expr_hash / param_grid_size / horizon / cost_bp / preset_thresholds / oos_split_date / status / finished_at / rank_ic / icir / t_nw / ls_sharpe_net / prev_hash`），写入量按 §4.3 的搜索预算上限（单立项 ≤200 组）估算，**一年也涨不到 10 MB**。对照：`market.db` 里光溯源审计（receipts + attempts + 索引 + `idx_quotes_receipt`）就占了 **2,569 MB = 全库 44.8%**（`M*`）—— **我们对「这行数据从哪来」的记录投入了 2.5 GB，对「这个结论怎么得出的」投入了 0 字节。**

### 7.3 分钟线不落库 + 实时数据零留存

`GET /api/market/minute/{code}` 明确不写 `market.db`，live 只有进程内 3–5 秒 TTL 缓存（`M*`）。

影响范围（对本文主题）：

- WQ101 的 `vwap` 只能用日线 `amount/volume` 近似（§2.3 已标注）；
- 任何日内因子（开盘半小时动量、尾盘资金流）**不可回测**，本仓 `tail-1450-*` 两篇已记过同一限制；
- 好消息：**§2.4 的 16 个算子全部只需要日线**，本条不阻断本文的主线建议。

---

## 8. 来源清单与证据分级

| # | 来源 | 取到什么 | 级别 |
|---|---|---|---|
| 1 | `stefan-jansen/alphalens-reloaded` — `src/alphalens/utils.py`（1052 行）、`performance.py`（1197 行）、README | 三张分析的实现、`get_clean_factor` 全部参数与 `max_loss` 逻辑、**无因子去极值**的验证 | `P1` |
| 2 | `microsoft/qlib` — `qlib/workflow/record_temp.py`、`qlib/contrib/eva/alpha.py`、`qlib/data/ops.py`、`qlib/contrib/data/loader.py`、`qlib/contrib/data/handler.py` | `SigAnaRecord` 全文、`calc_ic`/`calc_long_short_return`、30 个算子类清单、Alpha158 全部特征表达式、processors 与 label 定义 | `P1` |
| 3 | `microsoft/qlib` — `examples/benchmarks/README.md`、`LightGBM/workflow_config_lightgbm_Alpha158.yaml`、`Linear/workflow_config_linear_Alpha158.yaml` | §5.1 全部 benchmark 数字（20 seeds）、topk=50/n_drop=5、成本 5bp+15bp、训练/验证/测试切分 | `P1` |
| 4 | Kakushadze, *101 Formulaic Alphas*, arXiv:1601.00991 | 摘要三个数（持有期 0.6–6.4 天、平均相关 15.9%、与换手无关）、附录 A.1 全部算子定义、101 条公式正文 | `P1` |
| 5 | `trevorstephens/gplearn` — `gplearn/functions.py`、`gplearn/genetic.py` | 15 个内置算子、`SymbolicTransformer` 全部默认值、去相关算法、`make_function` 签名 | `P1` |
| 6 | Harvey, Liu & Zhu, *… and the Cross-Section of Expected Returns*, RFS 29(1) 5–68（Duke 官方 PDF） | t>3.0、Bonferroni 3.78/4.00、BHY 3.39/2.78、贝叶斯 3.9/3.0、313 篇/316 因子、71% 缺失、真因子年化夏普 0.44 | `P1` |
| 7 | Bailey & López de Prado, *The Deflated Sharpe Ratio*, JPM 40(5) 94–107（作者站预印本全文） | DSR 两步公式 + 论文自带 Python 片段、算例（SR 2.5 → DSR 0.90；N=46 → 0.9505）、holdout 反驳原文、memory effects → loss maximization、附录 3 的 N̂、1/e 停止法则 | `P1` |
| 8 | Bailey/Borwein/López de Prado/Zhu, *Pseudo-mathematics and financial charlatanism*, Notices of the AMS, May 2014, 458–471 | 仅确认出处与页码（经 DSR 原文引用 + 作者论文目录） | `P2` |
| 9 | DeMiguel, Garlappi & Uppal, RFS 22(5) 1915–1953, 2009 | 3000 个月 / 25 资产、6000 个月 / 50 资产（JSTOR 摘要原文） | `P2`（全文未读） |
| 10 | `dcajasn/Riskfolio-Lib` README | 26/22/37 种风险度量、建在 CVXPY 上、星标与许可 | `P1` |
| 11 | `robertmartin8/PyPortfolioOpt` README | 功能面、cvxpy 依赖、星标与许可 | `P1` |
| 12 | `ranaroussi/quantstats` README + `quantstats/stats.py` | 函数清单、有 PSR 无 DSR、`smart=True` 自相关惩罚、**按周期非按笔**的自述 | `P1` |
| 13 | `TA-Lib/ta-lib-python` README | 150+ 指标、C 库依赖、wheel 覆盖面、星标与许可 | `P1` |
| 14 | `bukosabino/ta` README | **43 个指标**全表、纯 pandas、星标与许可 | `P1` |
| 15 | `twopirllc/pandas-ta` | **HTTP 404**（2026-08-25 取回）。作为「不引」的直接依据 | `P1`（负面观察） |
| 16 | 本仓 `src/formula/domain/functions.py` / `indicators.py` / `chips.py` / `screen_formula_evaluator.py` / `src/strategy/application/screener.py` / `requirements.txt` | 现有 40+2 个函数清单、面板约定、`_COLUMN_CHUNK` 与 1.1 GB 注释、`screen_rank_factor` 钩子、依赖契约 | `P1` |
| 17 | 本机基准（700×5547 合成面板，`.venv` Python 3.12.13） | §2.4 全部耗时/峰值、Slope 闭式解与 `np.polyfit` 逐位相等、`HHVBARS == N-1-IdxMax`、`E[max SR]` 表、Bonferroni t 表（M=316 → 3.778 与论文吻合）、`NormalDist().inv_cdf` 可用 | `M` |
| 18 | 主 agent dbstat 实测 2026-08-25 | market.db 5,740.2 MB 分解、溯源占 44.8%、`strategy_backtests`/`strategy_versions` 0 行、`delist_date` 0 条、逐年行数、分钟线不落库、依赖清单 | `M*` |

### 未取到一手来源的缺口（避免重复检索）

| 缺口 | 尝试过什么 |
|---|---|
| PBO 原文（*The Probability of Backtest Overfitting*, J. Computational Finance）的 CSCV 具体算法与 S=16 的出处 | 只从 DSR 原文的引用段落与作者论文目录确认存在；SSRN 直连 **HTTP 403**；本文对 PBO 的算法描述属**转述 + 逻辑推论**，`> 0.5 = 比随机差` 是本文推导而非原文直述 |
| DeMiguel 2009 全文（14 种方法逐一的表现） | 只读到 JSTOR/SSRN 摘要 |
| `pandas-ta` 的指标数与现况 | 原仓库 404；未去找 fork |
| Qlib benchmark 数字是否含成本 | config 里有 `open_cost/close_cost`，但 README 未声明「年化收益」是否已扣。**本文按「已扣」理解，若实际未扣则 §5 的结论只会更强** |
| `portfolio_guard.check_portfolio_limits` 的实现语义 | 只确认符号存在于 `src/review/application/portfolio_guard.py:26`，未读实现 |
| 成分股历史表（回测宇宙是否用了当下成分） | 本轮未读 `universe` 解析逻辑 |

---

## 9. 落地优先级（如果只做一件）

| 序 | 事项 | 成本 | 解锁什么 |
|---|---|---|---|
| **1** | **trial 台账**（一张 append-only 表 + CI 的 hash 链校验） | 1 张表 + 1 个 CI job | §4.3 整个 Tier 2；从「无法评估过拟合」到「可以评估」 |
| **2** | **`CSRANK` / `CSZSCORE` / `CSDEMEAN` 三个截面算子**（§3.4 S1） | 1 源文件 + 1 测试 | §3 全部；311 ms / +97 MB，无性能风险 |
| **3** | **`factor_report.py`**（§3.4 S3，≤200 行，只读不入库） | 1 新文件 | §1.4 的第 1–8 关全部可算 |
| **4** | **把现役战法评分接进 factor_report**（§3.4 S4，0 行业务改动） | 接一个调用 | 本仓第一次拿到潜龙/三源评分的 IC |
| **5** | 补 `CORR` / `SLOPE` / `RSQUARE` / `RESI` / `QUANTILE` / `TSRANK` / `SKEW` / `KURT` 等 11 个时序算子 | 1 源文件 | Alpha158 的 11 个特征族；WQ101 约四成条目 |
| **6** | `audit.py` 的截面算子规则（§2.4 要点 5） | 1 源文件 | 让 2 与 5 能通过前视闸门 |
| **7** | `delist_date` 回填 + 退市票行情同步 | 数据工程，最重 | §4.3 Tier 0 唯一必然红的门禁；也是 §5 解锁条件的第 1 条 |

**1–4 加起来大约是 1 张表 + 2 个源文件 + 1 个新文件，没有任何新依赖，不动任何现役战法的行为。** 做完之后，「这个信号到底有没有」这个问题第一次有了可重复的答案。

---

**本轮未做**：装任何新依赖、跑真实行情面板（基准全部用合成数据）、读 `E:\entertainment_software\Loci\data` 下的任何库文件（§7 数字全部转引自主 agent dbstat）、改除本文件之外的任何仓库文件（含 `INDEX.md`）、commit、push、写库。DSR/PBO/Bonferroni 均**未在真实因子上试算**，§4.3 的阈值是按一手文献与 Qlib 基线**校准的建议值**，未经本仓样本验证。

---

## 摘要

四道工序把「想到信号」变成「敢用它」：对齐面板并报丢弃率、算 IC/分组/换手、按试验数抬门槛、与随机对照；Loci 缺一三四。

第二道只差 16 个算子（5 截面 11 时序；另 3 个仅是改名），纯 pandas 零依赖；700×5547 实测截面 rank 311ms、Slope 414ms。Top-N 钩子已在。

纠正：alphalens 不对因子去极值。门禁核心 Rank ICIR≥0.30、NW t≥3.0、DSR≥0.95、PBO≤0.25。

不上 ML（Linear 已达 GBDT 九成 IR）、不上组合优化（25 资产需 3000 月），改等权+Top-N+题材≤2 只。先做 trial 台账：strategy_backtests 现 0 行。
