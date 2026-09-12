"""Steward writes: getting official files onto the node from a USB stick.

Normative source: PRD §12.3 (USB pack → verify → replace → reindex → append to
changelog) and §8.3 ("file replace without a new log record is a failed steward
action"). Target: under 15 minutes end to end, by a person who is not an
engineer (G2).

The invariant this module exists to hold: no file lands in ``official/``
without a signed log record naming its hash. Copy and log succeed together or
the load is reported as failed.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cak_changelog import Changelog, hash_file, logged_file
from cak_changelog.record import LoggedFile
from cak_node.models import OfficialDirVerification, StewardLoadResult
from cak_node.pack import LocalePack

# What may live in official/. Everything here is text the agent can cite or a
# document a resident can be handed.
ALLOWED_SUFFIXES: frozenset[str] = frozenset(
    {".md", ".txt", ".csv", ".pdf", ".html", ".htm", ".yaml", ".yml", ".geojson", ".png", ".svg"}
)

# PRD §11.2 forbids spreadsheets of voter rolls on the Pi, and nothing
# executable belongs in a document directory.
REJECTED_SUFFIXES: dict[str, str] = {
    ".xlsx": "spreadsheets are not allowed in official/ (PRD §11.2: no voter rolls in Excel)",
    ".xls": "spreadsheets are not allowed in official/ (PRD §11.2: no voter rolls in Excel)",
    ".exe": "executables are not official documents",
    ".sh": "executables are not official documents",
    ".py": "executables are not official documents",
    ".db": "databases are not official documents",
    ".sqlite": "databases are not official documents",
}

MAX_FILE_BYTES = 256 * 1024 * 1024


@dataclass
class StewardContext:
    """What a steward write needs: the pack, the log, and somewhere to audit."""

    pack: LocalePack
    changelog: Changelog
    actor_role: str = "steward"
    actor_id_hash: str | None = None


def classify(path: Path) -> str | None:
    """Return a rejection reason for ``path``, or ``None`` if it may be loaded."""
    suffix = path.suffix.lower()
    if suffix in REJECTED_SUFFIXES:
        return REJECTED_SUFFIXES[suffix]
    if suffix not in ALLOWED_SUFFIXES:
        return f"unsupported file type {suffix or '(none)'}"
    if path.stat().st_size > MAX_FILE_BYTES:
        return f"file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"
    return None


def load_from_folder(
    source_dir: Path,
    context: StewardContext,
    source_note: str | None = None,
    dry_run: bool = False,
) -> StewardLoadResult:
    """Copy every allowed file from ``source_dir`` into the pack's ``official/``.

    Files whose contents already match are reported as ``unchanged`` and are
    neither copied nor logged, so plugging the same stick in twice does not
    inflate the chain.
    """
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise FileNotFoundError(f"steward source folder not found: {source_dir}")

    official = context.pack.official_dir
    official.mkdir(parents=True, exist_ok=True)

    accepted: list[str] = []
    rejected: list[str] = []
    unchanged: list[str] = []
    pending: list[tuple[Path, Path]] = []
    had_existing = False

    for src in sorted(source_dir.rglob("*")):
        if not src.is_file():
            continue
        relative = src.relative_to(source_dir)
        if ".." in relative.parts or relative.is_absolute():
            rejected.append(f"{relative}: path escapes the source folder")
            continue
        # Provenance sidecars travel with their document rather than being
        # loaded as documents themselves.
        if src.name.endswith(".meta.yaml"):
            pending.append((src, official / relative))
            continue
        reason = classify(src)
        if reason:
            rejected.append(f"{relative}: {reason}")
            continue
        destination = official / relative
        if destination.is_file():
            had_existing = True
            if hash_file(destination) == hash_file(src):
                unchanged.append(relative.as_posix())
                continue
        pending.append((src, destination))
        accepted.append(relative.as_posix())

    if dry_run or not accepted:
        return StewardLoadResult(
            accepted=accepted, rejected=rejected, unchanged=unchanged, changelog_seq=None
        )

    logged: list[LoggedFile] = []
    for src, destination in pending:
        _atomic_copy(src, destination)
        if destination.name.endswith(".meta.yaml"):
            continue
        rel_in_pack = destination.relative_to(context.pack.root).as_posix()
        logged.append(logged_file(destination, rel_in_pack, source=source_note))

    record = context.changelog.append(
        action="replace_file" if had_existing else "add_file",
        files=logged,
        actor_role=context.actor_role,
        actor_id_hash=context.actor_id_hash,
        note=source_note,
        locale_id=context.pack.manifest.locale_id,
    )

    return StewardLoadResult(
        accepted=accepted,
        rejected=rejected,
        unchanged=unchanged,
        changelog_seq=record.seq,
    )


def save_uploaded_file(
    filename: str,
    data: bytes,
    context: StewardContext,
    source_note: str | None = None,
) -> StewardLoadResult:
    """Authenticated local upload of a single file (PRD §6.2 steward mode)."""
    safe_name = Path(filename).name
    if not safe_name or safe_name.startswith("."):
        return StewardLoadResult(rejected=[f"{filename}: unusable filename"])
    with tempfile.TemporaryDirectory(prefix="cak-upload-") as tmp:
        staged = Path(tmp) / safe_name
        staged.write_bytes(data)
        return load_from_folder(Path(tmp), context, source_note=source_note)


def verify_official_dir(pack: LocalePack, changelog: Changelog) -> OfficialDirVerification:
    """Compare ``official/`` on disk against the change log.

    This is the acceptance test in PRD §23: edit ``hours.md`` behind the
    steward's back and the node says so.
    """
    subdir = pack.manifest.official_dir.strip("/")
    report = changelog.verify_files(pack.root, subdir=subdir)
    return OfficialDirVerification(
        ok=report.ok,
        checked=report.checked,
        mismatched=report.mismatched,
        unlogged=report.unlogged,
        missing=report.missing,
    )


def _atomic_copy(src: Path, destination: Path) -> None:
    """Copy via a temp file in the destination directory, then rename.

    A power cut mid-update is normal in the terrains this ships to. A partially
    written polling-place list is worse than an old one.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(destination.parent), prefix=".cak-tmp-")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        shutil.copyfile(src, tmp_path)
        with tmp_path.open("rb") as fh:
            os.fsync(fh.fileno())
        tmp_path.replace(destination)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
