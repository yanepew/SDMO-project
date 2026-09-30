"""
Legacy cryptography helper.

SECURITY WARNING:
This module intentionally models an incomplete legacy encryption design.

It uses XChaCha20 for confidentiality but does not provide authentication,
integrity protection, device authentication, secure key exchange, replay
protection, or post-quantum resistance.

It is included only as an educational baseline for later modernization.
"""

import base64
import hashlib
import json
import os

import device.legacy_xchacha20
from device.legacy_memory_controller import MemoryController

DEFAULT_LEGACY_SHARED_KEY = "legacy-demo-key-for-coursework-only"

# payload dictionary should be in memory, outputs to ciphered_json
def encrypt_json(mem: MemoryController) -> None:
    """
    Encrypt a JSON-compatible dictionary using XChaCha20.

    Returns a transport-friendly dictionary containing Base64 values.

    The cryptography library's XChaCha20 implementation expects:
    - 32-byte key
    - 24-byte nonce

    SECURITY LIMITATION:
    XChaCha20 here is used without an authentication tag. An attacker may be
    able to modify ciphertext without reliable detection.
    """
    with mem.auto_alloc_empty_vars("shared_secret", "key", "nonce", "message", "ciphertext"):
        mem["shared_secret"] = os.getenv("LEGACY_SHARED_KEY", DEFAULT_LEGACY_SHARED_KEY)
        mem["message"] = json.dumps(mem["payload"], separators=(",", ":"), sort_keys=True).encode("utf-8")
        mem["key"] = hashlib.sha256(mem["shared_secret"].encode("utf-8")).digest()
        mem["nonce"] = os.urandom(24)
        device.legacy_xchacha20.xchacha20_xor(mem)
        mem["ciphered_json"] = {
            "algorithm": "XChaCha20-legacy-no-authentication",
            "nonce": base64.b64encode(mem["nonce"]).decode("ascii"),
            "ciphertext": base64.b64encode(mem["ciphertext"]).decode("ascii")
        }
