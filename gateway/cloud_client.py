"""Gateway-side client for the ML-KEM secured cloud channel."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable

import requests

from common.keystore import KeyRecord
from common.pqc_channel import (
    ChannelError,
    SessionKeys,
    b64d,
    b64e,
    initiator_begin,
    initiator_finish,
)


class CloudClientError(Exception):
    """The aggregate could not be delivered (network, authentication or validation)."""


class _SessionRejected(Exception):
    """Cloud no longer knows/accepts the session (e.g. restart or expiry)."""


@dataclass
class _Session:
    keys: SessionKeys
    created_at: float
    next_seq: int = 0


class SecureCloudClient:
    def __init__(
        self,
        cloud_url: str,
        gateway: KeyRecord,
        cloud_ek: bytes,
        timeout: float = 5.0,
        max_session_age: float = 1800.0,
        max_session_messages: int = 1000,
        http: Any = requests,
        clock: Callable[[], float] = time.monotonic,
    ):
        if gateway.dk is None:
            raise ValueError("Gateway key record needs a private key.")
        self._url = cloud_url.rstrip("/")
        self._gateway = gateway
        self._cloud_ek = cloud_ek
        self._timeout = timeout
        self._max_age = max_session_age
        self._max_messages = max_session_messages
        self._http = http
        self._clock = clock
        self._session: _Session | None = None
        self._lock = Lock()

    # ---------------------------------------------------------------- helpers
    def _post(self, path: str, body: dict[str, Any]) -> Any:
        try:
            return self._http.post(f"{self._url}{path}", json=body, timeout=self._timeout)
        except requests.RequestException as error:
            raise CloudClientError(f"Network error contacting cloud: {error}") from error

    def _needs_new_session(self) -> bool:
        s = self._session
        return (
            s is None
            or self._clock() - s.created_at >= self._max_age
            or s.next_seq >= self._max_messages
        )

    # -------------------------------------------------------------- handshake
    def _handshake(self) -> None:
        self._session = None
        try:
            state = initiator_begin(self._cloud_ek)
            response = self._post(
                "/handshake",
                {"gateway_id": self._gateway.identity, "ct1": b64e(state.ct1)},
            )
            if response.status_code != 200:
                raise CloudClientError(f"Cloud rejected the handshake (HTTP {response.status_code}).")
            data = response.json()
            keys = initiator_finish(
                state,
                gateway_id=self._gateway.identity,
                gateway_ek=self._gateway.ek,
                gateway_dk=self._gateway.dk,
                cloud_ek=self._cloud_ek,
                session_id=b64d(data["session_id"]),
                ct2=b64d(data["ct2"]),
            )
        except (ChannelError, KeyError, ValueError, TypeError) as error:
            raise CloudClientError(f"Handshake failed: {error}") from error
        self._session = _Session(keys=keys, created_at=self._clock())

    # ------------------------------------------------------------------- send
    def _send(self, aggregate: dict[str, Any]) -> dict[str, Any]:
        session = self._session
        seq = session.next_seq
        session.next_seq += 1  # never reuse a nonce, even if the request fails

        plaintext = json.dumps(aggregate, separators=(",", ":")).encode("utf-8")
        response = self._post(
            "/secure/aggregates",
            {
                "session_id": b64e(session.keys.session_id),
                "seq": seq,
                "ciphertext": b64e(session.keys.seal_request(seq, plaintext)),
            },
        )
        if response.status_code in (401, 409):
            raise _SessionRejected()
        if response.status_code != 200:
            raise CloudClientError(f"Cloud returned HTTP {response.status_code}.")

        # A reply that authenticates under the session key proves the peer holds
        # the pinned cloud private key. Anything else is treated as an impostor.
        try:
            reply = json.loads(session.keys.open_response(seq, b64d(response.json()["ciphertext"])))
        except (ChannelError, KeyError, ValueError, TypeError) as error:
            self._session = None
            raise CloudClientError("Cloud response failed authentication.") from error

        if reply.get("status_code", 500) >= 400:
            raise CloudClientError(f"Cloud refused the aggregate: {reply.get('error', 'unknown error')}")
        return reply

    def post_aggregate(self, aggregate: dict[str, Any]) -> dict[str, Any]:
        """Deliver one aggregate; transparently (re)establishes the session."""
        with self._lock:
            for attempt in range(2):
                if self._needs_new_session():
                    self._handshake()
                try:
                    return self._send(aggregate)
                except _SessionRejected:
                    self._session = None
                    if attempt == 1:
                        raise CloudClientError("Cloud repeatedly rejected the secure session.") from None
            raise CloudClientError("Unreachable state.")  # pragma: no cover
