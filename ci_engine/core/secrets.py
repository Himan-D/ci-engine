# SPDX-License-Identifier: MIT
# CI Engine - Secrets Management with Fernet Encryption

import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from pydantic import BaseModel, ConfigDict
from cryptography.fernet import Fernet, InvalidToken

from ci_engine.server.models import Base


class Secret(Base):
    __tablename__ = "secrets"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    # repository=None → global secret; repository='owner/repo' → repo-scoped
    repository = Column(String(500), nullable=True, index=True)
    value_encrypted = Column(Text, nullable=False)
    key_version = Column(Integer, default=1)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)


def _get_fernet_key() -> bytes:
    """Get Fernet key from environment variable."""
    key = os.environ.get("CI_ENGINE_FERNET_KEY")
    if not key:
        raise ValueError(
            "CI_ENGINE_FERNET_KEY environment variable must be set. "
            'Generate one using: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key())"'
        )
    return key.encode()


_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    """Get or create Fernet instance."""
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_get_fernet_key())
    return _fernet


def _encrypt_value(value: str) -> tuple[str, int]:
    """Encrypt a value using Fernet. Returns (encrypted, key_version)."""
    fernet = _get_fernet()
    encrypted = fernet.encrypt(value.encode())
    return encrypted.decode(), 1


def _decrypt_value(encrypted: str, key_version: int) -> str:
    """Decrypt a value using Fernet."""
    fernet = _get_fernet()
    try:
        decrypted = fernet.decrypt(encrypted.encode())
        return decrypted.decode()
    except InvalidToken as e:
        raise ValueError("Failed to decrypt secret: invalid token") from e


class SecretCreate(BaseModel):
    name: str
    value: str
    created_by: Optional[str] = None
    repository: Optional[str] = None  # None = global; 'owner/repo' = repo-scoped


class SecretResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    is_active: bool
    key_version: int


class SecretService:
    """Service for managing secrets."""

    @staticmethod
    def create_secret(
        db,
        name: str,
        value: str,
        created_by: Optional[str] = None,
        repository: Optional[str] = None,
    ) -> Secret:
        """Create a new secret with Fernet encryption.

        If *repository* is given (e.g. ``'owner/repo'``) the secret is
        repo-scoped and will only be injected into builds from that repo.
        Repository-scoped secrets override global ones with the same name.
        """
        if not value:
            raise ValueError("Secret value must not be empty")
        encrypted, key_version = _encrypt_value(value)
        secret = Secret(
            name=name,
            repository=_normalise_repo(repository),
            value_encrypted=encrypted,
            key_version=key_version,
            created_by=created_by,
        )
        db.add(secret)
        db.commit()
        db.refresh(secret)
        return secret

    @staticmethod
    def get_secret(db, name: str) -> Optional[str]:
        """Get a secret value by name."""
        secret = (
            db.query(Secret)
            .filter(
                Secret.name == name,
                Secret.is_active,
            )
            .first()
        )
        if secret:
            return _decrypt_value(secret.value_encrypted, secret.key_version)
        return None

    @staticmethod
    def get_secret_metadata(db, name: str) -> Optional[Secret]:
        """Get secret metadata without value."""
        return db.query(Secret).filter(Secret.name == name).first()

    @staticmethod
    def update_secret(db, name: str, value: str) -> Optional[Secret]:
        """Update an existing secret."""
        secret = db.query(Secret).filter(Secret.name == name).first()
        if secret:
            encrypted, key_version = _encrypt_value(value)
            secret.value_encrypted = encrypted
            secret.key_version = key_version
            secret.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(secret)
        return secret

    @staticmethod
    def delete_secret(db, name: str) -> bool:
        """Soft delete a secret."""
        secret = db.query(Secret).filter(Secret.name == name).first()
        if secret:
            secret.is_active = False
            db.commit()
            return True
        return False

    @staticmethod
    def list_secrets(db, include_inactive: bool = False) -> list[Secret]:
        """List all secrets."""
        query = db.query(Secret)
        if not include_inactive:
            query = query.filter(Secret.is_active)
        return query.order_by(Secret.name).all()

    @staticmethod
    def get_build_env_vars(db, build_id: int) -> dict[str, str]:
        """Get environment variables for a build from secrets.

        Loads secrets assigned to the build's repository and returns
        decrypted key-value pairs for injection into the build environment.

        Args:
            db: Database session
            build_id: Build ID to get secrets for

        Returns:
            Dictionary of decrypted secret key-value pairs
        """
        from ci_engine.server.models import Build

        env_vars = {}

        # Get the build to find its repository
        build = db.query(Build).filter(Build.id == build_id).first()
        if not build:
            return {}

        # Get active secrets for this repository
        secrets = (
            db.query(Secret)
            .filter(
                Secret.is_active,
            )
            .all()
        )

        # Filter secrets that should apply to this build
        # All secrets are currently global, but we could filter by repository later
        for secret in secrets:
            try:
                decrypted = _decrypt_value(secret.value_encrypted, secret.key_version)
                env_vars[secret.name] = decrypted
            except ValueError as e:
                # Log but don't fail the build
                import logging

                logging.warning(f"Failed to decrypt secret {secret.name}: {e}")
                continue

        return env_vars


def _normalise_repo(repo: Optional[str]) -> Optional[str]:
    """Normalise repository identifier to 'owner/repo' (strip https://, trailing slash, .git)."""
    if not repo:
        return None
    r = repo.strip().rstrip("/")
    if r.endswith(".git"):
        r = r[:-4]
    # Strip https://github.com/ or git@github.com: prefix
    for prefix in ("https://github.com/", "https://gitlab.com/", "git@github.com:", "git@gitlab.com:"):
        if r.startswith(prefix):
            r = r[len(prefix):]
            break
    return r or None


def get_active_secrets(db, repository: Optional[str] = None) -> dict[str, str]:
    """Return decrypted key=value dict of active secrets for a build.

    Two-pass strategy:
      1. Fetch all global secrets (repository IS NULL).
      2. Fetch repo-scoped secrets for *repository* (overrides globals).

    If ``CI_ENGINE_FERNET_KEY`` is not set (dev mode), returns {} gracefully.
    """
    try:
        _get_fernet()
    except ValueError:
        return {}

    normalised = _normalise_repo(repository)

    # Pass 1 — global secrets
    global_secrets = (
        db.query(Secret)
        .filter(Secret.is_active, Secret.repository.is_(None))
        .all()
    )

    result: dict[str, str] = {}
    for s in global_secrets:
        try:
            result[s.name] = _decrypt_value(s.value_encrypted, s.key_version)
        except Exception:
            pass

    # Pass 2 — repo-scoped secrets (override globals of same name)
    if normalised:
        repo_secrets = (
            db.query(Secret)
            .filter(Secret.is_active, Secret.repository == normalised)
            .all()
        )
        for s in repo_secrets:
            try:
                result[s.name] = _decrypt_value(s.value_encrypted, s.key_version)
            except Exception:
                pass

    return result
