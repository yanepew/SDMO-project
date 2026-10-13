"""
ML-KEM secured channel between the edge gateway and the cloud service.

This replaces the former HTTPS-with-self-signed-certificate link.

Design (KEMTLS-style, mutually authenticated by static ML-KEM keys)
-------------------------------------------------------------------
Both sides hold a long-term ML-KEM-768 key pair. Each side is provisioned with
the other side's *public* (encapsulation) key out of band.

  Gateway                                        Cloud
  -------                                        -----
  (K1, ct1) = Encaps(cloud_ek)
              -- gateway_id, ct1 ------------->  K1 = Decaps(cloud_dk, ct1)
                                                 (K2, ct2) = Encaps(gateway_ek)
              <------------ session_id, ct2 ---
  K2 = Decaps(gateway_dk, ct2)
  keys = HKDF(K1 || K2, salt = transcript hash)  keys = HKDF(K1 || K2, ...)

* Only the real cloud can recover K1  -> the cloud is authenticated.
* Only the real gateway can recover K2 -> the gateway is authenticated.
* Application data is protected with AES-256-GCM using one key per direction,
  a strictly increasing sequence number as nonce, and an AAD that binds the
  session id, the sequence number and the message type.

Security notes
--------------
* ML-KEM only provides key establishment. Authentication here comes from the
  static keys being pinned, not from certificates.
* The backend is the pure-Python `kyber-py` package. It follows FIPS 203 but is
  NOT constant-time. All KEM calls are isolated in the three `kem_*` functions
  below so that a native backend (e.g. liboqs) can replace it in one place.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from kyber_py.ml_kem import ML_KEM_768

ALGORITHM = "ML-KEM-768"
EK_LEN = 1184
DK_LEN = 2400
CT_LEN = 1088
SS_LEN = 32
SESSION_ID_LEN = 16
MAX_SEQ = 2**63

PROTOCOL_LABEL = b"hospital-edge-cloud/ml-kem-768/v1"
REQUEST_LABEL = b"aggregate-request"
RESPONSE_LABEL = b"aggregate-response"

_KEM = ML_KEM_768
_backend_checked = False


class ChannelError(Exception):
    """Raised for any handshake or message-protection failure."""


# --------------------------------------------------------------------------
# Encoding helpers
# --------------------------------------------------------------------------
def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError, TypeError) as error:
        raise ChannelError("Invalid Base64 value.") from error


def _lp(data: bytes) -> bytes:
    """Length-prefix a field so concatenations are unambiguous."""
    return len(data).to_bytes(4, "big") + data


# --------------------------------------------------------------------------
# KEM backend (single place to swap the implementation)
# --------------------------------------------------------------------------
def _check_backend() -> None:
    """Round-trip self-test; also catches argument-order changes between versions."""
    global _backend_checked
    if _backend_checked:
        return
    try:
        ek, dk = _KEM.keygen()
        shared, ct = _KEM.encaps(ek)
        ok = (
            _KEM.decaps(dk, ct) == shared
            and len(ek) == EK_LEN
            and len(dk) == DK_LEN
            and len(ct) == CT_LEN
            and len(shared) == SS_LEN
        )
    except Exception as error:  # noqa: BLE001 - any failure means unusable backend
        raise RuntimeError(f"ML-KEM backend self-test failed: {error}") from error
    if not ok:
        raise RuntimeError("ML-KEM backend self-test failed: unexpected sizes or mismatch.")
    _backend_checked = True


def generate_kem_keypair() -> tuple[bytes, bytes]:
    """Return (encapsulation_key, decapsulation_key)."""
    _check_backend()
    return _KEM.keygen()


def kem_encapsulate(ek: bytes) -> tuple[bytes, bytes]:
    """Return (shared_secret, ciphertext)."""
    _check_backend()
    if len(ek) != EK_LEN:
        raise ChannelError("Encapsulation key has the wrong length.")
    try:
        return _KEM.encaps(ek)
    except Exception as error:  # noqa: BLE001
        raise ChannelError("Encapsulation failed (invalid public key).") from error


def kem_decapsulate(dk: bytes, ct: bytes) -> bytes:
    """Return the shared secret. ML-KEM uses implicit rejection for bad ciphertexts."""
    _check_backend()
    if len(ct) != CT_LEN:
        raise ChannelError("KEM ciphertext has the wrong length.")
    try:
        return _KEM.decaps(dk, ct)
    except Exception as error:  # noqa: BLE001
        raise ChannelError("Decapsulation failed.") from error


# --------------------------------------------------------------------------
# Key schedule
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SessionKeys:
    session_id: bytes
    gateway_to_cloud: bytes
    cloud_to_gateway: bytes

    def seal_request(self, seq: int, plaintext: bytes) -> bytes:
        return _seal(self.gateway_to_cloud, self.session_id, seq, REQUEST_LABEL, plaintext)

    def open_request(self, seq: int, ciphertext: bytes) -> bytes:
        return _open(self.gateway_to_cloud, self.session_id, seq, REQUEST_LABEL, ciphertext)

    def seal_response(self, seq: int, plaintext: bytes) -> bytes:
        return _seal(self.cloud_to_gateway, self.session_id, seq, RESPONSE_LABEL, plaintext)

    def open_response(self, seq: int, ciphertext: bytes) -> bytes:
        return _open(self.cloud_to_gateway, self.session_id, seq, RESPONSE_LABEL, ciphertext)


def _derive_session_keys(
    k1: bytes,
    k2: bytes,
    *,
    gateway_id: str,
    session_id: bytes,
    ct1: bytes,
    ct2: bytes,
    cloud_ek: bytes,
    gateway_ek: bytes,
) -> SessionKeys:
    transcript = hashlib.sha256(
        PROTOCOL_LABEL
        + _lp(gateway_id.encode("utf-8"))
        + _lp(session_id)
        + _lp(ct1)
        + _lp(ct2)
        + _lp(hashlib.sha256(cloud_ek).digest())
        + _lp(hashlib.sha256(gateway_ek).digest())
    ).digest()
    okm = HKDF(
        algorithm=hashes.SHA256(),
        length=64,
        salt=transcript,
        info=PROTOCOL_LABEL,
    ).derive(k1 + k2)
    return SessionKeys(session_id, okm[:32], okm[32:])


# --------------------------------------------------------------------------
# Handshake
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class InitiatorState:
    ct1: bytes
    k1: bytes


def initiator_begin(cloud_ek: bytes) -> InitiatorState:
    """Gateway step 1: encapsulate to the pinned cloud public key."""
    k1, ct1 = kem_encapsulate(cloud_ek)
    return InitiatorState(ct1=ct1, k1=k1)


def responder_accept(
    *,
    cloud_ek: bytes,
    cloud_dk: bytes,
    gateway_id: str,
    gateway_ek: bytes,
    ct1: bytes,
) -> tuple[bytes, SessionKeys]:
    """Cloud step: returns (ct2, session keys). The session id is in the keys."""
    k1 = kem_decapsulate(cloud_dk, ct1)
    k2, ct2 = kem_encapsulate(gateway_ek)
    session_id = os.urandom(SESSION_ID_LEN)
    keys = _derive_session_keys(
        k1, k2,
        gateway_id=gateway_id, session_id=session_id, ct1=ct1, ct2=ct2,
        cloud_ek=cloud_ek, gateway_ek=gateway_ek,
    )
    return ct2, keys


def initiator_finish(
    state: InitiatorState,
    *,
    gateway_id: str,
    gateway_ek: bytes,
    gateway_dk: bytes,
    cloud_ek: bytes,
    session_id: bytes,
    ct2: bytes,
) -> SessionKeys:
    """Gateway step 2: recover K2 and derive the session keys."""
    if len(session_id) != SESSION_ID_LEN:
        raise ChannelError("Session id has the wrong length.")
    k2 = kem_decapsulate(gateway_dk, ct2)
    return _derive_session_keys(
        state.k1, k2,
        gateway_id=gateway_id, session_id=session_id, ct1=state.ct1, ct2=ct2,
        cloud_ek=cloud_ek, gateway_ek=gateway_ek,
    )


# --------------------------------------------------------------------------
# Record protection (AES-256-GCM)
# --------------------------------------------------------------------------
def _nonce(seq: int) -> bytes:
    return seq.to_bytes(12, "big")


def _aad(session_id: bytes, seq: int, label: bytes) -> bytes:
    return _lp(PROTOCOL_LABEL) + _lp(session_id) + seq.to_bytes(8, "big") + _lp(label)


def _check_seq(seq: int) -> None:
    if not isinstance(seq, int) or isinstance(seq, bool) or not 0 <= seq < MAX_SEQ:
        raise ChannelError("Invalid sequence number.")


def _seal(key: bytes, session_id: bytes, seq: int, label: bytes, plaintext: bytes) -> bytes:
    _check_seq(seq)
    return AESGCM(key).encrypt(_nonce(seq), plaintext, _aad(session_id, seq, label))


def _open(key: bytes, session_id: bytes, seq: int, label: bytes, ciphertext: bytes) -> bytes:
    _check_seq(seq)
    try:
        return AESGCM(key).decrypt(_nonce(seq), ciphertext, _aad(session_id, seq, label))
    except InvalidTag as error:
        raise ChannelError("Message authentication failed.") from error
