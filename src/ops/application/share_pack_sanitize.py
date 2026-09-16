"""分享包脱敏：把「可分享的骨架」和「我独有的数据」切开。

分享包是**数据离开这台机器**的唯一出口，属于信任边界。所以这里一律用
**白名单**：新增的表 / 配置键默认不外发，而不是等谁记得来加黑名单。

脱敏后仍可用的：任务定义、战法档案、推送模板、调参档位。
被抹掉的：密钥、Webhook、账本以外的个人交易记录（纸面舱 / 教训 / 记忆 / 留痕）。
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import json
import shutil
import sqlite3
from typing import Any
from urllib.parse import urlsplit, urlunsplit

#: 绝不允许出现在分享包里的文件名（大小写不敏感）。最后一道闸。
FORBIDDEN_FILE_NAMES = frozenset(
    {
        ".palace_ai_master_key",
        "palace_ai_master_key",
        ".env",
        "credentials.json",
    }
)

FORBIDDEN_SUFFIXES = (".key", ".pem", ".pfx", ".p12")

#: 字段名里出现这些词就当秘密处理（递归扫 JSON 配置）。
_SECRET_HINTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "apikey",
    "api_key",
    "webhook",
    "device_key",
    "encrypted",
    "authorization",
    "master_key",
)

#: ops.db 里**整表清空**的个人记录。
PERSONAL_TABLES = (
    "stock_agent_trades",
    "stock_agent_funding",
    "stock_agent_equity",
    "stock_agent_runs",
    "stock_agent_profiles",
    "guardian_diary_preferences",
    "job_runs",
    "paper_cabins",
    "paper_positions",
    "paper_fills",
    "paper_rejects",
    "nextday_plans",
    "monitor_runs",
    "paper_style_profiles",
    "paper_lessons",
    "paper_mem_nodes",
    "paper_mem_edges",
    "alert_rules",
    "alert_hits",
    "leader_role_snapshots",
    "strategy_backtests",
    # AI 决策留痕含 prompt 原文与报价快照，属个人交易记录，绝不外发
    "ai_decisions",
    # 助手全套：对话原文、工具回执、运行事件、用量、授权凭据，以及**个人画像与
    # 长期记忆**（ai_assistant_profile / ai_memories）。这批表原来一张都没登记，
    # 分享包会把「我跟 AI 说过的每一句话」连同画像一起发出去。
    "ai_sessions",
    "ai_messages",
    "ai_agent_runs",
    "ai_agent_events",
    "ai_usage_daily",
    "ai_execution_grants",
    "ai_assistant_profile",
    "ai_memories",
)

#: 个人表的**命名约定**。新表只要落在这些前缀里就必须进 PERSONAL_TABLES；
#: 回归测试对着真实建出来的 ops.db 卡这条（tests/ai/test_share_pack_ai_tables.py）。
#: 靠人记得改清单是靠不住的——上面那八张 AI 表就是这么漏掉的。
PERSONAL_TABLE_PREFIXES = ("ai_", "paper_mem", "stock_agent_")

#: ops.db `meta` 只放行这些键（`*` 结尾为前缀匹配）。其余一律不外发。
META_ALLOWLIST = (
    "schema_version",
    "wecom_screen_template",
    "market_sync_settings",
    "watch_tuning:*",
)


def _is_secret_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(hint in lowered for hint in _SECRET_HINTS)


def scrub_secrets(value: Any, *, stripped: list[str], path: str = "") -> Any:
    """递归清掉 JSON 里的秘密字段；保留结构，值置空。"""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            where = f"{path}.{key}" if path else str(key)
            if _is_secret_key(key):
                if item not in (None, "", {}, []):
                    stripped.append(where)
                out[key] = "" if isinstance(item, str) else None
                continue
            out[key] = scrub_secrets(item, stripped=stripped, path=where)
        return out
    if isinstance(value, list):
        return [
            scrub_secrets(item, stripped=stripped, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    return value


def sanitize_json_file(src: Path, dest: Path) -> list[str]:
    """脱敏一份 JSON 配置；解析失败时**不外发**（宁可漏功能不可漏密钥）。"""
    stripped: list[str] = []
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [f"{src.name}: 解析失败，已整份跳过"]
    cleaned = scrub_secrets(raw, stripped=stripped)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return [f"{src.name}: {item}" for item in stripped]


def _meta_allowed(key: str) -> bool:
    for rule in META_ALLOWLIST:
        if rule.endswith("*") and key.startswith(rule[:-1]):
            return True
        if key == rule:
            return True
    return False


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _strip_url_credentials(url: str) -> str:
    """去掉 URL 里的 userinfo 与 query，保留可分享的端点骨架。

    自建网关常把 key 写进 `https://user:pass@host/...` 或 `?key=...`。
    解析失败时整条丢弃——宁可少给端点，不可漏密钥。
    """
    if not url.strip():
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if not parts.hostname:
        return "" if ("@" in url or "?" in url) else url
    netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def sanitize_ops_db(src: Path, dest: Path) -> list[str]:
    """复制 ops.db 后就地抹掉密钥与个人记录，返回处理说明。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    notes: list[str] = []
    conn = sqlite3.connect(dest)
    conn.row_factory = sqlite3.Row
    try:
        for table in PERSONAL_TABLES:
            if not _table_exists(conn, table):
                continue
            count = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            if count:
                conn.execute(f"DELETE FROM {table}")
                notes.append(f"ops.db: 清空 {table}（{count} 行个人记录）")

        if _table_exists(conn, "llm_providers"):
            count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM llm_providers WHERE encrypted_key IS NOT NULL"
                ).fetchone()[0]
            )
            # proxy_url 常见 http://user:pass@host 形态，base_url 也可能把 key 塞在
            # userinfo 或 query 里——只清 encrypted_key 挡不住这两条。
            conn.execute(
                "UPDATE llm_providers SET encrypted_key = NULL, key_last4 = '', proxy_url = ''"
            )
            for row in conn.execute("SELECT id, base_url FROM llm_providers").fetchall():
                cleaned = _strip_url_credentials(str(row["base_url"] or ""))
                if cleaned != str(row["base_url"] or ""):
                    conn.execute(
                        "UPDATE llm_providers SET base_url = ? WHERE id = ?",
                        (cleaned, row["id"]),
                    )
            if count:
                notes.append(f"ops.db: 抹掉 {count} 个 LLM 供应商密钥")

        if _table_exists(conn, "jobs"):
            stripped_jobs = 0
            for row in conn.execute("SELECT id, config_json FROM jobs").fetchall():
                try:
                    config = json.loads(row["config_json"] or "{}")
                except json.JSONDecodeError:
                    config = {}
                marks: list[str] = []
                cleaned = scrub_secrets(config, stripped=marks)
                if marks:
                    stripped_jobs += 1
                conn.execute(
                    "UPDATE jobs SET config_json = ?, last_run_at = '', last_status = ''"
                    " WHERE id = ?",
                    (json.dumps(cleaned, ensure_ascii=False), row["id"]),
                )
            if stripped_jobs:
                notes.append(f"ops.db: 抹掉 {stripped_jobs} 个任务配置里的密钥/Webhook")

        if _table_exists(conn, "meta"):
            removed = 0
            for row in conn.execute("SELECT key FROM meta").fetchall():
                if _meta_allowed(str(row["key"])):
                    continue
                conn.execute("DELETE FROM meta WHERE key = ?", (row["key"],))
                removed += 1
            if removed:
                notes.append(f"ops.db: 移除 {removed} 条不在白名单的运维设置")

        conn.commit()
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()
    return notes


