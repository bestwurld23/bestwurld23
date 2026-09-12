"""PII guards.

Normative source: PRD §13 (privacy and data policy) and §0.4 (no PII in logs).

Two jobs:

1. ``looks_like_pii`` decides whether a free-text string may be persisted at all.
   Callers must treat ``True`` as "drop the text, keep only the hash".
2. ``FORBIDDEN_COLUMNS`` is the deny list enforced by :mod:`cak_node.storage` at
   DDL time and by the no-PII linter in the test suite (PRD §17.7).
"""

from __future__ import annotations

import hashlib
import re
from typing import Final

# Column / field names that must never appear in cak.db. Enforced at runtime by
# storage.assert_no_pii_columns and statically by tests/test_no_pii.py.
FORBIDDEN_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "ssn",
        "social_security_number",
        "date_of_birth",
        "dob",
        "birthdate",
        "voter_name",
        "first_name",
        "last_name",
        "full_name",
        "legal_name",
        "home_address",
        "street_address",
        "mailing_address",
        "phone_number",
        "mobile_number",
        "email_address",
        "drivers_license",
        "state_id_number",
        "tribal_enrollment_number",
        "ballot_choice",
        "voted_for",
        "fingerprint",
        "face_template",
        "iris_template",
    }
)

_PII_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone", re.compile(r"\b(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    ("dob", re.compile(r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b")),
    ("dob", re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/](?:19|20)\d{2}\b")),
    # "123 Main St", "45 Oak Avenue Apt 2"
    (
        "street_address",
        re.compile(
            r"\b\d{1,6}\s+[A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*)*\s+"
            r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive|Ct|Court|"
            r"Way|Pl|Place|Ter|Terrace|Hwy|Highway)\b\.?",
            re.IGNORECASE,
        ),
    ),
    ("self_identification", re.compile(r"\bmy name is\b", re.IGNORECASE)),
    ("self_identification", re.compile(r"\bi(?:'m| am) [A-Z][a-z]+ [A-Z][a-z]+\b")),
    ("self_identification", re.compile(r"\bi live at\b", re.IGNORECASE)),
    ("id_number", re.compile(r"\b(?:ssn|social security)\b", re.IGNORECASE)),
)


def pii_kinds(text: str) -> list[str]:
    """Return the sorted, de-duplicated kinds of PII detected in ``text``."""
    found = {kind for kind, pattern in _PII_PATTERNS if pattern.search(text)}
    return sorted(found)


def looks_like_pii(text: str) -> bool:
    """True when ``text`` may contain personal data and must not be stored raw."""
    return bool(pii_kinds(text))


def redact(text: str) -> str:
    """Replace every detected PII span with a ``[redacted:<kind>]`` marker.

    Matching happens once, against the original text, and the replacements are
    applied by span. Substituting pattern by pattern would let a marker match a
    later pattern — ``[redacted:ssn]`` contains the word "ssn" — and nest.
    """
    spans: list[tuple[int, int, str]] = []
    for kind, pattern in _PII_PATTERNS:
        spans.extend((m.start(), m.end(), kind) for m in pattern.finditer(text))
    if not spans:
        return text

    # Earliest span wins; among those starting together, the longest.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    out: list[str] = []
    cursor = 0
    for start, end, kind in spans:
        if start < cursor:
            continue
        out.append(text[cursor:start])
        out.append(f"[redacted:{kind}]")
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def query_hash(text: str) -> str:
    """Stable, non-reversible handle for a query.

    Used for retrieval-quality counters. The raw text is never stored alongside
    it unless the steward opted in *and* :func:`looks_like_pii` is False.
    """
    normalized = " ".join(text.lower().split())
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
