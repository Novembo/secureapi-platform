"""Repository for RefreshSession entity persistence operations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.clock import get_clock
from app.models.refresh_session import RefreshSession


class RefreshSessionRepository:
    """Data-access layer for the RefreshSession model."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_session(
        self,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshSession:
        session = RefreshSession(
            user_id=user_id,
            family_id=family_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.db.add(session)
        self.db.flush()
        return session

    def get_by_token_hash(
        self, token_hash: str, *, for_update: bool = False
    ) -> RefreshSession | None:
        """Looks up a refresh session by token hash.

        When for_update=True, applies SELECT … FOR UPDATE (advisory in SQLite).
        """
        query = self.db.query(RefreshSession).filter(RefreshSession.token_hash == token_hash)
        if for_update:
            query = query.with_for_update()
        return query.first()

    def revoke_family(self, family_id: uuid.UUID) -> None:
        """Revokes all non-revoked sessions in the given family."""
        now = get_clock().now()
        self.db.query(RefreshSession).filter(
            RefreshSession.family_id == family_id,
            RefreshSession.revoked_at.is_(None),
        ).update({"revoked_at": now}, synchronize_session="fetch")
        self.db.flush()

    def revoke_all_user_sessions(self, user_id: uuid.UUID) -> None:
        """Revokes all non-revoked sessions for a user."""
        now = get_clock().now()
        self.db.query(RefreshSession).filter(
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
        ).update({"revoked_at": now}, synchronize_session="fetch")
        self.db.flush()

    def has_active_session_in_family(self, family_id: uuid.UUID) -> bool:
        """Returns True if at least one non-revoked, non-expired session exists."""
        now = get_clock().now()
        return (
            self.db.query(RefreshSession)
            .filter(
                RefreshSession.family_id == family_id,
                RefreshSession.revoked_at.is_(None),
                RefreshSession.expires_at > now,
            )
            .first()
            is not None
        )
