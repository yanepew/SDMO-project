# Legacy security notes (known and accepted)

The device ↔ gateway link is deliberately **not** modernised:

* hard-coded shared key (`DEFAULT_LEGACY_SHARED_KEY`), same key on every device;
* XChaCha20 without authentication tag → ciphertext can be modified undetected;
* no device authentication, no replay protection, no post-quantum protection;
* the gateway trusts the `device_id` inside the decrypted payload.

Mitigations inside the modernised gateway (without touching the device): strict reading validation and
range checks. Everything beyond that requires changing the device and is out of scope.

Note: `gateway/legacy_decrypt.py` raises "nonce must be exactly 16 bytes" while checking for 24 bytes
(message typo only; behaviour is correct).
