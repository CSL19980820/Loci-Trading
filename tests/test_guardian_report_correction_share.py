"""Published historical report links must disclose that a correction exists."""
import json
import sqlite3

from src.ops.application.guardian_report_document import render_shared_document
from src.ops.application.guardian_report_share import load_guardian_reference


def test_archived_share_points_to_current_correction(tmp_path):
    database = tmp_path / "palace.db"
    old = {"revision": 1, "created_at": "2026-09-23T16:10:31+08:00", "share_token": "old-token"}
    current = {"revision": 2, "created_at": "2026-09-23T18:00:00+08:00", "share_token": "new-token"}
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE guardian_reports(report_key TEXT, status TEXT, result_json TEXT)")
        conn.execute("CREATE TABLE guardian_report_revisions(report_key TEXT, revision INTEGER, result_json TEXT)")
        conn.execute("INSERT INTO guardian_reports VALUES(?,?,?)",
                     ("daily:2026-09-23", "success", json.dumps(current)))
        conn.execute("INSERT INTO guardian_report_revisions VALUES(?,?,?)",
                     ("daily:2026-09-23", 1, json.dumps(old)))
    reference = {"period": "daily", "day": "2026-09-23", "revision": 1,
                 "created_at": old["created_at"], "database": {"relative": "palace.db"}}

    archived = load_guardian_reference(reference, "old-token", root=tmp_path)
    assert archived["_superseded"] is True
    assert archived["_superseded_by"] == "/shared/reports/new-token"
    html = render_shared_document([], title="日复盘", owner="天才交易员",
                                  created_at=old["created_at"], superseded=True,
                                  replacement_url=archived["_superseded_by"])
    assert "此为已归档的旧版报告" in html
    assert 'href="/shared/reports/new-token"' in html


def test_pending_correction_marks_old_share_without_link(tmp_path):
    database = tmp_path / "palace.db"
    old = {"revision": 1, "created_at": "2026-09-23T16:10:31+08:00", "share_token": "old-token"}
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE guardian_reports(report_key TEXT, status TEXT, result_json TEXT)")
        conn.execute("CREATE TABLE guardian_report_revisions(report_key TEXT, revision INTEGER, result_json TEXT)")
        conn.execute("INSERT INTO guardian_reports VALUES(?,?,?)",
                     ("daily:2026-09-23", "failed", '{}'))
        conn.execute("INSERT INTO guardian_report_revisions VALUES(?,?,?)",
                     ("daily:2026-09-23", 1, json.dumps(old)))
    reference = {"period": "daily", "day": "2026-09-23", "revision": 1,
                 "created_at": old["created_at"], "database": {"relative": "palace.db"}}

    archived = load_guardian_reference(reference, "old-token", root=tmp_path)
    assert archived["_superseded"] is True
    assert archived["_superseded_by"] == ""
