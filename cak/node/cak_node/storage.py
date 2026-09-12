"""SQLite state: counters, the steward audit trail, and the field-report queue.

Normative source: PRD §12.1 (SQLite, WAL), §13 (privacy), §7.4 (store-and-forward,
append-only, never overwrite), §17.7 (a no-PII linter must fail CI if PII columns
reach cak.db).

The privacy rule is enforced twice on purpose: statically by the linter test,
and at runtime by :func:`assert_no_pii_columns`, which refuses to open a
database whose schema has grown a forbidden column. A future contributor adding
``date_of_birth`` gets a crash on the bench, not a subpoena in the field.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cak_node.privacy import FORBIDDEN_COLUMNS, looks_like_pii, query_hash

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Retrieval-quality counters. Never stores a raw question unless the steward
-- opted in AND the text carries no PII pattern (PRD §13).
CREATE TABLE IF NOT EXISTS query_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT    NOT NULL,
    query_digest      TEXT    NOT NULL,
    query_text        TEXT,
    language          TEXT    NOT NULL,
    status            TEXT    NOT NULL,
    refusal_category  TEXT,
    max_score         REAL,
    files_used        TEXT
);

-- Every steward write to official/. PRD §6.2: audit log of file replacements.
CREATE TABLE IF NOT EXISTS steward_audit (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,
    actor_role    TEXT    NOT NULL,
    action        TEXT    NOT NULL,
    detail        TEXT,
    changelog_seq INTEGER
);

-- Offline store-and-forward queue for field reports (PRD §7.4). Append-only:
-- a sync marks a row forwarded, it never edits or deletes the report.
CREATE TABLE IF NOT EXISTS field_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    site_id     TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    synced_at   TEXT,
    sync_target TEXT
);

CREATE INDEX IF NOT EXISTS field_reports_pending
    ON field_reports (synced_at) WHERE synced_at IS NULL;
"""


class PrivacyViolation(Exception):
    """Raised when a write would put personal data in cak.db."""


def utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class FieldReport:
    """One queued report, as returned to the steward dashboard."""

    id: int
    ts: str
    kind: str
    site_id: str
    payload: dict[str, Any]
    source: str
    synced_at: str | None
    sync_target: str | None


