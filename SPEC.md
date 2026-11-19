# SecureAPI Platform — Spécification du MVP

> **Destinataire : agent de code.** Ce document est la source de vérité du projet. Lis-le en entier avant d'écrire du code, exécute les phases de la section 16 dans l'ordre, et ne passe à la phase suivante que lorsque sa porte de validation est verte. Les annexes A à G contiennent des squelettes de fichiers prêts à adapter.
>
> Place ce fichier à la racine du dépôt sous le nom `SPEC.md`. Le `README.md` public du projet est un livrable distinct, rédigé en phase 9.

**Sommaire** — 0 Mode d'emploi · 1 Mission et définition du MVP · 2 Règles non négociables · 3 Décisions techniques · 4 Arborescence · 5 Écarts assumés · 6 Modèle de données · 7 Permissions, rôles, anti-escalade · 8 Dépendances d'autorisation · 9 Contrats d'API · 10 Sécurité et configuration · 11 Transactions et concurrence · 12 Erreurs · 13 Tests · 14 Docker et CI/CD · 15 Documentation · 16 Plan d'exécution · 17 Porte de release du MVP · 18 Commandes · 19 Post-MVP et hors périmètre · Annexes A–G

---

## 0. Mode d'emploi pour l'agent

**Prompt de lancement type :**

```
Lis SPEC.md en entier. Implémente le MVP (phases 0 à 9) en suivant la section 16.
Après chaque phase : lance la porte de validation, commit, mets à jour docs/PROGRESS.md.
Arrête-toi à la porte de release (section 17) et fais-en le compte rendu.
N'implémente rien du post-MVP (section 19) sans instruction explicite.
```

**Ordre de priorité en cas de conflit** : sécurité > correction fonctionnelle > tests > lisibilité > rapidité.

**Boucle de travail, pour chaque phase :**

1. Relis la phase (section 16) et les sections qu'elle référence.
2. Écris les tests décrits en même temps que le code (ou avant).
3. Lance la porte de validation (`make check` + tests ciblés).
4. Commit atomique (Conventional Commits), puis mise à jour de `docs/PROGRESS.md` : fait, décisions (avec lien ADR), écarts, risques résiduels.

**Conditions d'arrêt — stoppe et signale le problème plutôt que de deviner si :**

- deux règles de sécurité de ce document se contredisent ;
- une porte de validation reste rouge après trois tentatives de correction ;
- une dépendance requise est indisponible ou a une vulnérabilité connue sans correctif.

**Interdits :** affaiblir un test pour le faire passer, désactiver une règle Ruff/mypy sans justification écrite, committer un secret, ajouter une fonctionnalité hors périmètre.

---

## 1. Mission et définition du MVP

Construire une API REST permettant aux PME de gérer utilisateurs, organisations, rôles, permissions et accès aux ressources, avec :

- **isolation stricte** des données entre organisations ;
- **traçabilité** des actions sensibles (audit immuable) ;
- **révocation des sessions** (refresh tokens rotatifs, logout, logout-all) ;
- **séparation nette** des privilèges plateforme et organisation.

Pièce de portfolio : qualité, lisibilité, tests et documentation comptent autant que les fonctionnalités. Ne jamais présenter le projet comme « certifié » ou « invulnérable ».

### Périmètre du MVP

| Inclus dans le MVP (obligatoire) | Reporté après le MVP (section 19) |
|---|---|
| Authentification complète (9 endpoints) | Collection Postman |
| Organisations, membres, invitations | Démo hébergée publique et job `deploy` |
| RBAC, rôles personnalisés, anti-escalade | Script de purge de rétention + rôle DB dédié |
| Projets (ressource de démonstration) | Diagramme de classes UML |
| Audit immuable (organisation + plateforme) | MFA, SSO, SMTP réel |
| Rate limiting, verrouillage, en-têtes de sécurité | |
| Tests (unitaires, intégration, sécurité, concurrence) | |
| Docker, Compose, CI complète (6 jobs) | |
| Seed de démonstration + script de démo | |
| Docs : README, ERD, modèle de menace, OWASP, déploiement | |

**Critère d'acceptation global du MVP :** un développeur clone le dépôt, exécute `cp .env.example .env`, renseigne les secrets, lance `docker compose up`, puis `make seed && make demo`, et le scénario de la section 15 passe (accès autorisé, 403, 404) avec une CI verte.

**Acteurs :** `PlatformAdmin` (niveau plateforme) ; `OrganizationOwner`, `SecurityAdmin`, `Manager`, `Member` (niveau organisation, via les rôles de la section 7).

---

## 2. Règles non négociables

1. Aucune logique métier dans les routes : routes → services → repositories/modèles.
2. Toute opération multi-modèles s'exécute dans **une seule transaction** (section 11).
3. Chaque endpoint protégé vérifie **à la fois** l'authentification, l'appartenance à l'organisation **et** la permission requise, côté serveur.
4. Jamais de mot de passe, token, secret ou JWT complet en clair : ni en base, ni dans les logs, ni dans l'audit.
5. Les permissions sont résolues depuis la base à chaque requête, jamais lues dans le JWT.
6. Réponses d'erreur cohérentes (section 12) et documentées dans OpenAPI.
7. Secrets uniquement via variables d'environnement ; `.env.example` fourni (sans secret réel), `.env` ignoré par Git.
8. Chaque phase se termine par `make check` vert, puis un commit atomique.
9. Si le cahier est ambigu, choisis l'option la plus sûre et consigne-la dans `docs/decisions/` (ADR court : contexte, décision, conséquences).
10. Aucune fonctionnalité hors périmètre.
11. **Horloge injectable** : tout accès à l'heure passe par `app/core/clock.py` (surchargeable en test) ; jamais de `datetime.now()` direct dans les services.
12. **Pas d'assignation de masse** : les schémas d'entrée déclarent explicitement leurs champs (`extra="forbid"`) ; jamais de `**payload` vers un modèle ORM.

---

## 3. Décisions techniques

