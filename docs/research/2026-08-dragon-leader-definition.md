# A 股「龙头股」识别与定义体系 · 网络调研报告

> 调研日期：2026-08-11。方法：中文公开资料网络检索（游资语录整理、淘股吧/雪球/开普饭帖子、东方财富财富号、拾荒网/55188 等短线社区、量化专栏、财经媒体报道）。
> 性质：**市场惯例（folk taxonomy）综述**，不是监管定义，也不是已验证有效的策略。所有阈值都是「圈内常见口径」，本报告未做任何回测验证。
> 姊妹文档：[`dragon-leader-identification.md`](dragon-leader-identification.md) 给出的是**可回测、无未来函数的工程合同**（含交易所规则与同行评议文献）。本文补的是它刻意回避的另一半：**市场上实际在用的说法、术语和阈值**。两份文档配合读——本文告诉你「市场怎么说」，那份告诉你「工程上怎么才敢信」。

## 0. 证据分级口径

本文每条结论标注三档：

| 标记 | 含义 |
| --- | --- |
| **【广泛共识】** | ≥3 个互相独立的来源表述一致，且属于短线圈通用术语 |
| **【多数口径】** | 2 个以上来源一致，但存在可查到的不同数值口径 |
| **【个别说法】** | 单一来源、二手转述、或明显是作者自创模型；**不可直接落生产** |

另有一条贯穿全文的重要警告：**几乎所有龙头资料都是事后归因**。拾荒网明确写过「大多数市面上的首阴战法都是事后看图说话，不成功的龙头首阴比成功的要多得多」（<http://www.10huang.cn/zhangting/39480.html>）。本文照抄阈值，不代表这些阈值经过样本外检验。

---

## 1. 龙头的定义与分类

### 1.1 共识内核：三个特质，不是「涨得最高」

各来源在**定义内核**上高度一致【广泛共识】：龙头是「题材的情绪锚点 / 资金共识核心 / 板块上涨标杆」，必须同时具备：

1. **带动性** — 它涨停，板块跟着涨停；它断板，板块跟着分歧。**没有带动性，涨得再高也不是龙头**（独苗连板股属于「庄股自拉自唱」）。
2. **辨识度** — 提到该题材，全市场第一个想到它。
3. **抗跌性** — 板块分歧时它最抗跌甚至逆势涨停，退潮时它最后一个跌。

来源：<https://vcai.cn/index.php/celue-ticaitouji-4/>、<https://zhangtingke.com/longtougu>、<https://caifuhao.eastmoney.com/news/20230928154127665655390>、<http://www.10huang.cn/zhangting/49164.html>

拾荒网把这点说得最直白：**「板块带动性是区分（总龙头与板块龙头）他们最本质的依据」**（<http://www.10huang.cn/zhangting/49164.html>）。

### 1.2 分类是多维度的，不是一个平面清单

市面清单常把 8~10 种「龙头」并列罗列（<https://www.55188.com/thread-10228179-1-1.html> 列 8 种；<https://caifuhao.eastmoney.com/news/20230928154127665655390> 列 10 种），但那是**混维度**的。实际上至少有四个正交维度：

| 维度 | 取值 | 说明 |
| --- | --- | --- |
| **影响力层级** | 总龙头（市场龙）> 板块龙头 > 日内龙 | 覆盖范围，互斥（同一时刻只能占一档） |
| **胜出方式** | 空间龙（高度）/ 时间龙（身位）/ 人气龙（关注度）/ 换手龙 / 一字龙 | 描述「靠什么当上的」，**可叠加** |
| **周期角色** | 先锋龙 → 卡位龙 → 总龙头 → 补涨龙；中军独立一档 | 时间序列上的角色，**互斥且会迁移** |
| **走势形态** | 连板龙 / 趋势龙 | 注册制后新增的分叉，基本互斥 |

### 1.3 各类型判定口径

| 类型 | 判定口径 | 是否互斥 | 主要来源 |
| --- | --- | --- | --- |
| **总龙头 / 市场龙 / 精神领袖** | 一个阶段内①跨越时间周期最长 ②涨幅最高 ③带出小弟最多，**三者缺一不可**；大多从四板起步 | 同一时刻唯一 | <http://www.10huang.cn/zhangting/46556.html> |
| **板块龙头** | 板块内连板数最多 + 涨停时间最早 + 封单最大；封单接近时看流通盘（小者为龙） | 与总龙头是包含关系（总龙头必是某板块龙） | <http://www.10huang.cn/zhangting/49164.html> |
| **空间龙（最高板）** | 连板高度最高，打开题材上涨空间；是情绪周期的高度锚 | 常与总龙头重合但**不必然** | <https://vcai.cn/index.php/celue-ticaitouji-4/>、<http://www.10huang.cn/zhangting/46556.html> |
| **时间龙 / 先锋龙 / 身位龙** | 题材爆发日**第一个涨停**的票，有身位优势、抛压小 | 只在启动日有效，之后可能被卡位 | <https://caifuhao.eastmoney.com/news/20230928154127665655390>、<https://www.55188.com/thread-10228179-1-1.html> |
| **人气龙 / 情绪龙** | 市场关注度最高、波动最大、能引发资金共振；开普饭指出人气龙「要么走两波，要么走双顶反包」，而空间龙「一般走尖顶」 | 与空间龙**可分离**（这是关键区分点） | <https://www.kpfans.com/article/wLWoo3ynWj.html>、<https://caifuhao.eastmoney.com/news/20241002144328309940970> |
| **卡位龙** | 龙头争夺期「后发先至」，抢先上板卡掉原龙头身位；常因多重题材叠加而胜出 | 胜出后即成为新的板块龙/总龙头 | <https://www.55188.com/thread-11956376-1-1.html> |
| **中军** | 市值大、流动性好、机构+游资共同参与，涨幅稳定不暴涨暴跌，决定题材持续性 | **与情绪龙互斥**（角色不同） | <https://vcai.cn/index.php/celue-ticaitouji-4/> |
| **补涨龙** | 总龙头见顶横盘后启动的同题材低位标的；周期短（一般 3-5 个板），连板高度约为总龙头的一半 | 与总龙头**时间上互斥** | <https://vcai.cn/index.php/celue-ticaitouji-4/> |
| **趋势龙** | 不连板但涨不停，沿 5/10 日线持续上涨，回调不破 10 日线；日均成交额 ≥10 亿；机构+游资共振 | 与连板龙**基本互斥** | <https://vcai.cn/index.php/celue-ticaitouji-4/>、<https://vcai.cn/index.php/celue-ticaitouji-10/> |
| **日内龙** | 当日板块内人气最高/走势最强；多在早盘前 15 分钟产生；市场混沌期的产物 | 单日有效，不是稳定身份 | <https://www.55188.com/thread-10228179-1-1.html> |
| **一字龙** | 利好驱动开盘一字，筹码锁仓度高 | 55188 明确指出**一字龙「谈不上有什么人气」**，对情绪影响小 | <https://www.55188.com/thread-11956376-1-1.html> |

### 1.4 同一只票的不同侧面 vs 真正互斥

**可以是同一只票的不同侧面**（大周期里高度重合）：

- 总龙头 ≈ 人气龙 ≈ 空间龙 ≈ 时间龙 — 2023 年圣龙股份（华为汽车）被多个来源同时描述为总龙头 + 空间龙 + 带动 30+ 家涨停，即四者合一。这是**最理想也最少见**的形态。
- 板块龙头 ⊂ 总龙头 — 总龙头一定是某个板块的龙头，反之不成立。

**结构性可分离（最需要注意的分歧点）**：

- **空间龙 ≠ 人气龙**【多数口径】。开普饭专门写了两者区别：指数与情绪好时空间龙容易走成人气龙，但空间龙一般走**尖顶**（连续确认下跌），人气龙走**两波或双顶反包**（<https://www.kpfans.com/article/wLWoo3ynWj.html>）。一字连板堆出来的高度是空间不是人气。
- **时间龙 ≠ 总龙头**。先手龙「在题材炒作前期很香，但题材一致后分歧的阶段，如果其率先走弱，很容易坑人」（<https://caifuhao.eastmoney.com/news/20230928154127665655390>）。
- **总龙头连板数不一定最多**。拾荒网明确反对「总龙头就是连板数最多那个」的说法，认为「比较片面」，判断标准应是「谁激活了市场的人气」（<http://www.10huang.cn/zhangting/46556.html>）。

**真正互斥**：

- 中军 vs 情绪龙（大市值稳涨 vs 小市值暴涨，角色分工）
- 补涨龙 vs 总龙头（时间上前后接力）
- 连板龙 vs 趋势龙（形态互斥，注册制后这条越来越重要）

---

## 2. 龙头的确认标准（可量化部分）