def sanitize_mcp_json(src: Path, dest: Path) -> list[str]:
    """MCP 只留接入骨架：URL、工具清单、备注；token / headers 一律抹掉。"""
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["mcp.json: 解析失败，已整份跳过"]
    servers = raw.get("mcpServers") if isinstance(raw, Mapping) else None
    if not isinstance(servers, Mapping):
        return ["mcp.json: 结构异常，已整份跳过"]

    notes: list[str] = []
    cleaned_servers: dict[str, Any] = {}
    for name, cfg in servers.items():
        if not isinstance(cfg, Mapping):
            continue
        had_secret = any(_is_secret_key(key) and cfg.get(key) for key in cfg)
        cleaned_servers[name] = {
            key: value
            for key, value in cfg.items()
            if key in {"url", "tools", "tools_synced_at", "note", "disabled", "proxy_url"}
        }
        if had_secret:
            notes.append(f"mcp.json: 抹掉 {name} 的 API Key")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps({**raw, "mcpServers": cleaned_servers}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return notes


def find_forbidden_files(root: Path) -> list[str]:
    """打包前最后一道闸：staging 里不该出现的秘密文件。"""
    hits: list[str] = []
    if not root.is_dir():
        return hits
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name in FORBIDDEN_FILE_NAMES or name.endswith(FORBIDDEN_SUFFIXES):
            hits.append(str(path.relative_to(root)))
    return sorted(hits)


__all__ = [
    "FORBIDDEN_FILE_NAMES",
    "FORBIDDEN_SUFFIXES",
    "META_ALLOWLIST",
    "PERSONAL_TABLES",
    "PERSONAL_TABLE_PREFIXES",
    "find_forbidden_files",
    "sanitize_json_file",
    "sanitize_mcp_json",
    "sanitize_ops_db",
    "scrub_secrets",
]
