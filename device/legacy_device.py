"""
Simulated limited-capability legacy patient-monitoring device.

The device:
- generates synthetic heart-rate and blood-oxygen readings,
- simulates a 4 KB memory limit,
- waits between readings to simulate limited processing capability,
- encrypts data with legacy XChaCha20,
- sends encrypted readings to the edge gateway.

This is an educational simulation only.
"""

import os
import random
import time
from datetime import UTC, datetime

import traceback

import requests

from device.legacy_encrypt import encrypt_json
from device.legacy_memory_controller import MemoryController

SIMULATED_MEMORY_LIMIT_BYTES = 4096
mem = MemoryController(SIMULATED_MEMORY_LIMIT_BYTES, True)
mem.alloc_var("device_id", "bed-a-001")
mem.alloc_var("GATEWAY_URL", os.getenv("GATEWAY_URL", "http://127.0.0.1:8001"))
mem.alloc_var("SENSOR_READING_INTERVAL_SECONDS", 5)
mem.alloc_var("HTTP_TIMEOUT_SECONDS", 5)

def generate_heart_rate() -> None:
    """
    Generate a synthetic heart-rate reading.

    Most values are normal. Some intentionally abnormal values are generated
    so that the gateway alerting logic can be demonstrated.
    """
    with mem.auto_alloc("abnormal_case", random.random()):
        if mem["abnormal_case"] < 0.08:
            mem["heart_rate"] = random.randint(25, 39)  # dangerously low
        elif mem["abnormal_case"] < 0.16:
            mem["heart_rate"] = random.randint(101, 140)  # high
        else:
            mem["heart_rate"] = random.randint(55, 95)

def generate_blood_oxygen() -> int:
    """
    Generate a synthetic blood-oxygen saturation percentage.

    Most values are normal. Some intentionally abnormal values are generated.
    """
    if random.random() < 0.12:
        mem["blood_oxygen"] = random.randint(82, 89)  # low blood oxygen
    else:
        mem["blood_oxygen"] = random.randint(94, 100)


def collect_sensor_reading() -> None:
    """Create one synthetic patient-monitoring reading."""
    with mem.auto_alloc_empty_vars("heart_rate", "blood_oxygen"):
        generate_heart_rate()
        generate_blood_oxygen()
        mem["payload"] = {
            "device_id": mem["device_id"],
            "timestamp": datetime.now(UTC).isoformat(),
            "heart_rate_bpm": mem["heart_rate"],
            "blood_oxygen_percent": mem["blood_oxygen"],
        }

def send_reading_to_gateway() -> None:
    """Encrypt and send one reading to the edge gateway."""
    with mem.auto_alloc("ciphered_json", None):
        encrypt_json(mem)

        with mem.temp_alloc(1012): #simulate the post to take 1 KB, in reality post returns an object ~ 30KB
            response = requests.post(
                f"{mem["GATEWAY_URL"]}/device-data",
                json=mem["ciphered_json"],
                timeout=mem["HTTP_TIMEOUT_SECONDS"],
            )
            response.raise_for_status()

            print(
                "[DEVICE] Sent encrypted reading: "
                f"heart_rate={mem["payload"]['heart_rate_bpm']} BPM, "
                f"blood_oxygen={mem["payload"]['blood_oxygen_percent']}%, "
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
        with mem.temp_alloc(1012): #simulate the post to take 1 KB
            response = requests.post(
                f"{mem["GATEWAY_URL"]}/flush-aggregates",
                timeout=mem["HTTP_TIMEOUT_SECONDS"],
            )
            response.raise_for_status()
            print("[DEVICE] Requested gateway aggregate flush.")
    except requests.RequestException as error:
        print(f"[DEVICE] Could not request gateway aggregate flush: {error}")

def main() -> None:
    with mem.auto_alloc("id", input("Give device ID, if you type nothing bed-a-001 is used as ID: ")):
        if len(mem["id"]) > 0:
            mem["device_id"] = mem["id"]
    print("=" * 70)
    print("SIMULATED LEGACY DEVICE STARTED")
    print("=" * 70)
    print(f"[DEVICE] Device ID: {mem["device_id"]}")
    print(f"[DEVICE] Gateway URL: {mem["GATEWAY_URL"]}")
    print(f"[DEVICE] Simulated memory limit: {SIMULATED_MEMORY_LIMIT_BYTES} bytes")
    print(f"[DEVICE] Sensor reading interval: {mem["SENSOR_READING_INTERVAL_SECONDS"]} seconds")
    print("[DEVICE] Press Ctrl+C to stop and flush gateway aggregates.")
    print()

    try:
        while True:
            try:
                with mem.auto_alloc("payload", None):
                    start_time = time.time()
                    collect_sensor_reading()
                    send_reading_to_gateway()
                    t = time.time() - start_time
                    print("took: " + str(t) + "s")
            except MemoryError as error:
                print(f"[DEVICE] Memory constraint error: {error}")
            except requests.RequestException as error:
                print(f"[DEVICE] Network error while contacting gateway: {error}")
            except Exception as error:
                print(f"[DEVICE] Unexpected error: {error}")
                traceback.print_exc()

            # Simulates limited processing power and periodic sensor collection.
            time.sleep(mem["SENSOR_READING_INTERVAL_SECONDS"])

    except KeyboardInterrupt:
        print("\n[DEVICE] Device stopping.")
        request_gateway_flush()

if __name__ == "__main__":
    main()
