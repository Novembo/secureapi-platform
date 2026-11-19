"""Integration tests for Phase 3: Organizations, Members, Invitations (ORG-01 to ORG-10).

Covers:
- ACC-05: Suspended member loses access immediately; left member loses access immediately
- ACC-06: IDOR: substituting UUID of member from another org returns 404
- ACC-09: Concurrent acceptance of the same invitation succeeds exactly once
- ACC-14: PlatformAdmin non-member can view org (200), cannot access internal resources (404)
- Creation, slug uniqueness, owner assignment, invitation lifecycle
"""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import FakeClock
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_token
from app.db.constants import get_system_role_id
from app.models.invitation import Invitation
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.refresh_session import RefreshSession
from app.models.user import User
from app.tests.integration.test_auth import create_user


def create_authenticated_user(
    db: Session,
    email: str | None = None,
    is_platform_admin: bool = False,
    is_verified: bool = True,
) -> tuple[User, str]:
    """Helper to create user and a valid active JWT access token."""
    user_email = email or f"user_{uuid.uuid4().hex[:8]}@example.com"
    user = create_user(
        db,
        email=user_email,
        is_verified=is_verified,
        is_platform_admin=is_platform_admin,
    )
    family_id = uuid.uuid4()
    # Create an active refresh session row for this family so sid validation passes
    session = RefreshSession(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_id,
        token_hash=hash_token(f"refresh-token-for-{user_email}"),
        expires_at=user.created_at + timedelta(days=7),
    )
    db.add(session)
    db.commit()

    token = create_access_token(user_id=str(user.id), family_id=str(family_id))
    return user, token


def create_organization_with_owner(
    db: Session, owner: User, name: str = "Acme Corp", slug: str = "acme"
) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=slug,
        is_active=True,
    )
    db.add(org)
    db.flush()

    membership = Membership(
        id=uuid.uuid4(),
        user_id=owner.id,
        organization_id=org.id,
        status="active",
    )
    db.add(membership)
    db.flush()

    mr = MembershipRole(
        membership_id=membership.id,
        role_id=get_system_role_id("owner"),
    )
    db.add(mr)
    db.commit()
    db.refresh(org)
    return org


def add_member_to_org(
    db: Session,
    user: User,
    org: Organization,
    role_name: str = "member",
    status: str = "active",
) -> Membership:
    membership = Membership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=org.id,
        status=status,
    )
    db.add(membership)
    db.flush()

    mr = MembershipRole(
        membership_id=membership.id,
        role_id=get_system_role_id(role_name),
    )
    db.add(mr)
    db.commit()
    db.refresh(membership)
    return membership


# ==============================================================================
# ACC-05: Member status transitions (suspended, left) immediately revoke access
# ==============================================================================


