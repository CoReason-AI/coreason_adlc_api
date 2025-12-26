# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import hashlib
import os

import yaml
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/system", tags=["System & Compliance"])


class ComplianceResponse(BaseModel):
    checksum_sha256: str
    allowlists: dict


@router.get("/compliance", response_model=ComplianceResponse)
async def get_compliance_status() -> ComplianceResponse:
    """
    Returns the SHA256 hash of the server's authoritative compliance.yaml.
    This allows the client to verify "Safe Mode" integrity before importing libraries.
    """
    # Locate compliance.yaml relative to this file or package root
    # We assume it is in src/coreason_adlc_api/compliance.yaml
    base_path = os.path.dirname(os.path.dirname(__file__))
    compliance_path = os.path.join(base_path, "compliance.yaml")

    if not os.path.exists(compliance_path):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Compliance definition file missing on server.",
        )

    try:
        with open(compliance_path, "rb") as f:
            content = f.read()
            checksum = hashlib.sha256(content).hexdigest()

        with open(compliance_path, "r") as f:
            data = yaml.safe_load(f)

        return ComplianceResponse(checksum_sha256=checksum, allowlists=data.get("allowlists", {}))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process compliance file: {str(e)}",
        ) from e
