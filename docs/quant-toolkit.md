# 量化工具集使用指南

> 行情仓 · 通达信公式引擎 · 策略 · 回测 · 技能包 · 定时任务 · LLM 供应商
>
> 免责：本工具仅用于信息整理与方法论辅助，输出不构成任何投资建议。

---

## 0. 为什么通达信选得快，我们也能快

这套东西的性能关键只有一句话：**把全市场组织成面板，让公式作用在整张表上。**

| | 通达信 | 早先的做法 | 现在 |
|---|---|---|---|
| 数据 | 本地 `.day` 二进制 | 每次实时打 akshare | 本地 `market.db`（5532 只 / 1671 万行 / 2.4 GB） |
| 计算 | C 引擎，**逐票循环** | pandas 逐票 `apply` | **面板向量化，一次算完全市场** |
| 全市场选股 | ~10 秒 | 小时级 | **实测 3.58 秒**（5509 只 × 60 日） |

面板就是 `DataFrame(index=交易日, columns=股票代码)`。在它上面：

```python
REF(close, 1)              # → close.shift(1)        一次覆盖 5000 只票
MA(close, 20)              # → close.rolling(20).mean()
HHV(high, 60)              # → high.rolling(60).max()
COUNT(close > ma20, 12)    # → (close > ma20).rolling(12).sum()
```

全部走 pandas/numpy 的 C 路径。通达信是逐票循环，我们是矩阵运算——**这就是能反超的原因**。

---

## 1. 行情仓

### 首次准备

```bash
python market.py instruments          # 拉证券列表（约 5000 只 + 3 个基准指数）
python market.py sync --limit 400     # 先同步 400 只试跑
python market.py coverage             # 看仓库现状
```

全量回填：

```bash
python market.py sync --workers 4 --interval 0.15
```

**实测（全市场已完成回填）**：5532 只 / 1671 万行 / 2.4 GB / 1794 秒 / 0 失败，
6 并发下 0.32 秒/票。新浪源一次返回全历史，且自带换手率与流通股本。

同步有 watermark 断点：中途断网、被限流、进程被杀，重跑一次即可，
已成功的会自动跳过。`--force` 强制重来。

### 两个存储上的决定

**存不复权原始价 + 稀疏复权因子，不存固化的复权价。** 前复权价每次除权
都会整体重算。若入库时算死，下一次除权后全部历史缓存都会静默出错——
数字还在、看着正常，只是全错了。

**单独维护 `trading_calendar`。** 看着冗余（日期都在 `quotes_daily` 里），
但 `SELECT DISTINCT trade_date` 是全表扫描：400 只票时 648 ms，全市场会
到近 10 秒，而选股、T+N 复盘、回测每次都要问交易日。加表后 **4 ms**。

**面板必须合并成单块内存。** `pivot()` 返回的对象内部是每列一个 block，
5509 列就有 5509 个块，之后每次 shift/加减乘除 pandas 都在 Python 层遍历
这些块。实测 60×5509 的面板（才 330 万个浮点数）：`shift(1)` 98.55 ms →
合并后 0.60 ms，**164 倍**。不做这一步，向量化的全部优势会被块遍历吃光——
全市场选股从 3.6 秒退化到 31 秒。合并要放在 pivot、列筛选、复权乘法
**全部做完之后**，任何一步都会让结果重新变碎。

---

## 2. 策略与选股

```bash
python market.py strategies                      # 已注册战法
python market.py screen qianlong-auction         # 跑一次选股
python market.py bench                           # 性能实测
```

### 已实现

