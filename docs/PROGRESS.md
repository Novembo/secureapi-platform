# Journal d'avancement — SecureAPI Platform

Ce document consigne l'avancement phase par phase du MVP selon la section 16 de `SPEC.md`.

---

## Phase 0 — Squelette et socle technique
- **Statut** : Terminé
- **Livrables validés** :
  - `pyproject.toml`, `uv.lock`
  - `app/core/*` (`config.py`, `clock.py`, `security.py`, `exceptions.py`, `logging.py`, `rate_limit.py`, `common_passwords.py`)
  - `app/db/*` (`base.py`, `session.py`)
  - `app/middleware/*` (`request_id.py`, `security_headers.py`, `body_limit.py`)
  - `app/main.py` avec endpoints `/health`, `/ready` et gestionnaires d'erreurs normalisés
  - `Makefile`, `.env.example`
  - ADR 0001 (`docs/decisions/0001-stack.md`)
  - Tests unitaires et d'intégration du socle (`app/tests/unit/*`)
- **Porte de validation** :
  - `ruff check .` : vert (0 erreur)
  - `ruff format --check .` : vert
  - `mypy` strict sur `app/` : vert (0 erreur sur 23 fichiers)
  - `pytest --cov=app` : 24 tests passés, couverture 90.13% (seuil requis >= 85%)
- **Décisions** : ADR 0001 validé.
- **Écarts** : Aucun.
- **Risques résiduels** : Aucun.

---

## Phase 1 — Modèles, contraintes, migrations et trigger d'audit
- **Statut** : Terminé
- **Livrables validés** :
  - `app/models/*` (`user.py`, `organization.py`, `membership.py`, `role.py`, `permission.py`, `refresh_session.py`, `audit_log.py`, `invitation.py`, `email_token.py`, `project.py`)
  - `app/db/constants.py` (définition des 10 permissions et 4 rôles système, calcul déterministe UUID5 via `PROJECT_NAMESPACE`)
  - `migrations/env.py`, `alembic.ini`, `migrations/script.py.mako`
  - Migration DDL initiale `0001_initial_schema.py` avec contraintes, clés étrangères, index et triggers d'immuabilité audit (PostgreSQL + SQLite)
  - Migration de seed `0002_seed_roles_permissions.py` (idempotente avec downgrade propre)
  - Tests d'intégrité de schéma et scénario ACC-10 (`app/tests/integration/test_database_integrity.py`)
- **Porte de validation** :
  - `alembic upgrade head` : exécuté avec succès
  - `alembic check` : vert ("No new upgrade operations detected", aucune dérive)
  - `alembic downgrade -1 && alembic upgrade head` : cycle complet validé
  - `mypy` strict : 0 erreur sur 37 fichiers
  - `pytest --cov=app` : 32 tests passés, couverture globale de 94.37% (dont test ACC-10 d'immuabilité d'audit)
- **Décisions** : Triggers d'immuabilité sur `audit_logs` appliqués en SQL dialectal pour supporter à la fois PostgreSQL (production) et SQLite (tests locaux).
- **Écarts** : Aucun.
- **Risques résiduels** : Aucun.

---

