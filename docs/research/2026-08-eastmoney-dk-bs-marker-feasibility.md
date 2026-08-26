# 东财 DK 点与「K 线上标 B/S」：算法可复现性与本仓落地可行性（2026-08-12）

> **类型**：Explanation（外部产品逆向尽调 + 学术证据核验 + 本仓落点评估）
> **调研日**：2026-08-12
> **需求原话**：用户给出东方财富手机 App 日 K 截图（002636 金安国纪），图表工具栏有 `DK点` 按钮，开启后 K 线上直接叠加 `B`（买）/`S`（卖）标记，带虚线引线落到对应 K 线；均线栏是 `MA5/10/20/60/120`。问「**这种形式能做到吗？你看看他怎么做的**」。
> **范围**：只读。核验东方财富官方页面、DeMark 原始定义链、学术原文、本仓 `frontend/src/shared/components/charts` / `frontend/src/shared/lib` / `frontend/src/features/{market,ledger,ai}` / `src/{formula,research,strategy,market}`。**未改任何代码**，未跑回测，未写爬虫，未使用任何凭据。
> **证据分级**：`V` 本轮实际发请求并记录了真实返回；`E1` 源码/PDF 全文已读；`E2` 摘要/元数据/检索片段；`E3` 官方或平台文档正文；`E4` 经验主张（不可当收益承诺）。

---

## 0. 诚实边界（先读这一节）

### 0.1 本机链路 vs 本轮取证通道

本工作站的 DNS 被本地隧道客户端劫持成 Fake-IP（`198.18.0.0/15`），到 `eastmoney.com` / `10jqka.com.cn` 的 TLS 会失败。这一点 `src/intel/README.md` 第 36 行已写死对策：「主机名经 Clash/Surge Fake-IP 解析到 `198.18.0.0/15` 时……`needs_system_proxy` 打开 `trust_env` 走系统代理出站——否则直连 198.18 必挂」。

**本轮所有东财页面是从异地只读通道抓的，不是从本机直连**，且每个 URL 只发一次。因此本文里任何「东财某页返回了什么」都不能反推「本机能连东财」；反过来，本文也**没有**出现「东财接口挂了」这类结论——没测过就不写。

### 0.2 我验证到什么 / 没验证到什么

| 事项 | 状态 |
|---|---|
| 东财官方 DK 营销页 `zqhd.eastmoney.com/.../share1.html` | **已验证**，正文全文见 [A2] `V` `E3` |
| 东财官方 DK 产品页 `acttg.eastmoney.com/pub/ttjjapp_hskh_hqy_ggdt_...` | **已验证**，正文极短，见 [A2] `V` `E3` |
| 东财开户活动页（DK 权限领取流程）`zqhd.eastmoney.com/.../activity1.html` | **已验证**，正文全文 `V` `E3` |
| 东财**官方帮助中心**《神奇九转指标介绍》`qhweb.eastmoney.com/help/2437550.html` | **已验证**，算法全文 `V` `E3` |
| 东财财富号《DK股票池功能说明》 | **已验证** `V`。注意：财富号是东财站内自媒体位，作者署名「功能驿站」，页尾自带「仅代表作者个人观点，与本网站立场无关」免责声明——**只能算准官方，不能当官方规格书** |
| **东财官方帮助中心里的 DK 点算法页** | **未找到**。检索 `qhweb.eastmoney.com/help` 域下无 DK 条目；九转有、DK 没有。这是本文最重要的一条否定结论 |
| DK 点在手机端渲染成 `B`/`S` 字母 | **未能从官方来源验证**。官方与准官方文案一律写「D点（红点）/ K点（蓝点）」。用户截图里的 `B`/`S` 字母大概率是较新 App 版本对同一 DK 信号的换皮渲染，但**我没有证据**，不做断言。可确认的是入口一致：日 K 页 →「DK点」按钮（[A2] 活动页原文写明该入口） |
| DeMark 原始著作 *The New Science of Technical Analysis*（1994）第 7 章正文 | **未读到全文**（版权书籍）。本文给出的 Setup/Countdown 精确规则来自两处可读一手：DeMARK Analytics 官网条目 `E2`，以及一篇同行评审论文的形式化复述（读了 PDF 全文，`E1`），见 [A4] |
| `demark.com/sequential-indicator/` 全文 | **未能验证**：两次 WebFetch 超时。只有检索摘要级引文 `E2` |
| SSRN `abstract_id=2696155` 页面 | **未能验证**：WebFetch 超时。但同一论文的**作者版全文 PDF** 已读，见 [B1] `E1` |
| 通达信/同花顺版 DK 公式源码 | **未找到可信源码**。检索只命中股票论坛帖里一段「大致形式如下」的伪代码（`CROSS(短期线,长期线) AND MACD金叉`），发帖人自己写明「具体的函数和逻辑可能因软件版本和设置不同而有所差异」——**这是猜测，不是逆向，更不是源码**。本文不引用它作为 DK 算法 |
| 本仓前端 K 线链路全部文件 | **已逐行读** `E1` |

**没有验证到的一律不写字段名、不写参数、不写公式。**

---

## 结论摘要

| 问题 | 结论 |
|---|---|
| 东财 DK 点算法公开吗？ | **不公开**。官方只给到「以波段理论和右侧交易理论为基础」「综合多因子」「通过人工智能演算」「跟踪股票资金流向、涨幅表现及基本股性」这一层黑箱表述，**没有任何一处给出公式、参数或输入清单**。对照组很刺眼：同一家公司的**九转指标在官方帮助中心把算法写全了**，DK 没有 |
| 能复现吗？ | **不能。** 且不只是「算法没公开」——DK 的输入里含**资金流**（官方原话），而资金流是东财自家的 Level-2 派生数据，本仓根本拿不到同源输入。就算猜对了公式也复现不出同一条信号。只能做**行为对齐的近似**，且不得对用户宣称「这是 DK」 |
| 最接近的可复现公开替代 | **TD Sequential 的 Setup 阶段（国内俗称九转序列）**。原始定义出处：Thomas R. DeMark, *The New Science of Technical Analysis*, John Wiley & Sons, 1994, **Chapter 7 "Sequential"**；可直接读的一手复述见 [A4]。**东财自己就公开了这套算法**（官方帮助中心 `qhweb.eastmoney.com/help/2437550.html`），照它实现 = 与东财同款九转逐根对齐，不需要逆向 |
| 一手学术支持 | **有，但结论对「买卖点」是负面的。** Lissandrin/Daly/Sornette（SFI 15-56，后刊于 *Journal of Investment Strategies*）是目前唯一一份 DeMark 指标的同行评审实证：21 个商品期货 × 10 年，Sequential 在除铂金外的所有品种上「统计显著」——但作者紧接着自己写「**this indicator does not seem to be able to forecast the correct market direction**」。即：它能预测「要动」，不能预测「往哪动」。**没有找到任何 A 股上的 DeMark 一手检验** |
| 「K 线上标 B/S」本仓能做到什么程度 | **产品形态 100% 能做，而且比想象中近。** `KlineChart.vue` 已经注册了 `MarkPointComponent`，`buildKlineOption` 已经在往 `markPoint.data` 里塞涨跌停钉，`klineLimitMarks.ts` 就是现成的模板；`ArchiveView.vue` 手上已经握着「某只票的多日买卖事件」（`TimelineEvent`）。**画标记这件事零架构缺口** |
| 缺什么 | 缺的是**数据方向**，不是画布：本仓的策略信号是「一天 × N 只票」（`ScreenResult.picks`，`Pick` 里连 `trade_date` 都没有），而 K 线要的是「一只票 × N 天」。账本口径（我自己买卖过什么）已经有；**战法口径（某战法历史上在这只票发过什么信号）没有按 code 的只读端点** |
| 最小改动 | **5 个源文件 + 2 个 README**，不需要新 `use()` 注册（除非要虚线引线）。清单见 [C5] |
| MA60 / MA120 | **前端默认就已经画了**（`DEFAULT_MA_PERIODS = [5,10,20,30,60,120,250]`），比东财那张图还多两条。数据深度也够：前端拉 320 根、热库留 700 交易日。见 [D] |
| 报告路径 | `docs/research/2026-08-eastmoney-dk-bs-marker-feasibility.md`（本文） |

