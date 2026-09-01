# ADR-014：盘中留存带（intraday）与加密滚动窗口

> 命名说明：本仓 `src/market/infrastructure/tape/` 已经是「盘口情报 provider lanes」
> 的意思（ADR-009），为免混淆，本 ADR 描述的东西在代码里叫 **intraday**，不叫 tape。

**状态**：已采纳并落地（2026-08-25 同日实现；采集清单为第一批，尚未覆盖竞价与分钟 K）
**日期**：2026-08-25
**相关**：[`2026-08-mainstream-quant-benchmark.md`](../research/2026-08-mainstream-quant-benchmark.md) §7、[`_scratch_2026-08-qb-storage-encryption.md`](../research/_scratch_2026-08-qb-storage-encryption.md) B4–B6、[`_scratch_2026-08-qb-akshare-surface.md`](../research/_scratch_2026-08-qb-akshare-surface.md) §4、ADR-002（DuckDB 只读旁路）、ADR-007（热读窗口）、ADR-008（纸面量化舱）

## 背景

**问题不是「要不要存盘中数据」，是「不存就永久拿不到」。**

- 本仓盘中留存能力实测为 **0**：分钟线明确不落库（`GET /api/market/minute/{code}`），live 只有进程内 3–5 秒 TTL 缓存，`market.db` 九张表里没有任何分钟 / tick / 盘口表。唯一在做快照的是 `intel_snapshots`（479 行 / 15.1 MB，且**无 TTL**）。
- AkShare 403 个 `stock_*` 接口里，**21 个只有当天快照 + 3 个只有最新一期**——没有任何参数能取到过去某一天。东财 `trends2` 的 `ndays` 上限是 5，`stock_zh_a_hist_min_em(period="1")` 源码里 `"ndays": "5"` 写死。**集合竞价在 AkShare 全库没有第二个入口**（全包 grep「集合竞价」= 0）。
- 与此同时，`market.db` 5,740.2 MB 里 **44.8%（2,569 MB）是溯源审计**——近一半磁盘花在证明「我什么时候抓的」，却一天都没存过上述 24 类不可回溯的数据。

因此本 ADR 要解决的是一个**时效性问题**：每推迟一天，就永久少一天历史。

## 决策

### 1. 新增 L4「盘中留存带」，物理独立于三库

```
<data_dir>/intraday/
  2026-08-25/
    auction_3s.parquet.enc  # 集合竞价逐笔 9:15–9:25，3 秒
    spot_5m.parquet.enc  # 全市场 spot 断面，5 分钟
    minute_1m.parquet.enc   # 全市场分钟 K
    limitup_events.parquet.enc    # 涨停 / 炸板事件流
    sector_flow_5m.parquet.enc      # 板块与概念资金流，5 分钟
    lhb.parquet.enc          # 龙虎榜
    manifest.json           # 明文，见 §4
  2026-08-26/
  ...
```

**不进 `market.db` / `market_hot.db` / `palace.db` / `ops.db`。** 理由：① 行存把同一份数据放大 5.6–5.7×（分钟 K 1,060 MB → 6,070 MB）；② 与权威库的写锁完全解耦；③ 过期删除退化成 `rmtree`。

### 2. 存什么：按「不可重建性 × 存储代价」取前六项

| # | 内容 | 频率 | 60 交易日 | 不可重建 |
|---:|---|---|---:|:---:|
| 1 | 涨停 / 炸板事件流 | 事件驱动 | 0.42 MB | ✓✓ |
| 2 | 龙虎榜 | 1 次/日 | 1.08 MB | ✗（交易所永久公开，但 1 MB 存了省事） |
| 3 | 板块与概念资金流 | 5 分钟 | 43.9 MB | ✓✓ |
| 4 | **集合竞价逐笔** | 3 秒，9:15–9:25 | 654.2 MB | **✓✓✓ 最高** |
| 5 | 全市场分钟 K | 1 分钟 | 1,059.8 MB | ✗（TDX/东财可回补，但每次 5,500 请求） |
| 6 | 全市场 spot 断面（9 列） | 5 分钟 | 269.0 MB | ✓ |
| | **合计** | | **2,028.4 MB ≈ 2.03 GB** | |

**明确不存**：五档盘口 1 分钟（6,866 MB，16,000 倍代价换重复信息——封单信息第 1 项已用 0.42 MB 给了）、spot 10 秒（8,069 MB，免费源本身刷新在 3–5 秒，大量重复行）、全市场 3 秒快照（21,588 MB，无真 L2 委托流时对 1–5 日策略无可验证增量 alpha）。

### 3. 保留窗口：**60 个交易日**，目录级过期删除