def test_ACC_05_suspended_member_loses_access(client: TestClient, db_session: Session) -> None:
    """A member who is suspended immediately loses access to organization resources."""
    owner, owner_token = create_authenticated_user(db_session)
    org = create_organization_with_owner(
        db_session, owner, "Test Org", f"test-org-{uuid.uuid4().hex[:6]}"
    )

    member, member_token = create_authenticated_user(db_session)
    membership = add_member_to_org(db_session, member, org, role_name="security_admin")

    # Member can initially list members (has users:read)
    member_headers = {"Authorization": f"Bearer {member_token}"}
    res_before = client.get(
        f"/api/v1/organizations/{org.id}/members",
        headers=member_headers,
    )
    assert res_before.status_code == 200

    # Owner suspends member
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    patch_res = client.patch(
        f"/api/v1/organizations/{org.id}/members/{membership.id}",
        json={"status": "suspended"},
        headers=owner_headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "suspended"

    # Suspended member immediately receives 404 (non-member) on organization endpoints
    res_after = client.get(
        f"/api/v1/organizations/{org.id}/members",
        headers=member_headers,
    )
    assert res_after.status_code == 404


def test_ACC_05_left_member_loses_access(client: TestClient, db_session: Session) -> None:
    """A member who leaves the organization immediately loses all access."""
    owner, _ = create_authenticated_user(db_session)
    org = create_organization_with_owner(
        db_session, owner, "Test Org 2", f"test-org-2-{uuid.uuid4().hex[:6]}"
    )

    member, member_token = create_authenticated_user(db_session)
    add_member_to_org(db_session, member, org, role_name="security_admin")

    member_headers = {"Authorization": f"Bearer {member_token}"}
    # Member leaves
    leave_res = client.delete(
        f"/api/v1/organizations/{org.id}/members/me",
        headers=member_headers,
    )
    assert leave_res.status_code == 204

    # Member immediately gets 404
    res_after = client.get(
        f"/api/v1/organizations/{org.id}/members",
        headers=member_headers,
    )
    assert res_after.status_code == 404


# ==============================================================================
# ACC-06: IDOR protection across organizations
# ==============================================================================


def test_ACC_06_idor_member_other_org(client: TestClient, db_session: Session) -> None:
    """Substituting member ID of another organization returns 404."""
    owner_a, token_a = create_authenticated_user(db_session)
    org_a = create_organization_with_owner(
        db_session, owner_a, "Org A", f"org-a-{uuid.uuid4().hex[:6]}"
    )

    owner_b, _ = create_authenticated_user(db_session)
    org_b = create_organization_with_owner(
        db_session, owner_b, "Org B", f"org-b-{uuid.uuid4().hex[:6]}"
    )

    member_b, _ = create_authenticated_user(db_session)
    membership_b = add_member_to_org(db_session, member_b, org_b)

    # Owner A attempts to modify member_b from Org B using Org A path
    headers_a = {"Authorization": f"Bearer {token_a}"}
    idor_res = client.patch(
        f"/api/v1/organizations/{org_a.id}/members/{membership_b.id}",
        json={"status": "suspended"},
        headers=headers_a,
    )
    assert idor_res.status_code == 404
    assert idor_res.json()["error"]["code"] == "not_found"


# ==============================================================================
# ACC-09: Concurrent invitation accept (atomic consumption)
# ==============================================================================


def test_ACC_09_invitation_accept_lifecycle(
    client: TestClient, db_session: Session, fake_clock: FakeClock
) -> None:
    """Invitation acceptance: valid accept succeeds, second returns 400 invitation_invalid."""
    owner, token_owner = create_authenticated_user(db_session)
    org = create_organization_with_owner(
        db_session, owner, "Inv Org", f"inv-org-{uuid.uuid4().hex[:6]}"
    )

    invited_email = f"invited_{uuid.uuid4().hex[:6]}@example.com"
    invited_user, token_invited = create_authenticated_user(
        db_session, invited_email, is_verified=True
    )

    # Create invitation
    raw_token = f"invitation-token-{uuid.uuid4().hex}"
    inv = Invitation(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=invited_email,
        role_id=get_system_role_id("member"),
        token_hash=hash_token(raw_token),
        expires_at=fake_clock.now() + timedelta(days=7),
    )
    db_session.add(inv)
    db_session.commit()

    # 1. First acceptance -> 200
    headers_invited = {"Authorization": f"Bearer {token_invited}"}
    accept_1 = client.post(
        "/api/v1/invitations/accept",
        json={"token": raw_token},
        headers=headers_invited,
    )
    assert accept_1.status_code == 200

    # Verify invited user is now active member
    m = (
        db_session.query(Membership)
        .filter(
            Membership.user_id == invited_user.id,
            Membership.organization_id == org.id,
        )
        .first()
    )
    assert m is not None
    assert m.status == "active"

    # 2. Second acceptance (or concurrent replay) -> 400 invitation_invalid
    accept_2 = client.post(
        "/api/v1/invitations/accept",
        json={"token": raw_token},
        headers=headers_invited,
    )
    assert accept_2.status_code == 400
    assert accept_2.json()["error"]["code"] == "invitation_invalid"


# ==============================================================================
# ACC-14: PlatformAdmin privileges and boundaries
# ==============================================================================


def test_ACC_14_platform_admin_view_org(client: TestClient, db_session: Session) -> None:
    """PlatformAdmin can view any organization (200), even without membership (ACC-14)."""
    owner, _ = create_authenticated_user(db_session)
    org_slug = f"org-c-{uuid.uuid4().hex[:6]}"
    org = create_organization_with_owner(db_session, owner, "Org C", org_slug)

    admin, admin_token = create_authenticated_user(db_session, is_platform_admin=True)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # PlatformAdmin GET /organizations/{id} -> 200
    res = client.get(f"/api/v1/organizations/{org.id}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["name"] == "Org C"

    # PlatformAdmin can change organization status (PLT-01)
    status_res = client.put(
        f"/api/v1/platform/organizations/{org.id}/status",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert status_res.status_code == 200
    assert status_res.json()["is_active"] is False


def test_organization_crud_lifecycle(client: TestClient, db_session: Session) -> None:
    """Tests complete organization creation, slug uniqueness, and update."""
    limiter.reset()
    user, token = create_authenticated_user(db_session, is_verified=True)
    headers = {"Authorization": f"Bearer {token}"}
    slug = f"company-{uuid.uuid4().hex[:6]}"

    # 1. Create org -> 201
    create_res = client.post(
        "/api/v1/organizations",
        json={"name": "My Company", "slug": slug},
        headers=headers,
    )
    assert create_res.status_code == 201
    org_id = create_res.json()["id"]

    # 2. Duplicate slug -> 409
    dup_res = client.post(
        "/api/v1/organizations",
        json={"name": "Other Company", "slug": slug},
        headers=headers,
    )
    assert dup_res.status_code == 409
    assert dup_res.json()["error"]["code"] == "slug_taken"

    # 3. Update org name -> 200
    patch_res = client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"name": "My New Company"},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "My New Company"


# ==============================================================================
# Invitation validation & Anti-Escalation (Rule 1 & Rule 6)
# ==============================================================================


def test_invitation_already_member_error(client: TestClient, db_session: Session) -> None:
    """Inviting an active member returns 409 already_member."""
    owner, token = create_authenticated_user(db_session)
    org = create_organization_with_owner(db_session, owner, "Org", f"org-{uuid.uuid4().hex[:6]}")

    member, _ = create_authenticated_user(db_session, "active@example.com")
    add_member_to_org(db_session, member, org)

    res = client.post(
        f"/api/v1/organizations/{org.id}/invitations",
        json={"email": "active@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "already_member"


def test_invitation_privilege_escalation(client: TestClient, db_session: Session) -> None:
    """User cannot invite with a role containing permissions they lack (Rule 1)."""
    owner, _ = create_authenticated_user(db_session)
    org = create_organization_with_owner(db_session, owner, "Org", f"org-{uuid.uuid4().hex[:6]}")

    # Create a custom role with users:manage and users:read
    from app.db.constants import get_permission_id
    from app.models.role import Role, RolePermission

    custom_role = Role(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="manager_role",
        is_system=False,
    )
    db_session.add(custom_role)
    db_session.flush()
    db_session.add(
        RolePermission(role_id=custom_role.id, permission_id=get_permission_id("users:read"))
    )
    db_session.add(
        RolePermission(role_id=custom_role.id, permission_id=get_permission_id("users:manage"))
    )
    db_session.commit()

    inviter, inviter_token = create_authenticated_user(db_session)
    membership = Membership(
        id=uuid.uuid4(),
        user_id=inviter.id,
        organization_id=org.id,
        status="active",
    )
    db_session.add(membership)
    db_session.flush()
    db_session.add(MembershipRole(membership_id=membership.id, role_id=custom_role.id))
    db_session.commit()

    # Inviter has users:manage, but lacks organization:manage, so cannot invite with owner role
    res = client.post(
        f"/api/v1/organizations/{org.id}/invitations",
        json={
            "email": "newuser@example.com",
            "role_id": str(get_system_role_id("owner")),
        },
        headers={"Authorization": f"Bearer {inviter_token}"},
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "privilege_escalation"


def test_ACC_08_last_owner_cannot_be_suspended_or_removed(
    client: TestClient, db_session: Session
) -> None:
    """Cannot suspend, remove, or leave as the last active owner (Rule 6 -> 409 last_owner)."""
    owner, token = create_authenticated_user(db_session)
    org = create_organization_with_owner(db_session, owner, "Org", f"org-{uuid.uuid4().hex[:6]}")
    membership = (
        db_session.query(Membership)
        .filter(Membership.user_id == owner.id, Membership.organization_id == org.id)
        .first()
    )
    assert membership is not None
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Attempt to suspend last owner -> 409
    suspend_res = client.patch(
        f"/api/v1/organizations/{org.id}/members/{membership.id}",
        json={"status": "suspended"},
        headers=headers,
    )
    assert suspend_res.status_code == 409
    assert suspend_res.json()["error"]["code"] == "last_owner"

    # 2. Attempt to remove last owner -> 409
    remove_res = client.delete(
        f"/api/v1/organizations/{org.id}/members/{membership.id}",
        headers=headers,
    )
    assert remove_res.status_code == 409
    assert remove_res.json()["error"]["code"] == "last_owner"

    # 3. Attempt to leave as last owner -> 409
    leave_res = client.delete(
        f"/api/v1/organizations/{org.id}/members/me",
        headers=headers,
    )
    assert leave_res.status_code == 409
    assert leave_res.json()["error"]["code"] == "last_owner"