| slug | 战法 | 入场时点 | 源公式 |
|---|---|---|---|
| `qianlong-auction` | 潜龙出海·竞价版 | 当日开盘 | `tdx/潜龙出海_选股.txt` |
| `qianlong-close` | 潜龙出海·原版 | 次日开盘 | `tdx/潜龙出海_选股_原版.txt` |
| `lugw-sanwai` | 卢高文·三外有三 | 次日开盘 | `lugw_tdx_formulas.md` 公式 1 |
| `lugw-tianyi` | 卢高文·天衣无缝 | 次日开盘 | 同上 公式 2 |
| `lugw-daoba` | 卢高文·倒拔杨柳 | 次日开盘 | 同上 公式 3 |
| `lugw-haidi` | 卢高文·海底捞月 | 次日开盘 | 同上 公式 4 |
| `lugw-fenshou` | 卢高文·分手快乐 | 次日开盘 | 同上 公式 5 |
| `lugw-chouma` | 卢高文·筹码峰突破 | 次日开盘 | 同上 公式 6（依赖 `COST()`）|

**入场时点是策略元数据的一部分，不是回测参数。** 同一套形态条件，
"9:25 竞价筛、当日开盘买"和"盘后筛、次日开盘买"是两个完全不同的策略，
收益天差地别。用到当日收盘/最高/最低的策略，只能标 `next_open`——
否则就是拿收盘后才知道的信息去做当日成交。

### 新增一个战法

在 `src/strategies/` 加一个类，实现四个方法后 `register()`：

```python
class MyPicker:
    slug = "my-picker"
    name = "我的战法"
    description = "一句话说清它筛什么"
    entry_timing = "next_open"

    def default_params(self): return {"threshold": 3.0}
    def required_fields(self): return ("open", "high", "low", "close", "volume")
    def min_bars(self): return 60

    def compute(self, panels, params=None):
        p = merge_params(self, params)
        close = panels["close"]
        signals = (close > MA(close, 20)) & (COUNT(close > REF(close, 1), 5) >= 4)
        return SignalResult(signals=signals.fillna(False), factors={"MA20": MA(close, 20)})
```

写完自动被两条守卫检查（见 §7），不需要额外配置。

### 翻译通达信公式时的三个坑

1. **换手率单位。** `HSL` 是百分数（5 表示 5%），行情仓存的是小数
   （0.05 表示 5%）。漏乘 100，"昨换手>=5" 就变成要求 500% 换手——
   永远选不出票，而且不报错，只会安静地返回空结果。
2. **权重方向。** `rolling.apply` 的窗口是"最旧在前、当期在末"。
   把最大权重写给 `window[0]` 就是给了 20 天前那根。这个错误在本项目
   犯过两次（`src/qianlong.py` 的辰星线、`WMA` 的初版），都是被
   "权重必须偏向近期"那条断言当场抓出来的。
3. **别"修正"原公式。** 潜龙出海的辰星线跳过 `REF(YTSL,19)` 却纳入
   `REF(YTSL,20)`，分母 211 与权重和 210 不等。照抄。改它等于改策略，
   要走单独决策，不能在翻译层顺手处理。

---

## 3. 回测

```bash
python market.py backtest qianlong-auction --start 2025-01-01 --hold 3 --trades
python market.py backtest qianlong-auction --start 2025-01-01 --hold 1 --target 5
```

### A 股规则

少实现一条，收益就会系统性虚高：

- **T+1**：当日买入当日不可卖
- **一字涨停买不进**：跳过该信号，而不是假装成交
- **一字跌停/停牌卖不出**：退出日顺延到真能成交的那天
- **成本**：双边万三佣金 + 千一印花税 + 双边 5bps 滑点 = 往返 **26 bps**
- **数据到头**单独标记 `data_end`，不混进"到期了结"污染统计

### 前视偏差的两面

- **信号计算看未来 = 作弊。** 回测曲线会很漂亮但一分钱赚不到。
- **结果计算看未来 = 天经地义。** 不看之后发生了什么，怎么知道赚没赚。

两者在代码上物理分开：策略只吐信号，回测器只吃信号吐结果，中间不交换
任何信息。作弊因此无处发生——策略拿不到未来数据，回测器不参与选股决策。

