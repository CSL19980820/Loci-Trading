# 脚本

## 职责
构建与一次性迁移 / 文档辅助脚本。非运行时依赖。

## 关键入口
### 权威行情修复

`resync_market_authoritative.py` 默认全历史重拉，`--no-force` 只重刷增量近窗，`--codes` 可限定证券。两种模式均严格只用通达信并绕过当日水位；主源不可用时保留失败回执、返回非零退出码，不再把腾讯回退视为权威修复。`--dry-run` 只统计；合成成交额统计与体检一致，排除单一成交价日。

### 相对主题指数领先的回踩机会

- `python -m scripts.relative_leader_prepare --source OLD_RESEARCH_DIR --root RESEARCH_DIR`：使用国证历史指数与冻结股票日线，筛选上涨阶段显著领先、回踩后仍保留超额优势的个股；基准映射在脚本和产物中明确记录。
- `python -m scripts.participation_research --root RESEARCH_DIR --fund-root FUND_PAGES --policies relative_leader_rising_open relative_leader_falling_open --holds 10 20 --risk-budget 1000`：比较板块状态与持有窗口，使用已有成交引擎，限价订单预留当日名额。参与度、风险预算、跨期失败和历史机会见 [`相对领先回踩研究`](../docs/research/2026-09-11-relative-leader-pullbacks.md)。
- `participation_prepare.py` / `participation_research.py` 同时保留独立平台突破及确认后复测的研究对照，不能把其中表现差的版本注册成生产策略。

### 涨停回踩与资金右侧研究

- `python -m scripts.limitup_rightside_features --db FROZEN_DB --events EVENT_PAGES --output PREPARED_DIR`：校验历史涨停事件，生成启动、缩量回踩、右侧再确认与滞后题材活跃股证据；不使用当前概念成分回填历史。
- `python -m scripts.limitup_rightside_research --root RESEARCH_DIR`：消费冻结候选、价格及对应日资金榜，复用成交引擎和逐日盯市账本，比较三条路线与两个对照。配置、七个月结果、低仓位和小样本限制见 [`资金右侧研究`](../docs/research/2026-09-11-limitup-rightside.md)。

### 七个月高盈亏比研究

- `payoff_research_snapshot.py SOURCE TARGET`：通过只读附加连接冻结 2024-07 至 2026-08 的公共行情，生成来源、版本、完整性与 SHA-256 清单；目标文件必须不存在。
- `high_payoff_research.py --db FROZEN_DB --output OUTPUT_DIR`：复用线上同版成交引擎，比较突破、动量、低波动突破及趋势回撤；2025 年同期筛选，2026-02 至 2026-08 验证。输出信号、逐笔交易、逐日盯市权益、成本压力及训练筛选记录。只读冻结库，不注册策略、不写候选池。
- 股票池来自当前证券表，存在幸存者与历史 ST 状态缺口；追加探索不能称为未接触的独立样本外检验。规则、结果和复现方式见 [`七个月研究记录`](../docs/research/2026-09-11-high-payoff-seven-month.md)。

### 行情数据管线（选型 / 测速 / 校验）

- `benchmark_data_sources.py` — **数据源全面测量**：逐源单票时延、并发梯度吞吐、批量宽度、字段完整度，折算全市场耗时。主源选型的证据来源。
  `--codes 40 --bars 320 --workers 1,4,8,16,32`；报告落 `output/data-source-benchmark/`。
- `benchmark_sync_path.py` — **线上同步路径基线**：走真实 `sync_quotes` / router / store，种一个临时库避免污染生产库。
  `--codes 200 --workers 16 --interval 0.02`，加 `--force` 测全量回填、`--factors --spot` 测完整日终。
- `check_lane_readiness.py` — **全 lane 数据源可用性兵棋盘**：每条线路真打一次，回答「这条线路到底能不能用」，而不是只看配置里登记了谁。
- `verify_tdx_data_quality.py` — 通达信主源的字段 / 覆盖 / 历史深度 / 精度核对，逐票逐日对照 `market.db` 已落盘 OHLCV。
- `verify_sync_written.py` — 同步落盘正确性：跑完真实同步后，回头拿源侧数据逐格点比对写进库的值。
- `verify_market_data_quality.py` — **生产库数据体检(一次性深挖版)**:来源构成、合成假成交额占比、缺回执、北交所覆盖、坏 OHLC 按来源与年代。换源/重同步后跑它验收。
  **日常体检已经托管化**,见运维「行情库体检」任务(`kind=data_quality`,工作日 16:30);本脚本留给需要按年代/来源摊开细看的场合。
- `resync_market_authoritative.py` — 用权威源(通达信)全量重写生产库。走 `upsert` 只覆盖不删行、占 `market_write_lock`、按 watermark 断点续跑;`--dry-run` 只统计。**会招上游限流,不要当日常操作跑**(日常增量走近窗不会触发)。
  `--codes 600717,300333` 定点补洞:体检报出十几行缺回执时用它,不必为此重扫全市场。

- `compact_evidence_blobs.py` — **压掉 ops.db / palace.db 里的历史巨型证据字段**。写入侧已在 `finish_run` 与候选落库处收口(见 `src.shared.evidence_compact`),但那只管以后;已经躺在库里的历史行要用它清。实测 ops.db 5.67 GB → 0.01 GB、`GET /api/jobs/runs` 97s/1.5GB → 60ms/1.0MB;palace.db 候选证据 58.3 MB → 0.2 MB。只改 JSON 大字段、不删行,`--dry-run` 只统计,跑完 VACUUM 回收磁盘。

### 其它

