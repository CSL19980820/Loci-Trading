# 文档

## 职责
产品说明、ADR、架构约定（Diátaxis）。

## 边界
实现细节以代码与模块 README 为准。

## 关键入口
architecture/（含 [助手个性化](architecture/ai-assistant-personalization.md)、[助手富渲染](architecture/ai-assistant-rich-render.md)）· adr/（含 [ADR-002 DuckDB](adr/ADR-002-duckdb-readonly-panel.md)、[ADR-005 归档与记忆](adr/ADR-005-assistant-archive-and-memory.md)、[ADR-006 富渲染与流式](adr/ADR-006-assistant-rich-render-and-streaming.md)、[ADR-008 纸面量化舱](adr/ADR-008-paper-quant-cabin.md)、[ADR-009 盘口情报 lanes](adr/ADR-009-market-tape-provider-lanes.md)、[ADR-017 悟道简报转发与情报扩面](adr/ADR-017-wudao-briefing-relay-and-intel-widening.md)、[ADR-010 基线/观测/虚拟表/Polars](adr/ADR-010-2026-08-baseline-observability-virtual-table.md)、[ADR-011 热度尾盘选股器](adr/ADR-011-ths-heat-tail-close-picker.md)、[ADR-013 通达信主源](adr/ADR-013-tdx-primary-daily-source-and-batch-sync.md)、[ADR-014 盘中留存带与加密滚动窗口（草案）](adr/ADR-014-encrypted-intraday-tape-retention.md)、**[ADR-015 v2 多租户身份/社区/实时大屏](adr/ADR-015-v2-multi-tenant-identity-and-community.md)**、**[ADR-016 v2.1 租户隔离失效面/任务并发/保留期](adr/ADR-016-v2-1-tenant-isolation-concurrency-retention.md)**） · **[v2「群龙」发布说明](release-v2-qunlong.md)**· master-plan · quant-toolkit · **[research/INDEX.md](research/INDEX.md)（75 篇研究文档的导航入口，先读这个）** · **[research/2026-08-mainstream-quant-benchmark.md](research/2026-08-mainstream-quant-benchmark.md)（主流量化体系对标终稿 + 0/30/60/90 天路线图）** · research/2026-08-github-open-source-technology-radar.md

## 如何扩展
重大决策追加 ADR；结构变更改 architecture。

## 相关测试
—
