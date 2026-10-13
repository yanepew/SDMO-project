# System Architecture

```text
Legacy Device --XChaCha20 (hard-coded key, unchanged)--> Edge Gateway
Edge Gateway  --ML-KEM-768 handshake + AES-256-GCM-----> Cloud Service
```

## Components
* **Legacy device** (`device/`) – untouched.
* **Edge gateway** (`gateway/`) – decrypts legacy payloads, raises alerts, buffers readings,
  and every *N* seconds (`--interval`) sends one aggregate per device through `SecureCloudClient`.
* **Cloud** (`cloud/`) – `/handshake` + `/secure/aggregates`, `SessionStore` (TTLs, caps, replay check), in-memory DB by patient name.
* **Shared** (`common/`) – `pqc_channel` (protocol), `keystore` (key files), `keygen` (provisioning CLI).

## Gateway ↔ cloud channel
Mutual authentication by pinned static ML-KEM-768 keys (KEMTLS-style): the gateway encapsulates to the
cloud's key (K1), the cloud encapsulates to the gateway's key (K2); session keys =
HKDF-SHA256(K1‖K2, salt = transcript hash). Records use AES-256-GCM, per-direction keys,
sequence number as nonce, AAD binding session, sequence and message type.
Rekey after 30 min or 1000 messages (gateway), session TTL 1 h (cloud). Impostor responses fail authentication and drop the session.

### Why not certificates / TLS?
The requirement is an ML-KEM-secured connection. Python's standard `ssl` module has no portable way to
require ML-KEM key exchange, so key establishment is done at the application layer on top of plain HTTP.
Trade-offs: URL paths and message sizes are visible; there is no PKI revocation (rotate by replacing key files).

### Library choice
`kyber-py`: pure Python, FIPS 203 `ML_KEM_768`, easy `pip install` on Windows. Not constant-time and
slower than native code; fine for a simulation. For production swap the three `kem_*` functions for
`liboqs-python` or an OpenSSL ≥ 3.5 binding.

## Aggregation timing
Readings are buffered per device; a scheduler thread flushes every interval. Failed sends are re-queued
and merged into the next aggregate. Shutdown (Ctrl+C) and `/flush-aggregates` also flush.

## Delivery pipeline
CI (`.github/workflows/ci.yml`): ruff, pytest + coverage (Ubuntu/Windows × Python 3.12/3.13), bandit, pip-audit, end-to-end smoke run.
CD (`cd.yml`): on a `vX.Y.Z` tag, re-run CI, then publish `cloud` and `gateway` images to GHCR.

See also: `docs/fallback-strategies.md`, `docs/api.md`.