**一句话**：画法白送，算法买不到，别把「像 DK」说成「是 DK」。

---

## A. 东财 DK 点到底是什么

### A1. 先把三个同名东西拆开

东财体系里叫「DK」的至少有三个物件，混谈会得出互相矛盾的结论：

| 名字 | 载体 | 官方对它的描述 | 是否公开算法 |
|---|---|---|---|
| **DK 操盘密码 / DK 点** | 东方财富手机版（日 K 页「DK点」按钮）、电脑增值版「操盘密码」 | 「以波段理论和右侧交易理论为基础，通过 D/K 点买卖预警系统」 | **否** |
| **DK 波段信号 / DK 股票池** | 东方财富证券 App 内的全市场监控池 | 「东方财富证券利用大数据算法打造的**特色行情数据**」「跟踪股票资金流向、涨幅表现及基本股性」 | **否** |
| **趋势 DK 线** | 东方财富金融终端（Choice）「数据分析系统 → 趋势DK线」 | 「红色趋势DK线表示主力资金进入流入阶段，蓝色表示流出」；分波段/短线两种模式，「可自己更改参数设定，修改黄线与紫线的参数周期」 | **否**（连黄/紫线是什么都没说） |

三者共享同一套语义：**D = 多头/机会，K = 空头/风险**，红=D、蓝=K。用户截图里的 `DK点` 按钮属于第一类。

> 注：东财官网首页产品栏（`www.eastmoney.com`）把「操盘密码」列为**电脑增值版**的一档，与 Level-2 极速版、决策版、策略版、领航版并列。`V` `E3` 这坐实了它是**商业增值功能**而非免费指标。

### A2. 官方原文（本轮抓到的四页）

#### （1）`https://zqhd.eastmoney.com/Html/aghd/native/5.5/20181126/html/share1.html` —— 官方 DK 营销页，全文已读 `V` `E3`

这是本轮**信息量最大的官方页**。关键原文逐条摘录：

> 「DK操盘密码能够取得成功的诀窍:
> 1、顺势而为，在市场发生重要趋势运动时，坚持站在正确的一边。
> 2、**综合多因子的信号**建立仓位，用简明直接的信号果断了结仓位。
> 3、严格控制风险，及时纠正错误的交易，确保操作损失止于小额。」

> 「【DK操盘密码】操作指南 —— **D点提示机会，K点提示风险；做透波段，抓涨避跌**
> 操作指南一：短线操作 —— DK操盘密码提示 **15分钟线** 出现D点信号，预示个股上涨概率高；出现K点预示个股回调概率高，可作为日内高抛低吸点的参考。
> 操作指南二：中长线操作 —— DK操盘密码提示 **日线** 出现D点信号，预示个股短线拉升的可能性较高，可重点关注。」

> 「风险提示：以上操盘记录是在理想环境下依据历史数据**通过人工智能演算**所得结果。该结果未考虑冲击成本等复杂市场因素，不代表DK操盘密码对未来投资收益的承诺。」

页面还挂了 2018-06-14 截止的「个股操盘战绩」：罗牛山 +174.34%、片仔癀 +88.25%、贵州茅台 +68.70%（近 1 年收益）。**这是营销回测数字，不是样本外业绩**，页面自己也写了「依据历史数据……演算所得」。

**从这一页能确定的**：多因子、AI 演算、日线与 15 分钟线两个周期、右侧交易（即滞后确认，不是预测拐点）。
**从这一页确定不了的**：因子是什么、权重怎么定、阈值多少、训练目标是什么。

#### （2）`https://acttg.eastmoney.com/pub/ttjjapp_hskh_hqy_ggdt_01_01_01_0` —— 官方产品页 `V` `E3`

正文极短，全文有效句只有两句：

> 「操盘线以『**波段理论**』和『**右侧交易理论**』为基础，通过 D/K 点买卖预警系统，不仅帮您把握上涨波段，更能通过止损预警，防范下跌风险。」
> 「免责说明：以上案例均依据历史回测数据，过往业绩不代表未来表现。」

「右侧交易理论」这五个字是本轮**唯一一条有算法含义的官方线索**：右侧 = 等趋势确认后再进，天然滞后、天然不预测拐点。这与九转（左侧/逆势抄底逃顶）在哲学上是**相反**的。

#### （3）`http://zqhd.eastmoney.com/Html/aghd/pc/20180309/html/activity1.html` —— 开户活动页 `V` `E3`

> 「1.通过本活动页面按流程开通股票账户（含沪深两市），您即可获得短线雷达，手机Level-2极速行情，**DK操盘密码使用权限各1年**。」
> 「方式二：登录最新东方财富手机版（7.0及以上版本）→进入任一股票行情页→选择『**日线**』→点击『**DK点**』图标→活动页面按流程验证手机号即可查看DK操盘密码。」

**这一页坐实了两件事**：① DK 是**权限型付费/开户权益功能**，与 Level-2 并列在同一份权益包里；② 用户截图里那个 `DK点` 按钮就是官方文档描述的入口（日 K 页 → DK点图标），位置完全对得上。

另有超级 Level-2 活动页把 DK 操盘密码列进「6 大炒股特色功能」：「DK操盘密码、短线雷达、VIP财富内参、核心内参、东方财富专业版、Choice金融终端」。`V` `E3`

#### （4）财富号《DK股票池功能说明》（准官方，作者「功能驿站」）`V`

> 「DK波段信号是**东方财富证券利用大数据算法打造的特色行情数据**。」
> 「根据大数据算法，**跟踪股票资金流向、涨幅表现及基本股性**，分析个股的机会、风险信号。D提示机会，K提示风险。」
> 「趋势天数：触发DK信号至下一次触发信号的天数」「趋势涨幅：信号触发后的趋势天数内的区间涨幅」

**「跟踪股票资金流向」这六个字是本文对「能否复现」的判决依据**——见 [A5]。

### A3. 直接回答问题 A1 的三小问

