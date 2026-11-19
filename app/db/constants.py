import uuid

# Fixed namespace UUID for deterministic generation of system entities (uuid5)
PROJECT_NAMESPACE = uuid.UUID("7a5d1b71-3f62-4c6e-82d2-2c67676e1a44")


def get_permission_id(code: str) -> uuid.UUID:
    return uuid.uuid5(PROJECT_NAMESPACE, f"permission:{code}")


def get_system_role_id(name: str) -> uuid.UUID:
    return uuid.uuid5(PROJECT_NAMESPACE, f"role:{name}")


SYSTEM_PERMISSIONS: dict[str, str] = {
    "users:read": "Lire les utilisateurs et membres de l'organisation",
    "users:manage": "Gérer les membres et invitations de l'organisation",
    "roles:read": "Consulter les rôles et permissions de l'organisation",
    "roles:manage": "Créer, modifier ou attribuer des rôles",
    "audit:read": "Consulter les journaux d'audit de l'organisation",
    "organization:manage": "Modifier les paramètres de l'organisation",
    "projects:read": "Consulter les projets de l'organisation",
    "projects:create": "Créer un projet dans l'organisation",
    "projects:update": "Modifier un projet de l'organisation",
    "projects:delete": "Supprimer un projet de l'organisation",
}

SYSTEM_ROLES: dict[str, dict[str, object]] = {
    "owner": {
        "description": "Propriétaire de l'organisation avec tous les privilèges",
        "permissions": list(SYSTEM_PERMISSIONS.keys()),
    },
    "security_admin": {
        "description": "Administrateur sécurité : gestion des rôles, membres et audit",
        "permissions": [
            "users:read",
            "roles:read",
            "roles:manage",
            "audit:read",
            "projects:read",
        ],
    },
    "manager": {
        "description": "Gestionnaire des projets et consultation des membres",
        "permissions": [
            "users:read",
            "projects:read",
            "projects:create",
            "projects:update",
            "projects:delete",
        ],
    },
    "member": {
        "description": "Membre standard de l'organisation",
        "permissions": [
            "projects:read",
        ],
    },
}
