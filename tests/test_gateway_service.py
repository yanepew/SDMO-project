from datetime import UTC, datetime

import pytest

from conftest import make_legacy_payload, make_reading
from gateway.cloud_client import CloudClientError


# ------------------------------------------------------------ interval parsing
@pytest.mark.parametrize(
    "text,seconds",
    [("90", 90), ("30s", 30), ("5m", 300), ("1h", 3600), ("1.5h", 5400), (" 2M ", 120)],
)
def test_parse_interval(gateway_service, text, seconds):
    assert gateway_service.parse_interval(text) == seconds


@pytest.mark.parametrize("text", ["", "abc", "0", "0.5s", "-5", "5d", "1h30m"])
def test_parse_interval_rejects_invalid(gateway_service, text):
    with pytest.raises(ValueError):
        gateway_service.parse_interval(text)


def test_cli_interval_option(gateway_service):
    assert gateway_service.parse_args(["--interval", "10s"]).interval == 10


def test_interval_from_environment(gateway_service, monkeypatch):
    monkeypatch.setenv("AGGREGATE_INTERVAL", "2m")
    assert gateway_service.parse_args([]).interval == 120


# ------------------------------------------------------------------ thresholds
@pytest.mark.parametrize(
    "hr,spo2,count",
    [(70, 97, 0), (39, 97, 1), (101, 97, 1), (40, 90, 0), (100, 89, 1), (30, 80, 2)],
)
def test_health_thresholds(gateway_service, hr, spo2, count):
    assert len(gateway_service.get_health_issues(make_reading(hr, spo2))) == count


# ------------------------------------------------------------------ aggregation
def test_aggregate_statistics_and_exact_timestamps(gateway_service):
    readings = [
        make_reading(60, 95, "2026-02-16T10:04:10+00:00"),
        make_reading(80, 99, "2026-02-16T10:01:05+00:00"),
        make_reading(70, 97, "2026-02-16T10:07:30+00:00"),
    ]
    sent_at = datetime(2026, 2, 16, 10, 8, 3, 123456, tzinfo=UTC)
    aggregate = gateway_service.create_aggregate("bed-a-001", readings, sent_at)

    assert aggregate["heart_rate_bpm"] == {"minimum": 60, "maximum": 80, "average": 70.0}
    assert aggregate["blood_oxygen_percent"] == {"minimum": 95, "maximum": 99, "average": 97.0}
    assert aggregate["reading_count"] == 3
    assert aggregate["window_start"] == "2026-02-16T10:01:05+00:00"
    assert aggregate["window_end"] == "2026-02-16T10:07:30+00:00"
    assert aggregate["sent_at"] == "2026-02-16T10:08:03.123456+00:00"  # not rounded to the hour
    assert "hour_start" not in aggregate
    assert aggregate["patient_name"] == "Synthetic Patient One"


# ------------------------------------------------------------------ device link
def test_device_payload_is_accepted_and_buffered(gateway_service):
    client = gateway_service.app.test_client()
    response = client.post("/device-data", json=make_legacy_payload(make_reading(72, 98)))
    assert response.status_code == 202
    assert response.get_json()["alert_created"] is False
    assert len(gateway_service.pending_readings["bed-a-001"]) == 1


def test_alert_for_abnormal_reading(gateway_service, capsys):
    client = gateway_service.app.test_client()
    response = client.post("/device-data", json=make_legacy_payload(make_reading(30, 85)))
    assert response.get_json()["alert_created"] is True
    assert "ATTENTION NURSE" in capsys.readouterr().out


def test_unknown_device_and_garbage_payloads(gateway_service):
    client = gateway_service.app.test_client()
    assert client.post("/device-data", json=make_legacy_payload(make_reading(device="nope"))).status_code == 404
    assert client.post("/device-data", json={"nonce": "AA==", "ciphertext": "AA=="}).status_code == 400
    assert client.post("/device-data", json={}).status_code == 400


def test_receiving_a_reading_does_not_contact_cloud(gateway_service, http, cloud_service):
    gateway_service.app.test_client().post("/device-data", json=make_legacy_payload(make_reading()))
    assert http.calls == []  # sending is driven by the interval, not by incoming readings


# ------------------------------------------------------------------ flushing
def _post_readings(gateway_service, n=3):
    client = gateway_service.app.test_client()
    for i in range(n):
        client.post("/device-data", json=make_legacy_payload(make_reading(60 + i, 97)))


def test_flush_sends_one_aggregate_per_device_and_clears_buffer(gateway_service, cloud_service):
    _post_readings(gateway_service, 3)
    result = gateway_service.app.test_client().post("/flush-aggregates").get_json()
    assert result["sent_aggregate_count"] == 1
    stored = cloud_service.cloud_database["Synthetic Patient One"][0]
    assert stored["reading_count"] == 3
    assert gateway_service.pending_readings == {}


def test_failed_send_keeps_readings_for_next_attempt(gateway_service, cloud_service, monkeypatch):
    _post_readings(gateway_service, 2)
    original = gateway_service.send_aggregate_to_cloud

    def failing(_aggregate):
        raise CloudClientError("cloud down")

    monkeypatch.setattr(gateway_service, "send_aggregate_to_cloud", failing)
    result = gateway_service.flush_aggregates()
    assert result["failed_aggregate_count"] == 1
    assert len(gateway_service.pending_readings["bed-a-001"]) == 2

    monkeypatch.setattr(gateway_service, "send_aggregate_to_cloud", original)
    _post_readings(gateway_service, 1)  # new reading arrives during the outage
    assert gateway_service.flush_aggregates()["sent_aggregate_count"] == 1
    assert cloud_service.cloud_database["Synthetic Patient One"][0]["reading_count"] == 3


def test_flush_with_nothing_pending(gateway_service):
    assert gateway_service.flush_aggregates()["sent_aggregate_count"] == 0


def test_scheduler_flushes_on_interval_and_stops():
    import time
    from gateway.gateway_service import AggregateScheduler

    calls = []
    scheduler = AggregateScheduler(0.05, flush=lambda: calls.append(1))
    scheduler.start()
    time.sleep(0.4)
    scheduler.stop()
    scheduler.join(timeout=1)
    assert len(calls) >= 3
    assert not scheduler.is_alive()


def test_scheduler_survives_flush_errors():
    import time
    from gateway.gateway_service import AggregateScheduler

    calls = []

    def flaky():
        calls.append(1)
        raise RuntimeError("boom")

    scheduler = AggregateScheduler(0.05, flush=flaky)
    scheduler.start()
    time.sleep(0.3)
    scheduler.stop()
    assert len(calls) >= 2