> 阈值后括号内为来源与共识度。**发现多处冲突，已逐条标注**。

### 2.1 启动位置

| 项 | 常见阈值区间 | 来源 / 分歧 |
| --- | --- | --- |
| **筹码位置** | 低位单峰密集，上方套牢峰已消化，距离前高远 | 【广泛共识】<https://ag.yueniuzq.com/qa/ru-he-cong-pan-mian-shi-bie-long-tou-gu-q-s2-75667/>、<https://www.logic88.cn/40741.html> |
| **K 线形态** | 涨停突破大平台 / 创新高为佳，或上方阻力位很远 | 【多数口径】<http://www.10huang.cn/zhangting/42938_all.html>；章盟主口径为「涨停突破年线、半年线或前高」（<https://caifuhao.eastmoney.com/news/20190610153336058612360>） |
| **启动前累计涨幅上限** | 前期**不能翻倍**，否则后续首阴模式易失败 | 【个别说法】<https://www.chaogu1688.com/17907.html> |
| **启动市值** | **口径严重分歧**：30-100 亿（vcai）／流通盘 50-200 亿（涨停客）／3-60 亿（章盟主 2019 旧版）／50-500 亿（章盟主 2026 二手整理） | ⚠️ 无共识。<https://vcai.cn/index.php/celue-ticaitouji-4/>、<https://zhangtingke.com/longtougu>、<https://caifuhao.eastmoney.com/news/20190610153336058612360>、<https://caifuhao.eastmoney.com/news/20260320044417356732630> |
| **启动日放量** | 放量 2 倍以上 | 【个别说法】<http://caijing.cn99.net.cn/article-215995-1.html> |

> **市值口径分歧的解读**：这不是有人写错，而是**时代变了**。2019 年章盟主说 3-60 亿，2026 年整理说 50-500 亿，中间隔着注册制和量化崛起（详见 §6）。用哪个取决于你打算复现哪个年代的玩法。

### 2.2 连板高度 / 涨停次数 / 区间涨幅

| 项 | 常见阈值区间 | 来源 / 分歧 |
| --- | --- | --- |
| **总龙头起步高度** | 大多从**四板**起步 | 【多数口径】<http://www.10huang.cn/zhangting/46556.html> |
| **板块龙常见顶部** | 4-5 板；能走到 4 板的一个板块通常只有 1-2 只，5 板更少 | 【多数口径】<https://caifuhao.eastmoney.com/news/20241002144328309940970> |
| **注册制后连板高度** | 普遍压缩到 **5-7 板**，很难再走超长连板 | 【多数口径】<https://vcai.cn/index.php/celue-ticaitouji-4/> |
| **2026 年连板高度** | 进一步降至 **2-3 板** | ⚠️ 见 §6，主流媒体报道趋势属实，但具体数字为二手 |
| **龙回头前提涨停数** | ≥3 个涨停（多数）／2-3 个（放宽）／5 板以上换手板最佳（严格） | 【多数口径】<https://m.tgb.cn/a/2hqZCPSKPnz>、<https://finance.sina.com.cn/roll/2025-06-26/doc-infcmcye4619814.shtml>、<https://m.tgb.cn/a/2pdQagAaKg2> |
| **首阴博弈的位置** | 2-5 板自然换手连板；**3-5 板之间性价比最高**（3 板以下辨识度不足，5 板以上风险剧增） | 【个别说法】<https://xueqiu.com/2801102342/370428778> |
| **首阴前短期涨幅** | 超过 40% | 【个别说法】<https://finance.sina.com.cn/roll/2025-06-15/doc-infaczmh1890634.shtml> |
| **龙回头回调幅度** | 20%-30%（严格）／15%-30%（宽松） | 【多数口径】<https://m.tgb.cn/a/2hqZCPSKPnz>、<https://caifuhao.eastmoney.com/news/20260323225813677394530> |
| **龙回头回调时间** | 3-10 个交易日，理想 **5-7**（或 5-8） | 【广泛共识】<https://m.tgb.cn/a/2pdQagAaKg2>、<https://finance.sina.com.cn/roll/2025-06-26/doc-infcmcye4619814.shtml> |

> **关于「20 日涨幅 ≥ X%」**：调研中**未找到**任何权威短线资料把固定的「N 日涨幅阈值」当作龙头定义。市面上的通达信「龙头」选股公式确实用涨幅条件，但用法是**过滤**而非定义——例如「近 5 日内出现过涨停 + 5 日均线斜率 >75° + 股价连阳」（<http://www.gspt.com/gs/15453>），或反向排除「89 日前涨幅 ≥80%」「近 5 日累计涨幅 ≥30%」的高位股（<https://www.tdxzb.com/?id=9540>）。本仓已有的 [`dragon-leader-identification.md`](dragon-leader-identification.md) §「为什么『20 日涨 25%』不足」对此有更严格的论证，此处结论一致：**区间涨幅只能做初筛，不能做定义**。

### 2.3 封单额、封成比、开板次数

这是分歧最大的一块。三种口径并存：

| 口径体系 | 阈值 | 来源 |
| --- | --- | --- |
| **封流比（封单额/流通市值）主流档** | >3% 极强；1%-3% 较强；<1% 偏弱 | <https://ag.yueniuzq.com/market-review/how-to-judge-limit-up-seal-quality-in-review/>、<https://ag.yueniuzq.com/market-review/evaluate-limit-up-seal-quality-in-review/> |
| **封流比激进档** | >10% 极强（多为一字）；3%-10% 较强；<3% 偏弱 | <https://ag.yueniuzq.com/market-review/calculate-next-day-throwing-pressure-via-limit-up/> |
| **封流比宽松档** | >2% 即算质量较高；打板要求 ≥3% | <https://baike.kuaiji.com/v134915079.html>、<https://vcai.cn/index.php/celue-ticaitouji-4/> |
| **首板专用（更低）** | 封单/流通盘 0.8%-2% | <http://caijing.cn99.net.cn/article-215995-1.html> |

⚠️ **同一个「3%」在三套体系里分别是「极强」「较强」「宽松下限」。落地必须先固定一套口径**，且需按市值分档：小盘股通常要 3% 以上才算强，流通市值 500 亿以上的大盘股 0.5% 就已算较强（<https://ag.yueniuzq.com/market-review/how-to-judge-limit-up-seal-quality-in-review/>）。

其余封板质量项：

| 项 | 常见阈值 | 共识度 / 来源 |
| --- | --- | --- |
| **封成比（封单额/成交额）** | 封单额达当日成交量的 30%-50% 以上说明买盘意愿强；部分量化策略参考封成比 >10 | 【多数口径】<https://ag.yueniuzq.com/market-review/identify-sustainable-sector-leader/>、<https://baike.kuaiji.com/v134915079.html> |
| **封板时间** | 早盘封板优于午盘/尾盘；**10:00 前**（涨停客）或 **10:30 前**（约投顾）为佳；**14:30 后为偷袭板，不打** | 【广泛共识】<https://zhangtingke.com/longtougu>、<https://ag.yueniuzq.com/market-review/evaluate-limit-up-seal-quality-in-review/>、<https://vcai.cn/index.php/celue-ticaitouji-4/> |
| **首板黄金时段** | 9:30-9:35 第一个涨停，越早越有龙头相 | 【个别说法】<http://caijing.cn99.net.cn/article-215995-1.html> |
| **炸板回封速度** | 炸板后 **10 分钟内**快速回封为高质量 | 【个别说法】<https://zhangtingke.com/longtougu> |
| **撤单稳定性** | 封板后 30 分钟内撤单 ≤3 次为稳定；撤单率 >30% 需警惕 | 【多数口径】<https://ag.yueniuzq.com/market-review/how-to-judge-limit-up-seal-quality-in-review/>、<https://ag.yueniuzq.com/market-review/judge-next-day-sell-pressure-from-limit-up-orders/> |
| **尾盘封单变化** | 收盘封单 > 开盘封单为佳；尾盘 30 分钟封单减少 >50% 或开板 → 次日低开概率高 | 【多数口径】同上 |
| **复合涨停强度因子** | `strength = (封单金额/成交额) × (1/封板时间分钟数)`；早盘 30 分钟内涨停且封单 >日均成交额 20% 视为强共识 | 【个别说法】<https://codechina.net/article/weixin_42557537/21048> |

> **重要反例**：乔帮主明确说过 **「早盘板不一定比尾盘板好……说明啥，题材是王道，不是封板时间」**（<https://www.xiarj.com/26026.html>）。顶级游资本人否定「封板时间」这条被广泛传播的规则，说明这类阈值的适用性是条件性的。

### 2.4 换手率、成交额、量比

