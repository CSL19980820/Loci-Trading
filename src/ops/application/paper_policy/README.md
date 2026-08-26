# paper_policy

## 职责
跨链路纸面策略口径：竞价低开带、扫描/纸面 stance 词汇、开仓过滤。

## 边界
不依赖 `skill_watch` 扫描引擎实现；`skill_watch.paper_eligibility` / `auction_gap` 仅为兼容再导出。

## 关键入口
- `eligibility.filter_openable_picks` / `is_auction_abandoned` / `has_actionable_picks`
- `auction_gap.classify_low_open_band`
- `stances`：扫描 `abandoned|downgraded|confirmed|pending` ↔ 纸面 `follow|revise|abandon|wait`

## 给 Agent 的用法
判废只看 `auction_stance` / `open_blocked`；不要再写中文文案启发式。

## README 维护
公开口径或词汇表变更时同批更新本文件与 `src/ops/README.md` 纸面段。

## 相关测试
`tests/ops/test_paper_eligibility.py`
