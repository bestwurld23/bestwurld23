"""SHA-256 helpers. One implementation so the node, the CLI and the tests agree."""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while block := fh.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()
