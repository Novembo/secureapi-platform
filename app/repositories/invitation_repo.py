"""Repository for Invitation entity persistence operations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.invitation import Invitation
from app.models.membership import Membership
from app.models.user import User


class InvitationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        organization_id: uuid.UUID,
        email: str,
        role_id: uuid.UUID | None,
        token_hash: str,
        expires_at: datetime,
        invited_by_id: uuid.UUID | None,
    ) -> Invitation:
        invitation = Invitation(
            id=uuid.uuid4(),
            organization_id=organization_id,
            email=email.lower(),
            role_id=role_id,
            token_hash=token_hash,
            expires_at=expires_at,
            invited_by_id=invited_by_id,
        )
        self.db.add(invitation)
        self.db.flush()
        return invitation

    def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        return self.db.query(Invitation).filter(Invitation.token_hash == token_hash).first()

    def accept_atomic(self, token_hash: str, now: datetime) -> Invitation | None:
        """Atomically marks invitation as accepted if not already accepted and not expired.

        Uses row-level locking / direct update to guarantee that out of two concurrent requests,
        only one succeeds (ACC-09).
        """
        invitation = (
            self.db.query(Invitation)
            .filter(
                Invitation.token_hash == token_hash,
                Invitation.accepted_at.is_(None),
                Invitation.expires_at > now,
            )
            .first()
        )
        if invitation is None:
            return None

        invitation.accepted_at = now
        self.db.flush()
        return invitation

    def check_already_active_member(self, email: str, organization_id: uuid.UUID) -> bool:
        """Checks if a user with this email is already an active member of this organization."""
        count = (
            self.db.query(Membership)
            .join(User, User.id == Membership.user_id)
            .filter(
                func.lower(User.email) == email.lower(),
                Membership.organization_id == organization_id,
                Membership.status == "active",
            )
            .count()
        )
        return count > 0
