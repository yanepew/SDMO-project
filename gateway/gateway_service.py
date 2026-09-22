"""
Simulated hospital edge gateway.

Responsibilities:
- receive encrypted data from legacy devices,
- decrypt legacy ChaCha20 payloads,
- map a device ID to synthetic patient information,
- check health thresholds,
- print simulated nurse/reception alerts,
- aggregate readings by hour,
- send aggregate records to the cloud REST API.

This is an educational simulation only.
"""

import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

import requests
from flask import Flask, jsonify, request

from shared.legacy_crypto import decrypt_json


app = Flask(__name__)

CLOUD_URL = os.getenv("CLOUD_URL", "http://127.0.0.1:8002")
HOSPITAL_DATABASE_PATH = Path(__file__).parent / "hospital_database.json"

# In-memory aggregation storage:
# {
#   ("device-id", "2026-02-16T10:00:00+00:00"): [reading, reading, ...]
# }
hourly_readings: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
aggregation_lock = Lock()


def load_hospital_database() -> dict[str, dict[str, str]]:
    """Load the simulated local hospital patient/device mapping database."""
    with HOSPITAL_DATABASE_PATH.open("r", encoding="utf-8") as database_file:
        return json.load(database_file)


hospital_database = load_hospital_database()


def get_hour_bucket(timestamp: str) -> str:
    """
    Convert a timestamp into an hourly bucket.

    Example:
    2026-02-16T10:43:20+00:00 becomes 2026-02-16T10:00:00+00:00
    """
    parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

    if parsed_timestamp.tzinfo is None:
        parsed_timestamp = parsed_timestamp.replace(tzinfo=UTC)

    hour_start = parsed_timestamp.replace(minute=0, second=0, microsecond=0)
    return hour_start.isoformat()


def validate_reading(reading: dict[str, Any]) -> None:
    """Validate the required device reading fields."""
    required_fields = {
        "device_id": str,
        "timestamp": str,
        "heart_rate_bpm": int,
        "blood_oxygen_percent": int,
    }

    for field_name, expected_type in required_fields.items():
        if field_name not in reading:
            raise ValueError(f"Missing required reading field: {field_name}")

        if not isinstance(reading[field_name], expected_type):
            raise ValueError(
                f"Field '{field_name}' must be {expected_type.__name__}, "
                f"received {type(reading[field_name]).__name__}."
            )

    if not 0 <= reading["heart_rate_bpm"] <= 300:
        raise ValueError("Heart rate is outside the allowed simulation range.")

    if not 0 <= reading["blood_oxygen_percent"] <= 100:
        raise ValueError("Blood oxygen is outside the allowed simulation range.")

    # Validate timestamp format.
    datetime.fromisoformat(reading["timestamp"].replace("Z", "+00:00"))


def get_health_issues(reading: dict[str, Any]) -> list[str]:
    """Return a list of detected health issues."""
    issues = []

    heart_rate = reading["heart_rate_bpm"]
    blood_oxygen = reading["blood_oxygen_percent"]

    if heart_rate < 40:
        issues.append(f"heart rate dangerously low ({heart_rate} BPM)")
    elif heart_rate > 100:
        issues.append(f"heart rate high ({heart_rate} BPM)")

    if blood_oxygen < 90:
        issues.append(f"blood oxygen low ({blood_oxygen}%)")

    return issues


def send_alert_to_nurse(patient: dict[str, str], reading: dict[str, Any], issues: list[str]) -> None:
    """
    Simulated alert mechanism.

    In a real system this might send a message to a nurse-call platform,
    pager, clinical dashboard, or hospital alert service.
    """
    alert_message = (
        "\n"
        "!" * 70
        + "\n"
        + "[GATEWAY ALERT] ATTENTION NURSE / RECEPTION\n"
        + f"Patient: {patient['patient_name']} ({patient['patient_id']})\n"
        + f"Room: {patient['room_number']}, Bed: {patient['bed_number']}\n"
        + f"Device: {reading['device_id']}\n"
        + f"Heart rate: {reading['heart_rate_bpm']} BPM\n"
        + f"Blood oxygen: {reading['blood_oxygen_percent']}%\n"
        + f"Detected issue(s): {', '.join(issues)}\n"
        + "!" * 70
    )
    print(alert_message)


def add_reading_to_hourly_aggregation(reading: dict[str, Any]) -> None:
    """Store a reading in the appropriate in-memory hourly aggregation bucket."""
    hour_bucket = get_hour_bucket(reading["timestamp"])
    aggregation_key = (reading["device_id"], hour_bucket)

    with aggregation_lock:
        hourly_readings[aggregation_key].append(reading)


