"""Repository for User entity persistence operations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """Data-access layer for the User model."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        """Case-insensitive email lookup."""
        return self.db.query(User).filter(func.lower(User.email) == email.lower()).first()

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def create(self, email: str, password_hash: str, full_name: str) -> User:
        """Creates a new user with the email stored lowercase."""
        user = User(
            email=email.lower(),
            password_hash=password_hash,
            full_name=full_name,
        )
        self.db.add(user)
        self.db.flush()
        return user

    def increment_failed_attempts(self, user: User) -> None:
        user.failed_login_attempts += 1
        self.db.flush()

    def reset_failed_attempts(self, user: User) -> None:
        user.failed_login_attempts = 0
        user.locked_until = None
        self.db.flush()

    def lock_user(self, user: User, until: datetime) -> None:
        user.locked_until = until
        self.db.flush()

    def set_verified(self, user: User) -> None:
        user.is_verified = True
        self.db.flush()

    def update_password(self, user: User, new_password_hash: str) -> None:
        user.password_hash = new_password_hash
        self.db.flush()
