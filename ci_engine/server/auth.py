# SPDX-License-Identifier: MIT
# CI Engine - Authentication and Authorization

import hashlib
import secrets
import bcrypt
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, Boolean
from pydantic import BaseModel, ConfigDict

from ci_engine.server.models import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(20), default="developer")  # admin, developer, viewer
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True)
    token_hash = Column(String(256), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    user_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    last_used = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)


# Pydantic models for API
class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "developer"


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    created_at: datetime
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class TokenCreate(BaseModel):
    name: str
    expires_in_days: Optional[int] = 30


class TokenResponse(BaseModel):
    token: str  # Only returned once on creation
    name: str
    created_at: datetime
    expires_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class TokenVerify(BaseModel):
    token: str


# Authentication functions
def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a hash."""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def generate_api_token() -> str:
    """Generate a new API token."""
    return secrets.token_urlsafe(32)


def hash_api_token(token: str) -> str:
    """Hash an API token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    """Authentication service for CI Engine."""

    @staticmethod
    def create_user(db, username: str, password: str, role: str = "developer") -> User:
        """Create a new user."""
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def authenticate_user(db, username: str, password: str) -> Optional[User]:
        """Authenticate a user by username and password."""
        user = db.query(User).filter(User.username == username).first()
        if not user or not user.is_active:
            return None
        if verify_password(password, user.password_hash):
            user.last_login = datetime.utcnow()
            db.commit()
            return user
        return None

    @staticmethod
    def create_api_token(
        db, user_id: int, name: str, expires_in_days: int = 30
    ) -> tuple[ApiToken, str]:
        """Create a new API token for a user."""
        token = generate_api_token()
        token_hash = hash_api_token(token)

        expires_at = None
        if expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        api_token = ApiToken(
            token_hash=token_hash,
            name=name,
            user_id=user_id,
            expires_at=expires_at,
        )
        db.add(api_token)
        db.commit()
        db.refresh(api_token)
        return api_token, token

    @staticmethod
    def verify_api_token(db, token: str) -> Optional[User]:
        """Verify an API token and return the user."""
        token_hash = hash_api_token(token)
        api_token = (
            db.query(ApiToken)
            .filter(
                ApiToken.token_hash == token_hash,
                ApiToken.is_active,
            )
            .first()
        )

        if not api_token:
            return None

        # Check expiration
        if api_token.expires_at and api_token.expires_at < datetime.utcnow():
            return None

        # Update last used
        api_token.last_used = datetime.utcnow()
        db.commit()

        return db.query(User).filter(User.id == api_token.user_id).first()

    @staticmethod
    def revoke_api_token(db, token_id: int) -> bool:
        """Revoke an API token."""
        token = db.query(ApiToken).filter(ApiToken.id == token_id).first()
        if token:
            token.is_active = False
            db.commit()
            return True
        return False

    @staticmethod
    def get_user_tokens(db, user_id: int) -> list[ApiToken]:
        """Get all tokens for a user."""
        return db.query(ApiToken).filter(ApiToken.user_id == user_id).all()

    @staticmethod
    def list_user_tokens_metadata(db, user_id: int) -> list[dict]:
        """Get all tokens for a user with metadata (not raw tokens)."""
        tokens = db.query(ApiToken).filter(ApiToken.user_id == user_id).all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "created_at": t.created_at,
                "expires_at": t.expires_at,
                "last_used": t.last_used,
                "is_active": t.is_active,
            }
            for t in tokens
        ]

    @staticmethod
    def revoke_token_by_id(db, token_id: int, user_id: int) -> bool:
        """Revoke a specific token (must belong to user)."""
        token = (
            db.query(ApiToken)
            .filter(
                ApiToken.id == token_id,
                ApiToken.user_id == user_id,
            )
            .first()
        )
        if token:
            token.is_active = False
            db.commit()
            return True
        return False

    @staticmethod
    def get_token_by_id(db, token_id: int, user_id: int) -> Optional[ApiToken]:
        """Get token metadata by ID."""
        return (
            db.query(ApiToken)
            .filter(
                ApiToken.id == token_id,
                ApiToken.user_id == user_id,
            )
            .first()
        )

    @staticmethod
    def rotate_refresh_token(db, old_token_id: int, user_id: int) -> Optional[tuple[ApiToken, str]]:
        """Rotate refresh token: invalidate old, create new."""
        old_token = (
            db.query(ApiToken)
            .filter(
                ApiToken.id == old_token_id,
                ApiToken.user_id == user_id,
                ApiToken.is_active,
            )
            .first()
        )

        if not old_token:
            return None

        old_token.is_active = False

        new_token = generate_api_token()
        new_token_hash = hash_api_token(new_token)

        expires_at = None
        if old_token.expires_at:
            expires_at = old_token.expires_at

        new_api_token = ApiToken(
            token_hash=new_token_hash,
            name=f"{old_token.name} (rotated)",
            user_id=user_id,
            expires_at=expires_at,
        )
        db.add(new_api_token)
        db.commit()
        db.refresh(new_api_token)

        return new_api_token, new_token


class Permission:
    """Permission constants."""

    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"

    @staticmethod
    def can_create_build(role: str) -> bool:
        return role in (Permission.ADMIN, Permission.DEVELOPER)

    @staticmethod
    def can_cancel_build(role: str) -> bool:
        return role in (Permission.ADMIN, Permission.DEVELOPER)

    @staticmethod
    def can_manage_agents(role: str) -> bool:
        return role == Permission.ADMIN

    @staticmethod
    def can_manage_users(role: str) -> bool:
        return role == Permission.ADMIN

    @staticmethod
    def can_view_builds(role: str) -> bool:
        return True  # All roles can view

    @staticmethod
    def can_create_tokens(role: str) -> bool:
        return role in (Permission.ADMIN, Permission.DEVELOPER)


class PasswordValidationError(Exception):
    """Raised when password validation fails."""

    pass


class PasswordValidator:
    """Validate password strength."""

    MIN_LENGTH = 8
    MAX_LENGTH = 128
    REQUIRE_UPPERCASE = True
    REQUIRE_LOWERCASE = True
    REQUIRE_DIGIT = True
    REQUIRE_SPECIAL = False

    @classmethod
    def validate(cls, password: str) -> list[str]:
        """Validate password and return list of errors."""
        errors = []

        if len(password) < cls.MIN_LENGTH:
            errors.append(f"Password must be at least {cls.MIN_LENGTH} characters")
        if len(password) > cls.MAX_LENGTH:
            errors.append(f"Password must not exceed {cls.MAX_LENGTH} characters")
        if cls.REQUIRE_UPPERCASE and not any(c.isupper() for c in password):
            errors.append("Password must contain at least one uppercase letter")
        if cls.REQUIRE_LOWERCASE and not any(c.islower() for c in password):
            errors.append("Password must contain at least one lowercase letter")
        if cls.REQUIRE_DIGIT and not any(c.isdigit() for c in password):
            errors.append("Password must contain at least one digit")

        return errors


def validate_password_strength(password: str) -> bool:
    """Validate password meets strength requirements."""
    return len(PasswordValidator.validate(password)) == 0
