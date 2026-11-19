"""Service handling organization members, status transitions, and invitations."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.clock import get_clock
from app.core.exceptions import (
    AlreadyMemberError,
    InvitationInvalidError,
    LastOwnerError,
    NotFoundError,
    PrivilegeEscalationError,
)
from app.core.security import generate_secure_token, hash_token
from app.db.constants import get_system_role_id
from app.dependencies.auth import MembershipContext
from app.models.user import User
from app.repositories.invitation_repo import InvitationRepository
from app.repositories.membership_repo import MembershipRepository
from app.repositories.role_repo import RoleRepository
from app.schemas.organization import (
    InvitationCreate,
    MemberOut,
    MemberStatusIn,
    PaginatedResponse,
)
from app.services.audit_service import AuditService
from app.services.email_sender import get_email_sender


class MemberService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.membership_repo = MembershipRepository(db)
        self.invitation_repo = InvitationRepository(db)
        self.role_repo = RoleRepository(db)
        self.audit = AuditService(db)
        self.email_sender = get_email_sender()

    def list_members(
        self, org_id: uuid.UUID, limit: int = 20, offset: int = 0
    ) -> PaginatedResponse[MemberOut]:
        """Lists members in an organization (ORG-05). Requires users:read."""
        items, total = self.membership_repo.list_members(org_id, limit=limit, offset=offset)
        return PaginatedResponse(
            items=[
                MemberOut(
                    membership_id=m.id,
                    user_id=m.user.id,
                    email=m.user.email,
                    full_name=m.user.full_name,
                    status=m.status,
                    roles=[r.name for r in m.roles],
                    joined_at=m.joined_at,
                )
                for m in items
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    def create_invitation(
        self,
        org_id: uuid.UUID,
        data: InvitationCreate,
        actor_ctx: MembershipContext,
        ip: str,
        req_id: str,
    ) -> dict[str, str]:
        """Creates and emails an invitation (ORG-06).

        Requires users:manage and satisfies Anti-Escalation Rule 1.
        """
        # Check if email is already an active member
        if self.invitation_repo.check_already_active_member(data.email, org_id):
            raise AlreadyMemberError()

        # Target role: default is system role 'member'
        target_role_id = data.role_id or get_system_role_id("member")
        target_role = self.role_repo.get_by_id_and_org(target_role_id, org_id)
        if target_role is None:
            raise NotFoundError("Rôle spécifié introuvable.")

        # Anti-Escalation Rule 1: Actor cannot grant permissions they do not hold
        target_permissions = {p.code for p in target_role.permissions}
        if not target_permissions.issubset(actor_ctx.permissions):
            raise PrivilegeEscalationError(
                "Vous ne pouvez pas inviter avec un rôle contenant des permissions "
                "que vous ne possédez pas."
            )

        raw_token = generate_secure_token()
        token_hash_val = hash_token(raw_token)
        now = get_clock().now()
        expires_at = now + timedelta(days=7)

        self.invitation_repo.create(
            organization_id=org_id,
            email=data.email,
            role_id=target_role_id,
            token_hash=token_hash_val,
            expires_at=expires_at,
            invited_by_id=actor_ctx.user.id,
        )

        self.email_sender.send_account_exists_email(data.email)

        self.audit.record(
            action="invitation.created",
            resource_type="invitation",
            actor_id=actor_ctx.user.id,
            organization_id=org_id,
            resource_id=None,
            metadata={"email": data.email, "role": target_role.name},
            ip_address=ip,
            request_id=req_id,
        )

        self.db.commit()
        return {"message": "Invitation envoyée avec succès."}

    def accept_invitation(self, token: str, user: User, ip: str, req_id: str) -> dict[str, str]:
        """Atomically accepts an invitation and adds the user to the organization (ORG-07)."""
        token_hash_val = hash_token(token)
        now = get_clock().now()

        invitation = self.invitation_repo.accept_atomic(token_hash_val, now=now)
        if invitation is None:
            raise InvitationInvalidError()

        # Email must match the authenticated user
        if invitation.email.lower() != user.email.lower():
            raise InvitationInvalidError()

        # If already member, raise
        existing_membership = self.membership_repo.get_by_user_and_org(
            user.id, invitation.organization_id
        )
        if existing_membership is not None:
            if existing_membership.status == "active":
                raise AlreadyMemberError()
            # Reactivate
            existing_membership.status = "active"
            membership = existing_membership
        else:
            membership = self.membership_repo.create(
                user_id=user.id,
                org_id=invitation.organization_id,
                status="active",
            )

        # Assign role
        role_id = invitation.role_id or get_system_role_id("member")
        self.membership_repo.add_role_to_membership(membership.id, role_id)

        self.audit.record(
            action="invitation.accepted",
            resource_type="invitation",
            actor_id=user.id,
            organization_id=invitation.organization_id,
            resource_id=str(invitation.id),
            metadata={"user_id": str(user.id)},
            ip_address=ip,
            request_id=req_id,
        )

        self.db.commit()
        return {"message": "Invitation acceptée."}

    def update_member_status(
        self,
        org_id: uuid.UUID,
        membership_id: uuid.UUID,
        data: MemberStatusIn,
        actor_ctx: MembershipContext,
        ip: str,
        req_id: str,
    ) -> MemberOut:
        """Updates a member's status (ORG-08).

        Enforces Anti-Escalation Rule 6 (last owner protection).
        """
        membership = self.membership_repo.get_by_id_and_org(membership_id, org_id)
        if membership is None:
            raise NotFoundError("Membre introuvable dans cette organisation.")

        # If suspending an owner, verify not the last active owner
        if data.status == "suspended":
            is_owner = any(r.name == "owner" for r in membership.roles)
            if is_owner:
                active_owners = self.membership_repo.count_active_owners(org_id, for_update=True)
                if active_owners <= 1:
                    raise LastOwnerError()

        membership.status = data.status
        self.db.flush()

        self.audit.record(
            action="member.status_changed",
            resource_type="membership",
            actor_id=actor_ctx.user.id,
            organization_id=org_id,
            resource_id=str(membership.id),
            metadata={"target_user_id": str(membership.user_id), "new_status": data.status},
            ip_address=ip,
            request_id=req_id,
        )

        self.db.commit()

        return MemberOut(
            membership_id=membership.id,
            user_id=membership.user.id,
            email=membership.user.email,
            full_name=membership.user.full_name,
            status=membership.status,
            roles=[r.name for r in membership.roles],
            joined_at=membership.joined_at,
        )

    def remove_member(
        self,
        org_id: uuid.UUID,
        membership_id: uuid.UUID,
        actor_ctx: MembershipContext,
        ip: str,
        req_id: str,
    ) -> None:
        """Removes a member from an organization (ORG-09).

        Enforces Anti-Escalation Rule 6 (last owner protection).
        """
        membership = self.membership_repo.get_by_id_and_org(membership_id, org_id)
        if membership is None:
            raise NotFoundError("Membre introuvable dans cette organisation.")

        is_owner = any(r.name == "owner" for r in membership.roles)
        if is_owner:
            active_owners = self.membership_repo.count_active_owners(org_id, for_update=True)
            if active_owners <= 1:
                raise LastOwnerError()

        self.membership_repo.delete(membership)

        self.audit.record(
            action="member.removed",
            resource_type="membership",
            actor_id=actor_ctx.user.id,
            organization_id=org_id,
            resource_id=str(membership_id),
            metadata={"target_user_id": str(membership.user_id)},
            ip_address=ip,
            request_id=req_id,
        )

        self.db.commit()

    def leave_organization(self, org_id: uuid.UUID, user: User, ip: str, req_id: str) -> None:
        """Current member leaves the organization (ORG-10).

        Enforces Anti-Escalation Rule 6 (last owner cannot leave).
        """
        membership = self.membership_repo.get_by_user_and_org(user.id, org_id)
        if membership is None or membership.status != "active":
            raise NotFoundError("Organisation introuvable.")

        is_owner = any(r.name == "owner" for r in membership.roles)
        if is_owner:
            active_owners = self.membership_repo.count_active_owners(org_id, for_update=True)
            if active_owners <= 1:
                raise LastOwnerError()

        membership.status = "left"
        self.db.flush()

        self.audit.record(
            action="member.left",
            resource_type="membership",
            actor_id=user.id,
            organization_id=org_id,
            resource_id=str(membership.id),
            metadata={"user_id": str(user.id)},
            ip_address=ip,
            request_id=req_id,
        )

        self.db.commit()