- `build-loci.ps1` — 打 / 增量更新 Loci 便携版
- `sync_boot_splash_index.py` — 把 `src.shared.boot_splash` 同步进 `frontend/index.html`（改启动页后必跑）
- `upsert_agent_readme_sections.py` — 给模块 README 补 Agent 段落
- `migrate_imports.py` / `rewrite_frontend_imports.py` / `write_module_readmes.py` — 历史迁移辅助
- `legacy_strategy_combination_backtest.py` — 海底捞月、筹码峰突破、三外有三老版本的多条件组合回测
- `qianlong_v1_combination_backtest.py` / `qianlong_v1_backtest_report.py` — 潜龙老版本多条件组合回测
- `qianlong_structure_backtest.py` / `qianlong_structure_report.py` — 潜龙 v1/v2/v3 粗对比（旧）
- `qianlong_structure_research.py` — 潜龙 v1/v2/v3 结构研究（对齐三元报告标准：成本/盈亏比/组合回撤/分层），产出 `output/qianlong-structure-*`
- `qianlong_tail_rank_research.py` — 历史研究脚本（潜龙尾盘已下线；对照产出仍可本地跑，不注册战法）
- `cleanup_stale_candidate_versions.py` — palace 清理，两个 scope：`archived` 删已归档战法（qianlong-close / lugw-sanwai* 等）刷出来的**重复精选**；`deleted` 清**已整体删除的战法**（`DELETED_1450_SLUGS`：14:50 三源 / 杨氏 / 潜伏）在 `candidate_reviews` 与 `position_tracking` 里的**全部行（不分 decision）**——战法代码与定时任务都没了，留着的行既会继续出现在选股历史，也再无法重跑复现。只认 slug 列，slug 为空的早期行才回落到 `{slug}@日期` 的 pool_id，避免误删同批次里别的战法的行。默认 dry-run，`--apply` 才删；`--scope` 默认 `all`
- `tail_1450_next_day_touch_research.py` — 「尾盘买 + 次日冲高 ≥0.5% 算有效」的全市场回测；六种出场对照（0.5%/2%/3% 止盈、持到次日收盘、只吃隔夜、卖在次日最高的不可实现上界）+ 波动率匹配对照 + 日内截面中性化 + 逐年切片 + k≤3 组合网格。`--rank-exit` 决定网格按哪种出场排序（默认 `hold_close`）。只读 `market.db`，结论见 [`docs/research/2026-08-tail-1450-next-day-touch-backtest.md`](../docs/research/2026-08-tail-1450-next-day-touch-backtest.md)
- `tail_close_entry_baseline_research.py` — 尾盘入场基线：同一批样本、同一个卖出日，只把入场价从「T 日收盘」换成「T+1 开盘」，两臂之差即隔夜跳空的价格。输出 8 条臂（2 入场 × 4 持有期）+ 逐年 + 4 个因子的十分位（收益与隔夜跳空各一套）
- `tail_material_rules_backtest.py` — 把 `D:\资料\娱乐` 素材里的**纯日线**尾盘规则做成 11 条**预注册**对照臂（不做网格，避免多重比较），每条都跑「尾盘买 vs 次开买 × 持 1/2/3 日」，配日内截面中性化与波动率匹配对照。信号不使用当日 `high`/`low`（`entry_timing=close` 下裸用是 block）
- `yangshi_tail_rank_portfolio_research.py` — 杨氏六条（T28）闸门内的排序与组合层网格：11 个排序因子 × 4 个 Top-N × 2 个宽度闸门 × 2 个持有期 = 176 组，判据固定在事前（逐年零负年 + 前后两段皆正）。组合层用重叠持仓的标准处理（资金分 `hold` 份、按 `day_idx % hold` 错开，每份串行连乘后取平均），给出组合收益 / 最大回撤 / 仓位占用率。`yangshi-tail-v1` 落地为「当日涨幅降序 Top1 + 持 3 日 + 宽度≥40%」
- 上面三个脚本的结论合并在 [`docs/research/2026-08-yule-materials-tail-close-feasibility.md`](../docs/research/2026-08-yule-materials-tail-close-feasibility.md)

### build-loci.ps1 模式

| Mode | 场景 | 耗时量级 |
|------|------|----------|
| `full`（默认） | 首次打包、加/改 pip 依赖、改 `loci.py` / `loci.spec` | 全量（前端 + clean PyInstaller + 整包覆盖） |
| `frontend` | 只改前端 | 秒～分钟（bun build + 覆盖 `_internal/frontend/dist`） |
| `app` | 改后端 / 入口产物 | 无 clean 的 PyInstaller + 覆盖 exe/`src`/assets |
| `app -SrcOnly` | 只改了 `src/` 下业务代码 | 秒级（只同步 `_internal/src`） |
| `app+frontend` | 前后端都改、无新依赖 | 前端 + 无 clean PyInstaller + 增量覆盖 |

```powershell
.\scripts\build-loci.ps1 -Mode frontend -DeployDir "E:\entertainment_software\Loci"
.\scripts\build-loci.ps1 -Mode app -SrcOnly -DeployDir "E:\entertainment_software\Loci"
.\scripts\build-loci.ps1 -Mode app+frontend -DeployDir "E:\entertainment_software\Loci"
.\scripts\build-loci.ps1 -Mode full -DeployDir "E:\entertainment_software\Loci"
```

增量模式要求目标已有安装，且 `app` / `SrcOnly` 需要 `_internal/src`（松散业务代码）。旧安装先跑一次 `full`。`-SrcOnly` 仅能与 `-Mode app` 联用，不覆盖 `loci.py` 入口变更。

## 如何扩展
临时脚本用完可删；长期脚本在本 README 登记。

## 相关测试
—
