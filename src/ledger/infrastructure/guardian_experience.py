"""Versioned tenant-local memory, committed atomically with its source review."""
import json
from datetime import datetime, timezone

from src.ledger.domain.guardian_experience import (
    MAX_EXPERIENCES, MAX_EXPERIENCE_CHARACTERS, experience_text, validate_experience,
)

EXPERIENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS guardian_experience_versions (
    revision INTEGER PRIMARY KEY AUTOINCREMENT,
    source_report TEXT NOT NULL, source_revision INTEGER NOT NULL,
    trade_date TEXT NOT NULL, created_at TEXT NOT NULL,
    items_json TEXT NOT NULL, origins_json TEXT NOT NULL,
    UNIQUE(source_report, source_revision)
);
"""


class GuardianExperienceMixin:
    def experience(self, *, as_of: str | None = None, day: str | None = None) -> dict:
        clauses, args = [], []
        if as_of:
            clauses.append("julianday(created_at)<=julianday(?)")
            args.append(as_of)
        if day:
            clauses.append("trade_date<=?")
            args.append(day)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        row = self.conn.execute("SELECT * FROM guardian_experience_versions" + where +
                                " ORDER BY revision DESC LIMIT 1", args).fetchone()
        value = dict(row) if row else {"revision": 0, "source_report": "", "source_revision": 0,
                                       "trade_date": "", "created_at": ""}
        value['items'] = json.loads(value.pop('items_json')) if row else []
        value['origins'] = json.loads(value.pop('origins_json')) if row else {}
        value['text'] = experience_text(value['items'])
        value.update(characters=len(value['text']), max_characters=MAX_EXPERIENCE_CHARACTERS,
                     max_items=MAX_EXPERIENCES)
        return value

    def _save_experience(self, items: list[dict], *, source_report: str, source_revision: int,
                         day: str, expected_revision: int) -> None:
        """Caller owns the report transaction. A stale report cannot erase newer learning."""
        items = validate_experience(items)
        current = self.experience()
        if current['revision'] != expected_revision:
            raise ValueError("经验沉淀已被其他复盘更新，请基于最新版本重新生成")
        if current['trade_date'] > day:
            raise ValueError("历史复盘不能覆盖较新日期的经验沉淀")
        old = {item['id']: item for item in current['items']}
        origin = {'source_report': source_report, 'source_revision': source_revision}
        origins = {item['id']: current['origins'].get(item['id'], origin)
                   if old.get(item['id']) == item else origin for item in items}
        self.conn.execute("INSERT INTO guardian_experience_versions "
                          "(source_report,source_revision,trade_date,created_at,items_json,origins_json) VALUES(?,?,?,?,?,?)",
                          (source_report, source_revision, day, datetime.now(timezone.utc).isoformat(),
                           json.dumps(items, ensure_ascii=False), json.dumps(origins, ensure_ascii=False)))

    def daily_learning(self, start: str, end: str, as_of: str) -> list[dict]:
        # Query the whole week directly: unrelated reports cannot crowd daily learning out.
        rows = self.conn.execute("SELECT report_key,result_json FROM guardian_reports "
                                 "WHERE period='daily' AND status='success' AND trade_date BETWEEN ? AND ? "
                                 "ORDER BY trade_date", (start, end)).fetchall()
        result = []
        cutoff = datetime.fromisoformat(as_of)
        for row in rows:
            report = json.loads(row['result_json'])
            stamp = report.get('created_at')
            if not stamp:
                continue
            created = datetime.fromisoformat(stamp)
            if created.replace(tzinfo=created.tzinfo or timezone.utc) > cutoff:
                continue
            analysis = report.get('analysis') or {}
            result.append({'report_key': row['report_key'], 'revision': report.get('revision', 1),
                           'lessons': analysis.get('lessons', []),
                           'research_notes': analysis.get('research_notes', [])})
        return result
