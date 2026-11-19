from collections.abc import Sized

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db.constants import SYSTEM_PERMISSIONS, SYSTEM_ROLES, get_permission_id, get_system_role_id
from app.models.audit_log import AuditLog
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.permission import Permission
from app.models.project import Project
from app.models.role import Role
from app.models.user import User


def test_seed_permissions_and_system_roles_exist(db_session: Session) -> None:
    # 10 permissions exist with exact deterministic IDs
    for code, _ in SYSTEM_PERMISSIONS.items():
        expected_id = get_permission_id(code)
        perm = db_session.get(Permission, expected_id)
        assert perm is not None
        assert perm.code == code

    # 4 system roles exist
    for role_name, role_info in SYSTEM_ROLES.items():
        role_id = get_system_role_id(role_name)
        role = db_session.get(Role, role_id)
        assert role is not None
        assert role.name == role_name
        assert role.is_system is True
        assert role.organization_id is None
        perms = role_info["permissions"]
        assert isinstance(perms, Sized)
        assert len(role.permissions) == len(perms)


def test_unique_user_email_constraint(db_session: Session) -> None:
    u1 = User(
        email="test@example.com",
        password_hash="hash1",
        full_name="User One",
    )
    db_session.add(u1)
    db_session.commit()

    u2 = User(
        email="test@example.com",
        password_hash="hash2",
        full_name="User Two",
    )
    db_session.add(u2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unique_organization_slug_constraint(db_session: Session) -> None:
    org1 = Organization(name="Acme Corp", slug="acme")
    db_session.add(org1)
    db_session.commit()

    org2 = Organization(name="Acme Corporation", slug="acme")
    db_session.add(org2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unique_membership_user_organization(db_session: Session) -> None:
    user = User(email="member@example.com", password_hash="h", full_name="Member")
    org = Organization(name="Org One", slug="org-one")
    db_session.add_all([user, org])
    db_session.commit()

    m1 = Membership(user_id=user.id, organization_id=org.id)
    db_session.add(m1)
    db_session.commit()

    m2 = Membership(user_id=user.id, organization_id=org.id)
    db_session.add(m2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unique_custom_role_name_per_organization(db_session: Session) -> None:
    org = Organization(name="Role Org", slug="role-org")
    db_session.add(org)
    db_session.commit()

    r1 = Role(organization_id=org.id, name="CustomReviewer", is_system=False)
    db_session.add(r1)
    db_session.commit()

    r2 = Role(organization_id=org.id, name="CustomReviewer", is_system=False)
    db_session.add(r2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_foreign_key_cascade_organization_deletion(db_session: Session) -> None:
    user = User(email="owner@example.com", password_hash="h", full_name="Owner")
    org = Organization(name="Cascade Org", slug="cascade-org")
    db_session.add_all([user, org])
    db_session.commit()

    membership = Membership(user_id=user.id, organization_id=org.id)
    proj = Project(organization_id=org.id, name="Project 1", created_by_id=user.id)
    db_session.add_all([membership, proj])
    db_session.commit()

    # Deleting organization cascades to projects and memberships
    db_session.delete(org)
    db_session.commit()

    assert db_session.get(Project, proj.id) is None
    assert db_session.get(Membership, membership.id) is None


def test_foreign_key_restrict_on_role_deletion_with_memberships(db_session: Session) -> None:
    user = User(email="roleuser@example.com", password_hash="h", full_name="Role User")
    org = Organization(name="Role Org 2", slug="role-org-2")
    db_session.add_all([user, org])
    db_session.commit()

    custom_role = Role(organization_id=org.id, name="Editor", is_system=False)
    membership = Membership(user_id=user.id, organization_id=org.id)
    db_session.add_all([custom_role, membership])
    db_session.commit()

    membership_role = MembershipRole(membership_id=membership.id, role_id=custom_role.id)
    db_session.add(membership_role)
    db_session.commit()

    # Attempting to delete custom_role should fail due to RESTRICT on membership_roles
    db_session.delete(custom_role)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.security
def test_acc_10_audit_log_immutability(db_session: Session) -> None:
    """ACC-10: UPDATE et DELETE SQL sur audit_logs sont rejetés par la base de données."""
    audit = AuditLog(
        action="test.immutable",
        resource_type="system",
        resource_id=None,
        metadata_={"key": "original"},
    )
    db_session.add(audit)
    db_session.commit()
    audit_id = audit.id

    # Test that UPDATE is rejected by DB trigger
    with pytest.raises((IntegrityError, DBAPIError)):
        db_session.execute(
            text("UPDATE audit_logs SET action = 'tampered' WHERE id = :id"),
            {"id": audit_id},
        )
        db_session.commit()
    db_session.rollback()

    # Test that DELETE is rejected by DB trigger
    with pytest.raises((IntegrityError, DBAPIError)):
        db_session.execute(
            text("DELETE FROM audit_logs WHERE id = :id"),
            {"id": audit_id},
        )
        db_session.commit()
    db_session.rollback()

    # Ensure record remains unchanged and intact
    saved = db_session.get(AuditLog, audit_id)
    assert saved is not None
    assert saved.action == "test.immutable"
