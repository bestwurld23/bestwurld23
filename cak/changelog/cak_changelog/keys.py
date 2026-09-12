"""Ed25519 key handling for the change log (PRD §11.1: Ed25519, PEM + .sig)."""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def generate_private_key(path: Path) -> Ed25519PrivateKey:
    """Create an unencrypted Ed25519 key at ``path`` with 0600 permissions.

    The key is the steward's, on the steward's device. No passphrase, because a
    node that cannot restart unattended after a power cut is a node that stops
    logging — and an unsigned gap is worse than a key on an encrypted disk.
    Pair this with LUKS (PRD §12.4).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    path.chmod(0o600)
    return key


def load_private_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError(f"{path} is not an Ed25519 private key")
    return key


def load_public_key_pem(pem: str | bytes) -> Ed25519PublicKey:
    data = pem.encode("utf-8") if isinstance(pem, str) else pem
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("not an Ed25519 public key")
    return key


def public_key_pem(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return public.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def sign(key: Ed25519PrivateKey, message: str) -> str:
    """Detached signature over ``message``, base64 encoded."""
    return base64.b64encode(key.sign(message.encode("utf-8"))).decode("ascii")


def verify(public: Ed25519PublicKey, message: str, signature_b64: str) -> bool:
    try:
        public.verify(base64.b64decode(signature_b64), message.encode("utf-8"))
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True
