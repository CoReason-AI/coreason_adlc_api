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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from coreason_adlc_api.workbench.schemas import AccessMode

__all__ = ["AccessMode", "acquire_draft_lock", "refresh_lock", "verify_lock_for_update"]

# Lock duration (30 seconds)
LOCK_DURATION_SECONDS = 30


async def acquire_draft_lock(session: AsyncSession, draft_id: UUID, user_uuid: UUID, roles: list[str]) -> AccessMode:
    """
    Tries to acquire a lock for editing the draft.
    Returns AccessMode.EDIT if acquired.
    Returns AccessMode.SAFE_VIEW if locked by another user but user is MANAGER.
    Raises 423 Locked otherwise.
    """
    # Select current lock status FOR UPDATE to block other concurrent lock attempts
    # We rely on the session being in a transaction context (which standard AsyncSession in FastAPI is)
    stmt = text("""
        SELECT locked_by_user, lock_expiry
        FROM workbench.agent_drafts
        WHERE draft_id = :draft_id
        FOR UPDATE
    """)

    result = await session.execute(stmt, {"draft_id": draft_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")

    locked_by = row[0] # locked_by_user
    expiry = row[1] # lock_expiry
    now = datetime.now(timezone.utc)

    # Check if locked
    if locked_by and locked_by != user_uuid and expiry and expiry > now:
        # Locked by someone else

        # Check for Manager Override
        if "MANAGER" in roles:
            logger.info(f"Manager {user_uuid} accessing locked draft {draft_id} in SAFE_VIEW")
            await session.commit() # Release lock on row
            return AccessMode.SAFE_VIEW

        logger.warning(f"User {user_uuid} denied edit access to draft {draft_id} locked by {locked_by}")
        await session.rollback() # Release lock on row
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                f"Draft is currently being edited by another user (Lock expires in {(expiry - now).seconds}s)"
            ),
        )

    # Not locked, or locked by self, or lock expired -> Acquire Lock
    new_expiry = now + timedelta(seconds=LOCK_DURATION_SECONDS)

    update_stmt = text("""
        UPDATE workbench.agent_drafts
        SET locked_by_user = :user_uuid, lock_expiry = :new_expiry
        WHERE draft_id = :draft_id
    """)

    await session.execute(update_stmt, {
        "user_uuid": user_uuid,
        "new_expiry": new_expiry,
        "draft_id": draft_id
    })

    await session.commit()

    return AccessMode.EDIT


async def refresh_lock(session: AsyncSession, draft_id: UUID, user_uuid: UUID) -> None:
    """
    Extends the lock expiry if held by the user.
    """
    now = datetime.now(timezone.utc)
    new_expiry = now + timedelta(seconds=LOCK_DURATION_SECONDS)

    stmt = text("""
        UPDATE workbench.agent_drafts
        SET lock_expiry = :new_expiry
        WHERE draft_id = :draft_id AND locked_by_user = :user_uuid
    """)

    result = await session.execute(stmt, {
        "new_expiry": new_expiry,
        "draft_id": draft_id,
        "user_uuid": user_uuid
    })

    await session.commit()

    # Check if any row was updated
    if result.rowcount == 0:
        # Either draft doesn't exist, or user doesn't hold the lock
        # Check existence
        check_stmt = text("SELECT locked_by_user FROM workbench.agent_drafts WHERE draft_id = :draft_id")
        check_result = await session.execute(check_stmt, {"draft_id": draft_id})
        row = check_result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Draft not found")

        locked_by = row[0]
        if locked_by != user_uuid:
            raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="You do not hold the lock for this draft")


async def verify_lock_for_update(session: AsyncSession, draft_id: UUID, user_uuid: UUID) -> None:
    """
    Ensures the user holds a valid lock before performing an update.
    """
    stmt = text("SELECT locked_by_user, lock_expiry FROM workbench.agent_drafts WHERE draft_id = :draft_id")
    result = await session.execute(stmt, {"draft_id": draft_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")

    locked_by = row[0]
    expiry = row[1]
    now = datetime.now(timezone.utc)

    if not locked_by or locked_by != user_uuid:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="You must acquire a lock before editing")

    if expiry and expiry <= now:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Lock expired. Please refresh page.")
