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

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from coreason_adlc_api.vault.crypto import VaultCrypto

# Initialize VaultCrypto once or per request?
# Per request is safer if key rotation logic existed, but global is fine for now.
vault_crypto = VaultCrypto()


async def store_secret(session: AsyncSession, auc_id: str, service_name: str, raw_api_key: str, user_uuid: UUID) -> UUID:
    """
    Encrypts and stores an API key for a specific Project (AUC) and Service.
    """
    encrypted_value = vault_crypto.encrypt_secret(raw_api_key)

    stmt = text("""
        INSERT INTO vault.secrets (auc_id, service_name, encrypted_value, created_by)
        VALUES (:auc_id, :service_name, :encrypted_value, :user_uuid)
        ON CONFLICT (auc_id, service_name) DO UPDATE
        SET encrypted_value = EXCLUDED.encrypted_value,
            created_by = EXCLUDED.created_by,
            created_at = NOW()
        RETURNING secret_id;
    """)

    try:
        result = await session.execute(stmt, {
            "auc_id": auc_id,
            "service_name": service_name,
            "encrypted_value": encrypted_value,
            "user_uuid": user_uuid
        })
        await session.commit()
        row = result.fetchone()
        if not row:
            raise RuntimeError("Insert failed to return ID")
        return row[0]
    except Exception as e:
        logger.error(f"Failed to store secret for {auc_id}/{service_name}: {e}")
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to securely store secret"
        ) from e


async def retrieve_decrypted_secret(session: AsyncSession, auc_id: str, service_name: str) -> str:
    """
    Retrieves and decrypts an API key.
    This is an internal function for the Interceptor, NOT exposed via API.
    """
    stmt = text("""
        SELECT encrypted_value
        FROM vault.secrets
        WHERE auc_id = :auc_id AND service_name = :service_name
    """)

    result = await session.execute(stmt, {"auc_id": auc_id, "service_name": service_name})
    row = result.fetchone()

    if not row:
        raise ValueError(f"No secret found for {service_name} in project {auc_id}")

    encrypted_value = row[0]
    return vault_crypto.decrypt_secret(encrypted_value)
