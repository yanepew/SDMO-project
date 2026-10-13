import pytest

from common import pqc_channel as ch
from gateway.cloud_client import CloudClientError, SecureCloudClient
from test_cloud_service import _aggregate


def test_aggregate_is_stored_by_patient_name(secure_client, cloud_service):
    secure_client.post_aggregate(_aggregate("Synthetic Patient One"))
    secure_client.post_aggregate(_aggregate("Synthetic Patient Two"))
    secure_client.post_aggregate(_aggregate("Synthetic Patient One"))
    db = cloud_service.cloud_database
    assert len(db["Synthetic Patient One"]) == 2
    assert len(db["Synthetic Patient Two"]) == 1


def test_session_is_reused_between_messages(secure_client, http):
    for _ in range(3):
        secure_client.post_aggregate(_aggregate())
    assert http.calls.count("/handshake") == 1


def test_new_handshake_after_message_limit(cloud_service, key_material, http):
    client = SecureCloudClient("http://c.test", key_material.gateway, key_material.cloud.ek,
                               max_session_messages=2, http=http)
    for _ in range(5):
        client.post_aggregate(_aggregate())
    assert http.calls.count("/handshake") == 3


def test_new_handshake_after_session_age(cloud_service, key_material, http):
    now = [0.0]
    client = SecureCloudClient("http://c.test", key_material.gateway, key_material.cloud.ek,
                               max_session_age=60, http=http, clock=lambda: now[0])
    client.post_aggregate(_aggregate())
    now[0] = 61
    client.post_aggregate(_aggregate())
    assert http.calls.count("/handshake") == 2


def test_recovers_when_cloud_forgot_sessions(secure_client, cloud_service, http):
    secure_client.post_aggregate(_aggregate())
    cloud_service.session_store.clear()  # simulates a cloud restart
    secure_client.post_aggregate(_aggregate())
    assert http.calls.count("/handshake") == 2
    assert len(cloud_service.cloud_database["Synthetic Patient One"]) == 2


def test_gateway_pinned_to_wrong_cloud_key_fails_closed(cloud_service, key_material, http):
    wrong_ek, _dk = ch.generate_kem_keypair()
    client = SecureCloudClient("http://c.test", key_material.gateway, wrong_ek, http=http)
    with pytest.raises(CloudClientError):
        client.post_aggregate(_aggregate())
    assert cloud_service.cloud_database == {}  # impostor view: cloud could not even read it


def test_untrusted_gateway_cannot_connect(cloud_service, key_material, http):
    from common.keystore import KeyRecord
    ek, dk = ch.generate_kem_keypair()
    rogue = KeyRecord("gateway", "rogue", ek, dk)
    client = SecureCloudClient("http://c.test", rogue, key_material.cloud.ek, http=http)
    with pytest.raises(CloudClientError, match="rejected"):
        client.post_aggregate(_aggregate())


def test_forged_cloud_response_is_detected(secure_client, http):
    secure_client.post_aggregate(_aggregate())
    original_post = http.post

    def tampering_post(url, json=None, timeout=None):
        response = original_post(url, json=json, timeout=timeout)
        if url.endswith("/secure/aggregates"):
            body = response.json()
            raw = bytearray(ch.b64d(body["ciphertext"]))
            raw[0] ^= 1
            body["ciphertext"] = ch.b64e(bytes(raw))
            response.json = lambda: body
        return response

    http.post = tampering_post
    with pytest.raises(CloudClientError, match="authentication"):
        secure_client.post_aggregate(_aggregate())


def test_network_errors_become_client_errors(key_material):
    import requests

    class Down:
        def post(self, *a, **k):
            raise requests.ConnectionError("down")

    client = SecureCloudClient("http://c.test", key_material.gateway, key_material.cloud.ek, http=Down())
    with pytest.raises(CloudClientError, match="Network"):
        client.post_aggregate(_aggregate())