- 过期 = `unlink` 整个日期目录，实测删 30 天 **0.011 秒**，零碎片、无 2× 磁盘峰值。
- 挂进现有 `MANAGED_PRUNE`，**不新建 Job 类型**。
- **三道安全闸门**：只删 `intraday/` 下匹配 `^\d{4}-\d{2}-\d{2}$` 的目录；只删严格早于 `today - retention_days` 的；单次删除数量上限。
- 不用 SQLite `DELETE + VACUUM`：实测两个静默失效陷阱——`journal_mode=WAL` 排在 `auto_vacuum` 之前会让后者**静默变 0**；Python 里 `PRAGMA incremental_vacuum` **不 `.fetchall()` 等于没执行**。

### 4. 存原始，不存归一

`pipeline.normalize` 对选填列缺席是**静默丢列**（`pipeline.py:72`），对无法解析的值是 `to_numeric(errors="coerce")` **静默变 NaN**（`pipeline.py:52`）。快照的价值在于「当时上游到底返回了什么」，归一会把证据抹掉。

`manifest.json`（**明文**，因为它本身就是排障与漂移基线）至少含：

```json
{
  "contract_version": "loci-tape-manifest-v1",
  "trade_date": "2026-08-25",
  "akshare_version": "1.18.56",
  "files": [
    {
      "name": "spot_5m.parquet.enc",
      "tool": "stock_zh_a_spot_em",
      "captured_at": ["2026-08-25T09:35:00+08:00", "..."],
    "rows": 264000,
      "columns": ["序号", "代码", "名称", "最新价", "..."],
      "sha256": "…",
      "encrypted": true
    }
  ]
}
```

`columns` 这一项同时就是 AkShare 上游列漂移的比对基线——本仓目前唯一记过「本次实际列」的地方是 `sync.py:414-419` 的回执 `fields`，但**无人拿它做比对**。

### 5. 加密：DuckDB 原生 Parquet Modular Encryption + DPAPI

- **算法**：`AES_GCM_V1`，256-bit。规范为 PARQUET-1178，保留列裁剪与谓词下推。
- **密钥**：每库一个随机 DEK；DEK 用 Windows DPAPI（`CryptProtectData`，带 entropy）包裹后落 `<data_dir>/intraday/.dek`。**DEK 不进任何数据库、不进 `loci.config.json`、不进分享包。**
- **零新增依赖**：`duckdb` 已在 `requirements.txt`。
- **实测代价**：主查询 **343 ms vs 明文 354 ms（无劣化）**，体积 **0.977×**，无密钥**硬失败**（不是静默返回空）。

**排除的方案与理由**：

| 方案 | 判定 |
|---|---|
| SQLCipher | `sqlcipher3-binary` 0.4.0→0.6.0 **零 Windows wheel**；`pysqlcipher3` 仅 sdist、2023-01-29 停更。本项目发 PyInstaller Windows exe，**装不上** |
| SQLite SEE | 商业许可（$2,000 档），闭源 |
| Fernet | 实测 **+33.33% 体积**、AES-128、无 AAD |
| 应用层逐 blob AES-GCM | 可行但次优：要维护明文索引列（「能加密的是 value，不能加密的是你要 WHERE 的那列」），复杂度不划算 |

**威胁模型（必须写清）**：
- **防**：设备失窃、硬盘被拆、未加密备份泄露、误发云盘、分享包误带盘中数据。
- **不防**：本机已登录用户的任意进程（DPAPI 按用户解密）、内存 dump、有管理员权限的攻击者。

**为什么 `.palace_ai_master_key` 那次失败不会重演**：
1. 那次是**主密钥明文躺在被加密数据旁边**，等于没加密；这次 DEK 进 DPAPI，与密文**不在同一爆炸半径**。
2. 那次加密的是 LLM Key，解不开**功能直接不可用**，于是被迫回退明文；这次加密的是**可重建/可丢弃的盘中缓存**，解不开最坏是丢 60 天快照，**不阻断任何主体功能**。
3. **判据**：加密的对象必须是「丢了不影响主体功能」的东西。这是两次决策的分水岭，也是本 ADR 的适用边界——**不要用这套去加密 `palace.db`**。

### 6. L0 权威库与 L1 面板**不加密**

可重建、无隐私价值，加密只会挡住排障与第三方工具（DuckDB CLI / DB Browser）。


## 落地情况（2026-08-25）