class Store:
    """The node's SQLite database."""

    def __init__(self, path: Path | str, log_queries: bool = False) -> None:
        self.path = Path(path)
        self.log_queries = log_queries
        # One connection shared across request threads, serialized by a lock.
        # A Pi serving a room full of people does a handful of writes a minute;
        # a connection pool would be machinery for a problem this never has.
        self._lock = threading.Lock()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_SCHEMA)
        self._db.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._db.commit()
        assert_no_pii_columns(self._db)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _write(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Run a statement and commit. Returns rowcount or lastrowid."""
        with self._lock:
            cursor = self._db.execute(sql, params)
            self._db.commit()
            return cursor.lastrowid if cursor.lastrowid else cursor.rowcount

    def _read(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    # -- query counters ------------------------------------------------------
    def record_query(
        self,
        text: str,
        language: str,
        status: str,
        refusal_category: str | None = None,
        max_score: float | None = None,
        files_used: list[str] | None = None,
    ) -> None:
        """Record that a question was asked, without recording who asked it.

        The digest always goes in. The text goes in only if the steward turned
        on query logging *and* the question carries no name/address/phone
        pattern (PRD §6.3 step 7).
        """
        stored_text = None
        if self.log_queries and not looks_like_pii(text):
            stored_text = " ".join(text.split())[:500]
        with self._lock:
            self._db.execute(
                """
                INSERT INTO query_log
                    (ts, query_digest, query_text, language, status, refusal_category,
                     max_score, files_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utcnow(),
                    query_hash(text),
                    stored_text,
                    language,
                    status,
                    refusal_category,
                    max_score,
                    json.dumps(files_used or []),
                ),
            )
            self._db.commit()

    def counters(self) -> dict[str, int]:
        """Aggregates for ``/metrics``. Counts only — no text, no identities."""
        rows = self._read("SELECT status, COUNT(*) AS n FROM query_log GROUP BY status")
        counters = {f"queries_{row['status']}": int(row["n"]) for row in rows}
        counters["queries_total"] = sum(counters.values())
        refusals = self._read(
            """
            SELECT refusal_category, COUNT(*) AS n
            FROM query_log WHERE refusal_category IS NOT NULL
            GROUP BY refusal_category
            """
        )
        for row in refusals:
            counters[f"refusals_{row['refusal_category']}"] = int(row["n"])
        counters["steward_writes"] = int(
            self._read("SELECT COUNT(*) AS n FROM steward_audit")[0]["n"]
        )
        counters["field_reports_total"] = int(
            self._read("SELECT COUNT(*) AS n FROM field_reports")[0]["n"]
        )
        counters["field_reports_pending"] = int(
            self._read("SELECT COUNT(*) AS n FROM field_reports WHERE synced_at IS NULL")[0]["n"]
        )
        return counters

    # -- steward audit -------------------------------------------------------
    def audit(
        self,
        action: str,
        detail: str | None = None,
        actor_role: str = "steward",
        changelog_seq: int | None = None,
    ) -> None:
        self._write(
            """
            INSERT INTO steward_audit (ts, actor_role, action, detail, changelog_seq)
            VALUES (?, ?, ?, ?, ?)
            """,
            (utcnow(), actor_role, action, detail, changelog_seq),
        )

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._read("SELECT * FROM steward_audit ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in rows]

    # -- field reports (store and forward) -----------------------------------
    def enqueue_field_report(
        self,
        kind: str,
        site_id: str,
        payload: dict[str, Any],
        source: str = "sms",
    ) -> int:
        """Queue a report for later sync. Rejects payloads carrying PII."""
        offending = sorted(set(payload) & FORBIDDEN_COLUMNS)
        if offending:
            raise PrivacyViolation(
                "field report rejected: PII fields " + ", ".join(offending) + " (PRD §13)"
            )
        for key, value in payload.items():
            if isinstance(value, str) and looks_like_pii(value):
                raise PrivacyViolation(
                    f"field report rejected: field {key!r} looks like personal data (PRD §13)"
                )
        return self._write(
            """
            INSERT INTO field_reports (ts, kind, site_id, payload, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (utcnow(), kind, site_id, json.dumps(payload, sort_keys=True), source),
        )

    def pending_field_reports(self, limit: int = 500) -> list[FieldReport]:
        rows = self._read(
            "SELECT * FROM field_reports WHERE synced_at IS NULL ORDER BY id LIMIT ?",
            (limit,),
        )
        return [_as_report(row) for row in rows]

    def all_field_reports(self, limit: int = 1000) -> list[FieldReport]:
        rows = self._read("SELECT * FROM field_reports ORDER BY id DESC LIMIT ?", (limit,))
        return [_as_report(row) for row in rows]

    def mark_synced(self, report_ids: list[int], target: str) -> int:
        """Mark reports forwarded. Never deletes or rewrites the report itself.

        Already-synced rows are left alone, so a retried sync cannot lose or
        duplicate a report (PRD §7.4: append-only, never overwrite).
        """
        if not report_ids:
            return 0
        placeholders = ",".join("?" for _ in report_ids)
        with self._lock:
            cursor = self._db.execute(
                f"""
                UPDATE field_reports SET synced_at = ?, sync_target = ?
                WHERE id IN ({placeholders}) AND synced_at IS NULL
                """,
                (utcnow(), target, *report_ids),
            )
            self._db.commit()
            return cursor.rowcount


def _as_report(row: sqlite3.Row) -> FieldReport:
    return FieldReport(
        id=int(row["id"]),
        ts=row["ts"],
        kind=row["kind"],
        site_id=row["site_id"],
        payload=json.loads(row["payload"]),
        source=row["source"],
        synced_at=row["synced_at"],
        sync_target=row["sync_target"],
    )


def assert_no_pii_columns(db: sqlite3.Connection) -> None:
    """Refuse to run against a schema containing a forbidden column.

    PRD §17.7 asks for a linter. A linter can be silenced; this cannot.
    """
    offenders: list[str] = []
    tables = db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()
    for table in tables:
        name = table["name"]
        if name.startswith("sqlite_"):
            continue
        for column in db.execute(f"PRAGMA table_info('{name}')").fetchall():
            if column["name"].lower() in FORBIDDEN_COLUMNS:
                offenders.append(f"{name}.{column['name']}")
    if offenders:
        raise PrivacyViolation(
            "cak.db schema contains forbidden personal-data columns: "
            + ", ".join(sorted(offenders))
            + " (PRD §13, §17.7)"
        )