### 一次真实结果

跑潜龙出海竞价版，2025-01 至今。样本随行情仓扩大的变化本身就很说明问题：

| 样本 | 笔数 | 胜率 | 净收益均值 | MFE均值 | MAE均值 |
|---|---|---|---|---|---|
| 400 只（深市主板，持有 3 日） | 27 | 37.0% | −1.80% | +3.30% | −4.09% |
| 2025 只（持有 1 日） | 218 | 41.3% | −0.39% | +3.56% | −3.24% |

27 笔时的 −1.80% 不可信；扩到 218 笔跨过统计门槛后是 −0.39%，
相对沪深300 超额 −0.41%。**但那个病没变：MFE +3.56% 而净收益 −0.39%，
浮盈仍然全部回吐。** 持有越久越差说明信号只有当日脉冲；小样本上止盈 +5%
把胜率从 37% 拉到 48%，退出纪律确实有效。

少于 30 笔时 `compute_metrics` 会自动附上警告——不加这句，人就会把
7 笔交易的均值当成结论。

### 横向对比：我到底该用哪个

```bash
python market.py compare --start 2025-01-01 --holds 1,3
```

按**超额**排序而不是绝对收益——大盘涨的时候什么都赚。全市场 5500 只、
2025-01 至今的真实结果：

| 战法 | 笔数 | 胜率 | 净收益 | MFE | MAE | 超额 | 回吐 |
|---|---|---|---|---|---|---|---|
| **分手快乐 /3d** | 495 | 44.4% | **+0.92%** | +8.35% | −5.07% | **+0.73%** | 7.44% |
| **分手快乐 /1d** | 495 | 47.3% | +0.51% | +5.77% | −3.81% | **+0.50%** | 5.27% |
| 潜龙原版 /3d | 24878 | 47.6% | +0.30% | +5.34% | −3.64% | +0.07% | 5.04% |
| 海底捞月 /3d | 104 | 49.0% | +0.34% | +6.29% | −4.42% | −0.06% | 5.95% |
| 三外有三 /1d | 986 | 42.8% | 0.00% | +7.40% | −5.96% | −0.07% | 7.40% |
| 潜龙竞价 /1d | 600 | 40.7% | −0.24% | +3.91% | −3.37% | −0.24% | 4.15% |
| 筹码峰 /1d | 1751 | 40.1% | −0.27% | +5.38% | −4.09% | −0.36% | 5.65% |
| 倒拔杨柳 /3d | 85 | 32.9% | −1.26% | +9.36% | −7.55% | −1.20% | 10.62% |
| 天衣无缝 | 5 | — | — | — | — | — | 样本不足 |

四条结论：

1. **「分手快乐」是唯一稳定正超额的**：1 日与 3 日都为正，495 笔样本够，
   超额 +0.5~0.73%。
2. **潜龙原版 24878 笔但超额只有 +0.07%**——信号这么多说明条件太松，
   选出来的基本就是市场平均。样本大不等于结论强。
3. **八个战法无一例外，MFE 远高于净收益**（回吐 4~10 个百分点）。这不是
   某个战法的毛病，是**退出纪律的系统性缺失**——换战法解决不了。
4. 多数战法持有 3 天比 1 天差，说明信号只有短脉冲。

「回吐」= MFE 均值 − 净收益均值，即持有期内的浮盈最终没拿住多少。
超过 4 个百分点会被自动标记。

### 退出规则扫描：这套战法该怎么卖

横向对比指出所有战法都"浮盈拿不住"，那问题就在退出而不在选股。
固定信号不动，只扫持有期 × 止盈 × 止损：

```bash
python market.py optimize lugw-fenshou --start 2025-01-01     --holds 1,2,3,5 --targets 0,3,5,8 --stops 0,-5,-8
```

**样本内（2025-01 至今，495 笔）**

