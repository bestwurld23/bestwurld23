"""cak-changelog: an append-only, signed log of official *process* files.

Not a ledger of votes. See PRD §8.1 and §2.2 N5.
"""

from cak_changelog.files import hash_file, logged_file, media_type
from cak_changelog.log import (
    Changelog,
    ChangelogError,
    FileVerifyReport,
    VerifyReport,
    open_log,
)
from cak_changelog.record import (
    GENESIS_PREV_HASH,
    SCHEMA,
    ChangelogRecord,
    LoggedFile,
    canonical_json,
)

__all__ = [
    "Changelog",
    "ChangelogError",
    "ChangelogRecord",
    "FileVerifyReport",
    "GENESIS_PREV_HASH",
    "LoggedFile",
    "SCHEMA",
    "VerifyReport",
    "canonical_json",
    "hash_file",
    "logged_file",
    "media_type",
    "open_log",
]
__version__ = "0.1.0"
