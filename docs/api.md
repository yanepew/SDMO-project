# API reference

## Legacy device → Gateway (unchanged, intentionally insecure)

`POST /device-data` – XChaCha20 payload `{algorithm, nonce, ciphertext}` (hard-coded key, no authentication).
`POST /flush-aggregates` – send everything buffered now (the device calls this on Ctrl+C).

## Gateway (port 8001)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | status, known devices, `aggregate_interval_seconds` |
| POST | `/device-data` | receive an encrypted reading (buffered, no cloud call) |
| GET | `/pending-aggregates` | readings buffered for the next send |
| POST | `/flush-aggregates` | send buffered data to the cloud immediately |

Start-up: `python -m gateway.gateway_service --interval 5m`
(`30s`, `5m`, `1h`, or plain seconds; env `AGGREGATE_INTERVAL`; default `1h`; minimum 1 s).

## Cloud (port 8002)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | status counters, no patient data |
| POST | `/handshake` | trusted gateway id + ML-KEM | establish a session |
| POST | `/secure/aggregates` | session (AES-256-GCM) | store an aggregate |
| GET | `/patients`, `/patients/<name>`, `/database` | **none** | demo only; disable with `CLOUD_DEBUG_ENDPOINTS=0` |

The old plain `POST /aggregates` endpoint was **removed**.

### Handshake
Request `{"gateway_id": "gateway-1", "ct1": "<b64 ML-KEM ciphertext, 1088 B>"}` →
response `{"session_id": "<b64, 16 B>", "ct2": "<b64, 1088 B>"}`. See `common/pqc_channel.py`.

### Secure aggregate
Request `{"session_id": "<b64>", "seq": 0, "ciphertext": "<b64>"}`; `seq` must strictly increase per session.
Response `{"ciphertext": "<b64>"}` – decrypts to `{"status_code": 201, "status": "stored", ...}` or `{"status_code": 400, "error": ...}`.
Envelope-level errors: 400 malformed, 401 unknown/expired session or failed authentication, 409 replay, 503 busy.

### Aggregate record (changed)
```json
{
  "patient_id": "P-10001", "patient_name": "Synthetic Patient One",
  "room_number": "A-101", "bed_number": "1", "device_id": "bed-a-001",
  "window_start": "2026-10-04T10:01:05+00:00",
  "window_end":   "2026-10-04T10:07:30+00:00",
  "sent_at":      "2026-10-04T10:08:03.123456+00:00",
  "reading_count": 12,
  "heart_rate_bpm": {"minimum": 58, "maximum": 91, "average": 72.4},
  "blood_oxygen_percent": {"minimum": 95, "maximum": 99, "average": 97.1}
}
```
`hour_start` was replaced by `window_start`/`window_end` (first/last reading) and `sent_at` (exact send time).
