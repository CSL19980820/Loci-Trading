"""分享包脱敏：密钥与个人记录不得出机器。"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from src.ops.application.share_pack_sanitize import (
    find_forbidden_files,
    sanitize_json_file,
    sanitize_mcp_json,
    sanitize_ops_db,
    scrub_secrets,
)
from src.ops.infrastructure.store import OpsStore


def _seed_ops_db(path: Path) -> None:
    with OpsStore(path) as store:
        store.create_job(
            name="推送·企微",
            kind="notify",
            cron="0 15 * * 1-5",
            config={"template": "screen", "webhook": "https://qyapi.weixin.qq.com/x?key=abcd1234"},
            enabled=True,
        )
        store.set_setting("wecom_webhook", {"url": "https://qyapi.weixin.qq.com/x?key=abcd1234"})
        store.set_setting("wecom_screen_template", {"preset": "default"})
        store.set_setting("watch_tuning:dragon-return", {"stages": {"market_gate": True}})
        store.ensure_paper_cabin("dragon-return")
        store.add_paper_lesson(
            {"slug": "dragon-return", "trade_date": "2026-08-07", "kind": "mistake", "title": "高开追了"}
        )
        store.record_leader_roles(
            "dragon-return",
            trade_date="2026-08-07",
            observed_at="2026-08-07T09:40:00+08:00",
            gate_state="dragon",
            entries=[{"code": "600001", "role": "leader"}],
        )


def test_ops_db_sanitize_drops_secrets_and_personal_records(tmp_path: Path) -> None:
    src = tmp_path / "ops.db"
    _seed_ops_db(src)
    dest = tmp_path / "out" / "ops.db"

    notes = sanitize_ops_db(src, dest)

    conn = sqlite3.connect(dest)
    try:
        meta = {row[0] for row in conn.execute("SELECT key FROM meta").fetchall()}
        jobs = conn.execute("SELECT config_json FROM jobs").fetchall()
        lessons = conn.execute("SELECT COUNT(*) FROM paper_lessons").fetchone()[0]
        cabins = conn.execute("SELECT COUNT(*) FROM paper_cabins").fetchone()[0]
        roles = conn.execute("SELECT COUNT(*) FROM leader_role_snapshots").fetchone()[0]
    finally:
        conn.close()

    # 白名单外的运维设置一律不外发；企微 Webhook 属于秘密
    assert "wecom_webhook" not in meta
    assert "wecom_screen_template" in meta
    assert "watch_tuning:dragon-return" in meta
    # 任务定义保留，但配置里的 webhook 被抹掉
    assert "abcd1234" not in jobs[0][0]
    assert "template" in jobs[0][0]
    # 个人交易记录整表清空
    assert lessons == 0 and cabins == 0 and roles == 0
    assert any("wecom" in note or "Webhook" in note for note in notes)


def test_mcp_sanitize_keeps_endpoint_but_drops_api_key(tmp_path: Path) -> None:
    src = tmp_path / "mcp.json"
    src.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "wudao": {
                        "url": "https://stock.example.com/api/mcp",
                        "encrypted_token": "ZW5jcnlwdGVk",
                        "token_last4": "1234",
                        "headers": {"Authorization": "Bearer super-secret"},
                        "tools": [{"name": "kline"}],
                        "note": "悟道",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    dest = tmp_path / "out" / "mcp.json"

    notes = sanitize_mcp_json(src, dest)
    text = dest.read_text(encoding="utf-8")
    payload = json.loads(text)
    server = payload["mcpServers"]["wudao"]

    assert "super-secret" not in text
    assert "ZW5jcnlwdGVk" not in text
    assert server["url"] == "https://stock.example.com/api/mcp"
    assert server["tools"] == [{"name": "kline"}]
    assert notes


def test_scrub_secrets_walks_nested_config() -> None:
    stripped: list[str] = []
    cleaned = scrub_secrets(
        {"a": {"api_key": "xxx", "keep": 1}, "list": [{"password": "p"}]},
        stripped=stripped,
    )

    assert cleaned["a"]["api_key"] == ""
    assert cleaned["a"]["keep"] == 1
    assert cleaned["list"][0]["password"] == ""
    assert stripped == ["a.api_key", "list[0].password"]


def test_unparsable_config_is_skipped_rather_than_shipped(tmp_path: Path) -> None:
    src = tmp_path / "loci.config.json"
    src.write_text("{ not json", encoding="utf-8")
    dest = tmp_path / "out" / "loci.config.json"

    notes = sanitize_json_file(src, dest)

    assert not dest.exists()
    assert "跳过" in notes[0]


def test_forbidden_files_are_detected_anywhere_in_the_tree(tmp_path: Path) -> None:
    (tmp_path / "nested" / "deep").mkdir(parents=True)
    (tmp_path / "nested" / ".palace_ai_master_key").write_text("k", encoding="utf-8")
    (tmp_path / "nested" / "deep" / "server.pem").write_text("k", encoding="utf-8")
    (tmp_path / "ok.txt").write_text("fine", encoding="utf-8")

    hits = find_forbidden_files(tmp_path)

    assert len(hits) == 2
    assert any("master_key" in hit for hit in hits)
    assert any("server.pem" in hit for hit in hits)
