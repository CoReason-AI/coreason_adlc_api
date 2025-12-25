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

from coreason_adlc_api.db import get_pool
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
    pool = get_pool()

    # We use a transaction to ensure atomicity
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Select current lock status FOR UPDATE to block other concurrent lock attempts
            row = await conn.fetchrow(
                "SELECT locked_by_user, lock_expiry FROM workbench.agent_drafts WHERE draft_id = $1 FOR UPDATE",
                draft_id,
            )

            if not row:
                raise HTTPException(status_code=404, detail="Draft not found")

            locked_by = row["locked_by_user"]
            expiry = row["lock_expiry"]
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
            await conn.execute(
                "UPDATE workbench.agent_drafts SET locked_by_user = $1, lock_expiry = $2 WHERE draft_id = $3",
                user_uuid,
                new_expiry,
                draft_id,
            )

            return AccessMode.EDIT


async def refresh_lock(draft_id: UUID, user_uuid: UUID) -> None:
    """
    Extends the lock expiry if held by the user.
    """
    pool = get_pool()
    now = datetime.now(timezone.utc)
    new_expiry = now + timedelta(seconds=LOCK_DURATION_SECONDS)

    result = await pool.execute(
        """
        UPDATE workbench.agent_drafts
        SET lock_expiry = $1
        WHERE draft_id = $2 AND locked_by_user = $3
        """,
        new_expiry,
        draft_id,
        user_uuid,
    )

    # Check if any row was updated
    if result == "UPDATE 0":
        # Either draft doesn't exist, or user doesn't hold the lock
        # Check existence
        row = await pool.fetchrow("SELECT locked_by_user FROM workbench.agent_drafts WHERE draft_id = $1", draft_id)
        if not row:
            raise HTTPException(status_code=404, detail="Draft not found")

        locked_by = row["locked_by_user"]
        if locked_by != user_uuid:
            raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="You do not hold the lock for this draft")


async def verify_lock_for_update(draft_id: UUID, user_uuid: UUID) -> None:
    """
    Ensures the user holds a valid lock before performing an update.
    """
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT locked_by_user, lock_expiry FROM workbench.agent_drafts WHERE draft_id = $1", draft_id
    )

    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")

    locked_by = row["locked_by_user"]
    expiry = row["lock_expiry"]
    now = datetime.now(timezone.utc)

    if not locked_by or locked_by != user_uuid:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="You must acquire a lock before editing")

    if expiry and expiry <= now:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Lock expired. Please refresh page.")
