"""Service handling organization management and platform status."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, SlugTakenError
from app.db.constants import get_system_role_id
from app.models.user import User
from app.repositories.membership_repo import MembershipRepository
from app.repositories.organization_repo import OrganizationRepository
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationOut,
    OrganizationStatusIn,
    OrganizationUpdate,
    PaginatedResponse,
)
from app.services.audit_service import AuditService


class OrganizationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.org_repo = OrganizationRepository(db)
        self.membership_repo = MembershipRepository(db)
        self.audit = AuditService(db)

    def create_organization(
        self, data: OrganizationCreate, user: User, ip: str, req_id: str
    ) -> OrganizationOut:
        """Creates an organization and assigns the owner role to the creator (ORG-01)."""
        existing = self.org_repo.get_by_slug(data.slug)
        if existing is not None:
            raise SlugTakenError()

        org = self.org_repo.create(name=data.name, slug=data.slug)

        # Creator becomes active owner in same transaction
        membership = self.membership_repo.create(
            user_id=user.id,
            org_id=org.id,
            status="active",
        )
        owner_role_id = get_system_role_id("owner")
        self.membership_repo.add_role_to_membership(membership.id, owner_role_id)

        self.audit.record(
            action="organization.created",
            resource_type="organization",
            actor_id=user.id,
            organization_id=org.id,
            resource_id=str(org.id),
            metadata={"name": org.name, "slug": org.slug},
            ip_address=ip,
            request_id=req_id,
        )

        self.db.commit()

        return OrganizationOut(
            id=org.id,
            name=org.name,
            slug=org.slug,
            is_active=org.is_active,
            created_at=org.created_at,
        )

    def list_organizations(
        self, user: User, limit: int = 20, offset: int = 0
    ) -> PaginatedResponse[OrganizationOut]:
        """Lists organizations: all for PlatformAdmin, member orgs for standard users (ORG-02)."""
        if user.is_platform_admin:
            items, total = self.org_repo.list_all(limit=limit, offset=offset)
        else:
            items, total = self.org_repo.list_for_user(user.id, limit=limit, offset=offset)

        return PaginatedResponse(
            items=[
                OrganizationOut(
                    id=org.id,
                    name=org.name,
                    slug=org.slug,
                    is_active=org.is_active,
                    created_at=org.created_at,
                )
                for org in items
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_organization(self, org_id: uuid.UUID, user: User) -> OrganizationOut:
        """Retrieves organization details (ORG-03).

        PlatformAdmin can view any organization (ACC-14).
        Standard users must be active members; otherwise 404 is returned.
        """
        org = self.org_repo.get_by_id(org_id)
        if org is None:
            raise NotFoundError("Organisation introuvable.")

        if not user.is_platform_admin:
            membership = self.membership_repo.get_by_user_and_org(user.id, org_id)
            if membership is None or membership.status != "active":
                raise NotFoundError("Organisation introuvable.")

        return OrganizationOut(
            id=org.id,
            name=org.name,
            slug=org.slug,
            is_active=org.is_active,
            created_at=org.created_at,
        )

    def update_organization(
        self, org_id: uuid.UUID, data: OrganizationUpdate, user: User, ip: str, req_id: str
    ) -> OrganizationOut:
        """Updates organization settings (ORG-04). Requires organization:manage."""
        org = self.org_repo.get_by_id(org_id)
        if org is None:
            raise NotFoundError("Organisation introuvable.")

        self.org_repo.update(org, name=data.name)

        self.audit.record(
            action="organization.updated",
            resource_type="organization",
            actor_id=user.id,
            organization_id=org.id,
            resource_id=str(org.id),
            metadata={"new_name": data.name},
            ip_address=ip,
            request_id=req_id,
        )

        self.db.commit()

        return OrganizationOut(
            id=org.id,
            name=org.name,
            slug=org.slug,
            is_active=org.is_active,
            created_at=org.created_at,
        )

    def update_organization_status(
        self, org_id: uuid.UUID, data: OrganizationStatusIn, user: User, ip: str, req_id: str
    ) -> OrganizationOut:
        """Updates organization active status (PLT-01). PlatformAdmin only."""
        org = self.org_repo.get_by_id(org_id)
        if org is None:
            raise NotFoundError("Organisation introuvable.")

        self.org_repo.update_status(org, is_active=data.is_active)

        self.audit.record(
            action="platform.organization_status_changed",
            resource_type="organization",
            actor_id=user.id,
            organization_id=org.id,
            resource_id=str(org.id),
            metadata={"is_active": data.is_active},
            ip_address=ip,
            request_id=req_id,
        )

        self.db.commit()

        return OrganizationOut(
            id=org.id,
            name=org.name,
            slug=org.slug,
            is_active=org.is_active,
            created_at=org.created_at,
        )
