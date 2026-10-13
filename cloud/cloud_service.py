"""
Simulated cloud storage service.

The cloud:
- exposes a REST API,
- accepts an ML-KEM handshake from trusted edge gateways (POST /handshake),
- receives aggregates only through the authenticated-encryption channel
  (POST /secure/aggregates),
- stores them in an in-memory Python dictionary, grouped by patient name.

This is an educational simulation only.
"""

import json
import os
from datetime import datetime
from threading import Lock
from typing import Any

from flask import Flask, jsonify, request

from cloud.session_store import SessionError, SessionStore, SessionStoreFull
from common.keystore import KeyRecord, keys_dir, load_key, load_trusted_gateways, trusted_gateways_dir
from common.pqc_channel import ChannelError, b64d, b64e, responder_accept

app = Flask(__name__)

# In-memory simulated cloud database: {"Patient Name": [aggregate, ...]}
cloud_database: dict[str, list[dict[str, Any]]] = {}
database_lock = Lock()

# Security state, initialised by configure_security() (called from main() or tests).
cloud_identity: KeyRecord | None = None
trusted_gateways: dict[str, bytes] = {}
session_store = SessionStore()


def configure_security(identity: KeyRecord, gateways: dict[str, bytes], store: SessionStore | None = None) -> None:
    """Install the cloud's ML-KEM identity and the allow-list of gateway public keys."""
    global cloud_identity, trusted_gateways, session_store
    if identity.dk is None:
        raise ValueError("Cloud identity needs a private key.")
    cloud_identity = identity
    trusted_gateways = dict(gateways)
    session_store = store or SessionStore()


def _parse_timestamp(name: str, value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO-8601 string.")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name} is not a valid ISO-8601 timestamp.") from error


def validate_aggregate(aggregate: dict[str, Any]) -> None:
    """Validate basic expected aggregate fields."""
    if not isinstance(aggregate, dict):
        raise ValueError("Aggregate must be a JSON object.")

    required_fields = [
        "patient_id",
        "patient_name",
        "room_number",
        "bed_number",
        "device_id",
        "window_start",
        "window_end",
        "sent_at",
        "reading_count",
        "heart_rate_bpm",
        "blood_oxygen_percent",
    ]

    for field_name in required_fields:
        if field_name not in aggregate:
            raise ValueError(f"Missing required aggregate field: {field_name}")

    if not isinstance(aggregate["patient_name"], str):
        raise ValueError("patient_name must be a string.")

    for timestamp_field in ("window_start", "window_end", "sent_at"):
        _parse_timestamp(timestamp_field, aggregate[timestamp_field])

    count = aggregate["reading_count"]
    if not isinstance(count, int) or isinstance(count, bool):
        raise ValueError("reading_count must be an integer.")
    if count < 1:
        raise ValueError("reading_count must be at least 1.")

    for metric_name in ["heart_rate_bpm", "blood_oxygen_percent"]:
        metric = aggregate[metric_name]

        if not isinstance(metric, dict):
            raise ValueError(f"{metric_name} must be an object.")

        for statistic in ["minimum", "maximum", "average"]:
            if statistic not in metric:
                raise ValueError(f"{metric_name} is missing '{statistic}'.")


def store_aggregate(aggregate: dict[str, Any]) -> dict[str, Any]:
    """Validate and store one aggregate; returns the response body."""
    validate_aggregate(aggregate)
    patient_name = aggregate["patient_name"]

    with database_lock:
        new_patient_created = patient_name not in cloud_database
        if new_patient_created:
            cloud_database[patient_name] = []
        cloud_database[patient_name].append(aggregate)
        patient_record_count = len(cloud_database[patient_name])

    print(
        "[CLOUD] Stored aggregate: "
        f"patient={patient_name}, "
        f"window={aggregate['window_start']}..{aggregate['window_end']}, "
        f"sent_at={aggregate['sent_at']}, "
        f"total_records_for_patient={patient_record_count}"
    )
    return {
        "status": "stored",
        "patient_name": patient_name,
        "new_patient_created": new_patient_created,
        "patient_record_count": patient_record_count,
    }


def _debug_endpoints_enabled() -> bool:
    return os.getenv("CLOUD_DEBUG_ENDPOINTS", "1") == "1"


@app.get("/health")
def health() -> tuple[Any, int]:
    """Cloud service health endpoint (no patient data)."""
    with database_lock:
        patient_count = len(cloud_database)
        aggregate_count = sum(len(records) for records in cloud_database.values())

    return jsonify(
        {
            "service": "cloud-service",
            "status": "healthy",
            "patient_count": patient_count,
            "aggregate_record_count": aggregate_count,
            "security": "ML-KEM-768 channel",
            "active_sessions": len(session_store),
        }
    ), 200


