import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class BaseSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterIn(BaseSchema):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)


class LoginIn(BaseSchema):
    email: EmailStr
    password: str


class TokenOut(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int  # in seconds


class RefreshIn(BaseSchema):
    refresh_token: str


class VerifyEmailIn(BaseSchema):
    token: str


class ForgotPasswordIn(BaseSchema):
    email: EmailStr


class ResetPasswordIn(BaseSchema):
    token: str
    new_password: str = Field(min_length=12, max_length=128)


class MembershipRoleOut(BaseSchema):
    organization_id: uuid.UUID
    organization_slug: str
    roles: list[str]
    permissions: list[str]


class MeOut(BaseSchema):
    id: uuid.UUID
    email: str
    full_name: str
    is_verified: bool
    is_platform_admin: bool
    memberships: list[MembershipRoleOut]
