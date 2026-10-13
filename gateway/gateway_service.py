"""
Simulated hospital edge gateway.

Responsibilities:
- receive encrypted data from legacy devices,
- decrypt legacy XChaCha20 payloads (legacy link is unchanged and insecure by design),
- map a device ID to synthetic patient information,
- check health thresholds,
- print simulated nurse/reception alerts,
- aggregate readings and send one aggregate per device every N seconds,
  where N is chosen by whoever starts the gateway (--interval),
- deliver aggregates to the cloud over the ML-KEM secured channel.

This is an educational simulation only.
"""

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

import requests
from flask import Flask, jsonify, request

from common.keystore import keys_dir, load_key
from gateway.cloud_client import CloudClientError, SecureCloudClient
from gateway.legacy_decrypt import decrypt_json

app = Flask(__name__)

DEFAULT_CLOUD_URL = "http://127.0.0.1:8002"
DEFAULT_INTERVAL_SECONDS = 3600.0  # previous hard-coded behaviour: one hour
CLOUD_URL = os.getenv("CLOUD_URL", DEFAULT_CLOUD_URL)
HOSPITAL_DATABASE_PATH = Path(__file__).parent / "hospital_database.json"

# Readings waiting for the next aggregate send: {device_id: [reading, ...]}
pending_readings: dict[str, list[dict[str, Any]]] = {}
aggregation_lock = Lock()  # protects pending_readings
flush_lock = Lock()  # serialises whole flush operations (scheduler vs. manual)

aggregate_interval_seconds: float = DEFAULT_INTERVAL_SECONDS
cloud_client: SecureCloudClient | None = None


def load_hospital_database() -> dict[str, dict[str, str]]:
    """Load the simulated local hospital patient/device mapping database."""
    with HOSPITAL_DATABASE_PATH.open("r", encoding="utf-8") as database_file:
        return json.load(database_file)


hospital_database = load_hospital_database()


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
_DURATION = re.compile(r"\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*", re.IGNORECASE)
_UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600}


def parse_interval(text: str) -> float:
    """Parse '90', '30s', '5m', '1.5h' into seconds (minimum 1 second)."""
    match = _DURATION.fullmatch(str(text))
    if not match:
        raise ValueError(f"Invalid interval {text!r}; use e.g. 30s, 5m, 1h or a number of seconds.")
    seconds = float(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]
    if seconds < 1:
        raise ValueError("Interval must be at least 1 second.")
    return seconds