| 决策项 | 落点 | 实测 |
|---|---|---|
| 按天分目录 + 加密 Parquet | `src/market/infrastructure/intraday_archive.py` | 5 个数据集落盘，0.40 MB/日 |
| DEK + DPAPI | `src/market/infrastructure/intraday_keyring.py` | DPAPI 往返通过，entropy 生效；无 DPAPI 时如实标 `protection="none"` |
| 三道安全闸门 | `src/market/infrastructure/intraday_prune.py` | 6 条 prune 测试通过，含「`.dek` 与非日期目录不许被扫进删除清单」 |
| 采集编排 + fail-soft | `src/market/application/intraday.py` | 单源挂掉不影响其余项，实测 4/6 与 5/6 两种部分成功 |
| 托管任务 | `src/ops/application/ensure_intraday_capture_job.py`、`jobs/intraday_capture.py` | 工作日 15:35，幂等，`intraday_capture` 已进 `JOB_KINDS` 与 `EXECUTORS` |
| 过期删除挂 prune | `src/ops/application/jobs/prune.py` | `intraday_keep_days=60`、`intraday_max_delete=30` |
| CLI | `cli/market_intraday.py` | `intraday-capture` / `intraday-prune` / `intraday-status` |
| 测试 | `tests/market/test_intraday_archive.py`（19）、`tests/ops/test_share_pack_excludes_intraday.py`（3） | 全绿；全仓 2027 passed |

**加密语义已实测**：无密钥读取 `InvalidInputException`、错密钥同样硬失败，不会静默
返回空表。密文中不含明文股票名。

**分享包这一条不用改**：实测 `build_share_pack` 是**白名单**（只拷显式命名的
`palace.db` / `market.db` / `ops.db` / `mcp.json` / `skills/` / config），从不整目录遍历
`data_dir()`，因此 `intraday/` 与 `.dek` 本来就进不去。已加 `test_share_pack_excludes_intraday.py`
把这个性质锁住——哪天有人改成「拷整个 data 目录再排除几项」的黑名单写法，测试会红。

**首批采集清单与实测行数**（2026-08-25 收盘后）：

| dataset | 来源 | 行数 |
|---|---|---:|
| `limit_up_pool` | `stock_zt_pool_em` | 65 |
| `broken_limit_up_pool` | `stock_zt_pool_zbgc_em` | 22 |
| `spot_close` | `stock_zh_a_spot_em`，失败回退 `fetch_spot_routed` | 5,543 |
| `stock_comment` | `stock_comment_em` | 5,195 |
| `hot_rank` | `stock_hot_rank_em` | 100 |
| `sector_fund_flow_rank` | `stock_sector_fund_flow_rank` | 当日上游 `RemoteDisconnected`，未采到 |

**还没做的（下一轮）**：集合竞价逐笔（§2 第 4 项，不可逆性最高）、全市场分钟 K
（§2 第 5 项）、板块资金流的稳定来源。`spot_close` 目前多数时候走的是回退路径，
只有 8 列而不是东财的 23 列——要拿到量比/涨速/振幅还得解决东财 `push2` 的连接问题。

## 后果

**优点**
- 24 类不可回溯数据从「永久丢失」变成「滚动 60 天可用」，直接支撑本仓已有的尾盘 / 涨停 / 二波 / 竞价系列研究。
- 2.03 GB 的增量，被 §6 的瘦身（删 `idx_quotes_receipt` 1,049 MB + 删 `market_hot.db` 1,022 MB）**完全抵消有余**。
- 目录级过期是 O(1)，不引入新的 VACUUM / 碎片 / 写放大问题。

**约束**
- ~~分享包必须默认排除~~ **已实测无需改动**：`build_share_pack` 是白名单，`intraday/` 进不去。已加测试锁住该性质。
- 新增落盘模块要拆成 `tape_writer` / `tape_reader` / `tape_prune` 三个文件，遵守单文件 ≤600 行。
- `intraday/` 属「可重建缓存」语义的例外：**整目录可删，但删了拿不回来**。README 与「是否入库」决策表要为它单列一行，不能含糊成普通缓存。
- 盘中轮询会消耗第三方配额。第 3、6 项是**全市场单表**（一次调用覆盖全市场），第 4 项若做全市场逐票会打穿配额——**首版只对自选池 + 涨停池成员做竞价留存**。

**验收门禁**（未达标不得进主干）
- [ ] 连续 5 个交易日无缺日；`manifest.json` 三字段（版本 / 时刻 / 列名）齐全
- [ ] 无密钥读取**硬失败**（不得静默返回空表）
- [ ] 加密相对明文的主查询劣化 < 5%
- [ ] 过期删除只碰 `intraday/`，三道闸门各有单测（含「传入 `../` 必须拒绝」）
- [ ] 分享包解出来不含 `intraday/`
- [ ] 单日总体积告警阈值（超过预期 3× 时记 warning，防上游返回异常大表打爆磁盘）

**待实测（落地前必须补）**
- `stock_zh_a_hist_min_em` 5/15/30/60 分钟的真实历史深度（请求侧 `beg=0&end=20500000` 不设限，服务端截断未知）——决定分钟 K 是「必须自存」还是「可回补」。
- 竞价逐笔的实际可得粒度与配额消耗。
- DPAPI 在 PyInstaller onedir 打包后的行为（本轮只在解释器里实测过 entropy 生效）。