|  持有 | 止盈 | 止损 | 胜率 | 净收益 | 超额 |
|---|---|---|---|---|---|
| 5d | — | −5% | 37.2% | +1.38% | **+1.06%** |
| 5d | — | −8% | 44.6% | +1.49% | +1.06% |
| 3d | — | — | 45.7% | +0.84% | +0.60%（基线）|

**样本外（2024 全年，247 笔，与上面零重叠）**

|  持有 | 止盈 | 止损 | 胜率 | 净收益 | 超额 |
|---|---|---|---|---|---|
| 5d | — | −8% | 49.8% | +2.64% | **+1.65%** |
| 5d | — | −5% | 41.7% | +2.41% | +1.49% |
| 3d | — | — | 55.5% | +1.26% | +0.57%（基线）|

**两段区间的一致结论**：

1. **持有 5 日最优**——两段都是。
2. **不设止盈**——两段的全部前列都不带止盈。止盈能提高胜率，却砍掉了
   大赢家，总收益反而更差。
3. **要设止损**——−5% 与 −8% 都明显优于不设。
4. 具体止损数值两段不一致（−5% vs −8%），说明那是噪声级差异，
   取更宽的 −8% 更保险。

结论跨区间稳健，不是过拟合。

> 参数扫描天生会生产漂亮数字。命令本身会主动提示过拟合风险并建议换区间
> 重跑——不加这句，它就只是个自我欺骗的工具。

---

## 4. 技能包

一个 zip，解出来至少要有 `SKILL.md`。装上就多一个可定时运行的"模式"。

### 包结构

```
my-skill.zip
├── SKILL.md              必需
└── references/           可选，任意参考资料
    └── rules.md
```

`SKILL.md`：

```markdown
---
name: 潜龙盘后简报
slug: qianlong-brief          # 可选，缺省用 name
version: 1.0.0
description: 每个交易日盘后读取选股结果，输出一份可执行的观察简报
tools: [run_screen, get_quotes_daily]
schedule: "40 15 * * 1-5"     # 可选，建议的 cron
---

# 正文即给模型的指令

1. 今日入选：逐只列出代码与关键因子
2. 需要留意：哪些因子处在阈值边缘
3. 待核验：哪些结论需要人工去查
```

### 安装与管理

```bash
python ops.py skill install ./my-skill.zip
python ops.py skill list
python ops.py skill toggle my-skill off
python ops.py skill remove my-skill
```

也可以从网页上传（`POST /api/skills`，multipart）。

### 安全

解 zip 是整个系统攻击面最大的地方。以下每条都在**解压前**拦截：

| 攻击 | 拦截方式 |
|---|---|
| Zip Slip（`../../etc/cron.d/x`） | 条目名含 `..` 或绝对路径直接整包拒绝 |
| 符号链接指向 `/etc/shadow` | 检查 zip 条目的文件模式位 |
| Zip 炸弹（几十 KB 解出几百 MB） | 按解压后总大小与条目数拦截 |
| 混入可执行文件 | 只放行 `.md/.py/.json/.yaml/...` 白名单后缀 |

安装是原子的：先解到临时目录、校验通过才整体搬到最终位置。失败不留残骸——
否则下次会读到半个包。

**技能包无权覆盖项目铁律。** "不许编数据、不给确定性买卖建议、不碰自动
交易"由系统提示强制前置，并声明"冲突时以本段为准"。一个写着"忽略之前
所有指令"的技能包拆不掉这道护栏。

> 线上必须让 `PALACE_SKILL_ROOT` 指向数据卷。默认位置在代码目录里，
> 而每次发布都会换成新的 release 目录——装好的技能包会随下次同步凭空
> 消失且毫无报错。compose 已配 `/data/skills`。

---

## 5. LLM 供应商

不硬编码任何厂商：**名称 + Base URL + Key + 协议**，新增一家只是加一行配置。

