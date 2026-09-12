"""PRD §17.7 — the no-PII linter.

Three layers, because a rule that only lives in a document is a rule that gets
broken by a well-meaning contributor on a deadline:

1. A static scan of the source for forbidden column names in SQL.
2. The runtime schema check that refuses to open a database containing one.
3. Behavioural tests that a real question with a name in it is never stored.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from cak_node.privacy import FORBIDDEN_COLUMNS, looks_like_pii, pii_kinds, query_hash, redact
from cak_node.storage import PrivacyViolation, Store, assert_no_pii_columns

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = [REPO_ROOT / "node", REPO_ROOT / "changelog", REPO_ROOT / "sms"]

# Statements that would put a column into the database.
_DDL_RE = re.compile(
    r"(?is)\b(create\s+(?:virtual\s+)?table|alter\s+table\s+\w+\s+add(?:\s+column)?|insert\s+into)\b"
    r"(.{0,2000}?)(?:;|\"\"\"|''')"
)


def iter_source_files() -> list[Path]:
    files: list[Path] = []
    for directory in SOURCE_DIRS:
        files.extend(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def test_no_forbidden_columns_in_any_sql_statement() -> None:
    """Fail CI if code writes ssn, date_of_birth or friends into cak.db."""
    offenders: list[str] = []
    for path in iter_source_files():
        source = path.read_text(encoding="utf-8")
        for match in _DDL_RE.finditer(source):
            body = match.group(2).lower()
            for column in FORBIDDEN_COLUMNS:
                if re.search(rf"\b{re.escape(column)}\b", body):
                    line = source[: match.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{line} writes {column!r}")
    assert not offenders, "personal-data columns reached SQL:\n" + "\n".join(offenders)


def test_the_linter_would_actually_catch_a_violation(tmp_path: Path) -> None:
    """A linter nobody has seen fail is a linter nobody should trust."""
    bad = tmp_path / "bad_module.py"
    bad.write_text(
        'QUERY = """\nCREATE TABLE voters (id INTEGER, date_of_birth TEXT);\n"""\n',
        encoding="utf-8",
    )
    source = bad.read_text(encoding="utf-8")
    hits = [
        column
        for match in _DDL_RE.finditer(source)
        for column in FORBIDDEN_COLUMNS
        if re.search(rf"\b{re.escape(column)}\b", match.group(2).lower())
    ]
    assert "date_of_birth" in hits


def test_runtime_schema_check_rejects_a_pii_column(tmp_path: Path) -> None:
    db = sqlite3.connect(tmp_path / "bad.db")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, date_of_birth TEXT)")
    with pytest.raises(PrivacyViolation) as excinfo:
        assert_no_pii_columns(db)
    assert "date_of_birth" in str(excinfo.value)
    db.close()


def test_real_schema_passes_the_runtime_check(tmp_path: Path) -> None:
    store = Store(tmp_path / "cak.db")
    store.close()


def test_query_text_is_not_stored_by_default(tmp_path: Path) -> None:
    """PRD §13: chat logs off by default."""
    store = Store(tmp_path / "cak.db", log_queries=False)
    store.record_query("Where do I vote?", "en", "ok", files_used=["official/sites.md"])
    rows = store._db.execute("SELECT query_digest, query_text FROM query_log").fetchall()
    assert rows[0]["query_text"] is None
    assert rows[0]["query_digest"].startswith("sha256:")
    store.close()


def test_opted_in_logging_still_drops_anything_that_looks_personal(tmp_path: Path) -> None:
    store = Store(tmp_path / "cak.db", log_queries=True)
    store.record_query("When is early voting?", "en", "ok")
    store.record_query("My name is Jane Doe, where do I vote?", "en", "ok")
    store.record_query("I live at 123 Main Street, am I in the right precinct?", "en", "ok")
    rows = store._db.execute("SELECT query_text FROM query_log ORDER BY id").fetchall()
    assert rows[0]["query_text"] == "When is early voting?"
    assert rows[1]["query_text"] is None
    assert rows[2]["query_text"] is None
    store.close()


def test_query_hash_is_stable_and_not_reversible() -> None:
    assert query_hash("Where do I vote?") == query_hash("  where   do i VOTE? ")
    assert query_hash("Where do I vote?") != query_hash("When is early voting?")
    assert "vote" not in query_hash("Where do I vote?")


@pytest.mark.parametrize(
    "text,kind",
    [
        ("My SSN is 123-45-6789", "ssn"),
        ("call me at 555-123-4567", "phone"),
        ("jane@example.com", "email"),
        ("born 1962-04-11", "dob"),
        ("I live at 123 Main Street", "street_address"),
        ("my name is Jane", "self_identification"),
    ],
)
def test_pii_patterns_fire(text: str, kind: str) -> None:
    assert looks_like_pii(text)
    assert kind in pii_kinds(text)


@pytest.mark.parametrize(
    "text",
    [
        "When is early voting?",
        "Where do I vote?",
        "What are the hours on election day?",
        "Is the library wheelchair accessible?",
    ],
)
def test_ordinary_questions_are_not_flagged(text: str) -> None:
    assert not looks_like_pii(text), pii_kinds(text)


def test_redaction_replaces_spans() -> None:
    redacted = redact("My SSN is 123-45-6789 and I live at 42 Oak Avenue")
    assert "123-45-6789" not in redacted
    assert "42 Oak Avenue" not in redacted
    assert "[redacted:ssn]" in redacted


def test_metrics_are_counters_only(service) -> None:
    service.answer("When is early voting?")
    service.answer("Who should I vote for?")
    counters = service.metrics()
    assert counters["queries_total"] == 2
    assert counters["queries_ok"] == 1
    assert counters["refusals_partisan"] == 1
    assert all(isinstance(value, int) for value in counters.values())


def test_metrics_endpoint_exposes_no_text(client) -> None:
    client.post("/agent/query", json={"text": "My name is Jane Doe. Where do I vote?"})
    body = client.get("/metrics").text
    assert "Jane" not in body
    assert "name" not in body.lower().replace("no personal data", "")


def test_field_report_queue_rejects_forbidden_columns(service) -> None:
    for column in ["ssn", "date_of_birth", "voter_name", "ballot_choice"]:
        with pytest.raises(PrivacyViolation):
            service.store.enqueue_field_report("wait_time", "site01", {column: "x"}, "test")
