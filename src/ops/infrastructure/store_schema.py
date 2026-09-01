"""运维库 schema DDL 与进程内建表缓存。"""
from __future__ import annotations

SCHEMA_VERSION = 13

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- LLM 供应商：名称 + Base URL + 协议 + 密文 Key。
-- 不硬编码厂商枚举，新增一家 = 加一行配置，不改代码。
CREATE TABLE IF NOT EXISTS llm_providers (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    protocol        TEXT NOT NULL CHECK (protocol IN ('openai_compatible', 'anthropic')),
    base_url        TEXT NOT NULL,
    encrypted_key   BLOB,
    key_last4       TEXT NOT NULL DEFAULT '',
    default_model   TEXT NOT NULL DEFAULT '',
    models_json     TEXT NOT NULL DEFAULT '[]',
    models_synced_at TEXT NOT NULL DEFAULT '',
    proxy_url       TEXT NOT NULL DEFAULT '',
    is_active       INTEGER NOT NULL DEFAULT 1,
    is_default      INTEGER NOT NULL DEFAULT 0,
    validated_at    TEXT NOT NULL DEFAULT '',
    note            TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- 定时任务。cron 表达式 + 类型 + 该类型自己的配置。
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL,
    cron         TEXT NOT NULL DEFAULT '',
    config_json  TEXT NOT NULL DEFAULT '{}',
    enabled      INTEGER NOT NULL DEFAULT 1,
    last_run_at  TEXT NOT NULL DEFAULT '',
    last_status  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_enabled ON jobs(enabled, kind);


-- 每次执行的痕迹。定时任务最怕的是"静默地一直失败"，
-- 所以每次都记，且失败要留完整错误文本而不只是一个状态码。
CREATE TABLE IF NOT EXISTS job_runs (
    id           TEXT PRIMARY KEY,
    job_id       TEXT NOT NULL,
    job_name     TEXT NOT NULL DEFAULT '',
    kind         TEXT NOT NULL DEFAULT '',
    trigger      TEXT NOT NULL DEFAULT 'manual',
    status       TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT NOT NULL DEFAULT '',
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    result_json  TEXT NOT NULL DEFAULT '{}',
    error_text   TEXT NOT NULL DEFAULT '',
    owner_pid    INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    heartbeat_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_job ON job_runs(job_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON job_runs(status, started_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idempotency
    ON job_runs(idempotency_key) WHERE idempotency_key <> '';
CREATE INDEX IF NOT EXISTS idx_runs_heartbeat ON job_runs(status, heartbeat_at);

-- 量化战法档案：结构化记录战法形成背景、核心假设、适用市况和已知失效场景。
-- 有了这些，AI 做可行性分析和复盘优化时才有具体的可质疑点，
-- 而不是对着一行 description 瞎猜。
CREATE TABLE IF NOT EXISTS strategy_docs (
    slug            TEXT PRIMARY KEY,
    name            TEXT NOT NULL DEFAULT '',
    source_text     TEXT NOT NULL DEFAULT '',
    source_type     TEXT NOT NULL DEFAULT '',
    assumptions     TEXT NOT NULL DEFAULT '',
    market_cond     TEXT NOT NULL DEFAULT '',
    failure_modes   TEXT NOT NULL DEFAULT '',
    entry_timing    TEXT NOT NULL DEFAULT '',
    entry_instructions TEXT NOT NULL DEFAULT '',
    exit_rules      TEXT NOT NULL DEFAULT '',
    version         TEXT NOT NULL DEFAULT '1',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- 自定义策略版本历史。最多保留10个版本，超出时删最旧的「未被任务引用」版本。
-- 被任务引用的版本不删：如果任务正在用某版本，删掉会让任务崩溃。
CREATE TABLE IF NOT EXISTS strategy_versions (
    id          TEXT PRIMARY KEY,
    slug        TEXT NOT NULL,
    version     INTEGER NOT NULL,
    code        TEXT NOT NULL,
    file_path   TEXT NOT NULL DEFAULT '',
    issues      TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_sv_slug ON strategy_versions(slug, version DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sv_slug_active ON strategy_versions(slug) WHERE is_active=1;

-- 回测结果按策略版本存储，避免新代码覆盖旧版本的可复现实验结论。
CREATE TABLE IF NOT EXISTS strategy_backtests (
    slug          TEXT NOT NULL,
    version       TEXT NOT NULL,
    metrics_json  TEXT NOT NULL DEFAULT '{}',
    config_json   TEXT NOT NULL DEFAULT '{}',
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (slug, version)
);
CREATE INDEX IF NOT EXISTS idx_sb_slug_updated ON strategy_backtests(slug, updated_at DESC);
"""

_SCHEMA_READY: set[str] = set()

#: 增量迁移语句（幂等）。旧 skills / mcp_servers 先迁出再 DROP。
_MIGRATIONS: list[str] = [
    """CREATE TABLE IF NOT EXISTS strategy_docs (
        slug            TEXT PRIMARY KEY,
        name            TEXT NOT NULL DEFAULT '',
        source_text     TEXT NOT NULL DEFAULT '',
        source_type     TEXT NOT NULL DEFAULT '',
        assumptions     TEXT NOT NULL DEFAULT '',
        market_cond     TEXT NOT NULL DEFAULT '',
        failure_modes   TEXT NOT NULL DEFAULT '',
        entry_timing    TEXT NOT NULL DEFAULT '',
        entry_instructions TEXT NOT NULL DEFAULT '',
        exit_rules      TEXT NOT NULL DEFAULT '',
        version         TEXT NOT NULL DEFAULT '1',
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    )""",
    "ALTER TABLE strategy_docs ADD COLUMN entry_instructions TEXT NOT NULL DEFAULT ''",
    """CREATE TABLE IF NOT EXISTS strategy_versions (
        id          TEXT PRIMARY KEY,
        slug        TEXT NOT NULL,
        version     INTEGER NOT NULL,
        code        TEXT NOT NULL,
        file_path   TEXT NOT NULL DEFAULT '',
        issues      TEXT NOT NULL DEFAULT '[]',
        created_at  TEXT NOT NULL,
        is_active   INTEGER NOT NULL DEFAULT 1
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sv_slug ON strategy_versions(slug, version DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sv_slug_active ON strategy_versions(slug) WHERE is_active=1",
    """CREATE TABLE IF NOT EXISTS strategy_backtests (
        slug          TEXT NOT NULL,
        version       TEXT NOT NULL,
        metrics_json  TEXT NOT NULL DEFAULT '{}',
        config_json   TEXT NOT NULL DEFAULT '{}',
        updated_at    TEXT NOT NULL,
        PRIMARY KEY (slug, version)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sb_slug_updated ON strategy_backtests(slug, updated_at DESC)",
    "ALTER TABLE llm_providers ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE job_runs ADD COLUMN owner_pid INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE job_runs ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE job_runs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE job_runs ADD COLUMN heartbeat_at TEXT NOT NULL DEFAULT ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idempotency ON job_runs(idempotency_key) WHERE idempotency_key <> ''",
    "CREATE INDEX IF NOT EXISTS idx_runs_heartbeat ON job_runs(status, heartbeat_at)",
    "DROP TABLE IF EXISTS skills",
    "DROP TABLE IF EXISTS mcp_servers",
    # 二波监测 2026-08 退役：引擎、技能包、托管任务一并删除，留痕表随之作废。
    # DROP 放迁移里而不是「留着不写」——只追加的孤儿表会跟着 ops.db 一直被备份、
    # VACUUM、体检扫过，成本不为零（旧 skills / mcp_servers 同理，见上两行）。
    "DROP TABLE IF EXISTS second_wave_signals",
    """CREATE TABLE IF NOT EXISTS alert_rules (
        id TEXT PRIMARY KEY,
        code TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        condition_group_json TEXT NOT NULL DEFAULT '{}',
        market_hours_mode TEXT NOT NULL DEFAULT 'session',
        cooldown_minutes INTEGER NOT NULL DEFAULT 5,
        max_triggers_per_day INTEGER NOT NULL DEFAULT 10,
        repeat_mode TEXT NOT NULL DEFAULT 'repeat',
        expire_at TEXT NOT NULL DEFAULT '',
        plan_id_optional TEXT NOT NULL DEFAULT '',
        channel_ids_json TEXT NOT NULL DEFAULT '[]',
        last_trigger_at TEXT NOT NULL DEFAULT '',
        trigger_count_today INTEGER NOT NULL DEFAULT 0,
        trigger_date TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_alert_rules_enabled_code ON alert_rules(enabled, code)",
    """CREATE TABLE IF NOT EXISTS alert_hits (
        id TEXT PRIMARY KEY,
        rule_id TEXT NOT NULL,
        trigger_bucket TEXT NOT NULL,
        trigger_time TEXT NOT NULL,
        snapshot_json TEXT NOT NULL DEFAULT '{}',
        notify_ok INTEGER NOT NULL DEFAULT 0,
        notify_error TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(rule_id) REFERENCES alert_rules(id) ON DELETE CASCADE
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_hits_rule_bucket ON alert_hits(rule_id, trigger_bucket)",
    "CREATE INDEX IF NOT EXISTS idx_alert_hits_time ON alert_hits(trigger_time DESC)",
    """CREATE TABLE IF NOT EXISTS paper_cabins (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL DEFAULT '',
        max_layers REAL NOT NULL DEFAULT 4,
        max_layers_per_name REAL NOT NULL DEFAULT 0,
        config_json TEXT NOT NULL DEFAULT '{}',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS paper_positions (
        cabin_id TEXT NOT NULL,
        code TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        layers REAL NOT NULL DEFAULT 0,
        mark_cost REAL NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (cabin_id, code),
        FOREIGN KEY(cabin_id) REFERENCES paper_cabins(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS paper_fills (
        id TEXT PRIMARY KEY,
        cabin_id TEXT NOT NULL,
        code TEXT NOT NULL,
        action TEXT NOT NULL,
        layers REAL NOT NULL DEFAULT 0,
        mark_price REAL NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT '',
        reason TEXT NOT NULL DEFAULT '',
        decided_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY(cabin_id) REFERENCES paper_cabins(id) ON DELETE CASCADE
    )""",
    "ALTER TABLE paper_fills ADD COLUMN decided_by TEXT NOT NULL DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS idx_paper_fills_cabin ON paper_fills(cabin_id, created_at DESC)",
    """CREATE TABLE IF NOT EXISTS paper_rejects (
        id TEXT PRIMARY KEY,
        cabin_id TEXT NOT NULL,
        code TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL DEFAULT '',
        layers REAL NOT NULL DEFAULT 0,
        reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY(cabin_id) REFERENCES paper_cabins(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS nextday_plans (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL,
        plan_date TEXT NOT NULL,
        body_text TEXT NOT NULL DEFAULT '',
        items_json TEXT NOT NULL DEFAULT '[]',
        config_snapshot_json TEXT NOT NULL DEFAULT '{}',
        source TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(slug, plan_date)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_nextday_plans_slug_date ON nextday_plans(slug, plan_date DESC)",
    """CREATE TABLE IF NOT EXISTS monitor_runs (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT '',
        trigger_source TEXT NOT NULL DEFAULT '',
        snapshot_json TEXT NOT NULL DEFAULT '{}',
        orders_json TEXT NOT NULL DEFAULT '[]',
        fills_json TEXT NOT NULL DEFAULT '[]',
        rejects_json TEXT NOT NULL DEFAULT '[]',
        notes TEXT NOT NULL DEFAULT '',
        follow_pushed INTEGER NOT NULL DEFAULT 0,
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL DEFAULT '',
        duration_ms INTEGER NOT NULL DEFAULT 0,
        error_text TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_monitor_runs_slug ON monitor_runs(slug, started_at DESC)",
    """CREATE TABLE IF NOT EXISTS paper_style_profiles (
        slug TEXT PRIMARY KEY,
        style_md TEXT NOT NULL DEFAULT '',
        watch_hints_json TEXT NOT NULL DEFAULT '[]',
        buy_rules_json TEXT NOT NULL DEFAULT '{}',
        revision INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS paper_lessons (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL DEFAULT '',
        evidence_json TEXT NOT NULL DEFAULT '{}',
        absorbed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_paper_lessons_slug_date ON paper_lessons(slug, trade_date DESC, created_at DESC)",
    """CREATE TABLE IF NOT EXISTS paper_mem_nodes (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL,
        kind TEXT NOT NULL,
        key TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        props_json TEXT NOT NULL DEFAULT '{}',
        weight REAL NOT NULL DEFAULT 1.0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(slug, kind, key)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_paper_mem_nodes_slug_kind ON paper_mem_nodes(slug, kind, active)",
    """CREATE TABLE IF NOT EXISTS paper_mem_edges (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL,
        src_id TEXT NOT NULL,
        dst_id TEXT NOT NULL,
        rel TEXT NOT NULL,
        weight REAL NOT NULL DEFAULT 1.0,
        props_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(src_id) REFERENCES paper_mem_nodes(id) ON DELETE CASCADE,
        FOREIGN KEY(dst_id) REFERENCES paper_mem_nodes(id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_paper_mem_edges_slug ON paper_mem_edges(slug, rel)",
    "CREATE INDEX IF NOT EXISTS idx_paper_mem_edges_src ON paper_mem_edges(src_id)",
    "CREATE INDEX IF NOT EXISTS idx_paper_mem_edges_dst ON paper_mem_edges(dst_id)",
    # 龙头角色留痕：**只追加**。intel_snapshots 是按 (日, 工具) 覆盖的缓存，
    # 盘中角色演进会被抹掉；这里一次扫描写一批，便于回看「谁从龙头掉下来」。
    # 可整表清空重建（重扫即可再生），保留天数由 prune_leader_roles 控制。
    """CREATE TABLE IF NOT EXISTS leader_role_snapshots (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        code TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL,
        role_basis TEXT NOT NULL DEFAULT '',
        theme_code TEXT NOT NULL DEFAULT '',
        theme_name TEXT NOT NULL DEFAULT '',
        gate_state TEXT NOT NULL DEFAULT '',
        metrics_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_leader_roles_slug_code ON leader_role_snapshots(slug, code, observed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_leader_roles_slug_date ON leader_role_snapshots(slug, trade_date DESC, observed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_leader_roles_slug_observed ON leader_role_snapshots(slug, observed_at DESC)",
    # 悟道 MCP 日配额分池计数；DDL 归属 ops，intel.quota 仅读写本表
    """CREATE TABLE IF NOT EXISTS mcp_quota (
        trade_date   TEXT NOT NULL,
        pool         TEXT NOT NULL,
        call_count   INTEGER NOT NULL DEFAULT 0,
        updated_at   TEXT NOT NULL,
        PRIMARY KEY (trade_date, pool)
    )""",
    # AI 决策留痕：monitor_runs 只存 codes 列表，不存报价数值、prompt 与模型原始
    # 回复，事后无法复盘「模型当时凭什么这么判」。单条可达几十 KB，故独立成表，
    # 不拖累前端每次都要拉的 list_monitor_runs。可整表清空（见 PERSONAL_TABLES）。
    """CREATE TABLE IF NOT EXISTS ai_decisions (
        id                  TEXT PRIMARY KEY,
        slug                TEXT NOT NULL,
        run_id              TEXT NOT NULL DEFAULT '',
        trade_date          TEXT NOT NULL DEFAULT '',
        session_phase       TEXT NOT NULL DEFAULT '',
        model               TEXT NOT NULL DEFAULT '',
        system_prompt       TEXT NOT NULL DEFAULT '',
        user_payload_json   TEXT NOT NULL DEFAULT '{}',
        raw_output          TEXT NOT NULL DEFAULT '',
        parsed_orders_json  TEXT NOT NULL DEFAULT '[]',
        applied_orders_json TEXT NOT NULL DEFAULT '[]',
        quotes_json         TEXT NOT NULL DEFAULT '{}',
        status              TEXT NOT NULL DEFAULT 'ok',
        error_text          TEXT NOT NULL DEFAULT '',
        input_tokens        INTEGER NOT NULL DEFAULT 0,
        output_tokens       INTEGER NOT NULL DEFAULT 0,
        latency_ms          INTEGER NOT NULL DEFAULT 0,
        created_at          TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ai_decisions_slug ON ai_decisions(slug, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ai_decisions_run ON ai_decisions(run_id)",
    # 保留期清理按这些列截断。缺索引时 15 天截断就是全表扫，而清理跑在 02:30
    # 且整段持写锁——慢下来等于把凌晨的库锁住，比不清理更糟。
    # 已有可用的不再重复建：alert_hits.idx_alert_hits_time、
    # job_runs.idx_runs_job(job_id, started_at DESC)。
    # leader_role_snapshots 的三条复合索引都以 slug 打头，全表按 trade_date
    # 截断用不上，故单独补一条。
  "CREATE INDEX IF NOT EXISTS idx_ai_decisions_created ON ai_decisions(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_monitor_runs_started ON monitor_runs(started_at)",
    "CREATE INDEX IF NOT EXISTS idx_leader_roles_trade_date ON leader_role_snapshots(trade_date)",
    # 实时信号（大屏推流）的两张表。行情与研究产物**不**落这里——见
    # src/market/application/realtime_signals.py 的模块 docstring 第 1 条：
    # 「绝不写库」约束的是 market.db / research 库，信号日志与规则阈值属于运维
    # 事实，本来就该在 ops.db。两张表都可整表清空（清了只丢「我昨天收到过什么
    # 提醒」与「我调过哪几个阈值」，重开就回到代码里的默认值）。
    #
    # signal_rule_config：只存**被改过的那几条**。默认值写死在代码里的规则表
    # （realtime_signals.RULES），库里空 = 全部用默认。这样新增规则、改默认值
    # 不会被旧配置钉死，也不必写一次「把 6 条默认值灌进库」的种子迁移。
    # 主键是 (tenant, rule_id) 而不是裸 rule_id：ops.db 虽已按租户分库，但主租户
    # 的库同时被系统任务与管理员用，裸主键会让「谁把 fast_surge 关了」无从分辨，
    # 而且哪天要合库就得重做主键。多一列 tenant 是纵深防御，代价一个字节。
    # params 存 JSON 文本；空串等价于「一个键都没覆盖」（loads 的 fallback）。
    """CREATE TABLE IF NOT EXISTS signal_rule_config (
 tenant TEXT NOT NULL,
 rule_id TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1,
 params TEXT NOT NULL DEFAULT '',
 updated_at TEXT NOT NULL DEFAULT '',
 PRIMARY KEY (tenant, rule_id)
 )""",
    # signal_journal：信号日志（用户需求 5）。id 是**确定性去重键**（见
    # store_signals.signal_dedup_id），不是随机 uuid —— 引擎的内存去抖表一重启
    # 就没了，靠它把重启后重复命中的同一条信号压回一行。保留策略同样在写入时
    # 顺带执行，不另起定时任务（store_signals.prune_signal_journal）。
    """CREATE TABLE IF NOT EXISTS signal_journal (
 id TEXT PRIMARY KEY,
 tenant TEXT NOT NULL,
 code TEXT NOT NULL DEFAULT '',
 name TEXT NOT NULL DEFAULT '',
 rule_id TEXT NOT NULL DEFAULT '',
 rule_label TEXT NOT NULL DEFAULT '',
 title TEXT NOT NULL DEFAULT '',
 detail TEXT NOT NULL DEFAULT '',
 direction TEXT NOT NULL DEFAULT '',
 strength REAL NOT NULL DEFAULT 0,
 price REAL NOT NULL DEFAULT 0,
 pct REAL NOT NULL DEFAULT 0,
 triggered_at TEXT NOT NULL DEFAULT '',
 trade_day TEXT NOT NULL DEFAULT ''
 )""",
    # 读（最近 80 条）与两道保留闸门（按时间删、按条数删）走的是同一条路径：
    # 先按租户收窄，再按 triggered_at 倒序。缺这条索引三处都是全表扫。
  "CREATE INDEX IF NOT EXISTS idx_signal_journal_tenant_time"
    " ON signal_journal(tenant, triggered_at DESC)",
]
