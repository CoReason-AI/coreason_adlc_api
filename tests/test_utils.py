# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import httpx

from coreason_adlc_api.utils import get_http_client


def test_get_http_client_real() -> None:
    """Verify that the real get_http_client function returns an AsyncClient."""
    client = get_http_client()
    assert isinstance(client, httpx.AsyncClient)
    # Cleanup (not strictly async here but good practice if we entered context)
    # Since we just got the instance, garbage collection will close it eventually,
    # or we can manually close if it was opened. AsyncClient constructor doesn't open net resources immediately.