def create_aggregate(
    device_id: str,
    hour_bucket: str,
    readings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create one hourly min/max/average aggregate record."""
    patient = hospital_database[device_id]

    heart_rates = [reading["heart_rate_bpm"] for reading in readings]
    blood_oxygen_values = [reading["blood_oxygen_percent"] for reading in readings]

    return {
        "patient_id": patient["patient_id"],
        "patient_name": patient["patient_name"],
        "room_number": patient["room_number"],
        "bed_number": patient["bed_number"],
        "device_id": device_id,
        "hour_start": hour_bucket,
        "reading_count": len(readings),
        "heart_rate_bpm": {
            "minimum": min(heart_rates),
            "maximum": max(heart_rates),
            "average": round(sum(heart_rates) / len(heart_rates), 2),
        },
        "blood_oxygen_percent": {
            "minimum": min(blood_oxygen_values),
            "maximum": max(blood_oxygen_values),
            "average": round(sum(blood_oxygen_values) / len(blood_oxygen_values), 2),
        },
    }


def send_aggregate_to_cloud(aggregate: dict[str, Any]) -> None:
    """Send one processed aggregate record to the cloud REST API."""
    response = requests.post(
        f"{CLOUD_URL}/aggregates",
        json=aggregate,
        timeout=5,
    )
    response.raise_for_status()


def flush_aggregates(include_current_hour: bool = False) -> dict[str, Any]:
    """
    Send completed hourly aggregates to the cloud.

    Normally:
    - completed hours are sent automatically;
    - the current hour remains in gateway memory.

    For demonstrations:
    - include_current_hour=True sends all current data immediately.
    """
    current_hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0).isoformat()

    aggregates_to_send: list[tuple[tuple[str, str], dict[str, Any]]] = []

    with aggregation_lock:
        for aggregation_key, readings in list(hourly_readings.items()):
            device_id, hour_bucket = aggregation_key

            should_flush = include_current_hour or hour_bucket < current_hour

            if should_flush and readings:
                aggregate = create_aggregate(device_id, hour_bucket, readings)
                aggregates_to_send.append((aggregation_key, aggregate))

    successful_keys = []
    errors = []

    for aggregation_key, aggregate in aggregates_to_send:
        try:
            send_aggregate_to_cloud(aggregate)
            successful_keys.append(aggregation_key)

            print(
                "[GATEWAY] Sent hourly aggregate to cloud: "
                f"patient={aggregate['patient_name']}, "
                f"hour={aggregate['hour_start']}, "
                f"readings={aggregate['reading_count']}"
            )
        except requests.RequestException as error:
            errors.append(
                {
                    "device_id": aggregate["device_id"],
                    "hour_start": aggregate["hour_start"],
                    "error": str(error),
                }
            )
            print(f"[GATEWAY] Failed to send aggregate to cloud: {error}")

    # Remove only aggregates that were successfully sent.
    with aggregation_lock:
        for aggregation_key in successful_keys:
            hourly_readings.pop(aggregation_key, None)

    return {
        "sent_aggregate_count": len(successful_keys),
        "failed_aggregate_count": len(errors),
        "errors": errors,
    }


@app.get("/health")
def health() -> tuple[Any, int]:
    """Simple gateway health endpoint."""
    return jsonify(
        {
            "service": "edge-gateway",
            "status": "healthy",
            "known_devices": list(hospital_database.keys()),
            "cloud_url": CLOUD_URL,
        }
    ), 200


@app.post("/device-data")
def receive_device_data() -> tuple[Any, int]:
    """
    Receive an encrypted legacy device payload.

    Expected transport format:

    {
      "algorithm": "ChaCha20-legacy-no-authentication",
      "nonce": "...base64...",
      "ciphertext": "...base64..."
    }
    """
    encrypted_payload = request.get_json(silent=True)

    if not encrypted_payload:
        return jsonify({"error": "Expected a JSON encrypted payload."}), 400

    try:
        reading = decrypt_json(encrypted_payload)
        validate_reading(reading)

        device_id = reading["device_id"]

        if device_id not in hospital_database:
            return jsonify(
                {
                    "error": "Unknown device ID.",
                    "device_id": device_id,
                }
            ), 404

        patient = hospital_database[device_id]
        issues = get_health_issues(reading)

        print(
            "[GATEWAY] Received reading: "
            f"device={device_id}, "
            f"patient={patient['patient_name']}, "
            f"heart_rate={reading['heart_rate_bpm']}, "
            f"blood_oxygen={reading['blood_oxygen_percent']}"
        )

        if issues:
            send_alert_to_nurse(patient, reading, issues)

        add_reading_to_hourly_aggregation(reading)

        # Send completed previous-hour buckets, if any.
        flush_aggregates(include_current_hour=False)

        return jsonify(
            {
                "status": "accepted",
                "device_id": device_id,
                "patient_id": patient["patient_id"],
                "alert_created": len(issues) > 0,
                "issues": issues,
            }
        ), 202

    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        print(f"[GATEWAY] Unexpected processing error: {error}")
        return jsonify({"error": "Gateway could not process the device message."}), 500


@app.get("/pending-aggregates")
def pending_aggregates() -> tuple[Any, int]:
    """Display readings currently stored in gateway aggregation memory."""
    pending = []

    with aggregation_lock:
        for (device_id, hour_bucket), readings in hourly_readings.items():
            patient = hospital_database.get(device_id, {})
            pending.append(
                {
                    "device_id": device_id,
                    "patient_name": patient.get("patient_name", "Unknown"),
                    "hour_start": hour_bucket,
                    "reading_count": len(readings),
                }
            )

    return jsonify(
        {
            "pending_aggregate_buckets": pending,
            "bucket_count": len(pending),
        }
    ), 200


@app.post("/flush-aggregates")
def flush_current_aggregates() -> tuple[Any, int]:
    """
    Demonstration endpoint to immediately send current-hour aggregates to cloud.
    """
    result = flush_aggregates(include_current_hour=True)
    return jsonify(result), 200


def main() -> None:
    print("=" * 70)
    print("SIMULATED EDGE GATEWAY STARTED")
    print("=" * 70)
    print("[GATEWAY] Listening on http://127.0.0.1:8001")
    print(f"[GATEWAY] Cloud URL: {CLOUD_URL}")
    print(f"[GATEWAY] Loaded devices: {', '.join(hospital_database.keys())}")
    print("[GATEWAY] Development server only; not for production use.")
    print()

    app.run(host="127.0.0.1", port=8001, debug=False)


if __name__ == "__main__":
    main()
