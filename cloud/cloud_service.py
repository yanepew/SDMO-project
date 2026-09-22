"""
Simulated cloud storage service.

The cloud:
- exposes a REST API,
- receives hourly aggregates from the edge gateway,
- stores them in an in-memory Python dictionary,
- stores records by patient name.

This is an educational simulation only.
"""

from threading import Lock
from typing import Any

from flask import Flask, jsonify, request


app = Flask(__name__)

# In-memory simulated cloud database.
#
# Example:
# {
#   "Synthetic Patient One": [
#       {... hourly aggregate ...},
#       {... hourly aggregate ...}
#   ]
# }
cloud_database: dict[str, list[dict[str, Any]]] = {}
database_lock = Lock()


def validate_aggregate(aggregate: dict[str, Any]) -> None:
    """Validate basic expected aggregate fields."""
    required_fields = [
        "patient_id",
        "patient_name",
        "room_number",
        "bed_number",
        "device_id",
        "hour_start",
        "reading_count",
        "heart_rate_bpm",
        "blood_oxygen_percent",
    ]

    for field_name in required_fields:
        if field_name not in aggregate:
            raise ValueError(f"Missing required aggregate field: {field_name}")

    if not isinstance(aggregate["patient_name"], str):
        raise ValueError("patient_name must be a string.")

    if not isinstance(aggregate["reading_count"], int):
        raise ValueError("reading_count must be an integer.")

    if aggregate["reading_count"] < 1:
        raise ValueError("reading_count must be at least 1.")

    for metric_name in ["heart_rate_bpm", "blood_oxygen_percent"]:
        metric = aggregate[metric_name]

        if not isinstance(metric, dict):
            raise ValueError(f"{metric_name} must be an object.")

        for statistic in ["minimum", "maximum", "average"]:
            if statistic not in metric:
                raise ValueError(f"{metric_name} is missing '{statistic}'.")


@app.get("/health")
def health() -> tuple[Any, int]:
    """Cloud service health endpoint."""
    with database_lock:
        patient_count = len(cloud_database)
        aggregate_count = sum(len(records) for records in cloud_database.values())

    return jsonify(
        {
            "service": "cloud-service",
            "status": "healthy",
            "patient_count": patient_count,
            "aggregate_record_count": aggregate_count,
        }
    ), 200


@app.post("/aggregates")
def receive_aggregate() -> tuple[Any, int]:
    """
    Receive a processed hourly aggregate from the edge gateway.

    The cloud database is grouped by patient name, as required by this
    simulation. If the patient does not exist, a new patient record is created.
    """
    aggregate = request.get_json(silent=True)

    if not aggregate:
        return jsonify({"error": "Expected an aggregate JSON object."}), 400

    try:
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
            f"hour={aggregate['hour_start']}, "
            f"total_records_for_patient={patient_record_count}"
        )

        return jsonify(
            {
                "status": "stored",
                "patient_name": patient_name,
                "new_patient_created": new_patient_created,
                "patient_record_count": patient_record_count,
            }
        ), 201

    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.get("/patients")
def list_patients() -> tuple[Any, int]:
    """List all patients currently represented in cloud storage."""
    with database_lock:
        patients = [
            {
                "patient_name": patient_name,
                "aggregate_record_count": len(records),
            }
            for patient_name, records in cloud_database.items()
        ]

    return jsonify(
        {
            "patients": patients,
            "patient_count": len(patients),
        }
    ), 200


@app.get("/patients/<path:patient_name>")
def get_patient(patient_name: str) -> tuple[Any, int]:
    """Return all cloud aggregate records stored for one patient."""
    with database_lock:
        if patient_name not in cloud_database:
            return jsonify(
                {
                    "error": "Patient not found in cloud storage.",
                    "patient_name": patient_name,
                }
            ), 404

        records = cloud_database[patient_name]

    return jsonify(
        {
            "patient_name": patient_name,
            "aggregate_record_count": len(records),
            "aggregates": records,
        }
    ), 200


@app.get("/database")
def view_entire_database() -> tuple[Any, int]:
    """
    Return the entire simulated cloud database.

    This endpoint is useful for a classroom demonstration but would be
    inappropriate in a real healthcare environment.
    """
    with database_lock:
        database_copy = dict(cloud_database)

    return jsonify(database_copy), 200


def main() -> None:
    print("=" * 70)
    print("SIMULATED CLOUD SERVICE STARTED")
    print("=" * 70)
    print("[CLOUD] Listening on http://127.0.0.1:8002")
    print("[CLOUD] Storage type: in-memory Python dictionary")
    print("[CLOUD] Development server only; not for production use.")
    print()

    app.run(host="127.0.0.1", port=8002, debug=False)


if __name__ == "__main__":
    main()
