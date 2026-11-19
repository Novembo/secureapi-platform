"""Repository for Role and Permission database operations."""

from __future__ import annotations

import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.models.membership import MembershipRole
from app.models.permission import Permission
from app.models.role import Role, RolePermission


class RoleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, role_id: uuid.UUID) -> Role | None:
        return (
            self.db.query(Role)
            .options(selectinload(Role.permissions))
            .filter(Role.id == role_id)
            .first()
        )

    def get_by_id_and_org(self, role_id: uuid.UUID, org_id: uuid.UUID) -> Role | None:
        """Finds a role accessible within an org (system role or custom org role)."""
        return (
            self.db.query(Role)
            .options(selectinload(Role.permissions))
            .filter(
                Role.id == role_id,
                (Role.organization_id == org_id) | (Role.organization_id.is_(None)),
            )
            .first()
        )

    def get_by_name_and_org(self, name: str, org_id: uuid.UUID) -> Role | None:
        return (
            self.db.query(Role)
            .filter(
                func.lower(Role.name) == name.lower(),
                Role.organization_id == org_id,
            )
            .first()
        )

    def create(self, name: str, description: str | None, organization_id: uuid.UUID) -> Role:
        role = Role(
            id=uuid.uuid4(),
            organization_id=organization_id,
            name=name,
            description=description,
            is_system=False,
        )
        self.db.add(role)
        self.db.flush()
        return role

    def update(self, role: Role, name: str | None, description: str | None) -> Role:
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        self.db.flush()
        return role

    def delete(self, role: Role) -> None:
        self.db.delete(role)
        self.db.flush()

    def list_roles_for_org(self, org_id: uuid.UUID) -> list[Role]:
        """Returns all system roles plus custom roles belonging to this organization."""
        return list(
            self.db.query(Role)
            .options(selectinload(Role.permissions))
            .filter((Role.organization_id == org_id) | (Role.organization_id.is_(None)))
            .order_by(Role.is_system.desc(), Role.name.asc())
            .all()
        )

    def count_members_with_role(self, role_id: uuid.UUID) -> int:
        return self.db.query(MembershipRole).filter(MembershipRole.role_id == role_id).count()

    def set_role_permissions(self, role_id: uuid.UUID, permission_ids: list[uuid.UUID]) -> None:
        # Delete existing permissions
        self.db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
        # Add new
        for perm_id in permission_ids:
            self.db.add(RolePermission(role_id=role_id, permission_id=perm_id))
        self.db.flush()

    def get_permission_by_code(self, code: str) -> Permission | None:
        return self.db.query(Permission).filter(Permission.code == code).first()

    def list_all_permissions(self) -> list[Permission]:
        return list(self.db.query(Permission).order_by(Permission.code.asc()).all())