| Domaine | Choix |
|---|---|
| Langage / framework | Python ≥ 3.12, FastAPI, Pydantic v2, pydantic-settings, `email-validator` |
| ORM / migrations | SQLAlchemy 2 (style 2.0, typé), Alembic |
| Exécution | **Synchrone** (SQLAlchemy sync, routes `def`) : transactions et verrous plus simples à raisonner et à tester ; ADR obligatoire |
| Base de données | PostgreSQL 16, driver `psycopg` v3 |
| JWT | PyJWT, HS256, secret ≥ 32 octets, `algorithms=["HS256"]` fixé côté serveur, `require` sur les claims obligatoires |
| Durées | access token 15 min, refresh token 7 jours |
| Mots de passe | Argon2id (`argon2-cffi`), paramètres pilotés par la config (valeurs allégées en test) |
| Rate limiting | `slowapi`, stockage mémoire (limite documentée : non partagé entre instances) |
| Tests | pytest, `TestClient`/HTTPX, pytest-cov, factories maison déterministes |
| Qualité | Ruff (lint + format), mypy strict sur `app/` |
| Sécurité CI | `pip-audit`, Bandit, Trivy |
| Infra | Docker multi-stage, Docker Compose, GitHub Actions |
| Dépendances | `uv` avec `uv.lock` (ou `pip-tools`) |

**Épinglage** : installe les dernières versions stables, épingle-les exactement dans le fichier de verrouillage, et consigne-les avec la justification des choix majeurs dans `docs/decisions/0001-stack.md`. Les versions d'images Docker et d'actions GitHub sont épinglées aussi (version exacte ou digest).

---

## 4. Arborescence cible

```
.
├── SPEC.md
├── app/
│   ├── main.py                 # app, routers, middlewares, handlers d'erreurs
│   ├── core/                   # config, clock, sécurité (hash, JWT), exceptions, logging, rate limit
│   ├── db/                     # engine, sessions, Base, conventions de nommage
│   ├── models/
│   ├── schemas/                # création / mise à jour / lecture séparés
│   ├── api/v1/                 # auth, organizations, members, invitations, roles,
│   │                           #   permissions, projects, audit, platform, system
│   ├── services/
│   ├── repositories/
│   ├── dependencies/
│   ├── middleware/             # correlation ID, en-têtes, limite de taille, IP client
│   └── tests/{unit,integration,security,factories}/
├── migrations/                 # Alembic (dont la migration de seed des rôles/permissions)
├── scripts/                    # create_platform_admin.py, seed_demo.py, demo_scenario.sh
├── docs/
│   ├── PROGRESS.md
│   ├── architecture.md
│   ├── threat-model.md
│   ├── owasp-api-top10.md
│   ├── deployment.md
│   └── decisions/
├── .github/workflows/ci.yml
├── Dockerfile  docker-compose.yml  Makefile  alembic.ini
├── .env.example  pyproject.toml  uv.lock
└── README.md                   # README public (phase 9)
```

---

## 5. Écarts assumés par rapport au cahier des charges initial

Documente-les dans un ADR : ils sont nécessaires pour tenir les exigences de sécurité du cahier.

| Ajout | Raison |
|---|---|
| `User.is_platform_admin` (bool, défaut `false`) | Séparer privilèges plateforme et organisation. **Jamais attribuable via l'API** ; uniquement via `scripts/create_platform_admin.py`. |
| `User.failed_login_attempts`, `User.locked_until` | Verrouillage anti brute force / credential stuffing. |
| `RefreshSession.family_id` | Révoquer toute la famille en cas de réutilisation ; sert de `sid` dans l'access token. |
| Table `EmailToken` | Vérification d'email et reset de mot de passe à usage unique. |
| `Membership.status` ∈ {`active`, `suspended`, `left`} | Suspension et départ. |
| `Invitation.role_id` (nullable, défaut = rôle `member`) | Rôle attribué à l'acceptation. |
| `AuditLog.request_id` | Corréler audit et logs. |
| `GET /platform/audit-logs` | Les événements sans organisation (connexions, échecs) restent consultables. |
| `PUT /platform/organizations/{id}/status` | Activation/désactivation réservée au PlatformAdmin, séparée du `PATCH` d'organisation (évite l'assignation de masse sur `is_active`). |
| `GET /health` et `GET /ready` | Liveness (sans DB) et readiness (ping DB). |
| Interface `EmailSender`, backend « console » | Pas de SMTP réel ; emails écrits dans les logs en dev/test uniquement. Jamais de token valide dans les logs de production. |

---

## 6. Modèle de données

**Conventions :** clés primaires UUID v4 (sauf données de seed : section 6.1), `created_at`/`updated_at` en `timestamptz` UTC, conventions de nommage Alembic pour contraintes et index, emails stockés en minuscules.

| Table | Colonnes principales | Contraintes / index |
|---|---|---|
| `users` | id, email, password_hash, full_name, is_active, is_verified, is_platform_admin, failed_login_attempts, locked_until, created_at, updated_at | `UNIQUE(email)` |
| `organizations` | id, name, slug, is_active, created_at | `UNIQUE(slug)` ; slug `^[a-z0-9][a-z0-9-]{1,62}$` |
| `memberships` | id, user_id, organization_id, status, joined_at | `UNIQUE(user_id, organization_id)` ; FK `CASCADE` ; index `(organization_id, status)` |
| `roles` | id, organization_id (nullable), name, description, is_system | `UNIQUE(organization_id, name)` + index unique partiel sur `name` où `organization_id IS NULL` |
| `permissions` | id, code, description | `UNIQUE(code)` |
| `role_permissions` | role_id, permission_id | PK composite ; FK `CASCADE` |
| `membership_roles` | membership_id, role_id | PK composite ; `CASCADE` côté membership, `RESTRICT` côté role |
| `refresh_sessions` | id, user_id, family_id, token_hash, expires_at, revoked_at, created_at, replaced_by_id, device_metadata (JSONB) | `UNIQUE(token_hash)` ; index `(user_id)`, `(family_id)` |
| `audit_logs` | id, organization_id (nullable), actor_id (nullable), action, resource_type, resource_id, metadata (JSONB), ip_address, request_id, created_at | index `(organization_id, created_at DESC)`, `(actor_id)`, `(action)` ; FK `actor_id` `SET NULL` |
| `invitations` | id, organization_id, email, role_id, token_hash, expires_at, accepted_at, invited_by_id | `UNIQUE(token_hash)` ; index `(organization_id, email)` |
| `email_tokens` | id, user_id, purpose ∈ {`verify_email`, `reset_password`}, token_hash, expires_at, used_at, created_at | `UNIQUE(token_hash)` ; index `(user_id, purpose)` |
| `projects` | id, organization_id, name, description, created_by_id, created_at, updated_at | index `(organization_id, created_at DESC)` ; FK `organization_id` `CASCADE` |