```bash
python ops.py genkey                    # 生成 PALACE_AI_MASTER_KEY

python ops.py provider add --name openrouter \
    --base-url https://openrouter.ai/api/v1 --key sk-xxx
python ops.py provider models openrouter
python ops.py provider list
```

### 服务器实测（容器内直连，无代理）

| 供应商 | 结果 | 是否需要代理 |
|---|---|---|
| **OpenRouter** | 200 / 0.99s | **不需要** |
| **DeepSeek** | 401 / 0.12s（可达） | **不需要** |
| Anthropic | 403（地域封锁） | 需要 |
| OpenAI | 网络不可达 | 需要 |

**OpenRouter 是当前最优解**：一个 key 接 100+ 模型（含 Claude），
OpenAI 兼容协议，`/models` 能自动拉列表，零代理就能在线上用上 Claude。

需要官方 API 时，代理**按供应商单独配**：

```bash
python ops.py provider add --name anthropic --protocol anthropic \
    --base-url https://api.anthropic.com/v1 --key sk-ant-xxx \
    --model claude-opus-4-20250514 --proxy http://172.17.0.1:7890
```

不做全局代理，是为了不让境内的行情接口也跟着绕道出去。

### 密钥安全

- AES-256-GCM 加密，主密钥在环境变量、密文在 `ops.db`，**两者永不同处**
- AAD 绑定 `provider_id`：密文被搬到另一行会直接解不开。没有这层绑定，
  攻击者可以把 A 供应商的密文搬到 B 供应商，系统照样解密成功，然后拿着
  A 的 key 去请求 B 声明的 base_url——等于主动把密钥送出去
- 保存时先发一次最小请求校验，**校验失败绝不落库**
- 任何接口只回末四位，永不回显明文或密文

---

## 6. 定时任务

四类任务走同一套调度与留痕：

```bash
# 盘后同步行情
python ops.py job add 盘后同步 sync --cron "35 15 * * 1-5" \
    --config '{"workers":6}'

# 竞价前选股
python ops.py job add 潜龙选股 screen --cron "26 9 * * 1-5" \
    --config '{"strategy":"qianlong-auction"}'

# 周末回测复盘
python ops.py job add 周度回测 backtest --cron "0 10 * * 6" \
    --config '{"strategy":"qianlong-auction","start":"2025-01-01","hold_days":1}'

# 盘后 AI 简报：技能包 + 供应商 + 真实数据上下文
python ops.py job add 盘后简报 skill --cron "40 15 * * 1-5" \
    --config '{"skill":"qianlong-brief","provider":"openrouter",
               "context":["screen","market_coverage"],
               "context_strategy":"qianlong-auction"}'

python ops.py job list
python ops.py job run 潜龙选股        # 立即执行一次
python ops.py runs --limit 10        # 执行历史
python ops.py serve                  # 前台常驻调度
```

线上由 FastAPI 生命周期接管，`PALACE_ENABLE_SCHEDULER=1` 开启。

### 一套能直接用的日常流水线

```bash
python ops.py job add "01 盘后同步行情" sync --cron "35 15 * * 1-5"     --config '{"workers":6,"interval":0.08}'

# record_candidates 是关键：选股结果自动入候选池，T+N 后复盘引擎才有得验
python ops.py job add "02 盘后选股·分手快乐" screen --cron "45 15 * * 1-5"     --config '{"strategy":"lugw-fenshou","record_candidates":true}'
python ops.py job add "03 盘后选股·潜龙原版" screen --cron "47 15 * * 1-5"     --config '{"strategy":"qianlong-close","record_candidates":true}'
python ops.py job add "04 竞价前选股·潜龙竞价" screen --cron "26 9 * * 1-5"     --config '{"strategy":"qianlong-auction","record_candidates":true}'

# 周末回顾：战法还有没有效、卖法要不要调
python ops.py job add "05 周末战法对比" compare --cron "0 10 * * 6"     --config '{"start":"2025-01-01","holds":[1,3]}'
python ops.py job add "06 周末退出扫描" optimize --cron "30 10 * * 6"     --config '{"strategy":"lugw-fenshou","start":"2025-01-01"}'

# 执行记录每天累积，不清理会把几百 KB 的运维库撑到几百 MB
python ops.py job add "07 每周清理执行历史" prune --cron "0 3 * * 0"     --config '{"keep_per_job":200}'
```