| 项 | 常见阈值区间 | 共识度 / 来源 |
| --- | --- | --- |
| **龙头日常换手率** | **10%-30%** 为健康区间 | 【广泛共识】<https://vcai.cn/index.php/celue-ticaitouji-4/>、<https://ag.yueniuzq.com/market-review/identify-sustainable-sector-leader/>、<https://blog.cifangquant.com/post/104.html> |
| **启动日换手** | >15% 为佳（vcai/东财）；首板 5%-15%（选股清单）；首板 5%-10%（筹码视角） | 【多数口径，数值分歧】<https://caifuhao.eastmoney.com/news/20260601220731106036770>、<http://caijing.cn99.net.cn/article-215995-1.html>、<https://ag.yueniuzq.com/market-review/calculate-upward-throwing-pressure-of-bottom-first/> |
| **死亡换手** | >50% 需警惕；卖出信号为小盘 >50% / 大盘 >70% | 【多数口径】<https://ag.yueniuzq.com/market-review/identify-sustainable-sector-leader/>、<https://blog.cifangquant.com/post/104.html> |
| **换手率演变路径** | **低换手启动 → 高换手分歧 → 低换手加速** | 【广泛共识】<https://zhangtingke.com/longtougu>；20cm 时代尤其强调「涨停充分换手」（<http://www.10huang.cn/zhangting/42938_all.html>） |
| **半路买点换手门槛** | 当日换手 ≥ 前 5 日平均换手的 **80%** | 【个别说法】<https://vcai.cn/index.php/celue-ticaitouji-4/> |
| **打板换手门槛** | 当日换手 ≥ 前 5 日平均换手的 **100%**；缩量一字板/秒板不打 | 【个别说法】同上 |
| **趋势龙成交额** | 日均 ≥10 亿 | 【多数口径】<https://vcai.cn/index.php/celue-ticaitouji-4/>、<https://vcai.cn/index.php/celue-ticaitouji-10/> |
| **量比** | 集合竞价量比 >1.5 作为介入确认 | 【个别说法】<http://www.gspt.com/gs/16598> |
| **首阴量能** | 为前一日涨停量的 **80%-120%**（温和放量）；缩量 20% 以内为机会型；放量翻倍/换手 >30% 为陷阱型 | 【多数口径】<https://xueqiu.com/2801102342/370428778>、<https://www.163.com/dy/article/KI3OT2AG0553AF6B.html> |

### 2.5 题材地位与板块带动性

| 项 | 常见阈值区间 | 共识度 / 来源 |
| --- | --- | --- |
| **是否题材第一个涨停** | 时间龙的定义就是「题材爆发日第一个涨停」；先手龙有身位优势、抛压最小 | 【广泛共识】<https://caifuhao.eastmoney.com/news/20230928154127665655390> |
| **带动性量化** | 龙头涨停后，板块内**跟风股上涨超 5% 的数量 ≥3 只** | 【个别说法但可直接落地】<https://zhangtingke.com/longtougu> |
| **题材容量** | 5-10 只概念股联动（或 5-8 只），高潮期至少 3 只封板 | 【多数口径】<https://caifuhao.eastmoney.com/news/20260601220731106036770>、<https://finance.sina.com.cn/roll/2025-06-15/doc-infaczmh1890634.shtml> |
| **板块共振因子** | `resonance = 板块内涨停家数 / 板块总家数`，建议用申万三级行业、剔除 ST 与次新 | 【个别说法】<https://codechina.net/article/weixin_42557537/21048> |
| **板块效应评分** | 所属板块当日 ≥3 只涨停记满分 | 【个别说法】<https://ag.yueniuzq.com/market-review/evaluate-limit-up-seal-quality-in-review/> |
| **题材正宗性** | 主营直接受益、营收占比高，非蹭概念 | 【广泛共识】多来源 |

### 2.6 人气指标

| 项 | 口径 | 共识度 / 来源 |
| --- | --- | --- |
| **龙虎榜合力** | 多机构/知名游资**联合买入**（而非独食）为强化信号 | 【多数口径】<https://ag.yueniuzq.com/market-review/identify-sustainable-sector-leader/>、<https://zhangtingke.com/longtougu> |
| **龙虎榜披露门槛** | 仅涨跌幅偏离值达 7% **或**换手率 >20% 的个股上榜 — **未上榜的涨停股无法用席位验证** | 【事实性约束】<https://ag.yueniuzq.com/market-review/judge-next-day-sell-pressure-from-limit-up-orders/> |
| **开盘啦人气** | 人气榜、板块强度、复盘啦涨停天梯、特色标签（人气核心/人气激增/最正宗/机构增仓） | 【产品事实】<https://www.kaipanla.com/article/39810>、<https://app.mi.com/details?id=com.aiyu.kaipanla> |
| **竞价委买额** | 打板 → 竞价 → 涨停委买额；9:15 集合竞价起含隔夜单，可按金额排序 | 【产品事实】<https://m.87g.com/az/218978.html> |
| **资金承接力** | 高位分歧时不跳水、下跌时有强劲承接盘 | 【广泛共识】<https://zhangtingke.com/longtougu> |

> **未找到可靠来源**：股吧热度、雪球讨论量等社交热度指标的**具体数值阈值**（如「热度排名进前 N」）。检索到的资料只做定性描述，没有可复现的量化口径。

---

## 3. 龙头的生命周期分期

### 3.1 两套并行的分期，要分清

市场上「周期」有两层，经常被混为一谈：

- **市场情绪周期**（大盘级）：冰点 → 启动 → 发酵 → 高潮 → 分歧 → 退潮
- **个股龙头生命周期**：启动 → 确认 → 主升 → 分歧 → 反包 → 见顶 → 退潮

两者共振但不等同（<https://vcai.cn/index.php/celue-ticaitouji-3/>）。章盟主的版本更简：初生期 → 加速期 → 休整期 → 衰退期（<https://caifuhao.eastmoney.com/news/20190610153336058612360>）。

### 3.2 市场情绪周期的可观测指标表【本报告最可直接落地的一张表】

来源：<https://vcai.cn/index.php/celue-ticaitouji-3/>（原文注明「阈值来自历史数据统计，受宏观及政策影响需随环境更新」）

| 核心指标 | 冰点期 | 启动期 | 发酵期 | 高潮期 | 分歧期 | 退潮期 |
| --- | --- | --- | --- | --- | --- | --- |
| 连板高度 | 2-3 板 | 3-5 板 | 5-7 板 | 7 板以上 | 断板 / 7 板内下降 | 3 板以内 |
| 涨停跌停比 | <1 | >2 | >3 | >5 | 1~2 | <1 |
| 炸板率 | >40% | 30~40% | 20~30% | <20% | 30~40% | >40% |
| 涨跌数比 | <0.3 | 0.5~1 | 1~2 | >2 | 0.5~1 | <0.3 |
| 涨停数 | <10 | 40~50 | 50~60 | >60 | 30~40 | 10~30 |
| 跌停数 | ≥20 | ≤10 | ≤10 | ≤10 | 10~20 | ≥30 |
| 昨日涨停晋级率 | ≤20% | 20~30% | 30~40% | ≥50% | 20~30% | ≤25% |
| 昨日涨停平均涨幅 | <0% | >2% | 3~5% | >5% | 0~2% | <-2% |
| 核心锚定标的 | 无龙头，全是杂毛 | 新题材龙头出现 | 龙头连板带动板块 | 龙头超预期连板 | 龙头断板，板块分化 | 龙头见顶跌停，板块崩溃 |

⚠️ 这张表的绝对数（涨停数 >60 等）明显对应 2020-2023 年生态。在 2026 年连板高度普遍 2-3 板的环境下（§6），「连板高度」行需要整体下移，否则会长期判定为「冰点」。**建议落地时改用分位数而非绝对值**。

### 3.3 各阶段：龙头个股特征 + 操作含义

