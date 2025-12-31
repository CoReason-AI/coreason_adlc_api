# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlmodel import select, col

from coreason_adlc_api.db import async_session_factory
from coreason_adlc_api.db_models import AgentDraft
from coreason_adlc_api.workbench.schemas import AccessMode

__all__ = ["AccessMode", "acquire_draft_lock", "refresh_lock", "verify_lock_for_update"]

# Lock duration (30 seconds)
LOCK_DURATION_SECONDS = 30


async def acquire_draft_lock(draft_id: UUID, user_uuid: UUID, roles: list[str]) -> AccessMode:
    """
    Tries to acquire a lock for editing the draft.
    Returns AccessMode.EDIT if acquired.
    Returns AccessMode.SAFE_VIEW if locked by another user but user is MANAGER.
    Raises 423 Locked otherwise.
    """
    try:
        async with async_session_factory() as session:
            # We use with_for_update() to lock the row
            statement = select(AgentDraft).where(AgentDraft.draft_id == draft_id).with_for_update()
            result = await session.exec(statement)
            draft = result.first()

            if not draft:
                raise HTTPException(status_code=404, detail="Draft not found")

            locked_by = draft.locked_by_user
            expiry = draft.lock_expiry
            now = datetime.now(timezone.utc)

            # Check if locked
            if locked_by and locked_by != user_uuid and expiry and expiry > now:
                # Locked by someone else

                # Check for Manager Override
                if "MANAGER" in roles:
                    logger.info(f"Manager {user_uuid} accessing locked draft {draft_id} in SAFE_VIEW")
                    return AccessMode.SAFE_VIEW

                logger.warning(f"User {user_uuid} denied edit access to draft {draft_id} locked by {locked_by}")
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail=(
                        f"Draft is currently being edited by another user (Lock expires in {(expiry - now).seconds}s)"
                    ),
                )

            # Not locked, or locked by self, or lock expired -> Acquire Lock
            new_expiry = now + timedelta(seconds=LOCK_DURATION_SECONDS)
            draft.locked_by_user = user_uuid
            draft.lock_expiry = new_expiry
            session.add(draft)
            await session.commit()

            return AccessMode.EDIT

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error acquiring lock: {e}")
        raise HTTPException(status_code=500, detail="Failed to acquire lock") from e


async def refresh_lock(draft_id: UUID, user_uuid: UUID) -> None:
    """
    Extends the lock expiry if held by the user.
    """
    async with async_session_factory() as session:
        statement = select(AgentDraft).where(
            AgentDraft.draft_id == draft_id,
            AgentDraft.locked_by_user == user_uuid
        )
        result = await session.exec(statement)
        draft = result.first()

        if draft:
            now = datetime.now(timezone.utc)
            new_expiry = now + timedelta(seconds=LOCK_DURATION_SECONDS)
            draft.lock_expiry = new_expiry
            session.add(draft)
            await session.commit()
            return

        # If not found via the above query, check if draft exists at all
        exists_stmt = select(AgentDraft).where(AgentDraft.draft_id == draft_id)
        exists_res = await session.exec(exists_stmt)
        existing = exists_res.first()

        if not existing:
            raise HTTPException(status_code=404, detail="Draft not found")

        if existing.locked_by_user != user_uuid:
             raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="You do not hold the lock for this draft")


async def verify_lock_for_update(draft_id: UUID, user_uuid: UUID) -> None:
    """
    Ensures the user holds a valid lock before performing an update.
    """
    async with async_session_factory() as session:
        statement = select(AgentDraft).where(AgentDraft.draft_id == draft_id)
        result = await session.exec(statement)
        draft = result.first()

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    locked_by = draft.locked_by_user
    expiry = draft.lock_expiry
    now = datetime.now(timezone.utc)

    if not locked_by or locked_by != user_uuid:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="You must acquire a lock before editing")

    if expiry and expiry <= now:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Lock expired. Please refresh page.")