**Tokens :** `secrets.token_urlsafe(48)`, stockés en SHA-256 hexadécimal (entropie élevée : un hash rapide suffit). Argon2id est réservé aux mots de passe.

**Suppressions :** une organisation est désactivée, jamais supprimée. Les suppressions physiques relèvent de la politique de rétention (section 19).

**Audit immuable :** la migration crée un trigger PostgreSQL qui lève une exception sur `UPDATE` et `DELETE` de `audit_logs`.

**Politique de rétention (à documenter dans `docs/deployment.md`, script reporté en post-MVP) :** audit 365 jours ; sessions expirées/révoquées, invitations et email tokens expirés 30 jours.

### 6.1 Seed des rôles et permissions

Migration de données dédiée, **idempotente**, avec des UUID **déterministes** (`uuid5` d'un namespace fixe du projet appliqué au code de la permission ou au nom du rôle) pour que les identifiants soient stables entre environnements et utilisables dans les tests.

---

## 7. Permissions, rôles et anti-escalade

### Permissions

`users:read`, `users:manage`, `roles:read`, `roles:manage`, `audit:read`, `organization:manage`, `projects:read`, `projects:create`, `projects:update`, `projects:delete`.

### Rôles système (`is_system=true`, immuables)

| Rôle | Permissions |
|---|---|
| `owner` | toutes |
| `security_admin` | `users:read`, `roles:read`, `roles:manage`, `audit:read`, `projects:read` |
| `manager` | `users:read`, `projects:read`, `projects:create`, `projects:update`, `projects:delete` |
| `member` | `projects:read` |

Le créateur d'une organisation reçoit `owner`. Les rôles système sont globaux ; les rôles personnalisés appartiennent à une organisation.

### PlatformAdmin

Peut lister et consulter toutes les organisations, changer leur statut, et lire `/platform/audit-logs`. Il **ne contourne pas** les contrôles d'appartenance et de permission sur les données internes d'une organisation (projets, membres, rôles, audit d'organisation). Toute action plateforme est auditée.

### Règles anti-escalade (à implémenter dans `services/`, un test par règle)

1. Un acteur ne peut accorder (à un rôle) ou attribuer (à un membre) que des permissions qu'il **détient lui-même** dans cette organisation.
2. Un acteur ne peut pas modifier ses propres rôles.
3. Seul un `owner` peut attribuer ou retirer le rôle `owner`.
4. Les rôles système ne peuvent être ni modifiés, ni supprimés, ni voir leurs permissions changées.
5. Un rôle encore attribué à des membres ne peut pas être supprimé (409).
6. Impossible de retirer le rôle `owner`, suspendre ou faire quitter le **dernier owner actif** (409). Le « transfert » = attribuer `owner` à un autre membre actif *avant* de retirer le premier.
7. Un rôle personnalisé de l'organisation A ne peut jamais être attribué dans l'organisation B.

---

## 8. Dépendances FastAPI d'autorisation

- **`get_current_user`** : valide signature, `exp`, `iss`, `aud`, `type == "access"`, utilisateur actif, et que la session `sid` (= `family_id`) est active (au moins une ligne non révoquée et non expirée dans la famille). `logout` et `logout-all` deviennent ainsi effectifs immédiatement.
- **`get_membership_context(organization_id)`** : charge le membership `active` ; absent → **404** (ne pas révéler l'existence de l'organisation). Organisation inactive → 403. Retourne un contexte avec les permissions effectives (union des rôles) chargées depuis la base.
- **`require_permission("code")`** : s'appuie sur le contexte ; absence → 403 et entrée d'audit.
- **Ressources** (`project_id`, `membership_id`, `role_id`) : toujours chargées **avec** le filtre `organization_id`. UUID d'une autre organisation → 404 (IDOR).

```python
def require_permission(code: str):
    def checker(ctx: MembershipContext = Depends(get_membership_context)) -> MembershipContext:
        if code not in ctx.permissions:
            audit.record_denied(ctx, permission=code)  # transaction indépendante du 403
            raise PermissionDenied(code)
        return ctx

    return checker
```

---

## 9. Contrats d'API

Préfixe `/api/v1` (sauf `/health` et `/ready`, à la racine). Conventions :

- Corps validés par Pydantic, `extra="forbid"`.
- Listes paginées : `limit` (1–100, défaut 20), `offset` (≥ 0), tri explicite, filtres en liste blanche. Réponse : `{"items": [...], "total": n, "limit": n, "offset": n}`.
- Toute erreur suit la section 12. Les erreurs listées ci-dessous s'ajoutent à 401/403/404/422/429 communs.

### 9.1 Catalogue des endpoints

Colonnes : **Accès** = authentification et permission requises ; **Audit** = action journalisée (section 9.3).

| ID | Endpoint | Accès | Succès | Erreurs spécifiques | Audit |
|---|---|---|---|---|---|
| SYS-01 | `GET /health` | public | 200 | — | — |
| SYS-02 | `GET /ready` | public | 200 | 503 si DB injoignable | — |
| AUTH-01 | `POST /auth/register` | public | 202 | 422 mot de passe refusé | `user.registered` |
| AUTH-02 | `POST /auth/login` | public | 200 | 401 `invalid_credentials` ; 403 `email_not_verified` (seulement après mot de passe correct) | `auth.login_success`, `auth.login_failed`, `auth.account_locked` |
| AUTH-03 | `POST /auth/refresh` | public (token en corps) | 200 | 401 `token_invalid` | `auth.refresh_reuse_detected` |
| AUTH-04 | `POST /auth/logout` | authentifié | 204 | — | `auth.logout` |
| AUTH-05 | `POST /auth/logout-all` | authentifié | 204 | — | `auth.logout_all` |
| AUTH-06 | `POST /auth/verify-email` | public | 204 | 400 `token_invalid` | `auth.email_verified` |
| AUTH-07 | `POST /auth/forgot-password` | public | 202 | — | `auth.password_reset_requested` |
| AUTH-08 | `POST /auth/reset-password` | public | 204 | 400 `token_invalid` ; 422 mot de passe refusé | `auth.password_reset` |
| AUTH-09 | `GET /auth/me` | authentifié | 200 | — | — |
| ORG-01 | `POST /organizations` | authentifié et vérifié | 201 | 409 `slug_taken` | `organization.created` |
| ORG-02 | `GET /organizations` | authentifié (membre actif ; PlatformAdmin : toutes) | 200 | — | — |
| ORG-03 | `GET /organizations/{id}` | membre actif ou PlatformAdmin | 200 | — | — |
| ORG-04 | `PATCH /organizations/{id}` | `organization:manage` | 200 | 409 `slug_taken` | `organization.updated` |
| ORG-05 | `GET /organizations/{id}/members` | `users:read` | 200 | — | — |
| ORG-06 | `POST /organizations/{id}/invitations` | `users:manage` | 201 | 403 `privilege_escalation` ; 409 `already_member` | `invitation.created` |
| ORG-07 | `POST /invitations/accept` | authentifié et vérifié | 200 | 400 `invitation_invalid` | `invitation.accepted` |
| ORG-08 | `PATCH /organizations/{id}/members/{membership_id}` | `users:manage` | 200 | 409 `last_owner` | `member.status_changed` |
| ORG-09 | `DELETE /organizations/{id}/members/{membership_id}` | `users:manage` | 204 | 409 `last_owner` | `member.removed` |
| ORG-10 | `DELETE /organizations/{id}/members/me` | membre actif | 204 | 409 `last_owner` | `member.left` |
| ROLE-01 | `GET /permissions` | authentifié | 200 | — | — |
| ROLE-02 | `GET /organizations/{id}/roles` | `roles:read` | 200 | — | — |
| ROLE-03 | `POST /organizations/{id}/roles` | `roles:manage` | 201 | 409 `role_name_taken` | `role.created` |
| ROLE-04 | `GET /organizations/{id}/roles/{role_id}` | `roles:read` | 200 | — | — |
| ROLE-05 | `PATCH /organizations/{id}/roles/{role_id}` | `roles:manage` | 200 | 409 `system_role_immutable`, `role_name_taken` | `role.updated` |
| ROLE-06 | `DELETE /organizations/{id}/roles/{role_id}` | `roles:manage` | 204 | 409 `system_role_immutable`, `role_in_use` | `role.deleted` |
| ROLE-07 | `PUT /organizations/{id}/roles/{role_id}/permissions` | `roles:manage` | 200 | 403 `privilege_escalation` ; 409 `system_role_immutable` | `role.permissions_changed` |
| ROLE-08 | `PUT /organizations/{id}/members/{membership_id}/roles` | `roles:manage` | 200 | 403 `privilege_escalation` ; 409 `last_owner` | `member.roles_changed` |
| PRJ-01 | `GET /organizations/{id}/projects` | `projects:read` | 200 | — | — |
| PRJ-02 | `POST /organizations/{id}/projects` | `projects:create` | 201 | — | `project.created` |
| PRJ-03 | `GET /organizations/{id}/projects/{project_id}` | `projects:read` | 200 | — | — |
| PRJ-04 | `PATCH /organizations/{id}/projects/{project_id}` | `projects:update` | 200 | — | `project.updated` |
| PRJ-05 | `DELETE /organizations/{id}/projects/{project_id}` | `projects:delete` | 204 | — | `project.deleted` |
| AUD-01 | `GET /organizations/{id}/audit-logs` | `audit:read` | 200 | 422 filtres invalides | — |
| AUD-02 | `GET /platform/audit-logs` | PlatformAdmin | 200 | 422 filtres invalides | — |
| PLT-01 | `PUT /platform/organizations/{id}/status` | PlatformAdmin | 200 | — | `platform.organization_status_changed` |

Tout `403` sur une opération sensible journalise `access.denied`.

### 9.2 Schémas clés (noms indicatifs, champs exacts)

| Schéma | Champs |
|---|---|
| `RegisterIn` | `email`, `password`, `full_name` |
| `LoginIn` / `TokenOut` | `email`, `password` / `access_token`, `refresh_token`, `token_type="bearer"`, `expires_in` |
| `RefreshIn`, `VerifyEmailIn`, `ForgotPasswordIn`, `ResetPasswordIn` | `refresh_token` ; `token` ; `email` ; `token`, `new_password` |
| `MeOut` | `id`, `email`, `full_name`, `is_verified`, `memberships[]` (`organization_id`, `organization_slug`, `roles[]`, `permissions[]`) |
| `OrganizationCreate` / `Update` / `Out` | `name`, `slug` / `name?` (le slug n'est pas modifiable) / `id`, `name`, `slug`, `is_active`, `created_at` |
| `InvitationCreate` | `email`, `role_id?` |
| `InvitationAcceptIn` | `token` |
| `MemberOut` | `membership_id`, `user_id`, `email`, `full_name`, `status`, `roles[]`, `joined_at` |
| `MemberStatusIn` | `status` ∈ {`active`, `suspended`} |
| `RoleCreate` / `Update` / `Out` | `name`, `description` / idem, optionnels / `id`, `name`, `description`, `is_system`, `permission_codes[]` |
| `RolePermissionsIn` / `MemberRolesIn` | `permission_codes[]` / `role_ids[]` |
| `ProjectCreate` / `Update` / `Out` | `name`, `description?` / idem, optionnels / `id`, `organization_id`, `name`, `description`, `created_by_id`, `created_at`, `updated_at` |
| `AuditLogOut` | `id`, `organization_id`, `actor_id`, `action`, `resource_type`, `resource_id`, `metadata`, `ip_address`, `request_id`, `created_at` |
| `OrganizationStatusIn` | `is_active` |

### 9.3 Règles par endpoint

**Authentification**

- **Mot de passe** : 12–128 caractères, refus s'il figure dans une liste de mots de passe courants embarquée dans le dépôt (≥ 1 000 entrées) ou s'il contient la partie locale de l'email. Pas de règles de composition arbitraires.
- **Register** : réponse **202 identique** que l'email existe ou non (corps et statut). Un email déjà utilisé déclenche un message « compte existant » vers l'adresse, via `EmailSender`, sans changer la réponse HTTP.
- **Login** : erreur unique `invalid_credentials` (mauvais email, mauvais mot de passe, compte verrouillé, compte inactif). Hash factice si l'utilisateur n'existe pas (temps de réponse comparable). Verrouillage après `LOGIN_MAX_ATTEMPTS` échecs pour `LOGIN_LOCK_MINUTES` ; remise à zéro du compteur au succès. `email_not_verified` n'est renvoyé qu'après un mot de passe correct, si `REQUIRE_VERIFIED_EMAIL=true`.
- **Refresh** : rotation (ancien token révoqué, `replaced_by_id` renseigné, même `family_id`). **Réutilisation d'un token déjà remplacé = toute la famille révoquée**, audit, 401.
- **Forgot-password** : 202 identique que le compte existe ou non ; token à usage unique valable 1 h.
- **Reset-password** : consomme le token, applique la politique, **révoque toutes les sessions**.
- **Verify-email** : token à usage unique valable 24 h.
- **JWT access** : claims `iss`, `aud`, `sub`, `sid`, `iat`, `exp`, `jti`, `type="access"`. Aucune permission dans le token.

**Organisations et membres**

- **ORG-01** : le créateur devient `owner` dans la même transaction. Limité en débit.
- **ORG-06** : token hashé, expiration 7 jours ; le rôle invité (défaut `member`) est soumis à la règle anti-escalade 1 ; refus si l'email est déjà membre actif.
- **ORG-07** : l'email de l'utilisateur authentifié doit correspondre à celui de l'invitation. Toute raison d'échec (token inconnu, expiré, déjà utilisé, mauvais email) renvoie le même `invitation_invalid`. Création du membership et du rôle dans **une transaction**.
- **ORG-08/09/10** : règle 6 (dernier owner). Un membre suspendu perd immédiatement tout accès.

**Rôles**

- **ROLE-07/08** : remplacent l'ensemble. Appliquer les règles 1 à 4 et 7 de la section 7 avant tout changement, de façon atomique.

**Projets**

- `created_by_id` fixé côté serveur. Appartenance et permission vérifiées simultanément.

**Audit**

- Journalisation en énumération fermée (les actions du catalogue ci-dessus). Aucun secret, token ou mot de passe ; emails masqués (`o***@example.com`) ; `ip_address` et `request_id` renseignés.
- Les événements sans organisation (connexions, échecs, verrouillages, reset) ont `organization_id = NULL` et ne sont visibles que via **AUD-02**.

---

## 10. Sécurité transverse et configuration

- **Correlation ID** : `X-Request-ID` (généré si absent, validé : longueur et caractères), propagé dans les logs JSON structurés et l'audit.
- **IP client** : `X-Forwarded-For` n'est lue que si l'adresse directe appartient à `TRUSTED_PROXIES` ; sinon, utiliser l'adresse de la connexion. Rate limiting et audit utilisent cette IP.
- **En-têtes** : `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Strict-Transport-Security` (hors dev), `Cache-Control: no-store` sur `/auth/*`.
- **CORS** strict : origines explicites par configuration, jamais `*` avec credentials.
- **Limites** : taille de corps (`MAX_BODY_BYTES`), timeouts, rate limiting par IP et par identifiant sur `/auth/*` (plus strict sur login, register, forgot-password).
- **OpenAPI** désactivable en production (`DOCS_ENABLED`).
- Aucun détail interne dans les réponses (stack trace, SQL). Logs sans données personnelles superflues.
- **Validation de la configuration au démarrage** : refus de démarrer si `ENVIRONMENT=prod` avec un `JWT_SECRET` absent, < 32 octets ou égal à une valeur d'exemple.
- **JWT** : `alg=none` rejeté, algorithme fixé, `iss` et `aud` vérifiés.
- **Emails de test** : utiliser le domaine `example.com` (et ses sous-domaines). **Ne pas utiliser `.test`** : `email-validator` rejette ce domaine réservé.

| Variable | Rôle |
|---|---|
| `ENVIRONMENT` | `dev`, `test`, `prod` |
| `DATABASE_URL` | connexion PostgreSQL |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | initialisation de la base (Compose) |
| `JWT_SECRET`, `JWT_ISSUER`, `JWT_AUDIENCE` | signature et validation JWT |
| `ACCESS_TOKEN_TTL_MINUTES`, `REFRESH_TOKEN_TTL_DAYS` | durées de vie |
| `ARGON2_TIME_COST`, `ARGON2_MEMORY_KIB`, `ARGON2_PARALLELISM` | coût du hachage |
| `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCK_MINUTES` | verrouillage |
| `REQUIRE_VERIFIED_EMAIL` | exiger l'email vérifié au login |
| `CORS_ORIGINS` | origines autorisées (liste) |
| `TRUSTED_PROXIES` | CIDR autorisés à fournir `X-Forwarded-For` (vide = aucun) |
| `RATE_LIMIT_LOGIN`, `RATE_LIMIT_DEFAULT` | limites de débit |
| `MAX_BODY_BYTES` | taille maximale des corps |
| `DOCS_ENABLED` | exposer `/docs` et `/openapi.json` |
| `DEMO_PASSWORD` | mot de passe des comptes de démonstration |

---

## 11. Transactions et concurrence

- **Une unité de travail par requête** : session injectée, commit en fin de service, rollback sur exception.
- **Refresh** : charger la ligne avec `SELECT … FOR UPDATE` (un seul de deux refresh simultanés l'emporte). Sur réutilisation détectée, **commit la révocation de la famille avant de lever le 401**, sinon le rollback l'annule.
- **Dernier owner** : verrouiller (`FOR UPDATE`) les memberships `owner` actifs de l'organisation avant de vérifier la règle 6.
- **Invitation** : consommer par `UPDATE … SET accepted_at = :now WHERE id = :id AND accepted_at IS NULL RETURNING …` ; zéro ligne = déjà utilisée.
- **Audit des refus** : l'entrée d'audit d'un 403 est écrite dans sa propre transaction.

```python
# services/auth.py — rotation du refresh token
with uow.begin():
    row = repo.get_by_hash(sha256_hex(token), for_update=True)
    if row is None or row.expires_at <= clock.now():
        raise Unauthorized()
    if row.revoked_at is not None:
        if row.replaced_by_id is not None:           # réutilisation
            repo.revoke_family(row.family_id)
            audit.record(Action.REFRESH_REUSE_DETECTED, ...)
            uow.commit()                             # avant de lever
        raise Unauthorized()
    new = repo.create_session(family_id=row.family_id, user_id=row.user_id, ...)
    row.revoked_at, row.replaced_by_id = clock.now(), new.id
```

---

## 12. Format d'erreur

```json
{
  "error": {
    "code": "permission_denied",
    "message": "Vous n'avez pas la permission requise.",
    "request_id": "…",
    "details": null
  }
}
```

| HTTP | Codes `error.code` |
|---|---|
| 400 | `invitation_invalid`, `token_invalid` |
| 401 | `invalid_credentials`, `token_invalid`, `token_expired` |
| 403 | `permission_denied`, `privilege_escalation`, `email_not_verified`, `organization_inactive` |
| 404 | `not_found` (ressource absente **ou hors périmètre**) |
| 409 | `slug_taken`, `role_name_taken`, `already_member`, `last_owner`, `system_role_immutable`, `role_in_use` |
| 422 | `validation_error` (`details` = liste des champs en erreur, sans valeur sensible) |
| 429 | `rate_limited` (en-tête `Retry-After`) |
| 500 / 503 | `internal_error` / `service_unavailable` |

Les exceptions de domaine (`DomainError` et sous-classes) portent `code`, `http_status` et `message`. Un handler global convertit aussi les erreurs de validation FastAPI et les exceptions non gérées dans ce format. Toutes les réponses sont déclarées dans OpenAPI.

---

## 13. Tests

### Fixtures

- Client HTTPX et base PostgreSQL **réelle** isolée, réinitialisée entre les tests.
- Horloge contrôlable (section 2, règle 11) pour les expirations.
- Acteurs : PlatformAdmin, Owner, SecurityAdmin, Manager, Member ; deux organisations A et B avec projets ; un utilisateur membre des deux.
- Rôles et permissions seedés ; sessions active, expirée, révoquée ; invitations valide et expirée.
- Factories **déterministes** (graine fixe), données fictives uniquement (`example.com`).
- Argon2 allégé en test via la configuration.

### Scénarios d'acceptation obligatoires

Nomme chaque test `test_<ID>_<description>`. Chaque scénario est couvert par au moins un test d'intégration.

| ID | Scénario |
|---|---|
| ACC-01 | **Démo** : Manager crée un projet → 201 ; Member tente de le supprimer → 403 `permission_denied` ; Manager de A lit un projet de B → 404 |
| ACC-02 | Un refresh token déjà remplacé est rejoué → 401 et **toute la famille est révoquée** (le token récent échoue aussi) |
| ACC-03 | Après `logout`, l'access token émis avant est refusé immédiatement ; idem après `logout-all` et après `reset-password` |
| ACC-04 | Une permission retirée à un rôle est effective à la requête suivante avec le même access token |
| ACC-05 | Un membre suspendu perd l'accès immédiatement ; un membre ayant quitté aussi |
| ACC-06 | IDOR : substituer l'UUID d'un projet/membre/rôle d'une autre organisation → 404 |
| ACC-07 | SecurityAdmin tente d'accorder `organization:manage` à un rôle → 403 `privilege_escalation` |
| ACC-08 | Retrait du dernier owner (rôle, suspension, départ) → 409 `last_owner` ; transfert préalable → autorisé |
| ACC-09 | Deux acceptations simultanées de la même invitation : une seule réussit |
| ACC-10 | `UPDATE` et `DELETE` SQL sur `audit_logs` sont rejetés par la base |
| ACC-11 | Register, forgot-password et login : réponses identiques (statut et corps) pour compte existant et inexistant |
| ACC-12 | JWT : signature falsifiée, `alg=none`, mauvais `aud`, mauvais `iss`, expiré, `type` incorrect → 401 |
| ACC-13 | Rate limiting : dépassement sur `/auth/login` → 429 avec `Retry-After` ; verrouillage après N échecs |
| ACC-14 | PlatformAdmin non membre : 404 sur les projets d'une organisation ; 200 sur `GET /organizations/{id}` |
| ACC-15 | Assignation de masse : corps contenant `is_platform_admin`, `organization_id`, `created_by_id`, `is_system` → 422 |
| ACC-16 | Pagination : `limit=101`, `offset=-1`, filtre inconnu → 422 |
| ACC-17 | Règle 7 : attribuer un rôle personnalisé de A dans B → refusé |
| ACC-18 | Deux refresh simultanés avec le même token : un seul gagne |
| ACC-19 | Audit : une entrée par action du catalogue ; aucun secret ni email en clair dans `metadata` ; événements sans organisation visibles uniquement via AUD-02 |
| ACC-20 | Matrice rôle × endpoint : autorisé et refusé pour chacun des 5 acteurs sur toutes les routes protégées |

### Couverture

Objectif : **≥ 90 %** sur `services/` et `dependencies/`, **≥ 85 %** global (échec de la CI en dessous). La couverture ne prouve pas l'absence de vulnérabilités : ne le prétends jamais. Rapports XML et HTML publiés comme artefacts CI.

---

## 14. Docker et CI/CD

- **Dockerfile** : multi-stage, utilisateur non-root, pas de cache pip, `HEALTHCHECK`, aucun privilège superflu (annexe E).
- **docker-compose.yml** : `db` avec volume nommé et healthcheck ; `migrate` à usage unique ; `api` qui démarre après `migrate` terminé avec succès ; système de fichiers en lecture seule, `cap_drop: [ALL]`, `no-new-privileges`. Aucun secret en dur (annexe D).
- **GitHub Actions** : six jobs bloquants (`lint`, `typecheck`, `test`, `migrations`, `security`, `build`) ; permissions en lecture seule par défaut ; actions épinglées (annexe F). Le job `migrations` exécute `alembic upgrade head`, `alembic check` (aucune dérive modèle/migration) et un `downgrade -1` suivi d'un `upgrade head`.
- Le job `deploy` est **post-MVP** (section 19).

---

## 15. Documentation à produire (MVP)

| Livrable | Contenu |
|---|---|
| `README.md` public | présentation, fonctionnalités, schéma d'architecture, démarrage Docker, comptes de démonstration, commandes, scénario de démo, résultats de tests, limites connues |
| `docs/architecture.md` | diagrammes **Mermaid** : ERD ; séquences login / refresh-rotation / vérification de permission |
| `docs/threat-model.md` | actifs, acteurs, frontières de confiance, menaces (STRIDE), mesures, risques résiduels |
| `docs/owasp-api-top10.md` | une section par risque de l'édition en vigueur (à vérifier à la date de rédaction), mesure implémentée et test associé (IDs ACC-xx) |
| `docs/deployment.md` | variables d'environnement, secrets, migrations en production, sauvegarde/restauration PostgreSQL, retour arrière, politique de rétention |
| `docs/decisions/` | ADR : stack (0001), synchrone, algorithme JWT, écarts de la section 5, `sid` et révocation |
| `docs/PROGRESS.md` | journal d'avancement par phase |

**Scénario de démonstration** (`scripts/demo_scenario.sh`, annexe G) : login Manager → création de projet (**201**) → login Member → tentative de suppression (**403**) → accès à un projet de l'organisation B (**404**).

**Comptes de démonstration** (créés par `scripts/seed_demo.py`, tous vérifiés, mot de passe issu de `DEMO_PASSWORD`, jamais committé). Le script refuse de s'exécuter avec `ENVIRONMENT=prod` sauf option explicite `--force` :

| Compte | Rôle |
|---|---|
| `admin@example.com` | PlatformAdmin |
| `owner@acme.example.com` | owner de l'organisation `acme` |
| `secadmin@acme.example.com` | security_admin de `acme` |
| `manager@acme.example.com` | manager de `acme` |
| `member@acme.example.com` | member de `acme` |
| `owner@globex.example.com` | owner de l'organisation `globex` |
| `multi@example.com` | member de `acme` **et** de `globex` |

Chaque organisation reçoit deux projets (`acme` : Alpha, Beta ; `globex` : Gamma, Delta).

---

## 16. Plan d'exécution

| Phase | Contenu | Livrables | Porte de validation |
|---|---|---|---|
| 0 | Squelette : config, clock, logging, middlewares, erreurs, `/health`, `/ready`, Makefile, Compose (DB), CI minimale | `pyproject.toml`, `uv.lock`, `app/core/*`, `Makefile`, `.env.example`, ADR 0001 | `make check` vert ; `/health` testé |
| 1 | Modèles, contraintes, migrations, seed rôles/permissions, trigger d'audit | `app/models/*`, `migrations/*` | `alembic upgrade head` + `alembic check` ; tests d'intégrité (unicités, FK, trigger, ACC-10) |
| 2 | Authentification (AUTH-01 à 09) | services, routeurs, `EmailSender` | ACC-02, 03, 11, 12, 13 verts |
| 3 | Organisations, membres, invitations (ORG-01 à 10) | idem | ACC-05, 06, 09, 14 verts |
| 4 | RBAC : rôles et permissions (ROLE-01 à 08) | idem | ACC-04, 07, 08, 17 verts |
| 5 | Projets et statut plateforme (PRJ-01 à 05, PLT-01) | idem | ACC-01 vert |
| 6 | Audit : écriture, lecture filtrée, plateforme, masquage (AUD-01, 02) | idem | ACC-16, 19 verts |
| 7 | Durcissement : tests de sécurité, concurrence, matrice, couverture | `tests/security/*` | ACC-15, 18, 20 verts ; seuils de couverture atteints |
| 8 | Dockerfile, Compose complet, CI complète, seed et script de démo | annexes D, E, F, G | pipeline verte ; `make seed && make demo` OK |
| 9 | Documentation MVP et README public | section 15 | porte de release (section 17) |

Après chaque phase : commit, puis compte rendu dans `docs/PROGRESS.md`.

---

## 17. Porte de release du MVP

L'agent s'arrête ici et produit un compte rendu final. Tout point non coché est signalé.

- [ ] Les 37 endpoints du catalogue (section 9.1) sont implémentés et documentés dans OpenAPI, avec leurs erreurs.
- [ ] Les scénarios ACC-01 à ACC-20 passent.
- [ ] `make check` est vert ; couverture ≥ 90 % sur `services/` et `dependencies/`, ≥ 85 % global.
- [ ] `docker compose up` démarre une API migrée ; `make seed && make demo` réussit de zéro.
- [ ] La CI est verte : lint, types, tests, migrations, audit des dépendances, build et scan d'image.
- [ ] Aucun secret, mot de passe ou token en clair dans le dépôt, les logs ou l'audit (vérifié par un test et par une recherche dans l'historique Git).
- [ ] La documentation de la section 15 est complète et les limites connues sont listées.
- [ ] Aucune affirmation de « sécurité garantie » : le modèle de menace décrit ce qui est couvert **et** ce qui ne l'est pas.

---

## 18. Commandes de référence

```bash
cp .env.example .env            # puis renseigner les secrets
make up                         # docker compose up -d --build (db, migrate, api)
make seed                       # comptes et données de démonstration
make demo                       # scénario 201 / 403 / 404
make check                      # lint + typage + tests
alembic revision --autogenerate -m "message"
alembic upgrade head && alembic check
python scripts/create_platform_admin.py
```

---

## 19. Post-MVP et hors périmètre

**Post-MVP (phase 10, uniquement sur instruction explicite) :** collection Postman et environnement ; script `purge_retention.py` avec `--dry-run` et rôle DB dédié ; diagramme de classes UML ; démo hébergée avec comptes contrôlés ; job `deploy` conditionné à la réussite de tous les autres jobs ; procédure de retour arrière testée.

**Hors périmètre :** envoi d'emails réel (SMTP), authentification multifacteur, SSO/OAuth, changement d'email, interface front-end, facturation, multi-région, cache distribué.

**Limites à documenter :** rate limiting en mémoire non partagé entre instances ; emails écrits dans les logs (backend console) ; pas de MFA ; vérification du `sid` = une requête SQL supplémentaire par appel authentifié ; aucun audit de sécurité externe ni test d'intrusion.

---

# Annexes — squelettes de référence

> Ces fichiers sont des points de départ : adapte-les, épingle les versions, et fais-les passer par les portes de validation.

## A. `pyproject.toml` (extraits de configuration)

```toml
[project]
name = "secureapi-platform"
requires-python = ">=3.12"
dependencies = []   # à renseigner et épingler via uv

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "S", "SIM"]

[tool.ruff.lint.per-file-ignores]
"app/tests/**" = ["S101", "S105", "S106"]

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]
files = ["app"]

[tool.pytest.ini_options]
testpaths = ["app/tests"]
addopts = "--strict-markers -q"
markers = ["security: tests de sécurité", "concurrency: tests de concurrence"]

[tool.coverage.run]
source = ["app"]
branch = true

[tool.coverage.report]
fail_under = 85
show_missing = true

[tool.bandit]
exclude_dirs = ["app/tests"]
```

## B. `Makefile`

```make
.PHONY: install up down migrate lint typecheck test check seed demo

install: ; uv sync --frozen
up: ; docker compose up -d --build
down: ; docker compose down
migrate: ; docker compose run --rm migrate
lint: ; ruff check . && ruff format --check .
typecheck: ; mypy
test: ; pytest --cov --cov-report=term-missing --cov-report=xml --cov-report=html
check: lint typecheck test
seed: ; docker compose run --rm api python scripts/seed_demo.py
demo: ; bash scripts/demo_scenario.sh
```

## C. `.env.example`

```dotenv
ENVIRONMENT=dev
POSTGRES_USER=secureapi
POSTGRES_PASSWORD=
POSTGRES_DB=secureapi
DATABASE_URL=postgresql+psycopg://secureapi:<POSTGRES_PASSWORD>@db:5432/secureapi

# Générer : python -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET=
JWT_ISSUER=secureapi
JWT_AUDIENCE=secureapi-clients
ACCESS_TOKEN_TTL_MINUTES=15
REFRESH_TOKEN_TTL_DAYS=7

ARGON2_TIME_COST=3
ARGON2_MEMORY_KIB=65536
ARGON2_PARALLELISM=4
LOGIN_MAX_ATTEMPTS=5
LOGIN_LOCK_MINUTES=15
REQUIRE_VERIFIED_EMAIL=true

CORS_ORIGINS=http://localhost:3000
TRUSTED_PROXIES=
RATE_LIMIT_LOGIN=5/minute
RATE_LIMIT_DEFAULT=100/minute
MAX_BODY_BYTES=1048576
DOCS_ENABLED=true
DEMO_PASSWORD=
```

## D. `docker-compose.yml`

```yaml
services:
  db:
    image: postgres:16            # épingler la version mineure
    env_file: .env
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports: ["127.0.0.1:5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10

  migrate:
    build: .
    env_file: .env
    command: ["alembic", "upgrade", "head"]
    depends_on:
      db: { condition: service_healthy }
    restart: "no"

  api:
    build: .
    env_file: .env
    ports: ["8000:8000"]
    depends_on:
      db: { condition: service_healthy }
      migrate: { condition: service_completed_successfully }
    read_only: true
    tmpfs: ["/tmp"]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]

volumes:
  pgdata:
```

## E. `Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy PIP_NO_CACHE_DIR=1
COPY --from=ghcr.io/astral-sh/uv:<VERSION_ÉPINGLÉE> /uv /usr/local/bin/uv
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 --no-create-home appuser
WORKDIR /srv
COPY --from=build /opt/venv /opt/venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY app ./app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## F. `.github/workflows/ci.yml`

```yaml
name: ci
on:
  push: { branches: [main] }
  pull_request:
permissions:
  contents: read
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4          # épingler par SHA ou version vérifiée
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run ruff check . && uv run ruff format --check .

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run mypy

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_USER: ci, POSTGRES_PASSWORD: ci, POSTGRES_DB: ci }
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U ci" --health-interval 5s
          --health-timeout 3s --health-retries 10
    env:
      ENVIRONMENT: test
      DATABASE_URL: postgresql+psycopg://ci:ci@localhost:5432/ci
      JWT_SECRET: ci-only-secret-ci-only-secret-ci-only-secret
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run pytest --cov --cov-report=xml --cov-report=html
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: coverage, path: "coverage.xml\nhtmlcov/" }

  migrations:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_USER: ci, POSTGRES_PASSWORD: ci, POSTGRES_DB: ci }
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U ci" --health-interval 5s
          --health-timeout 3s --health-retries 10
    env:
      ENVIRONMENT: test
      DATABASE_URL: postgresql+psycopg://ci:ci@localhost:5432/ci
      JWT_SECRET: ci-only-secret-ci-only-secret-ci-only-secret
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run alembic upgrade head
      - run: uv run alembic check
      - run: uv run alembic downgrade -1 && uv run alembic upgrade head

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run pip-audit
      - run: uv run bandit -r app -c pyproject.toml

  build:
    runs-on: ubuntu-latest
    needs: [lint, typecheck, test, migrations, security]
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t secureapi:ci .
      - uses: aquasecurity/trivy-action@<VERSION_ÉPINGLÉE>
        with:
          image-ref: secureapi:ci
          severity: HIGH,CRITICAL
          exit-code: "1"
```

## G. `scripts/demo_scenario.sh`

```bash
#!/usr/bin/env bash
# Scénario : accès autorisé (201), refus de permission (403), accès inter-organisation (404).
set -euo pipefail
BASE="${BASE:-http://localhost:8000/api/v1}"
PW="${DEMO_PASSWORD:?DEMO_PASSWORD requis}"

json() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
login() {
  curl -sf -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$PW\"}" | json 'd["access_token"]'
}
org_id() {  # $1 = token, $2 = slug
  curl -sf "$BASE/organizations" -H "Authorization: Bearer $1" \
    | json "[o['id'] for o in d['items'] if o['slug']=='$2'][0]"
}
expect() {  # $1 = attendu, $2 = obtenu, $3 = libellé
  if [ "$1" = "$2" ]; then echo "OK   $3 ($2)"; else echo "FAIL $3 : attendu $1, obtenu $2"; exit 1; fi
}
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

MGR=$(login manager@acme.example.com)
MEM=$(login member@acme.example.com)
MULTI=$(login multi@example.com)
ORG_A=$(org_id "$MGR" acme)
ORG_B=$(org_id "$MULTI" globex)

# 1. Manager crée un projet -> 201
RESP=$(curl -s -w '\n%{http_code}' -X POST "$BASE/organizations/$ORG_A/projects" \
  -H "Authorization: Bearer $MGR" -H 'Content-Type: application/json' \
  -d '{"name":"Projet de démonstration"}')
expect 201 "$(echo "$RESP" | tail -n1)" "Manager crée un projet"
PROJ=$(echo "$RESP" | head -n1 | json 'd["id"]')

# 2. Member tente de supprimer -> 403
expect 403 "$(code -X DELETE "$BASE/organizations/$ORG_A/projects/$PROJ" -H "Authorization: Bearer $MEM")" \
  "Member tente de supprimer"

# 3. Manager de A tente de lire un projet de B -> 404
PROJ_B=$(curl -sf "$BASE/organizations/$ORG_B/projects" -H "Authorization: Bearer $MULTI" \
  | json 'd["items"][0]["id"]')
expect 404 "$(code "$BASE/organizations/$ORG_B/projects/$PROJ_B" -H "Authorization: Bearer $MGR")" \
  "Manager de A lit un projet de B"

echo "Scénario de démonstration réussi."
```