| 阶段 | 龙头可观测特征 | 量能 / 涨停形态 | 跟风与板块效应 | 操作含义（原文口径） |
| --- | --- | --- | --- | --- |
| **启动** | 题材爆发日最早涨停、封单坚决；打破前期连板高度限制 | 换手涨停优于一字；放量 | 板块涨停 10-15 家，梯队初成 | 轻仓试错新题材龙头，仓位 3-5 成；错了立刻止损 |
| **确认 / 发酵** | **分歧转一致**（分歧时抗跌甚至逆势涨停，之后率先涨停）；带动性确认；走出板块最高连板 | 连板高度打开到 5-7 板 | 跟风股上涨 >5% 的 ≥3 只；梯队完整 | **胜率最高阶段**：龙头半路、换手板、中军低吸；仓位 5-7 成 |
| **主升 / 高潮** | 龙头**缩量加速**、超预期连板；沿 5/10 日线不破 | 炸板率 <20%；缩量一字或加速板 | 板块每天 30+ 家涨停，闭眼买都赚 | 持股待涨，仓位 7-8 成；可分批止盈但不全卖飞 |
| **分歧** | 龙头断板或大幅波动，但**依然抗跌**、无连续下跌；板块内部高低切换 | 炸板率飙升 >40%；跌停家数增加 | 高位股跌、低位补涨股涨 | 降仓到 3-5 成；只做龙头分歧低吸/尾盘低吸、低位补涨首板；**绝不追高打高位板** |
| **反包 / 首阴** | 断板后 1-3 个交易日内再次涨停 | 首阴量能温和（前日涨停量 80%-120%）；收盘在 5 日线上 | 板块情绪未崩 | 「龙头最后一跳」，随后往往正式回落；<http://www.10huang.cn/zhangting/39480.html> |
| **龙回头 / 反抽** | 退潮一段时间后借题材余热回光返照，常发生在 5/10/20 均线附近 | 回调 15%-30%、3-10 日、缩量；再启动需放量阳线 | 需要「没有新题材或新题材有重大不确定性」，资金回流老题材 | 低吸博二波；止损设支撑位下方 3%-5% |
| **见顶 / 退潮** | 高位放量滞涨、长上影/墓碑线；带动性消失；跌破核心均线 | 炸板率 >50%，打板即天地板 | 跟风股**先于龙头补跌** | 无条件清仓；反弹就是离场机会 |

来源：<https://vcai.cn/index.php/celue-ticaitouji-3/>、<https://vcai.cn/index.php/celue-ticaitouji-4/>、<https://zhangtingke.com/longtougu>、<http://www.10huang.cn/zhangting/39480.html>、<https://ag.yueniuzq.com/market-review/review-ebb-process-of-popular-sector/>

### 3.4 退潮的传导顺序【广泛共识，很有用】

约投顾给出的三阶段传导：**① 龙头放量滞涨或炸板 → ② 跟风股提前补跌（往往比龙头下跌更早、幅度更大）→ ③ 板块指数跌破关键均线**（<https://ag.yueniuzq.com/market-review/review-ebb-process-of-popular-sector/>）。

「跟风先于龙头补跌」是可以直接做成盘中预警的领先信号。

---

## 4.「龙头已死」的判定信号

### 4.1 分层：见顶 ≠ 死亡 ≠ 失去龙回头资格

三个概念严格递进，市面资料常混用：

**A. 见顶信号（该止盈了）** — 出现任意 2 个分批止盈，3 个以上无条件清仓（<https://vcai.cn/index.php/celue-ticaitouji-4/>）：

1. 高位放量滞涨（放巨量但股价不涨甚至下跌，收长上影）
2. 断板后无法反包（次日低开低走）
3. 有效跌破 10 日线且 3 个交易日内无法站回，甚至跌破 20 日线
4. **带动性消失**（龙头涨停板块不跟；龙头跌板块跟着大跌）
5. 情绪周期进入退潮期（哪怕龙头还没跌）
6. 出现大额减持/业绩暴雷/监管问询等利空

**B. 龙头死亡（身份终结）**：

| 判定 | 口径 | 来源 |
| --- | --- | --- |
| 章盟主口径（最严格、最可量化） | **跌破 5 日线的次日没有涨停 → 本波行情结束，基本确定龙头死亡** | <https://caifuhao.eastmoney.com/news/20190610153336058612360> |
| 拾荒网退潮口径 | 断板后次日不能再次涨停即「武断定义」已退潮；后续若仍能引领市场再修正。**非总龙头一旦退就基本是真的退了** | <http://www.10huang.cn/zhangting/39480.html> |
| 首阴跌停口径 | **断板首阴跌停即宣告被资金放弃、走势结束**；没有跌停的个股才保留反包希望 | <https://www.n8n8.cn/yanjiu/yuekan/detail/24/198.html> |
| 极端出货口径 | 高位跌停且封单成交额占流通市值 1% 以上 = 主力不计成本出货，后续大概率继续下挫 | <https://ag.yueniuzq.com/qa/long-tou-gu-jian-ding-qian-you-na-xie-xin-s2-94903/> |

**C. 失去「龙回头」资格（不再有二波价值）** — 综合各源，满足以下任一即取消资格：

| 条件 | 阈值 | 来源 |
| --- | --- | --- |
| **跌破启动位** | 跌破启动阳线最低价 | <https://blog.cifangquant.com/post/104.html> |
| **回调过深** | 回调 >30%（严格口径 >28%）说明龙头已走弱，不再是洗盘 | <https://caifuhao.eastmoney.com/news/20260323225813677394530>、[`dragon-return-screener.md`](../dragon-return-screener.md) |
| **调整时间过长** | 超过 10 个交易日「很难再次汇聚人气」 | <https://m.tgb.cn/a/2pdQagAaKg2>、<https://finance.sina.com.cn/roll/2025-06-26/doc-infcmcye4619814.shtml> |
| **放量破位** | 放量跌破 10/20 日线且 3-5 日内无法收复；「缩量企稳是洗盘，放量破位是终结」 | 【广泛共识】<https://ag.yueniuzq.com/market-review/differentiate-theme-cooling-or-washout/> |
| **断头铡刀** | 一根大阴线同时跌破 5/10/20 日均线 | <https://ag.yueniuzq.com/qa/long-tou-gu-jian-ding-qian-you-na-xie-xin-s2-94903/> |
| **连续放量下跌** | 连续 3 个交易日放量下跌或放量滞涨，且量能无法萎缩回常态 | 同上 |
| **市场已换新龙** | 新龙头出现、老龙头失去号召力 → 果断切换 | <https://blog.cifangquant.com/post/104.html> |
| **题材证伪/退潮** | 板块指数跌破 20/30/60 日线；跟风股连续补跌 | <https://ag.yueniuzq.com/market-review/review-ebb-process-of-popular-sector/> |
| **反弹无量** | 反弹力度弱、高点逐步降低（见顶特征），对比洗盘后能创新高 | <https://ag.yueniuzq.com/qa/long-tou-gu-jian-ding-qian-you-na-xie-xin-s2-94903/> |

### 4.2 一个值得注意的胜率数字【个别说法，未独立验证】

某自媒体宣称对龙头首阴做过统计：整体反包概率约 **45%**；满足「前期 ≥3 个涨停 + 首阴成交量不低于前日涨停量 + 首阴未跌破 5 日线」三条件时升至 **65% 以上**；而「放量暴跌超 8% + 跌破 10 日线 + 板块退潮」时不足 **15%**（<https://www.163.com/dy/article/KI3OT2AG0553AF6B.html>）。

⚠️ 该文未披露样本区间、样本量与「反包」定义，**不能作为参数依据**，仅可作为「首阴远非高胜率模式」的定性佐证——这与拾荒网「不成功的龙头首阴比成功的多得多」相互印证。

---

## 5. 游资流派差异

### 5.1 最简分类（一手媒体报道）

21 世纪经济报道 2020 年的行业观察给出了最干净的分野：**「有的擅长低位题材的挖掘，比如成都帮；有的偏爱高位打板，比如欢乐海岸；有的喜欢做强势股的低吸，比如乔帮主；有的善于打造大板块的波段运作，比如赵老哥。」**（<http://21jingji.com/article/20200809/herald/7ae3a9f25f8fdea37a86f508be5e5158.html>）

### 5.2 各家对「什么是龙头 / 怎么选龙头」的侧重点

