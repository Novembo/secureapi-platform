"""Audit service for recording immutable audit log entries."""

from __future__ import annotations

import re
import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.clock import get_clock
from app.core.logging import get_correlation_id, logger
from app.core.rate_limit import get_real_client_ip
from app.db.session import SessionLocal
from app.models.audit_log import AuditLog

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def mask_email(email: str) -> str:
    """Masks an email address: keeps first char of local part, replaces rest with ***."""
    local, domain = email.split("@")
    return f"{local[0]}***@{domain}"


def _mask_emails_in_dict(data: dict[str, object]) -> dict[str, object]:
    """Returns a shallow copy with email values masked."""
    masked: dict[str, object] = {}
    for key, value in data.items():
        if isinstance(value, str) and _EMAIL_RE.fullmatch(value):
            masked[key] = mask_email(value)
        else:
            masked[key] = value
    return masked


def get_client_ip(request: Request) -> str:
    """Extracts the real client IP from the request."""
    return get_real_client_ip(request)


def get_request_id_from_request(request: Request) -> str:
    """Extracts the request ID from request.state or the correlation context."""
    request_id: str = getattr(request.state, "request_id", "") or get_correlation_id()
    return request_id


def get_audit_session() -> Session:
    """Returns a new DB session for recording out-of-band audit entries."""
    return SessionLocal()


class AuditService:
    """Service for recording immutable audit log entries."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        action: str,
        resource_type: str,
        *,
        actor_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        resource_id: str | None = None,
        metadata: dict[str, object] | None = None,
        ip_address: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Creates an audit log entry in the current transaction."""
        safe_metadata = _mask_emails_in_dict(metadata) if metadata else {}
        entry = AuditLog(
            organization_id=organization_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_=safe_metadata,
            ip_address=ip_address,
            request_id=request_id,
            created_at=get_clock().now(),
        )
        self.db.add(entry)
        self.db.flush()

    def record_in_new_transaction(
        self,
        action: str,
        resource_type: str,
        *,
        actor_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        resource_id: str | None = None,
        metadata: dict[str, object] | None = None,
        ip_address: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Records an audit entry in an independent session/transaction.

        Used for security-critical events (e.g., 403 access denied) that must be
        persisted even if the outer transaction rolls back.
        """
        safe_metadata = _mask_emails_in_dict(metadata) if metadata else {}
        session = get_audit_session()
        try:
            entry = AuditLog(
                organization_id=organization_id,
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                metadata_=safe_metadata,
                ip_address=ip_address,
                request_id=request_id,
                created_at=get_clock().now(),
            )
            session.add(entry)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Failed to record audit entry in new transaction")
        finally:
            session.close()
