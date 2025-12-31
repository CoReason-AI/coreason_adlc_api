# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlmodel import select
from sqlalchemy.dialects.postgresql import insert

from coreason_adlc_api.db import async_session_factory
from coreason_adlc_api.db_models import Secret
from coreason_adlc_api.vault.crypto import VaultCrypto

# Initialize VaultCrypto once or per request?
# Per request is safer if key rotation logic existed, but global is fine for now.
vault_crypto = VaultCrypto()


async def store_secret(auc_id: str, service_name: str, raw_api_key: str, user_uuid: UUID) -> UUID:
    """
    Encrypts and stores an API key for a specific Project (AUC) and Service.
    """
    encrypted_value = vault_crypto.encrypt_secret(raw_api_key)

    try:
        async with async_session_factory() as session:
            stmt = insert(Secret).values(
                auc_id=auc_id,
                service_name=service_name,
                encrypted_value=encrypted_value,
                created_by=user_uuid,
                created_at=datetime.utcnow()
            ).on_conflict_do_update(
                index_elements=['auc_id', 'service_name'], # Requires unique constraint on these columns
                set_=dict(
                    encrypted_value=encrypted_value,
                    created_by=user_uuid,
                    created_at=datetime.utcnow()
                )
            ).returning(Secret.secret_id)

            result = await session.exec(stmt) # type: ignore[call-overload]
            # result is a Result object wrapping Rows (tuples)
            # We want the scalar value. .first() returns a Row (uuid,) or None.
            row = result.first()

            if not row:
                 # Should not happen with upsert returning
                 raise RuntimeError("Upsert failed to return ID")

            # Extract UUID from tuple
            secret_id = row[0]
            await session.commit()
            return secret_id

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
    async with async_session_factory() as session:
        statement = select(Secret).where(Secret.auc_id == auc_id, Secret.service_name == service_name)
        result = await session.exec(statement)
        secret = result.first()

    if not secret:
        raise ValueError(f"No secret found for {service_name} in project {auc_id}")

    return vault_crypto.decrypt_secret(secret.encrypted_value)
