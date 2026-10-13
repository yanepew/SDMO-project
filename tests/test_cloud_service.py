import json

from common import pqc_channel as ch
from conftest import GATEWAY_ID


def _aggregate(name="Synthetic Patient One"):
    stat = {"minimum": 1, "maximum": 3, "average": 2.0}
    return {
        "patient_id": "P-1", "patient_name": name, "room_number": "A", "bed_number": "1",
        "device_id": "bed-a-001",
        "window_start": "2026-02-16T10:00:00+00:00", "window_end": "2026-02-16T10:04:00+00:00",
        "sent_at": "2026-02-16T10:05:00+00:00", "reading_count": 3,
        "heart_rate_bpm": stat, "blood_oxygen_percent": stat,
    }


def test_plain_aggregates_endpoint_no_longer_exists(cloud_service):
    response = cloud_service.app.test_client().post("/aggregates", json=_aggregate())
    assert response.status_code in (404, 405)
    assert cloud_service.cloud_database == {}


def test_unknown_gateway_is_rejected_before_kem_work(cloud_service, key_material):
    state = ch.initiator_begin(key_material.cloud.ek)
    response = cloud_service.app.test_client().post(
        "/handshake", json={"gateway_id": "evil", "ct1": ch.b64e(state.ct1)}
    )
    assert response.status_code == 403


def test_malformed_handshake(cloud_service):
    client = cloud_service.app.test_client()
    assert client.post("/handshake", json={"gateway_id": GATEWAY_ID, "ct1": "!!"}).status_code == 400
    assert client.post("/handshake", json={"nope": 1}).status_code == 400


def test_secure_endpoint_requires_known_session(cloud_service):
    response = cloud_service.app.test_client().post(
        "/secure/aggregates",
        json={"session_id": ch.b64e(b"x" * 16), "seq": 0, "ciphertext": ch.b64e(b"junk")},
    )
    assert response.status_code == 401


def test_replay_is_rejected(secure_client, cloud_service, http):
    secure_client.post_aggregate(_aggregate())
    # Re-send the exact captured envelope.
    session = secure_client._session
    sealed = session.keys.seal_request(0, json.dumps(_aggregate()).encode())
    response = http.client.post(
        "/secure/aggregates",
        json={"session_id": ch.b64e(session.keys.session_id), "seq": 0, "ciphertext": ch.b64e(sealed)},
    )
    assert response.status_code == 409
    assert len(cloud_service.cloud_database["Synthetic Patient One"]) == 1


def test_invalid_aggregate_gets_authenticated_400(secure_client):
    from gateway.cloud_client import CloudClientError
    import pytest

    bad = _aggregate()
    del bad["sent_at"]
    with pytest.raises(CloudClientError, match="sent_at"):
        secure_client.post_aggregate(bad)


def test_debug_endpoints_can_be_disabled(cloud_service, monkeypatch):
    client = cloud_service.app.test_client()
    assert client.get("/database").status_code == 200
    monkeypatch.setenv("CLOUD_DEBUG_ENDPOINTS", "0")
    assert client.get("/database").status_code == 404
    assert client.get("/health").status_code == 200


def test_session_store_limits_and_expiry():
    from cloud.session_store import SessionError, SessionStore, SessionStoreFull
    from common.pqc_channel import SessionKeys
    import pytest

    now = [0.0]
    store = SessionStore(max_sessions=1, pending_ttl=10, established_ttl=100, clock=lambda: now[0])
    keys = SessionKeys(b"a" * 16, b"k" * 32, b"l" * 32)
    store.add("gw", keys)
    with pytest.raises(SessionStoreFull):
        store.add("gw", SessionKeys(b"b" * 16, b"k" * 32, b"l" * 32))
    now[0] = 11  # unconfirmed session expired
    with pytest.raises(SessionError):
        store.open_request(keys.session_id, 0, b"x")
    store.add("gw", SessionKeys(b"b" * 16, b"k" * 32, b"l" * 32))  # space freed
