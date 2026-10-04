---
name: 个股复核与精炼记录
slug: compact-stock-research
version: 1.0.0
description: 独立股票智能体每轮逐股复核观察池和持仓，输出短日记、可接续计划；日周复盘维护有证据的有限经验。
capability: agent_workbench
policy: research
---

1. 读取 authority_calendar 与本轮时点。下一交易日只取系统 next_trade_date；日程未知就保留空值。用本轮账户、来源资格和真实报价复核 required_assessment_codes，每只在 assessments 留一句判断；猎隼包括全部观察股及持仓，其他智能体按本阶段原权限限定对象。缺报价写明缺数据；未查证用 unreviewed。全部对象均有证据复核才完成全池复核，重点研究对象用 focus 标记，两只重点不等于只复核两只。
2. 区分参与条件与可执行交易。stance 记录 participate、wait、avoid 或 exit；可验证的进场参考价写 expected_entry_price（元），缺依据保留 null。逐股结论写最关键依据与触发/失效条件，单条不超过120字。订单、拒单和成交分别以本轮意图和账本回执为准。
3. 输出 detail 的市场判断、重要变化和下一步；summary 用两句概述。research_plan_structured 按股保存仍有效的进场、退出、失效与下次核验条件。新记录以结构化字段为准，research_plan 留 null 沿用旧历史，不把同一段长报告复制到多个字段。
4. 日复盘和周复盘达到足够证据时维护 learning：沿用稳定 id，更新/验证旧认识，替换失效表述，删除冗余条目并写理由。经验最多12条、优化建议8条。样本、正反例和状态有真实证据支持；无新发现就留空。优化只记录待验证建议，执行权限与候选范围继续按当前智能体契约。

输出模板（只填本轮有依据的内容，避免跨字段重复）：

- 接续计划：market_view「环境判断一句」；next_trade_date「系统日期」；stocks 每股写 entry_condition「达到什么条件参与」、exit_condition「什么变化退出」、invalidation「判断何时失效」、next_check「何时查什么」。
- 工作日记：summary「本轮判断一句。实际买卖或保持等待一句。」；detail 写「市场 / 变化 / 下一步」各一句；assessments 每股 summary「关键证据 → 等待或行动条件」，code 明确对象、focus 标记重点；orders 仅提交有依据的意图，成交由账本确认。
- 经验条目：title「结论短句」、finding「证据说明」、conditions「适用范围」、sample_definition「样本口径」、validation_plan「怎么验证及什么结果推翻」。新判断 pending；有支持或反例时用 validate；同一认识新证据用 update；表述过时用 replace；重复或失效用 delete。操作沿用 id 并说明 reason，验证不能把假设样本改成实际成交。
