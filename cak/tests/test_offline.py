"""PRD §17.4 — every Must feature works with the network disabled.

Rather than trusting that nothing calls out, this test breaks the socket layer
for the duration: any attempt to open a network connection raises. A node in a
chapter house with no backhaul behaves exactly like this, and so should CI.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from cak_node.printing import PaperPack
from cak_node.service import NodeService


class NetworkDisabled(OSError):
    """Raised in place of any outbound connection attempt."""


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every outbound socket operation fail."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise NetworkDisabled("network is disabled for this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def test_the_guard_itself_works(no_network: None) -> None:
    with pytest.raises(NetworkDisabled):
        socket.create_connection(("example.invalid", 80))


def test_agent_answers_offline(service: NodeService, no_network: None) -> None:
    response = service.answer("When is early voting?")
    assert response.status == "ok"
    assert response.citations
    assert "8am to 6pm" in " ".join(c.excerpt for c in response.citations)


def test_refusals_work_offline(service: NodeService, no_network: None) -> None:
    response = service.answer("Am I eligible if I have a felony?")
    assert response.status == "i_dont_know"
    assert response.office.phone == "555-0100"


def test_health_works_offline(service: NodeService, no_network: None) -> None:
    health = service.health()
    assert health.status == "ok"
    assert health.offline is True
    assert health.official_file_count == 3
    assert health.indexed_chunk_count > 0
    assert health.changelog_ok is True


def test_changelog_verifies_offline(service: NodeService, no_network: None) -> None:
    assert service.changelog.verify().ok
    assert service.verify_files().ok


def test_steward_load_works_offline(service: NodeService, tmp_path: Path, no_network: None) -> None:
    usb = tmp_path / "usb-offline"
    usb.mkdir()
    (usb / "hours.md").write_text(
        "# Early voting hours\n\nEarly voting runs on weekdays from 7am to 7pm.\n",
        encoding="utf-8",
    )
    result = service.load_folder(usb, source_note="USB stick, offline")
    assert result.accepted == ["hours.md"]
    assert result.changelog_seq is not None
    assert service.verify_files().ok


def test_printing_works_offline(service: NodeService, no_network: None) -> None:
    """The paper path must not depend on a web font or a CDN."""
    html = PaperPack(service.pack, service.catalogue).howto_html()
    assert "Springfield Civic Board" in html
    assert "555-0100" in html
    assert "http://" not in html.replace("http://www.w3.org", "")
    assert "https://" not in html.replace("https://example.invalid", "")


def test_kiosk_page_works_offline(client, no_network: None) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "not an official election office" in page.text.lower()
    # No external assets: everything a browser needs is in the page.
    assert "cdn" not in page.text.lower()
    assert "<script" not in page.text.lower()


def test_query_api_works_offline(client, no_network: None) -> None:
    reply = client.post("/agent/query", json={"text": "Where do I vote?"})
    assert reply.status_code == 200
    payload = reply.json()
    assert payload["status"] == "ok"
    assert payload["citations"][0]["file_id"] == "official/sites.md"


def test_seven_days_disconnected_changes_nothing(
    service: NodeService, no_network: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PRD §3 P2: no licence check, no token refresh, no expiry after a week.

    Nothing in the node consults the clock to decide whether it may answer, so
    the test asserts the property directly: the same question a week later gets
    the same answer.
    """
    import datetime as real_datetime

    before = service.answer("When is early voting?")

    later = real_datetime.datetime.now(real_datetime.UTC) + real_datetime.timedelta(days=7)

    class FrozenDateTime(real_datetime.datetime):
        @classmethod
        def now(cls, tz: object = None) -> real_datetime.datetime:  # type: ignore[override]
            return later

    monkeypatch.setattr(real_datetime, "datetime", FrozenDateTime)
    after = service.answer("When is early voting?")

    assert after.status == before.status == "ok"
    assert [c.file_id for c in after.citations] == [c.file_id for c in before.citations]
    assert after.answer_markdown == before.answer_markdown
