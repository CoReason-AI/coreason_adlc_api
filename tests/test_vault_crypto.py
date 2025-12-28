# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import secrets
from typing import Generator

import pytest
from coreason_adlc_api.vault.crypto import VaultCrypto

# Valid 32-byte hex key
TEST_KEY = secrets.token_hex(32)


@pytest.fixture
def vault() -> Generator[VaultCrypto, None, None]:
    yield VaultCrypto(key_hex=TEST_KEY)


def test_encryption_decryption_cycle(vault: VaultCrypto) -> None:
    """Verify that a string can be encrypted and then decrypted to its original value."""
    original_text = "sk-live-1234567890abcdef"
    encrypted = vault.encrypt_secret(original_text)

    assert encrypted != original_text
    assert isinstance(encrypted, str)

    decrypted = vault.decrypt_secret(encrypted)
    assert decrypted == original_text


def test_encryption_randomness(vault: VaultCrypto) -> None:
    """Verify that encrypting the same text twice produces different outputs (due to nonce)."""
    text = "secret-value"
    enc1 = vault.encrypt_secret(text)
    enc2 = vault.encrypt_secret(text)

    assert enc1 != enc2
    assert vault.decrypt_secret(enc1) == text
    assert vault.decrypt_secret(enc2) == text


def test_initialization_with_invalid_key() -> None:
    """Verify error handling for invalid keys."""
    # Too short
    with pytest.raises(ValueError, match="ENCRYPTION_KEY must be 32 bytes"):
        VaultCrypto(key_hex="1234")

    # Not hex
    with pytest.raises(ValueError, match="ENCRYPTION_KEY must be a valid hex string"):
        VaultCrypto(key_hex="zzzz")

    # None and env var missing/empty (mocking env)
    # Note: We rely on the class logic, if settings provides a default, this test might need adjustment.
    # But passing explicit None should trigger the settings lookup.


def test_decryption_failure(vault: VaultCrypto) -> None:
    """Verify that tampering with the ciphertext causes decryption failure."""
    text = "my-secret"
    encrypted = vault.encrypt_secret(text)

    # Tamper with the base64 string safely
    # We replace the first character with something different
    replacement = "A" if encrypted[0] != "A" else "B"
    tampered = replacement + encrypted[1:]

    with pytest.raises(ValueError, match="Decryption failed"):
        vault.decrypt_secret(tampered)


def test_decrypt_invalid_base64(vault: VaultCrypto) -> None:
    """Verify error when input is not valid base64."""
    with pytest.raises(ValueError, match="Decryption failed"):
        vault.decrypt_secret("!@#$%^&*()")


def test_default_settings_key() -> None:
    """Verify it works with the default key from settings if none provided."""
    # Assuming config.py has a default valid key
    v = VaultCrypto()
    enc = v.encrypt_secret("test")
    assert v.decrypt_secret(enc) == "test"


def test_missing_env_key() -> None:
    """Verify it raises error if settings key is missing/empty."""
    from coreason_adlc_api.config import settings

    original = settings.ENCRYPTION_KEY
    try:
        settings.ENCRYPTION_KEY = ""
        with pytest.raises(ValueError, match="ENCRYPTION_KEY is not set"):
            VaultCrypto()
    finally:
        settings.ENCRYPTION_KEY = original


def test_encrypt_empty_string(vault: VaultCrypto) -> None:
    """Verify handling of empty strings."""
    encrypted = vault.encrypt_secret("")
    decrypted = vault.decrypt_secret(encrypted)
    assert decrypted == ""


def test_encrypt_unicode(vault: VaultCrypto) -> None:
    """Verify handling of Unicode characters."""
    text = "🔒 Secret Key with Emojis 🚀 and Symbols @#$%"
    encrypted = vault.encrypt_secret(text)
    decrypted = vault.decrypt_secret(encrypted)
    assert decrypted == text


def test_encrypt_large_payload(vault: VaultCrypto) -> None:
    """Verify handling of large payloads (e.g., 1MB)."""
    text = "a" * 1024 * 1024  # 1MB
    encrypted = vault.encrypt_secret(text)
    decrypted = vault.decrypt_secret(encrypted)
    assert decrypted == text


def test_decrypt_with_wrong_key(vault: VaultCrypto) -> None:
    """Verify that decryption fails when using a different key."""
    # Encrypt with the default vault fixture (Key A)
    text = "top-secret"
    encrypted = vault.encrypt_secret(text)

    # Initialize a second vault with a different key (Key B)
    other_key = secrets.token_hex(32)
    other_vault = VaultCrypto(key_hex=other_key)

    # Attempt to decrypt
    with pytest.raises(ValueError, match="Decryption failed"):
        other_vault.decrypt_secret(encrypted)


def test_key_rotation_workflow(vault: VaultCrypto) -> None:
    """Verify the workflow of rotating keys: Decrypt with old, re-encrypt with new."""
    secret_data = "my-precious-api-key"

    # 1. Encrypt with Key A (current vault)
    encrypted_a = vault.encrypt_secret(secret_data)

    # 2. Simulate Key Rotation
    new_key = secrets.token_hex(32)
    vault_b = VaultCrypto(key_hex=new_key)

    # 3. Decrypt with old key (Key A)
    decrypted = vault.decrypt_secret(encrypted_a)
    assert decrypted == secret_data

    # 4. Re-encrypt with new key (Key B)
    encrypted_b = vault_b.encrypt_secret(decrypted)

    # 5. Verify integrity with new key
    assert vault_b.decrypt_secret(encrypted_b) == secret_data
    assert encrypted_a != encrypted_b


def test_decrypt_short_payload(vault: VaultCrypto) -> None:
    """Verify behavior when ciphertext is too short (e.g. less than IV length)."""
    # 1 byte -> Base64 encoded is "AA==".
    # Decodes to 1 byte. IV requires 12 bytes.
    with pytest.raises(ValueError, match="Decryption failed"):
        vault.decrypt_secret("AA==")


def test_decrypt_empty_string_input(vault: VaultCrypto) -> None:
    """Verify behavior when input is an empty string."""
    with pytest.raises(ValueError, match="Decryption failed"):
        vault.decrypt_secret("")
