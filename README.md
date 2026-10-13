# Legacy Hospital Edge–Cloud Monitoring System (modernised)

Synthetic-data simulation of a legacy bedside monitor → edge gateway → cloud pipeline, modernised for
post-quantum cryptography (PQC). **Never use with real patients or production systems.**

## What changed in the modernisation
| Area | Before | Now |
|---|---|---|
| Gateway → cloud security | HTTPS, self-signed cert, `verify=False` | **ML-KEM-768** handshake (mutually authenticated, pinned keys) + AES-256-GCM |
| Aggregate send | hard-coded, hourly buckets | `--interval` chosen at gateway start (`30s`, `5m`, `1h`, …) |
| Timestamps | `hour_start` (whole hour) | `window_start`, `window_end`, exact `sent_at` |
| Quality | none | pytest suite, ruff, bandit, pip-audit, GitHub Actions CI/CD, Docker |
| Legacy device ↔ gateway | XChaCha20, hard-coded key | **unchanged and still insecure by design** |

Details: `docs/architecture.md`, `docs/api.md`, `docs/fallback-strategies.md`, `docs/legacy-security-notes.md`.

## Layout
```text
device/    legacy device (unmodified)       common/   ML-KEM channel, key store, keygen
gateway/   edge gateway + secure client     cloud/    cloud service + session store
tests/     pytest suite                     scripts/  run_demo.ps1, smoke_test.py
```

## Setup (Windows PowerShell; Python 3.12+ is required)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m common.keygen dev        # once: creates keys\ (cloud + gateway keys, mutual trust)
```
`keys\` holds private keys and is git-ignored. In a real deployment run `keygen cloud` / `keygen gateway --id <id>`
on the respective hosts and copy only the *public* files (`cloud.public.json` to the gateway,
`gateway.public.json` into the cloud's `keys\trusted_gateways\`).

## Run
Automatic: `.\scripts\run_demo.ps1 -Interval 30s` (it also creates keys if missing).

Manually (order: cloud → gateway → device):
```powershell
python -m cloud.cloud_service
python -m gateway.gateway_service --interval 30s     # default 1h; env AGGREGATE_INTERVAL also works
python -m device.legacy_device
```
Browse `http://127.0.0.1:8002/health`, `/patients`, `/database` (demo endpoints, no auth; set `CLOUD_DEBUG_ENDPOINTS=0` to disable)
and `http://127.0.0.1:8001/health`, `/pending-aggregates`. Ctrl+C on the device flushes the gateway.

## Tests and CI/CD
```powershell
pip install -r requirements-dev.txt
pytest --cov
ruff check .
```
GitHub Actions: `ci.yml` on every push/PR (lint, tests on Ubuntu+Windows × 3.12/3.13, security scans, end-to-end smoke run);
`cd.yml` on tags `vX.Y.Z` (CI, then Docker images for `cloud` and `gateway` to GHCR).
The `slow` test runs the real, unmodified legacy encryption against the gateway's decryption.

## Known limitations
* `kyber-py` is pure Python and not constant-time; swap `common/pqc_channel.py::kem_*` for liboqs in production.
* Static pinned keys: no revocation/rotation automation yet.
* The ML-KEM fallback strategies are documented, not implemented.
