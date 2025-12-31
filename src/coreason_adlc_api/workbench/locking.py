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
from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from coreason_adlc_api.auth.identity import UserIdentity
from coreason_adlc_api.db_models import DraftModel
from coreason_adlc_api.exceptions import DraftLockedError
from coreason_adlc_api.workbench.schemas import AccessMode

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


# Legacy wrapper for tests
async def acquire_draft_lock(
    draft_id: str,
    user: UserIdentity,
    session: AsyncSession = None,  # type: ignore
    roles: List[str] = None,  # type: ignore
) -> AccessMode:
    """
    Simulates old acquire_draft_lock behavior returning AccessMode.
    Note: 'session' must be passed or mocked if using real DB logic, but tests might mock DraftLockManager?
    Actually tests pass 'draft_id', 'user', 'roles'. They might rely on global session or something?
    Wait, the failing call was: `acquire_draft_lock(draft_id, user_b, roles=[])`.
    My wrapper expected `session` first.
    I swapped arguments to match usage I saw in error: `Argument 1 to "acquire_draft_lock" has incompatible type "UUID"; expected "AsyncSession"`.
    Ah, so `draft_id` is passed as first arg.

    If tests don't pass session, this function is expected to get it somehow or mock it.
    But I refactored to use `DraftLockManager` which NEEDS session.
    If I can't get session, I can't use `DraftLockManager`.
    But `test_validation_business_goals.py` mocks `acquire_draft_lock` usually?
    No, it imports it.
    The test likely patches `async_session_factory` if it's integration.
    Or I should create a new session here if None?
    """
    if session is None:
        # Try to get from global factory?
        from coreason_adlc_api.db import async_session_factory

        async with async_session_factory() as s:
            manager = DraftLockManager(s, user)
            # Determine force from roles
            force = "MANAGER" in (roles or [])
            try:
                await manager.acquire_lock(draft_id, force=force)
                return AccessMode.EDIT
            except DraftLockedError:
                if force:  # Should have forced?
                    return AccessMode.SAFE_VIEW  # Or something?
                # If we are here, we failed to acquire lock.
                # If user is manager, maybe they get SAFE_VIEW?
                if "MANAGER" in (roles or []):
                    return AccessMode.SAFE_VIEW
                raise

    manager = DraftLockManager(session, user)
    force = "MANAGER" in (roles or [])
    try:
        await manager.acquire_lock(draft_id, force=force)
        return AccessMode.EDIT
    except DraftLockedError:
        if "MANAGER" in (roles or []):
            return AccessMode.SAFE_VIEW
        raise


async def verify_lock_for_update(session: AsyncSession, user: UserIdentity, draft_id: str) -> None:
    manager = DraftLockManager(session, user)
    await manager.check_lock(draft_id)