| 游资 | 对「龙头」的核心主张 | 主打模式 | 关键出处 |
| --- | --- | --- | --- |
| **炒股养家** | 情绪周期的提出者。**「人气所向，牛股所在」「只做龙头不做杂毛」「龙头不死，行情不止」「高手买入龙头，超级高手卖出龙头」**。龙头是情绪与人气的产物，不是资金堆出来的 | **打板/低吸皆可，关键在阶段**：「追涨也好、低吸也好，问题不在模式，而在何种阶段应用，以及火候」 | <https://m.tgb.cn/a/2f0oRGfYwr4>、<https://caifuhao.eastmoney.com/news/20260320223426909144550>、<http://21jingji.com/article/20200809/herald/7ae3a9f25f8fdea37a86f508be5e5158.html> |
| **赵老哥** | **「二板定龙头，一板能看出来个毛」**；**「大龙头都是多点共振的结果」**；**「有新题材，坚决抛弃旧题材」**；「只做龙头，只做主升，只做惯性」 | **打板接力**，大板块波段运作 | <https://www.ttyfp.com/chaogu/3339.html>、<http://21jingji.com/article/20200809/herald/7ae3a9f25f8fdea37a86f508be5e5158.html> |
| **佛山无影脚**（廖国沛） | 龙头不是他关心的重点——他要的是**低位、有阻力释放、能被自己大单封死的首板**。「打板前日必须大阴线」，5000 万起步大单强封 | **只打低位首板，一日游，不接力不持股** | <https://m.tgb.cn/a/26FZy704Zqj>、<https://www.jiemiaobi.com/archives/25397> |
| **章盟主**（章建平） | 龙头有明确的**四周期生命**（初生/加速/休整/衰退）与 10 条选股原则：相对低位涨停启动、老鸭头形态、涨停突破年线/半年线/前高、多周期共振、启动前流通市值 3-60 亿 | **权重大票主升浪 + 妖股第二波**；波段为主，很少一日游，**很少参与第一波拉升**；有「善庄」之称 | <https://caifuhao.eastmoney.com/news/20190610153336058612360>、<https://www.163.com/dy/article/I8N29HFA05563524.html> |
| **方新侠** | 偏爱**多头排列的加速模式**（「这个模式能拿到筹码」）；**不太做接力**，若做接力也只做流通盘 200 亿以上的大票 | **大成交额趋势票 + 格局锁仓**，大开大合 | <https://www.163.com/dy/article/I8N29HFA05563524.html> |
| **乔帮主**（范羽） | **「题材是王道，不是封板时间」**；性价比来自「人气股 + 处在关键压力位、突破则一马平川」的预期差 | **强势股分歧低吸**：5 日线低吸、回踩 10 日线低吸、阳线+十字星；卖点 T+1，几乎不格局 | <https://www.jiemiaobi.com/archives/17728>、<https://www.jiemiaobi.com/archives/23471>、<https://www.xiarj.com/26026.html> |
| **作手新一** | 「围绕主线做强势股的核心不能变」，靠**研究涨停积累**认龙头 | **连板接力为主**（后期占交易比例 90%）；反包板；独创「排连续一字板的第三个涨停」；资金变大后转向流动性好的大票 | <https://www.55188.com/thread-14333736-1-1.html>、<https://siruidata.com/strategy/26.html>、<https://www.jiemian.com/article/3505520.html> |
| **欢乐海岸** | — | **高位打板 / 龙头锁仓** | <http://21jingji.com/article/20200809/herald/7ae3a9f25f8fdea37a86f508be5e5158.html> |
| **成都帮** | — | **低位题材挖掘**（超跌首板、快进快出） | 同上 |

### 5.3 打板派 vs 低吸派

| 派别 | 代表 | 龙头判定的侧重 |
| --- | --- | --- |
| **打板接力** | 赵老哥、作手新一、欢乐海岸、章盟主（高位接板） | 重**封板质量、身位、连板高度**；「二板定龙头」；靠涨停这个动作确认市场合力 |
| **低位首板一日游** | 佛山无影脚、成都帮 | 重**位置与筹码**（前日大阴、超跌、低位），基本不关心谁是龙头 |
| **强势股低吸** | 乔帮主 | 重**题材与均线支撑**（5/10 日线），弱化封板时间 |
| **趋势格局** | 方新侠、章盟主（主升浪）、作手新一（后期） | 重**多头排列、成交额容量、机构合力**，不做纯情绪接力 |

### 5.4 一个必须记住的证伪

乔帮主本人对「低吸鼻祖」这个标签的回应：**「我现在基本很少低吸了……只要是超短，任何位置我都有可能买入。最低点、红盘、绿盘、涨价，招无定式、水无常形，才是我的特点。」**他还明确说「牛市追涨和打板能保证稳定获利……熊市才是低吸发挥效应最强的市场」（<https://www.xiarj.com/26026.html>）。

**含义**：外界给游资贴的「流派」标签，很多是从某一段交割单归纳出的**阶段性画像**，不是稳定人格。把流派差异当作可移植的规则集使用，风险很高。

---

## 6. 2024-2026：环境变化对龙头定义的冲击【重要】

这是本次调研中最值得警惕的一节——**大量经典阈值的生成环境已经不在了**。

| 变化 | 具体表述 | 来源 |
| --- | --- | --- |
| **连板高度系统性压缩** | 注册制后普遍 5-7 板；主板 7 板停牌规则压制高度，5 板就容易分歧套现 | <https://vcai.cn/index.php/celue-ticaitouji-4/>、<https://www.sohu.com/a/977521490_121409661> |
| **趋势龙取代连板龙** | 「1-2 板启动 + 趋势拉升」成为主流；20cm 制度下 3 个 20cm ≈ 旧时 6 个 10cm | <https://www.sohu.com/a/977521490_121409661>、<https://vcai.cn/index.php/celue-ticaitouji-10/> |
| **龙头向中大市值迁移** | 小市值退市风险增加，量化与机构更青睐流动性好、基本面扎实的中大市值 | <https://www.sohu.com/a/977521490_121409661> |
| **必须机构+游资共振** | 纯游资炒作的无逻辑小题材持续性极差，多为一日游 | <https://vcai.cn/index.php/celue-ticaitouji-10/>、<https://www.sohu.com/a/977521490_121409661> |
| **量化围剿高标** | 量化「本能地围剿高标股」——连板会降低波动，不符合量化利益；量化主动制造轮动（当天批量买、次日高抛） | <https://quant.10jqka.com.cn/view/article/RU0WZ2AQ8A1562849HRFKOYPA0> |
| **题材当天就是高潮** | 「不要再等待龙头确立，必须在发酵当天就上车」 | 同上 |
| **游资集体转型** | 陈小群「退网」、流沙河发《人类操盘手向量化交易之降书》、96 余哥注销公众号；「传统的无脑打板模式将消亡，打板策略将高度机构化」 | <https://finance.sina.com.cn/jjxw/2026-04-12/doc-inhufzha5461856.shtml> |
| **打板策略降频与逻辑前置** | 「不能死守封板瞬间，更多在点火阶段或分歧转一致的过程中通过算法介入」；持仓周期从日内 T+0 式博弈向 2-5 日事件驱动迁移 | 同上 |
| **量化打板反噬** | 「量化低位抢完所有筹码，让我们三板四板去接力，很简单，我就不来了」 | <https://36kr.com/p/2192204555174277> |

> 关于「2026 一季度连板股数量同比下降 68%、连板高度降至 2-3 板、龙虎榜席位占比从 12% 降至 6.x%、趋势型操作占比从 35% 升至 62%」这组具体数字：来源为 <https://lianghuawang.com/h-nd-531.html>，本次两次抓取均超时，**未能独立核实，标记为【个别说法】，不建议引用**。趋势方向本身有新浪财经报道佐证。

---

## 7. 【核心交付】可量化的龙头判定 checklist 表

> 用法：先过 **A 组硬门槛**（不满足直接淘汰），再用 **B 组打分**排序，**C 组为否决项**（命中即出局）。
> 「本仓可算」一列基于对 `stock-analyzer` 现有数据层的盘点，详见 §8。

### A 组 · 硬门槛（题材与身份）

| # | 字段名 | 口径 / 公式 | 建议阈值 | 数据源类型 | 共识度 | 本仓可算 |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | `theme_limit_up_count` | 当日该题材内涨停家数 | ≥3（高潮期至少 3 只封板） | 涨停数据 + 题材库 | 广泛共识 | 需 MCP |
| A2 | `theme_capacity` | 题材内联动概念股数 | 5-10 只（过小无容量，过大不聚焦） | 题材库 | 多数口径 | 需 MCP |
| A3 | `is_first_limit_up_in_theme` | 是否为该题材当日第一个涨停 | True（时间龙判定） | 涨停数据（需封板时刻） | 广泛共识 | ❌ 需 MCP |
| A4 | `theme_rank_by_boards` | 题材内连板数排名 | 第 1（并列时看涨停时间→封单→流通盘小者） | 涨停数据 + 题材库 | 广泛共识 | 需 MCP |
| A5 | `is_st_or_new` | ST / 次新 / 停牌排除 | False | 日K + 标的表 | 工程惯例 | ✅ |
| A6 | `not_one_word_dominant` | 一字板占比（连板中） | <50%（一字堆高度筹码结构不健康） | 日K 派生（O=H=L=C） | 多数口径 | ✅ |

### B 组 · 打分维度

