"""Organization management API routes (ORG-01 to ORG-04, PLT-01)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import PermissionDeniedError
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.dependencies.auth import (
    MembershipContext,
    get_current_user,
    get_verified_user,
    require_permission,
)
from app.models.user import User
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationOut,
    OrganizationStatusIn,
    OrganizationUpdate,
    PaginatedResponse,
)
from app.services.audit_service import get_client_ip, get_request_id_from_request
from app.services.organization_service import OrganizationService

router = APIRouter(tags=["organizations"])


@router.post("/organizations", response_model=OrganizationOut, status_code=201)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def create_organization(
    data: OrganizationCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_verified_user),
) -> OrganizationOut:
    """Creates a new organization with the current user as owner (ORG-01)."""
    service = OrganizationService(db)
    return service.create_organization(
        data=data,
        user=user,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )


@router.get("/organizations", response_model=PaginatedResponse[OrganizationOut])
def list_organizations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedResponse[OrganizationOut]:
    """Lists organizations for current user or all organizations for PlatformAdmin (ORG-02)."""
    service = OrganizationService(db)
    return service.list_organizations(user=user, limit=limit, offset=offset)


@router.get("/organizations/{organization_id}", response_model=OrganizationOut)
def get_organization(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrganizationOut:
    """Gets organization details (ORG-03). Active member or PlatformAdmin."""
    service = OrganizationService(db)
    return service.get_organization(org_id=organization_id, user=user)


@router.patch("/organizations/{organization_id}", response_model=OrganizationOut)
def update_organization(
    organization_id: uuid.UUID,
    data: OrganizationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    ctx: MembershipContext = Depends(require_permission("organization:manage")),
) -> OrganizationOut:
    """Updates organization name (ORG-04). Requires organization:manage."""
    service = OrganizationService(db)
    return service.update_organization(
        org_id=organization_id,
        data=data,
        user=ctx.user,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )


@router.put("/platform/organizations/{organization_id}/status", response_model=OrganizationOut)
def update_organization_status(
    organization_id: uuid.UUID,
    data: OrganizationStatusIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrganizationOut:
    """Activates or deactivates an organization (PLT-01). PlatformAdmin only."""
    if not user.is_platform_admin:
        raise PermissionDeniedError("Réservé aux administrateurs de la plateforme.")

    service = OrganizationService(db)
    return service.update_organization_status(
        org_id=organization_id,
        data=data,
        user=user,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )
