import base64
import hashlib
import json
import os
from types import SimpleNamespace

import pytest
from Crypto.Cipher import ChaCha20

from common.keystore import KeyRecord
from common.pqc_channel import generate_kem_keypair
from gateway.cloud_client import SecureCloudClient

GATEWAY_ID = "gateway-test"


@pytest.fixture(scope="session")
def key_material():
    cloud_ek, cloud_dk = generate_kem_keypair()
    gw_ek, gw_dk = generate_kem_keypair()
    return SimpleNamespace(
        cloud=KeyRecord("cloud", "cloud", cloud_ek, cloud_dk),
        gateway=KeyRecord("gateway", GATEWAY_ID, gw_ek, gw_dk),
    )


class FlaskHttp:
    """Adapter so SecureCloudClient talks to a Flask test client instead of the network."""

    def __init__(self, test_client):
        self.client = test_client
        self.calls = []

    def post(self, url, json=None, timeout=None):
        path = "/" + url.split("//", 1)[1].split("/", 1)[1]
        self.calls.append(path)
        response = self.client.post(path, json=json)
        return SimpleNamespace(status_code=response.status_code, json=response.get_json)


@pytest.fixture
def cloud_service(key_material):
    from cloud import cloud_service as module

    module.cloud_database.clear()
    module.configure_security(key_material.cloud, {GATEWAY_ID: key_material.gateway.ek})
    return module


@pytest.fixture
def http(cloud_service):
    return FlaskHttp(cloud_service.app.test_client())


@pytest.fixture
def secure_client(cloud_service, key_material, http):
    return SecureCloudClient(
        "http://cloud.test", key_material.gateway, key_material.cloud.ek, http=http
    )


@pytest.fixture
def gateway_service(secure_client):
    from gateway import gateway_service as module

    module.pending_readings.clear()
    module.configure_cloud_client(secure_client)
    yield module
    module.configure_cloud_client(None)
    module.pending_readings.clear()


def make_legacy_payload(reading: dict, secret: str = "legacy-demo-key-for-coursework-only") -> dict:
    """Encrypt a reading exactly like the legacy device (XChaCha20, 24-byte nonce)."""
    key = hashlib.sha256(secret.encode()).digest()
    nonce = os.urandom(24)
    message = json.dumps(reading, separators=(",", ":"), sort_keys=True).encode()
    ciphertext = ChaCha20.new(key=key, nonce=nonce).encrypt(message)
    return {
        "algorithm": "XChaCha20-legacy-no-authentication",
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def make_reading(hr=70, spo2=97, ts="2026-02-16T10:43:20+00:00", device="bed-a-001") -> dict:
    return {"device_id": device, "timestamp": ts, "heart_rate_bpm": hr, "blood_oxygen_percent": spo2}