@app.post("/handshake")
def handshake() -> tuple[Any, int]:
    """
    ML-KEM handshake. Body: {"gateway_id": str, "ct1": base64}.
    Returns: {"session_id": base64, "ct2": base64}.
    """
    if cloud_identity is None:
        return jsonify({"error": "Cloud security is not configured."}), 503

    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("gateway_id"), str):
        return jsonify({"error": "Malformed handshake."}), 400

    # Cheap allow-list check *before* any expensive KEM work.
    gateway_ek = trusted_gateways.get(body["gateway_id"])
    if gateway_ek is None:
        return jsonify({"error": "Handshake rejected."}), 403

    try:
        ct1 = b64d(body.get("ct1", ""))
        ct2, keys = responder_accept(
            cloud_ek=cloud_identity.ek,
            cloud_dk=cloud_identity.dk,
            gateway_id=body["gateway_id"],
            gateway_ek=gateway_ek,
            ct1=ct1,
        )
        session_store.add(body["gateway_id"], keys)
    except ChannelError:
        return jsonify({"error": "Malformed handshake."}), 400
    except SessionStoreFull:
        return jsonify({"error": "Server busy, retry later."}), 503

    print(f"[CLOUD] Handshake completed for gateway '{body['gateway_id']}'.")
    return jsonify({"session_id": b64e(keys.session_id), "ct2": b64e(ct2)}), 200


@app.post("/secure/aggregates")
def receive_secure_aggregate() -> tuple[Any, int]:
    """
    Receive a processed aggregate from the edge gateway.

    Envelope: {"session_id": base64, "seq": int, "ciphertext": base64}.
    The decrypted payload is the aggregate JSON; the reply is also encrypted,
    which authenticates the cloud to the gateway.
    """
    envelope = request.get_json(silent=True)
    if not isinstance(envelope, dict):
        return jsonify({"error": "Malformed envelope."}), 400

    try:
        session_id = b64d(envelope["session_id"])
        ciphertext = b64d(envelope["ciphertext"])
        seq = envelope["seq"]
        if not isinstance(seq, int) or isinstance(seq, bool):
            raise ValueError
    except (KeyError, ValueError, TypeError, ChannelError):
        return jsonify({"error": "Malformed envelope."}), 400

    try:
        session, plaintext = session_store.open_request(session_id, seq, ciphertext)
    except SessionError as error:
        return jsonify({"error": str(error)}), error.status

    try:
        reply = {"status_code": 201, **store_aggregate(json.loads(plaintext))}
    except (ValueError, UnicodeDecodeError) as error:  # JSONDecodeError is a ValueError
        reply = {"status_code": 400, "error": str(error)}

    sealed = session.keys.seal_response(seq, json.dumps(reply, separators=(",", ":")).encode("utf-8"))
    return jsonify({"ciphertext": b64e(sealed)}), 200


# ---- Demonstration read endpoints (plain HTTP, NO authentication) ---------
# Disable with CLOUD_DEBUG_ENDPOINTS=0. Never expose these in a real deployment.
@app.get("/patients")
def list_patients() -> tuple[Any, int]:
    """List all patients currently represented in cloud storage."""
    if not _debug_endpoints_enabled():
        return jsonify({"error": "Not found."}), 404
    with database_lock:
        patients = [
            {"patient_name": name, "aggregate_record_count": len(records)}
            for name, records in cloud_database.items()
        ]
    return jsonify({"patients": patients, "patient_count": len(patients)}), 200


@app.get("/patients/<path:patient_name>")
def get_patient(patient_name: str) -> tuple[Any, int]:
    """Return all cloud aggregate records stored for one patient."""
    if not _debug_endpoints_enabled():
        return jsonify({"error": "Not found."}), 404
    with database_lock:
        if patient_name not in cloud_database:
            return jsonify({"error": "Patient not found in cloud storage.", "patient_name": patient_name}), 404
        records = list(cloud_database[patient_name])
    return jsonify(
        {"patient_name": patient_name, "aggregate_record_count": len(records), "aggregates": records}
    ), 200


@app.get("/database")
def view_entire_database() -> tuple[Any, int]:
    """Return the entire simulated cloud database (demonstration only)."""
    if not _debug_endpoints_enabled():
        return jsonify({"error": "Not found."}), 404
    with database_lock:
        database_copy = {name: list(records) for name, records in cloud_database.items()}
    return jsonify(database_copy), 200


def main() -> None:
    identity = load_key(keys_dir() / "cloud.private.json", require_private=True)
    gateways = load_trusted_gateways(trusted_gateways_dir())
    configure_security(identity, gateways)

    host = os.getenv("CLOUD_HOST", "127.0.0.1")
    print("=" * 70)
    print("SIMULATED CLOUD SERVICE STARTED")
    print("=" * 70)
    print(f"[CLOUD] Listening on http://{host}:8002 (application-layer ML-KEM-768 channel)")
    print(f"[CLOUD] Trusted gateways: {', '.join(gateways) or 'NONE'}")
    if not gateways:
        print("[CLOUD] WARNING: no trusted gateway keys found; run `python -m common.keygen dev`.")
    print()

    app.run(host=host, port=8002, debug=False)


if __name__ == "__main__":
    main()
