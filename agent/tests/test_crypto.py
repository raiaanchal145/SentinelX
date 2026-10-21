"""
Unit Tests for DPAPI Protection and Secret Masking.
"""

from agent.crypto import dpapi_decrypt, dpapi_encrypt, mask_secret


def test_dpapi_round_trip():
    secret = "sxa_device_secret_key_abcdef123456"
    encrypted = dpapi_encrypt(secret)
    assert encrypted != secret
    assert encrypted.startswith(("dpapi:", "b64:"))

    decrypted = dpapi_decrypt(encrypted)
    assert decrypted == secret


def test_mask_secret():
    assert mask_secret("sxe_1234567890abcdef") == "sxe_12...cdef"
    assert mask_secret("sxa_9988776655443322") == "sxa_99...3322"
    assert mask_secret("short") == "********"
    assert mask_secret("") == "<none>"
    assert mask_secret(None) == "<none>"
