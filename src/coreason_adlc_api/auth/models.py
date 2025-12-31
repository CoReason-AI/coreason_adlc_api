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
from datetime import datetime
from typing import List

from sqlalchemy import ARRAY, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from coreason_adlc_api.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "identity"}

    user_uuid: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String)
    full_name: Mapped[str] = mapped_column(String)
    last_login: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class GroupMapping(Base):
    __tablename__ = "group_mappings"
    __table_args__ = {"schema": "identity"}

    sso_group_oid: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    allowed_auc_ids: Mapped[List[str]] = mapped_column(ARRAY(String))
