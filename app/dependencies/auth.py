"""Authentication dependencies for route protection and authorization."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.exceptions import (
    EmailNotVerifiedError,
    InvalidCredentialsError,
    NotFoundError,
    OrganizationInactiveError,
    PermissionDeniedError,
    TokenExpiredError,
    TokenInvalidError,
)
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.membership import Membership
from app.models.organization import Organization
from app.models.user import User
from app.repositories.refresh_session_repo import RefreshSessionRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_service import AuditService, get_client_ip, get_request_id_from_request


@dataclass
class MembershipContext:
    """Carries the authenticated user's membership data for a specific organization."""

    user: User
    membership: Membership
    organization: Organization
    permissions: set[str] = field(default_factory=set)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Extracts and validates the Bearer token, returning the authenticated User."""
    auth_header: str | None = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise InvalidCredentialsError()

    token = auth_header[len("Bearer ") :]

    try:
        payload = decode_access_token(token)
    except TokenExpiredError:
        raise
    except TokenInvalidError:
        raise
    except Exception as e:
        raise TokenInvalidError() from e

    user_id_str: str | None = payload.get("sub")
    family_id_str: str | None = payload.get("sid")
    if not user_id_str or not family_id_str:
        raise TokenInvalidError()

    try:
        user_id = uuid.UUID(user_id_str)
        family_id = uuid.UUID(family_id_str)
    except (ValueError, AttributeError) as e:
        raise TokenInvalidError() from e

    user_repo = UserRepository(db)
    user = user_repo.get_by_id(user_id)
    if user is None or not user.is_active:
        raise InvalidCredentialsError()

    # Verify the session family is still active
    refresh_repo = RefreshSessionRepository(db)
    if not refresh_repo.has_active_session_in_family(family_id):
        raise InvalidCredentialsError()

    # Store family_id on request.state for logout to use
    request.state.family_id = family_id

    return user


def get_verified_user(
    user: User = Depends(get_current_user),
) -> User:
    """Ensures the current user has verified their email."""
    if not user.is_verified:
        raise EmailNotVerifiedError()
    return user


def get_membership_context(
    organization_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MembershipContext:
    """Loads and validates the user's membership in the specified organization."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise NotFoundError("Ressource introuvable.")

    if not org.is_active:
        raise OrganizationInactiveError()

    membership = (
        db.query(Membership)
        .filter(
            Membership.user_id == user.id,
            Membership.organization_id == organization_id,
            Membership.status == "active",
        )
        .first()
    )
    if membership is None:
        # Don't reveal org existence — return generic 404
        raise NotFoundError("Ressource introuvable.")

    # Compute union of all role permissions
    permissions: set[str] = set()
    for role in membership.roles:
        for perm in role.permissions:
            permissions.add(perm.code)

    return MembershipContext(
        user=user,
        membership=membership,
        organization=org,
        permissions=permissions,
    )


def require_permission(
    code: str,
) -> Callable[..., MembershipContext]:
    """Returns a dependency that checks the user has the specified permission."""

    def checker(
        request: Request,
        ctx: MembershipContext = Depends(get_membership_context),
        db: Session = Depends(get_db),
    ) -> MembershipContext:
        if code not in ctx.permissions:
            # Audit in independent transaction so it persists even on rollback
            audit = AuditService(db)
            audit.record_in_new_transaction(
                action="access.denied",
                resource_type="permission",
                actor_id=ctx.user.id,
                organization_id=ctx.organization.id,
                resource_id=code,
                metadata={"required_permission": code},
                ip_address=get_client_ip(request),
                request_id=get_request_id_from_request(request),
            )
            raise PermissionDeniedError()
        return ctx

    return checker
