import pytest

from common import pqc_channel as ch
from common.keystore import KeyRecord, load_key, load_trusted_gateways, save_key


def _handshake(cloud, gateway, gateway_id="gw"):
    state = ch.initiator_begin(cloud.ek)
    ct2, cloud_keys = ch.responder_accept(
        cloud_ek=cloud.ek, cloud_dk=cloud.dk, gateway_id=gateway_id,
        gateway_ek=gateway.ek, ct1=state.ct1,
    )
    gw_keys = ch.initiator_finish(
        state, gateway_id=gateway_id, gateway_ek=gateway.ek, gateway_dk=gateway.dk,
        cloud_ek=cloud.ek, session_id=cloud_keys.session_id, ct2=ct2,
    )
    return cloud_keys, gw_keys


def test_kem_sizes_match_ml_kem_768():
    ek, dk = ch.generate_kem_keypair()
    secret, ct = ch.kem_encapsulate(ek)
    assert (len(ek), len(dk), len(ct), len(secret)) == (1184, 2400, 1088, 32)
    assert ch.kem_decapsulate(dk, ct) == secret


def test_both_sides_derive_identical_keys(key_material):
    cloud_keys, gw_keys = _handshake(key_material.cloud, key_material.gateway)
    assert cloud_keys == gw_keys


def test_sessions_are_unique(key_material):
    a, _ = _handshake(key_material.cloud, key_material.gateway)
    b, _ = _handshake(key_material.cloud, key_material.gateway)
    assert a.gateway_to_cloud != b.gateway_to_cloud


def test_request_response_roundtrip(key_material):
    cloud_keys, gw_keys = _handshake(key_material.cloud, key_material.gateway)
    sealed = gw_keys.seal_request(0, b"hello")
    assert cloud_keys.open_request(0, sealed) == b"hello"
    reply = cloud_keys.seal_response(0, b"world")
    assert gw_keys.open_response(0, reply) == b"world"


def test_tampering_and_wrong_sequence_are_detected(key_material):
    cloud_keys, gw_keys = _handshake(key_material.cloud, key_material.gateway)
    sealed = bytearray(gw_keys.seal_request(5, b"data"))
    with pytest.raises(ch.ChannelError):
        cloud_keys.open_request(6, bytes(sealed))  # different sequence number
    sealed[0] ^= 1
    with pytest.raises(ch.ChannelError):
        cloud_keys.open_request(5, bytes(sealed))  # flipped bit


def test_request_cannot_be_reflected_as_response(key_material):
    cloud_keys, gw_keys = _handshake(key_material.cloud, key_material.gateway)
    sealed = gw_keys.seal_request(1, b"data")
    with pytest.raises(ch.ChannelError):
        gw_keys.open_response(1, sealed)


def test_impostor_cloud_cannot_produce_matching_keys(key_material):
    impostor_ek, impostor_dk = ch.generate_kem_keypair()
    impostor = KeyRecord("cloud", "cloud", impostor_ek, impostor_dk)
    state = ch.initiator_begin(key_material.cloud.ek)  # gateway pinned the real cloud
    ct2, fake_keys = ch.responder_accept(
        cloud_ek=impostor.ek, cloud_dk=impostor.dk, gateway_id="gw",
        gateway_ek=key_material.gateway.ek, ct1=state.ct1,
    )
    gw_keys = ch.initiator_finish(
        state, gateway_id="gw", gateway_ek=key_material.gateway.ek,
        gateway_dk=key_material.gateway.dk, cloud_ek=key_material.cloud.ek,
        session_id=fake_keys.session_id, ct2=ct2,
    )
    with pytest.raises(ch.ChannelError):
        gw_keys.open_response(0, fake_keys.seal_response(0, b"fake"))


def test_wrong_length_ciphertext_rejected(key_material):
    with pytest.raises(ch.ChannelError):
        ch.responder_accept(
            cloud_ek=key_material.cloud.ek, cloud_dk=key_material.cloud.dk,
            gateway_id="gw", gateway_ek=key_material.gateway.ek, ct1=b"short",
        )


def test_invalid_sequence_numbers_rejected(key_material):
    _, gw_keys = _handshake(key_material.cloud, key_material.gateway)
    for bad in (-1, 2**63, True):
        with pytest.raises(ch.ChannelError):
            gw_keys.seal_request(bad, b"x")


def test_keystore_roundtrip_and_trusted_gateways(tmp_path, key_material):
    save_key(tmp_path / "gw.private.json", key_material.gateway, include_private=True)
    loaded = load_key(tmp_path / "gw.private.json", require_private=True)
    assert loaded == key_material.gateway

    save_key(tmp_path / "trusted" / "gw.json", key_material.gateway, include_private=False)
    assert load_trusted_gateways(tmp_path / "trusted") == {"gateway-test": key_material.gateway.ek}
    with pytest.raises(RuntimeError):
        load_key(tmp_path / "trusted" / "gw.json", require_private=True)
