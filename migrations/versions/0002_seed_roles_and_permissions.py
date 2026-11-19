"""Seed system permissions and roles with deterministic UUIDs

Revision ID: 0002_seed_roles_permissions
Revises: 0001_initial_schema
Create Date: 2026-11-18 01:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.constants import SYSTEM_PERMISSIONS, SYSTEM_ROLES, get_permission_id, get_system_role_id

revision: str = "0002_seed_roles_permissions"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Insert permissions
    permissions_table = sa.table(
        "permissions",
        sa.column("id", sa.Uuid),
        sa.column("code", sa.String),
        sa.column("description", sa.Text),
    )
    perm_rows = [
        {
            "id": get_permission_id(code),
            "code": code,
            "description": desc,
        }
        for code, desc in SYSTEM_PERMISSIONS.items()
    ]
    op.bulk_insert(permissions_table, perm_rows)

    # 2. Insert system roles (organization_id IS NULL, is_system = True)
    roles_table = sa.table(
        "roles",
        sa.column("id", sa.Uuid),
        sa.column("organization_id", sa.Uuid),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_system", sa.Boolean),
    )
    role_rows = [
        {
            "id": get_system_role_id(name),
            "organization_id": None,
            "name": name,
            "description": str(role_info["description"]),
            "is_system": True,
        }
        for name, role_info in SYSTEM_ROLES.items()
    ]
    op.bulk_insert(roles_table, role_rows)

    # 3. Insert role_permissions
    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Uuid),
        sa.column("permission_id", sa.Uuid),
    )
    rp_rows = []
    for role_name, role_info in SYSTEM_ROLES.items():
        role_id = get_system_role_id(role_name)
        perms = role_info["permissions"]
        if isinstance(perms, list):
            for code in perms:
                rp_rows.append(
                    {
                        "role_id": role_id,
                        "permission_id": get_permission_id(str(code)),
                    }
                )
    op.bulk_insert(role_permissions_table, rp_rows)


def downgrade() -> None:
    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Uuid),
        sa.column("permission_id", sa.Uuid),
    )
    roles_table = sa.table(
        "roles",
        sa.column("id", sa.Uuid),
        sa.column("name", sa.String),
    )
    permissions_table = sa.table(
        "permissions",
        sa.column("id", sa.Uuid),
        sa.column("code", sa.String),
    )

    role_ids = [get_system_role_id(name) for name in SYSTEM_ROLES]

    op.execute(
        role_permissions_table.delete().where(role_permissions_table.c.role_id.in_(role_ids))
    )
    op.execute(roles_table.delete().where(roles_table.c.name.in_(list(SYSTEM_ROLES.keys()))))
    op.execute(
        permissions_table.delete().where(
            permissions_table.c.code.in_(list(SYSTEM_PERMISSIONS.keys()))
        )
    )
