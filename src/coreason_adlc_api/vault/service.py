# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from uuid import UUID

from coreason_adlc_api.db import get_pool
from coreason_adlc_api.vault.crypto import VaultCrypto
from fastapi import HTTPException, status
from loguru import logger

# Initialize VaultCrypto once or per request?
# Per request is safer if key rotation logic existed, but global is fine for now.
vault_crypto = VaultCrypto()


async def store_secret(auc_id: str, service_name: str, raw_api_key: str, user_uuid: UUID) -> UUID:
    """
    Encrypts and stores an API key for a specific Project (AUC) and Service.
    """
    encrypted_value = vault_crypto.encrypt_secret(raw_api_key)

    pool = get_pool()
    query = """
        INSERT INTO vault.secrets (auc_id, service_name, encrypted_value, created_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (auc_id, service_name) DO UPDATE
        SET encrypted_value = EXCLUDED.encrypted_value,
            created_by = EXCLUDED.created_by,
            created_at = NOW()
        RETURNING secret_id;
    """

    try:
        row = await pool.fetchrow(query, auc_id, service_name, encrypted_value, user_uuid)
        if not row:
            raise RuntimeError("Insert failed to return ID")
        return row["secret_id"]  # type: ignore
    except Exception as e:
        logger.error(f"Failed to store secret for {auc_id}/{service_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to securely store secret"
        ) from e


async def retrieve_decrypted_secret(auc_id: str, service_name: str) -> str:
    """
    Retrieves and decrypts an API key.
    This is an internal function for the Interceptor, NOT exposed via API.
    """
    pool = get_pool()
    query = """
        SELECT encrypted_value
        FROM vault.secrets
        WHERE auc_id = $1 AND service_name = $2
    """

    row = await pool.fetchrow(query, auc_id, service_name)
    if not row:
        raise ValueError(f"No secret found for {service_name} in project {auc_id}")

    encrypted_value = row["encrypted_value"]
    return vault_crypto.decrypt_secret(encrypted_value)
