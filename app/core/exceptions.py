from typing import Any


class DomainError(Exception):
    """Base class for all domain/business exceptions."""

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = 400,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details
        self.headers = headers or {}


# 400
class InvitationInvalidError(DomainError):
    def __init__(
        self, message: str = "L'invitation est invalide, expirée ou déjà utilisée."
    ) -> None:
        super().__init__(code="invitation_invalid", message=message, http_status=400)


class TokenInvalid400Error(DomainError):
    def __init__(self, message: str = "Le jeton fourni est invalide ou expiré.") -> None:
        super().__init__(code="token_invalid", message=message, http_status=400)


# 401
class InvalidCredentialsError(DomainError):
    def __init__(self, message: str = "Identifiants invalides.") -> None:
        super().__init__(code="invalid_credentials", message=message, http_status=401)


class TokenInvalidError(DomainError):
    def __init__(self, message: str = "Jeton d'accès invalide.") -> None:
        super().__init__(code="token_invalid", message=message, http_status=401)


class TokenExpiredError(DomainError):
    def __init__(self, message: str = "Jeton expiré.") -> None:
        super().__init__(code="token_expired", message=message, http_status=401)


# 403
class PermissionDeniedError(DomainError):
    def __init__(self, message: str = "Vous n'avez pas la permission requise.") -> None:
        super().__init__(code="permission_denied", message=message, http_status=403)


class PrivilegeEscalationError(DomainError):
    def __init__(self, message: str = "Tentative d'escalade de privilèges non autorisée.") -> None:
        super().__init__(code="privilege_escalation", message=message, http_status=403)


class EmailNotVerifiedError(DomainError):
    def __init__(self, message: str = "Adresse email non vérifiée.") -> None:
        super().__init__(code="email_not_verified", message=message, http_status=403)


class OrganizationInactiveError(DomainError):
    def __init__(self, message: str = "L'organisation est désactivée.") -> None:
        super().__init__(code="organization_inactive", message=message, http_status=403)


# 404
class NotFoundError(DomainError):
    def __init__(self, message: str = "Ressource introuvable.") -> None:
        super().__init__(code="not_found", message=message, http_status=404)


# 409
class SlugTakenError(DomainError):
    def __init__(self, message: str = "Ce slug d'organisation est déjà utilisé.") -> None:
        super().__init__(code="slug_taken", message=message, http_status=409)


class RoleNameTakenError(DomainError):
    def __init__(self, message: str = "Un rôle portant ce nom existe déjà.") -> None:
        super().__init__(code="role_name_taken", message=message, http_status=409)


class AlreadyMemberError(DomainError):
    def __init__(self, message: str = "Cet utilisateur est déjà membre de l'organisation.") -> None:
        super().__init__(code="already_member", message=message, http_status=409)


class LastOwnerError(DomainError):
    def __init__(
        self,
        message: str = (
            "Impossible de retirer, suspendre ou supprimer le dernier propriétaire actif."
        ),
    ) -> None:
        super().__init__(code="last_owner", message=message, http_status=409)


class SystemRoleImmutableError(DomainError):
    def __init__(
        self,
        message: str = "Les rôles système ne peuvent pas être modifiés ou supprimés.",
    ) -> None:
        super().__init__(code="system_role_immutable", message=message, http_status=409)


class RoleInUseError(DomainError):
    def __init__(
        self,
        message: str = "Ce rôle est actuellement attribué à un ou plusieurs membres.",
    ) -> None:
        super().__init__(code="role_in_use", message=message, http_status=409)


# 422
class ValidationError(DomainError):
    def __init__(
        self, message: str = "Erreur de validation des données.", details: Any = None
    ) -> None:
        super().__init__(code="validation_error", message=message, http_status=422, details=details)


# 429
class RateLimitedError(DomainError):
    def __init__(
        self,
        retry_after: int = 60,
        message: str = "Trop de requêtes. Veuillez réessayer plus tard.",
    ) -> None:
        super().__init__(
            code="rate_limited",
            message=message,
            http_status=429,
            headers={"Retry-After": str(retry_after)},
        )


# 503
class ServiceUnavailableError(DomainError):
    def __init__(self, message: str = "Service temporairement indisponible.") -> None:
        super().__init__(code="service_unavailable", message=message, http_status=503)
