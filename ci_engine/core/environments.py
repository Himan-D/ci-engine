# SPDX-License-Identifier: MIT
# CI Engine - Environment Groups

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, Text
from pydantic import BaseModel, ConfigDict

from ci_engine.server.models import Base


class EnvironmentGroup(Base):
    """Environment variable group model."""

    __tablename__ = "environment_groups"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(500), nullable=True)
    variables = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by = Column(Integer, nullable=True)


class EnvironmentGroupCreate(BaseModel):
    """Schema for creating environment group."""

    name: str
    description: Optional[str] = None
    variables: dict[str, str]


class EnvironmentGroupResponse(BaseModel):
    """Schema for environment group response."""

    id: int
    name: str
    description: Optional[str]
    variables: dict[str, str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


def create_environment_group(
    name: str,
    variables: dict[str, str],
    db,
    description: Optional[str] = None,
    created_by: Optional[int] = None,
) -> EnvironmentGroup:
    """Create a new environment group."""
    group = EnvironmentGroup(
        name=name,
        description=description,
        variables=json.dumps(variables),
        created_by=created_by,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def get_environment_group(group_id: int, db) -> Optional[EnvironmentGroup]:
    """Get environment group by ID."""
    return db.query(EnvironmentGroup).filter(EnvironmentGroup.id == group_id).first()


def get_environment_group_by_name(name: str, db) -> Optional[EnvironmentGroup]:
    """Get environment group by name."""
    return db.query(EnvironmentGroup).filter(EnvironmentGroup.name == name).first()


def list_environment_groups(db) -> list[EnvironmentGroup]:
    """List all environment groups."""
    return db.query(EnvironmentGroup).all()


def update_environment_group(
    group_id: int,
    db,
    name: Optional[str] = None,
    description: Optional[str] = None,
    variables: Optional[dict[str, str]] = None,
) -> Optional[EnvironmentGroup]:
    """Update an environment group."""
    group = db.query(EnvironmentGroup).filter(EnvironmentGroup.id == group_id).first()
    if not group:
        return None

    if name is not None:
        group.name = name
    if description is not None:
        group.description = description
    if variables is not None:
        group.variables = json.dumps(variables)

    group.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(group)
    return group


def delete_environment_group(group_id: int, db) -> bool:
    """Delete an environment group."""
    group = db.query(EnvironmentGroup).filter(EnvironmentGroup.id == group_id).first()
    if not group:
        return False

    db.delete(group)
    db.commit()
    return True


def get_group_variables(group_name: str, db) -> dict[str, str]:
    """Get variables for an environment group."""
    group = get_environment_group_by_name(group_name, db)
    if not group:
        return {}
    return json.loads(group.variables)
