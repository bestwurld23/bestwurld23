"""Steward flow: USB load, changelog linkage, reindex, tamper detection.

This is the PRD §23 acceptance sequence, run end to end:
replace ``hours.md`` through the steward flow, watch the changelog seq
increment and the answer change; then edit the file behind the node's back and
watch the verifier catch it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cak_node.service import NodeService


@pytest.fixture
def usb(tmp_path: Path) -> Path:
    stick = tmp_path / "usb"
    stick.mkdir(exist_ok=True)
    return stick


def test_replacing_hours_changes_the_answer_and_the_log(service: NodeService, usb: Path) -> None:
    before = service.answer("When is early voting?")
    assert "8am to 6pm" in " ".join(c.excerpt for c in before.citations)
    seq_before = service.changelog.head().seq

    (usb / "hours.md").write_text(
        "# Early voting hours\n\nEarly voting runs on weekdays from 7am to 9pm.\n",
        encoding="utf-8",
    )
    result = service.load_folder(usb, source_note="Springfield Civic Board download")

    assert result.accepted == ["hours.md"]
    assert result.rejected == []
    assert service.changelog.head().seq == seq_before + 1

    after = service.answer("When is early voting?")
    assert after.status == "ok"
    excerpts = " ".join(c.excerpt for c in after.citations)
    assert "7am to 9pm" in excerpts
    assert "8am to 6pm" not in excerpts


def test_load_records_the_new_hash_in_the_changelog(service: NodeService, usb: Path) -> None:
    from cak_changelog import hash_file

    (usb / "hours.md").write_text(
        "# Early voting hours\n\nWeekdays 7am to 9pm.\n", encoding="utf-8"
    )
    service.load_folder(usb, source_note="USB")

    on_disk = hash_file(service.pack.official_dir / "hours.md")
    assert service.changelog.find_by_sha256(on_disk)
    assert service.verify_files().ok


def test_loading_the_same_stick_twice_adds_no_record(service: NodeService, usb: Path) -> None:
    (usb / "hours.md").write_text(
        "# Early voting hours\n\nWeekdays 7am to 9pm.\n", encoding="utf-8"
    )
    service.load_folder(usb)
    seq = service.changelog.head().seq

    second = service.load_folder(usb)
    assert second.unchanged == ["hours.md"]
    assert second.accepted == []
    assert service.changelog.head().seq == seq


def test_dry_run_changes_nothing(service: NodeService, usb: Path) -> None:
    seq = service.changelog.head().seq
    original = (service.pack.official_dir / "hours.md").read_text(encoding="utf-8")
    (usb / "hours.md").write_text("# Hours\n\nDifferent.\n", encoding="utf-8")

    result = service.load_folder(usb, dry_run=True)
    assert result.accepted == ["hours.md"]
    assert service.changelog.head().seq == seq
    assert (service.pack.official_dir / "hours.md").read_text(encoding="utf-8") == original


def test_new_file_is_added_and_becomes_answerable(service: NodeService, usb: Path) -> None:
    (usb / "registration.md").write_text(
        "# How to register\n\nRegistration forms are available at the Board office.\n"
        "Bring the completed form to 10 Civic Plaza.\n",
        encoding="utf-8",
    )
    result = service.load_folder(usb, source_note="Board download")
    assert result.accepted == ["registration.md"]

    answer = service.answer("How do I register?")
    assert answer.status == "ok"
    assert any(c.file_id == "official/registration.md" for c in answer.citations)


@pytest.mark.parametrize(
    "filename,content",
    [
        ("voters.xlsx", b"PK\x03\x04fake"),
        ("payload.exe", b"MZ"),
        ("script.sh", b"#!/bin/sh\n"),
        ("rolls.db", b"SQLite format 3\x00"),
    ],
)
def test_forbidden_file_types_are_rejected(
    service: NodeService, usb: Path, filename: str, content: bytes
) -> None:
    """PRD §11.2: no voter rolls in Excel, nothing executable in official/."""
    (usb / filename).write_bytes(content)
    result = service.load_folder(usb)
    assert result.accepted == []
    assert len(result.rejected) == 1
    assert filename in result.rejected[0]
    assert not (service.pack.official_dir / filename).exists()


def test_rejected_file_does_not_block_a_good_one(service: NodeService, usb: Path) -> None:
    (usb / "voters.xlsx").write_bytes(b"PK\x03\x04")
    (usb / "hours.md").write_text(
        "# Early voting hours\n\nWeekdays 7am to 9pm.\n", encoding="utf-8"
    )
    result = service.load_folder(usb)
    assert result.accepted == ["hours.md"]
    assert any("voters.xlsx" in r for r in result.rejected)


def test_tampering_on_disk_is_detected(service: NodeService) -> None:
    """PRD §23: edit hours.md without the steward flow; the verifier says so."""
    assert service.verify_files().ok

    (service.pack.official_dir / "hours.md").write_text(
        "# Early voting hours\n\nPolls open at 3am.\n", encoding="utf-8"
    )

    report = service.verify_files()
    assert not report.ok
    assert [m["path"] for m in report.mismatched] == ["official/hours.md"]


def test_tampering_is_visible_through_the_api(client, service: NodeService) -> None:
    (service.pack.official_dir / "hours.md").write_text("# Hours\n\n3am.\n", encoding="utf-8")
    reply = client.get("/changelog/verify-files")
    assert reply.status_code == 200
    body = reply.json()
    assert body["ok"] is False
    assert body["mismatched"][0]["path"] == "official/hours.md"


def test_steward_write_is_audited(service: NodeService, usb: Path) -> None:
    (usb / "hours.md").write_text(
        "# Early voting hours\n\nWeekdays 7am to 9pm.\n", encoding="utf-8"
    )
    service.load_folder(usb, source_note="USB stick")
    trail = service.store.audit_trail()
    assert trail[0]["action"] == "load_folder"
    assert trail[0]["changelog_seq"] == service.changelog.head().seq


def test_audit_trail_holds_no_question_text(service: NodeService, usb: Path) -> None:
    service.answer("My name is Jane Doe, where do I vote?")
    (usb / "hours.md").write_text(
        "# Early voting hours\n\nWeekdays 7am to 9pm.\n", encoding="utf-8"
    )
    service.load_folder(usb)
    blob = repr(service.store.audit_trail())
    assert "Jane" not in blob


def test_missing_source_folder_is_an_error(service: NodeService, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        service.load_folder(tmp_path / "no-such-stick")


def test_first_boot_logs_the_shipped_pack(service: NodeService) -> None:
    records = service.changelog.all_records()
    assert records[0].action == "genesis"
    assert records[1].action == "pack_install"
    assert {f.path for f in records[1].files} == {
        "official/hours.md",
        "official/sites.md",
        "official/contacts.md",
    }
    assert service.changelog.verify().ok
