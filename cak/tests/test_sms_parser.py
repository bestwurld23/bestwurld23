"""PRD §17.6 — SMS parser. ``WAIT site03 25`` and everything around it."""

from __future__ import annotations

import pytest
import yaml

from cak_sms import MAX_SMS_CHARS, SmsCommands, SmsParseError, is_gsm7


@pytest.fixture
def commands() -> SmsCommands:
    return SmsCommands()


def test_the_canonical_example(commands: SmsCommands) -> None:
    parsed = commands.parse("WAIT site03 25")
    assert parsed.kind == "wait_time"
    assert parsed.site_id == "site03"
    assert parsed.payload == {"site_id": "site03", "line_minutes": 25, "open": True}


@pytest.mark.parametrize(
    "body", ["wait site03 25", "  WAIT   site03   25  ", "Wait Site03 25", "WAIT site03 25 extra"]
)
def test_wait_is_forgiving_about_shape(commands: SmsCommands, body: str) -> None:
    parsed = commands.parse(body)
    assert parsed.site_id == "site03"
    assert parsed.payload["line_minutes"] == 25


def test_closed_and_open(commands: SmsCommands) -> None:
    assert commands.parse("CLOSED site02").payload["reported_status"] == "closed"
    assert commands.parse("OPEN site02").payload["reported_status"] == "open"


def test_help(commands: SmsCommands) -> None:
    parsed = commands.parse("HELP")
    assert parsed.kind == "help"
    assert parsed.site_id is None
    assert len(parsed.reply) <= MAX_SMS_CHARS


@pytest.mark.parametrize(
    "body",
    ["WAIT", "WAIT site03", "WAIT site03 abc", "WAIT site03 -5", "BANANA site03", ""],
)
def test_bad_messages_raise_with_a_usable_reply(commands: SmsCommands, body: str) -> None:
    with pytest.raises(SmsParseError) as excinfo:
        commands.parse(body)
    assert excinfo.value.reply
    assert len(excinfo.value.reply) <= MAX_SMS_CHARS


def test_minutes_are_capped_at_the_form_limit(commands: SmsCommands) -> None:
    assert commands.parse("WAIT site03 480").payload["line_minutes"] == 480
    with pytest.raises(SmsParseError):
        commands.parse("WAIT site03 481")


def test_site_ids_are_validated(commands: SmsCommands) -> None:
    with pytest.raises(SmsParseError):
        commands.parse("WAIT ../../etc/passwd 25")
    with pytest.raises(SmsParseError):
        commands.parse("WAIT 'OR 1=1 25")


def test_replies_fit_one_message(commands: SmsCommands) -> None:
    for body in ["WAIT site03 25", "CLOSED site02", "OPEN site02", "HELP"]:
        reply = commands.parse(body).reply
        assert len(reply) <= MAX_SMS_CHARS
        assert is_gsm7(reply), reply


def test_replies_repeat_the_disclaimer(commands: SmsCommands) -> None:
    """Even 160 characters has room to say what this is not."""
    assert "Not an election office" in commands.parse("WAIT site03 25").reply
    assert "Not an election office" in commands.parse("HELP").reply


def test_payloads_never_carry_identity(commands: SmsCommands) -> None:
    """PRD §7.3: SMS payloads contain no names and no phone numbers."""
    forbidden = {"name", "phone", "phone_number", "sender", "msisdn", "from"}
    for body in ["WAIT site03 25", "CLOSED site02", "OPEN site01"]:
        assert not set(commands.parse(body).payload) & forbidden


def test_codes_come_from_the_pack(pack_dir) -> None:
    codes = yaml.safe_load((pack_dir / "sms" / "codes.yaml").read_text(encoding="utf-8"))
    commands = SmsCommands(codes=codes)
    assert commands.parse(codes["wait_code"] + " site01 10").kind == "wait_time"
    for example in codes["examples"]:
        assert commands.parse(example)


def test_a_locale_can_rename_every_code() -> None:
    """PRD §7.3: locale packs define the codes. Spanish-language example."""
    commands = SmsCommands(
        codes={
            "wait_code": "ESPERA",
            "closed_code": "CERRADO",
            "open_code": "ABIERTO",
            "help_code": "AYUDA",
        }
    )
    assert commands.parse("ESPERA site03 25").payload["line_minutes"] == 25
    assert commands.parse("CERRADO site03").payload["reported_status"] == "closed"
    with pytest.raises(SmsParseError):
        commands.parse("WAIT site03 25")


def test_ussd_style_wrapping_is_accepted(commands: SmsCommands) -> None:
    """Some aggregators deliver USSD input as ``*CODE#``."""
    assert commands.parse("*HELP#").kind == "help"


def test_queued_reports_reject_pii(service) -> None:
    """The queue is the last line: a gateway that leaks a name is refused."""
    from cak_node.storage import PrivacyViolation

    commands = SmsCommands()
    parsed = commands.parse("WAIT site03 25")
    assert service.store.enqueue_field_report("wait_time", "site03", parsed.payload, "sms") > 0

    with pytest.raises(PrivacyViolation):
        service.store.enqueue_field_report(
            "wait_time", "site03", {"site_id": "site03", "phone_number": "555-0100"}, "sms"
        )
    with pytest.raises(PrivacyViolation):
        service.store.enqueue_field_report(
            "turnaway", "site03", {"site_id": "site03", "notes": "My name is Jane Doe"}, "sms"
        )
