# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import logging
import uuid
from datetime import datetime, timedelta

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from coreason_adlc_api.auth.identity import UserIdentity
from coreason_adlc_api.db_models import DraftModel
from coreason_adlc_api.exceptions import DraftLockedError

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_MINUTES = 30


class DraftLockManager:
    """
    Manages pessimistic locking for drafts (Safe View / Edit Mode).
    """

    def __init__(self, session: AsyncSession, user: UserIdentity):
        self.session = session
        self.user = user

    async def acquire_lock(self, draft_id: str, force: bool = False) -> bool:
        """
        Acquires a lock on the draft.
        If already locked by another user:
          - If force=True and user is MANAGER, override.
          - Else raise DraftLockedError.
        """
        # We need to perform a SELECT ... FOR UPDATE to ensure atomicity
        # SQLModel doesn't directly expose with_for_update easily on select() object in current versions,
        # but we can use .execution_options() on the session or use raw SQL.
        # Or, just select and check, relying on optimistic logic if we don't need rigorous DB-level locking yet.
        # For true pessimistic locking, we need `select(DraftModel).where(...).with_for_update()`.

        # NOTE: SQLAlchemy 1.4+ (which SQLModel uses) supports with_for_update() on the statement.
        stmt = select(DraftModel).where(DraftModel.id == uuid.UUID(draft_id)).with_for_update()
        result = await self.session.exec(stmt)
        draft = result.one_or_none()

        if not draft:
            return False  # Draft not found

        now = datetime.utcnow()

        # Check existing lock
        if draft.locked_by and draft.locked_by != self.user.oid:
            # Check timeout
            if draft.locked_at and (now - draft.locked_at) < timedelta(minutes=LOCK_TIMEOUT_MINUTES):
                if force:
                    # Check if user is manager (role check logic here or passed in)
                    # For now, assuming caller handles role check or we check here
                    # simple overwrite
                    logger.info(f"User {self.user.oid} forcing lock on draft {draft_id}")
                else:
                    raise DraftLockedError(f"Draft is locked by user {draft.locked_by}")
            else:
                # Lock expired, can take over
                logger.info(f"Lock expired on draft {draft_id}, taking over.")

        # Set lock
        draft.locked_by = self.user.oid
        draft.locked_at = now
        self.session.add(draft)
        await self.session.commit()
        return True

    async def release_lock(self, draft_id: str) -> bool:
        """
        Releases the lock if held by the current user.
        """
        stmt = select(DraftModel).where(DraftModel.id == uuid.UUID(draft_id)).with_for_update()
        result = await self.session.exec(stmt)
        draft = result.one_or_none()

        if not draft:
            return False

        if draft.locked_by == self.user.oid:
            draft.locked_by = None
            draft.locked_at = None
            self.session.add(draft)
            await self.session.commit()
            return True

        return False

    async def check_lock(self, draft_id: str) -> None:
        """
        Verifies that the current user holds the lock. Raises DraftLockedError if not.
        """
        stmt = select(DraftModel).where(DraftModel.id == uuid.UUID(draft_id))
        result = await self.session.exec(stmt)
        draft = result.one_or_none()

        if not draft:
            # Should be 404, but strict lock check might just fail
            raise DraftLockedError("Draft not found")

        if draft.locked_by != self.user.oid:
            # Check if expired?
            # For strict checking during save, we assume we must actively hold it.
            raise DraftLockedError(f"Draft is locked by {draft.locked_by}")