| 问 | 答 |
|---|---|
| 全称是什么 | 产品名 **「DK 操盘密码」**，图上的按钮叫 **「DK点」**，池子叫 **「DK 股票池」**，信号本体官方叫 **「DK 波段信号」**。D/K 两个字母官方从未展开成中文全称；坊间「多空点」的说法**在本轮四页官方文本中一次也没出现**，属民间附会，不采信 |
| 有没有公布算法或参数 | **没有。** 官方给到的最细颗粒度是「波段理论 + 右侧交易理论」「综合多因子」「跟踪资金流向、涨幅表现及基本股性」「人工智能演算」。**零公式、零参数、零输入清单。** 对照：同公司的九转指标在官方帮助中心把「收盘价 vs 4 日前收盘价 / 连续 9 日 / 第 6 日起显示」全写了，说明东财**有能力也有意愿**公开非商业指标的算法——DK 不公开是商业选择，不是疏忽 |
| 指标信号还是 AI 预测？付费吗？ | 官方措辞是 **「大数据算法」+「人工智能演算」**，且明确定性为「**特色行情数据**」——即东财把它当**数据产品**卖，不是当公式送。**付费/权益型**：与手机 Level-2 打包在开户权益里赠 1 年，电脑端归入「增值版·操盘密码」。它既不是纯规则指标，也不是可验证的模型——**是一个没有 model card 的黑箱订阅服务** |

### A4. 与 TD Sequential（神奇九转）的关系辨析

**结论先给：不同源、不同哲学、不同东西。东财 App 里两个功能并存这件事本身就是证据。**

#### 九转在东财是免费公开的，算法写在官方帮助中心

`https://qhweb.eastmoney.com/help/2437550.html`《神奇九转指标介绍》全文已读 `V` `E3`。原文：

> 「1. 计算方法
> • 价格在上涨或（下跌）过程中连续9日达到触发条件，即**当日收盘价大于（小于）4个交易日前的收盘价**，会生成数列1、2、3、4、5、6、7、8、9，数列会依次标注在当日K线上方（下方）。
> • 只有当价格**连续第六天**达到触发条件时，数列才开始进行显示，依次显示1、2、3、4、5、6，当第七天依然达到触发条件时则显示7，如第七日未达到触发条件则前面6天的序号消失。
> • 第八日同第七日的显示逻辑一样。当第九天依然达到触发条件时，便形成了一个九转结构。
> • 而当第九日未达到触发条件时则前面8日的序号消失，九转结构不成立。
> • 价格上涨过程中形成的九转结构称之为上涨9结构，数字在k线上方，其中数字9在客户端中标注为**绿色**；而价格下跌过程中形成的九转结构则称之为下跌9结构，数字在k线下方，其中数据9在客户端中标注为**红色**。」

> 「几点注意事项：
> • 神奇九转指标**只有在出现第九天时才确认有效**，否则前面的序列号不成立。
> • 神奇九转指标**只适用于震荡市、弱牛市和弱熊市，不适用于大牛市和大熊市**，因为在强势行情中，标的价格可能连续出现多个九转结构而不反转。
> • ……不能单独作为买卖依据。」

设置入口是 App 右上角【设置】→【K线设置】→【神奇九转】开关（`E2`，多份教程一致），**与「DK点」是两个独立开关**。

> 富途 moomoo 帮助中心对同一指标的说明补上了血统：「神奇九转指标思想来源于技术分析领域著名大师**汤姆·迪马克的TD序列**」，其余计算条文与东财帮助中心**逐字一致**（含「第六天才开始显示」这个非 DeMark 原生的显示细节）。`E3` 这说明国内各家的「神奇九转」是同一份工程化转写，而不是各自实现。

#### DeMark 原始定义

一手出处：**Thomas R. DeMark, _The New Science of Technical Analysis_, New York: John Wiley & Sons, 1994, Chapter 7 "Sequential"**。这个引文格式被多个独立的专业软件文档同时给出（Aspen Graphics 官方指标文档 `E3`；TradingCenter 教学页 `E2`），可交叉确认。DeMark 本人的另一部 *DeMark Indicators*（Jason Perl, Bloomberg Press, 2008）是通行的二手权威。**这两本书我没有全文，不逐字引述书中原话。**

可直接读到的最接近一手的形式化定义有两处：

**（a）DeMARK Analytics 官方页 `demark.com/sequential-indicator/`（本轮 WebFetch 超时，仅检索摘要 `E2`）**：

> 「A **Buy Setup** occurs when there are **9 consecutive closes less than the close four bars earlier**. A **Sell Setup** occurs when there are 9 consecutive closes greater than the close four bars earlier.」
> 「The **Countdown** phase occurs once Setup is complete... Countdown is calculated by **comparing the close of the current bar to the high or low two bars earlier**. Each fulfilled comparison produces a number... Once the series reaches a **13** the market is prone to a reversal, with the **Risk Level** defining the zone within which the trend should reverse, and the **12-bar rule** defining the time within which it should do so.」
> 「the **13 bar must be** greater than or equal / less than or equal **the 8 bar in the Countdown**」

**（b）同行评审论文里的完整形式化（PDF 全文已读，`E1`）**：Lissandrin, Daly & Sornette, §2「Definition of DeMark Indicators to be tested」把 Setup / Countdown / Combo 写成了带编号方程的伪代码。这是本轮拿到的**最精确的可读一手复述**，逐条抄录：

- **Setup**（式 1）：`∀ (new) t, Pc(t) < Pc(t − n)`，`n = 4`。计数器 `s` 连续满足才 +1，一旦中断归零；`m = 9` 时 Setup 完成。原文：「a negative price velocity is measured over four time periods (n = 4) and it has to be maintained for **nine consecutive periods (m = 9)**」。
- **Setup 的副产品**（式 2–4）：Setup 区间 `[min(Pl), max(Ph)]`、宽度 `Rw`，以及支撑/阻力位 `res(t) = max(Ph)`、`sup(t) = min(Pl)`——这就是 TDST 线。
- **Countdown**（式 5）：Setup 完成后启动，`u = 2`；标准版 `Pc(t) ≤ Pl(t − u)`，激进版 `Pl(t) ≤ Pl(t − u)`。**「Unlike the Setup, what matters for the Countdown to be completed is the total number p of bars fulfilling eq. 5, not the consecutive number」**——即 Countdown 允许不连续。
- **第 13 根的额外条件**（式 6）：`Pl(p) ≤ Pc(k)`，`p = 13`、`k = 8`。不满足则**顺延**而非取消。
- **Recycle / 取消规则**（三条，原文）：① 反向 Setup 完成 → 当前 Countdown 立即结束并被反向 Countdown 取代；② 穿越支撑/阻力（买入侧 `Pl(t) > res(t)`）→ Countdown 停止并作废；③ 同向新 Setup → 仅当 `Rw_new > Rw_old` 才重置计数。
- **Combo**（式 7）：把 Countdown 换成四个同时成立的条件，且「the bar check in eq. 7 starts from the **first** bar of the Setup instead of the last」。
- **入场**（式 8）：保守版要求 `Pc(t) > Pc(t − n)` 才在 `t+1` 收盘价进场。

#### 三点辨析

1. **哲学相反。** 九转/TD Sequential 是 DeMark 亲口定位的 **counter-trend / 逆势** 工具（论文原文：「Sequential... tries to identify areas of trend exhaustion that will lead to price reversals」）；东财 DK 官方写的是 **「右侧交易理论」**，即顺势确认后再进。一个抄底逃顶，一个追认趋势。
2. **输入相反。** 九转**只吃 OHLC**（纯价格结构，论文原文：「For each trading day, DeMark indicators need bar charts (starting, highest, lowest and closing prices)」）；DK 官方自述吃 **资金流向 + 涨幅表现 + 基本股性**，价格只是其中一项。
3. **共存即证伪同源。** 东财 App 里「神奇九转」（免费、K线设置里开、算法公开）与「DK点」（权益、日K页按钮、算法不公开）是**两个并列开关**。如果 DK 就是九转，东财没有理由把同一个东西卖一遍。

