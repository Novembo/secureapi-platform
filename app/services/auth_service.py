"""Authentication service: register, login, refresh, logout, email verification, password reset."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.clock import ensure_utc, get_clock
from app.core.config import settings
from app.core.exceptions import (
    EmailNotVerifiedError,
    InvalidCredentialsError,
    NotFoundError,
    TokenInvalid400Error,
)
from app.core.security import (
    create_access_token,
    generate_secure_token,
    hash_password,
    hash_token,
    validate_password_policy,
    verify_dummy_password,
    verify_password,
)
from app.repositories.email_token_repo import EmailTokenRepository
from app.repositories.refresh_session_repo import RefreshSessionRepository
from app.repositories.user_repo import UserRepository
from app.schemas.auth import (
    ForgotPasswordIn,
    LoginIn,
    MembershipRoleOut,
    MeOut,
    RefreshIn,
    RegisterIn,
    ResetPasswordIn,
    TokenOut,
    VerifyEmailIn,
)
from app.services.audit_service import AuditService
from app.services.email_sender import get_email_sender


class AuthService:
    """Encapsulates all authentication business logic."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.user_repo = UserRepository(db)
        self.refresh_repo = RefreshSessionRepository(db)
        self.email_token_repo = EmailTokenRepository(db)
        self.audit = AuditService(db)
        self.email_sender = get_email_sender()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, data: RegisterIn, ip: str, req_id: str) -> None:
        """Registers a new user or silently notifies an existing one (uniform 202)."""
        validate_password_policy(data.password, data.email)

        existing = self.user_repo.get_by_email(data.email)
        if existing is not None:
            self.email_sender.send_account_exists_email(data.email)
            return

        password_hash = hash_password(data.password)
        user = self.user_repo.create(
            email=data.email,
            password_hash=password_hash,
            full_name=data.full_name,
        )

        # Create verification email token
        raw_token = generate_secure_token()
        token_hash = hash_token(raw_token)
        now = get_clock().now()
        self.email_token_repo.create_token(
            user_id=user.id,
            purpose="verify_email",
            token_hash=token_hash,
            expires_at=now + timedelta(hours=24),
        )

        self.email_sender.send_verification_email(data.email, raw_token)

        self.audit.record(
            action="user.registered",
            resource_type="user",
            actor_id=user.id,
            resource_id=str(user.id),
            metadata={"email": data.email},
            ip_address=ip,
            request_id=req_id,
        )
        self.db.commit()

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def login(self, data: LoginIn, ip: str, req_id: str) -> TokenOut:
        """Authenticates a user and returns access + refresh tokens."""
        user = self.user_repo.get_by_email(data.email)

        # User not found — constant-time dummy hash
        if user is None:
            verify_dummy_password(data.password)
            raise InvalidCredentialsError()

        # User inactive
        if not user.is_active:
            verify_dummy_password(data.password)
            raise InvalidCredentialsError()

        # Account locked
        now = get_clock().now()
        if user.locked_until is not None and ensure_utc(user.locked_until) > now:
            raise InvalidCredentialsError()

        # Wrong password
        if not verify_password(data.password, user.password_hash):
            self.user_repo.increment_failed_attempts(user)

            if user.failed_login_attempts >= settings.LOGIN_MAX_ATTEMPTS:
                lock_until = now + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
                self.user_repo.lock_user(user, lock_until)
                self.audit.record(
                    action="auth.account_locked",
                    resource_type="user",
                    actor_id=user.id,
                    resource_id=str(user.id),
                    metadata={"email": data.email},
                    ip_address=ip,
                    request_id=req_id,
                )

            self.audit.record(
                action="auth.login_failed",
                resource_type="user",
                actor_id=user.id,
                resource_id=str(user.id),
                metadata={"email": data.email},
                ip_address=ip,
                request_id=req_id,
            )
            self.db.commit()
            raise InvalidCredentialsError()

        # Email verification required
        if settings.REQUIRE_VERIFIED_EMAIL and not user.is_verified:
            raise EmailNotVerifiedError()

        # Success
        self.user_repo.reset_failed_attempts(user)

        family_id = uuid.uuid4()
        raw_token = generate_secure_token()
        token_hash_val = hash_token(raw_token)
        refresh_expires = now + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)

        self.refresh_repo.create_session(
            user_id=user.id,
            family_id=family_id,
            token_hash=token_hash_val,
            expires_at=refresh_expires,
        )

        access_token = create_access_token(
            user_id=str(user.id),
            family_id=str(family_id),
        )

        self.audit.record(
            action="auth.login_success",
            resource_type="user",
            actor_id=user.id,
            resource_id=str(user.id),
            metadata={"email": data.email},
            ip_address=ip,
            request_id=req_id,
        )
        self.db.commit()

        return TokenOut(
            access_token=access_token,
            refresh_token=raw_token,
            token_type="bearer",  # noqa: S106
            expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
        )

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self, data: RefreshIn, ip: str, req_id: str) -> TokenOut:
        """Rotates a refresh token (family-based reuse detection)."""
        incoming_hash = hash_token(data.refresh_token)
        session = self.refresh_repo.get_by_token_hash(incoming_hash, for_update=True)

        if session is None:
            raise InvalidCredentialsError()

        now = get_clock().now()

        # Expired
        if ensure_utc(session.expires_at) <= now:
            raise InvalidCredentialsError()

        # Reuse detection: revoked AND already replaced → family compromise
        if session.revoked_at is not None:
            if session.replaced_by_id is not None:
                self.refresh_repo.revoke_family(session.family_id)
                self.audit.record(
                    action="auth.refresh_reuse_detected",
                    resource_type="refresh_session",
                    actor_id=session.user_id,
                    resource_id=str(session.family_id),
                    metadata={"family_id": str(session.family_id)},
                    ip_address=ip,
                    request_id=req_id,
                )
                self.db.commit()
                raise InvalidCredentialsError()
            # Revoked without replacement
            raise InvalidCredentialsError()

        # Normal rotation
        raw_token = generate_secure_token()
        new_hash = hash_token(raw_token)
        refresh_expires = now + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)

        new_session = self.refresh_repo.create_session(
            user_id=session.user_id,
            family_id=session.family_id,
            token_hash=new_hash,
            expires_at=refresh_expires,
        )

        # Mark old session as revoked + replaced
        session.revoked_at = now
        session.replaced_by_id = new_session.id
        self.db.flush()

        access_token = create_access_token(
            user_id=str(session.user_id),
            family_id=str(session.family_id),
        )

        self.db.commit()

        return TokenOut(
            access_token=access_token,
            refresh_token=raw_token,
            token_type="bearer",  # noqa: S106
            expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
        )

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------

    def logout(self, user_id: uuid.UUID, family_id: uuid.UUID, ip: str, req_id: str) -> None:
        """Revokes all sessions in the current token family."""
        self.refresh_repo.revoke_family(family_id)
        self.audit.record(
            action="auth.logout",
            resource_type="user",
            actor_id=user_id,
            resource_id=str(user_id),
            ip_address=ip,
            request_id=req_id,
        )
        self.db.commit()

    def logout_all(self, user_id: uuid.UUID, ip: str, req_id: str) -> None:
        """Revokes all sessions for the user."""
        self.refresh_repo.revoke_all_user_sessions(user_id)
        self.audit.record(
            action="auth.logout_all",
            resource_type="user",
            actor_id=user_id,
            resource_id=str(user_id),
            ip_address=ip,
            request_id=req_id,
        )
        self.db.commit()

    # ------------------------------------------------------------------
    # Email verification
    # ------------------------------------------------------------------

    def verify_email(self, data: VerifyEmailIn, ip: str, req_id: str) -> None:
        """Verifies a user's email address via a one-time token."""
        token_hash_val = hash_token(data.token)
        email_token = self.email_token_repo.consume_token(token_hash_val, "verify_email")

        if email_token is None:
            raise TokenInvalid400Error()

        user = self.user_repo.get_by_id(email_token.user_id)
        if user is None:
            raise TokenInvalid400Error()

        self.user_repo.set_verified(user)

        self.audit.record(
            action="auth.email_verified",
            resource_type="user",
            actor_id=user.id,
            resource_id=str(user.id),
            metadata={"email": user.email},
            ip_address=ip,
            request_id=req_id,
        )
        self.db.commit()

    # ------------------------------------------------------------------
    # Forgot / Reset password
    # ------------------------------------------------------------------

    def forgot_password(self, data: ForgotPasswordIn, ip: str, req_id: str) -> None:
        """Initiates password reset (uniform 202 regardless of email existence)."""
        user = self.user_repo.get_by_email(data.email)
        if user is not None and user.is_active:
            raw_token = generate_secure_token()
            token_hash_val = hash_token(raw_token)
            now = get_clock().now()
            self.email_token_repo.create_token(
                user_id=user.id,
                purpose="reset_password",
                token_hash=token_hash_val,
                expires_at=now + timedelta(hours=1),
            )
            self.email_sender.send_password_reset_email(data.email, raw_token)

            self.audit.record(
                action="auth.password_reset_requested",
                resource_type="user",
                actor_id=user.id,
                resource_id=str(user.id),
                metadata={"email": data.email},
                ip_address=ip,
                request_id=req_id,
            )
            self.db.commit()

    def reset_password(self, data: ResetPasswordIn, ip: str, req_id: str) -> None:
        """Resets a user's password via a one-time token."""
        token_hash_val = hash_token(data.token)
        email_token = self.email_token_repo.consume_token(token_hash_val, "reset_password")

        if email_token is None:
            raise TokenInvalid400Error()

        user = self.user_repo.get_by_id(email_token.user_id)
        if user is None:
            raise TokenInvalid400Error()

        validate_password_policy(data.new_password, user.email)

        new_hash = hash_password(data.new_password)
        self.user_repo.update_password(user, new_hash)

        # Revoke all sessions for security
        self.refresh_repo.revoke_all_user_sessions(user.id)

        self.audit.record(
            action="auth.password_reset",
            resource_type="user",
            actor_id=user.id,
            resource_id=str(user.id),
            metadata={"email": user.email},
            ip_address=ip,
            request_id=req_id,
        )
        self.db.commit()

    # ------------------------------------------------------------------
    # Me
    # ------------------------------------------------------------------

    def get_me(self, user_id: uuid.UUID) -> MeOut:
        """Returns the authenticated user's profile including memberships."""
        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("Utilisateur introuvable.")

        membership_items: list[MembershipRoleOut] = []
        for membership in user.memberships:
            if membership.status != "active":
                continue
            role_names: list[str] = []
            permission_codes: set[str] = set()
            for role in membership.roles:
                role_names.append(role.name)
                for perm in role.permissions:
                    permission_codes.add(perm.code)
            membership_items.append(
                MembershipRoleOut(
                    organization_id=membership.organization_id,
                    organization_slug=membership.organization.slug,
                    roles=role_names,
                    permissions=sorted(permission_codes),
                )
            )

        return MeOut(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_verified=user.is_verified,
            is_platform_admin=user.is_platform_admin,
            memberships=membership_items,
        )
