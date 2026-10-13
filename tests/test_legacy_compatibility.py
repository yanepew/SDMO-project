"""The unmodified legacy device must still interoperate with the modernised gateway."""

import pytest

pytest.importorskip("pympler")

from conftest import make_reading  # noqa: E402


@pytest.mark.slow
def test_real_legacy_device_encryption_is_decryptable_by_gateway():
    from device.legacy_encrypt import encrypt_json
    from device.legacy_memory_controller import MemoryController
    from gateway.legacy_decrypt import decrypt_json

    reading = make_reading(72, 98)
    mem = MemoryController(8192, True)
    mem.alloc_var("payload", reading)
    mem.alloc_var("ciphered_json", None)
    encrypt_json(mem)

    assert decrypt_json(mem["ciphered_json"]) == reading
