"""Locale pack loading and validation.

Normative source: PRD §10. A locale pack is configuration, never a fork: the
same node binary serves Englewood, a rural county, a chapter house, or an
invited EMB depending only on the directory handed to it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

LOCALE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){1,4}$")

# A pack must publicly disclaim these capabilities. The node refuses to load a
# pack that does not, so no deployment can quietly present itself as an
# eligibility authority (PRD §2.2 N3, §10.2 `does_not`).
REQUIRED_DISCLAIMERS: frozenset[str] = frozenset({"determine_eligibility", "collect_ballots"})

INDEXABLE_SUFFIXES: frozenset[str] = frozenset({".md", ".txt", ".csv", ".html", ".htm", ".pdf"})


class PackValidationError(Exception):
    """Raised when a pack.yaml or pack directory is not usable."""


class Authority(BaseModel):
    """The official body whose documents the pack redistributes."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    url: str | None = None
    phone: str | None = None
    address: str | None = None


class SmsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    wait_code: str = "WAIT"
    closed_code: str = "CLOSED"
    help_code: str = "HELP"


class PackManifest(BaseModel):
    """Typed view of ``pack.yaml`` (PRD §10.2)."""

    model_config = ConfigDict(extra="forbid")

    cak_pack_version: int
    locale_id: str
    name: str = Field(min_length=1)
    authority: Authority
    languages: Annotated[list[str], Field(min_length=1)]
    default_language: str
    retrieval_min_score: float = Field(ge=0.0, le=1.0)
    legal_banner: str = Field(min_length=1)
    time_zone: str = "UTC"
    sites_file: str | None = None
    official_dir: str = "official/"
    i18n_dir: str = "i18n/"
    sms: SmsConfig = SmsConfig()
    does_not: list[str] = Field(default_factory=list)
    pack_version: str = Field(min_length=1)
    files_license: str | None = None

    @field_validator("cak_pack_version")
    @classmethod
    def _supported_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"unsupported cak_pack_version {v!r}; this node speaks version 1")
        return v

    @field_validator("locale_id")
    @classmethod
    def _locale_shape(cls, v: str) -> str:
        if not LOCALE_ID_RE.match(v):
            raise ValueError(
                f"locale_id {v!r} must be lowercase dash-separated, e.g. 'us-il-chicago'"
            )
        return v

    @model_validator(mode="after")
    def _cross_field_rules(self) -> PackManifest:
        if self.default_language not in self.languages:
            raise ValueError(
                f"default_language {self.default_language!r} is not in languages {self.languages}"
            )
        missing = sorted(REQUIRED_DISCLAIMERS - set(self.does_not))
        if missing:
            raise ValueError(
                "does_not must declare " + ", ".join(missing) + " (PRD §2.2: these are non-goals)"
            )
        return self


class OfficialFile(BaseModel):
    """One indexable document plus whatever provenance the steward recorded."""

    model_config = ConfigDict(extra="forbid")

    file_id: str
    path: Path
    media_type: str
    bytes: int
    sha256: str
    title: str
    source_url: str | None = None
    retrieved_at: str | None = None
    authority: str | None = None
    notes: str | None = None
    is_derivative: bool = False