| # | 字段名 | 口径 / 公式 | 建议阈值区间 | 数据源类型 | 共识度 | 本仓可算 |
| --- | --- | --- | --- | --- | --- | --- |
| **B1** | `seal_ratio_float` | 封流比 = 收盘封单额 / 流通市值 | 主流档 >3% 极强、1%-3% 较强、<1% 偏弱；⚠️ 另有 >10%/3%-10%/<3% 与 >2% 两套口径；大盘股（>500 亿）0.5% 即算强 | 涨停数据（Level-1 买一挂单） | 多数口径**但阈值分歧大** | ❌ 需 MCP/L1 |
| **B2** | `seal_ratio_amount` | 封成比 = 封单额 / 当日成交额 | 30%-50% 以上为强；部分量化用 >10（倍） | 涨停数据 + 日K | 多数口径 | ❌ 需 MCP |
| **B3** | `first_seal_time` | 首次封板时刻 | ≤10:00（严格）／≤10:30（宽松）；>14:30 为偷袭板扣分 | 涨停数据（分钟级） | 广泛共识 | ❌ 需 MCP/分钟 |
| **B4** | `reseal_latency` | 炸板→回封耗时 | ≤10 分钟 | 分钟数据 | 个别说法 | ❌ 需分钟 |
| **B5** | `break_count` | 当日开板（炸板）次数 | 0 最佳；≤1 可接受 | 分钟数据 | 多数口径 | ❌ 需分钟 |
| **B6** | `limit_strength` | `(封单额/成交额) × (1/封板分钟数)` | 越大越强；早盘 30 分钟内封板且封单 >日均成交额 20% 视为强共识 | 涨停 + 日K + 分钟 | 个别说法 | ❌ |
| **B7** | `turnover_rate` | 当日换手率 | 健康 10%-30%；启动日 >15% 为佳；首板 5%-15% | 日K（`quotes_daily.turnover`） | 广泛共识 | ✅ |
| **B8** | `turnover_vs_ma5` | 当日换手 / 前 5 日平均换手 | 半路 ≥80%；打板 ≥100% | 日K | 个别说法 | ✅ |
| **B9** | `volume_ratio` | 量比 = 成交量 / MA(成交量,20) | >1.5（竞价口径）；启动放量 2 倍+ | 日K | 个别说法 | ✅ |
| **B10** | `amount_share_in_theme` | 个股成交额 / 板块总成交额 | 无公开阈值 — **未找到可靠来源** | 日K + 题材库 | — | 需题材成分 |
| **B11** | `consecutive_boards` | 连板数 | 总龙头多从 4 板起步；板块龙常见顶部 4-5 板；⚠️ 2026 环境下需下调 | 涨停数据（或日K 派生） | 广泛共识 | ⚠️ 日K 可近似 |
| **B12** | `follower_count_5pct` | 龙头涨停当日，板块内涨幅 >5% 的跟风股数量 | ≥3 | 日K + 题材成分 | 个别说法但易落地 | 需题材成分 |
| **B13** | `sector_resonance` | 板块内涨停家数 / 板块总家数 | 越高越强（无固定阈值） | 涨停 + 题材库 | 个别说法 | 需 MCP |
| **B14** | `above_ma5 / above_ma10` | 收盘价相对 5/10 日线 | 主升期不破 10 日线；趋势龙不破 10/20 日线 | 日K | 广泛共识 | ✅ |
| **B15** | `dist_from_prior_high` | 距前高距离 / 是否突破平台 | 突破大平台或创新高为佳；上方套牢峰越远越好 | 日K | 多数口径 | ✅ |
| **B16** | `daily_amount` | 日均成交额（趋势龙门槛） | ≥10 亿 | 日K（`amount`） | 多数口径 | ✅ |
| **B17** | `lhb_joint_buy` | 龙虎榜是否多知名游资/机构联合买入 | 联合买入=强化；独食/一日游席位=减分。⚠️ 仅偏离 7% 或换手 >20% 才上榜 | 龙虎榜 | 多数口径 | ❌ 需 MCP |
| **B18** | `auction_limit_buy_amount` | 竞价涨停委买额（9:15 起含隔夜单） | 排名越前越强（无绝对阈值） | 竞价数据 | 产品事实 | ❌ 需 MCP |
| **B19** | `popularity_rank` | 开盘啦人气排名 / 板块强度 | 排名越前越强 | 第三方人气榜 | 产品事实 | ❌ |
| **B20** | `main_net_inflow` | 主力净流入（日频四档） | 为正且持续；无公开阈值 | 资金流 | 多数口径 | ⚠️ 可拉取不落库 |

### C 组 · 否决项（命中即出局 / 强制降级）

| # | 字段名 | 口径 | 触发阈值 | 数据源 | 共识度 | 本仓可算 |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | `death_cross_ma5_no_limit` | 跌破 5 日线的次日是否涨停 | 未涨停 → 判定死亡（章盟主口径） | 日K | 个别说法但最可量化 | ✅ |
| C2 | `broke_ma10_3d` | 有效跌破 10 日线且 3 日内未站回 | True → 见顶 | 日K | 广泛共识 | ✅ |
| C3 | `guillotine` | 一根大阴线同时跌破 5/10/20 均线 | True → 转弱 | 日K | 多数口径 | ✅ |
| C4 | `vol_up_price_down_3d` | 连续 3 日放量下跌 / 放量滞涨 | True → 见顶概率高 | 日K | 广泛共识 | ✅ |
| C5 | `below_launch_low` | 跌破启动阳线最低价 | True → 失去龙回头资格 | 日K | 多数口径 | ✅ |
| C6 | `drawdown_from_peak` | 自最高收盘的回撤 | >30%（严格 >28%）→ 出局 | 日K | 多数口径 | ✅ |
| C7 | `pullback_days` | 回调交易日数 | >10 日 → 人气难聚，出局 | 日K | 广泛共识 | ✅ |
| C8 | `first_yin_limit_down` | 断板首阴是否跌停 | 跌停 → 宣告结束，不参与 | 日K | 多数口径 | ✅ |
| C9 | `first_yin_drop` | 首阴实体跌幅 | 3%-7% 为分歧；>8% 为溃败 | 日K | 多数口径 | ✅ |
| C10 | `leadership_lost` | 龙头涨停但板块不跟 / 龙头跌板块大跌 | True → 带动性消失 | 日K + 题材成分 | 广泛共识 | 需题材成分 |
| C11 | `theme_index_broke` | 板块指数跌破 20/30/60 日线 | True → 板块退潮 | 题材指数 | 多数口径 | ❌ |
| C12 | `emotion_ebb` | 情绪周期处于退潮期（炸板率 >40%、跌停 ≥30 家） | True → 一律不参与 | 涨停/情绪统计 | 广泛共识 | ⚠️ 需 MCP |
| C13 | `new_dragon_emerged` | 市场已出现新龙头 | True → 切换 | 涨停 + 题材 | 广泛共识 | 需 MCP |

---

## 8. 数据可得性映射：哪些算得出，哪些算不出

> 基于对 `stock-analyzer` 现有数据层的盘点（`src/market/infrastructure/store_schema.py`、`src/formula/domain/board.py`、`src/market/infrastructure/adapters/`、`src/market/infrastructure/tape/`）。

### 8.1 四类数据的实际状态

| 数据类别 | 本仓状态 | 落点 | 缺什么 |
| --- | --- | --- | --- |
| **日K** | ✅ **一等公民** | `market.db` 表 `quotes_daily`（`open/high/low/close/volume/amount/outstanding_share/turnover`）+ `adjust_factors`（后复权因子） | 无重大缺口；MA/量比/区间涨幅需即时计算（无预存列） |
| **涨停数据** | ⚠️ **部分：可派生，但微观结构缺失** | `src/formula/domain/board.py` 的 `limit_up_flags` / `one_word_flags` / `ZTPRICE` 从 OHLC 派生；实时口径走 tape lane `limit_up_pool` / `broken_limit_up` / `market_emotion`（悟道 MCP），缓存在 `intel_snapshots`（JSON blob，非类型化列） | **无持久化字段**：封单额、封板时刻、开板次数、涨停原因、连板数历史表 |
| **板块题材** | ⚠️ **部分** | 本地：`instruments.board` / `instruments.industry`（行业投影，标记 `local_industry_derived`）；实时：tape lane `theme_board` / `theme_members`（悟道 KPL 题材） | **无持久化的概念成分表**，更无成分的历史版本（做回测会有幸存者/回填偏差） |
| **资金流** | ⚠️ **只取不存** | `EastmoneyAdapter.fetch_capital_flow`（akshare `stock_individual_fund_flow`）→ `main_net_inflow` / `super_large_net_inflow` / `large_*` / `medium_*` / `small_*` | **无 `capital_flow` 表**，无历史；板块资金无本地历史 |
| **龙虎榜** | ❌ **无** | 仅 intel 收盘配方的 `dragon_tiger` 工具 blob | 全部缺失 |
| **竞价** | ❌ **无本地表** | tape lane `auction_snapshot`（悟道） | 竞价委买额无本地历史 |
| **分钟** | ❌ **不落库** | fetch-only（tdx 仅 `datetime/close/volume`；eastmoney 有 OHLC+amount） | 封板时刻、炸板次数、分时承接全部无法离线回算 |

### 8.2 「只有日K + 涨停数据 + 板块题材 + 资金流」能算什么

