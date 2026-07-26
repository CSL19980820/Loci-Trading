# 卢高文涨停文章提炼与通达信选股公式

来源目录：`D:\资料\娱乐\涨停相关\卢高文`

已解析文件：
- `10月14日卢高文复盘+涨停形态战法第一章！.doc`
- `10月15日卢高文复盘+涨停形态战法第二章！.doc`
- `10月16日卢高文课程+涨停形态战法第三章！.doc`
- `10月17日卢高文复盘+涨停形态战法第四章！.docx`
- `10月18日卢高文复盘+涨停战法第五章！+如何买卖个股！.docx`
- `筹码峰教学！.docx`

## 可落地结论

可以做成通达信选股公式，但不能百分百还原原文。

能量化的部分：
- 涨停、一字涨停、连续涨停。
- 高开 0%-3%、高开低走、阴线后涨停。
- 不跌破某根涨停 K 线价格。
- 5 日线、20 日线、阶段低位、长期下跌。
- 缩量、放量。
- `COST` 近似筹码集中与筹码峰突破。

不能完全量化的部分：
- “市场各阶段龙头或妖股”：只能用近期涨停数、阶段涨幅近似。
- “低位”“长期下跌”：公式里只能用均线/区间高点回撤近似。
- “筹码峰形状”：通达信条件公式不能像肉眼那样识别完整筹码图，只能用 `COST(85)-COST(15)` 这类集中度近似。
- 盘中分时黄色线、站稳 20 分钟、尾盘炸板次数：这类属于盘中/分时交易规则，不适合做日线静态条件选股。

## 统一涨停识别模板

以下公式都内置了这段逻辑：

```tdx
BL:=IF(CODELIKE('688') OR CODELIKE('689') OR CODELIKE('300') OR CODELIKE('301'),0.20,
IF(CODELIKE('8') OR CODELIKE('4') OR CODELIKE('92'),0.30,
IF(NAMELIKE('ST'),0.05,0.10)));
ZT:=C>=ZTPRICE(REF(C,1),BL)*0.995 AND C=H;
```

说明：
- 主板默认 10%。
- 科创板、创业板按 20%。
- 北交所常见代码前缀按 30%。
- ST 按 5%。
- `0.995` 用来容忍四舍五入和少量价格误差。

## 公式 1：三外有三

原文规则：
- 先连续三个涨停。
- 三板后调整 2-5 天左右。
- 调整不深，最好不跌破第三板价格；跌破第二板价格止损。

通达信条件选股公式：

```tdx
BL:=IF(CODELIKE('688') OR CODELIKE('689') OR CODELIKE('300') OR CODELIKE('301'),0.20,
IF(CODELIKE('8') OR CODELIKE('4') OR CODELIKE('92'),0.30,
IF(NAMELIKE('ST'),0.05,0.10)));
ZT:=C>=ZTPRICE(REF(C,1),BL)*0.995 AND C=H;
S3:=ZT AND REF(ZT,1) AND REF(ZT,2);
N:=BARSLAST(S3);
M:=IF(N<1,1,N);
T3C:=REF(C,N);
T2C:=REF(C,N+1);
ADJ:=N>=2 AND N<=5;
STOPOK:=LLV(L,M)>=T2C*0.98;
NEAR3:=C>=T2C AND C<=T3C*1.08;
XG:ADJ AND STOPOK AND NEAR3;
```

更严格版本：把 `STOPOK` 改成：

```tdx
STOPOK:=LLV(L,M)>=T3C*0.98;
```

## 公式 2：天衣无缝

原文规则：
- 低位出现一字板涨停。
- 次日高开 0%-3% 是买点。
- 一字板价格为保护价，不能跌破。
- 一字涨停最好缩量。

通达信条件选股公式：

```tdx
BL:=IF(CODELIKE('688') OR CODELIKE('689') OR CODELIKE('300') OR CODELIKE('301'),0.20,
IF(CODELIKE('8') OR CODELIKE('4') OR CODELIKE('92'),0.30,
IF(NAMELIKE('ST'),0.05,0.10)));
ZT:=C>=ZTPRICE(REF(C,1),BL)*0.995 AND C=H;
LOWPOS:=C<HHV(H,60)*0.80 OR C<MA(C,60)*0.95;
YZT:=ZT AND H=L AND V<REF(V,1)*0.80 AND LOWPOS;
BUYOK:=O>=REF(C,1) AND O<=REF(C,1)*1.03;
PROTECT:=L>=REF(C,1)*0.98;
XG:REF(YZT,1) AND BUYOK AND PROTECT;
```