class LocalePack:
    """A loaded, validated pack rooted at ``root``."""

    def __init__(self, root: Path, manifest: PackManifest) -> None:
        self.root = root
        self.manifest = manifest

    # -- paths ---------------------------------------------------------------
    @property
    def official_dir(self) -> Path:
        return self.root / self.manifest.official_dir

    @property
    def i18n_dir(self) -> Path:
        return self.root / self.manifest.i18n_dir

    @property
    def sites_path(self) -> Path | None:
        if not self.manifest.sites_file:
            return None
        return self.root / self.manifest.sites_file

    # -- content -------------------------------------------------------------
    def official_files(self) -> list[OfficialFile]:
        """Every document the agent is allowed to read, with provenance attached.

        ``README.md`` in ``official/`` is provenance prose, not an official
        document, so it is deliberately excluded (PRD §10.1).
        """
        from cak_node.hashing import sha256_file  # local import: keeps hashing leaf-level

        files: list[OfficialFile] = []
        base = self.official_dir
        if not base.is_dir():
            return files
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.name == "README.md" or path.name.endswith(".meta.yaml"):
                continue
            if path.suffix.lower() not in INDEXABLE_SUFFIXES:
                continue
            rel = path.relative_to(self.root).as_posix()
            meta = _read_sidecar(path)
            files.append(
                OfficialFile(
                    file_id=rel,
                    path=path,
                    media_type=_media_type(path),
                    bytes=path.stat().st_size,
                    sha256=sha256_file(path),
                    title=meta.get("title") or _derive_title(path),
                    source_url=meta.get("source_url"),
                    retrieved_at=str(meta["retrieved_at"]) if meta.get("retrieved_at") else None,
                    authority=meta.get("authority") or self.manifest.authority.name,
                    notes=meta.get("notes"),
                    is_derivative=bool(meta.get("is_derivative", False)),
                )
            )
        return files

    def sites(self) -> dict[str, Any]:
        """The pack's GeoJSON FeatureCollection, or an empty one."""
        path = self.sites_path
        if path is None or not path.is_file():
            return {"type": "FeatureCollection", "features": []}
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("type") != "FeatureCollection":
            raise PackValidationError(f"{path} is not a GeoJSON FeatureCollection (RFC 7946)")
        return data

    def office_contact(self) -> dict[str, str | None]:
        """Contact block echoed on every answer, including 'I don't know'."""
        a = self.manifest.authority
        return {"name": a.name, "phone": a.phone, "address": a.address, "url": a.url}


def _media_type(path: Path) -> str:
    return {
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".html": "text/html",
        ".htm": "text/html",
        ".pdf": "application/pdf",
        ".yaml": "application/yaml",
        ".geojson": "application/geo+json",
    }.get(path.suffix.lower(), "application/octet-stream")


def _derive_title(path: Path) -> str:
    if path.suffix.lower() in {".md", ".txt"}:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("#"):
                    return line.lstrip("#").strip()
                if line.strip():
                    return line.strip()[:80]
        except OSError:
            pass
    return path.stem.replace("_", " ").replace("-", " ").title()


def _read_sidecar(path: Path) -> dict[str, Any]:
    sidecar = path.with_name(path.name + ".meta.yaml")
    if not sidecar.is_file():
        return {}
    loaded = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def load_manifest(pack_yaml: Path) -> PackManifest:
    """Parse and validate a ``pack.yaml``, raising :class:`PackValidationError`."""
    if not pack_yaml.is_file():
        raise PackValidationError(f"missing pack manifest: {pack_yaml}")
    try:
        raw = yaml.safe_load(pack_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PackValidationError(f"{pack_yaml} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise PackValidationError(f"{pack_yaml} must contain a YAML mapping")
    try:
        return PackManifest.model_validate(raw)
    except ValidationError as exc:
        raise PackValidationError(f"{pack_yaml} failed schema validation:\n{exc}") from exc


def load_pack(root: Path) -> LocalePack:
    """Load the pack at ``root``, validating both manifest and directory layout."""
    root = Path(root)
    if not root.is_dir():
        raise PackValidationError(f"pack directory does not exist: {root}")
    manifest = load_manifest(root / "pack.yaml")
    pack = LocalePack(root, manifest)
    if not pack.official_dir.is_dir():
        raise PackValidationError(f"official_dir {manifest.official_dir!r} not found under {root}")
    if manifest.sites_file and not pack.sites_path.is_file():  # type: ignore[union-attr]
        raise PackValidationError(f"sites_file {manifest.sites_file!r} not found under {root}")
    if not pack.i18n_dir.is_dir():
        raise PackValidationError(f"i18n_dir {manifest.i18n_dir!r} not found under {root}")
    return pack