**✅ 完全能算（纯日K 即可）**

区间涨幅、MA5/10/20/60、量比、换手率与换手演变、涨停/一字板（OHLC 派生）、连板数（连续涨停计数）、距前高距离、平台突破、自峰值回撤、回调天数、放量下跌/放量滞涨、断头铡刀、跌破启动阳线低点、首阴实体跌幅与是否跌停、成交额门槛、跌破 5 日线次日是否涨停。

→ 对应 checklist：**A5、A6、B7、B8、B9、B14、B15、B16、C1–C9 全部**。

**✅ 加上题材成分即可算**

板块内涨停家数、跟风股 >5% 数量、板块共振比、题材内连板排名、带动性消失判定。

→ 对应：**A1、A2、A4、B10、B12、B13、C10**。前提是拿到**当时点**的成分快照，不能用今天的标签回填历史。

**✅ 加上日频资金流即可算**

主力净流入方向与持续性。→ **B20**（但无历史，只能实时用）。

**❌ 算不出来 — 需要替代方案**

| 算不出的指标 | 为什么 | 建议替代 |
| --- | --- | --- |
| **封流比 / 封成比**（B1、B2） | 需要收盘时买一挂单额，日K 无此信息 | ①实时用悟道 MCP `limit_up_ladder` 等返回的封单字段；②离线退化为 `是否一字板`（O=H=L=C）+ `成交额/流通市值`（反向代理：一字且极低换手 ≈ 强封单） |
| **封板时刻**（B3） | 需分钟或 tick | ①实时 MCP；②离线用 `(close-open)/open` 接近涨停幅 + 极小 `(high-low)` 近似「早盘封板」，**这是弱代理，需标注不确定性** |
| **炸板次数、回封耗时**（B4、B5） | 需分钟 | ①离线可判「触板未封」：`high == 涨停价 且 close < 涨停价`（这是 `broken` 的日K 代理，已有 tape local_provider 采用同思路）；②次数无法还原 |
| **复合涨停强度**（B6） | 依赖 B1+B3 | 用 `一字板 + 换手率倒数` 做粗排序，标注为代理 |
| **龙虎榜席位合力**（B17） | 无数据；且 7%偏离/20%换手 才上榜，本身覆盖不全 | ①实时 MCP `dragon_tiger`；②**结构性替代**：用「大单净额/主力净流入 + 次日溢价」代理资金性质，不要假装能识别具体游资 |
| **竞价委买额**（B18） | 无本地竞价数据 | 实时 MCP `auction_market_scan`（`sortBy=limitBuyAmount`）；离线用「次日开盘涨幅」做**事后**代理（不可用于当日决策） |
| **人气排名**（B19） | 第三方产品指标 | 代理：`成交额全市场分位` + `换手率分位` + `振幅分位` 的合成排名。**注意这是自造指标，不等于开盘啦人气榜** |
| **题材指数均线**（C11） | 无题材指数 | 用题材成分股等权收益序列自建指数，标注为自建 |
| **市场情绪周期阶段**（C12） | 需全市场涨停/跌停/炸板率统计 | ①实时 MCP `short_term_emotion` / `limit_stats`；②离线可从全市场日K 派生涨停家数、跌停家数、昨日涨停晋级率、昨日涨停平均涨幅（这四项**日K 可算**），但**炸板率算不准**（需要「触板未封」，日K 只能近似） |

### 8.3 一条必须写死的工程约束

**「带动性」不能用未来收益伪装成当日事实。** 龙头是否真的带动板块，日线数据只能证明**同步共振**，不能证明**因果带动**。建议字段分两个：

- `co_move`（T 日同步共振，可用于当日信号）
- `follow_through`（T+1 确认，**只能做研究标签，不能倒灌进 T 日买入逻辑**）

这一点与 [`dragon-leader-identification.md`](dragon-leader-identification.md) §3 的结论完全一致。

---

## 9. 共识 vs 分歧总览

### 9.1 广泛共识（可以放心当作行业惯例）

1. 龙头 = 带动性 + 辨识度 + 抗跌性；**没有带动性就不是龙头**。
2. 「二板定龙头」——首板看不出，需要晋级验证。
3. 换手率健康区间 10%-30%；换手演变路径「低换手启动 → 高换手分歧 → 低换手加速」。
4. 早盘封板优于尾盘封板（但乔帮主明确反对，见 §2.3 反例）。
5. 「买在分歧，卖在一致」——分歧 = 爆量炸板/烂板/冲高回落**且收红盘**；一致 = 连续缩量加速或板块连续大面积涨停。
6. 情绪周期六阶段划分，以及「退潮期空仓是唯一正确操作」。
7. 龙回头回调时间 3-10 日、理想 5-7 日；「缩量企稳是洗盘，放量破位是终结」。
8. 退潮传导顺序：龙头滞涨/炸板 → 跟风先补跌 → 板块指数破位。
9. 「不成功的龙头首阴远多于成功的」；龙头模式整体是低频高赔率，不是高胜率。

### 9.2 明确存在分歧（落地必须先选定口径）

| 分歧点 | 冲突口径 |
| --- | --- |
| 封流比阈值 | >3% / >10% / >2% / 0.8%-2%（首板）四套并存 |
| 启动市值 | 3-60 亿 / 30-100 亿 / 50-200 亿 / 50-500 亿 |
| 封板时间是否重要 | 主流认为重要；乔帮主认为「题材是王道，不是封板时间」 |
| 总龙头是否等于最高板 | 涨停客/vcai 倾向是；拾荒网明确说这个看法「片面」 |
| 空间龙与人气龙 | 多数资料混用；开普饭明确区分（尖顶 vs 双顶/两波） |
| 首阴是否值得做 | 战法派给出 65% 高胜率场景；拾荒网称多数是事后看图 |
| 龙回头回调幅度 | 20%-30% / 15%-30% / 8%-28% |

### 9.3 未找到可靠来源

- 「20 日涨幅 ≥ X%」作为龙头**定义**的权威出处（只找到作为过滤条件的用法）。
- 股吧热度、雪球讨论量的具体量化阈值。
- 「成交额占板块比」的公开阈值。
- 竞价委买额的绝对金额门槛（只有相对排名口径）。
- 2026 年连板生态的**可核实**统计数字（趋势有媒体报道，精确数字来源未能验证）。

---

## 10. 局限与使用边界

1. **本文是术语与惯例综述，不是策略验证。** 所有阈值均未在本仓做样本外回测。
2. **来源质量参差。** 一手材料（游资本人语录、交易所规则、媒体报道）与二手整理（自媒体归纳、AI 生成的「完整版心法」）混杂。凡标注【个别说法】的均为后者。
3. **严重的幸存者偏差与事后归因。** 所有案例（圣龙股份、剑桥科技、捷荣技术、浙江建投）都是成功案例的反向叙述，失败样本从不出现在这类文章里。
4. **阈值有时代性。** §6 已说明，2020-2023 生成的阈值在 2026 年环境下大概率需要重标定。
5. **不构成投资建议。** 落生产前须走本仓既有流程：预注册参数 → 训练/验证/样本外分段 → 涨跌停可成交性建模 → 与基线对比。参见 [`dragon-leader-identification.md`](dragon-leader-identification.md) 的「回测与反证要求」。

---

## 11. 来源清单

### 体系性教程 / 知识树

- 小V学投资 第三章 情绪周期（含 6 阶段 × 8 指标表）：<https://vcai.cn/index.php/celue-ticaitouji-3/>
- 小V学投资 第四章 龙头战法体系（分类表、5 大基因、6 大见顶信号、趋势龙）：<https://vcai.cn/index.php/celue-ticaitouji-4/>
- 小V学投资 第十章 注册制下新玩法：<https://vcai.cn/index.php/celue-ticaitouji-10/>
- 涨停客 龙头股知识树：<https://zhangtingke.com/longtougu>
- 开普饭《龙头股情绪周期教程》全集总序：<https://www.kpfans.com/article/PxWD7Ozb9n.html>
- 开普饭 人气龙与空间龙的区别：<https://www.kpfans.com/article/wLWoo3ynWj.html>
- 次方量化 短线/龙头/趋势战法（含连板龙 vs 趋势龙对比表）：<https://blog.cifangquant.com/post/104.html>

### 分类与术语

- 55188 龙头股种类及属性特征详解（8 类）：<https://www.55188.com/thread-10228179-1-1.html>
- 55188 个股地位揭秘（一字龙/日内龙/卡位龙/补涨龙）：<https://www.55188.com/thread-11956376-1-1.html>
- 东方财富 龙头战法：什么是龙头？龙头分几种（10 类）：<https://caifuhao.eastmoney.com/news/20230928154127665655390>
- 拾荒网 龙头战法打板常用术语解释：<http://www.10huang.cn/zhangting/46556.html>
- 拾荒网 最高板（空间板）和核心板的逻辑：<http://www.10huang.cn/zhangting/49164.html>
- 东方财富 什么是龙头/卡位/助攻/中军：<https://caifuhao.eastmoney.com/news/20241002144328309940970>