def _interval_arg(text: str) -> float:
    try:
        return parse_interval(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def configure_cloud_client(client: SecureCloudClient | None) -> None:
    global cloud_client
    cloud_client = client


# --------------------------------------------------------------------------
# Reading processing
# --------------------------------------------------------------------------
def _parse_timestamp(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


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

    _parse_timestamp(reading["timestamp"])  # validates the format


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


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------
def add_reading_to_aggregation(reading: dict[str, Any]) -> None:
    """Buffer a reading until the next aggregate send."""
    with aggregation_lock:
        pending_readings.setdefault(reading["device_id"], []).append(reading)


def create_aggregate(
    device_id: str,
    readings: list[dict[str, Any]],
    sent_at: datetime,
) -> dict[str, Any]:
    """
    Create one min/max/average aggregate.

    window_start / window_end are the first and last reading timestamps in the
    aggregate; sent_at is the exact moment the aggregate was produced for sending.
    """
    patient = hospital_database[device_id]

    heart_rates = [reading["heart_rate_bpm"] for reading in readings]
    blood_oxygen_values = [reading["blood_oxygen_percent"] for reading in readings]
    timestamps = sorted(_parse_timestamp(reading["timestamp"]) for reading in readings)

    return {
        "patient_id": patient["patient_id"],
        "patient_name": patient["patient_name"],
        "room_number": patient["room_number"],
        "bed_number": patient["bed_number"],
        "device_id": device_id,
        "window_start": timestamps[0].isoformat(),
        "window_end": timestamps[-1].isoformat(),
        "sent_at": sent_at.isoformat(),
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
    """Send one aggregate to the cloud over the ML-KEM secured channel."""
    if cloud_client is None:
        raise CloudClientError("Cloud client is not configured.")
    cloud_client.post_aggregate(aggregate)


def flush_aggregates() -> dict[str, Any]:
    """
    Send everything buffered since the last flush: one aggregate per device.

    Readings whose aggregate could not be delivered are put back (in order) and
    are included in the next attempt, so nothing is lost on a cloud outage.
    """
    with flush_lock:
        with aggregation_lock:
            snapshot = {device: readings for device, readings in pending_readings.items() if readings}
            pending_readings.clear()

        sent = 0
        errors = []
        for device_id, readings in snapshot.items():
            aggregate = create_aggregate(device_id, readings, datetime.now(UTC))
            try:
                send_aggregate_to_cloud(aggregate)
                sent += 1
                print(
                    "[GATEWAY] Sent aggregate to cloud: "
                    f"patient={aggregate['patient_name']}, "
                    f"sent_at={aggregate['sent_at']}, "
                    f"readings={aggregate['reading_count']}"
                )
            except (CloudClientError, requests.RequestException) as error:
                errors.append({"device_id": device_id, "sent_at": aggregate["sent_at"], "error": str(error)})
                print(f"[GATEWAY] Failed to send aggregate to cloud (will retry): {error}")
                with aggregation_lock:
                    pending_readings[device_id] = readings + pending_readings.get(device_id, [])

    return {
        "sent_aggregate_count": sent,
        "failed_aggregate_count": len(errors),
        "errors": errors,
    }


class AggregateScheduler(Thread):
    """Calls flush_aggregates() every `interval` seconds until stopped."""

    def __init__(self, interval: float, flush=flush_aggregates):
        super().__init__(name="aggregate-scheduler", daemon=True)
        self.interval = interval
        self._flush = flush
        self._stop_event = Event()

    def run(self) -> None:
        while not self._stop_event.wait(self.interval):
            try:
                self._flush()
            except Exception as error:  # noqa: BLE001 - keep the scheduler alive
                print(f"[GATEWAY] Scheduled flush failed: {error}")

    def stop(self) -> None:
        self._stop_event.set()


# --------------------------------------------------------------------------
# HTTP API
# --------------------------------------------------------------------------
@app.get("/health")
def health() -> tuple[Any, int]:
    """Simple gateway health endpoint."""
    return jsonify(
        {
            "service": "edge-gateway",
            "status": "healthy",
            "known_devices": list(hospital_database.keys()),
            "cloud_url": CLOUD_URL,
            "aggregate_interval_seconds": aggregate_interval_seconds,
            "cloud_channel": "ML-KEM-768",
        }
    ), 200


@app.post("/device-data")
def receive_device_data() -> tuple[Any, int]:
    """
    Receive an encrypted legacy device payload.

    Expected transport format (unchanged legacy format):

    {
      "algorithm": "XChaCha20-legacy-no-authentication",
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
            return jsonify({"error": "Unknown device ID.", "device_id": device_id}), 404

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

        add_reading_to_aggregation(reading)

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
    except Exception as error:  # noqa: BLE001
        print(f"[GATEWAY] Unexpected processing error: {error}")
        return jsonify({"error": "Gateway could not process the device message."}), 500


@app.get("/pending-aggregates")
def pending_aggregates() -> tuple[Any, int]:
    """Display readings currently buffered for the next aggregate send."""
    pending = []

    with aggregation_lock:
        for device_id, readings in pending_readings.items():
            patient = hospital_database.get(device_id, {})
            pending.append(
                {
                    "device_id": device_id,
                    "patient_name": patient.get("patient_name", "Unknown"),
                    "reading_count": len(readings),
                }
            )

    return jsonify(
        {
            "pending_aggregate_buckets": pending,
            "bucket_count": len(pending),
            "aggregate_interval_seconds": aggregate_interval_seconds,
        }
    ), 200


@app.post("/flush-aggregates")
def flush_current_aggregates() -> tuple[Any, int]:
    """Immediately send all buffered data (used by the legacy device on Ctrl+C)."""
    return jsonify(flush_aggregates()), 200


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def build_cloud_client(cloud_url: str) -> SecureCloudClient:
    gateway_key = load_key(
        Path(os.getenv("GATEWAY_KEY_FILE", keys_dir() / "gateway.private.json")), require_private=True
    )
    cloud_key = load_key(Path(os.getenv("CLOUD_PUBLIC_KEY_FILE", keys_dir() / "cloud.public.json")))
    return SecureCloudClient(cloud_url, gateway=gateway_key, cloud_ek=cloud_key.ek)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulated edge gateway")
    parser.add_argument(
        "--interval",
        type=_interval_arg,
        default=_interval_arg(os.getenv("AGGREGATE_INTERVAL", "1h")),
        help="How often aggregates are sent to the cloud, e.g. 30s, 5m, 1h "
        "(env AGGREGATE_INTERVAL, default 1h).",
    )
    parser.add_argument("--cloud-url", default=CLOUD_URL, help="Cloud base URL.")
    return parser.parse_args(argv)


def main() -> None:
    global aggregate_interval_seconds, CLOUD_URL
    args = parse_args()
    aggregate_interval_seconds = args.interval
    CLOUD_URL = args.cloud_url
    configure_cloud_client(build_cloud_client(CLOUD_URL))

    host = os.getenv("GATEWAY_HOST", "127.0.0.1")
    print("=" * 70)
    print("SIMULATED EDGE GATEWAY STARTED")
    print("=" * 70)
    print(f"[GATEWAY] Listening on http://{host}:8001")
    print(f"[GATEWAY] Cloud URL: {CLOUD_URL} (ML-KEM-768 secured channel)")
    print(f"[GATEWAY] Aggregate send interval: {aggregate_interval_seconds:g} seconds")
    print(f"[GATEWAY] Loaded devices: {', '.join(hospital_database.keys())}")
    print("[GATEWAY] Development server only; not for production use.")
    print()

    scheduler = AggregateScheduler(aggregate_interval_seconds)
    scheduler.start()
    try:
        app.run(host=host, port=8001, debug=False)
    finally:
        scheduler.stop()
        flush_aggregates()


if __name__ == "__main__":
    main()
