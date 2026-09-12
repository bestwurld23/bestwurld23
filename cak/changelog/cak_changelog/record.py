"""Record schema and canonicalization for ``cak-changelog-1``.

Normative source: PRD §8.2.

This log covers *process files* — polling place lists, hours, registration
instructions. It never covers ballots or people (PRD §8.1, §2.2 N5). What it
proves is narrow and useful: "this is the polling-place list that was on the
node on Tuesday."
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA = "cak-changelog-1"

# Genesis has no predecessor; an all-zero digest marks the start of the chain.
GENESIS_PREV_HASH = "sha256:" + "0" * 64

Action = Literal[
    "genesis",
    "add_file",
    "replace_file",
    "remove_file",
    "pack_install",
    "note",
]

# Fields excluded from the hashed body: the hash itself, and the signature over it.
_UNHASHED_FIELDS = ("record_hash", "sig")


class LoggedFile(BaseModel):
    """One file as it stood when the record was written."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    media_type: str
    source: str | None = None


class ChangelogRecord(BaseModel):
    """One append-only entry."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_id: str = Field(default=SCHEMA, alias="schema")
    log_id: str
    seq: int = Field(ge=0)
    ts: str
    locale_id: str
    actor_role: str
    actor_id_hash: str | None = None
    action: Action
    files: list[LoggedFile] = Field(default_factory=list)
    note: str | None = None
    # Genesis only: the pack/steward public key the rest of the chain is signed with.
    pack_public_key: str | None = None
    prev_hash: str
    record_hash: str | None = None
    sig: str | None = None

    def hashable_body(self) -> dict[str, Any]:
        """The record minus its own hash and signature."""
        body = self.model_dump(by_alias=True, exclude_none=True)
        for field in _UNHASHED_FIELDS:
            body.pop(field, None)
        return body

    def compute_hash(self) -> str:
        return hash_body(self.hashable_body())

    def to_json_line(self) -> str:
        return canonical_json(self.model_dump(by_alias=True, exclude_none=True)).decode("utf-8")


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON: sorted keys, no spaces, UTF-8, no ASCII escaping.

    Two implementations must agree byte for byte or the chain is worthless, so
    this is the only serializer allowed to touch a record.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def hash_body(body: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(body)).hexdigest()


def parse_record(line: str) -> ChangelogRecord:
    return ChangelogRecord.model_validate(json.loads(line))
