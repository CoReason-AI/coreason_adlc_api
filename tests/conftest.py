from typing import Any, Callable, Generator
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from coreason_adlc_api.config import settings
from coreason_adlc_api.middleware.proxy import _breakers


@pytest.fixture(autouse=True)
def reset_circuit_breaker() -> Generator[None, None, None]:
    """Reset circuit breaker state before and after each test."""
    _breakers.clear()
    yield
    _breakers.clear()


@pytest.fixture(scope="session")
def rsa_key_pair() -> tuple[RSAPrivateKey, RSAPublicKey]:
    """Generates a fresh RSA key pair for testing (session scoped)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def mock_oidc_factory(
    rsa_key_pair: tuple[RSAPrivateKey, RSAPublicKey],
) -> Generator[Callable[[dict[str, Any] | None], str], None, None]:
    """
    Patches the auth system to accept tokens signed by the local RSA key.
    Returns a factory function `create_token(payload_overrides)` -> jwt_string.
    """
    private_key, public_key = rsa_key_pair

    mock_jwk_client = MagicMock()
    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key
    mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key

    # Mock config to avoid network calls and ensure issuer match
    mock_config = {
        "issuer": f"{settings.OIDC_DOMAIN.rstrip('/')}/",
    }

    # Patch both global variables in identity
    with (
        patch("coreason_adlc_api.auth.identity._OIDC_CONFIG_CACHE", mock_config),
        patch("coreason_adlc_api.auth.identity._JWKS_CLIENT", mock_jwk_client),
    ):

        def _create_token(payload_overrides: dict[str, Any] | None = None) -> str:
            # Default payload matching UserIdentity schema
            payload = {
                "iss": f"{settings.OIDC_DOMAIN.rstrip('/')}/",
                "aud": settings.OIDC_AUDIENCE,
                "sub": "00000000-0000-0000-0000-000000000001",
                "email": "test@coreason.ai",
                "name": "Test User",
                "groups": [],
                # Long expiry by default
                "exp": 9999999999,
            }
            if payload_overrides:
                payload.update(payload_overrides)

            # Cast for mypy strictness on jwt.encode arguments
            return str(jwt.encode(payload, private_key, algorithm="RS256"))

        yield _create_token