时间安排的理由：15:35 同步（收盘后行情已出），15:45 起选股（同步已完成），
9:26 跑竞价版（集合竞价 9:25 结束，开盘前还有 4 分钟）。

`record_candidates` 是整条回路的接头处：

    选股 → 候选池 → T+N 后自动验证 → 知道这套战法准不准

不开这个开关，复盘页的候选池验证永远没有数据可验。入池记录的 reason 会
带上触发它的具体因子数值——只写"某战法选中"，三个月后回看等于没记。

### 三条设计约束

- **必须单 worker。** APScheduler 是进程内单例。多 worker 下同一条 cron
  会被每个 worker 各触发一次：行情重复抓、简报生成两遍、token 烧双倍。
  已实测服务器容器是单 worker；检测到多 worker 会显式报错。
- **cron 写错当场报错**，不留到"它安静地永不触发"时才发现。一条坏 cron
  不影响其他任务装载。
- **失败落库而不是抛出。** 定时任务最怕的不是失败，是静默地一直失败——
  半年后才发现每天的盘后同步早就挂了。每次执行都留记录，失败保留完整
  错误文本而不只是状态码。

`skill` 类任务的 `context` 字段声明要喂给模型哪些真实数据
（`screen` / `market_coverage` / `positions`）。取不到就如实标注
"未取得真实数据"，不让模型拿着空气编——铁律靠这里落实，不是只在
prompt 里写一句"不许编"。

---

## 7. 两条常驻守卫

这两条测试防的不是今天的代码，是将来任何一次改动。

**信号截断一致性**（`tests/test_strategies.py`）
同一天的信号算两遍：一遍喂全部历史，一遍只喂到当天为止，结果必须完全
一致。任何未来函数（`shift(-1)`、居中窗口、全局归一化）都会让两者分叉。
新加的策略自动纳入，无需额外配置。

**权重方向**（`tests/test_formula.py`）
对单调递增序列，近期加权均值必须高于同窗口简单均值。这条已经抓到过两次
真实的权重倒挂 bug。

---

## 8. HTTP 接口

```
GET  /api/capabilities              哪些能力可用（前端据此隐藏入口）
GET  /api/market/coverage|search
GET  /api/market/quotes/{code}?adjust=qfq
POST /api/market/sync
GET  /api/strategies
POST /api/strategies/screen
POST /api/backtest
GET/POST/DELETE      /api/skills
GET/POST/PATCH/DELETE /api/jobs
POST /api/jobs/{id}/run
GET  /api/jobs/runs | /api/jobs/schedule
GET/POST/DELETE      /api/providers
```

写操作与账本写入走同一道门（浏览器会话或 Agent Bearer 令牌），不开旁路。

所有重依赖在路由函数内**懒导入**：即便线上只装了最小依赖，账本 API 也
照常可用，对应接口返回 503 并说清缺什么。

---

## 9. 已知限制

- **样本与结论**：目前只同步了 400 只深市主板。任何回测结论在全市场
  多年数据上重跑之前都只是参考。
- **`COST()` 筹码分布未实现**：卢高文六个涨停战法依赖它（换手率衰减的
  筹码分布分位数）。现有 `calc_chip_distribution` 只是等宽分箱直方图，
  语义相差很远，不能直接拿来复刻。
- **「一箭穿心」源材料不在仓库里**：对 `tdx/`、`lugw_tdx_formulas.*`、
  `潜龙出海.txt` 及那份 `.doc` 做过全文与字节级扫描，均无命中。需要你
  提供公式文本才能复刻。
