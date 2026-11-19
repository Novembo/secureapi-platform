"""Schemas for Organization, Member, and Invitation resources."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, TypeVar

from pydantic import EmailStr, Field

from app.schemas.auth import BaseSchema

T = TypeVar("T")


class OrganizationCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")


class OrganizationUpdate(BaseSchema):
    name: str = Field(min_length=1, max_length=255)


class OrganizationOut(BaseSchema):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime


class OrganizationStatusIn(BaseSchema):
    is_active: bool


class MemberOut(BaseSchema):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    status: str
    roles: list[str]
    joined_at: datetime


class MemberStatusIn(BaseSchema):
    status: Literal["active", "suspended"]


class InvitationCreate(BaseSchema):
    email: EmailStr
    role_id: uuid.UUID | None = None  # defaults to member role if None


class InvitationOut(BaseSchema):
    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role_id: uuid.UUID | None
    expires_at: datetime
    created_at: datetime


class InvitationAcceptIn(BaseSchema):
    token: str


class PaginatedResponse[T](BaseSchema):
    items: list[T]
    total: int
    limit: int
    offset: int
