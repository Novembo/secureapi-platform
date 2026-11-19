# ADR 0001 — Choix de la stack technique et architecture synchrone

- **Statut** : Accepté
- **Date** : 2026-11-18
- **Auteur** : SecureAPI Platform Team

## Contexte
La plateforme SecureAPI doit fournir une API REST multi-tenant sécurisée pour la gestion des organisations, membres, rôles (RBAC), invitations, projets et pistes d'audit immuables. Le système impose des garanties strictes de non-escalade de privilèges, d'isolation stricte entre organisations (anti-IDOR), et de gestion transactionnelle atomique des opérations multi-modèles et de révocation des sessions.

## Décisions

1. **Python 3.12+ & FastAPI**
   - FastAPI avec Pydantic v2 et `pydantic-settings` pour la validation stricte (`extra="forbid"`), la documentation OpenAPI automatique et les performances.
   - Validation d'emails avec `email-validator` (les domaines comme `example.com` sont utilisés, les TLDs non enregistrés comme `.test` sont évités).

2. **Exécution Synchrone (SQLAlchemy 2.0 sync & endpoints `def`)**
   - Le moteur relationnel, les verrous pessimistes (`SELECT ... FOR UPDATE`), les transactions complexes multi-tables (ex. révocation atomique de famille de sessions, anti-escalade) et les tests d'isolation sont nettement plus prévisibles, robustes et simples à vérifier formellement en mode synchrone qu'en mode asynchrone (évite les pièges de concurrence event loop et les complexités de session context-vars).

3. **Base de données & Driver**
   - PostgreSQL 16 avec driver moderne `psycopg` (v3), support natif des UUID, JSONB et triggers d'immuabilité SQL.

4. **Authentification & Cryptographie**
   - **Argon2id** (`argon2-cffi`) pour le hachage des mots de passe des utilisateurs, avec paramètres configurables (réduits en environnement de test pour accélérer la suite de tests).
   - **PyJWT** (algorithme `HS256` fixé côté serveur, secret ≥ 32 octets, validation stricte de `iss`, `aud`, `sub`, `sid`, `exp`, `jti`, et rejet formel de `alg=none`).
   - Hachage rapide SHA-256 hexadécimal pour les tokens d'invitation, refresh tokens et email tokens (entropie élevée de 48 octets générés par `secrets.token_urlsafe(48)`).

5. **Rate Limiting**
   - `slowapi` en mémoire avec clé basée sur l'IP résolue (en tenant compte de `TRUSTED_PROXIES` pour `X-Forwarded-For`).

6. **Outillage & Qualité**
   - Gestionnaire de paquets `uv` avec fichier `uv.lock`.
   - Linter/formateur `Ruff`, typage statique strict `mypy` sur `app/`.
   - Sécurité : `pip-audit`, `Bandit`, `Trivy`.
   - Tests : `pytest`, `pytest-cov`, `HTTPX`.

## Conséquences
- Architecture claire et lisible sans complexité async inutile.
- Garanties transactionnelles ACID fortes sur chaque requête.
- Dépendances verrouillées et reproductibilité assurée.
