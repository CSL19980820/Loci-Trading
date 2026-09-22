# Loci 长期存储治理

## 目标

存储治理的目标不是把某次满盘事故的文件删掉，而是让每一次增长都有归属、保留期、上限、容量闸门和可核验回执。账本、行情事实、来源证据、可重建缓存、用户手工备份必须分开处理。

线上 2026-09-18 的只读盘点为：根盘 40G、可用约 18G；`market.db` 约 2.2G，`market_hot.db` 约 846M，`palace.db` 约 102M，`ops.db` 约 70M。`market.db` 最大对象是 `source_route_receipts`、其索引和 `source_route_attempts`，不是 `/var/log`。同盘一致性备份还会短时产生一份整库临时副本，因此“当前还有空间”不能替代备份/重建的峰值预检。

## 数据分层

| 层 | 内容 | 存储与保留 | 自动动作 |
|---|---|---|---|
| L0 不可丢事实 | `palace.db` 账本、纸面成交、用户作品、配置 | SQLite；不按磁盘压力自动删除 | 只做一致性备份，恢复前先核验行数/完整性 |
| L1 在线行情事实 | `market.db` 日 K、交易日历、复权因子 | SQLite；历史地板 `2023-01-01`，保留完整在线窗口 | 只删除地板以前的异常行；不做“按容量删行情” |
| L1 派生热库 | `market_hot.db` | SQLite/WAL；700 个交易日，可从全量库重建 | 重建前检查 2×当前库 + 512MiB，空间不足直接跳过 |
| L2 在线来源证据 | 最近 selected/失败/skip 回执 | SQLite；selected 14 天，skip 7 天，失败回执保留 | selected 先归档，核验成功后再删；attempt 随回执处理 |
| L2 冷来源证据 | 已离开在线窗口的 selected 回执 | Parquet + Zstd；按批清单和主键摘要校验，保留 90 天 | `source_evidence` 查不到 SQLite 回执时按 receipt id 回读归档 |
| L3 可重建缓存 | `intel_snapshots`、盘中快照、运行缓存 | 现有 Parquet/SQLite 结构；按天数清理 | 30 天快照、盘中 60 天规则沿用现有任务 |
| L4 运维与研究产物 | `ops.db` 运行记录、`skill_runs/`、`research_runs/` | 租户清理任务分批处理；用户作品不按天删除 | 按租户保留期/配额软上限加速清理临时产物 |
| L5 备份 | 自动 market 一致性备份与人工维护备份 | 自动备份独立目录，默认保留 2 份；人工 `data/backups` 不自动碰 | 备份前预留临时整库 + 压缩空间和 10GiB 警戒水位 |

SQLite 仍是在线事实库；Parquet/Zstd 只承担冷证据，避免把高频回执的索引和写放大永久留在主库。归档不构成第二套可写真相，清单校验失败时不会删除 SQLite 行。

## 已实现入口

```bash
python -m cli.market storage-report --json
python -m cli.market storage-check --json
python -m cli.market storage-maintenance --json
python -m cli.market storage-maintenance --dry-run --json
```

`storage-report` 输出磁盘、数据库边车、目录和 SQLite `dbstat` 分项；`storage-check` 是轻量容量闸门；`storage-maintenance` 使用行情跨进程写锁，分批清理，归档校验后删除，并在容量允许时才 `VACUUM`。每次维护结果包括删除数量、归档清单、完整性检查和前后容量快照。

线上宿主任务由 `/usr/local/sbin/loci-storage-maintenance.sh` 统一调度，使用同一把 `flock`：

- 每 15 分钟：容量巡检，低于 10GiB 写 warning，低于 6GiB 写 critical；
- 每天 03:10：应用侧来源归档、保留期清理、WAL checkpoint 和条件压缩；
- 每周日 03:40：SQLite `.backup`、`integrity_check`、gzip 校验和 SHA-256 清单；
- 旧的 `/root/loci_market_maintenance.sh`、`/root/loci_market_backup.sh` 文件保留供取证，但不再由 cron 重复调度。

容量进入 warning 后每日任务仍可清理，但跳过 `VACUUM`；进入 critical 后跳过维护和备份，只保留告警和状态回执，避免在最危险的时刻制造临时副本。

## 恢复与验收

恢复前必须区分目标：行情库可由同步/热库重建，账本只能从一致性备份恢复。恢复或归档批处理验收至少包括：Parquet 行数、receipt 主键摘要、attempt 主键摘要、SQLite `quick_check`/`integrity_check`、前后文件大小和目标行数。单次“删了几行”不能证明磁盘释放；只有 `VACUUM` 成功后的文件大小或后续 `du/df` 才能证明归还操作系统。

自动备份目前仍在同一台服务器；它能防止在线库损坏时的即时回滚，但不等于异地灾备。异地对象存储或另一台主机的备份目的端必须单独配置后，才可以把 L5 标记为灾备完成。

## 本次上线回执（2026-09-18）

- 镜像 `loci-qianlong:2.0.0-20260918-145931` 已上线；容器 `healthy`，容器直连与 nginx `/api/health` 均为 HTTP 200。
- 宿主脚本 `/usr/local/sbin/loci-storage-maintenance.sh` 已安装，线上 SHA-256 为 `05457eac5713262db050203ce2272de46cf2040063af62b8e8c75f74aa1cbd47`；旧的重复 cron 行已移除。
- 真实维护回执 `data/storage-governance/latest-maintenance.json`：归档并删除 selected 回执 167,970 条，归档清单 9 个，SQLite `quick_check=ok`；旧 selected 候选为 0；空闲页 20,803，低于 262,144 碎片阈值，按策略跳过 `VACUUM`。
- 真实备份回执 `data/storage-governance/latest-backup.json`：`market-consistent-20260918-070656.db.gz`，`integrity=ok`，gzip 与 SHA-256 已核验；临时整库副本及上传临时文件已清理。
- 完成后根盘约 40G 中可用约 17G（约 58% 已用）。原有 `data/backups` 手工备份未自动删除；同盘自动备份不等于异地灾备。
