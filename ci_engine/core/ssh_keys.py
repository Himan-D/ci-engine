# SPDX-License-Identifier: MIT
# CI Engine - SSH Key Management for Agents

import hashlib
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from pydantic import BaseModel

from ci_engine.server.models import Base


class SSHKey(Base):
    """SSH key model for agent authentication."""

    __tablename__ = "ssh_keys"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    public_key = Column(Text, nullable=False)
    fingerprint = Column(String(100), nullable=False, unique=True)
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)


class SSHKeyCreate(BaseModel):
    """Schema for creating SSH key."""

    name: str
    public_key: str
    description: Optional[str] = None


class SSHKeyResponse(BaseModel):
    """Schema for SSH key response."""

    id: int
    name: str
    fingerprint: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime]

    class Config:
        from_attributes = True


def generate_fingerprint(public_key: str) -> str:
    """Generate SHA256 fingerprint from SSH public key."""
    import base64

    parts = public_key.strip().split()
    if len(parts) < 2:
        return ""

    key_data = parts[1]
    try:
        key_bytes = base64.b64decode(key_data)
        fingerprint = hashlib.sha256(key_bytes).hexdigest()
        return ":".join([fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2)])
    except Exception:
        return ""


def create_ssh_key(
    name: str,
    public_key: str,
    db,
    description: Optional[str] = None,
    created_by: Optional[int] = None,
) -> SSHKey:
    """Create a new SSH key."""
    fingerprint = generate_fingerprint(public_key)

    existing = db.query(SSHKey).filter(SSHKey.fingerprint == fingerprint).first()
    if existing:
        raise ValueError("SSH key already exists")

    key = SSHKey(
        name=name,
        public_key=public_key,
        fingerprint=fingerprint,
        description=description,
        created_by=created_by,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


def get_ssh_key(key_id: int, db) -> Optional[SSHKey]:
    """Get SSH key by ID."""
    return db.query(SSHKey).filter(SSHKey.id == key_id).first()


def get_ssh_key_by_fingerprint(fingerprint: str, db) -> Optional[SSHKey]:
    """Get SSH key by fingerprint."""
    return db.query(SSHKey).filter(SSHKey.fingerprint == fingerprint).first()


def list_ssh_keys(db, active_only: bool = False) -> list[SSHKey]:
    """List SSH keys."""
    query = db.query(SSHKey)
    if active_only:
        query = query.filter(SSHKey.is_active)
    return query.all()


def update_ssh_key(
    key_id: int,
    db,
    name: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[SSHKey]:
    """Update an SSH key."""
    key = db.query(SSHKey).filter(SSHKey.id == key_id).first()
    if not key:
        return None

    if name is not None:
        key.name = name
    if description is not None:
        key.description = description
    if is_active is not None:
        key.is_active = is_active

    db.commit()
    db.refresh(key)
    return key


def delete_ssh_key(key_id: int, db) -> bool:
    """Delete an SSH key."""
    key = db.query(SSHKey).filter(SSHKey.id == key_id).first()
    if not key:
        return False

    db.delete(key)
    db.commit()
    return True


def mark_key_used(key_id: int, db) -> bool:
    """Mark SSH key as used."""
    key = db.query(SSHKey).filter(SSHKey.id == key_id).first()
    if not key:
        return False

    key.last_used_at = datetime.utcnow()
    db.commit()
    return True


def validate_agent_key(public_key: str, db) -> Optional[SSHKey]:
    """Validate an agent's SSH key and return the key if valid."""
    fingerprint = generate_fingerprint(public_key)
    if not fingerprint:
        return None

    key = get_ssh_key_by_fingerprint(fingerprint, db)
    if not key or not key.is_active:
        return None

    mark_key_used(key.id, db)
    return key