- **akshare 上游不稳**：底层是爬公开网页接口，随时可能改版或限流封 IP。
  已做多源降级（新浪主 / 东财备）与限速，但不能假设长期稳定。
- **`ak.stock_info_a_code_name()` 不可用**：它依赖 py_mini_racer 执行 JS，
  在多线程同步下会触发**原生崩溃**——整个进程直接挂掉，连 traceback 都
  没有。已改用交易所各自的列表接口。

---

## 10. 外部情报（MCP）

### 分工

| | 本地行情仓 | 外部 MCP |
|---|---|---|
| 数据 | 全市场日线、复权因子、交易日历 | 涨停梯队、炸板池、封板事件流、概念热度、龙虎榜、研报、公告 |
| 为什么 | 量价计算要高频大批量 | 这些要盘中逐笔或全网抓取，本地没有数据源 |
| 规模 | 5509 只一次算完，891 ms | 有配额（典型 5000 次/天、50 次/分） |
| 时机 | 离线、随时 | 在线、低频、小批量 |

**不要拿 MCP 做全市场扫描**——一次选股 5509 只，当天配额立刻见底。

### 接入

```bash
python ops.py mcp add --name wudao \
    --url https://stock.quicktiny.cn/api/mcp --token lb_xxx
python ops.py mcp list
python ops.py mcp tools wudao          # 刷新并列出（wudao 实测 63 个）
python ops.py mcp call wudao kline --args '{"codes":["600519"],"days":5}'
```

注册时会**当场握手并拉工具列表**，连不上就不落库——配置错误应该在保存时
暴露，而不是等某个半夜的定时任务失败。

token 与 LLM Key 同一套加密：主密钥在环境变量、密文在 `ops.db`，
AAD 绑定 server id。密文被搬到另一行会直接解不开——没有这层绑定，
攻击者可以把 A 的 token 挪到 B 声明的 URL 上，等于主动把凭据送出去。

### 为什么是 MCP 而不是包 REST

wudao 同时提供 REST，直接调也能用。但它有 63 个工具，手工包一遍要写
63 份 schema，上游一改就全过时。MCP 的 `tools/list` **自动发现**——
接一个新 server 只是加一行配置，工具自动出现在 Agent 的可用列表里。
约 150 行代码换零维护成本。

### 为什么不用 LangChain / LangGraph

它们要解决的问题（供应商抽象、密钥管理、工具循环、状态编排）本项目已经
自己实现了，而且更贴合业务约束——两段式写入、配额刹车、铁律强制前置。
服务器只剩约 1.1 G 可用内存，那条依赖链背不起。

### 让技能用上这些工具

```bash
python ops.py job add 盘后简报 skill --cron "40 15 * * 1-5" \
    --config '{"skill":"my-skill","provider":"openrouter",
               "mcp_servers":["wudao"],
               "tools":["limit_up_ladder","theme_intraday_capital"]}'
```

`tools` 留空则用技能包 `SKILL.md` 里 `tools:` 声明的那几个。**务必收窄**：
一个 server 63 个工具的 schema 全塞进 system prompt 会占掉大量上下文，
而多数技能只用三五个。

### 三道刹车

无人值守下，陷入循环的 Agent 会安静地烧光配额与 token：

- **轮数上限**（默认 8）：撞上就停，并在输出里**如实说明分析可能不完整**
- **单轮工具数上限**（默认 8）：模型偶尔一口气请求二十个
- **失败不中断**：工具报错原文如实回传给模型让它换路子。**不能返回空结果**——
  那会让模型以为"查到了但没数据"，进而编造结论

只接**只读工具**。写账本必须走"AI 提议 → 人工确认"的两段式，不该发生在
无人值守的定时任务里。定时技能能查任意数据、能给结论，但改不了任何一条
账本记录。