**判定：DK 点与 TD Sequential 无同源关系。任何声称「DK 就是九转」的说法都与东财自己的产品结构矛盾。**

### A5. 能不能复现？—— 不能，而且不是「难」是「不可能」

分两层说清楚，别让人误以为再逆向一阵就能搞定：

**第一层：算法没公开。** 官方给到的是「多因子 + AI 演算」，等价于什么都没说。社区侧本轮**也没有找到任何可信的逆向实现**——检索命中的唯一「源码」是股票论坛帖里一段自称「大致形式如下」的伪代码（`CROSS(短期线,长期线) AND MACD金叉`），发帖人自己写明「具体的函数和逻辑可能因软件版本和设置不同而有所差异，具体使用时应参考软件的帮助文档或咨询软件客服」。这是**猜的**，不是逆向的，本文拒绝把它当线索。

**第二层（更硬）：输入拿不到。** 官方原文说 DK 跟踪「股票**资金流向**」。资金流是东财基于自家 Level-2 逐笔委托推的派生量，本仓 `market.db` 只有 OHLCV + 复权因子。**即使把公式白送给我们，也喂不进同一份输入，算不出同一条信号。** 这一条一票否决「复现」，与算法保不保密无关。

**结论：DK 点不可复现，只能做「行为对齐的近似」——而且必须在 UI 上写清楚这是本仓自己的信号，不得暗示与东财 DK 同源。**

### A6. 最接近的可复现公开替代（按推荐度排序）

| 替代 | 原始定义出处 | 输入 | 与 DK 的差距 | 本仓可实现性 |
|---|---|---|---|---|
| **TD Sequential Setup（九转）** | DeMark 1994, *The New Science of Technical Analysis*, Ch.7；**东财官方帮助中心已把中文实现口径写全**（`qhweb.eastmoney.com/help/2437550.html`） | 仅 close | 逆势 vs 右侧，方向哲学相反；但**这是唯一一个能与东财自家产品逐根对齐**的选项 | **最高**。`src/formula/domain/functions.py` 已有 `REF` / `BARSLAST` / `MA` 等通达信同名函数，Setup 是十几行的事 |
| **TD Countdown（13）** | 同上，式 5–8 见 [A4](b) | OHLC | 同上，且信号更稀疏 | 高，但 recycle 三条规则容易实现错，必须逐条对照 [A4] |
| **Williams Fractals（分形顶底）** | **Bill Williams, _Trading Chaos_, John Wiley & Sons, 1995**（1998 *New Trading Dimensions* 扩写）。定义：候选 K 的 high 严格高于前 2 根与后 2 根的 high → 上分形；low 严格低于前后各 2 根的 low → 下分形；**确认滞后 2 根** | high / low | 纯几何，无趋势含义；只标结构点不标买卖 | 高，五行代码 |
| **ZigZag** | **无单一权威原始出处**——这是行业通用画法而非某人的具名指标，各平台阈值口径（百分比 / ATR / 分形）不一。可读的口径对照见 LuxAlgo 概念库：「Zigzag filters swings by **magnitude**, requiring a minimum percent or ATR move between pivots, while fractals filter only by local bar geometry」`E2` | OHLC | **有重绘（repaint）**：最后一段会随新数据改写。用它标历史 B/S 会产生前视幻觉 | 中。**若做必须在 UI 明示「末段可能重绘」**，否则违反本仓「禁止前视」红线 |
| **SuperTrend** | 归于 Olivier Seban，**本轮未找到作者原始出版物**，只有各平台文档级描述。**按本仓一手来源优先原则，标为出处不明** `E2` | ATR + OHLC | 顺势（与 DK 的右侧哲学**最接近**） | 中。ATR 本仓 `src/formula` 未确认是否已有，需先核 |
| **本仓自己的战法信号** | `src/strategy` 各战法，`entry_timing` 已有前视审计 | 本仓自有 | **不冒充任何外部产品**，口径自洽、可回测、可解释 | **最高，且是唯一一个能对结论负责的选项** |

> **推荐路线**：如果只要「图上有 B/S」这个产品形态，直接用**本仓已有的账本事件 + 战法信号**（见 [C]），根本不需要复刻任何外部指标。如果还想额外加一条与东财同款的对照线，就实现**九转 Setup**——因为它的中文口径是东财自己公开的，不存在「我们猜的对不对」这个问题。

---

## B. TD Sequential / 反转型信号的学术检验

### B1. DeMark 指标：有一手检验，一份

