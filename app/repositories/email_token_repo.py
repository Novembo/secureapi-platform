"""Repository for EmailToken entity persistence operations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.clock import get_clock
from app.models.email_token import EmailToken


class EmailTokenRepository:
    """Data-access layer for the EmailToken model."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_token(
        self,
        user_id: uuid.UUID,
        purpose: str,
        token_hash: str,
        expires_at: datetime,
    ) -> EmailToken:
        token = EmailToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.db.add(token)
        self.db.flush()
        return token

    def consume_token(self, token_hash: str, purpose: str) -> EmailToken | None:
        """Finds a valid token by hash+purpose (not used, not expired) and atomically marks it used.

        Returns None when no matching valid token exists.
        """
        now = get_clock().now()
        email_token = (
            self.db.query(EmailToken)
            .filter(
                EmailToken.token_hash == token_hash,
                EmailToken.purpose == purpose,
                EmailToken.used_at.is_(None),
                EmailToken.expires_at > now,
            )
            .first()
        )
        if email_token is None:
            return None
        email_token.used_at = now
        self.db.flush()
        return email_token
