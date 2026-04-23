# SPDX-License-Identifier: MIT
# CI Engine - JWT Authentication Middleware

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address

from ci_engine.server.db import get_db
from ci_engine.server.auth import User


class TokenType(str):
    """JWT token types."""

    ACCESS = "access"
    REFRESH = "refresh"


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str
    exp: datetime
    iat: datetime
    type: str = "access"
    name: Optional[str] = None


class AuthConfig:
    """Authentication configuration."""

    SECRET_KEY: str = os.environ.get("CI_ENGINE_JWT_SECRET_KEY", "")
    if not SECRET_KEY:
        import secrets

        SECRET_KEY = secrets.token_urlsafe(32)

    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 15
    REFRESH_TOKEN_EXPIRE_DAYS = 7


def create_access_token(user_id: int, username: str) -> str:
    """Create JWT access token."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "exp": now + timedelta(minutes=AuthConfig.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": now,
        "type": "access",
        "name": username,
    }
    return jwt.encode(payload, AuthConfig.SECRET_KEY, algorithm=AuthConfig.ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    """Create JWT refresh token."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "exp": now + timedelta(days=AuthConfig.REFRESH_TOKEN_EXPIRE_DAYS),
        "iat": now,
        "type": "refresh",
    }
    return jwt.encode(payload, AuthConfig.SECRET_KEY, algorithm=AuthConfig.ALGORITHM)


def verify_token(token: str) -> TokenPayload:
    """Verify and decode JWT token."""
    try:
        payload = jwt.decode(
            token,
            AuthConfig.SECRET_KEY,
            algorithms=[AuthConfig.ALGORITHM],
        )
        return TokenPayload(**payload)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def extract_token_from_header(authorization: Optional[str]) -> str:
    """Extract token from Authorization header."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return parts[1]


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """JWT authentication middleware for FastAPI."""

    def __init__(
        self,
        app,
        public_paths: Optional[list[str]] = None,
    ):
        super().__init__(app)
        self.public_paths = public_paths or [
            "/",
            "/health",
            "/health/deep",
            "/status",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/api/auth/login",
            "/api/auth/register",
            "/api/stats",
            "/ws/",
        ]

        self.ip_allowlist = self._load_ip_allowlist()

    def _load_ip_allowlist(self) -> Optional[list[str]]:
        """Load IP allowlist from environment variable."""
        allowlist_str = os.environ.get("CI_ENGINE_IP_ALLOWLIST", "")
        if not allowlist_str:
            return None
        return [ip.strip() for ip in allowlist_str.split(",") if ip.strip()]

    def _is_ip_allowed(self, ip: str) -> bool:
        """Check if IP is allowed."""
        if not self.ip_allowlist:
            return True

        for allowed in self.ip_allowlist:
            if allowed == ip:
                return True
            if allowed.endswith("*"):
                prefix = allowed[:-1]
                if ip.startswith(prefix):
                    return True
        return False

    def _is_public_path(self, path: str) -> bool:
        """Check if path is public."""
        if not path:
            return True
        path = path.rstrip("/")
        for public in self.public_paths:
            public = public.rstrip("/")
            if path == public or path.startswith(f"{public}/") or path.startswith(public):
                return True
        return False

    async def dispatch(self, request: Request, call_next):
        """Process request through authentication."""
        client_ip = request.client.host if request.client else None

        if client_ip and not self._is_ip_allowed(client_ip):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "IP address not allowed"},
            )

        if self._is_public_path(request.url.path):
            return await call_next(request)

        authorization = request.headers.get("Authorization")
        try:
            token = extract_token_from_header(authorization)
            payload = verify_token(token)

            if payload.type != "access":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type",
                )

            request.state.user_id = int(payload.sub)
            request.state.username = payload.name

        except HTTPException:
            raise
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication failed"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)


security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db=Depends(get_db),
) -> User:
    """Get current authenticated user from token."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_token(credentials.credentials)
    user = db.query(User).filter(User.id == int(payload.sub)).first()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db=Depends(get_db),
) -> Optional[User]:
    """Get current user if authenticated, None otherwise."""
    if not credentials:
        return None

    try:
        payload = verify_token(credentials.credentials)
        user = db.query(User).filter(User.id == int(payload.sub)).first()
        return user if user and user.is_active else None
    except HTTPException:
        return None


def require_role(*allowed_roles: str):
    """Dependency factory for role-based access control."""

    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(allowed_roles)}",
            )
        return current_user

    return role_checker


require_admin = require_role("admin")
require_developer = require_role("admin", "developer")


limiter = Limiter(key_func=get_remote_address)


def get_rate_limit_key(request: Request) -> str:
    """Get rate limit key from request."""
    auth_header = request.headers.get("Authorization")
    if auth_header:
        return auth_header
    return get_remote_address(request)
