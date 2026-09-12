"""cak-sms: short-code parsing for feature phones. Apache-2.0.

Gateways (``twilio``, ``africas_talking``, ``local_modem``) are pluggable and
land in Phase 2 (PRD §18). The parser ships now because it is the part that
must be correct before any gateway touches it.
"""

from cak_sms.parser import (
    DEFAULT_CODES,
    MAX_SMS_CHARS,
    ParsedSms,
    SmsCommands,
    SmsParseError,
    is_gsm7,
)

__all__ = [
    "DEFAULT_CODES",
    "MAX_SMS_CHARS",
    "ParsedSms",
    "SmsCommands",
    "SmsParseError",
    "is_gsm7",
]
__version__ = "0.1.0"
