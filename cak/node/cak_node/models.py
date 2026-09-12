"""Wire types. The agent response shape is normative (PRD §11.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgentStatus = Literal["ok", "i_dont_know", "error"]


class Citation(BaseModel):
    """A pointer a human can check: which file, where in it, and the words."""

    file_id: str
    title: str
    locator: str
    excerpt: str
    sha256: str | None = None
    source_url: str | None = None


class Office(BaseModel):
    """The authority to call when the device cannot help (PRD §19)."""

    name: str
    phone: str | None = None
    address: str | None = None
    url: str | None = None


class AgentMeta(BaseModel):
    """Non-normative diagnostics. Contains no personal data (PRD §13)."""

    locale_id: str
    pack_version: str
    retrieval_max_score: float = 0.0
    retrieval_min_score: float = 0.0
    files_used: list[str] = Field(default_factory=list)
    refusal_category: str | None = None
    generator: str | None = None
    grounding_failure: str | None = None


class AgentResponse(BaseModel):
    """The only thing ``POST /agent/query`` ever returns."""

    model_config = ConfigDict(extra="forbid")

    status: AgentStatus
    language: str
    answer_markdown: str
    citations: list[Citation] = Field(default_factory=list)
    office: Office
    disclaimer: str
    meta: AgentMeta | None = None


class AgentQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    language: str | None = None


class HealthResponse(BaseModel):
    """PRD §6.2: disk, model loaded, file count, last pack version."""

    status: Literal["ok", "degraded"]
    version: str
    locale_id: str
    pack_version: str
    official_file_count: int
    indexed_chunk_count: int
    index_skipped: list[str] = Field(default_factory=list)
    generator: str
    # Whether a language model is loaded. False is normal and healthy with the
    # extractive generator, which has no model; it is a problem only when
    # `generator` is "ollama".
    model_loaded: bool
    changelog_seq: int | None = None
    changelog_ok: bool | None = None
    disk_free_bytes: int | None = None
    disk_total_bytes: int | None = None
    offline: bool = True


class StewardLoadResult(BaseModel):
    """Summary of one steward file load (PRD §12.3)."""

    accepted: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    changelog_seq: int | None = None
    indexed_chunk_count: int = 0


class VerifyFileResult(BaseModel):
    """Answer to 'is this file the one the log says was on the node?'"""

    sha256: str
    known: bool
    records: list[dict] = Field(default_factory=list)


class OfficialDirVerification(BaseModel):
    """Whole-directory integrity report (PRD §23: tamper detection)."""

    ok: bool
    checked: int
    mismatched: list[dict] = Field(default_factory=list)
    unlogged: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
