"""
Authentication layer for ScanToText.

JWT         — short-lived access tokens (24 h); stored in localStorage.
Google OAuth — users sign in with Google; we get their verified email.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
import urllib.parse
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from db import User, get_db, get_or_create_user

logger = logging.getLogger(__name__)

# ── JWT Config ────────────────────────────────────────────────────────────────
JWT_SECRET   = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGO     = "HS256"
JWT_TTL_SECS = int(os.getenv("JWT_TTL_SECS", str(24 * 3600)))  # 24 h default

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


# ── Admin config ──────────────────────────────────────────────────────────────
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_JWT_TTL  = 8 * 3600  # 8 hours


# ── Token helpers ─────────────────────────────────────────────────────────────

def create_access_token(email: str) -> str:
    payload = {
        "sub": email.lower().strip(),
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_TTL_SECS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def create_admin_token() -> str:
    """Issue a short-lived JWT for the admin dashboard (role=admin)."""
    payload = {
        "sub":  "admin",
        "role": "admin",
        "iat":  int(time.time()),
        "exp":  int(time.time()) + ADMIN_JWT_TTL,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def require_admin(
    authorization: Optional[str] = Header(default=None),
) -> None:
    """FastAPI dependency: verifies Bearer token has role=admin, raises 401 otherwise."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        if payload.get("role") != "admin":
            raise ValueError("not admin role")
    except (JWTError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired admin token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def decode_access_token(token: str) -> str:
    """Return email from a valid JWT; raises HTTPException on any failure."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        email: str = payload.get("sub", "")
        if not email:
            raise ValueError("empty sub")
        return email
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI dependency ────────────────────────────────────────────────────────

def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency: validates Bearer JWT and returns the User row.
    Raise 401 if token is missing/invalid, 404 if user doesn't exist in DB.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1]
    email = decode_access_token(token)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def require_active_user(user: User = Depends(get_current_user)) -> User:
    """Like get_current_user but also checks subscription/trial is live."""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Active subscription or trial required.",
        )
    return user


def get_optional_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    FastAPI dependency: returns the User if a valid Bearer JWT is present,
    or None if no token provided / token is invalid.
    Never raises — safe to use on endpoints that work for both authed and anon users.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1]
    try:
        email = decode_access_token(token)
    except HTTPException:
        return None
    return db.query(User).filter(User.email == email).first()


# ── Google OAuth ──────────────────────────────────────────────────────────────

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def google_redirect_uri() -> str:
    return f"{BASE_URL}/auth/google/callback"


def build_google_auth_url(state: str) -> str:
    params = urllib.parse.urlencode({
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  google_redirect_uri(),
        "response_type": "code",
        "scope":         "openid email",
        "state":         state,
        "access_type":   "online",
    })
    return f"{GOOGLE_AUTH_URL}?{params}"


async def exchange_google_code(code: str) -> str:
    """Exchange OAuth authorization code for a verified email address."""
    import httpx
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  google_redirect_uri(),
            "grant_type":    "authorization_code",
        })
        token_data = token_resp.json()
        if "access_token" not in token_data:
            logger.error("Google token exchange failed: %s", token_data)
            raise HTTPException(400, "Google authentication failed")

        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        userinfo = userinfo_resp.json()
        email = userinfo.get("email")
        if not email:
            raise HTTPException(400, "Could not retrieve email from Google")
        return email.lower().strip()
