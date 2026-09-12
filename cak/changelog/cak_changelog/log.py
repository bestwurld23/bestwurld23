"""The append-only change log: write, read, verify.

Normative source: PRD §8.3.

* First record is a genesis carrying the public key the chain is signed with.
* A file replaced without a log record is a *failed* steward action — so
  :meth:`Changelog.verify_files` reports on-disk hashes that the log does not
  know about, which is how tampering surfaces.
* Export is ``changelog.jsonl`` plus the public key in PEM.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from cak_changelog import keys
from cak_changelog.record import (
    GENESIS_PREV_HASH,
    Action,
    ChangelogRecord,
    LoggedFile,
    parse_record,
)

# Files in official/ that are not official documents and so are never logged.
IGNORED_FILENAMES: tuple[str, ...] = ("README.md",)
IGNORED_SUFFIXES: tuple[str, ...] = (".meta.yaml",)


class ChangelogError(Exception):
    """Raised when the log cannot be appended to or read."""


@dataclass
class VerifyReport:
    """Result of a full-chain verification."""

    ok: bool
    record_count: int = 0
    problems: list[str] = field(default_factory=list)
    signature_checked: bool = False

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class FileVerifyReport:
    """Result of comparing a directory on disk against the log."""

    ok: bool
    checked: int = 0
    mismatched: list[dict[str, Any]] = field(default_factory=list)
    unlogged: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Changelog:
    """A ``changelog.jsonl`` file plus the key material used to sign it."""

    def __init__(
        self,
        path: Path,
        private_key: Ed25519PrivateKey | None = None,
        public_key: Ed25519PublicKey | None = None,
    ) -> None:
        self.path = Path(path)
        self._private = private_key
        self._public = public_key

    # -- reading -------------------------------------------------------------
    def exists(self) -> bool:
        return self.path.is_file() and self.path.stat().st_size > 0

    def records(self) -> Iterator[ChangelogRecord]:
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield parse_record(line)
                except Exception as exc:  # noqa: BLE001 - surface the line number
                    raise ChangelogError(
                        f"{self.path}:{lineno} is not a valid record: {exc}"
                    ) from exc

    def all_records(self) -> list[ChangelogRecord]:
        return list(self.records())

    def head(self) -> ChangelogRecord | None:
        last = None
        for record in self.records():
            last = record
        return last

    @property
    def log_id(self) -> str | None:
        first = next(self.records(), None)
        return first.log_id if first else None

    def chain_public_key(self) -> Ed25519PublicKey | None:
        """The key from the genesis record, if the chain declares one."""
        if self._public is not None:
            return self._public
        first = next(self.records(), None)
        if first is None or not first.pack_public_key:
            return None
        return keys.load_public_key_pem(first.pack_public_key)

    # -- writing -------------------------------------------------------------
    def genesis(
        self,
        log_id: str,
        locale_id: str,
        public_key_pem: str,
        actor_role: str = "steward",
        note: str | None = None,
    ) -> ChangelogRecord:
        if self.exists():
            raise ChangelogError(f"{self.path} already has records; genesis would rewrite history")
        record = ChangelogRecord(
            log_id=log_id,
            seq=0,
            ts=utcnow(),
            locale_id=locale_id,
            actor_role=actor_role,
            action="genesis",
            files=[],
            note=note or "Genesis record. Process files only; never ballots.",
            pack_public_key=public_key_pem,
            prev_hash=GENESIS_PREV_HASH,
        )
        return self._finalize_and_write(record)

    def append(
        self,
        action: Action,
        files: list[LoggedFile] | None = None,
        actor_role: str = "steward",
        actor_id_hash: str | None = None,
        note: str | None = None,
        locale_id: str | None = None,
    ) -> ChangelogRecord:
        """Append one record, linked to the current head."""
        head = self.head()
        if head is None:
            raise ChangelogError(
                f"{self.path} has no genesis record; run 'cak-changelog init' first"
            )
        if head.record_hash is None:
            raise ChangelogError("head record has no record_hash; log is corrupt")
        record = ChangelogRecord(
            log_id=head.log_id,
            seq=head.seq + 1,
            ts=utcnow(),
            locale_id=locale_id or head.locale_id,
            actor_role=actor_role,
            actor_id_hash=actor_id_hash,
            action=action,
            files=files or [],
            note=note,
            prev_hash=head.record_hash,
        )
        return self._finalize_and_write(record)

    def _finalize_and_write(self, record: ChangelogRecord) -> ChangelogRecord:
        record.record_hash = record.compute_hash()
        if self._private is not None:
            record.sig = keys.sign(self._private, record.record_hash)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(record.to_json_line() + "\n")
        return record

    # -- verification --------------------------------------------------------
    def verify(self, public_key: Ed25519PublicKey | None = None) -> VerifyReport:
        """Check sequence, links, record hashes and signatures.

        Catches the two attacks that matter for a local log: editing a record
        (its ``record_hash`` no longer matches its body) and reordering or
        dropping records (``prev_hash`` no longer matches its predecessor).
        """
        problems: list[str] = []
        try:
            records = self.all_records()
        except ChangelogError as exc:
            return VerifyReport(ok=False, problems=[str(exc)])

        if not records:
            return VerifyReport(ok=False, problems=["log is empty: no genesis record"])

        pubkey = public_key or self.chain_public_key()
        signature_checked = pubkey is not None

        if records[0].action != "genesis":
            problems.append(f"seq {records[0].seq}: first record must be a genesis")
        if records[0].prev_hash != GENESIS_PREV_HASH:
            problems.append("genesis prev_hash must be the all-zero digest")
        if not records[0].pack_public_key:
            problems.append("genesis record does not carry a public key (PRD §8.3)")

        log_id = records[0].log_id
        previous: ChangelogRecord | None = None
        for record in records:
            where = f"seq {record.seq}"
            if record.log_id != log_id:
                problems.append(f"{where}: log_id {record.log_id!r} != {log_id!r}")
            expected_hash = record.compute_hash()
            if record.record_hash != expected_hash:
                problems.append(
                    f"{where}: record_hash mismatch (body was edited); "
                    f"stored {record.record_hash}, computed {expected_hash}"
                )
            if previous is None:
                if record.seq != 0:
                    problems.append(f"{where}: chain must start at seq 0")
            else:
                if record.seq != previous.seq + 1:
                    problems.append(f"{where}: out of order or gap after seq {previous.seq}")
                if record.prev_hash != previous.record_hash:
                    problems.append(
                        f"{where}: prev_hash does not match seq {previous.seq} "
                        "(records reordered, inserted or removed)"
                    )
            if pubkey is not None:
                if not record.sig:
                    problems.append(f"{where}: missing signature")
                elif not keys.verify(pubkey, record.record_hash or "", record.sig):
                    problems.append(f"{where}: signature does not verify")
            previous = record

        return VerifyReport(
            ok=not problems,
            record_count=len(records),
            problems=problems,
            signature_checked=signature_checked,
        )

    # -- queries -------------------------------------------------------------
    def find_by_sha256(self, sha256: str) -> list[ChangelogRecord]:
        """Every record that mentions a file with this hash (verifier page)."""
        needle = sha256.removeprefix("sha256:").lower()
        return [r for r in self.records() if any(f.sha256 == needle for f in r.files)]

    def latest_file_hashes(self) -> dict[str, str]:
        """Current expected hash per path, honouring ``remove_file`` records."""
        state: dict[str, str] = {}
        for record in self.records():
            for file in record.files:
                if record.action == "remove_file":
                    state.pop(file.path, None)
                else:
                    state[file.path] = file.sha256
        return state

    def verify_files(
        self,
        root: Path,
        subdir: str = "official",
        ignore_names: tuple[str, ...] = IGNORED_FILENAMES,
        ignore_suffixes: tuple[str, ...] = IGNORED_SUFFIXES,
    ) -> FileVerifyReport:
        """Compare files under ``root/subdir`` against the log's latest hashes.

        This is the check behind PRD §23: change ``hours.md`` on disk without
        going through the steward flow and the report comes back mismatched.

        ``README.md`` and ``*.meta.yaml`` are skipped because they are not
        official documents — the first is provenance prose and the second is a
        sidecar describing its neighbour (PRD §10.1, §10.4). Flagging them as
        "never logged" would train stewards to ignore the verifier, which is
        the one thing it cannot survive.
        """
        from cak_changelog.files import hash_file

        root = Path(root)
        expected = {
            path: digest
            for path, digest in self.latest_file_hashes().items()
            if path.startswith(f"{subdir}/")
        }
        base = root / subdir
        on_disk: dict[str, str] = {}
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                if not path.is_file() or path.name in ignore_names:
                    continue
                if any(path.name.endswith(suffix) for suffix in ignore_suffixes):
                    continue
                on_disk[path.relative_to(root).as_posix()] = hash_file(path)

        mismatched = [
            {"path": p, "expected_sha256": expected[p], "actual_sha256": on_disk[p]}
            for p in sorted(expected.keys() & on_disk.keys())
            if expected[p] != on_disk[p]
        ]
        missing = sorted(expected.keys() - on_disk.keys())
        unlogged = sorted(on_disk.keys() - expected.keys())
        return FileVerifyReport(
            ok=not mismatched and not missing and not unlogged,
            checked=len(on_disk),
            mismatched=mismatched,
            unlogged=unlogged,
            missing=missing,
        )

    # -- export --------------------------------------------------------------
    def export(self, out_dir: Path) -> list[Path]:
        """Write ``changelog.jsonl`` and ``changelog.pem`` for an auditor."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        written = [out_dir / "changelog.jsonl"]
        written[0].write_text(
            "".join(r.to_json_line() + "\n" for r in self.records()), encoding="utf-8"
        )
        pubkey = self.chain_public_key()
        if pubkey is not None:
            pem_path = out_dir / "changelog.pem"
            pem_path.write_text(keys.public_key_pem(pubkey), encoding="utf-8")
            written.append(pem_path)
        return written


def open_log(
    path: Path,
    private_key_path: Path | None = None,
    create_key: bool = False,
) -> Changelog:
    """Open a log, optionally attaching the steward's signing key."""
    private = None
    if private_key_path is not None:
        key_path = Path(private_key_path)
        if key_path.is_file():
            private = keys.load_private_key(key_path)
        elif create_key:
            private = keys.generate_private_key(key_path)
        else:
            raise ChangelogError(f"signing key not found: {key_path}")
    return Changelog(Path(path), private_key=private)
