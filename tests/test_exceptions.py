# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import unittest
from unittest.mock import MagicMock

from coreason_adlc_api.exceptions import (
    AuthenticationError,
    BudgetExceededError,
    ClientError,
    ComplianceViolationError,
    CoreasonError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
)


class TestExceptions(unittest.TestCase):
    def test_inheritance_hierarchy(self) -> None:
        """Verify the inheritance structure of exceptions."""
        self.assertTrue(issubclass(ClientError, CoreasonError))
        self.assertTrue(issubclass(ServerError, CoreasonError))

        self.assertTrue(issubclass(AuthenticationError, ClientError))
        self.assertTrue(issubclass(BudgetExceededError, ClientError))
        self.assertTrue(issubclass(ComplianceViolationError, ClientError))
        self.assertTrue(issubclass(RateLimitError, ClientError))

        self.assertTrue(issubclass(ServiceUnavailableError, ServerError))

    def test_exception_attributes_with_response(self) -> None:
        """Verify exception attributes when initialized with a response."""
        mock_response = MagicMock()
        mock_response.status_code = 402

        err = BudgetExceededError("Budget exceeded", mock_response)

        self.assertEqual(err.message, "Budget exceeded")
        self.assertEqual(err.response, mock_response)
        self.assertEqual(err.status_code, 402)
        self.assertEqual(str(err), "Budget exceeded")

    def test_exception_attributes_without_response(self) -> None:
        """Verify exception attributes when initialized without a response."""
        err = CoreasonError("Generic error")

        self.assertEqual(err.message, "Generic error")
        self.assertIsNone(err.response)
        self.assertIsNone(err.status_code)
