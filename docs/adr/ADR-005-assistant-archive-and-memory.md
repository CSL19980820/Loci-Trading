# ADR-005 · 助手归档真删与记忆落 ops.db

- **状态**：Accepted
- **日期**：2026-08-05

## 背景

助手会话曾把 `DELETE` 做成软归档，前端无确认、无归档轨。个性化（指令/规则/记忆）缺失。需对齐 ChatGPT 归档/真删与 Hermes 双仓记忆。

## 决策

1. **归档** = `status=archived`（可恢复）；**删除** = 物理删除会话行（CASCADE 消息与 run）；`ai_execution_grants` 无 FK，审计保留。
2. **画像与记忆** 存 `ops.db`（`ai_assistant_profile` / `ai_memories`），与助手同库；不进 palace/market。
3. **Core Safety Prompt** 写死在 domain；用户指令/规则/记忆仅追加注入；run 开始冻结快照。
4. **自动记忆** 按会话消息数阈值触发轻量整理，字符硬顶防 prompt 膨胀。

## 后果

- 旧客户端若把「删除」当可恢复，需改接归档 API。
- 真删不可撤销；UI 必须二次确认。
- 记忆与授权审计同在 ops，备份 ops.db 即备份个性化。
