"""Email sender protocol and console implementation."""

from __future__ import annotations

from typing import Protocol

from app.core.config import settings
from app.core.logging import logger


class EmailSender(Protocol):
    """Protocol for sending transactional emails."""

    def send_verification_email(self, email: str, token: str) -> None: ...

    def send_password_reset_email(self, email: str, token: str) -> None: ...

    def send_account_exists_email(self, email: str) -> None: ...


class ConsoleEmailSender:
    """Logs email details to the console. Only shows tokens in dev/test."""

    def send_verification_email(self, email: str, token: str) -> None:
        if settings.ENVIRONMENT in ("dev", "test"):
            logger.info(
                "Email: Verification — to=%s token=%s",
                email,
                token,
            )
        else:
            logger.info("Email: Verification — to=%s", email)

    def send_password_reset_email(self, email: str, token: str) -> None:
        if settings.ENVIRONMENT in ("dev", "test"):
            logger.info(
                "Email: Password Reset — to=%s token=%s",
                email,
                token,
            )
        else:
            logger.info("Email: Password Reset — to=%s", email)

    def send_account_exists_email(self, email: str) -> None:
        logger.info("Email: Account Exists — to=%s", email)


_sender: EmailSender | None = None


def get_email_sender() -> EmailSender:
    """Returns the singleton email sender instance."""
    global _sender  # noqa: PLW0603
    if _sender is None:
        _sender = ConsoleEmailSender()
    return _sender
