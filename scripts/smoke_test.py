"""End-to-end check used by CI: device-style payload -> gateway -> ML-KEM channel -> cloud."""

import base64
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime

import requests
from Crypto.Cipher import ChaCha20

GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:8001")
CLOUD = os.getenv("CLOUD_BASE", "http://127.0.0.1:8002")


def legacy_payload(reading: dict) -> dict:
    key = hashlib.sha256(b"legacy-demo-key-for-coursework-only").digest()
    nonce = os.urandom(24)
    message = json.dumps(reading, separators=(",", ":"), sort_keys=True).encode()
    return {
        "algorithm": "XChaCha20-legacy-no-authentication",
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ChaCha20.new(key=key, nonce=nonce).encrypt(message)).decode(),
    }


def main() -> int:
    reading = {
        "device_id": "bed-a-001",
        "timestamp": datetime.now(UTC).isoformat(),
        "heart_rate_bpm": 72,
        "blood_oxygen_percent": 98,
    }
    assert requests.post(f"{GATEWAY}/device-data", json=legacy_payload(reading), timeout=5).status_code == 202

    for _ in range(15):  # the gateway scheduler flushes on its own interval
        records = requests.get(f"{CLOUD}/database", timeout=5).json()
        if records.get("Synthetic Patient One"):
            print("OK: aggregate arrived through the ML-KEM channel:", records["Synthetic Patient One"][0]["sent_at"])
            return 0
        time.sleep(1)
    print("FAIL: no aggregate reached the cloud")
    return 1


if __name__ == "__main__":
    sys.exit(main())
