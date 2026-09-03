import time

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

from app.config import settings
from app.services.supabase_client import get_supabase

bearer_scheme = HTTPBearer()

# Supabase's public signing keys live here. Cached in-memory and refreshed
# only when we hit a `kid` we don't recognise (e.g. after key rotation),
# so normal requests don't do a network round trip on every call.
JWKS_URL = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
_jwks_cache: dict = {"keys": [], "fetched_at": 0.0}
_JWKS_CACHE_TTL_SECONDS = 3600


class CurrentUser:
    def __init__(self, id: str, role: str):
        self.id = id
        self.role = role


def _fetch_jwks() -> dict:
    resp = httpx.get(JWKS_URL, timeout=5.0)
    resp.raise_for_status()
    return resp.json()


def _get_signing_key(kid: str) -> dict:
    now = time.time()
    stale = (now - _jwks_cache["fetched_at"]) > _JWKS_CACHE_TTL_SECONDS

    if not _jwks_cache["keys"] or stale:
        _jwks_cache.update(_fetch_jwks())
        _jwks_cache["fetched_at"] = now

    for key in _jwks_cache["keys"]:
        if key.get("kid") == kid:
            return key

    # kid not found even after a fresh fetch attempt above - try one
    # forced refresh in case keys just rotated, then give up.
    _jwks_cache.update(_fetch_jwks())
    _jwks_cache["fetched_at"] = time.time()
    for key in _jwks_cache["keys"]:
        if key.get("kid") == kid:
            return key

    raise JWTError(f"No matching signing key found for kid={kid}")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    """
    Validates the Supabase-issued JWT that Flutter sends after admin/monitor
    login (via supabase_flutter's session.access_token), then looks up the
    user's role from the profiles table.

    Supabase signs these tokens asymmetrically (ES256), so verification uses
    the project's public JWKS rather than a shared HS256 secret.

    Driver-facing endpoints do NOT use this dependency - driver search is
    public/anonymous by design (see routers/driver.py).
    """
    token = credentials.credentials
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise JWTError("Token header missing kid")

        signing_key = _get_signing_key(kid)

        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[signing_key.get("alg", "ES256")],
            audience="authenticated",
        )
    except (JWTError, httpx.HTTPError) as exc:
        print("TOKEN VERIFY FAILED:", repr(exc))  # TEMP DEBUG
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")

    supabase = get_supabase()
    result = (
        supabase.table("profiles")
        .select("id, role")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=403, detail="No profile found for user")

    return CurrentUser(id=result.data["id"], role=result.data["role"])


def require_role(*allowed_roles: str):
    """Usage: Depends(require_role('admin')) or Depends(require_role('admin', 'monitor'))"""

    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {' or '.join(allowed_roles)}",
            )
        return user

    return checker