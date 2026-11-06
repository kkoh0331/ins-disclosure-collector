from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    period_year INTEGER,
    period_kind TEXT NOT NULL,
    period_label TEXT NOT NULL,
    posted_date TEXT,
    detail_url TEXT NOT NULL UNIQUE,
    discovered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    source_url TEXT NOT NULL UNIQUE,
    local_path TEXT NOT NULL,
    text_path TEXT,
    sha256 TEXT,
    byte_count INTEGER,
    page_count INTEGER,
    downloaded_at TEXT,
    extracted_at TEXT
);
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attachment_id INTEGER NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    metric_key TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL,
    prior_value REAL,
    change_value REAL,
    unit TEXT,
    UNIQUE(attachment_id, metric_key)
);
CREATE INDEX IF NOT EXISTS idx_documents_period ON documents(period_year, period_kind);
CREATE INDEX IF NOT EXISTS idx_metrics_key ON metrics(metric_key);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_document(conn: sqlite3.Connection, disclosure: Any) -> int:
    conn.execute(
        """INSERT INTO documents
           (company, title, period_year, period_kind, period_label, posted_date, detail_url, discovered_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(detail_url) DO UPDATE SET
             title=excluded.title,
             period_year=excluded.period_year,
             period_kind=excluded.period_kind,
             period_label=excluded.period_label,
             posted_date=COALESCE(excluded.posted_date, documents.posted_date)""",
        (
            disclosure.company,
            disclosure.title,
            disclosure.period_year,
            disclosure.period_kind,
            disclosure.period_label,
            disclosure.posted_date,
            disclosure.detail_url,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    row = conn.execute(
        "SELECT id FROM documents WHERE detail_url = ?", (disclosure.detail_url,)
    ).fetchone()
    conn.commit()
    return int(row["id"])


def get_attachment_by_url(conn: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM attachments WHERE source_url = ?", (url,)
    ).fetchone()


def upsert_attachment(
    conn: sqlite3.Connection,
    document_id: int,
    filename: str,
    source_url: str,
    local_path: str,
    sha256: str,
    byte_count: int,
    text_path: str,
    page_count: int,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO attachments
           (document_id, filename, source_url, local_path, text_path, sha256,
            byte_count, page_count, downloaded_at, extracted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(source_url) DO UPDATE SET
             document_id=excluded.document_id,
             filename=excluded.filename,
             local_path=excluded.local_path,
             text_path=excluded.text_path,
             sha256=excluded.sha256,
             byte_count=excluded.byte_count,
             page_count=excluded.page_count,
             downloaded_at=excluded.downloaded_at,
             extracted_at=excluded.extracted_at""",
        (
            document_id,
            filename,
            source_url,
            local_path,
            text_path,
            sha256,
            byte_count,
            page_count,
            now,
            now,
        ),
    )
    row = conn.execute(
        "SELECT id FROM attachments WHERE source_url = ?", (source_url,)
    ).fetchone()
    conn.commit()
    return int(row["id"])


def replace_metrics(
    conn: sqlite3.Connection, attachment_id: int, metrics: list[dict[str, Any]]
) -> None:
    conn.execute("DELETE FROM metrics WHERE attachment_id = ?", (attachment_id,))
    conn.executemany(
        """INSERT INTO metrics
           (attachment_id, section, metric_key, metric_name, value, prior_value, change_value, unit)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                attachment_id,
                m["section"],
                m["metric_key"],
                m["metric_name"],
                m.get("value"),
                m.get("prior_value"),
                m.get("change"),
                m.get("unit"),
            )
            for m in metrics
        ],
    )
    conn.commit()


def export_csv(conn: sqlite3.Connection, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    exports = {
        "documents.csv": """SELECT company, title, period_year, period_kind, period_label,
                                   posted_date, detail_url
                            FROM documents ORDER BY posted_date DESC, id DESC""",
        "attachments.csv": """SELECT d.company, d.title, d.period_label, d.posted_date,
                                     a.filename, a.source_url, a.local_path, a.text_path,
                                     a.sha256, a.byte_count, a.page_count, a.downloaded_at
                              FROM attachments a JOIN documents d ON d.id = a.document_id
                              ORDER BY d.posted_date DESC, a.filename""",
        "metrics.csv": """SELECT d.company, d.title, d.period_label, d.posted_date,
                                  a.filename, m.section, m.metric_key, m.metric_name,
                                  m.value, m.prior_value, m.change_value, m.unit,
                                  a.source_url
                           FROM metrics m
                           JOIN attachments a ON a.id = m.attachment_id
                           JOIN documents d ON d.id = a.document_id
                           ORDER BY d.posted_date DESC, m.section, m.metric_key""",
    }
    for filename, query in exports.items():
        rows = conn.execute(query).fetchall()
        path = output_dir / filename
        with path.open("w", newline="", encoding="utf-8-sig") as output:
            if rows:
                writer = csv.writer(output)
                writer.writerow(rows[0].keys())
                writer.writerows([tuple(row) for row in rows])
            else:
                path.write_text("", encoding="utf-8-sig")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
