"""PRD §17.3 — hash-log immutability.

The two failures that matter: editing a record, and reordering records. Both
must be detectable by an auditor holding nothing but the file and the public
key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cak_changelog import Changelog, ChangelogError, hash_file, keys, logged_file
from cak_changelog.record import GENESIS_PREV_HASH, canonical_json, parse_record


@pytest.fixture
def signed_log(tmp_path: Path, pack_dir: Path) -> Changelog:
    key_path = tmp_path / "steward.ed25519"
    private = keys.generate_private_key(key_path)
    log = Changelog(tmp_path / "changelog.jsonl", private_key=private)
    log.genesis(
        log_id="caklog_test",
        locale_id="us-xx-springfield",
        public_key_pem=keys.public_key_pem(private),
    )
    files = [
        logged_file(pack_dir / "official" / name, f"official/{name}", source="fixture")
        for name in ("hours.md", "sites.md", "contacts.md")
    ]
    log.append(action="pack_install", files=files, note="first boot")
    return log


def test_fresh_log_verifies(signed_log: Changelog) -> None:
    report = signed_log.verify()
    assert report.ok, report.problems
    assert report.record_count == 2
    assert report.signature_checked


def test_genesis_carries_the_public_key(signed_log: Changelog) -> None:
    genesis = signed_log.all_records()[0]
    assert genesis.action == "genesis"
    assert genesis.seq == 0
    assert genesis.prev_hash == GENESIS_PREV_HASH
    assert genesis.pack_public_key
    assert signed_log.chain_public_key() is not None


def test_appending_links_to_the_head(signed_log: Changelog, pack_dir: Path) -> None:
    head = signed_log.head()
    assert head is not None
    record = signed_log.append(
        action="replace_file",
        files=[logged_file(pack_dir / "official" / "hours.md", "official/hours.md")],
    )
    assert record.seq == head.seq + 1
    assert record.prev_hash == head.record_hash
    assert signed_log.verify().ok


def test_editing_a_record_body_breaks_its_hash(signed_log: Changelog) -> None:
    lines = signed_log.path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["files"][0]["sha256"] = "0" * 64
    lines[1] = canonical_json(record).decode("utf-8")
    signed_log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = signed_log.verify()
    assert not report.ok
    assert any("record_hash mismatch" in problem for problem in report.problems)


def test_reordering_records_breaks_the_chain(signed_log: Changelog, pack_dir: Path) -> None:
    signed_log.append(
        action="replace_file",
        files=[logged_file(pack_dir / "official" / "sites.md", "official/sites.md")],
    )
    lines = signed_log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    lines[1], lines[2] = lines[2], lines[1]
    signed_log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = signed_log.verify()
    assert not report.ok
    assert any("out of order" in p or "prev_hash" in p for p in report.problems)


def test_dropping_a_record_breaks_the_chain(signed_log: Changelog, pack_dir: Path) -> None:
    signed_log.append(action="note", files=[], note="second")
    lines = signed_log.path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    signed_log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = signed_log.verify()
    assert not report.ok


def test_a_forged_record_fails_signature_check(signed_log: Changelog) -> None:
    """Recomputing the hash is not enough: the signature is over a key you lack."""
    lines = signed_log.path.read_text(encoding="utf-8").splitlines()
    record = parse_record(lines[1])
    record.note = "forged"
    record.record_hash = record.compute_hash()  # hash now matches the edited body
    lines[1] = record.to_json_line()
    signed_log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = signed_log.verify()
    assert not report.ok
    assert any("signature does not verify" in p for p in report.problems)


def test_tampered_file_on_disk_is_detected(signed_log: Changelog, pack_dir: Path) -> None:
    """PRD §23: edit hours.md outside the steward flow, verifier reports mismatch."""
    assert signed_log.verify_files(pack_dir).ok

    hours = pack_dir / "official" / "hours.md"
    hours.write_text("# Early voting hours\n\nPolls open at 3am.\n", encoding="utf-8")

    report = signed_log.verify_files(pack_dir)
    assert not report.ok
    assert len(report.mismatched) == 1
    assert report.mismatched[0]["path"] == "official/hours.md"
    assert report.mismatched[0]["actual_sha256"] == hash_file(hours)
    assert report.mismatched[0]["expected_sha256"] != report.mismatched[0]["actual_sha256"]


def test_unlogged_file_on_disk_is_reported(signed_log: Changelog, pack_dir: Path) -> None:
    (pack_dir / "official" / "smuggled.md").write_text("# Fake\n\nVote here.\n", encoding="utf-8")
    report = signed_log.verify_files(pack_dir)
    assert not report.ok
    assert "official/smuggled.md" in report.unlogged


def test_deleted_file_is_reported(signed_log: Changelog, pack_dir: Path) -> None:
    (pack_dir / "official" / "sites.md").unlink()
    report = signed_log.verify_files(pack_dir)
    assert not report.ok
    assert "official/sites.md" in report.missing


def test_find_by_hash(signed_log: Changelog, pack_dir: Path) -> None:
    digest = hash_file(pack_dir / "official" / "hours.md")
    assert signed_log.find_by_sha256(digest)
    assert signed_log.find_by_sha256("sha256:" + digest)
    assert not signed_log.find_by_sha256("0" * 64)


def test_second_genesis_is_refused(signed_log: Changelog) -> None:
    with pytest.raises(ChangelogError):
        signed_log.genesis("caklog_test", "us-xx-springfield", "not-a-key")


def test_canonical_json_is_stable_regardless_of_key_order() -> None:
    a = canonical_json({"b": 1, "a": {"d": 2, "c": 3}})
    b = canonical_json({"a": {"c": 3, "d": 2}, "b": 1})
    assert a == b


def test_export_writes_jsonl_and_pem(signed_log: Changelog, tmp_path: Path) -> None:
    written = signed_log.export(tmp_path / "audit")
    names = {p.name for p in written}
    assert names == {"changelog.jsonl", "changelog.pem"}
    assert "BEGIN PUBLIC KEY" in (tmp_path / "audit" / "changelog.pem").read_text()
    reopened = Changelog(tmp_path / "audit" / "changelog.jsonl")
    assert reopened.verify().ok


def test_empty_log_does_not_verify(tmp_path: Path) -> None:
    report = Changelog(tmp_path / "nothing.jsonl").verify()
    assert not report.ok