## 公式 3：倒拔杨柳

原文规则：
- 适用于上升加速中的龙头/妖股。
- 前面有涨停，次日高开低走，收假阴线。
- 股价仍高于前收盘。
- 回踩不能跌破 5 日线。
- K 线最好是下影锤头，不能有明显上影线。

通达信条件选股公式：

```tdx
BL:=IF(CODELIKE('688') OR CODELIKE('689') OR CODELIKE('300') OR CODELIKE('301'),0.20,
IF(CODELIKE('8') OR CODELIKE('4') OR CODELIKE('92'),0.30,
IF(NAMELIKE('ST'),0.05,0.10)));
ZT:=C>=ZTPRICE(REF(C,1),BL)*0.995 AND C=H;
LEADER:=COUNT(ZT,10)>=2 OR C/LLV(L,20)>1.30;
FAKEYIN:=REF(ZT,1) AND O>REF(C,1)*1.02 AND C<O AND C>REF(C,1);
MA5OK:=L>=MA(C,5)*0.995;
LOWER:=(MIN(O,C)-L)>ABS(C-O)*1.20;
UPPER:=(H-MAX(O,C))<ABS(C-O)*0.30;
XG:LEADER AND FAKEYIN AND MA5OK AND LOWER AND UPPER;
```

## 公式 4：海底捞月

原文规则：
- 长时间下跌后，突然出现一根涨停 K 线。
- 后续不跌破涨停价格。
- 在涨停价附近可介入，跌破涨停价离场。

通达信条件选股公式：

```tdx
BL:=IF(CODELIKE('688') OR CODELIKE('689') OR CODELIKE('300') OR CODELIKE('301'),0.20,
IF(CODELIKE('8') OR CODELIKE('4') OR CODELIKE('92'),0.30,
IF(NAMELIKE('ST'),0.05,0.10)));
ZT:=C>=ZTPRICE(REF(C,1),BL)*0.995 AND C=H;
DOWN:=REF(C,1)<REF(MA(C,20),1) AND REF(MA(C,20),1)<REF(MA(C,60),1)
AND REF(C,1)<HHV(H,60)*0.75;
START:=ZT AND DOWN;
N:=BARSLAST(START);
M:=IF(N<1,1,N);
BASE:=REF(C,N);
NEARBASE:=C>=BASE*0.99 AND C<=BASE*1.08;
NOBREAK:=LLV(L,M)>=BASE*0.98;
XG:N>=1 AND N<=10 AND NEARBASE AND NOBREAK;
```

## 公式 5：分手快乐

原文规则：
- 阴线之后突然大幅高开。
- 当天攻击涨停。
- 涨停次日 3% 以内试探介入。
- 跌穿涨停启动点止损。
- 按板块涨跌幅识别涨停：创业板/科创板 20cm，其余默认 10cm；不单独处理 ST 和北交所。

通达信条件选股公式：

```tdx
BL:=IF(CODELIKE('688') OR CODELIKE('689') OR CODELIKE('300') OR CODELIKE('301'),0.20,0.10);
ZT:=C>=ZTPRICE(REF(C,1),BL)*0.995 AND C=H;
PAT:=REF(C,1)<REF(O,1) AND O>REF(C,1)*1.02 AND ZT;
N:=BARSLAST(PAT);
BUYOK:=O>=REF(C,1) AND O<=REF(C,1)*1.03;
PROTECT:=L>=REF(C,1)*0.98;
XG:N=1 AND BUYOK AND PROTECT;
```

## 公式 6：筹码低位单峰突破近似

原文规则：
- 低位形成单峰密集。
- 放量突破筹码峰，通常是一轮上升行情征兆。
- 后面回调最好缩量，回踩不破再上攻。

通达信条件选股公式：

```tdx
CHIPN:=(COST(85)-COST(15))/COST(50)<0.18;
LOWCHIP:=COST(50)<HHV(H,120)*0.75;
VOLUP:=V>MA(V,5)*1.50;
BREAK:=C>COST(85) AND C>REF(HHV(H,20),1);
XG:CHIPN AND LOWCHIP AND VOLUP AND BREAK;
```

## 使用建议

- 不建议直接五合一混选，最好每个战法单独建一个条件选股公式，分别跑结果。
- 初筛后必须人工复核：题材强度、板块位置、是否近期龙头、是否有利空公告、是否次新/停牌/一字无成交。
- 这些公式只适合做候选池，不适合作为自动买入信号。
- 可先用历史行情回测命中率，再微调 `LOWPOS`、`LEADER`、`N`、`0.98/1.03/1.08` 这些阈值。
