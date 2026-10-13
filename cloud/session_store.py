"""Server-side session bookkeeping for the ML-KEM channel (cloud side)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Callable

from common.pqc_channel import ChannelError, SessionKeys


class SessionError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class SessionStoreFull(Exception):
    """Too many live sessions; refuse new handshakes (basic DoS protection)."""


@dataclass
class CloudSession:
    keys: SessionKeys
    gateway_id: str
    expires_at: float
    confirmed: bool = False
    last_seq: int = -1


class SessionStore:
    """
    Sessions start *unconfirmed* with a short lifetime. They become confirmed
    only after the first message authenticates under the session key, which
    proves the peer really holds the gateway's private ML-KEM key.
    """

    def __init__(
        self,
        max_sessions: int = 1000,
        established_ttl: float = 3600.0,
        pending_ttl: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._max = max_sessions
        self._established_ttl = established_ttl
        self._pending_ttl = pending_ttl
        self._clock = clock
        self._sessions: dict[bytes, CloudSession] = {}
        self._lock = Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _purge_expired(self) -> None:
        now = self._clock()
        for sid in [s for s, v in self._sessions.items() if v.expires_at <= now]:
            del self._sessions[sid]

    def add(self, gateway_id: str, keys: SessionKeys) -> None:
        with self._lock:
            self._purge_expired()
            if len(self._sessions) >= self._max:
                raise SessionStoreFull()
            self._sessions[keys.session_id] = CloudSession(
                keys=keys,
                gateway_id=gateway_id,
                expires_at=self._clock() + self._pending_ttl,
            )

    def open_request(self, session_id: bytes, seq: int, ciphertext: bytes) -> tuple[CloudSession, bytes]:
        """Authenticate/decrypt one request, enforcing replay protection."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.expires_at <= self._clock():
                self._sessions.pop(session_id, None)
                raise SessionError("Unknown or expired session.", 401)
            if not isinstance(seq, int) or seq <= session.last_seq:
                raise SessionError("Replayed or out-of-order message.", 409)
            try:
                plaintext = session.keys.open_request(seq, ciphertext)
            except ChannelError as error:
                raise SessionError("Message authentication failed.", 401) from error
            session.last_seq = seq
            if not session.confirmed:
                session.confirmed = True
                session.expires_at = self._clock() + self._established_ttl
            return session, plaintext