### 识别标准与阈值

- 东方财富 超短线龙头战法选股逻辑（8 大识别标准）：<https://caifuhao.eastmoney.com/news/20260601220731106036770>
- 约投顾 涨停板复盘中的封单质量怎么判断：<https://ag.yueniuzq.com/market-review/how-to-judge-limit-up-seal-quality-in-review/>
- 约投顾 封单结构测算次日抛压与溢价：<https://ag.yueniuzq.com/market-review/calculate-next-day-throwing-pressure-via-limit-up/>
- 约投顾 涨停封板质量的复盘评估指标（10 分制评分）：<https://ag.yueniuzq.com/market-review/evaluate-limit-up-seal-quality-in-review/>
- 约投顾 从涨停封单质量预判次日出货压力（含龙虎榜披露门槛）：<https://ag.yueniuzq.com/market-review/judge-next-day-sell-pressure-from-limit-up-orders/>
- 约投顾 如何识别题材持续性强的板块龙头：<https://ag.yueniuzq.com/market-review/identify-sustainable-sector-leader/>
- 约投顾 底部首板放量突破的抛压测算：<https://ag.yueniuzq.com/market-review/calculate-upward-throwing-pressure-of-bottom-first/>
- 约投顾 龙头股启动初期的移动成本分布特征：<https://ag.yueniuzq.com/qa/ru-he-cong-pan-mian-shi-bie-long-tou-gu-q-s2-75667/>
- 会计百科 封流比词条：<https://baike.kuaiji.com/v134915079.html>
- 圆梦财经 行情初期选龙头板块龙头股（首板 6 硬标准）：<http://caijing.cn99.net.cn/article-215995-1.html>
- 代码聚汇 龙头战法量化模型：核心因子构建与 Python 实现：<https://codechina.net/article/weixin_42557537/21048>
- 拾荒网 20cm 注册制下龙头战法核心心法：<http://www.10huang.cn/zhangting/42938_all.html>
- logic88 突破低位单峰密集（筹码公式）：<https://www.logic88.cn/40741.html>

### 生命周期 / 首阴 / 龙回头 / 死亡信号

- 拾荒网 怎么看龙头首阴、龙头反包、龙头二波（首阴/退潮/反包/反抽/二波定义）：<http://www.10huang.cn/zhangting/39480.html>
- 经传多赢 龙头战法（首阴+龙回头）：<https://www.n8n8.cn/yanjiu/yuekan/detail/24/198.html>
- 淘股吧 扶摇破浪 龙回头战法详解：<https://m.tgb.cn/a/2hqZCPSKPnz>
- 淘股吧 退学炒A股 短线龙回头技巧：<https://m.tgb.cn/a/2pdQagAaKg2>
- 东方财富 龙回头战法深度解析：<https://caifuhao.eastmoney.com/news/20260323225813677394530>
- 天云复盘 龙回头战法（通达信公式）：<https://www.ttyfp.com/pdf/36220.html>
- 新浪财经 详细解析「龙回头形态」的实战用法：<https://finance.sina.com.cn/roll/2025-06-26/doc-infcmcye4619814.shtml>
- 新浪财经 龙头股首阴战法：<https://finance.sina.com.cn/roll/2025-06-15/doc-infaczmh1890634.shtml>
- 雪球 龙头首阴战法全解析：<https://xueqiu.com/2801102342/370428778>
- 网易 「龙头首阴」是机会还是陷阱（自称量化统计）：<https://www.163.com/dy/article/KI3OT2AG0553AF6B.html>
- 炒股1688 龙头首阴战法详解（选股公式）：<https://www.chaogu1688.com/17907.html>
- 约投顾 龙头股见顶前的常见信号：<https://ag.yueniuzq.com/qa/long-tou-gu-jian-ding-qian-you-na-xie-xin-s2-94903/>
- 约投顾 复盘板块龙头的生命力与潜在见顶信号：<https://ag.yueniuzq.com/market-review/review-sector-leader-lifespan-and-top-signals/>
- 约投顾 如何复盘热门板块的退潮过程：<https://ag.yueniuzq.com/market-review/review-ebb-process-of-popular-sector/>
- 约投顾 热点降温是终结还是中途洗盘：<https://ag.yueniuzq.com/market-review/differentiate-theme-cooling-or-washout/>
- CSDN 淘股吧米开朗基瑞 情绪周期与节点转换（阶段论）：<https://blog.csdn.net/okmacong/article/details/161766545>

### 游资流派

- 21 世纪经济报道《暴利与血亏：游资的打板江湖》（一手媒体，各派分野）：<http://21jingji.com/article/20200809/herald/7ae3a9f25f8fdea37a86f508be5e5158.html>
- 天云复盘 赵老哥养家心法等顶级游资心法：<https://www.ttyfp.com/chaogu/3339.html>
- 淘股吧 炒股养家「买在分歧、卖在一致」：<https://m.tgb.cn/a/2f0oRGfYwr4>
- 淘股吧 游资炒股养家情绪周期龙头战法：<https://www.tgb.cn/a/2tdwA6fbQYa>
- 东方财富 炒股养家心法（完整版）：<https://caifuhao.eastmoney.com/news/20260320223426909144550>
- 网易 炒股养家做短线仅有一句话：<https://www.163.com/dy/article/JIR6G6PK0553GD76.html>
- 东方财富 章盟主传下：龙头战法 14 要点（四周期 + 10 原则）：<https://caifuhao.eastmoney.com/news/20190610153336058612360>
- 东方财富 章盟主炒股核心特点（2026 整理，二手）：<https://caifuhao.eastmoney.com/news/20260320044417356732630>
- 网易 中国顶级游资风格一览（章盟主/方新侠等）：<https://www.163.com/dy/article/I8N29HFA05563524.html>
- 淘股吧 佛山无影脚打板手法特点总结：<https://m.tgb.cn/a/26FZy704Zqj>
- 皆妙笔 终生成就奖老牌游资佛山无影脚：<https://www.jiemiaobi.com/archives/25397>
- 皆妙笔 低吸鼻祖乔帮主语录及交割单：<https://www.jiemiaobi.com/archives/17728>
- 皆妙笔 龙头战法之乔帮主（上）：<https://www.jiemiaobi.com/archives/23471>
- 闽发论坛 乔帮主语录汇编（含「题材是王道，不是封板时间」）：<https://www.xiarj.com/26026.html>
- 55188 作手新一的交易体系：<https://www.55188.com/thread-14333736-1-1.html>
- 思瑞游资笔记 作手新一交易策略总结：<https://siruidata.com/strategy/26.html>
- 界面新闻 7 年 1000 倍收益，80 后游资「作手新一」如何操盘：<https://www.jiemian.com/article/3505520.html>
- 东方财富 12 位知名游资大佬核心信息：<https://caifuhao.eastmoney.com/news/20251124111830695565100>

### 2024-2026 环境变化

- 搜狐《「龙头战法」失效了吗？拆解新旧周期下龙头股的四大演变特征》：<https://www.sohu.com/a/977521490_121409661>
- 同花顺量化社区《读懂量化时代：从跟庄、打板到与 AI 共舞》：<https://quant.10jqka.com.cn/view/article/RU0WZ2AQ8A1562849HRFKOYPA0>
- 新浪财经《陈小群「退网」、流沙河「投降」……打板策略迭代与重构》（2026-04-12）：<https://finance.sina.com.cn/jjxw/2026-04-12/doc-inhufzha5461856.shtml>
- 36 氪《量化打板「生死劫」》：<https://36kr.com/p/2192204555174277>
- ⚠️ 量化网《顶级游资的量化转型》（含 2026 一季度统计数字，**本次抓取超时，未能核实**）：<https://lianghuawang.com/h-nd-531.html>

### 工具与产品事实

- 开盘啦 如何用「开盘啦」看懂每一轮行情：<https://www.kaipanla.com/article/39810>
- 开盘啦 小米应用商店页（功能与游资标签组合）：<https://app.mi.com/details?id=com.aiyu.kaipanla>
- 87G 开盘啦竞价涨停委买额与隔夜单查看方式：<https://m.87g.com/az/218978.html>

### 本仓相关文档

- [`docs/research/dragon-leader-identification.md`](dragon-leader-identification.md) — 可回测的龙头识别研究合同（交易所规则 + 同行评议文献）
- [`docs/dragon-return-screener.md`](../dragon-return-screener.md) — 龙回头自动筛选落地说明（评分口径 100 分制）