**Lissandrin, M., Daly, D., & Sornette, D. (2015/2017), "Statistical Testing of DeMark Technical Indicators on Commodity Futures"**
Swiss Finance Institute Research Paper No. 15-56；SSRN [abstract_id=2696155](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2696155)；后刊于 *Journal of Investment Strategies*（[risk.net 条目](https://www.risk.net/journal-of-investment-strategies/5293521/statistical-testing-of-demark-technical-indicators-on-commodity-futures)）；RePEc [chf/rpseri/rp1556](https://ideas.repec.org/p/chf/rpseri/rp1556.html)。
**作者版全文 PDF 已读**（The Technical Analyst 托管的 Unblinded Manuscript）`E1`。

**这是本轮找到的唯一一份 DeMark 指标的同行评审实证。** 设计与结论：

| 项 | 事实（原文 / 全文所载） |
|---|---|
| 标的 | **21 个商品期货**（谷物 / 软商品 / 能源 / 工业金属 / 贵金属）。**不含股票，不含 A 股** |
| 样本 | 2004-01 至 2014-01，日频 |
| 被测指标 | Sequential、Combo、Setup Trend（ST） |
| 方法 | 条件收益分布 vs 无条件（市场）分布；再用 **Monte-Carlo permutation test**（随机化同样次数的入场与持有天数）做基准 |
| 信号频率 | **极稀疏**：Sequential 3.9 次/年、Combo 1.7 次/年、ST 4.5 次/年。原文：「we can conclude that the entry signals are sparse」 |
| 正面结论 | 「For all the commodity futures apart from **Platinum**, DeMark's Sequential indicator has shown **statistically significant predictive power** for either long or short entry positions」 |
| **致命限定** | 「**Unfortunately, just like its Combo version, this indicator does not seem to be able to forecast the correct market direction.** This limits our trading strategies, but forthcoming price move in an unknown direction can still be profitable, for example by using a **long straddle** option strategy.」 |
| 另一处限定 | 「Although Sequential is described as a time-based indicator that identifies turning points, there are products or even commodity classes, like energy products, where entry signals identify **continuing trends instead of turning points**.」——**同一个信号在不同品种上语义相反** |
| 时效结构 | 举例小麦：「Across all metrics, there is nice predictive power, but this **only appears 11-12 days after** the position has been entered.」 |
| 稳健性警告 | 换合约展期方式（roll on expiry day）后「in two out of three examples, there is even **no statistical significance left**」 |
| **作者自认的方法缺口** | 「A natural extension of this work should investigate the **data snooping bias**... In our case, results do not seem to be driven by luck due to a relatively low number of combinations (3 trading rules over 21 data-sets).」——**他们没有做 Reality Check / SPA 校正**，只是论证「组合数少所以大概不用做」 |
| 交易成本 | 全文未做净额检验；论文自述这些是「entry signals... **they are not trading systems**」 |

**怎么读这份证据**：它支持「Sequential 之后价格会显著动」，**不支持**「Sequential 是买卖点」。而 DK 点 / B/S 标记恰恰是在断言方向。把这篇拿来给「图上标 B 就买」背书，是偷换命题。

**除此之外，没有找到**：DeMark 指标在**股票**上的同行评审检验、在**A 股**上的任何一手检验。检索到的中文「九转回测」全部是自媒体/券商投教内容，无方法披露、无样本外、无成本假设——按硬要求，**如实写「A 股上无一手学术检验」，不用博客充数**。

### B2. 更一般的反转型技术信号：data-snooping 校正后的存活率

#### 框架原文：Sullivan, Timmermann & White (1999)

**"Data-Snooping, Technical Trading Rule Performance, and the Bootstrap"**, *The Journal of Finance* **54(5): 1647–1691**，DOI [10.1111/0022-1082.00163](https://doi.org/10.1111/0022-1082.00163)。**全文 PDF 已读** `E1`（[Kevin Sheppard 教学镜像](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf)；工作论文版 [LSE eprints dp303](http://eprints.lse.ac.uk/119144/1/dp303.pdf)）。

设计：把 Brock/Lakonishok/LeBaron (1992) 的 26 条规则扩成 **7,846 条**全宇宙，套 100 年 DJIA 日频，用 White's Reality Check bootstrap（B = 500）做多重检验校正。

结论原文（§V，第 767–780 行）：

> 「We find that the results of BLL appear to be **robust to data-snooping**, and indeed there are trading rules that perform even better... **However, we also find that the superior performance of the best technical trading rule is not repeated in the out-of-sample experiment covering the 10-year period 1987–1996. In this sample the results are completely reversed and the best-performing trading rule is not even statistically significant at standard critical levels.** This result is also borne out when data on a more readily tradable futures contract on the S&P 500 index are considered: **Again there is no evidence that any trading rule outperforms** over the sample period.」

作者还预先堵掉了「样本外期不具代表性」的辩解：「the out-of-sample trading period is rather long (**3,291 days**)... the out-of-sample results are **robust to whether or not data on 1987 are included**」。

**这就是反转/趋势类技术规则的天花板参照：在最有利的样本内、经过严格校正后确实活得下来；换到之后的 10 年，全灭。**

#### A 股上的复现（两个方向都有，必须都列）

| 论文 | 出处 | 方法 | 结论 |
|---|---|---|---|
| Jiang, F. et al. (2019), "Technical Analysis Profitability Without Data Snooping Bias: Evidence from Chinese Stock Market" | *International Review of Finance*，DOI [10.1111/irfi.12161](https://doi.org/10.1111/irfi.12161) `E2` | **stepwise SPA**（Hsu-Hsu-Kuan 2010），**>28,000** 条信号，19 年 A 股日频总量收益 | **正面**：「we find **substantial evidence** on the profitability of technical trading rules... **remain valid under the presence of transaction costs**」 |
| Wang, S. et al. (2015), "Testing the performance of technical trading rules in the Chinese markets based on superior predictive test" | *Physica A*，DOI [10.1016/j.physa.2015.07.029](https://doi.org/10.1016/j.physa.2015.07.029) `E2` | **SPA test**，7,000+ 条规则，SSCI 1992–2013 与 HS300 2005–2013 | **半负面**：「for SSCI, technical trading rules offer significant profitability, **while for SHSZ 300, this ability is lost**」；且「the financial bubble from 2005 to 2007 **greatly improve** the effectiveness」——有效性来自泡沫期 |
| (2024), "Profitability of technical trading rules in the Chinese stock market" | *Pacific-Basin Finance Journal* 84，[RePEc 条目](https://ideas.repec.org/a/eee/pacfin/v84y2024ics0927538x24000295.html) `E2` | **stepwise generalized error rate control**（FWER / FDP），**38,456** 条规则，SSEC 与创业板指，2010–2021 | **最负面，也最新**：「only a few complex rules outperform SSEC in different testing sub-periods, and **no trading rules outperform GEM**. As the outperforming rules are based on relatively high frequent trades, **most lucrative rules yield negative returns in the out-of-sample periods once transaction costs were considered**」 |

**时间序列很清楚**：2019 年那篇乐观的样本是 1990s–2010s（含 2005–07 泡沫与 2015 杠杆牛）；2024 年那篇覆盖 2010–2021，结论是**样本外扣成本后为负**，创业板一条都不剩。这与 STW 1999 在美股上的发现结构完全一致——**技术规则的有效期随市场成熟度衰减**。

### B3. 反面证据（单列）

1. **STW (1999) 的样本外全灭**。见 [B2] 原文引述。这是最经典的一击，且作者已排除「1987 崩盘污染」的解释。
2. **Lissandrin et al. 自己承认 Sequential 不预测方向**。见 [B1]。一个不预测方向的信号被渲染成 `B` / `S` 两个字母，是**渲染层制造了原信号没有的信息**——这是本次产品形态最本质的风险。
3. **A 股 2024 年那篇：扣成本后样本外为负，创业板零存活**。见 [B2]。
4. **跨市场证据**：Pätäri 等 (2023) 对 23 个发达 + 18 个新兴市场、6,406 条规则、最长 66 年做 stepwise SPA，结论「the predictability **diminishes drastically over time** in all markets. In particular, markets turn **unpredictable in the last years** of our sample... the results are **very sensitive to the introduction of moderate transaction costs**... Overall, our results **cast serious doubt** on whether investors could have earned any excess profits」`E2`。
5. **东财自家帮助中心的自曝**（针对九转，原文）：「神奇九转也是**滞后性指标**」「**只适用于震荡市、弱牛市和弱熊市，不适用于大牛市和大熊市**，因为在强势行情中，标的价格可能连续出现多个九转结构而不反转」「不能单独作为买卖依据」。**供应商自己写的适用边界比多数回测文章诚实。**
6. **东财自家 DK 页的自曝**（原文）：「以上操盘记录是在理想环境下依据历史数据通过人工智能演算所得结果。该结果**未考虑冲击成本等复杂市场因素**」——即那三个 +174% / +88% / +68% 是**未扣冲击成本的理想回测**。

### B4. 一句话判定

**「在 K 线上标 B/S」这个产品形态没有学术问题；「这些 B/S 是对的」有严重学术问题。** 前者是可视化，后者是主张。本仓可以做前者，但必须在 UI 与文档上拒绝后者。

---

## C. 「在 K 线图上标 B/S 点」在本仓的实现可行性

**全部只读核对，未改任何文件。**

### C1. 主 K 线组件与已注册的 ECharts 组件

主组件：**`frontend/src/shared/components/charts/KlineChart.vue`**（405 行）。

已注册组件（`KlineChart.vue` 第 26–36 行）：

```ts
echarts.use([
  CandlestickChart,
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkPointComponent,
  CanvasRenderer,
])
```

| 组件 | 状态 | 备注 |
|---|---|---|
| `MarkPointComponent` | **已注册**（import 第 8 行 / use 第 34 行） | **画 B/S 钉不需要任何新注册** |
| `MarkLineComponent` | **未注册** | 若要复刻东财那条**虚线引线**才需要加。仓内已有先例：`MinuteSessionDialog.vue:10,30`、`EquityLineChart.vue:6,16` |
| `MarkAreaComponent` | **未注册** | 本需求用不到 |

option 构建下沉在 **`frontend/src/shared/lib/klineChartOption.ts`**（339 行，`buildKlineOption`）。**`markPoint` 已经在用**：

```ts
// klineChartOption.ts 第 153–157 行
      markPoint: {
        symbol: 'rect',
        symbolSize: [44, 16],
        data: [...limitMarks],
      },
```

`limitMarks` 来自 **`frontend/src/shared/lib/klineLimitMarks.ts`**（41 行）——**这就是 B/S 标记的现成模板**，形状完全通用：

```ts
// klineLimitMarks.ts 第 24–38 行
    marks.push({
      name: limitLabel(kind),
      coord: [dates[i], y],
      value: limitLabel(kind),
      symbol: 'pin',
      symbolSize: 28,
      symbolOffset: kind === 'up' ? [0, -4] : [0, 4],
      itemStyle: { color: kind === 'up' ? t.up : t.down },
      label: {
        formatter: limitLabel(kind),
        color: t.sheet,
        fontSize: 9,
        fontWeight: 650,
      },
    })
```

把 `limitLabel(kind)` 换成 `'B'` / `'S'`、`t.up/t.down` 换成买卖色、`coord[1]` 取 `low`（B）或 `high`（S），**就是东财那个效果**。`symbol: 'pin'` + `symbolOffset` 本身就带一个类似引线的针脚。

**宿主**（两处，都不用改结构）：

- `frontend/src/features/market/components/DataQueryDetailPanel.vue:257`（个股 K 线详情，通达信式三窗）
- `frontend/src/features/ai/components/AssistantKlineCard.vue:42`（助手 `kline` artifact，MA 固定 `[5,10,20]`，见 `assistantArtifacts.ts:59`）

`DataQueryDetailPanel` 的最终宿主是 **`frontend/src/features/ledger/ArchiveView.vue:411`**（个股工作台）。

### C2. 现成的信号数据通道 —— 一条能用，一条方向不对

这是本次调研**最关键的发现**，也是唯一的真缺口所在。

#### ✅ 能直接用：账本时间线（一只票 × N 天）

```ts
// frontend/src/shared/types/palace.ts 第 147–154 行
export interface TimelineEvent {
  id: string
  date: string
  created_at: string
  type: 'trade' | 'candidate' | 'plan' | 'review'
  label: string
  detail: Record<string, unknown>
}
```

- API：`frontend/src/shared/api/palace.ts:230` → `GET /timeline/{code}`
- Store：`frontend/src/shared/stores/palace.ts:41` `selectedTimeline`，经 `ensureArchiveSlice(code, ['timeline'])` 按需加载
- **`ArchiveView.vue` 已经在同一个组件里同时握着 K 线和这份时间线**：

```ts
// ArchiveView.vue 第 92–95 行
const timeline = computed(() => (store.selectedCode === code.value ? store.selectedTimeline : []))
const trades = computed(() => store.trades.filter((item) => item.code === code.value))
const candidates = computed(() => timeline.value.filter((e) => e.type === 'candidate'))
const tradeEvents = computed(() => timeline.value.filter((e) => e.type === 'trade'))
```

**`tradeEvents` 就是「我在这只票上的历史买卖」，`candidates` 就是「这只票被选中过的日子」，两者都自带 `date`。喂给 markPoint 的数据结构已经躺在同一个 `<script setup>` 里，只差一次 map。**

另外 `PoolView` / `StockLink` 进档案时已经带 `?date=YYYY-MM-DD`，`ArchiveView` 转成 `focusDate` 传给 `KlineChart`，后者 `findFocusIndex` + `zoomAroundIndex` 把视窗锚到那一天（`KlineChart.vue:143-149, 303-313`）。**「单个信号日 → 图上定位」的管道已经通了，只是现在表现为缩放锚点，不是可见标记。**

#### ❌ 方向不对：策略侧信号（一天 × N 只票）

```ts
// frontend/src/shared/types/screenSkill.ts 第 329–340 行
export interface Pick {
  code: string
  name?: string
  board_bucket?: string
  board_label?: string
  is_st?: boolean
  open: number | null
  close: number | null
  pct_chg?: number | null
  intent?: 'observe' | string
  factors: Record<string, number | boolean | null>
}
```

**`Pick` 里没有 `trade_date`** ——日期挂在外层 `ScreenResult.trade_date`（`screenSkill.ts:398-416`）。`SkillWatchSignal` / `SkillWatchPick`（`quant-jobs.ts:213-230`）同样只有 `code`，没有日期。

也就是说：**策略信号的天然形状是「某一天选出了哪些票」，而 K 线要的是「这只票在哪些天被选出过」。转置这件事目前没有现成端点。**

已有的半个补丁：`ScreenRangeDay`（`screenSkill.ts:381-387`，含 `trade_date` / `picks` / `watch_picks`）说明后端有逐日跑选股的能力，前端理论上可以拉一段区间再自己转置——但那是 N 天 × 全市场的数据量，为了画一只票的标记去拉它是不划算的。

`unified_monitor_pool` / `skill_watch` 在后端有丰富的按日信号（`src/ops/application/skill_watch/*`、`src/ops/infrastructure/store_watch.py`），但**没有暴露「按 code 取历史信号」的只读 API**。

### C3. 标记密度：仓内已有先例，直接沿用

`KlineChart.vue` 对「标签太密」这件事已经立过规矩：

```ts
// KlineChart.vue 第 97 / 111–117 行
const LABEL_VISIBLE_MAX = 90
// ...
function visibleCountOf(n: number): number {
  return Math.max(1, Math.round((n * (zoomEnd - zoomStart)) / 100))
}

function shouldShowBarLabels(n: number): boolean {
  return n > 0 && visibleCountOf(n) <= LABEL_VISIBLE_MAX
}
```

并在 `datazoom` 事件里用 `patchBarLabels()`（第 213–222 行）做增量 `setOption({ lazyUpdate: true })`，**不整图重绘**。B/S 标记应当接同一条闸门（阈值可以更低，比如 60），而不是另起一套。

窄屏口径：`ArchiveView.vue:243` 定义 `narrow = window.matchMedia('(max-width: 959px)').matches`，全页共用这一个断点。

视口硬约束在 `frontend/AGENTS.md` §3.7.1：**禁止文档级滚动条**；路由页根用 `.page-fill`，滚动下沉到 `.page-scroll` 或表体。B/S 标记画在 canvas 内，**不产生新的高度**，与这条约束无冲突；但**图例/开关不要新起一行页头**，应挤进 `DataQueryDetailPanel` 已有的 `.tdx-controls`（第 190–238 行，那里已经是 `el-radio-group` + `el-popover` + `el-button` 的组合）。

按 `frontend/AGENTS.md` §3.3.1 的强制表，那个开关必须是 **`el-button`（或 `el-switch`）**，不能手写 `<button>`。

### C4. 三个必须先定死的口径（否则实现完是错的）

1. **复权对齐。** `markPoint` 的 `coord` 是 `[dateString, price]`，而面板可在 `qfq / hfq / none` 之间切（`DataQueryDetailPanel.vue:200-211`）。账本成交价是**原始成交价**；前复权下 K 线整体被缩放，B 钉会**浮在 K 线之外**。要么用 `adjust_factors` 把信号价一起换算，要么干脆只用 `coord[1] = bar.low / bar.high`（跟着当前 K 线走，不用信号自带价格）。**后者更省事也更不会错。**
2. **周/月 K 会静默丢标记。** `chartPrep.ts:35-36` 里 `dates = resampleBars(bars, period).map(b => b.trade_date)`——周/月线的 `dates` 是**聚合后的代表日**，日频信号日在里面**命中不了**，category 轴上的 `coord` 会静默不画。要么先把信号日聚合到所属周/月 bucket，要么在非日 K 时直接隐藏 B/S（推荐后者，与「DK点」在东财也只在日线可用一致）。
3. **「这不是 DK」。** 只要 UI 上出现 B/S，就必须在同一屏能看到「这是本机 XX 战法 / 我的成交记录」的归属说明。本仓 `src/AGENTS.md` 业务红线里 ai 一栏写着「不产出权威行情/盈亏」，同一精神适用于此：**不得让用户以为看到的是券商级信号。**

### C5. 最小改动清单

**必改 5 个源文件：**

| # | 文件 | 改什么 | 量级 |
|---|---|---|---|
| 1 | `frontend/src/shared/lib/klineSignalMarks.ts`（**新建**） | 照 `klineLimitMarks.ts` 的形状写 `buildSignalMarks(bars, dates, signals, tokens)`；`signals: Array<{ date: string; side: 'buy' \| 'sell'; label?: string; tip?: string }>` | ~45 行 |
| 2 | `frontend/src/shared/lib/klineChartOption.ts` | `buildKlineOption` 入参加 `signalMarks?: Array<Record<string, unknown>>`；第 156 行 `data: [...limitMarks]` 改成 `data: [...limitMarks, ...signalMarks]` | 3 行 |
| 3 | `frontend/src/shared/components/charts/KlineChart.vue` | 加 prop `signals?: KlineSignal[]`；在 `buildOption()`（第 151–163 行）里调 `buildSignalMarks`；接进 `watch` 依赖数组（第 353–379 行）。**`MarkPointComponent` 已注册，不加 `use()`** | ~10 行 |
| 4 | `frontend/src/features/market/components/DataQueryDetailPanel.vue` | 透传 `signals`；在 `.tdx-controls` 里加一个 `el-button`（`plain` / 选中态）当「买卖点」开关，本地 `useLocalStorage` 记住状态（与第 53 行 `loci.market.maPeriods` 同风格） | ~15 行 |
| 5 | `frontend/src/features/ledger/ArchiveView.vue` | 把已有的 `tradeEvents` / `candidates`（第 94–95 行）map 成 `KlineSignal[]` 传下去。**数据零新增** | ~12 行 |

**同批必须更新的 README（`AGENTS.md` DoD 硬要求）：**

| # | 文件 | 加什么 |
|---|---|---|
| 6 | `frontend/src/features/market/README.md` | 第 20–22 行 `DataQueryDetailPanel` 那段补一行「买卖点标记开关 / 只在日 K 生效 / 数据来源与口径」 |
| 7 | `frontend/src/features/ledger/README.md` | 第 11 行 `ArchiveView.vue` 那段补一行「行情 tab 可叠账本买卖点」 |

**建议同批但非必须：** `frontend/src/shared/lib/klineSignalMarks.test.ts`（纯函数，参考 `minuteChartOption.test.ts:91-124` 的 markPoint 断言写法）。

**只有想复刻虚线引线时才加的第 8 项：** `KlineChart.vue` 追加 `use([MarkLineComponent])` + 每个信号配一条 `markLine`。**不推荐**——`symbol: 'pin'` 的针脚已经有指向性，加 markLine 会让密集区变成一片竖线。

### C6. 现成能力覆盖到什么程度，还缺什么

| 环节 | 状态 |
|---|---|
| ECharts 能力（markPoint / 定位 / 主题色 / 密度闸门） | ✅ **全都有**，且有 `buildLimitMarks` 这个逐行可抄的先例 |
| 组件注册 | ✅ `MarkPointComponent` 已在 `use()` 列表里，**零新增** |
| 「一只票 × N 天」的信号数据（**账本口径**） | ✅ `TimelineEvent` + `GET /timeline/{code}`，且已在宿主组件内 |
| 单信号日 → 图上定位 | ✅ `focusDate` → `findFocusIndex` → `zoomAroundIndex` 已通 |
| 交互开关（DK点 那个按钮） | ✅ `.tdx-controls` 有现成位置，EP 组件齐 |
| 窄屏 / 视口约束 | ✅ 断点与规则都已存在，markPoint 不吃高度 |
| 「一只票 × N 天」的信号数据（**战法口径**） | ❌ **缺**。需要一个新的只读端点（`GET /api/screen/signals/{code}?strategy=&start=&end=`）把 `ScreenResult` 转置成按 code 的时间序列，或复用 `screen/range` 在前端转置 |
| 复权口径对齐 | ⚠️ **未决**，见 [C4].1 |
| 周/月 K 的日期 bucket | ⚠️ **陷阱**，见 [C4].2 |
| DK 算法本身 | ❌ **永远缺**，见 [A5] |

**一句话**：**画布是白送的，第一版（标自己的买卖记录）只需要动 5 个文件、零后端改动、零新依赖；真正要投入的是「战法信号按 code 的时间序列」这一个后端端点，以及复权口径这一个决策。**

---

## D. MA60 / MA120 的既有用法与数据深度

### D1. 前端：默认就比东财那张图多两条

```ts
// frontend/src/shared/lib/klineConfig.ts 第 19 行
export const DEFAULT_MA_PERIODS: number[] = [5, 10, 20, 30, 60, 120, 250]
```

用户截图里东财是 `MA5/10/20/60/120` 五条；**本仓默认七条，含 MA60 / MA120 / MA250**。而且是**用户可改**的：`DataQueryDetailPanel.vue:212-236` 有「均线设置」popover，`normalizeMaPeriods`（`klineConfig.ts:42-51`）允许 2–500 任意整数、去重升序、清空即不画，结果存 `useLocalStorage('loci.market.maPeriods')`。

**这一条不需要任何改动，用户「60日、120日也是可以考虑的」这个诉求本仓已经满足且超额满足。**

唯一例外是助手卡片：`assistantArtifacts.ts:59` 把 `ASSISTANT_KLINE_MA` 钉死成 `[5, 10, 20]`（因为卡片只有 16rem 高、最少 20 根）。这是刻意的窄场景配置，不建议动。

### D2. 后端：MA60 / MA120 已在算，但战法层没用

| 位置 | 用法 |
|---|---|
| `src/research/application/technical.py:195` | 研究维度 `2_kline` 的标量集合含 `"ma5", "ma10", "ma20", "ma60", "ma120", "ma200"`，全部随 `indicator_frame(frame)` 一次算出 |
| 同文件 `:209-211` | 不足 200 根时显式记 gap：「历史不足 200 根，MA200/Stage 可能不完整」——**已有「深度不够就说出来」的机制**，不静默 |
| `src/ai/application/system_toolbus_research.py:7-18` | 助手只读研究工具的 `_METRIC_KEYS` 含 `"ma20", "ma60", "ma200"` |
| `src/formula/domain/functions.py:42` | `MA(X, N)`：任意 N 的通达信同款简单均线，「不足 N 根返回空值，与通达信一致」。`REF` / `BARSLAST` / `EMA` / `SMA` / `WMA` / `DMA` 同在（第 24 行白名单） |
| `src/strategy/application/tail_resonance.py:159-194` | **只用到 MA3 / 8 / 10 / 20 / 25 与 `MA(volume, 20)`，没有 MA60 / MA120** |
| `src/strategy/application/backup/lugaowen-legacy.py:241` | 有 `ma20 / ma60` 金叉判断，但这是 `backup/` 下的 legacy 文件，不在活跃战法链路 |

**结论：MA60/MA120 在「展示」和「研究读数」两层都在用；在「战法判定」层基本没用（只有一个 legacy 备份文件）。** 这是个事实陈述，不是缺陷——本仓短线战法本来就吃 3–25 日尺度。

### D3. 数据深度够不够

| 层 | 深度 | 够 MA120 吗 | 够 MA250 吗 |
|---|---|---|---|
| 前端单票拉取（个股工作台） | `ArchiveView.vue:63` `quotesLimit = ref(320)`；周 K `max(800, 320)`、月 K `max(1500, 320)`（第 67–71 行） | ✅ 320 − 120 = 200 根有值 | ✅ 320 − 250 = 70 根有值 ≥ 默认可视 60 根（`KlineChart.vue` prop 默认 `visibleBars: 60`）。**320 这个数就是按 MA250 + 60 根可视反推出来的** |
| 前端通用默认 | `useQuotesQuery.ts:32,43` `limit ?? 60` | ❌ 只有 60 根 | ❌ |
| 热读库 `market_hot.db` | `src/market/infrastructure/store_hot.py:29` `HOT_WINDOW_TRADING_DAYS = 700`（注释：「≈2.8 年。覆盖 MA250 与常规选股/面板/复盘窗口」） | ✅ 绰绰有余 | ✅ 700 ≫ 250 |
| 全量 `market.db` | 权威库，全历史 | ✅ | ✅ |

**ADR-007 决策 5** 明确：「`requires_full_history` 的策略、未配置热库、镜像失败或热库末日落后于全量时，**回退全量库**选股」，且「长历史公式必须声明 `requires_full_history`」。

**判定：MA120 / MA250 在热读库窗口内完全够用，无需任何窗口调整。** 唯一要留神的是：如果将来某个战法要跑 MA250 **的多年历史序列**（不是只要最新值），那已经超出 700 天窗口的「有值区间」（700 − 250 = 450 根），得按 ADR-007 声明 `requires_full_history` 走全量库。

---

## 附：本轮实际发出的请求

只读、无凭据、每个 URL 单次，不构成爬取。

| # | 请求 | 结果 |
|---|---|---|
| 1 | `GET https://caifuhao.eastmoney.com/news/20241230091832664953780`（DK股票池功能说明） | `200`，正文全文，见 [A2](4) |
| 2 | `GET http://zqhd.eastmoney.com/Html/aghd/pc/20180309/html/activity1.html?ad_id=...`（DK 开户活动页） | `200`，正文全文 |
| 3 | `GET https://zqhd.eastmoney.com/Html/aghd/native/5.5/20181126/html/share1.html`（DK操盘密码官方页） | `200`，正文全文，见 [A2](1) |
| 4 | `GET https://acttg.eastmoney.com/pub/ttjjapp_hskh_hqy_ggdt_01_01_01_0`（DK 产品页） | `200`，正文极短，见 [A2](2) |
| 5 | `GET https://qhweb.eastmoney.com/help/2437550.html`（东财**官方帮助中心**·神奇九转指标介绍） | `200`，算法全文，见 [A4] |
| 6 | `GET https://www.eastmoney.com/default.html` | `200`，产品栏含「电脑增值版 → 操盘密码」 |
| 7 | `GET https://demark.com/sequential-indicator/` | **超时 ×1，未验证**。仅检索摘要 `E2` |
| 8 | `GET https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2696155` | **超时 ×1，未验证**。改读作者版全文 PDF（#9） |
| 9 | `GET https://technicalanalyst-cdn-1.s3.eu-west-2.amazonaws.com/.../Unblinded-Manuscript.pdf`（Lissandrin/Daly/Sornette 作者版全文） | `200`，79.3 KB / 1,628 行，**全文已读** `E1` |
| 10 | `GET https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf` | `200`，92.3 KB / 1,110 行，**全文已读** `E1` |
| 11 | `GET http://eprints.lse.ac.uk/119144/1/dp303.pdf`（STW 工作论文版） | `200`，97.4 KB |
| 12 | 检索：东财 DK / 九转 / DeMark 学术检验 / data-snooping / A 股技术规则 / Williams Fractals / 通达信九转公式 | 见各节引用 |
| 13 | 本机只读：`frontend/src/shared/{components/charts,lib,types,api,stores}`、`frontend/src/features/{market,ledger,ai}`、`src/{formula,research,strategy,market,intel}`、`docs/adr/ADR-007` | 见 [C]、[D] |

**未做**：批量抓取、带凭据请求、注册账号、下载东财客户端、反编译、写入任何数据库、修改除本文与 `INDEX.md` 之外的任何文件。

---

## 未解决的问题

1. **DK 点的算法**：官方未公开，社区无可信逆向，且输入含本仓拿不到的资金流。**这是终态，不用再查了**——除非东财哪天出帮助中心页。
2. **`B` / `S` 字母渲染**：官方文档一律写「D点（红）/ K点（蓝）」。用户截图里的 `B`/`S` 未能从官方来源验证，本文按「同一 DK 信号的新版渲染」处理，但**不作断言**。若要确证，只能靠 App 内截图对照版本号，本轮无此条件。
3. **DeMark 原著第 7 章逐字原文**：版权书籍，未读到。本文的 Setup/Countdown 精确规则来自 DeMARK Analytics 官网摘要（`E2`）+ 一篇同行评审论文的形式化复述（`E1`），两者互相印证且与东财帮助中心的中文口径一致，但**不等于原书原文**。
4. **A 股上的 DeMark / 九转一手检验**：**没有找到**。检索到的全是自媒体与投教内容。若真要用九转，只能自己在本仓回测框架里跑，且必须按 [B2] 的教训做样本外 + 扣成本 + 正反两个方向。
5. **SuperTrend 的原始出处**：只查到「归于 Olivier Seban」，未找到作者本人的出版物或官方定义页。按硬要求标为**出处不明**，若要采用需先补一手来源。
6. **战法信号按 code 的时间序列端点**：目前不存在，也没有 ADR 讨论过它该归 `strategy` 还是 `ops`。这是 [C5] 之外唯一需要架构决策的点。
7. **复权口径**：账本成交价 vs 前复权 K 线的对齐方式尚未决策，见 [C4].1。实现前必须先定死，否则 B 钉会飘。
