"""Repository for Membership and MembershipRole operations."""

from __future__ import annotations

import contextlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.constants import get_system_role_id
from app.models.membership import Membership, MembershipRole


class MembershipRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_user_and_org(self, user_id: uuid.UUID, org_id: uuid.UUID) -> Membership | None:
        return (
            self.db.query(Membership)
            .options(selectinload(Membership.roles))
            .filter(
                Membership.user_id == user_id,
                Membership.organization_id == org_id,
            )
            .first()
        )

    def get_by_id_and_org(self, membership_id: uuid.UUID, org_id: uuid.UUID) -> Membership | None:
        return (
            self.db.query(Membership)
            .options(selectinload(Membership.roles), selectinload(Membership.user))
            .filter(
                Membership.id == membership_id,
                Membership.organization_id == org_id,
            )
            .first()
        )

    def create(self, user_id: uuid.UUID, org_id: uuid.UUID, status: str = "active") -> Membership:
        membership = Membership(
            id=uuid.uuid4(),
            user_id=user_id,
            organization_id=org_id,
            status=status,
        )
        self.db.add(membership)
        self.db.flush()
        return membership

    def add_role_to_membership(self, membership_id: uuid.UUID, role_id: uuid.UUID) -> None:
        mr = MembershipRole(membership_id=membership_id, role_id=role_id)
        self.db.add(mr)
        self.db.flush()

    def count_active_owners(self, org_id: uuid.UUID, for_update: bool = True) -> int:
        """Counts active owners in an organization with row-level lock (Rule 6)."""
        owner_role_id = get_system_role_id("owner")
        query = (
            self.db.query(Membership)
            .join(MembershipRole, MembershipRole.membership_id == Membership.id)
            .filter(
                Membership.organization_id == org_id,
                Membership.status == "active",
                MembershipRole.role_id == owner_role_id,
            )
        )
        if for_update:
            with contextlib.suppress(Exception):
                query = query.with_for_update()
        return query.count()

    def list_members(
        self, org_id: uuid.UUID, limit: int = 20, offset: int = 0
    ) -> tuple[list[Membership], int]:
        total_stmt = select(func.count(Membership.id)).where(Membership.organization_id == org_id)
        total = self.db.scalar(total_stmt) or 0

        items_stmt = (
            select(Membership)
            .options(selectinload(Membership.roles), selectinload(Membership.user))
            .where(Membership.organization_id == org_id)
            .order_by(Membership.joined_at.asc())
            .offset(offset)
            .limit(limit)
        )
        items = list(self.db.scalars(items_stmt).all())
        return items, total

    def delete(self, membership: Membership) -> None:
        self.db.delete(membership)
        self.db.flush()