## Phase 2 — Authentification (AUTH-01 à AUTH-09)
- **Statut** : Terminé
- **Livrables validés** :
  - `app/schemas/auth.py` (schémas avec `extra="forbid"`)
  - `app/services/email_sender.py` (interface `EmailSender` + implémentation console)
  - `app/repositories/user_repo.py`, `refresh_session_repo.py`, `email_token_repo.py`
  - `app/services/auth_service.py` (register 202 uniforme, login avec dummy hash et lockout, refresh avec rotation et révocation de famille si réutilisation, logout, logout-all, verify-email, forgot-password 202 uniforme, reset-password invalidant toutes les sessions, me)
  - `app/services/audit_service.py` (service d'audit immuable avec masquage des adresses email et transaction dédiée pour les 403)
  - `app/dependencies/auth.py` (`get_current_user` validant JWT et état actif de la famille de session `sid`, `get_membership_context`, `require_permission`)
  - `app/api/v1/auth.py` (routes AUTH-01 à AUTH-09 avec rate limiting)
  - `app/tests/integration/test_auth.py` (scénarios ACC-02, ACC-03, ACC-11, ACC-12, ACC-13, verify-email)
- **Porte de validation** :
  - `ruff check .` : vert (0 erreur)
  - `ruff format --check .` : vert
  - `mypy` strict sur `app/` : vert (0 erreur sur 53 fichiers)
  - `pytest --cov=app` : 44 tests passés, couverture globale 91.81% (seuil requis >= 85%)
  - Scénarios d'acceptation ACC-02, ACC-03, ACC-11, ACC-12, ACC-13 tous au vert.
- **Décisions** :
  - En SQLite pour les tests, `ensure_utc` normalise les timestamps datetime retournés naïfs par le driver SQLite.
  - Réinitialisation automatique du stockage slowapi entre les tests dans `conftest.py` pour isoler les tests de verrouillage applicatif et de rate-limiting.
- **Écarts** : Aucun.
- **Risques résiduels** : Aucun.

---

## Phase 3 — Organisations, membres et invitations (ORG-01 à ORG-10)
- **Statut** : Terminé
- **Livrables validés** :
  - `app/schemas/organization.py` (schémas `OrganizationCreate`, `OrganizationUpdate`, `OrganizationOut`, `MemberOut`, `MemberStatusIn`, `InvitationCreate`, `InvitationOut`, `InvitationAcceptIn`, `OrganizationStatusIn`, `PaginatedResponse[T]`)
  - `app/repositories/organization_repo.py`, `membership_repo.py`, `invitation_repo.py`, `role_repo.py`
  - `app/services/organization_service.py` (création d'organisation avec attribution atomique du rôle `owner` au créateur, listing paginé pour membre ou PlatformAdmin, consultation sécurisée sans révélation d'existence, mise à jour, changement de statut PLT-01)
  - `app/services/member_service.py` (listing paginé des membres, invitations avec vérification anti-escalade règle 1, acceptation atomique avec verrouillage, mise à jour de statut avec protection dernier owner règle 6, exclusion et départ avec protection dernier owner)
  - `app/api/v1/organizations.py` (routes ORG-01 à ORG-04, PLT-01)
  - `app/api/v1/members.py` (routes ORG-05 à ORG-10)
  - `app/tests/integration/test_organizations.py` (scénarios ACC-05, ACC-06, ACC-09, ACC-14, cycle complet CRUD et règles 1 et 6)
- **Porte de validation** :
  - `ruff check .` : vert (0 erreur)
  - `ruff format --check .` : vert (0 fichier à reformater)
  - `mypy` strict sur `app/` : vert (0 erreur sur 63 fichiers)
  - `pytest --cov=app` : 53 tests passés, couverture globale 90.96% (seuil requis >= 85%)
  - Scénarios d'acceptation ACC-05 (perte immédiate d'accès pour membre suspendu ou ayant quitté), ACC-06 (protection IDOR 404), ACC-09 (consommation atomique d'invitation), ACC-14 (droits et frontières PlatformAdmin), règle 1 (anti-escalade sur invitation) et règle 6 (protection dernier owner actif) tous au vert.
- **Décisions** :
  - Utilisation de `StaticPool` pour l'engine de test SQLite afin de partager l'état en mémoire entre les sessions concurrentes/indépendantes comme `get_audit_session`.
  - La route statique `DELETE /organizations/{id}/members/me` est déclarée avant la route paramétrée `DELETE /organizations/{id}/members/{membership_id}` pour éviter les conflits de routage FastAPI.
- **Écarts** : Aucun.
- **Risques résiduels** : Aucun.

---

## Phase 4 — RBAC : rôles et permissions (ROLE-01 à ROLE-08)
- **Statut** : À venir
- **Livrables attendus** :
  - `app/schemas/role.py`
  - `app/services/role_service.py` (anti-escalade règles 1 à 7)
  - `app/api/v1/roles.py` (routes ROLE-01 à ROLE-08)
  - Scénarios d'acceptation ACC-04, ACC-07, ACC-08, ACC-17
- **Porte de validation** : ACC-04, ACC-07, ACC-08, ACC-17 verts ; couverture >= 90% sur services et dependencies.
- **Décisions** : À documenter.
- **Écarts** : Aucun.
- **Risques résiduels** : Aucun.

---
