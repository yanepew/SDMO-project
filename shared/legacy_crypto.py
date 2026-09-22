"""
Legacy cryptography helper.

SECURITY WARNING:
This module intentionally models an incomplete legacy encryption design.

It uses ChaCha20 for confidentiality but does not provide authentication,
integrity protection, device authentication, secure key exchange, replay
protection, or post-quantum resistance.

It is included only as an educational baseline for later modernization.
"""

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms


DEFAULT_LEGACY_SHARED_KEY = "legacy-demo-key-for-coursework-only"


def _derive_legacy_key(shared_secret: str) -> bytes:
    """
    Convert the human-readable legacy shared secret into a 32-byte ChaCha20 key.

    This is intentionally simplistic for the legacy simulation.
    A production design would use secure key management and a proper KDF.
    """
    return hashlib.sha256(shared_secret.encode("utf-8")).digest()


def encrypt_json(payload: dict[str, Any], shared_secret: str | None = None) -> dict[str, str]:
    """
    Encrypt a JSON-compatible dictionary using ChaCha20.

    Returns a transport-friendly dictionary containing Base64 values.

    The cryptography library's ChaCha20 implementation expects:
    - 32-byte key
    - 16-byte nonce

    SECURITY LIMITATION:
    ChaCha20 here is used without an authentication tag. An attacker may be
    able to modify ciphertext without reliable detection.
    """
    if shared_secret is None:
        shared_secret = os.getenv("LEGACY_SHARED_KEY", DEFAULT_LEGACY_SHARED_KEY)

    plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    key = _derive_legacy_key(shared_secret)
    nonce = os.urandom(16)

    cipher = Cipher(algorithms.ChaCha20(key, nonce), mode=None)
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(plaintext)

    return {
        "algorithm": "ChaCha20-legacy-no-authentication",
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_json(encrypted_payload: dict[str, str], shared_secret: str | None = None) -> dict[str, Any]:
    """
    Decrypt a payload produced by encrypt_json().

    Raises ValueError if required fields are missing or if decrypted data is not
    valid JSON.
    """
    if shared_secret is None:
        shared_secret = os.getenv("LEGACY_SHARED_KEY", DEFAULT_LEGACY_SHARED_KEY)

    try:
        nonce = base64.b64decode(encrypted_payload["nonce"])
        ciphertext = base64.b64decode(encrypted_payload["ciphertext"])
    except KeyError as error:
        raise ValueError(f"Missing encrypted payload field: {error}") from error
    except Exception as error:
        raise ValueError("Encrypted payload contains invalid Base64 data.") from error

    if len(nonce) != 16:
        raise ValueError("Legacy ChaCha20 nonce must be exactly 16 bytes.")

    key = _derive_legacy_key(shared_secret)

    cipher = Cipher(algorithms.ChaCha20(key, nonce), mode=None)
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext)

    try:
        return json.loads(plaintext.decode("utf-8"))
    except Exception as error:
        raise ValueError(
            "Unable to decrypt valid JSON. The message may be corrupted, "
            "modified, or encrypted with a different key."
        ) from error
