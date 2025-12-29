# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import base64
import os

from coreason_adlc_api.config import settings
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultCrypto:
    """
    Handles AES-256 GCM encryption and decryption for sensitive secrets.
    The encryption key is derived from the ENCRYPTION_KEY environment variable.
    """

    def __init__(self, key_hex: str | None = None) -> None:
        """
        Initialize the VaultCrypto instance.
        If key_hex is not provided, it falls back to settings.ENCRYPTION_KEY.
        The key must be a 32-byte hex string (64 hex characters).
        """
        self._key = self._load_key(key_hex)
        self._aesgcm = AESGCM(self._key)

    def _load_key(self, key_hex: str | None) -> bytes:
        """
        Parses and validates the encryption key.
        """
        raw_key = key_hex or settings.ENCRYPTION_KEY
        if not raw_key:
            raise ValueError("ENCRYPTION_KEY is not set.")

        try:
            key_bytes = bytes.fromhex(raw_key)
        except ValueError:
            raise ValueError("ENCRYPTION_KEY must be a valid hex string.") from None

        if len(key_bytes) != 32:
            raise ValueError(f"ENCRYPTION_KEY must be 32 bytes (64 hex chars). Got {len(key_bytes)} bytes.")

        return key_bytes

    def encrypt_secret(self, raw_value: str) -> str:
        """
        Encrypts a raw string using AES-GCM.
        Returns: Base64 encoded string containing (IV + Ciphertext).
        """
        nonce = os.urandom(12)  # 96-bit nonce recommended for GCM
        ciphertext = self._aesgcm.encrypt(nonce, raw_value.encode("utf-8"), None)
        return base64.b64encode(nonce + ciphertext).decode("utf-8")

    def decrypt_secret(self, encrypted_value: str) -> str:
        """
        Decrypts a Base64 encoded string (IV + Ciphertext).
        Returns: The original raw string.
        """
        try:
            decoded = base64.b64decode(encrypted_value)
            nonce = decoded[:12]
            ciphertext = decoded[12:]
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except Exception:
            raise ValueError("Decryption failed. Invalid key or corrupted data.") from None
