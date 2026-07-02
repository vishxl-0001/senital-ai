"""
Sentinel AI — Clerk session JWT verification (dashboard auth path).

Dashboard-facing routes derive ``tenant_id`` from the *verified* Clerk session
token (RS256, signed by Clerk), NOT from any client-supplied header/body field.
``tenant_id`` is the Clerk Organization id (the ``org_id`` claim).

This is deliberately separate from ``app.api.auth.get_tenant_from_api_key``,
which is the webhook/agent auth path (X-API-Key) and is correctly designed.

Key resolution is injectable (``static_keys``) so tests can exercise the real
``verify()`` path — signature check, issuer check, expiry, ``org_id`` extraction
— against a known key without hitting the network or needing real Clerk creds.
"""

import base64
import binascii
from functools import lru_cache
from typing import Optional

import httpx
import structlog
from fastapi import Depends, HTTPException, Request, status
from jose import jwt
from jose.exceptions import JWTError

from app.config import settings

log = structlog.get_logger()


# ── Issuer / JWKS derivation ──────────────────────────────────────────────

def derive_frontend_api(publishable_key: str) -> Optional[str]:
    """
    Clerk publishable keys (``pk_test_<b64>`` / ``pk_live_<b64>``) encode the
    Frontend API host as base64 of ``"<host>$"``. Decode it back out so we can
    build the issuer + JWKS URL without extra configuration.
    """
    parts = publishable_key.split("_", 2)
    if len(parts) < 3 or not parts[2]:
        return None
    b64 = parts[2]
    padded = b64 + "=" * (-len(b64) % 4)
    try:
        decoded = base64.b64decode(padded).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    host = decoded.rstrip("$")
    return host or None


def resolve_issuer_and_jwks() -> tuple[Optional[str], Optional[str]]:
    """Explicit env wins; otherwise derive both from the publishable key."""
    issuer = settings.CLERK_ISSUER
    jwks_url = settings.CLERK_JWKS_URL
    if (not issuer or not jwks_url) and settings.CLERK_PUBLISHABLE_KEY:
        host = derive_frontend_api(settings.CLERK_PUBLISHABLE_KEY)
        if host:
            issuer = issuer or f"https://{host}"
            jwks_url = jwks_url or f"https://{host}/.well-known/jwks.json"
    return issuer, jwks_url


# ── Verifier ──────────────────────────────────────────────────────────────

class ClerkJWTVerifier:
    """
    Verifies Clerk session JWTs (RS256) against Clerk's JWKS.

    ``static_keys`` (test mode): a ``{kid: jwk-dict-or-PEM}`` mapping used
    directly, never refetched. When ``None`` (prod), keys are fetched from
    ``jwks_url`` and cached, refetching once on a kid cache-miss (key rotation).
    """

    def __init__(
        self,
        issuer: Optional[str],
        jwks_url: Optional[str],
        static_keys: Optional[dict] = None,
        verify_issuer: bool = True,
    ):
        self.issuer = issuer
        self.jwks_url = jwks_url
        self.verify_issuer = verify_issuer
        self._static_keys = static_keys
        self._cache: Optional[dict] = None

    def _fetch_keys(self) -> dict:
        if not self.jwks_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth not configured: missing Clerk JWKS URL",
            )
        try:
            resp = httpx.get(self.jwks_url, timeout=5.0)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.error("Failed to fetch Clerk JWKS", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to reach identity provider",
            )
        return {jwk["kid"]: jwk for jwk in resp.json().get("keys", []) if "kid" in jwk}

    def _signing_key(self, kid: str):
        if self._static_keys is not None:
            key = self._static_keys.get(kid)
            if key is None:
                raise HTTPException(status_code=401, detail="Unknown signing key")
            return key

        if self._cache is None:
            self._cache = self._fetch_keys()
        key = self._cache.get(kid)
        if key is None:  # possible key rotation — refetch once
            self._cache = self._fetch_keys()
            key = self._cache.get(kid)
        if key is None:
            raise HTTPException(status_code=401, detail="Unknown signing key")
        return key

    def verify(self, token: str) -> dict:
        """Return verified claims, or raise HTTP 401 on any verification failure."""
        try:
            header = jwt.get_unverified_header(token)
        except JWTError:
            raise HTTPException(status_code=401, detail="Malformed token")

        kid = header.get("kid")
        if not kid:
            raise HTTPException(status_code=401, detail="Token missing key id")

        key = self._signing_key(kid)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.issuer if self.verify_issuer else None,
                options={"verify_aud": False, "verify_iss": self.verify_issuer},
            )
        except JWTError as exc:
            raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
        return claims


@lru_cache
def get_verifier() -> ClerkJWTVerifier:
    """Process-wide singleton verifier (caches JWKS across requests)."""
    issuer, jwks_url = resolve_issuer_and_jwks()
    return ClerkJWTVerifier(issuer=issuer, jwks_url=jwks_url)


# ── Token extraction + FastAPI dependency ─────────────────────────────────

def _extract_token(request: Request) -> str:
    """Prefer ``Authorization: Bearer``; fall back to Clerk's ``__session`` cookie."""
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    cookie = request.cookies.get("__session")
    if cookie:
        return cookie
    raise HTTPException(status_code=401, detail="Missing session token")


async def get_current_tenant(
    request: Request,
    verifier: ClerkJWTVerifier = Depends(get_verifier),
) -> str:
    """
    Dependency for dashboard-facing routes: verify the Clerk session JWT and
    return the tenant id (the verified ``org_id`` claim).

    A signed-in user with no active organization gets 403 — there is no tenant
    context to scope their request to.
    """
    token = _extract_token(request)
    claims = verifier.verify(token)
    org_id = claims.get("org_id")
    if not org_id:
        # Fallback to the user ID (sub) if no organization is active.
        # This allows single-user testing without requiring a Clerk Organization.
        org_id = claims.get("sub")
        if not org_id:
            raise HTTPException(
                status_code=403,
                detail="No active organization or user ID found in token.",
            )
    return org_id
