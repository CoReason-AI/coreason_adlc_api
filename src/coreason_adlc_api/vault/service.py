# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import uuid
import logging
from typing import Optional, List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from coreason_adlc_api.auth.identity import UserIdentity, map_groups_to_projects
from coreason_adlc_api.db_models import SecretModel
from coreason_adlc_api.exceptions import AccessDeniedError, ResourceNotFoundError
from coreason_adlc_api.vault.crypto import VaultCrypto

logger = logging.getLogger(__name__)

class VaultService:
    def __init__(self, session: AsyncSession, user: UserIdentity):
        self.session = session
        self.user = user

    async def _check_access(self, project_id: str) -> None:
        """
        Verifies that the user has access to the given project.
        """
        allowed_projects = await map_groups_to_projects(self.user, self.session)
        if project_id not in allowed_projects:
            raise AccessDeniedError(f"User does not have access to project {project_id}")

    async def store_secret(self, project_id: str, key_name: str, secret_value: str) -> uuid.UUID:
        """
        Encrypts and stores a secret. Uses upsert logic.
        """
        await self._check_access(project_id)

        encrypted = VaultCrypto.encrypt(secret_value)

        # Atomic upsert using PostgreSQL ON CONFLICT
        stmt = insert(SecretModel).values(
            project_id=project_id,
            key_name=key_name,
            encrypted_value=encrypted
        ).on_conflict_do_update(
            index_elements=["project_id", "key_name"],
            set_={"encrypted_value": encrypted, "updated_at": insert(SecretModel).excluded.updated_at}
        ).returning(SecretModel.id)

        result = await self.session.exec(stmt) # type: ignore
        secret_id = result.one()
        await self.session.commit()
        return secret_id

    async def get_secret(self, project_id: str, key_name: str) -> Optional[str]:
        """
        Retrieves and decrypts a secret.
        """
        await self._check_access(project_id)

        query = select(SecretModel).where(
            SecretModel.project_id == project_id,
            SecretModel.key_name == key_name
        )
        result = await self.session.exec(query)
        secret = result.first()

        if not secret:
            return None

        return VaultCrypto.decrypt(secret.encrypted_value)

    async def list_secrets(self, project_id: str) -> List[str]:
        """
        Lists secret keys for a project.
        """
        await self._check_access(project_id)

        query = select(SecretModel.key_name).where(SecretModel.project_id == project_id)
        result = await self.session.exec(query)
        return list(result.all())

    async def delete_secret(self, project_id: str, key_name: str) -> bool:
        """
        Deletes a secret.
        """
        await self._check_access(project_id)

        query = select(SecretModel).where(
            SecretModel.project_id == project_id,
            SecretModel.key_name == key_name
        )
        result = await self.session.exec(query)
        secret = result.first()

        if not secret:
            raise ResourceNotFoundError(f"Secret {key_name} not found in project {project_id}")

        await self.session.delete(secret)
        await self.session.commit()
        return True
