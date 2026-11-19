"""Member and invitation management API routes (ORG-05 to ORG-10)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import (
    MembershipContext,
    get_current_user,
    get_verified_user,
    require_permission,
)
from app.models.user import User
from app.schemas.organization import (
    InvitationAcceptIn,
    InvitationCreate,
    MemberOut,
    MemberStatusIn,
    PaginatedResponse,
)
from app.services.audit_service import get_client_ip, get_request_id_from_request
from app.services.member_service import MemberService

router = APIRouter(tags=["members"])


@router.get(
    "/organizations/{organization_id}/members",
    response_model=PaginatedResponse[MemberOut],
)
def list_members(
    organization_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    ctx: MembershipContext = Depends(require_permission("users:read")),
) -> PaginatedResponse[MemberOut]:
    """Lists members in the organization (ORG-05). Requires users:read."""
    service = MemberService(db)
    return service.list_members(org_id=organization_id, limit=limit, offset=offset)


@router.post("/organizations/{organization_id}/invitations", status_code=201)
def create_invitation(
    organization_id: uuid.UUID,
    data: InvitationCreate,
    request: Request,
    db: Session = Depends(get_db),
    ctx: MembershipContext = Depends(require_permission("users:manage")),
) -> dict[str, str]:
    """Invites a user to the organization (ORG-06). Requires users:manage."""
    service = MemberService(db)
    return service.create_invitation(
        org_id=organization_id,
        data=data,
        actor_ctx=ctx,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )


@router.post("/invitations/accept", status_code=200)
def accept_invitation(
    data: InvitationAcceptIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_verified_user),
) -> dict[str, str]:
    """Accepts an organization invitation (ORG-07). Authenticated and verified."""
    service = MemberService(db)
    return service.accept_invitation(
        token=data.token,
        user=user,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )


@router.delete("/organizations/{organization_id}/members/me", status_code=204)
def leave_organization(
    organization_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Current member leaves the organization (ORG-10). Enforces Rule 6."""
    service = MemberService(db)
    service.leave_organization(
        org_id=organization_id,
        user=user,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )
    return Response(status_code=204)


@router.patch(
    "/organizations/{organization_id}/members/{membership_id}",
    response_model=MemberOut,
)
def update_member_status(
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    data: MemberStatusIn,
    request: Request,
    db: Session = Depends(get_db),
    ctx: MembershipContext = Depends(require_permission("users:manage")),
) -> MemberOut:
    """Updates member status (ORG-08). Requires users:manage. Enforces Rule 6."""
    service = MemberService(db)
    return service.update_member_status(
        org_id=organization_id,
        membership_id=membership_id,
        data=data,
        actor_ctx=ctx,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )


@router.delete(
    "/organizations/{organization_id}/members/{membership_id}",
    status_code=204,
)
def remove_member(
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    ctx: MembershipContext = Depends(require_permission("users:manage")),
) -> Response:
    """Removes a member from the organization (ORG-09). Requires users:manage. Enforces Rule 6."""
    service = MemberService(db)
    service.remove_member(
        org_id=organization_id,
        membership_id=membership_id,
        actor_ctx=ctx,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )
    return Response(status_code=204)
