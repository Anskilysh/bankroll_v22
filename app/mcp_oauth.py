"""JWT/OAuth resource-server support for the existing Render MCP gateway.

Uses an external OAuth 2.1-compatible authorization server (e.g. Auth0).
ChatGPT authenticates the user there; this server verifies each JWT locally.
Nothing in this module issues access tokens or exposes gateway API keys.
"""
from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import jwt
from jwt import InvalidTokenError, PyJWKClient
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl


def _https_url(value: str, name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise RuntimeError(f"{name} must be a public HTTPS URL")
    return value


def oauth_configuration() -> dict[str, str]:
    """Fail closed if OAuth mode is selected without all required settings."""
    names = {
        "issuer": "MCP_OAUTH_ISSUER",
        "audience": "MCP_OAUTH_AUDIENCE",
        "jwks_url": "MCP_OAUTH_JWKS_URL",
        "resource": "MCP_PUBLIC_URL",
        "scope": "MCP_OAUTH_SCOPE",
    }
    cfg = {key: os.getenv(env, "").strip() for key, env in names.items()}
    missing = [names[key] for key, value in cfg.items() if not value]
    if missing:
        raise RuntimeError("Missing OAuth settings: " + ", ".join(missing))
    _https_url(cfg["issuer"], "MCP_OAUTH_ISSUER")
    _https_url(cfg["jwks_url"], "MCP_OAUTH_JWKS_URL")
    _https_url(cfg["resource"], "MCP_PUBLIC_URL")
    if not urlparse(cfg["resource"]).path.startswith("/mcp"):
        raise RuntimeError("MCP_PUBLIC_URL must refer to the /mcp resource")
    return cfg


class OIDCJWTVerifier(TokenVerifier):
    """Validate signature, JWT issuer, audience, expiration and read scope."""

    def __init__(self, cfg: dict[str, str]):
        self.cfg = cfg
        self.jwks = PyJWKClient(
            cfg["jwks_url"], cache_jwk_set=True, lifespan=600, timeout=8
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            # PyJWKClient performs HTTPS I/O when its key cache expires.
            signing_key = await asyncio.to_thread(self.jwks.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self.cfg["issuer"],
                audience=self.cfg["audience"],
                options={"require": ["iss", "aud", "exp", "sub"]},
                leeway=30,
            )
            granted_scopes = set(str(claims.get("scope", "")).split())
            permissions = claims.get("permissions", [])
            if isinstance(permissions, list):
                granted_scopes.update(str(permission) for permission in permissions)
            if self.cfg["scope"] not in granted_scopes:
                return None
            return AccessToken(
                token=token,
                client_id=str(claims.get("azp") or claims.get("client_id") or claims["sub"]),
                subject=str(claims["sub"]),
                scopes=sorted(granted_scopes),
                expires_at=int(claims["exp"]),
                resource=self.cfg["resource"],
            )
        except (InvalidTokenError, ValueError, KeyError, OSError, jwt.PyJWKClientError):
            return None


def create_oauth_options():
    """Return kwargs supported by MCPServer(auth=..., token_verifier=...)."""
    cfg = oauth_configuration()
    return cfg, {
        "token_verifier": OIDCJWTVerifier(cfg),
        "auth": AuthSettings(
            issuer_url=AnyHttpUrl(cfg["issuer"]),
            resource_server_url=AnyHttpUrl(cfg["resource"]),
            required_scopes=[cfg["scope"]],
            validate_token_resource=True,
        ),
    }


def protected_resource_metadata(cfg: dict[str, str]) -> dict:
    """RFC 9728 metadata, discoverable before users authenticate."""
    return {
        "resource": cfg["resource"],
        "authorization_servers": [cfg["issuer"]],
        "scopes_supported": [cfg["scope"]],
        "bearer_methods_supported": ["header"],
    }
