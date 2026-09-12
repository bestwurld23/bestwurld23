"""File hashing and media typing for log records.

Kept in the Apache-licensed changelog library so the CLI and the AGPL node app
agree on exactly what a file's identity is.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from cak_changelog.record import LoggedFile

CHUNK = 1024 * 1024

MEDIA_TYPES = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xml": "application/xml",
    ".zip": "application/zip",
}


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while block := fh.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def media_type(path: Path) -> str:
    return MEDIA_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


def logged_file(path: Path, rel_path: str, source: str | None = None) -> LoggedFile:
    """Build a :class:`LoggedFile` for ``path``, recorded under ``rel_path``."""
    path = Path(path)
    return LoggedFile(
        path=rel_path,
        sha256=hash_file(path),
        bytes=path.stat().st_size,
        media_type=media_type(path),
        source=source,
    )
