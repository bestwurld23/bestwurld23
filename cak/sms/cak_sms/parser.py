"""SMS short-code parser for feature phones (PRD §7.3).

A feature phone and a sheet of paper have to be enough to use CAK (PRD §14), so
this path is not an afterthought: it is the lowest rung that still works.

Two rules shape the design:

* Payloads carry no names and no phone numbers. The sender's number is the
  gateway's business, never CAK's — it is not returned by the parser and never
  reaches the field-report queue (PRD §7.3, §13).
* Replies stay under 160 GSM-7 characters so they arrive as one message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_SMS_CHARS = 160
MAX_LINE_MINUTES = 480  # PRD §7.2: line_minutes is 0-480

_SITE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_DIGITS_RE = re.compile(r"^\d{1,4}$")

DEFAULT_CODES: dict[str, str] = {
    "wait_code": "WAIT",
    "closed_code": "CLOSED",
    "open_code": "OPEN",
    "help_code": "HELP",
}


class SmsParseError(ValueError):
    """The message could not be understood. ``reply`` is what to text back."""

    def __init__(self, message: str, reply: str) -> None:
        super().__init__(message)
        self.reply = reply


@dataclass(frozen=True)
class ParsedSms:
    """A recognized command, ready for the store-and-forward queue."""

    kind: str
    site_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    reply: str = ""


class SmsCommands:
    """Parser bound to one pack's ``sms/codes.yaml``."""

    def __init__(self, codes: dict[str, str] | None = None, help_text: str | None = None) -> None:
        merged = {**DEFAULT_CODES, **(codes or {})}
        self.wait = merged["wait_code"].upper()
        self.closed = merged["closed_code"].upper()
        self.open = merged["open_code"].upper()
        self.help = merged["help_code"].upper()
        self.help_text = help_text or self.default_help()

    def default_help(self) -> str:
        """Help reply, kept inside one SMS."""
        text = (
            f"{self.wait} <site> <minutes> = report wait. "
            f"{self.closed} <site> = report closed. "
            f"{self.open} <site> = report open. "
            "Not an election office."
        )
        return text[:MAX_SMS_CHARS]

    def parse(self, body: str) -> ParsedSms:
        """Parse one inbound message body.

        Raises :class:`SmsParseError` with a ready-to-send reply when the
        message is not a recognized command.
        """
        tokens = (body or "").strip().split()
        if not tokens:
            raise SmsParseError("empty message", self.help_text)

        command = tokens[0].upper().lstrip("#*").rstrip("#")
        args = tokens[1:]

        if command == self.help:
            return ParsedSms(kind="help", reply=self.help_text)

        if command == self.wait:
            if len(args) < 2:
                raise SmsParseError(
                    "WAIT needs a site and minutes",
                    f"Send: {self.wait} <site> <minutes>. Example: {self.wait} site03 25",
                )
            site_id = self._site(args[0])
            minutes = self._minutes(args[1])
            return ParsedSms(
                kind="wait_time",
                site_id=site_id,
                payload={"site_id": site_id, "line_minutes": minutes, "open": True},
                reply=self._ack(f"Wait {minutes} min logged for {site_id}."),
            )

        if command in {self.closed, self.open}:
            if not args:
                raise SmsParseError(
                    f"{command} needs a site",
                    f"Send: {command} <site>. Example: {command} site03",
                )
            site_id = self._site(args[0])
            is_open = command == self.open
            return ParsedSms(
                kind="closure",
                site_id=site_id,
                payload={
                    "site_id": site_id,
                    "reported_status": "open" if is_open else "closed",
                },
                reply=self._ack(f"Reported {site_id} as {'open' if is_open else 'closed'}."),
            )

        raise SmsParseError(f"unknown command {command!r}", self.help_text)

    # -- validation ----------------------------------------------------------
    @staticmethod
    def _site(raw: str) -> str:
        site = raw.strip().lower()
        if not _SITE_ID_RE.match(site):
            raise SmsParseError(
                f"bad site id {raw!r}",
                "Site code must be letters and numbers, e.g. site03.",
            )
        return site

    @staticmethod
    def _minutes(raw: str) -> int:
        if not _DIGITS_RE.match(raw.strip()):
            raise SmsParseError(f"bad minutes {raw!r}", "Minutes must be a whole number, e.g. 25.")
        minutes = int(raw)
        if minutes > MAX_LINE_MINUTES:
            raise SmsParseError(
                f"minutes {minutes} above {MAX_LINE_MINUTES}",
                f"Minutes must be {MAX_LINE_MINUTES} or less.",
            )
        return minutes

    @staticmethod
    def _ack(text: str) -> str:
        suffix = " Thanks. Not an election office."
        return (text + suffix)[:MAX_SMS_CHARS]


def is_gsm7(text: str) -> bool:
    """True when ``text`` fits the GSM-7 alphabet, so it costs one segment."""
    gsm7 = (
        "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
        "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
    )
    extended = "^{}\\[~]|€"
    return all(ch in gsm7 or ch in extended for ch in text)
