"""``node.toml`` — the steward's configuration (PRD §12.2).

Defaults are chosen so that an unconfigured node is the safe node: bound to
localhost, query logging off, extractive generator, no cloud anything.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("/etc/cak/node.toml")

PBKDF2_ITERATIONS = 240_000
_SCHEME = "pbkdf2_sha256"


class ConfigError(Exception):
    """Raised when node.toml is missing required values or contradicts itself."""


@dataclass
class NodeConfig:
    """Runtime configuration for one Civic Node."""

    locale_pack: Path
    # PRD §11.4: steward routes bind to localhost by default. A steward who
    # wants kiosk access from the LAN opts in explicitly *and* must set a
    # password first (enforced in __post_init__).
    bind: str = "127.0.0.1"
    port: int = 8080
    steward_password_hash: str | None = None
    generator: str = "extractive"
    model: str = "llama3.2:3b"
    ollama_host: str = "http://127.0.0.1:11434"
    retrieval_backend: str = "sqlite_fts"
    top_k: int = 6
    log_queries: bool = False
    db_path: Path = Path("/var/lib/cak/cak.db")
    changelog_path: Path = Path("/var/lib/cak/changelog.jsonl")
    changelog_key: Path = Path("/etc/cak/steward.ed25519")
    steward_inbox: Path = Path("/media/cak-usb")
    log_id: str = "caklog_local"
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.locale_pack = Path(self.locale_pack)
        self.db_path = Path(self.db_path)
        self.changelog_path = Path(self.changelog_path)
        self.changelog_key = Path(self.changelog_key)
        self.steward_inbox = Path(self.steward_inbox)
        if self.retrieval_backend != "sqlite_fts":
            raise ConfigError(
                f"retrieval_backend {self.retrieval_backend!r} is not available in v1; "
                "only 'sqlite_fts' is supported (PRD §12.1)"
            )
        if self.generator not in {"extractive", "ollama"}:
            raise ConfigError(f"generator must be 'extractive' or 'ollama', not {self.generator!r}")
        if not self.is_localhost_only and not self.steward_password_hash:
            raise ConfigError(
                f"bind = {self.bind!r} exposes this node beyond localhost, so "
                "steward_password_hash must be set (PRD §12.4: no open steward API)"
            )

    @property
    def is_localhost_only(self) -> bool:
        return self.bind in {"127.0.0.1", "::1", "localhost"}

    @classmethod
    def from_toml(cls, path: Path) -> NodeConfig:
        path = Path(path)
        if not path.is_file():
            raise ConfigError(f"config not found: {path}")
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
        return cls.from_mapping(raw, base_dir=path.parent)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any], base_dir: Path | None = None) -> NodeConfig:
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        if "locale_pack" not in raw:
            raise ConfigError("node.toml must set locale_pack")
        kwargs = {k: v for k, v in raw.items() if k in known}
        extra = {k: v for k, v in raw.items() if k not in known}
        config = cls(**kwargs, extra=extra)
        if base_dir is not None:
            config.resolve_relative_to(base_dir)
        return config

    def resolve_relative_to(self, base_dir: Path) -> None:
        """Make relative paths mean 'next to node.toml', which is what a steward expects."""
        base_dir = Path(base_dir)
        for name in ("locale_pack", "db_path", "changelog_path", "changelog_key", "steward_inbox"):
            value = Path(getattr(self, name))
            if not value.is_absolute():
                setattr(self, name, (base_dir / value).resolve())


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Hash a steward password as ``pbkdf2_sha256$iterations$salt$digest``.

    Stewards are not cloud accounts (PRD §6.2). This is a local secret, hashed
    so a stolen SD card does not hand over the PIN.
    """
    if not password:
        raise ValueError("steward password must not be empty")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        [
            _SCHEME,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, encoded: str | None) -> bool:
    """Constant-time password check. A node with no password set accepts nobody."""
    if not encoded or not password:
        return False
    try:
        scheme, iterations_text, salt_b64, digest_b64 = encoded.split("$")
        if scheme != _SCHEME:
            return False
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.b64decode(salt_b64),
            int(iterations_text),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


def new_steward_password(length: int = 12) -> str:
    """Suggest a password for a steward who does not want to invent one."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join(
        "".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(max(1, length // 4))
    )
