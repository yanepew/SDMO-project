"""
Simulated limited-capability legacy patient-monitoring device.

The device:
- generates synthetic heart-rate and blood-oxygen readings,
- simulates a 2 KB payload/memory limit,
- waits between readings to simulate limited processing capability,
- encrypts data with legacy ChaCha20,
- sends encrypted readings to the edge gateway.

This is an educational simulation only.
"""

import json
import os
import random
import time
from datetime import UTC, datetime

import requests

from shared.legacy_crypto import encrypt_json


device_id = "bed-a-001"
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8001")

# Simulated constrained-device characteristics.
SIMULATED_MEMORY_LIMIT_BYTES = 2048
SENSOR_READING_INTERVAL_SECONDS = 5
HTTP_TIMEOUT_SECONDS = 5


def generate_heart_rate() -> int:
    """
    Generate a synthetic heart-rate reading.

    Most values are normal. Some intentionally abnormal values are generated
    so that the gateway alerting logic can be demonstrated.
    """
    abnormal_case = random.random()

    if abnormal_case < 0.08:
        return random.randint(25, 39)  # dangerously low
    if abnormal_case < 0.16:
        return random.randint(101, 140)  # high
    return random.randint(55, 95)


def generate_blood_oxygen() -> int:
    """
    Generate a synthetic blood-oxygen saturation percentage.

    Most values are normal. Some intentionally abnormal values are generated.
    """
    if random.random() < 0.12:
        return random.randint(82, 89)  # low blood oxygen
    return random.randint(94, 100)


def collect_sensor_reading() -> dict:
    """Create one synthetic patient-monitoring reading."""
    return {
        "device_id": device_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "heart_rate_bpm": generate_heart_rate(),
        "blood_oxygen_percent": generate_blood_oxygen(),
    }


def enforce_simulated_memory_limit(payload: dict) -> None:
    """
    Simulate the device's limited memory/payload capacity.

    This does not limit the real Python process to 2 KB. Instead, it ensures
    the outgoing serialized sensor message fits within the simulated 2 KB
    message-memory constraint.
    """
    payload_size = len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    if payload_size > SIMULATED_MEMORY_LIMIT_BYTES:
        raise MemoryError(
            f"Simulated device payload is {payload_size} bytes, exceeding the "
            f"{SIMULATED_MEMORY_LIMIT_BYTES}-byte legacy device limit."
        )


def send_reading_to_gateway(reading: dict) -> None:
    """Encrypt and send one reading to the edge gateway."""
    enforce_simulated_memory_limit(reading)

    encrypted_payload = encrypt_json(reading)

    # The final encrypted HTTP body should also remain below the simulated limit.
    enforce_simulated_memory_limit(encrypted_payload)

    response = requests.post(
        f"{GATEWAY_URL}/device-data",
        json=encrypted_payload,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    print(
        "[DEVICE] Sent encrypted reading: "
        f"heart_rate={reading['heart_rate_bpm']} BPM, "
        f"blood_oxygen={reading['blood_oxygen_percent']}%, "
        f"gateway_response={response.status_code}"
    )


def request_gateway_flush() -> None:
    """
    Ask the gateway to flush current aggregated data to the cloud.

    Normally, hourly aggregation would be transmitted after an hour has ended.
    This endpoint exists so the simulated demonstration can be completed
    without waiting for a full hour.
    """
    try:
        response = requests.post(
            f"{GATEWAY_URL}/flush-aggregates",
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        print("[DEVICE] Requested gateway aggregate flush.")
    except requests.RequestException as error:
        print(f"[DEVICE] Could not request gateway aggregate flush: {error}")


def main() -> None:
    id = input("Give device ID, if you type nothing bed-a-001 is used as ID: ")
    if len(id) > 0:
        device_id = id
    print("=" * 70)
    print("SIMULATED LEGACY DEVICE STARTED")
    print("=" * 70)
    print(f"[DEVICE] Device ID: {device_id}")
    print(f"[DEVICE] Gateway URL: {GATEWAY_URL}")
    print(f"[DEVICE] Simulated memory limit: {SIMULATED_MEMORY_LIMIT_BYTES} bytes")
    print(f"[DEVICE] Sensor reading interval: {SENSOR_READING_INTERVAL_SECONDS} seconds")
    print("[DEVICE] Press Ctrl+C to stop and flush gateway aggregates.")
    print()

    try:
        while True:
            try:
                reading = collect_sensor_reading()
                send_reading_to_gateway(reading)
            except MemoryError as error:
                print(f"[DEVICE] Memory constraint error: {error}")
            except requests.RequestException as error:
                print(f"[DEVICE] Network error while contacting gateway: {error}")
            except Exception as error:
                print(f"[DEVICE] Unexpected error: {error}")

            # Simulates limited processing power and periodic sensor collection.
            time.sleep(SENSOR_READING_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\n[DEVICE] Device stopping.")
        request_gateway_flush()


if __name__ == "__main__":
    main()
