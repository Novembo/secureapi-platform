"""Repository for Organization database operations."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.membership import Membership
from app.models.organization import Organization


class OrganizationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, org_id: uuid.UUID) -> Organization | None:
        return self.db.query(Organization).filter(Organization.id == org_id).first()

    def get_by_slug(self, slug: str) -> Organization | None:
        return (
            self.db.query(Organization)
            .filter(func.lower(Organization.slug) == slug.lower())
            .first()
        )

    def create(self, name: str, slug: str) -> Organization:
        org = Organization(
            id=uuid.uuid4(),
            name=name,
            slug=slug.lower(),
            is_active=True,
        )
        self.db.add(org)
        self.db.flush()
        return org

    def update(self, org: Organization, name: str) -> Organization:
        org.name = name
        self.db.flush()
        return org

    def update_status(self, org: Organization, is_active: bool) -> Organization:
        org.is_active = is_active
        self.db.flush()
        return org

    def list_for_user(
        self, user_id: uuid.UUID, limit: int = 20, offset: int = 0
    ) -> tuple[list[Organization], int]:
        """Lists active organizations where the user is an active member."""
        base_query = (
            select(Organization)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(
                Membership.user_id == user_id,
                Membership.status == "active",
                Organization.is_active.is_(True),
            )
        )
        total_stmt = select(func.count()).select_from(base_query.subquery())
        total = self.db.scalar(total_stmt) or 0

        items_stmt = base_query.order_by(Organization.created_at.asc()).offset(offset).limit(limit)
        items = list(self.db.scalars(items_stmt).all())
        return items, total

    def list_all(self, limit: int = 20, offset: int = 0) -> tuple[list[Organization], int]:
        """Lists all organizations across the platform (PlatformAdmin only)."""
        total = self.db.scalar(select(func.count(Organization.id))) or 0
        items_stmt = (
            select(Organization).order_by(Organization.created_at.asc()).offset(offset).limit(limit)
        )
        items = list(self.db.scalars(items_stmt).all())
        return items, total
