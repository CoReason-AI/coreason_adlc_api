
import json
from unittest.mock import MagicMock
from coreason_adlc_api.client import CoreasonClient

def test_client_promote_draft():
    # Setup
    client = CoreasonClient()
    client.client = MagicMock()

    draft_id = "test-draft"
    artifact = {"id": "test-draft", "content": {}}
    mock_resp_assemble = MagicMock()
    mock_resp_assemble.is_success = True
    mock_resp_assemble.status_code = 200
    mock_resp_assemble.json.return_value = artifact

    mock_resp_publish = MagicMock()
    mock_resp_publish.is_success = True
    mock_resp_publish.status_code = 200
    mock_resp_publish.json.return_value = {"url": "http://gitlab/v1"}

    # Mock GET and POST
    # We mock request because convenience methods call request
    def side_effect(method, url, **kwargs):
        if method == "GET" and "assemble" in url:
            return mock_resp_assemble
        if method == "POST" and "publish" in url:
            # Verify signature injection
            assert "signature" in kwargs["json"]
            assert kwargs["json"]["signature"] == "valid_sig"
            return mock_resp_publish
        return MagicMock()

    client.client.request.side_effect = side_effect

    # Execute
    signer = lambda x: "valid_sig"
    url = client.promote_draft(draft_id, signer)

    # Assert
    assert url == "http://gitlab/v1"
